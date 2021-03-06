import os
import sys
import csv
import time
import pandas
import random
import datetime
import numpy as np
from tqdm import tqdm
import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from sklearn.metrics import r2_score
import matplotlib.pyplot as plt
from pandarallel import pandarallel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataloader import load_data_new
import utils

class Small_CNN(nn.Module):
    '''
    Sentinel-2 CNN
    '''
    def __init__(self, num_bands, device = "cpu"):
        super(Small_CNN, self).__init__()

        in_channels = num_bands 
        out_channels1 = 64
        out_channels2 = 128
        out_channels3 = 256
        out_channels4 = 256

        self.device = device
        
        self.conv1 = nn.Conv2d(in_channels, out_channels1, kernel_size=5, stride=1, padding=1)
        self.bn1 = nn.BatchNorm2d(out_channels1)
        self.pool1 = nn.MaxPool2d(kernel_size=3, stride=3)
        self.conv2 = nn.Conv2d(out_channels1, out_channels2, kernel_size=3, stride=1, padding=1)
        self.bn2 = nn.BatchNorm2d(out_channels2)
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.conv3 = nn.Conv2d(out_channels2, out_channels3, kernel_size=3, stride=1, padding=1)
        self.bn3 = nn.BatchNorm2d(out_channels3)
        self.pool3 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.conv4 = nn.Conv2d(out_channels3, out_channels4, kernel_size=3, stride=1, padding=1)
        self.bn4 = nn.BatchNorm2d(out_channels4)
        self.pool4 = nn.MaxPool2d(kernel_size=2, stride=2)
        
        self.drop = nn.Dropout(p=0.5)
        self.fc1 = nn.Linear(256 * 8 * 8, 4000)
        self.fc2 = nn.Linear(4000, 100)
        self.fc3 = nn.Linear(100, 1) 

    def forward(self, x):
        
        x = self.conv1(x)
        x = F.relu(self.bn1(x))
        x = self.pool1(x)
        x = self.conv2(x)
        x = F.relu(self.bn2(x))
        x = self.pool2(x)
        x = self.conv3(x)
        x = F.relu(self.bn3(x))
        x = self.pool3(x)
        x = self.conv4(x)
        x = F.relu(self.bn4(x))
        x = self.pool4(x)        
        x = self.drop(x)
        x = x.reshape(x.size(0), 256 * 8 * 8) 
        x = F.relu(self.fc1(x))
        embed = self.fc2(x)
        x = F.relu(embed)
        x = self.fc3(x)
        x = x.reshape(-1)
        
        return x,embed
    
    def init_weights(self, m):
        if type(m) == nn.Conv2d or type(m) == nn.Linear:
            nn.init.kaiming_uniform_(m.weight, nonlinearity='relu')
            m.bias.data.fill_(0.01)
            
    def _set_seeds(self, seed):
        ''' Sets the seeds of various libraries '''
        if self.device == "cuda:0":
            torch.cuda.manual_seed(seed)
        else:
            torch.manual_seed(seed)
        random.seed(seed)
        np.random.seed(seed)
        
        
def train(model, optimizer, loss_fn, dataloader, batch_size, epoch, scheduler=None):
    '''
    Trains the model for 1 epoch on all batches in the dataloader.
    '''
    summaries  = []
    num_batches = len(dataloader)
    train_dataset_size = num_batches * batch_size
    
    # Set model to train mode
    model.train()
   
    print("Training for one epoch on {} batches.".format(num_batches))
          
    with tqdm(total=num_batches) as t:
        
        for i, sample in enumerate(dataloader):

            indices, inputs, features, labels = sample['index'], sample['image'], sample['non_image'], sample['label']
            sites, dates, states = sample['site'], sample['month'], sample['state']
            
            # Move to GPU if available       
            inputs = inputs.to(model.device, dtype=torch.float)
            labels = labels.to(model.device, dtype=torch.float)

            # Forward pass and calculate loss
            outputs,_ = model(inputs)
            loss = loss_fn(outputs, labels)

            # Compute gradients and perform parameter updates
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
                
            # Move to cpu and convert to numpy
            outputs = outputs.data.cpu().numpy()
            labels = labels.data.cpu().numpy()
            indices = indices.data.cpu().numpy()
            sites, dates = sites.data.cpu().numpy(), dates.data.cpu().numpy()
            
            # Compute batch metrics
            r2 = r2_score(labels, outputs) 
            summary_batch = {'average r2': r2, 'average MSE loss': loss.item()}
            summaries.append(summary_batch)
            
            # Display batch loss and r2
            loss_str = '{:05.3f}'.format(loss.item())
            r2_str = '{:01.3f}'.format(r2)
            t.set_postfix(loss=loss_str, r2=r2_str) 
            t.update()
            
            if epoch % 20 == 0:
            # Save predictions to compute r2 over full dataset
                curr_batch_size = outputs.shape[0]  
                utils.save_predictions(indices, outputs, labels, sites, dates, states, curr_batch_size, 
                                       "predictions/repaired/cnn_train_preds_epoch_" + str(epoch) + ".csv") 
         
            del inputs, labels, outputs
            torch.cuda.empty_cache()
            
    # Save metrics
    mean_metrics = {metric: np.mean([x[metric] for x in summaries]) for metric in summaries[0]} 
    metrics_string = " ; ".join("{}: {:05.3f}".format(k, v) for k, v in mean_metrics.items())
    print("Train metrics: {}".format(metrics_string))

    return mean_metrics


def evaluate(model, loss_fn, dataloader, batch_size, epoch):
    '''
    Evaluates the model for 1 epoch on all batches in the dataloader.
    '''
    # Set model to eval mode
    model.eval()
   
    summaries = []
    num_batches = len(dataloader)
    val_dataset_size = num_batches * batch_size
    
    print("Evaluating on {} batches".format(num_batches))
    
    with tqdm(total=num_batches) as t:

        with torch.no_grad():
            for i, sample in enumerate(dataloader):

                indices, inputs, features, labels = sample['index'], sample['image'], sample['non_image'], sample['label']
                sites, dates, states = sample['site'], sample['month'], sample['state']
    
                # Move to GPU if available       
                inputs = inputs.to(model.device, dtype=torch.float)
                labels = labels.to(model.device, dtype=torch.float)

                # Forward pass and calculate loss
                outputs,_ = model(inputs)
                loss = loss_fn(outputs, labels)

                # Move to cpu and convert to numpy
                outputs = outputs.data.cpu().numpy()
                labels = labels.data.cpu().numpy()
                indices = indices.data.cpu().numpy()
                sites, dates = sites.data.cpu().numpy(), dates.data.cpu().numpy()

                # Save predictions to compute r2 over full dataset
                curr_batch_size = outputs.shape[0]  
                utils.save_predictions(indices, outputs, labels, sites, dates, states, curr_batch_size, 
                                       "predictions/repaired/cnn_val_preds_epoch_" + str(epoch) + ".csv") 
 
                # Save metrics
                r2 = r2_score(labels, outputs) 
                summary_batch = {'average r2': r2, 'average MSE loss': loss.item()}
                summaries.append(summary_batch)

                # Display batch loss and r2
                loss_str = '{:05.3f}'.format(loss.item())
                r2_str = '{:01.3f}'.format(r2)
                t.set_postfix(loss=loss_str, r2=r2_str) 
                t.update()
                
                del inputs, labels, outputs
                torch.cuda.empty_cache()

    mean_metrics = {metric: np.mean([x[metric] for x in summaries]) for metric in summaries[0]}    
    metrics_string = " ; ".join("{}: {:05.3f}".format(k, v) for k, v in mean_metrics.items())
    print("Evaluation metrics: {}".format(metrics_string))
    
    return mean_metrics


def train_and_evaluate(model, optimizer, loss_fn, train_dataloader, val_dataloader, 
                       batch_size, num_epochs, num_train, model_dir=None, saved_weights_file=None):
    '''
    Trains the model and evaluates at every epoch
    '''

    best_val_r2 = -1.0
    all_train_losses, all_val_losses, all_train_r2, all_val_r2 = [], [], [], []
    
    # If a saved weights file for the model is specified, reload the weights
    if model_dir is not None and saved_weights_file is not None:
        saved_weights_path = os.path.join(model_dir, saved_weights_file + '.pth.tar')
        utils.load_checkpoint(saved_weights_path, model, optimizer)
        print("Restoring parameters from {}".format(saved_weights_path))
    
    for epoch in range(num_epochs):
        
        print("Running Epoch {}/{}".format(epoch, num_epochs))
              
        # Train on all batches
        train_mean_metrics = train(model, optimizer, loss_fn, train_dataloader, batch_size, epoch)

        # Evaluate on validation set
        val_mean_metrics = evaluate(model, loss_fn, val_dataloader, batch_size, epoch)
        
        # Save losses and r2 from this epoch
        all_train_losses.append(train_mean_metrics['average MSE loss'])
        all_val_losses.append(val_mean_metrics['average MSE loss'])
        all_train_r2.append(train_mean_metrics['average r2'])
        all_val_r2.append(val_mean_metrics['average r2'])
    
        val_r2 = val_mean_metrics['average r2']
        is_best = val_r2 > best_val_r2
        
        # Save current model weights from this epoch
        utils.save_checkpoint({'epoch': epoch + 1, 'state_dict': model.state_dict(),
                               'optim_dict': optimizer.state_dict()},
                              is_best=is_best, checkpoint=model_dir)

        # If best_eval, save to best_save_path
        if is_best:
            best_val_r2 = val_r2
            print("Found new best R2 value of {}. Saving to checkpoint directory {}.".format(best_val_r2, model_dir))

            # Save best val metrics in a json file in the model directory
            best_json_path = os.path.join(model_dir, "metrics_val_best_weights_regression_unbal.json")
            utils.save_dict_to_json(val_mean_metrics, best_json_path)
        
        if epoch % 10 == 0:
            print("Train losses: {} \n Validation losses: {}".format(all_train_losses, all_val_losses))
            print("Train mean R2s: {} \n Validation mean R2s: {}".format(all_train_r2, all_val_r2))
            
            
    print("Train losses: {} ".format(all_train_losses))
    print("Val losses: {} ".format(all_val_losses))
    print("Train average r2s: {}".format(all_train_r2))
    print("Val average r2s: {}".format(all_val_r2))
    
    utils.plot_losses(all_train_losses, all_val_losses, num_epochs, num_train, save_as="plots/loss_cnn_"+str(num_train)+".png")
    utils.plot_r2(all_train_r2, all_val_r2, num_epochs, num_train, save_as="plots/r2_cnn_"+str(num_train)+".png")
                
    # Return train and eval metrics
    return train_mean_metrics, val_mean_metrics


def predict(model, loss_fn, dataloader, batch_size, num_epochs, 
            dataset='val', model_dir=None, saved_weights_file=None):
    
    # If a saved weights file for the model is specified, reload the weights
    if model_dir is not None and saved_weights_file is not None:
        saved_weights_path = os.path.join(model_dir, saved_weights_file + '.pth.tar')
        utils.load_checkpoint(saved_weights_path, model)
        print("Restoring parameters from {}".format(saved_weights_path))

    # Evaluate on validation or test set
    epoch = "final"
    mean_metrics = evaluate(model, loss_fn, dataloader, batch_size, epoch)
    r2 = mean_metrics['average r2']
    print("Mean R2 for {} dataset: {}".format(dataset, r2))
    

def run_train():
    '''
    Runs the whole training process.
    '''
    
    npy_dir = utils.SENTINEL_FOLDER 
    #train_csv = os.path.join(utils.PROCESSED_DATA_FOLDER, "train_sites_master_csv_2016_2017.csv")   
    #val_csv = os.path.join(utils.PROCESSED_DATA_FOLDER, "val_sites_master_csv_2016_2017.csv")
    test_csv = os.path.join(utils.PROCESSED_DATA_FOLDER, "test_sites_master_csv_2016_2017.csv")
    checkpt_dir = "checkpoints/sentinel_cnn/repaired/"
    
    train_repaired = os.path.join(utils.PROCESSED_DATA_FOLDER, "train_repaired_suff_stats_cloud_remove_2016.csv")
    val_repaired = os.path.join(utils.PROCESSED_DATA_FOLDER, "val_repaired_suff_stats_cloud_remove_2016.csv")

    lr = 0.00001
    reg = 1e-5
    batch_size = 90
    num_epochs = 30 
    num_train = 12761 #103604 #107376 
    num_sent_bands = 13
    
    print("Training model for {} epochs with batch size = {}, lr = {}, reg = {}.".format(num_epochs, batch_size, lr, reg))
   
    dataloaders = load_data_new(train_repaired, batch_size = batch_size, 
                                sample_balanced=False, num_workers=8,
                                train_images=npy_dir, val_images=npy_dir, 
                                val_nonimage_csv=val_repaired,
                                num_sent_bands=num_sent_bands,
                                stats_in_csv=True)  
    
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = Small_CNN(num_bands=num_sent_bands, device=device)
    model.to(device)

    model._set_seeds(0)
    model.apply(model.init_weights)
    optimizer = optim.Adam(model.parameters(), lr = lr, weight_decay=reg)
        
    train_and_evaluate(model, optimizer, nn.MSELoss(), dataloaders['train'], dataloaders['val'], 
                       batch_size=batch_size, num_epochs=num_epochs, num_train=num_train, 
                       model_dir = checkpt_dir)
    
    
def run_test():
    '''
    Runs final evaluation on the test set.   
    '''
 
    npy_dir = utils.SENTINEL_FOLDER 
    train_csv = os.path.join(utils.PROCESSED_DATA_FOLDER, "train_sites_master_csv_2016_2017.csv")   
    test_csv = os.path.join(utils.PROCESSED_DATA_FOLDER, "test_sites_master_csv_2016_2017.csv")
    checkpt_dir = "checkpoints/sentinel_cnn/"    
    
    lr = 0.00001
    reg = 1e-5
    batch_size = 64
    num_epochs = 100 
    num_train = 308132 
    
    dataloaders = load_data_new(train_csv, batch_size = batch_size, 
                                sample_balanced=False, num_workers=8,
                                train_images=npy_dir, test_images=npy_dir, 
                                test_nonimage_csv=test_csv)    
    
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = Small_CNN(device)
    model.to(device)

    model._set_seeds(0)
    model.apply(model.init_weights)
    optimizer = optim.Adam(model.parameters(), lr = lr, weight_decay=reg)
    
    predict(model, nn.MSELoss(), dataloaders['test'], batch_size, num_epochs, 
            dataset='test', model_dir=checkpt_dir, saved_weights_file="best_weights")
    
    
if __name__ == "__main__":
    
    run_train()
    ## run_test()
    
    
  
