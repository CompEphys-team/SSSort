# sys
import sys
import os
import copy
import dill
import shutil
import configparser
from pathlib import Path
from tqdm import tqdm

# sci
import scipy as sp
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

# ephys
import neo
import elephant as ele

# own
from tools.functions import *
from tools.plotters import *
import tools.sssio as sssio

# banner
print(banner)

# plotting
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns

"""
 
 #### ##    ## #### 
  ##  ###   ##  ##  
  ##  ####  ##  ##  
  ##  ## ## ##  ##  
  ##  ##  ####  ##  
  ##  ##   ###  ##  
 #### ##    ## #### 
 
"""

plt.rcParams.update({'font.size': 6})

# get config
config_path = Path(os.path.abspath(sys.argv[1]))
Config = configparser.ConfigParser()
Config.read(config_path)
print_msg('config file read from %s' % config_path)

# get segment to analyse
seg_no= Config.getint('general','segment_number')

spike_label_interval= Config.getint('output','spike_label_interval')

# handling paths and creating output directory
data_path = Path(Config.get('path','data_path'))
if not data_path.is_absolute():
    data_path = config_path.parent / data_path

exp_name = Config.get('path','experiment_name')
results_folder = config_path.parent / exp_name / 'results'
plots_folder = results_folder / 'plots' / 'sssort'
os.makedirs(plots_folder, exist_ok=True)
os.chdir(config_path.parent / exp_name)

spikes_path = config_path.parent / results_folder / "spikes_result.dill"
templates_path = config_path.parent / results_folder / "Templates_ini.npy"
rej_spikes_path = config_path.parent / results_folder / "rejected_spikes.npy"

#TODO: add question!!
# os.system("rm %s/*"%plots_folder)

# copy config
shutil.copyfile(config_path, config_path.parent / exp_name / config_path.name)

# read data
try:
    Blk = sssio.get_data(spikes_path)
    Blk.name = exp_name
except FileNotFoundError:
    print_msg("Spike file not found, run templates_extraction.py first")
    exit()
    
seg = Blk.segments[seg_no]
print_msg('spikes read from %s' % spikes_path)

Templates= np.load(templates_path)
print_msg('templates read from %s' % templates_path)

#Load rejected spikes if found
try:
    rej_spikes = np.load(rej_spikes_path)
except:
    rej_spikes = None


# Data info
fs = seg.analogsignals[0].sampling_rate
n_samples= np.array(Config.get('spike model','template_window').split(','),dtype='float32')/1000.0
n_samples= np.array(n_samples*fs, dtype= int)


# plotting
mpl.rcParams['figure.dpi'] = Config.get('output','fig_dpi')
fig_format = Config.get('output','fig_format')


#TODO restriction if you do not want to analyze the whole trace

# try:
#     ini = Config.getint('preprocessing','ini') // 1000
#     end = Config.getint('preprocessing','end') // 1000
# except configparser.NoOptionError as no_option:
#     ini = 0
#     end = -1
# except:
#     exit()

"""
 
  ######  ##       ##     ##  ######  ######## ######## ########  
 ##    ## ##       ##     ## ##    ##    ##    ##       ##     ## 
 ##       ##       ##     ## ##          ##    ##       ##     ## 
 ##       ##       ##     ##  ######     ##    ######   ########  
 ##       ##       ##     ##       ##    ##    ##       ##   ##   
 ##    ## ##       ##     ## ##    ##    ##    ##       ##    ##  
  ######  ########  #######   ######     ##    ######## ##     ## 
 
"""

#Performs the first clustering from PCA 
n_clusters_init = Config.getint('spike sort','init_clusters')
print_msg("initial kmeans with %i clusters" % n_clusters_init)
pca = PCA(n_components=5) # FIXME HARDCODED PARAMETER
X = pca.fit_transform(Templates.T)
kmeans_labels = KMeans(n_clusters=n_clusters_init).fit_predict(X)
#print("labels that are -1: {}".format(np.sum(kmeans_labels == -1)))
spike_labels = kmeans_labels.astype('U')

"""
 
  ######  ########  #### ##    ## ######## #### ##    ## ########  #######  
 ##    ## ##     ##  ##  ##   ##  ##        ##  ###   ## ##       ##     ## 
 ##       ##     ##  ##  ##  ##   ##        ##  ####  ## ##       ##     ## 
  ######  ########   ##  #####    ######    ##  ## ## ## ######   ##     ## 
       ## ##         ##  ##  ##   ##        ##  ##  #### ##       ##     ## 
 ##    ## ##         ##  ##   ##  ##        ##  ##   ### ##       ##     ## 
  ######  ##        #### ##    ## ######## #### ##    ## ##        #######  
 
"""
# Generates the SpikeInfo data frame with first clustering. 

#  make a SpikeInfo dataframe
SpikeInfo = pd.DataFrame()

# count spikes
n_spikes = Templates.shape[1]
SpikeInfo['id'] = sp.arange(n_spikes,dtype='int32')

# get all spike times
spike_times = seg.spiketrains[0].times.magnitude
SpikeInfo['time'] = spike_times

# get segment labels
# This is from the original version, data is in only in the first segment,
# every value in this column should be 0
segment_labels = seg.spiketrains[0].shape[0] * [seg_no]
SpikeInfo['segment'] = segment_labels

# get all labels
SpikeInfo['unit'] = spike_labels #Unit column has cluster id.

# get clean templates
n_neighbors = Config.getint('spike model','template_reject')
reject_spikes(Templates, SpikeInfo, 'unit', n_neighbors, verbose=True)

# unassign spikes if unit has too little good spikes
SpikeInfo = unassign_spikes(SpikeInfo, 'unit',min_good=15) # FIXME hardcoded parameter min_good


outpath = plots_folder / ("templates_init" + fig_format)
plot_templates(Templates, SpikeInfo, N=100, save=outpath)


"""
 
 #### ##    ## #### ######## 
  ##  ###   ##  ##     ##    
  ##  ####  ##  ##     ##    
  ##  ## ## ##  ##     ##    
  ##  ##  ####  ##     ##    
  ##  ##   ###  ##     ##    
 #### ##    ## ####    ##    
 
"""
# first ini run
print_msg('- initializing algorithm: calculating all initial firing rates')

# rate est
kernel_slow = Config.getfloat('kernels','sigma_slow')
kernel_fast = Config.getfloat('kernels','sigma_fast')
calc_update_frates(SpikeInfo, 'unit', kernel_fast, kernel_slow)

# model
n_model_comp = Config.getint('spike model','n_model_comp')
Models = train_Models(SpikeInfo, 'unit', Templates, n_comp=n_model_comp, verbose=True)
outpath = plots_folder / ("Models_ini" + fig_format)
plot_Models(Models, save=outpath)

zoom = sp.array(Config.get('output','zoom').split(','),dtype='float32') / 1000

seg_name = Path(seg.annotations['filename']).stem
units = get_units(SpikeInfo, 'unit')

Blk = populate_block(Blk,SpikeInfo,'unit',units)

outpath = plots_folder / ('fitted_spikes_init' + fig_format)
plot_fitted_spikes(seg, Models, SpikeInfo, 'unit', zoom=zoom, save=outpath,wsize=n_samples,rejs=rej_spikes,spike_label_interval=spike_label_interval)


"""
 
 ########  ##     ## ##    ## 
 ##     ## ##     ## ###   ## 
 ##     ## ##     ## ####  ## 
 ########  ##     ## ## ## ## 
 ##   ##   ##     ## ##  #### 
 ##    ##  ##     ## ##   ### 
 ##     ##  #######  ##    ## 
 
"""

# reset
SpikeInfo['unit_0'] = SpikeInfo['unit'] # the init

# get run parameters from config file
n_final_clusters = Config.getint('spike sort','n_final_clusters')
rm_smaller_cluster = Config.getboolean('spike sort','rm_smaller_cluster')
it_merge = Config.getint('spike sort','it_merge')
org_it_merge = it_merge
first_merge = Config.getint('spike sort','first_merge')
clust_alpha = Config.getfloat('spike sort','clust_alpha')
units = get_units(SpikeInfo, 'unit_0')
n_units = len(units)
penalty = Config.getfloat('spike sort','penalty')
try:
    approve_merge = Config.getboolean('spike sort', 'approve_merge')
except Exception:
    approve_merge= False

ScoresSum = []
AICs = []

spike_ids = SpikeInfo['id'].values

it_no_merge = Config.getint('spike sort','it_no_merge')

#init loop params
it =1
not_merge =0

change_cluster=Config.getint('spike sort','cluster_limit_train')
last = False
illegal_merge= []

while n_units >= n_final_clusters and not last:
    if n_units == n_final_clusters:
        last = True

    # unit columns
    prev_unit_col = 'unit_%i' % (it-1)
    this_unit_col = 'unit_%i' % it
    
    # update rates
    calc_update_frates(SpikeInfo, prev_unit_col, kernel_fast, kernel_slow)

    # train models with labels from last iteration
    Models = train_Models(SpikeInfo, prev_unit_col, Templates, verbose=False, n_comp=n_model_comp)
    outpath = plots_folder / ("Models_%s%s" % (prev_unit_col, fig_format))
    plot_Models(Models, save=outpath)

    # Score spikes with models
    score = Rss #change to double_score or amplitude_score for other model scoring
    Scores, units = Score_spikes(Templates, SpikeInfo, prev_unit_col, Models, score_metric=score, penalty=penalty)

    #If still changing from prediction
    if n_units > change_cluster:
        # assign new labels
        min_ix = sp.argmin(Scores, axis=1)
        new_labels = sp.array([units[i] for i in min_ix],dtype='object')

    else: #stop clusters changes and force merging
        new_labels = sp.array(SpikeInfo[prev_unit_col])
        it_merge = 1
        clust_alpha = 10
        # assign new labels just for spikes with unit "-1"
        mone_spikes= SpikeInfo[prev_unit_col].values == '-1'
        if np.sum(mone_spikes) > 0:
            min_ix = sp.argmin(Scores[mone_spikes,:], axis=1)
            new_labels[mone_spikes] = sp.array([units[i] for i in min_ix],dtype='object')

    SpikeInfo[this_unit_col] = new_labels
    n_changes = np.sum(~(SpikeInfo[prev_unit_col]==SpikeInfo[this_unit_col]))
    print_msg("Changes by scoring: %d "%n_changes)

    # merge value forcing
    if it_merge > 1 and n_changes < 3:
        it_merge = 1
        clust_alpha +=0.1
    else:
        it_merge = org_it_merge

    SpikeInfo = unassign_spikes(SpikeInfo, this_unit_col)
    reject_spikes(Templates, SpikeInfo, this_unit_col,verbose=False)
    
    # plot templates
    outpath = plots_folder / ("Templates_%s%s" % (this_unit_col, fig_format))
    plot_templates(Templates, SpikeInfo, this_unit_col, save=outpath)

    # every n iterations, merge
    if (it > first_merge) and (it % it_merge) == 0 and not last:
        print_msg("check for merges ... ")
        Avgs, Sds = calculate_pairwise_distances(Templates, SpikeInfo, this_unit_col)
        merge = best_merge(Avgs, Sds, units, clust_alpha, illegal_merge=illegal_merge)

        if len(merge) > 0:
            print_msg("########merging: " + ' '.join(merge))
            if approve_merge:
                fig, ax= plot_Models(Models)
                fig.show()
                Blk = populate_block(Blk,SpikeInfo,this_unit_col,units)
                Seg = Blk.segments[0]
                fig2, ax2= plot_fitted_spikes(seg, Models, SpikeInfo, this_unit_col, zoom=zoom, wsize=n_samples,rejs=rej_spikes,spike_label_interval=spike_label_interval)
                fig2.show()
                do_merge= input("Go ahead (Y/N)?").upper() == 'Y'
                plt.close(fig)
                plt.close(fig2)
            else:
                do_merge= True

            if do_merge:
                ix = SpikeInfo.groupby(this_unit_col).get_group(merge[1])['id']
                SpikeInfo.loc[ix, this_unit_col] = merge[0]
            
                #reset merging parameters
                not_merge =0
                it_merge = Config.getint('spike sort','it_merge')
                it_no_merge = Config.getint('spike sort','it_no_merge')
            else:
                illegal_merge.append(merge)
                not_merge+= 1
        else:
            not_merge +=1

    #Increase merge probability after n failed merges
    if not_merge > it_no_merge:
        clust_alpha +=0.1
        it_merge = max(it_merge-1,1)
        it_no_merge = max(it_no_merge-1,1)

        print_msg("%d failed merges. New alpha value: %f"%(not_merge,clust_alpha))
        not_merge = 0

    
    # Model eval

    n_changes,Rss_sum,ScoresSum,units,AICs,n_units = eval_model(SpikeInfo,this_unit_col,prev_unit_col,Scores,Templates,ScoresSum,AICs)

    try:
        zoom = sp.array(Config.get('output','zoom').split(','),dtype='float32') / 1000
        
        seg_name = Path(seg.annotations['filename']).stem

        Blk = populate_block(Blk,SpikeInfo,this_unit_col,units)

        outpath = plots_folder / ('fitted_spikes_%d'%(it) + fig_format)
        plot_fitted_spikes(seg, Models, SpikeInfo, this_unit_col, zoom=zoom, save=outpath,wsize=n_samples,rejs=rej_spikes,spike_label_interval=spike_label_interval)
    except Exception as ex:
        print(ex.args)
        pass


    # print iteration info
    print_msg("It:%i - Rss sum: %.3e - # reassigned spikes: %s / %d" % (it, Rss_sum, n_changes,len(spike_labels)))
    print_msg("Number of clusters after iteration: %d"%len(units))

    print_msg("Number of spikes in trace: %d"%SpikeInfo[this_unit_col].size)
    print_msg("Number of good spikes: %d"%len(SpikeInfo.groupby(['good']).get_group(True)[this_unit_col]))
    # print_msg("Number of bad spikes: %d"%len(SpikeInfo.groupby(['good']).get_group(False)[this_unit_col]))
    print_msg("Number of clusters: %d"%len(units))
    it +=1


#######
print_msg("algorithm run is done")

#find last column name
last_unit_col = [col for col in SpikeInfo.columns if col.startswith('unit')][-1]
unit_column = last_unit_col

# plot templates and models for last column
outpath = plots_folder / ("Templates_%s%s" % (unit_column,fig_format))
plot_templates(Templates, SpikeInfo, unit_column, save=outpath)
outpath = plots_folder / ("Models_%s%s" % (unit_column,fig_format))
plot_Models(Models, save=outpath)

# Remove the smallest cluster
# TODO change for smallest amplitude?
max_window= Config.getfloat('output','max_window_fitted_spikes_overview')
if rm_smaller_cluster:
    SpikeInfo['last_remove_save'] = copy.deepcopy(SpikeInfo[unit_column].values)
    remove_spikes(SpikeInfo,unit_column,'min')
    n_changes,Rss_sum,ScoresSum,units,AICs,n_units = eval_model(SpikeInfo,this_unit_col,prev_unit_col,Scores,Templates,ScoresSum,AICs)

    # plot templates and models for last column
    outpath = plots_folder / ("Templates_final%s" % ( fig_format))
    plot_templates(Templates, SpikeInfo, unit_column, save=outpath)
    outpath = plots_folder / ("Models_final%s" % (fig_format))
    plot_Models(Models, save=outpath)

    plot_fitted_spikes_complete(seg, Templates, SpikeInfo, [ 'last_remove_sae',unit_column], max_window, plots_folder, fig_format,wsize=n_samples,extension='_last_remove',plot_function=plot_compared_fitted_spikes,rejs=rej_spikes,spike_label_interval=spike_label_interval)




"""
 
 ######## #### ##    ## ####  ######  ##     ## 
 ##        ##  ###   ##  ##  ##    ## ##     ## 
 ##        ##  ####  ##  ##  ##       ##     ## 
 ######    ##  ## ## ##  ##   ######  ######### 
 ##        ##  ##  ####  ##        ## ##     ## 
 ##        ##  ##   ###  ##  ##    ## ##     ## 
 ##       #### ##    ## ####  ######  ##     ## 
 
"""

last_unit_col = [col for col in SpikeInfo.columns if col.startswith('unit')][-1]

# plot
outpath = plots_folder / ("Convergence_Rss" + fig_format)
plot_convergence(ScoresSum, save=outpath)

outpath = plots_folder / ("Convergence_AIC" + fig_format)
plot_convergence(AICs, save=outpath)

outpath = plots_folder / ("Clustering" + fig_format)
plot_clustering(Templates, SpikeInfo, last_unit_col, save=outpath)

# update spike labels
kernel = ele.kernels.GaussianKernel(sigma=kernel_fast * pq.s)
# it = its-1 # the last
it = it-1

#TODO change for a call to populate block
spike_labels = SpikeInfo['unit_%i' % it].values
seg.spiketrains[0].annotations['unit_labels'] = list(spike_labels)

# make spiketrains
St = seg.spiketrains[0]
spike_labels = St.annotations['unit_labels']
sts = [St]

for unit in units:
    times = St.times[sp.array(spike_labels) == unit]
    st = neo.core.SpikeTrain(times, t_start = St.t_start, t_stop=St.t_stop)
    st.annotate(unit=unit)
    sts.append(st)
seg.spiketrains=sts

# est firing rates
asigs = [seg.analogsignals[0]]
for unit in units:
    St, = select_by_dict(seg.spiketrains, unit=unit)
    frate = ele.statistics.instantaneous_rate(St, kernel=kernel, sampling_period=1/fs)
    frate.annotate(kind='frate_fast', unit=unit)
    asigs.append(frate)
seg.analogsignals = asigs

#save all

units = get_units(SpikeInfo,unit_column)
print_msg("Number of spikes in trace: %d"%SpikeInfo[unit_column].size)
print_msg("Number of bad spikes: %d"%len(SpikeInfo.groupby(['good']).get_group(True)[unit_column]))
print_msg("Number of clusters: %d"%len(units))

# warning firing rates not saved, too high memory use.
sssio.save_all(results_folder, SpikeInfo, Blk, FinalSpikes= False)

"""
 
 ########  ##        #######  ########    #### ##    ##  ######  ########  ########  ######  ######## 
 ##     ## ##       ##     ##    ##        ##  ###   ## ##    ## ##     ## ##       ##    ##    ##    
 ##     ## ##       ##     ##    ##        ##  ####  ## ##       ##     ## ##       ##          ##    
 ########  ##       ##     ##    ##        ##  ## ## ##  ######  ########  ######   ##          ##    
 ##        ##       ##     ##    ##        ##  ##  ####       ## ##        ##       ##          ##    
 ##        ##       ##     ##    ##        ##  ##   ### ##    ## ##        ##       ##    ##    ##    
 ##        ########  #######     ##       #### ##    ##  ######  ##        ########  ######     ##    
 
"""

#TODO: fix memory rising: loop & plt.close...

do_plot= Config.getboolean('spike sort','plot_fitted_spikes')

if do_plot:
    print_msg("creating plots")
    # plot all sorted spikes
    outpath = plots_folder / ('overview' + fig_format)
    plot_segment(seg, units, save=outpath)

    # plot all sorted spikes
    plot_fitted_spikes_complete(seg, Templates, SpikeInfo, unit_column, max_window, plots_folder, fig_format,wsize=n_samples,extension='_templates',rejs=rej_spikes,spike_label_interval=spike_label_interval)

    print_msg("plotting done")
    
print_msg("all done - quitting")

