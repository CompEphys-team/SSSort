import sys
import os
from pathlib import Path
import dill

import neo
import quantities as pq

import numpy as np
from tools.functions import print_msg, select_by_dict

def asc2seg(path):
    """ reads an autospike .asc file into neo segment """
    header_rows = 6

    with open(path, 'r') as fH:
        lines = [line.strip() for line in fH.readlines()]

    header = lines[:header_rows]
    data = lines[header_rows:]
    rec_fac = float(header[3].split(' ')[3])
    fs = float(header[4].split(' ')[3])
    Data  = np.array([d.split('\t')[1] for d in data],dtype='float')
    Asig = neo.core.AnalogSignal(Data, units=pq.uV, sampling_rate=fs*pq.Hz)
    segment = neo.core.Segment()
    segment.analogsignals = [Asig]
    segment.annotate(filename=str(path))
    return segment

def raw2seg(path, fs, dtype, scale=1):
    """ reads a raw binary file into a neo segment. Requires manual specification of data type and sampling rate """
    Data = np.fromfile(path, dtype=dtype)
    Data *= scale
    print(Data.shape)
    Asig = neo.core.AnalogSignal(Data, units=pq.uV, sampling_rate=fs*pq.Hz)
    segment = neo.core.Segment()
    segment.analogsignals = [Asig]
    return segment


def asc2seg_noheader(path, fs, unit=pq.uV, header_rows=6, col=1):
    # """ reads an autospike .asc file into neo segment """
    # with open(path, 'r') as fH:
    #     lines = [line.strip() for line in fH.readlines()]

    # header = lines[:header_rows]
    # data = lines[header_rows:]
    # # fs = float(header[4].split(' ')[3])
    # print(len(data))
    # Data = np.array([d.split('\t')[1] for d in data], dtype='float')
    Data = np.loadtxt(path, skiprows=header_rows)
    Data = Data[:,col]
    print(Data.shape)
    Asig = neo.core.AnalogSignal(Data, units=unit, sampling_rate=fs*pq.Hz)
    segment = neo.core.Segment()
    segment.analogsignals = [Asig]
    segment.annotate(filename=str(path))
    return segment

def seg2dill(Seg, path):
    """ dumps a seg via dill"""
    with open(path, 'wb') as fH:
        print_msg("dumping neo.segment to %s" % path)
        dill.dump(Seg, fH)

def dill2seg(path):
    """ dumps a seg via dill"""
    with open(path, 'rb') as fH:
        print_msg("reading neo.segment from %s" % path)
        Seg = dill.load(fH)
    return Seg

def dill2blk(path):
    with open(path, 'rb') as fH:
        print_msg("reading neo.block from %s" % path)
        Blk = dill.load(fH)
    return Blk

def blk2dill(Blk, path):
    """ dumps a block via dill"""
    with open(path, 'wb') as fH:
        print_msg("dumping neo.block to %s" % path)
        dill.dump(Blk, fH)

def get_data(path):
    """ reads data at path """
    ext = os.path.splitext(path)[1]
    if ext == '.dill':
        with open(path, 'rb') as fH:
            Blk = dill.load(fH)
    else: 
        print_msg("Error reading data, 'get_data' expects .dill file")
    return Blk

def save_data(Blk, path):
    """ saves data to path """
    ext = os.path.splitext(path)[1]
    if ext == '.dill':
        blk2dill(Blk, path)

def save_all(results_folder, SpikeInfo, Blk, FinalSpikes= False):
    # store SpikeInfo
    outpath = results_folder / 'SpikeInfo.csv'
    print_msg("saving SpikeInfo to %s" % outpath)
    SpikeInfo.to_csv(outpath,index= False)

    if FinalSpikes:
        # store separate spike time lists for A and B cells
        for unit in ['A','B']:
            st = SpikeInfo.groupby('unit_final').get_group(unit)['time']
            outpath = results_folder / ('Spikes'+unit+'.csv')
            np.savetxt(outpath, st)
    
    # store Block
    outpath = results_folder / 'result.dill'
    print_msg("saving Blk as .dill to %s" % outpath)
    blk2dill(Blk, outpath)

    print_msg("data is stored")
        
