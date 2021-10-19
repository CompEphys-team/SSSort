# system
import sys
import os
import time
import copy
if os.name == 'posix':
    import resource
import warnings
from tqdm import tqdm
import threading

# sci
import scipy as sp
import numpy as np
from scipy import stats, signal
import quantities as pq
import pandas as pd

# ml
import sklearn
from sklearn.neighbors import LocalOutlierFactor
from sklearn.decomposition import PCA
from sklearn import metrics

# ephys
import neo
import elephant as ele

# print
import colorama
import tableprint as tp

# plotting
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore")
t0 = time.time()

"""
 
 ##     ## ######## ##       ########  ######## ########   ######  
 ##     ## ##       ##       ##     ## ##       ##     ## ##    ## 
 ##     ## ##       ##       ##     ## ##       ##     ## ##       
 ######### ######   ##       ########  ######   ########   ######  
 ##     ## ##       ##       ##        ##       ##   ##         ## 
 ##     ## ##       ##       ##        ##       ##    ##  ##    ## 
 ##     ## ######## ######## ##        ######## ##     ##  ######  
 
"""

def print_msg(msg, log=True):
    """prints the msg string with elapsed time and current memory usage.

    Args:
        msg (str): the string to print
        log (bool): write the msg to the log as well

    """
    if os.name == 'posix':
        mem_used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
        # msg = "%s%s\t%s\t%s%s" % (colorama.Fore.CYAN, timestr, memstr, colorama.Fore.GREEN, msg)
        mem_used = sp.around(mem_used, 2)
        memstr = '('+str(mem_used) + ' GB): '
        timestr = tp.humantime(sp.around(time.time()-t0,2))
        print(colorama.Fore.CYAN + timestr + '\t' +  memstr + '\t' +
              # colorama.Fore.GREEN + msg)
              colorama.Fore.WHITE + msg)
        if log:
            with open('log.log', 'a+') as fH:
                log_str = timestr + '\t' +  memstr + '\t' + msg + '\n'
                fH.writelines(log_str)
    else:
        timestr = tp.humantime(sp.around(time.time()-t0,2))
        print(colorama.Fore.CYAN + timestr + '\t' +
              # colorama.Fore.GREEN + msg)
              colorama.Fore.WHITE + msg)
        if log:
            with open('log.log', 'a+') as fH:
                log_str = timestr + '\t' + '\t' + msg
                fH.writelines(log_str)
    pass

def select_by_dict(objs, **selection):
    """
    selects elements in a list of neo objects with annotations matching the
    selection dict.

    Args:
        objs (list): a list of neo objects that have annotations
        selection (dict): a dict containing key-value pairs for selection

    Returns:
        list: a list containing the subset of matching neo objects
    """
    # print("Selection",selection.items())
    res = []
    for obj in objs:
        if selection.items() <= obj.annotations.items():
            res.append(obj)
    return res

def sort_units(units):
    """ helper to sort units ascendingly according to their number """
    units = sp.array(units,dtype='int32')
    units = sp.sort(units).astype('U')
    return list(units)

def get_units(SpikeInfo, unit_column, remove_unassinged=True):
    """ helper that returns all units in a given unit column, with or without unassigned """
    units = list(pd.unique(SpikeInfo[unit_column]))
    if remove_unassinged:
        if '-1' in units:
            units.remove('-1')
    return sort_units(units)

def get_asig_at_st_times(asig, st):
    """ return value of analogsignal at times of a spiketrain (closest samples) """
    fs = asig.sampling_rate
    inds = (st.times * fs).simplified.magnitude.astype('int32')
    offset = (st.t_start * fs).simplified.magnitude.astype('int32')
    inds = inds - offset
    return asig.magnitude.flatten()[inds], inds

def unassign_spikes(SpikeInfo, unit_column, min_good=5):
    """ unassign spikes from unit it unit does not contain enough spikes as samples """
    units = get_units(SpikeInfo, unit_column)
    for unit in units:
        Df = SpikeInfo.groupby(unit_column).get_group(unit)
        if sp.sum(Df['good']) < min_good:
            print_msg("not enough good spikes (%d) for unit %s" %(sp.sum(Df['good']),unit))
            SpikeInfo.loc[Df.index, unit_column] = '-1'
    return SpikeInfo


"""
 
  ######  ########  #### ##    ## ########    ########  ######## ######## ########  ######  ######## 
 ##    ## ##     ##  ##  ##   ##  ##          ##     ## ##          ##    ##       ##    ##    ##    
 ##       ##     ##  ##  ##  ##   ##          ##     ## ##          ##    ##       ##          ##    
  ######  ########   ##  #####    ######      ##     ## ######      ##    ######   ##          ##    
       ## ##         ##  ##  ##   ##          ##     ## ##          ##    ##       ##          ##    
 ##    ## ##         ##  ##   ##  ##          ##     ## ##          ##    ##       ##    ##    ##    
  ######  ##        #### ##    ## ########    ########  ########    ##    ########  ######     ##    
 
"""

def MAD(AnalogSignal):
    """ median absolute deviation of an AnalogSignal """
    X = AnalogSignal.magnitude
    mad = sp.median(sp.absolute(X - sp.median(X))) * AnalogSignal.units
    return mad

def spike_detect(AnalogSignal, bounds, lowpass_freq=1000*pq.Hz,wsize=40):
    """
    detects all spikes in an AnalogSignal that fall within amplitude bounds

    Args:
        AnalogSignal (neo.core.AnalogSignal): the waveform
        bounds (quantities.Quantity): a Quantity of shape (2,) with
            (lower,upper) bounds, unit [uV]
        lowpass_freq (quantities.Quantity): cutoff frequency for a smoothing
            step before spike detection, unit [Hz]

    Returns:
        neo.core.SpikeTrain: the resulting SpikeTrain
    """

    # filter to avoid multiple peaks
    if lowpass_freq is not None:
        AnalogSignal = ele.signal_processing.butter(AnalogSignal,
                                                    lowpass_freq=lowpass_freq)

    # find relative maxima / minima
    peak_inds = signal.argrelmax(AnalogSignal)[0]

    # to data structure
    # SAVES MAX AND NOT SIGNAL!!!
    peak_amps = AnalogSignal.magnitude[peak_inds, :, sp.newaxis] * AnalogSignal.units

    tvec = AnalogSignal.times
    SpikeTrain = neo.core.SpikeTrain(tvec[peak_inds],
                                     t_start=AnalogSignal.t_start,
                                     t_stop=AnalogSignal.t_stop,
                                     sampling_rate=AnalogSignal.sampling_rate,
                                     waveforms=peak_amps)

    # subset detected SpikeTrain by bounds
    SpikeTrain = bounded_threshold(SpikeTrain, bounds)

    return SpikeTrain

#TODO: optimize time, save in negative detection "positive peak" and max?
def double_spike_detect(AnalogSignal, bounds_pos,bounds_neg, lowpass_freq=1000*pq.Hz,wsize=40,plot=False,verbose=False):
    """
    detects all spikes in an AnalogSignal that fall within amplitude bounds
    combines positive and negative peaks

    Args:
        AnalogSignal (neo.core.AnalogSignal): the waveform
        bounds (quantities.Quantity): a Quantity of shape (2,) with
            (lower,upper) bounds, unit [uV]
        lowpass_freq (quantities.Quantity): cutoff frequency for a smoothing
            step before spike detection, unit [Hz]

    Returns:
        neo.core.SpikeTrain: the resulting SpikeTrain
    """
    SpikeTrain_pos = spike_detect(AnalogSignal,bounds_pos, lowpass_freq)
    SpikeTrain_neg = spike_detect(AnalogSignal*-1,bounds_neg, lowpass_freq)

    times_unique = copy.deepcopy(SpikeTrain_pos.times)
    waveforms = copy.deepcopy(SpikeTrain_pos.waveforms)

    plt.plot(AnalogSignal.times,AnalogSignal.magnitude)
    plt.plot(SpikeTrain_neg.times,-1*SpikeTrain_neg.waveforms.reshape(SpikeTrain_neg.waveforms.shape[0]),'x')
    plt.plot(SpikeTrain_pos.times,SpikeTrain_pos.waveforms.reshape(SpikeTrain_pos.waveforms.shape[0]),'x')
    
    for i,st_neg in enumerate(SpikeTrain_neg):
        st_neg_id = int(st_neg*AnalogSignal.sampling_rate)

        size = wsize/2/AnalogSignal.sampling_rate
        size.units = pq.s
        
        indexes = np.where((SpikeTrain_pos > st_neg-size) & (SpikeTrain_pos < st_neg+size))

        if indexes[0].size == 0: #spike not found in positive trains detection
            pini_st_neg = st_neg_id - wsize//2
            pend_st_neg = min(st_neg_id + wsize//2,AnalogSignal.times.size-1)
            
            neg_waveform = AnalogSignal.magnitude[pini_st_neg:st_neg_id]
            waveform = neg_waveform

            new_time_id = int(pini_st_neg + np.argmax(neg_waveform))
            new_time = AnalogSignal.times[new_time_id]

            #remove false detections
            if max(AnalogSignal.magnitude[new_time_id-wsize//2:new_time_id]) > AnalogSignal.magnitude[new_time_id]:
                if verbose:
                    print_msg("max value bigger than peak, not a spike "+str(new_time))
                continue

            plt.plot(st_neg,1,'.',color='r')
            plt.plot(new_time,1,'.',color='b')
            plt.plot((AnalogSignal.times[pini_st_neg],AnalogSignal.times[pend_st_neg]),(1,1),'.',color='k')   

            times_unique = np.append(times_unique,new_time)
            waveforms = np.append(waveforms,max(waveform).item())

    if plot:
        plt.show()
    else:
        plt.close()

    times_unique *= AnalogSignal.times.units
    waveforms = waveforms[:,sp.newaxis,sp.newaxis]

    sortinds = times_unique.argsort()
    times_unique = times_unique[sortinds]
    waveforms = waveforms[sortinds]

    SpikeTrain = neo.core.SpikeTrain(times_unique,
                                     t_start=AnalogSignal.t_start,
                                     t_stop=AnalogSignal.t_stop,
                                     sampling_rate=AnalogSignal.sampling_rate,
                                     waveforms=waveforms,
                                     sort=True)

    return SpikeTrain

#TODO: do with Templates, updating SpikeInfo
def reject_non_spikes(AnalogSignal,SpikeTrain,wsize,plot=False,verbose=False):
    to_remove = []
    for i,sp in enumerate(SpikeTrain):
        sp_id = int(sp*AnalogSignal.sampling_rate)

        waveform = AnalogSignal.magnitude[sp_id-wsize//2:sp_id+wsize//2]
        # end_waveform = AnalogSignal.magnitude[sp_id:sp_id+wsize//2]
        # ini_waveform = AnalogSignal.magnitude[sp_id-wsize//2:sp_id]

        # half = (max(waveform)+min(waveform))/2
        ampl = (max(waveform)-min(waveform))
        half = max(waveform)-(ampl)/3
        # ampl = (max(waveform)-min(waveform))

        try:
            duration_vals = np.where(np.isclose(waveform, half,atol=0.06))[0]
            dur = duration_vals[-1]-duration_vals[0]
        except:
            dur = -np.inf

        #ignore spike when first point much smaller than last
        # and crosses mid point only once.
        # or amplitude is too small for a spike
        # non_spike_cond = (waveform[0] < waveform[-1]-ampl*0.2 and np.where(waveform[waveform.size//2:]<half)[0].size==0)

        non_spike_cond = ((waveform[0] < waveform[-1]-ampl*0.2) and ~(waveform[waveform.size//2:]<half).any())
        if non_spike_cond or ampl < 0.25 or dur > 25:
            to_remove.append(i)
            # if sp > 2.25 and sp < 2.3:
            # print('ini-end','back_down','back_down_any')
            # print(sp,waveform[0] < waveform[-1]-ampl*0.2, np.where(waveform[waveform.size//2:]<half)[0].size==0,~(waveform[waveform.size//2:]<half).any())
            # print('ampl','dur')
            # print((ampl < 0.25),dur > 25)
            # #     print(waveform[0], waveform[-1],ampl*0.2, half, ampl ,dur)
            # plt.plot(waveform)
            # plt.plot(waveform.size//2,AnalogSignal.magnitude[sp_id],'.',color='k')
            # plt.plot(np.ones(waveform.shape)*half)
            # plt.plot(waveform[0],'.')
            # plt.plot(waveform.size,waveform[-1],'.')
            # plt.show()


    if plot:
        plt.show()
    else:
        plt.close()

    if verbose:
        # print_msg("Removing spike at "+str(sp))
        print_msg("Removing %d non-spikes"%len(to_remove))


    new_times = np.delete(SpikeTrain.times,to_remove)
    new_waveforms = np.delete(SpikeTrain.waveforms,to_remove)
    new_waveforms = new_waveforms[:,np.newaxis,np.newaxis]


    SpikeTrain = neo.core.SpikeTrain(new_times*AnalogSignal.times.units,
                                     t_start=AnalogSignal.t_start,
                                     t_stop=AnalogSignal.t_stop,
                                     sampling_rate=AnalogSignal.sampling_rate,
                                     waveforms=new_waveforms,
                                     sort=True)
    return SpikeTrain


def bounded_threshold(SpikeTrain, bounds):
    """
    removes all spike from a SpikeTrain which amplitudes do not fall within the
    specified static bounds.

    Args:
        SpikeTrain (neo.core.SpikeTrain): The SpikeTrain
        bounds (quantities.Quantity): a Quantity of shape (2,) with
            (lower,upper) bounds, unit [uV]

    Returns:
        neo.core.SpikeTrain: the resulting SpikeTrain
    """

    SpikeTrain = copy.deepcopy(SpikeTrain)
    peak_amps = SpikeTrain.waveforms.max(axis=1)

    good_inds = sp.logical_and(peak_amps > bounds[0], peak_amps < bounds[1])
    SpikeTrain = SpikeTrain[good_inds.flatten()]
    return SpikeTrain


def get_all_peaks(Segments, lowpass_freq=1*pq.kHz,t_max=None):
    """
    returns the values of all peaks (in all segments)
    called once - TODO future remove
    """
    peaks = []
    inds = []
    for seg in Segments:
        asig = seg.analogsignals[0]
        asig = ele.signal_processing.butter(asig, lowpass_freq=lowpass_freq)
        st = seg.spiketrains[0]
        if t_max is not None:
            st = st.time_slice(st.t_start,t_max)
        peaks.append(get_asig_at_st_times(asig,st)[0])
    peaks = sp.concatenate(peaks)
    return peaks


"""
 
 ######## ######## ##     ## ########  ##          ###    ######## ########  ######  
    ##    ##       ###   ### ##     ## ##         ## ##      ##    ##       ##    ## 
    ##    ##       #### #### ##     ## ##        ##   ##     ##    ##       ##       
    ##    ######   ## ### ## ########  ##       ##     ##    ##    ######    ######  
    ##    ##       ##     ## ##        ##       #########    ##    ##             ## 
    ##    ##       ##     ## ##        ##       ##     ##    ##    ##       ##    ## 
    ##    ######## ##     ## ##        ######## ##     ##    ##    ########  ######  
 
"""

def get_Templates(data, inds, n_samples):
    """ slice windows of n_samples (symmetric) out of data at inds """

    if type(n_samples) is tuple:
        wsizel = n_samples[0]
        wsizer = n_samples[1]
    else:
        wsizel = n_samples//2
        wsizer = n_samples//2
    # hwsize = sp.int32(n_samples/2)

    # check for valid inds
    # N = data.shape[0]
    # inds = inds[sp.logical_and(inds > hwsize, inds < N-hwsize)]

    # Templates = sp.zeros((n_samples,inds.shape[0]))
    Templates = sp.zeros((wsizel+wsizer,inds.shape[0]))
    for i, ix in enumerate(inds):
        ini = ix-wsizel
        end = ix+wsizer
        if ini < 0:
            Templates[:,i] = np.concatenate(([data[0]]*(0-ini),data[0:end]))
        elif end > data.size:
            Templates[:,i] = np.concatenate((data[ini:data.size],np.array([data[-1]]*(end-data.size))))
        else:
            Templates[:,i] = data[ini:end]


    return Templates

def outlier_reject(Templates, n_neighbors=80):
    """ detect outliers using sklearns LOF, return outlier indices """
    clf = LocalOutlierFactor(n_neighbors=n_neighbors)
    bad_inds = clf.fit_predict(Templates.T) == -1
    return bad_inds

def peak_reject(Templates, f=3):
    """ detect outliers using peak rejection criterion. Peak must be at least
    f times larger than first or last sample. Return outlier indices """
    # peak criterion
    n_samples = Templates.shape[0]
    mid_ix = int(n_samples/2)
    peak = Templates[mid_ix,:]
    left = Templates[0,:]
    right = Templates[-1,:]

    bad_inds = sp.logical_or(left > peak/f, right > peak/f)
    return bad_inds

#TODO: not useful rejection. Review bad spikes influence
def reject_spikes(Templates, SpikeInfo, unit_column, n_neighbors=80, verbose=False):
    """ reject bad spikes from Templates, updates SpikeInfo """
    units = get_units(SpikeInfo, unit_column)
    spike_labels = SpikeInfo[unit_column]
    for unit in units:
        ix = sp.where(spike_labels == unit)[0]
        a = outlier_reject(Templates[:,ix], n_neighbors)
        b = peak_reject(Templates[:,ix])
        good_inds_unit = ~sp.logical_or(a,b)

        SpikeInfo.loc[ix,'good'] = good_inds_unit

        if verbose:
            n_total = ix.shape[0]
            n_good = sp.sum(good_inds_unit)
            n_bad = sp.sum(~good_inds_unit)
            frac = n_good / n_total
            print_msg("# spikes for unit %s: total:%i \t good/bad:%i,%i \t %.2f" % (unit, n_total, n_good, n_bad, frac))

"""
 
  ######  ########  #### ##    ## ########    ##     ##  #######  ########  ######## ##       
 ##    ## ##     ##  ##  ##   ##  ##          ###   ### ##     ## ##     ## ##       ##       
 ##       ##     ##  ##  ##  ##   ##          #### #### ##     ## ##     ## ##       ##       
  ######  ########   ##  #####    ######      ## ### ## ##     ## ##     ## ######   ##       
       ## ##         ##  ##  ##   ##          ##     ## ##     ## ##     ## ##       ##       
 ##    ## ##         ##  ##   ##  ##          ##     ## ##     ## ##     ## ##       ##       
  ######  ##        #### ##    ## ########    ##     ##  #######  ########  ######## ######## 
 
"""
def lin(x, *args):
    m, b = args
    return x*m+b

class Spike_Model():
    """ models how firing rate influences spike shape. First forms a 
    lower dimensional embedding of spikes in PC space and then fits a 
    linear relationship on how the spikes change in this space. """

    def __init__(self, n_comp=5):
        self.n_comp = n_comp
        self.Templates = None
        self.frates = None
        pass

    def fit(self, Templates, frates):
        """ fits the linear model """
        
        # keep data
        self.Templates = Templates
        self.frates = frates

        # make pca from templates
        self.pca = PCA(n_components=self.n_comp)
        self.pca.fit(Templates.T)
        pca_templates = self.pca.transform(Templates.T)

        self.pfits = []
        p0 = [0,0]
        for i in range(self.n_comp):
            pfit = sp.stats.linregress(frates, pca_templates[:,i])[:2]
            self.pfits.append(pfit)

    def predict(self, fr):
        """ predicts spike shape at firing rate fr, in PC space, returns
        inverse transform: the actual spike shape as it would be measured """
        pca_i = [lin(fr,*self.pfits[i]) for i in range(len(self.pfits))]
        return self.pca.inverse_transform(pca_i)

def train_Models(SpikeInfo, unit_column, Templates, n_comp=5, verbose=True):
    """ trains models for all units, using labels from given unit_column """

    if verbose:
        print_msg("training model on: " + unit_column)

    units = get_units(SpikeInfo, unit_column)

    Models = {}
    for unit in units:
        # get the corresponding spikes - restrict training to good spikes
        SInfo = SpikeInfo.groupby([unit_column,'good']).get_group((unit,True))
        # data
        ix = SInfo['id']
        T = Templates[:,ix.values]
        # frates
        frates = SInfo['frate_fast']
        # model
        Models[unit] = Spike_Model(n_comp=n_comp)
        Models[unit].fit(T, frates)
    
    return Models

"""
 
 ########     ###    ######## ########    ########  ######  ######## #### ##     ##    ###    ######## ####  #######  ##    ## 
 ##     ##   ## ##      ##    ##          ##       ##    ##    ##     ##  ###   ###   ## ##      ##     ##  ##     ## ###   ## 
 ##     ##  ##   ##     ##    ##          ##       ##          ##     ##  #### ####  ##   ##     ##     ##  ##     ## ####  ## 
 ########  ##     ##    ##    ######      ######    ######     ##     ##  ## ### ## ##     ##    ##     ##  ##     ## ## ## ## 
 ##   ##   #########    ##    ##          ##             ##    ##     ##  ##     ## #########    ##     ##  ##     ## ##  #### 
 ##    ##  ##     ##    ##    ##          ##       ##    ##    ##     ##  ##     ## ##     ##    ##     ##  ##     ## ##   ### 
 ##     ## ##     ##    ##    ########    ########  ######     ##    #### ##     ## ##     ##    ##    ####  #######  ##    ## 
 
"""

# def local_frate1(t, mu, sig):
#     """ local firing rate - symmetric gaussian kernel with width parameter sig """
#     return 1/(sig*sp.sqrt(2*sp.pi)) * sp.exp(-0.5 * ((t-mu)/sig)**2)

def local_frate(t, mu, tau):
    """ local firing rate - anti-causal alpha kernel with shape parameter tau """
    y = (1/tau**2)*(t-mu)*sp.exp(-(t-mu)/tau)
    y[t < mu] = 0
    return y

def est_rate(spike_times, eval_times, sig):
    """ returns estimated rate at spike_times """
    rate = local_frate(eval_times[:,sp.newaxis], spike_times[sp.newaxis,:], sig).sum(1)
    return rate

def calc_update_frates(Segments, SpikeInfo, unit_column, kernel_fast, kernel_slow):
    """ calculate all firing rates for all units, based on unit_column. Updates SpikeInfo """
    # TODO - mix of new and old syntax - Segments are not needed
    
    from_units = get_units(SpikeInfo, unit_column, remove_unassinged=True)
    to_units = get_units(SpikeInfo, unit_column, remove_unassinged=False)

    # estimating firing rate profile for "from unit" and getting the rate at "to unit" timepoints
    for i, seg  in enumerate(Segments):
        for j, from_unit in enumerate(from_units):
            try:
                SInfo = SpikeInfo.groupby([unit_column,'segment']).get_group((from_unit,i))

                # spike times
                from_times = SInfo['time'].values

                # estimate its own rate at its own spike times
                rate = est_rate(from_times, from_times, kernel_fast)

                # set
                ix = SInfo['id']
                SpikeInfo.loc[ix,'frate_fast'] = rate
            except:
                # can not set it's own rate, when there are no spikes in this segment for this unit
                pass

            # the rates on others
            for k, to_unit in enumerate(to_units):
                try:
                    SInfo = SpikeInfo.groupby([unit_column, 'segment']).get_group((to_unit,i))

                    # spike times
                    to_times = SInfo['time'].values

                    # the rates of the other units at this units spike times
                    pred_rate = est_rate(from_times, to_times, kernel_slow)

                    ix = SInfo['id']
                    SpikeInfo.loc[ix,'frate_from_'+from_unit] = pred_rate
                except:
                    # similar: when no spikes in this segment, can not set
                    pass


"""
 
  ######   ######   #######  ########  ######## 
 ##    ## ##    ## ##     ## ##     ## ##       
 ##       ##       ##     ## ##     ## ##       
  ######  ##       ##     ## ########  ######   
       ## ##       ##     ## ##   ##   ##       
 ##    ## ##    ## ##     ## ##    ##  ##       
  ######   ######   #######  ##     ## ######## 
 
"""

def Rss(X,Y):
    """ sum of squared residuals """
    return sp.sum((X-Y)**2) / X.shape[0]

def score_amplitude(X,Y):
    # print(max(X) ,max(Y))
    """ if predicted spike amplitude is bigger than the original (the spike increased), 
        return worse score"""
        
    # ampl_Y = max(Y)
    # ampl_X = max(X)

    ampl_Y = max(Y)+min(Y)
    ampl_X = max(X)+min(X)

    # if ampl_Y <= ampl_X:
    #     return 0 
    # else:
    return -abs(ampl_Y - ampl_X) #If amplitude is much bigger in prediction, bad score

def double_score(X,Y):
    rss = Rss(X,Y)
    ampl = score_amplitude(X,Y)

    if ampl > 0:
        return (0.6*rss+0.4*ampl)
    else:
        return rss

def Score_spikes(Templates, SpikeInfo, unit_column, Models, score_metric=Rss, penalty=0.1):
    """ Score all spikes using Models """

    spike_ids = SpikeInfo['id'].values

    units = get_units(SpikeInfo, unit_column)
    n_units = len(units)

    n_spikes = spike_ids.shape[0]
    Scores = sp.zeros((n_spikes,n_units))
    Rates = sp.zeros((n_spikes,n_units))

    for i, spike_id in enumerate(spike_ids):
        Rates[i,:] = [SpikeInfo.loc[spike_id,'frate_from_%s' % unit] for unit in units]
        spike = Templates[:, spike_id]

        for j, unit in enumerate(units):
            # get the corresponding rate
            rate = Rates[i,j]

            # the simulated data
            spike_pred = Models[unit].predict(rate)
            Scores[i,j] = score_metric(spike, spike_pred)

    Scores[sp.isnan(Scores)] = sp.inf
    
    # penalty adjust
    unit_inds = [units.index(i) if (i != '-1')  else -1 for i in SpikeInfo[unit_column].values]
    for i, ui in enumerate(unit_inds):
        if ui != -1:
            Scores[i,ui] = Scores[i,ui] * (1+penalty)
            
    return Scores, units


"""
 
  ######  ##       ##     ##  ######  ######## ######## ########  
 ##    ## ##       ##     ## ##    ##    ##    ##       ##     ## 
 ##       ##       ##     ## ##          ##    ##       ##     ## 
 ##       ##       ##     ##  ######     ##    ######   ########  
 ##       ##       ##     ##       ##    ##    ##       ##   ##   
 ##    ## ##       ##     ## ##    ##    ##    ##       ##    ##  
  ######  ########  #######   ######     ##    ######## ##     ## 
 
"""

# def get_units_amplitudes(Templates,SpikeInfo,unit_column,lim=10):
#     units = get_units(SpikeInfo, unit_column)
#     n_units = len(units)

#     # n_spikes = spike_ids.shape[0]
#     Amplitudes = sp.zeros((n_units))

#     for i, unit in enumerate(units):
#         # the simulated data
#         ix_b = SpikeInfo.groupby([unit_column, 'good']).get_group((unit, True))['id']
#         T_b = Templates[:,ix_b].T

#         T_b = np.array([max(t)-min(t) for t in T_b])

#         Amplitudes[i] = sp.average(T_b[:lim])

    
#     return Amplitudes

def get_neighbors_amplitude(st,Templates,SpikeInfo,unit_column,unit,idx=0,t=0.3):
    times_all = SpikeInfo['time']

    idx_t = times_all.values[idx]

    ini = idx_t - t
    end = idx_t + t

    times = times_all.index[np.where((times_all.values > ini) & (times_all.values < end) & (times_all.values != idx_t))]
    neighbors = times[np.where(SpikeInfo.loc[times,unit_column].values==unit)]

    T_b = Templates[:,neighbors].T
    T_b = np.array([max(t[t.size//2:])-min(t[t.size//2:]) for t in T_b])

    return sp.average(T_b)

def get_duration(waveform):
    ampl = (max(waveform)-min(waveform))
    half = max(waveform)-(ampl)/3
    try:
        duration_vals = np.where(np.isclose(waveform, half,atol=0.06))[0]
        dur = duration_vals[-1]-duration_vals[0]
    except:
        dur = -np.inf

    return dur

def get_neighbors_duration(st,Templates,SpikeInfo,unit_column,unit,idx=0,t=0.3):
    times_all = SpikeInfo['time']

    idx_t = times_all.values[idx]

    ini = idx_t - t
    end = idx_t + t

    times = times_all.index[np.where((times_all.values > ini) & (times_all.values < end) & (times_all.values != idx_t))]
    neighbors = times[np.where(SpikeInfo.loc[times,unit_column].values==unit)]

    T_b = Templates[:,neighbors].T

    durations = []

    for waveform in T_b:
        dur = get_duration(waveform)
        durations.append(dur)

    return sp.average(durations)


def calculate_pairwise_distances(Templates, SpikeInfo, unit_column, n_comp=5):
    """ calculate all pairwise distances between Templates in PC space defined by n_comp.
    returns matrix of average distances and of their sd """

    units = get_units(SpikeInfo, unit_column)
    n_units = len(units)

    Avgs = sp.zeros((n_units,n_units))
    Sds = sp.zeros((n_units,n_units))
    
    pca = PCA(n_components=n_comp)
    X = pca.fit_transform(Templates.T)

    for i,unit_a in enumerate(units):
        for j, unit_b in enumerate(units):
            ix_a = SpikeInfo.groupby([unit_column, 'good']).get_group((unit_a, True))['id']
            ix_b = SpikeInfo.groupby([unit_column, 'good']).get_group((unit_b, True))['id']
            T_a = X[ix_a,:]
            T_b = X[ix_b,:]
            D_pw = metrics.pairwise.euclidean_distances(T_a,T_b)

            Avgs[i,j] = sp.average(D_pw)
            Sds[i,j] = sp.std(D_pw)
    return Avgs, Sds

def best_merge(Avgs, Sds, units, alpha=1):
    """ merge two units if their average between distance is lower than within distance.
    SD scaling by factor alpha regulates aggressive vs. conservative merging """
    Q = copy.copy(Avgs)
    
    for i in range(Avgs.shape[0]):
        Q[i,i] = Avgs[i,i] + alpha * Sds[i,i]

    try:
        merge_candidates = list(zip(sp.arange(Q.shape[0]),sp.argmin(Q,1)))

        # remove self
        for i in range(Q.shape[0]):
            try:
                merge_candidates.remove((i,i))
            except ValueError:
                pass

        min_ix = sp.argmin([Q[c] for c in merge_candidates])
        pair = merge_candidates[min_ix]
        merge =  [units[pair[0]],units[pair[1]]]
    except:
        merge = []

    return merge


def safe_merge(merge,SpikeInfo,unit_column,min_frac=0.75):
    for label in merge:
        frac = get_frac(SpikeInfo,unit_column,label)
        if frac < min_frac:
            print_msg("#####Not enough rate. Merge of " + ' '.join(merge)+" rejected")
            return []

    return merge

def get_frac(SpikeInfo,unit_column,unit):
    units = get_units(SpikeInfo, unit_column)
    spike_labels = SpikeInfo[unit_column]

    ix = sp.where(spike_labels == unit)[0]

    n_goods = sp.sum(SpikeInfo.loc[ix,'good'])
    n_total = ix.shape[0]

    return n_goods/n_total



def populate_block(Blk,SpikeInfo,unit_column,units):
    for i, seg in enumerate(Blk.segments):
        spike_labels = SpikeInfo.groupby(('segment')).get_group((i))[unit_column].values
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

    return Blk


def remove_spikes(SpikeInfo,unit_column,criteria):
    if criteria == 'min':
        units = get_units(SpikeInfo, unit_column)
        spike_labels = SpikeInfo[unit_column]

        n_spikes_units = []
        for unit in units:
            ix = sp.where(spike_labels == unit)[0]
            n_spikes_units.append(ix.shape[0])

        rm_unit = units[sp.argmin(n_spikes_units)]
    else:
        rm_unit = criteria

    SpikeInfo[unit_column] = SpikeInfo[unit_column].replace(rm_unit,'-1')

    # index_names = SpikeInfo[ SpikeInfo[unit_column] == rm_unit ].index
  
    # # drop these row indexes
    # # from dataFrame
    # SpikeInfo = SpikeInfo.drop(index_names, inplace = True)


def eval_model(SpikeInfo,this_unit_col,prev_unit_col,Scores,Templates,ScoresSum,AICs):
    #Re-eval model:
    n_changes = sp.sum(~(SpikeInfo[this_unit_col] == SpikeInfo[prev_unit_col]).values)
    
    Rss_sum = sp.sum(np.min(Scores,axis=1)) / Templates.shape[1]
    ScoresSum.append(Rss_sum)
    units = get_units(SpikeInfo, this_unit_col)
    AICs.append(len(units) - 2 * sp.log(Rss_sum))

    n_units = len(units)

    return n_changes,Rss_sum,ScoresSum,units,AICs,n_units

def distance_to_average(Templates,units,averages):
    D_pw = sp.zeros((len(units),Templates.shape[1]))

    for i,unit in enumerate(units):
        D_pw[i,:] = metrics.pairwise.euclidean_distances(Templates.T,averages[i].reshape(1,-1)).reshape(-1)
    
    return D_pw.T