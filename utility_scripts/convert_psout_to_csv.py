# -*- coding: utf-8 -*-
'''
This is a script to convert Manitoba Hydro International (MHI) PSOUT files to CSV format.
It reads the PSOUT files from a specified folder, extracts the required signals based on a figure setup CSV file (or all PGB output channel signals if no figure setup file is given), and writes the data to CSV files.
It supports optional compression of the output files, i.e. .zip, .gz, .bz2, or .xz formats provided by Pandas' "to_csv" function.
It is designed to be used in conjunction with the process_psout set of function and uses Manitoba Hydro International (MHI) PSOUT File Reader Library.
It is designed to be run from the command line with various options for input and output paths, compression type, and verbosity.
'''
import os, sys, glob, time
from datetime import datetime
import argparse
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'plotter'))
from process_psout import listPsoutSignals
from process_results import findMtbPath, toMtbSignalName, getAllMtbSignals, getFigureSetupSignals
import numpy as np
import pandas as pd

__version__ = 2.0

#-----------------------------------------------------------------------------#
parser = argparse.ArgumentParser(prog = 'convert_psout_to_csv',
                                 description = 'Convert .psout to .csv with optional compression if required')
parser.add_argument('-p', '--psoutFolder',
                    action = 'store',
                    dest = 'psoutFolder',
                    nargs = '?',
                    metavar = 'PSOUTFOLDER',
                    required = True,
                    help = 'the folder where the .psout files are located (required)')
parser.add_argument('-o', '--outputRootFolder',
                    action = 'store',
                    dest = 'outputRootFolder',
                    nargs = '?',
                    metavar = 'OUTPUTROOTFOLDER',
                    default = None,
                    help = 'the output root folder where the date-time stamped folder will be created and the [compressed] .csv files will be saved (default: the parent folder of PSOUTFOLDER)')
parser.add_argument('-f', '--figureSetupPath',
                    action = 'store',
                    dest = 'figureSetupPath',
                    nargs = '?',
                    metavar = 'FIGURESETUPPATH',
                    default = None,
                    help = 'the path to the figureSetup.csv file. If omitted, all PGB output channel signals are extracted')
parser.add_argument('-c', '--compressionType',
                    action = 'store',
                    dest = 'compressionType',
                    type = str,           
                    nargs = '?',          
                    metavar = 'COMPRESSIONTYPE',
                    default = '.csv',
                    help = 'the output compression type e.g. .zip, .bz2, .gz or .xz')
parser.add_argument('-d', '--decimal',
                    action = 'store',
                    dest = 'decimal',
                    choices = ['.', ','],
                    default = ',',
                    help = "the decimal separator. '.' uses ',' as column separator, ',' uses ';' as column separator (default: ',')")
parser.add_argument('-l', '--list',
                    action = 'store_true',
                    dest = 'listSignals',
                    default = False,
                    help = 'list all PGB output channel signals in the first .psout file in PSOUTFOLDER and exit without converting')
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


def printPsoutSignals(psoutFilePath):
    '''
    Print all PGB output channel signal paths in the .psout file, sorted, with the array size for signal arrays.
    MTB signals are listed as 'MTB\\<signal>', also if the MTB is not placed on the main canvas.
    '''
    signals = listPsoutSignals(psoutFilePath)
    mtbPath = findMtbPath(path for path, _ in signals)
    print(f'PGB output channel signals in {psoutFilePath}:')
    if mtbPath and mtbPath != 'MTB':
        print(f'  (The MTB is located at {mtbPath} and its signals are listed as MTB\\...)')
    for path, numTraces in sorted(signals, key=lambda item: toMtbSignalName(item[0], mtbPath).lower()):
        print(f'  {toMtbSignalName(path, mtbPath)}' + (f'  [{numTraces}]' if numTraces > 1 else ''))
    print(f'{len(signals)} signal(s) found')


def convertPsouts(psoutFilesPath, csvFolder, outFileType, lstSignalnames):
    '''
    Convert the .psout files to .csv files. If lstSignalnames is None all PGB output channel signals are extracted.
    Returns the number of files written.
    '''
    os.makedirs(csvFolder)
    filesWritten = 0

    for psoutFilePath in psoutFilesPath:
        psoutFileNameExt = os.path.basename(psoutFilePath)
        psoutFileName = os.path.splitext(psoutFileNameExt)[0]
        try:
            projectname, case = psoutFileName.rsplit('_', 1)
            case = int(case)
        except ValueError:
            print(f"Warning: '{psoutFileNameExt}' does not follow the <project>_<case>.psout naming convention. Skipping...")
            continue
        if not args.QUIET: print(f'Processing {psoutFileNameExt}')
        if lstSignalnames is None:
            dfSignals = getAllMtbSignals(psoutFilePath)
        else:
            signalnames = getCaseSignalnames(lstSignalnames, case)
            dfSignals = getFigureSetupSignals(psoutFilePath, signalnames)
        if dfSignals.empty:
            print(f'Warning: No signals found for {psoutFileNameExt}. Skipping...')
            continue
        dfSignals.set_index('time', inplace=True)
        if not args.QUIET: print(f'Writing {projectname}_{case:02}{outFileType}\n')
        separator = ',' if args.decimal == '.' else ';'
        dfSignals.to_csv(os.path.join(csvFolder, f'{projectname}_{case:02}{outFileType}'), sep=separator, header=True, compression='infer', decimal=args.decimal) #Note: For a Danish computer, decimal=',' else numbers are read in incorrectly in Excel
        filesWritten += 1

    return filesWritten


def main():
    # For .psout post processing
    start = time.time()

    if not os.path.isdir(args.psoutFolder):
        sys.exit(f'Error: The .psout folder "{args.psoutFolder}" does not exist.')
    psoutFilesPath = glob.glob(os.path.join(args.psoutFolder, '*.psout'))
    if not psoutFilesPath:
        sys.exit(f'Error: No .psout files found in "{args.psoutFolder}".')

    if args.listSignals:
        printPsoutSignals(psoutFilesPath[0])
        return

    if args.figureSetupPath is None:
        if not args.QUIET: print('No figureSetup.csv specified. Extracting all PGB output channel signals.')
        lstSignalnames = None
    elif not os.path.isfile(args.figureSetupPath):
        sys.exit(f'Error: The figureSetup.csv file "{args.figureSetupPath}" does not exist.')
    else:
        lstSignalnames = getAllSignalnames(args.figureSetupPath)

    outputRootFolder = args.outputRootFolder if args.outputRootFolder else os.path.dirname(os.path.abspath(args.psoutFolder))
    outputFolder = os.path.abspath(os.path.join(outputRootFolder, f'MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}'))
    filesWritten = convertPsouts(psoutFilesPath, outputFolder, args.compressionType, lstSignalnames)
    if filesWritten == 0:
        os.rmdir(outputFolder)
        sys.exit('Error: No .csv files were written.')
    end = time.time()
    elapsed = end - start
    print(f'Done! {filesWritten} file(s) written to "{outputFolder}" ({elapsed:.2f} s)')

if __name__ == '__main__':
    main()