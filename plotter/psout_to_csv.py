# -*- coding: utf-8 -*-
'''
This is a script to convert Manitoba Hydro International (MHI) PSOUT files to CSV format.
It reads the PSOUT files from a specified folder, extracts the required signals based on a figure setup CSV file, and writes the data to CSV files. 
It supports optional compression of the output files, i.e. .zip, .gz, .bz2, or .xz formats provided by Pandas' "to_csv" function.
It is designed to be used in conjunction with the process_psout set of function and uses Manitoba Hydro International (MHI) PSOUT File Reader Library.
It is designed to be run from the command line with various options for input and output paths, compression type, and verbosity.
'''
import os, glob, time
from datetime import datetime
from process_psout import getPsoutSignals
import argparse
import numpy as np
import pandas as pd

__version__ = 2.0

#-----------------------------------------------------------------------------#
parser = argparse.ArgumentParser(prog = 'psout_to_csv',
                                 description = 'Convert .psout to .csv with optional compression if required')
parser.add_argument('-p', '--psoutFolder',
                    action = 'store',
                    dest = 'psoutFolder',
                    nargs = '?',
                    metavar = 'PSOUTFOLDER',
                    default = '..\\export\\MTB_27042026094343',
                    help = 'the folder where the .psout files are located')
parser.add_argument('-o', '--outputRootFolder',
                    action = 'store',
                    dest = 'outputRootFolder',
                    nargs = '?',
                    metavar = 'OUTPUTROOTFOLDER',
                    default = '..\\export',
                    help = 'the output root folder where the date-time stamped folder will be created and the [compressed] .csv files will be saved')
parser.add_argument('-f', '--figureSetupPath',
                    action = 'store',
                    dest = 'figureSetupPath',
                    nargs = '?',
                    metavar = 'FIGURESETUPPATH',
                    default = 'figureSetup.csv',
                    help = 'the path to the figureSetup.csv file')
parser.add_argument('-c', '--compressionType',
                    action = 'store',
                    dest = 'compressionType',
                    type = str,           
                    nargs = '?',          
                    metavar = 'COMPRESSIONTYPE',
                    default = '.csv',
                    help = 'the output compression type e.g. .zip, .bz2, .gz or .xz')
parser.add_argument('-q', '--quiet',
                    action = 'store_true',
                    dest = 'QUIET',
                    default = False,
                    help = 'run quietly')
parser.add_argument('-v','--version',
                    action='version',
                    version='Version: %(prog)s '+str(__version__))

args = parser.parse_args()
#-----------------------------------------------------------------------------#

def getAllSignalnames(figureSetupPath):
    '''
    Get all the EMT signal names required from figureSetup.csv for the figures in the HTML and PNG plotter output
    '''
    
    figureSetupDF = pd.read_csv(figureSetupPath, sep=';')
    
    signamecase=[]
    for index, row in figureSetupDF.iterrows():
        if pd.isnull(row['include_in_case']):
            if not pd.isnull(row['emt_signal_1']): signamecase.append([row['emt_signal_1'], np.nan])
            if not pd.isnull(row['emt_signal_2']): signamecase.append([row['emt_signal_2'], np.nan])
            if not pd.isnull(row['emt_signal_3']): signamecase.append([row['emt_signal_3'], np.nan])
        else:
            if not pd.isnull(row['emt_signal_1']): signamecase.append([row['emt_signal_1'], row['include_in_case']])
            if not pd.isnull(row['emt_signal_2']): signamecase.append([row['emt_signal_2'], row['include_in_case']])
            if not pd.isnull(row['emt_signal_3']): signamecase.append([row['emt_signal_3'], row['include_in_case']])
            
    return pd.DataFrame(signamecase, columns=['Signalname', 'Case'])


def getCaseSignalnames(emtSignalnamesDF, case):
    '''
    Get a list of required signalnames for the specific case
    '''
    signalnames = list()
    for index, row in emtSignalnamesDF.iterrows():
        if pd.isnull(row['Case']):
            signalnames.append(row['Signalname'])
        else:
            cases = [int(val) for val in row['Case'].split(',')]    # The Cases are stored as comma separated string, and needs to be converted to a list
            if case in cases:
                signalnames.append(row['Signalname'])
    return signalnames


def convertPsouts(psoutFolder, csvFolder, outFileType, lstSignalnames):
    psoutFilesPath = glob.glob(os.path.join(psoutFolder,'*.psout'))
    os.mkdir(csvFolder)

    for psoutFilePath in psoutFilesPath:
        psoutFileNameExt = os.path.basename(psoutFilePath)
        psoutFileName = os.path.splitext(psoutFileNameExt)[0]
        projectname, case = psoutFileName.split('_')
        case = int(case)
        if not args.QUIET: print(f'Processing {psoutFileNameExt}')
        signalnames = getCaseSignalnames(lstSignalnames, case)
        dfSignals = getPsoutSignals(psoutFilePath, signalnames)
        dfSignals.set_index('time', inplace=True)
        if not args.QUIET: print(f'Writing {projectname}_{case:02}{outFileType}\n')
        dfSignals.to_csv(os.path.join(csvFolder, f'{projectname}_{case:02}{outFileType}'), sep=';', header=True, compression='infer', decimal=',') #Note: For a Danish computer, decimal=',' else numbers are read in incorrelty in Excel


def main():
    # For .psout post processing
    start = time.time()
    lstSignalnames = getAllSignalnames(args.figureSetupPath)    
    outputFolder = os.path.join(args.outputRootFolder, f'MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}')
    convertPsouts(args.psoutFolder, outputFolder, args.compressionType, lstSignalnames)
    end = time.time()
    elapsed = end - start
    print(f'Done! ({elapsed:.2f} s)')

if __name__ == '__main__':
    main()