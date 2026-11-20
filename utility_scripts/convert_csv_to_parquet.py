# -*- coding: utf-8 -*-
'''
This is a script to convert [compressed] .csv result files to the Apache Parquet format.
It works with the .csv files written by convert_psout_to_csv.py (PSCAD) and the .csv files exported by PowerFactory.
The column separator, decimal separator and the number of header rows (1 for PSCAD, 2 for PowerFactory) are detected automatically:
    - ';' as column separator implies ',' as decimal separator
    - ',' as column separator implies '.' as decimal separator
The resulting .parquet files are read with pandas.read_parquet() and give the same DataFrame as pandas.read_csv() of the original file.
Requires pyarrow.
'''
import os, sys, glob, time, gzip, bz2, lzma, zipfile
from datetime import datetime
import argparse
import pandas as pd

try:
    import pyarrow  # noqa: F401
except ImportError:
    print('Could not import pyarrow. Install it with "pip install pyarrow".')
    sys.exit(1)

__version__ = 1.0

CSV_EXTENSIONS = ('.csv', '.zip', '.gz', '.bz2', '.xz')

#-----------------------------------------------------------------------------#
parser = argparse.ArgumentParser(prog = 'convert_csv_to_parquet',
                                 description = 'Convert [compressed] .csv result files (PSCAD or PowerFactory) to .parquet')
parser.add_argument('-p', '--csvFolder',
                    action = 'store',
                    dest = 'csvFolder',
                    metavar = 'CSVFOLDER',
                    required = True,
                    help = 'the folder where the [compressed] .csv files are located (required)')
parser.add_argument('-o', '--outputRootFolder',
                    action = 'store',
                    dest = 'outputRootFolder',
                    metavar = 'OUTPUTROOTFOLDER',
                    default = None,
                    help = 'the output root folder where the date-time stamped folder will be created and the .parquet files will be saved (default: the parent folder of CSVFOLDER)')
parser.add_argument('-c', '--compression',
                    action = 'store',
                    dest = 'compression',
                    choices = ['zstd', 'snappy', 'gzip', 'none'],
                    default = 'zstd',
                    help = 'the parquet compression (default: zstd)')
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

def readFirstLines(csvFilePath, numLines=2):
    '''
    Read the first lines of a, possibly compressed, .csv file
    '''
    ext = os.path.splitext(csvFilePath)[1].lower()
    if ext == '.zip':
        with zipfile.ZipFile(csvFilePath) as zf:
            with zf.open(zf.namelist()[0]) as f:
                return [f.readline().decode('utf-8', errors='replace') for _ in range(numLines)]
    opener = {'.gz': gzip.open, '.bz2': bz2.open, '.xz': lzma.open}.get(ext, open)
    with opener(csvFilePath, 'rt', encoding='utf-8', errors='replace') as f:
        return [f.readline() for _ in range(numLines)]


def detectCsvFormat(csvFilePath):
    '''
    Detect the column separator, decimal separator and the number of header rows of a .csv file.
    Returns (sep, decimal, header) where header is 0 for one header row and [0, 1] for two header rows (PowerFactory).
    '''
    firstLine, secondLine = readFirstLines(csvFilePath)
    sep = ';' if ';' in firstLine else ','
    decimal = ',' if sep == ';' else '.'
    try:
        float(secondLine.split(sep)[0].strip().replace(decimal, '.'))
        header = 0
    except ValueError:
        header = [0, 1]
    return sep, decimal, header


def outputFileName(csvFilePath):
    '''
    Get the .parquet file name, e.g. 'Project_01.csv.gz' -> 'Project_01.parquet'
    '''
    name = os.path.basename(csvFilePath)
    while os.path.splitext(name)[1].lower() in CSV_EXTENSIONS:
        name = os.path.splitext(name)[0]
    return f'{name}.parquet'


def convertCsvs(csvFilesPath, parquetFolder, compression):
    '''
    Convert the .csv files to .parquet files. Returns the number of files written.
    '''
    os.makedirs(parquetFolder)
    filesWritten = 0

    for csvFilePath in csvFilesPath:
        csvFileNameExt = os.path.basename(csvFilePath)
        try:
            sep, decimal, header = detectCsvFormat(csvFilePath)
            if not args.QUIET: print(f"Processing {csvFileNameExt} (sep='{sep}', decimal='{decimal}', header rows={1 if header == 0 else 2})")
            df = pd.read_csv(csvFilePath, sep=sep, decimal=decimal, header=header, compression='infer')
        except Exception as e:
            print(f'Warning: Could not read {csvFileNameExt}: {e}. Skipping...')
            continue
        if df.empty:
            print(f'Warning: No data found in {csvFileNameExt}. Skipping...')
            continue
        parquetFileName = outputFileName(csvFilePath)
        if not args.QUIET: print(f'Writing {parquetFileName}\n')
        # The default (RangeIndex) index is kept, as pandas then stores the metadata needed to restore the two header rows from PowerFactory
        df.to_parquet(os.path.join(parquetFolder, parquetFileName), compression=None if compression == 'none' else compression)
        filesWritten += 1

    return filesWritten


def main():
    start = time.time()

    if not os.path.isdir(args.csvFolder):
        sys.exit(f'Error: The .csv folder "{args.csvFolder}" does not exist.')
    csvFilesPath = sorted(f for f in glob.glob(os.path.join(args.csvFolder, '*')) if os.path.isfile(f) and f.lower().endswith(CSV_EXTENSIONS))
    if not csvFilesPath:
        sys.exit(f'Error: No .csv files ({", ".join(CSV_EXTENSIONS)}) found in "{args.csvFolder}".')

    outputRootFolder = args.outputRootFolder if args.outputRootFolder else os.path.dirname(os.path.abspath(args.csvFolder))
    outputFolder = os.path.abspath(os.path.join(outputRootFolder, f'MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}'))
    filesWritten = convertCsvs(csvFilesPath, outputFolder, args.compression)
    if filesWritten == 0:
        os.rmdir(outputFolder)
        sys.exit('Error: No .parquet files were written.')
    end = time.time()
    elapsed = end - start
    print(f'Done! {filesWritten} file(s) written to "{outputFolder}" ({elapsed:.2f} s)')

if __name__ == '__main__':
    main()
