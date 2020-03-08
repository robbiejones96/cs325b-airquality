import os
import csv
import numpy as np
import pandas as pd
from sklearn.metrics import r2_score
from pandarallel import pandarallel
from scipy.stats.stats import pearsonr
from utils import remove_partial_missing_modis
import matplotlib.pyplot as plt

HOME_FOLDER = os.path.expanduser("~")
REPO_NAME = "cs325b-airquality"
DATA_FOLDER = "data"
REPO_FOLDER = os.path.join(HOME_FOLDER, REPO_NAME)
SENTINEL_FOLDER = os.path.join(REPO_FOLDER, DATA_FOLDER, "sentinel")
PROCESSED_DATA_FOLDER = os.path.join(REPO_FOLDER, DATA_FOLDER, "processed_data")


def get_subdir_name(num_measurements):
    '''
    Gets the correct subdirectory to save plot 
    based on the number of measurements. 
    '''
    if num_measurements < 40:
        subdir  = '20-40'
    elif num_measurements < 60:
        subdir  = '40-60'
    elif num_measurements < 80:
        subdir  = '60-80'
    elif num_measurements < 100:
        subdir  = '80-100'
    elif num_measurements < 120:
        subdir  = '100-120'
    else:
        subdir  = '120-more'
         
    dir_ = "visuals/repaired/allsites/" + str(subdir) + "/"

    return dir_
   
    
def get_MODIS_vals(row):
    
    b1,b2,b3,b4 = float(row['Blue [0,0]']), float(row['Blue [0,1]']), float(row['Blue [1,0]']), float(row['Blue [1,1]'])
    g1,g2,g3,g4 = float(row['Green [0,0]']), float(row['Green [0,1]']), float(row['Green [1,0]']), float(row['Green [1,1]'])
    AOD_vals = np.array([b1,b2,b3,b4,g1,g2,g3,g4])
    
    return AOD_vals

def get_MODIS_green_mean(row):
    
    g1,g2,g3,g4 = float(row['Green [0,0]']), float(row['Green [0,1]']), float(row['Green [1,0]']), float(row['Green [1,1]'])
    green_mean = (g1+g2+g3+g4)/4
    
    return green_mean

def get_MODIS_blue_mean(row):
    
    b1,b2,b3,b4 = float(row['Blue [0,0]']), float(row['Blue [0,1]']), float(row['Blue [1,0]']), float(row['Blue [1,1]'])
    blue_mean = (b1+b2+b3+b4)/4
    
    return blue_mean


def get_sentinel_band_mean(row, band=0):

    means_str = row['means']
    means = [float(ss) for ss in means_str[1:-1].split()] 
    mean = means[band]
    return mean
    

def plot_PM_vs_AOD(master_csv):
    '''
    Computes and plots the Pearson coefficient of PM2.5 vs. MODIS 
    AOD green means for each individual site.
    '''
    pandarallel.initialize()

    df = pd.read_csv(master_csv)
    df = remove_partial_missing_modis(df)
    df['all AOD'] = df.parallel_apply(get_MODIS_vals, axis=1)
    df['green mean'] = df.parallel_apply(get_MODIS_green_mean, axis=1)
    df['blue mean'] = df.parallel_apply(get_MODIS_blue_mean, axis=1)
   
    # Get all unqiue EPA sites
    epa_stations = df['Site ID'].unique()
    av_pearson = 0
    count = 0
    
    for idx, station in enumerate(epa_stations):
        station_df = df[df['Site ID'] == station]
        num_measurements = len(station_df)
        
        if num_measurements > 20:
            
            print("Creating plot for station {}/{}: {}".format(idx,len(epa_stations), station))
    
            subdir = get_subdir_name(num_measurements)
            pearson = pearsonr(station_df['green mean'], station_df['Daily Mean PM2.5 Concentration'])
            pearson_str = "r = " + str(round(pearson[0], 3))
            plt.xlabel("Modis Green Mean Daily Value")
            plt.ylabel("PM2.5 Concentration")
            plt.scatter(station_df['green mean'],station_df['Daily Mean PM2.5 Concentration'],s=1,label=pearson_str)  
            plt.title("Modis Green Mean vs. PM2.5 value for Site: " + str(station), fontsize=16)
            plt.legend(loc='upper left') 
            plt.savefig(subdir + "PM_vs_modis_green_mean_for_" + str(station) +".png")            
            plt.show()
            plt.clf()
    
            av_pearson += pearson[0]
            count += 1
    
    print("Average pearson across {} sites: {}".format(count, av_pearson/count))

    
    
def plot_PM_vs_sent_all_sites(master_csv):
    '''
    Computes and plots the Pearson coefficient of PM2.5 vs. sentinel band
    means across all entries in the master .csv (i.e. all readings at all sites).
    '''
    pandarallel.initialize()

    df = pd.read_csv(master_csv)
    subdir = "visuals/repaired/allsites/"
    
    for band in [0]: #range(0,13):

        label = 'b' + str(band+1)+ ' mean'
        df[label] = df.parallel_apply(get_sentinel_band_mean, band=band, axis=1)
        pearson = pearsonr(df[label], df['Daily Mean PM2.5 Concentration'])
        mean_day_diff =  df['PM Reading/Image day difference'].mean()
                
        if np.isnan(pearson[0]):
            continue
                                    
        print("Band {} pearson: {}. Day difference: {}".format(band, pearson, mean_day_diff))
        
        pearson_str = "r = " + str(round(pearson[0], 3))
        plt.scatter(df[label], df['Daily Mean PM2.5 Concentration'], s=1, label = pearson_str)
        plt.xlabel("Sentinel Band " + str(band) + " Mean Value")
        plt.ylabel("PM2.5 Concentration")
        plt.title("Sentinel Band " + str(band) + " Mean vs. PM2.5 value across all sites", fontsize=16)
        plt.legend(loc='upper left') 
        plt.savefig(subdir + "PM_vs_sent_band_" +str(band)+"_mean_for_all_sites.png")            
        plt.show()
        plt.clf()
                
    print("Pearson across dataset: {}".format(pearson))
    
def plot_PM_vs_sent_per_site(master_csv):
    '''
    Computes and plots the Pearson coefficient of PM2.5 vs. sentinel 
    band means for each individual site.
    '''
    pandarallel.initialize()

    df = pd.read_csv(master_csv)
   
    epa_stations = df['Site ID'].unique()
    av_pearsons = {'b1 mean':0, 'b2 mean':0, 'b3 mean':0, 'b4 mean':0, 'b5 mean':0, 
                            'b6 mean':0, 'b7 mean':0, 'b8 mean':0, 'b9 mean':0, 
                            'b10 mean':0, 'b11 mean':0, 'b12 mean':0, 'b13 mean':0}
    count = 0
    
    # Loop over all unique EPA stations in csv
    for idx, station in enumerate(epa_stations):
            
        station_df = df[df['Site ID'] == station]
        num_measurements = len(station_df)

        if num_measurements > 20:
                        
            subdir = get_subdir_name(num_measurements)
            
            print("Creating plot for station {}/{}: {} in subdir {}".format(idx,len(epa_stations), station, subdir))
            
            for band in [0]: #range(0,13):

                label = 'b' + str(band+1) + ' mean'
                station_df[label] = df.parallel_apply(get_sentinel_band_mean, band=band, axis=1)

                pearson = pearsonr(station_df[label], station_df['Daily Mean PM2.5 Concentration'])
                mean_day_diff =  station_df['PM Reading/Image day difference'].mean()
             
                if np.isnan(pearson[0]):
                    continue
                    
                pearson_str = "r = " + str(round(pearson[0], 3))
                
                print("Band {} pearson for site {}: {}. ".format(band, station, pearson))
                print("Number of measurements: {}. Mean day difference: {}\n".format(num_measurements, mean_day_diff))
                
                plt.scatter(station_df[label], station_df['Daily Mean PM2.5 Concentration'], s=1, label = pearson_str)
                plt.xlabel("Sentinel Band " + str(band) + " Mean Value")
                plt.ylabel("PM2.5 Concentration")
                plt.title("Sentinel Band " + str(band) + " Mean vs. PM2.5 value for Site: " + str(station), fontsize=16)
                plt.legend(loc='upper left') 
                plt.savefig(subdir + "PM_vs_sent_band_" +str(band)+"_mean_for_"+ str(station) +".png")            
                plt.show()
                plt.clf()
               
                av_pearsons[label] += pearson[0]
                
        count += 1
    
    for band, sum_ in av_pearsons.items():
        av_pearsons[band] = sum_/count
        
    print("Average pearson across {} sites: {}".format(count, av_pearsons))

    
if __name__ == "__main__":
    
    train_high_var = os.path.join(PROCESSED_DATA_FOLDER,"train_sites_DT_and_thresh_2000_stats_var_thresh_30_csv_2016.csv")
    train_all_sites = os.path.join(PROCESSED_DATA_FOLDER,"train_sites_DT_2000_stats_csv_2016.csv")
    new_train_repaired_stats = os.path.join(PROCESSED_DATA_FOLDER,"train_repaired_sufficient_close_stats_2016.csv")

    plot_PM_vs_sent_per_site(new_train_repaired_stats)
    