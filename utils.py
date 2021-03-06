import os
import ast
import csv
import json
import shutil
import torch
import yaml
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import torch.nn as nn
from sklearn.metrics import r2_score
from pandarallel import pandarallel 
from scipy.stats.stats import pearsonr

HOME_FOLDER = os.path.expanduser("~")
REPO_NAME = "cs325b-airquality" #"es262-airquality"
BUCKET_FOLDER = os.path.join(HOME_FOLDER, REPO_NAME)
DATA_FOLDER = os.path.join(BUCKET_FOLDER, "data")
EPA_FOLDER = os.path.join(DATA_FOLDER, "epa")
GHCND_BASE_FOLDER = os.path.join(DATA_FOLDER, "GHCND_weather")
GHCND_DATA_FOLDER = os.path.join(GHCND_BASE_FOLDER, "ghcnd_hcn")
MODIS_FOLDER = os.path.join(DATA_FOLDER, "modis")
SENTINEL_FOLDER = os.path.join(DATA_FOLDER, "sentinel")
SENTINEL_METADATA_FOLDER = os.path.join(DATA_FOLDER, "Metadata")
PROCESSED_DATA_FOLDER = os.path.join(DATA_FOLDER, "processed_data")


def get_epa(epa_directory, year = '2016'):
    """
    Gathers all the EPA csv files for a given year
    located in the directory referenced by epa_directory.
    
    Loads into one dataframe and returns this aggregated dataframe. 
    """
    files = os.listdir(epa_directory)
    first_file = True
    for file in files:
        if file[-8:]== year + ".csv" or year == "any":
            file_path = os.path.join(epa_directory, file)
            new_df = pd.read_csv(file_path)
            if not first_file:
                df = df.append(new_df,ignore_index=True)
            else:
                df = new_df
                first_file = False
    return df

def load_csv_dfs(folder_path, blacklist = [], excluded_years = []):
    """
    Loads all .csv files from the specified folder and concatenates into one
    giant Pandas dataframe. Potential extension to different file types if we
    need it.
    
    Parameters
    ----------
    folder_path : str
        Path to the folder from which to read .csv files.
    blacklist : list[str]
        List of filenames to ignore.
    
    Returns
    -------
    df : pandas.DataFrame
        DataFrame for all of the .csv files in the specified folder.
    """
    df_list = []
    for filename in os.listdir(folder_path):
        file, ext = os.path.splitext(filename)
        if ext != ".csv" or filename in blacklist:
            continue
        if int(file[-4:]) in excluded_years:
            continue
        file_path = os.path.join(folder_path, filename)
        df = pd.read_csv(file_path)
        if "Weather Station ID" in df.columns:
            df = df.drop("Weather Station ID", axis=1)
        df_list.append(df)
    return pd.concat(df_list)

def read_yaml(yaml_file):
    yaml_data = None
    print("Loading yaml data from {}".format(os.path.abspath(yaml_file)))
    with open(yaml_file, 'r') as input_file:
        yaml_data = yaml.load(input_file, Loader=yaml.Loader)
    return yaml_data

def get_directory_paths(folder_path):
    """
    Returns absolute paths to directories in the folder, excluding "." and "..".

    Parameters
    ----------
    folder : str
        Absolute path of the folder to search through.

    Returns
    -------
    directories : list
        List of absolute paths of directories contained within the folder.
    """

    directories = next(os.walk(folder_path))[1]
    
    # omit hidden folders (ones starting with .)
    directories = filter(lambda name : not name.startswith("."), directories)
    return [os.path.join(folder_path, directory) for directory in directories]

def flatten(l):
    return [num for item in l for num in (item if isinstance(item, list) else (item,))]

def clean_df(df):
    '''
    Method to clean the given dataframe. Filters out examples with null min/max 
    temperatures and null precipitation. Keeps example with null snowfall/snow depth
    but replaces null values with marker values of -1. Also removes examples missing
    the matching Sentinel image.
    '''
    df = df[df['TMAX'].notnull()]
    df = df[df['TMIN'].notnull()]
    df['PRCP'].fillna(-1,inplace=True)
    df['SNOW'].fillna(-1,inplace=True)
    df['SNWD'].fillna(-1,inplace=True)
    df = df[df['PRCP']>-1]
    df = df[df['SENTINEL_INDEX'].notnull()]
    df = df[df['SENTINEL_INDEX'] != -1]
    
    # Fix indexing
    df = df.rename(columns={'Unnamed: 0': 'Index'}) 
    
    return df

def get_epa_features(row, filter_empty_temp=True):
    '''
    Method that retrieves the 16 Non-Sentinel features from the given row from the master df, including:
    lat, lon, month, 4 center blue Modis AOD pixels, 4 center green Modis AOD pixels, precipitation,
    snow fall, snow depth, min temperature, and max temperature.
    '''
    date = pd.to_datetime(row['Date'])
    month = date.month
    X = np.array([row['SITE_LATITUDE'],row['SITE_LONGITUDE'], month,
                  row['Blue [0,0]'],row['Blue [0,1]'], row['Blue [1,0]'], row['Blue [1,1]'],
                  row['Green [0,0]'],row['Green [0,1]'], row['Green [1,0]'], row['Green [1,1]'],
                  row['PRCP'], row['SNOW'], row['SNWD'], row['TMAX'], row['TMIN']])
    y = np.array(row['Daily Mean PM2.5 Concentration'])
    return X, y

def get_epa_features_no_weather(row, filter_empty_temp=True):
    '''
    Method that gets Non-Sentinel features from the given row from the master df, excluding all weather 
    features.  Includes:    lat, lon, month, 4 center blue AOD pixels, 4 center green AOD pixels.
    '''
    date = pd.to_datetime(row['Date'])
    month = date.month
    X = np.array([row['SITE_LATITUDE'],row['SITE_LONGITUDE'], month,
                  row['Blue [0,0]'],row['Blue [0,1]'], row['Blue [1,0]'], row['Blue [1,1]'],
                  row['Green [0,0]'],row['Green [0,1]'], row['Green [1,0]'], row['Green [1,1]']])
    y = np.array(row['Daily Mean PM2.5 Concentration'])
    return X, y

def get_epa_features_no_snow(row, filter_empty_temp=True):
    '''
    Method that gets Non-Sentinel features from the given row from the master df, excluding all two snow 
    features.  Includes:  lat, lon, month, 4 center blue AOD pixels, 4 center green AOD pixels, precipitation,
    min. temp, max temp.
    '''
    date = pd.to_datetime(row['Date'])
    month = date.month
    X = np.array([row['SITE_LATITUDE'],row['SITE_LONGITUDE'], month,
                  row['Blue [0,0]'],row['Blue [0,1]'], row['Blue [1,0]'], row['Blue [1,1]'],
                  row['Green [0,0]'],row['Green [0,1]'], row['Green [1,0]'], row['Green [1,1]'],
                  row['PRCP'], row['TMAX'], row['TMIN']])

    y = np.array(row['Daily Mean PM2.5 Concentration'])
    return X, y


def remove_partial_missing_modis(df):
    '''
    Given a df, removes the entries with any missing modis values
    '''
    df = df[df['Blue [0,0]'] != -1]
    df = df[df['Blue [0,1]'] != -1]
    df = df[df['Blue [1,0]'] != -1]
    df = df[df['Blue [1,1]'] != -1]
    df = df[df['Green [0,0]'] != -1]
    df = df[df['Green [0,1]'] != -1]
    df = df[df['Green [1,0]'] != -1]
    df = df[df['Green [1,1]'] != -1]

    return df

def remove_full_missing_modis(df):
    ''' 
    Given a df, removes the entries with fully missing modis values
    (i.e. all 8 pixel values are missing) 
    '''
    df = df[(df['Blue [0,0]'] != -1) 
            & (df['Blue [0,1]'] != -1)
            & (df['Blue [1,0]'] != -1)
            & (df['Blue [1,1]'] != -1)
            & (df['Green [0,0]'] != -1)
            & (df['Green [0,1]'] != -1)
            & (df['Green [1,0]'] != -1)
            & (df['Green [1,1]'] != -1 )]
    
    return df
        
    
def remove_missing_sent(full_df):
    ''' 
    Given the full dataframe, removes the datapoints with corrupted sentinel files.
    The list of corrupted sentinel files to remove is given in file 
    "final_sent_mismatch.csv". 
    '''

    to_remove_csv = "data_csv_files/final_sent_mismatch.csv"
    to_remove_df = pd.read_csv(to_remove_csv)
    to_remove_df = to_remove_df.rename(columns={"0": "Filename"})
   
    print("Removing {} files from original df of length {}".format(len(to_remove_df), len(full_df)))

    # Should probably be able to hit this with an apply, but leaving for now
    for i, row in to_remove_df.iterrows():
        bad_file = row['Filename']
        full_df = full_df[full_df['SENTINEL_FILENAME'] != bad_file]
   
    print("After removing files, df of length {}".format(len(full_df)))

    return full_df


def remove_sent_and_save_df_to_csv(load_from_csv_filename, save_to_csv_filename):
    ''' 
    Given a .csv of the df of current datapoints, loads the df, then
    removes the missing sentinel from the updated bad-file list, and
    resaves to a .csv for later use.
    '''
    df = pd.read_csv(load_from_csv_filename)
    df = remove_missing_sent(df)
    df.to_csv(save_to_csv_filename)
    
    
    
def load_sentinel_npy_files(epa_row, npy_files_dir_path):
    ''' 
    Reads in a sentinel.npy file which is a (h, w, 13) tensor of the sentinel image 
    for the day specified by the 'SENTINEL_INDEX' in epa_row.
    '''
    original_tif_filename = str(epa_row['SENTINEL_FILENAME'])
    index_in_original_tif =  int(epa_row['SENTINEL_INDEX'])
    npy_filename = original_tif_filename[:-4] + '_' + str(index_in_original_tif) + '.npy'
    full_npy_path = npy_files_dir_path + npy_filename
    img = np.load(full_npy_path)
    return img
 
    
def get_PM_from_row(row):
    '''
    Given a row in a df, returns the PM2.5 concentration. 
    To be used with pandarallel parallel_apply().
    '''
    pm_val =  float(row['Daily Mean PM2.5 Concentration'])
    return pm_val


def get_month(row):
    date = pd.to_datetime(row['Date'])
    month = date.month
    return month


def save_dict_to_json(d, json_path):
    '''
    Saves dict of floats in json file
    Args:
        d: (dict) of float-castable values (np.float, int, float, etc.)
        json_path: (string) path to json file
    '''
    with open(json_path, 'w') as f:
        # We need to convert the values to float for json (it doesn't accept np.array, np.float, )
        d = {k: float(v) for k, v in d.items()}
        json.dump(d, f, indent=4)

        
def save_checkpoint(state, is_best, checkpoint):
    '''
    Saves model and training parameters at checkpoint + 'last.pth.tar'. If is_best==True, also saves
    checkpoint + 'best.pth.tar'
    Args:
        state: (dict) contains model's state_dict, may contain other keys such as epoch, optimizer 
        is_best: (bool) True if it is the best model seen till now
        checkpoint: (string) folder where parameters are to be saved
    '''
    
    filepath = os.path.join(checkpoint, 'last_weights_3_20.pth.tar')
    if not os.path.exists(checkpoint):
        print("Checkpoint Directory does not exist! Making directory {}".format(checkpoint))
        os.mkdir(checkpoint)
    torch.save(state, filepath)
    if is_best:
        shutil.copyfile(filepath, os.path.join(checkpoint, 'best_weights_3_20.pth.tar'))

        
def load_checkpoint(checkpoint, model, optimizer=None):
    '''
    Loads model parameters (state_dict) from file_path. If optimizer is provided, loads state_dict of
    optimizer assuming it is present in checkpoint.
    Args:
        checkpoint: (string) filename which needs to be loaded
        model: (torch.nn.Module) model for which the parameters are loaded
        optimizer: (torch.optim) optional: resume optimizer from checkpoint
    '''
    if not os.path.exists(checkpoint):
        print("File doesn't exist {}".format(checkpoint))
        return 
    checkpoint = torch.load(checkpoint)
    model.load_state_dict(checkpoint['state_dict'])

    if optimizer:
        optimizer.load_state_dict(checkpoint['optim_dict'])

    return checkpoint


def plot_losses(train_losses, val_losses, num_epochs, num_ex, save_as):
    '''
    Method to plot train and validation losses over num_epochs epochs.
    '''
    plt.clf()
    plt.plot(range(0, num_epochs), train_losses, label='train')
    plt.plot(range(0, num_epochs), val_losses, label='val')
    plt.legend(loc=2)
    plt.xlabel("Epoch")
    plt.ylabel("MSE Loss")
    plt.title("Average MSE Loss of " + str(num_ex) + " over " + str(num_epochs) + " epochs.")
    plt.show()
    plt.savefig(save_as)
                                            
def plot_r2(train_r2, val_r2, num_epochs, num_ex, save_as):
    '''
    Method to plot train and validation r2 values over num_epochs epochs.
    '''
    plt.clf()
    plt.plot(range(0, num_epochs), train_r2, label = 'train')
    plt.plot(range(0, num_epochs), val_r2, label = 'val')
    plt.axis([0, num_epochs, -0.2, 1])
    plt.legend(loc=2)
    plt.title("Average R2 of " + str(num_ex) + " over " + str(num_epochs) + " epochs.")
    plt.xlabel("Epoch")
    plt.ylabel("R2")
    plt.show()
    plt.savefig(save_as)
    
        
def save_predictions(indices, predictions, labels, sites, dates, states, batch_size, save_to):
    '''
    Method to save indices, labels, and predictions of a given batch. 
    All batches over entire epoch will be saved to the same file,
    so that each .csv file has the predictions over all samples.
    '''
    with open(save_to, 'a') as fd:
        writer = csv.writer(fd)
        for i in range(0, batch_size):
            index = indices[i]
            y_pred = predictions[i]
            y_true = labels[i]
            site = sites[i]
            date = dates[i]
            state = states[i]
            row = [index, y_pred, y_true, site, date, state]
            writer.writerow(row)
            
def strip_and_freeze(model):
    """
    Takes a PyTorch model, removes the last layer, and freezes the
    parameters.

    Parameters
    ----------
    model : torch.nn.Module
        Model to freeze.

    Returns
    -------
    stripped_model : torch.nn.Sequential
        Same model but with last layer removed and parameters frozen.
    """
    layers = list(model.children())[:-1] # remove last layer
    stripped_model = torch.nn.Sequential(*layers)
    for param in stripped_model.parameters():
        param.requires_grad = False # freeze layer
    return stripped_model
   
def get_output_dim(model):
    """
    Takes a PyTorch model and returns the output dimension.

    Parameters
    ----------
    model : torch.nn.Module
        Model to report output dimension.

    Returns
    -------
    output_dim : int
        Dimension of the output from running model.forward()
    """
    last_layer = list(model.children())[-1]
    return last_layer.out_features

def compute_dataloader_mean_std(dataloader):
    """
    Iterates through a torch.utils.data.DataLoader and computes means and
    standard deviations. Useful for computing normalization constants over a
    training dataset.

    Parameters
    ----------
    dataloader : torch.utils.data.DataLoader
        DataLoader to iterate through to compute means and standard deviations.

    Returns
    -------
    normalizations : dict
        Dictionary mapping each input key (e.g., "non_image" or "image")
        to another dict of { "mean", "std" }.
    """
    pass

def mse_row(row):
    '''
    Given a row of a df which is an example of the
    form (index, prediction, label),
    computes the MSE of the example.
    '''
    pred = row['Prediction']
    label = row['Label']
    mse = (label-pred)**2
    return mse


def compute_r2(predictions_csv):
    '''                                                 
    Takes in .csv created from save_predictions of (indices, predictions, labels)
    for each example, and calculates total R2 over the dataset.
    '''
    df = pd.read_csv(predictions_csv)
    
    indices = df['Index']
    predictions = df['Prediction']
    labels = df['Label']
    
    r2 = r2_score(labels, predictions)
    pearson = pearsonr(labels, predictions)
    return r2, pearson 
    

def compute_mse(predictions_csv):
    '''
    Computes the mean MSE over all predictions in predictions_csv.
    '''
    pandarallel.initialize()

    df = pd.read_csv(predictions_csv)
    mses = df.parallel_apply(mse_row, axis=1)
    mse = mses.sum()/len(mses)

    return mse

def plot_loss_histogram(predictions_csv):
    '''                                                 
    Takes in .csv created from save_predictions of (indices, predictions, labels)
    for each example, and calculates MSE of each example.     
    Then plots the histogram of the losses.  
    '''
    pandarallel.initialize()

    df = pd.read_csv(predictions_csv)
    mses = df.parallel_apply(mse_row, axis=1)
    df['MSE'] = mses

    # Compute mean and stdev of MSEs                                                                    
    mean_mse = np.mean(mses)
    stddev_mse = np.std(mses)

    stdev1 = mean_mse + stddev_mse
    stdev2 = stdev1 + stddev_mse
    stdev3 = stdev2 + stddev_mse

    bins = 100

    plt.hist(mses, bins,alpha=.9,label = 'MSE loss')
    min_ylim, max_ylim = plt.ylim()
    plt.axvline(mean_mse, color='k', linestyle='dashed', linewidth=1)
    plt.text(mean_mse*1.1, max_ylim*0.9, 'Mean = {:.2f}'.format(mean_mse), fontsize=10)

    plt.axvline(stdev1, color='k', linestyle='dashed', linewidth=1)
    plt.text(stdev1*1.1, max_ylim*0.7,  'Mean+1stdv = {:.2f}'.format(stdev1), fontsize=10)

    plt.axvline(stdev2, color='k', linestyle='dashed', linewidth=1)
    plt.text(stdev2*1.1, max_ylim*0.6, 'Mean+2std = {:.2f}'.format(stdev2) , fontsize=10)

    plt.axvline(stdev3, color='k', linestyle='dashed', linewidth=1)
    plt.text(stdev3*1.1, max_ylim*0.5, 'Mean+3std = {:.2f}'.format(stdev3), fontsize=10)

    plt.savefig("plots/loss_hist.png")
    plt.show() 
    
    above_three_stdv = df[df['MSE']>stdev3]
    sorted_above_three = above_three_stdv.sort_values(by=['Index'])
    
    
def month_average_analysis(averages_csv):
    '''
    Method that computes the mean monthly PM2.5 average over all sites. 
    '''
    average_df = pd.read_csv(averages_csv)
    for month in range(1, 13):
        month_df = average_df[average_df['Month']== month]
        pms = month_df['Month Average']
        mean_avg_pm_allsites = np.mean(pms)
        print("Month {} mean average over all sites: {}".format(month, mean_avg_pm_allsites))

        
def plot_predictions(predictions_csv, model_name):
    '''
    Method to plot true PM2.5 values vs. model predicted values based on predictions in
    the predictions_csv file.
    '''
    df = pd.read_csv(predictions_csv)
    
    indices = df['Index']
    predictions = df['Prediction']
    labels = df['Label']
   
    plt.scatter(labels, predictions, s=1)
    plt.xlabel("Real PM2.5 Values (μg/$m^3$')", fontsize=14)
    plt.ylabel("Model PM2.5 Predictions (μg/$m^3$')", fontsize=14)
    plt.axis([-10, 25, -10, 25])
    plt.title("True PM2.5 Values versus Model \n PM2.5 Predictions: " + model_name, fontsize=16)
    plt.savefig("plots/true_vs_preds_new_ " + model_name +".png")
    plt.show()

    
def plot_predictions_histogram(predictions_csv, model_name, dataset='val'):
    '''                                                 
    Takes in .csv created from save_predictions of (indices, predictions, labels)
    for each example. Then plots the histogram of the predictions vs. the labels.  
    '''
    plt.clf()
    df = pd.read_csv(predictions_csv)
    predictions = df['Prediction']
    labels = df['Label']
    bins = 50
   
    plt.hist(predictions, bins, alpha=.95,label = 'Predictions', color='cadetblue')
    plt.hist(labels, bins, alpha=.8,label = 'Labels', color='darkseagreen')
    plt.xlabel("Prediction/Ground Truth Value")
    plt.ylabel("Frequency")
    plt.title("Histograms of Predicted PM2.5 Values versus Ground \nTruth Labels on Test Data: " + model_name, fontsize=15)
    plt.legend()
    plt.savefig("plots/"+dataset+"_" + model_name + "_predictions_hist.png")
    plt.show()

    
def highest_loss_analysis_via_outliers(predictions_csv):
    '''                                                 
    Takes in predictions csv of the form:  (indices, predictions, labels, site id, month, state),
    for each example, and calculates MSE of each example.     
    Then determines examples with highest losses, based on month/site ID, to investigate trends. 
    '''
    pandarallel.initialize()

    df = pd.read_csv(predictions_csv)
    mses = df.parallel_apply(mse_row, axis=1)
    df['MSE'] = mses

    # Compute mean and stdev of MSEs
    mean_mse = np.mean(mses)
    stddev_mse = np.std(mses)

    stdev1 = mean_mse + stddev_mse
    stdev2 = stdev1 + stddev_mse
    stdev3 = stdev2 + stddev_mse
    
    # Determine outliers based on loss - defined as examples > 3 std. away from mean
    above_two_stdv = df[df['MSE']>stdev2]
    above_three_stdv = df[df['MSE']>stdev3]
    sorted_above_three = above_three_stdv.sort_values(by=['Index'])
    
    category = 'Month'  # or 'Site ID'
    category_outliers = above_three_stdv[category]
    unique_values = pd.unique(category_outliers)   #i.e. unique sites / unique months
    num_unique = len(unique_values)

    plt.hist(sites, num_unique, alpha=.9,label = 'Highest Loss examples by '+ category)
    plt.title('Highest Loss examples by '+ category , fontsize=16)
    plt.xlabel(category, fontname="Times New Roman", fontsize=12)
    plt.ylabel('Frequency',fontname="Times New Roman", fontsize=12)
    plt.savefig("plots/highest_losses_by_" + category + ".png")
    plt.show()
    
    n = 5 # Top 5 most fq sites most informative; 4 most fq months most informative
    most_fq_in_category = category_outliers.value_counts()[:n].index.tolist()  
    return most_fq_in_category

    
def get_outlier_info(master_csv):
    '''
    Look up information of an outlier found from highest_loss_analysis function
    '''
    
    site_id = 60371201 
    df = pd.read_csv(master_csv)

    site_points = df[df['Site ID'] == site_id]
    twenty = site_points.head(20)                                                             
    most_fq_months = site_points['Month'].value_counts()[:12].index.tolist()

    preds_csv = "predictions/newest_combined_val_epoch_14.csv"
    preds_df = pd.read_csv(preds_csv)
    preds_at_site = preds_df[preds_df['Site ID'] == site_id]
    return preds_at_site


def highest_loss_analysis(predictions_csv, model_name):
    '''                                                 
    Takes in predictions .csv of the form: (indices, predictions, labels, site id, month, state),
    for each example, and calculates MSE of each example.     
    Plots losses vs. month/state to investigate trends. 
    '''
    pandarallel.initialize()
    plt.clf()
    df = pd.read_csv(predictions_csv)
    mses = df.parallel_apply(mse_row, axis=1)
    df['MSE'] = mses
    df = df.groupby('State', as_index=False)['MSE'].mean()  # Or 'Month'
 
    # 44 states; Does not include ak, nd, dc, ri , hi, md
    states = ['AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA','ME',
              'MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','OH','OK','OR','PA',
              'SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']
    
    state_colors_multi_modal = ['b','b','b','r','b','r','b','b','b','r','b','b','r','b','b','b','b',
              'b','b','b','b','b','r','b','b','b','b','b','b','b','b','b','b','r',
              'b','b','b','b','b','b','b','b','b','b','b']

    state_colors_knn = ['r','b','b','r','r','r','b','b','b','r','b','b','b','b','b','b','b',
                  'b','b','b','b','b','r','b','b','b','b','b','b','b','b','b','b','b',
                  'b','b','b','b','b','b','b','b','b','b','b']
    r = 'firebrick'
    g = 'darkseagreen'
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    month_colors = [r,r,g,g,g,g,g,g,g,g,r,r]  
    
    plt.xlabel("State",fontsize=14)
    plt.ylabel("Average Mean Squared Error")
    plt.xticks(np.arange(0,44), states, rotation='vertical', fontsize=10)

    plt.title("Average Mean Squared Error By State")
    plt.bar(states, df['MSE'], color=state_colors_knn)
    ##plt.bar(months, df['MSE'], color=month_colors)                                                                                                    
    plt.savefig("plots/avg_losses_by_state_"+ model_name +".png")
    plt.show()
    
    
def compute_per_site_r2(preds_csv):
    '''
    Reads in predictions df given in preds_csv and 
    computes the per-site r2 and Pearson for the predictions.
    '''
    df = pd.read_csv(preds_csv)
    epa_stations = df['Site ID'].unique()

    for idx, station in enumerate(epa_stations):
        station_df = df[df['Site ID'] == station]
        predictions = station_df['Prediction']
        labels = station_df['Label']
        r2 = r2_score(labels, predictions)
        pearson = pearsonr(labels, predictions)
        print("Site {}/{}: {} r2 score: {}".format(idx, len(epa_stations), station, r2))
            
    #labels = df['Month Average']
    #predictions = df['Predicted Month Average']
            
    return r2, pearson



