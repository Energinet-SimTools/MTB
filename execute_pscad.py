'''
Executes the Powerplant model testbench in PSCAD.
'''
from __future__ import annotations 
import os
import sys

try:
    LOG_FILE = open('execute_pscad.log', 'w')
except:
    print('Failed to open log file. Logging to file disabled.')
    LOG_FILE = None #type: ignore

def print(*args): #type: ignore
    '''
    Overwrites the print function to also write to a log file.
    '''
    outputString = ''.join(map(str, args)) + '\n' #type: ignore
    sys.stdout.write(outputString)
    if LOG_FILE:
        LOG_FILE.write(outputString)
        LOG_FILE.flush()

if __name__ == '__main__':
    print('Python', sys.version)
    #Ensure right working directory
    executePath = os.path.abspath(__file__)
    executeFolder = os.path.dirname(executePath)
    os.chdir(executeFolder)
    if not executeFolder in sys.path:
        sys.path.append(executeFolder)
    print(f'CWD: {executeFolder}')
    print('sys.path:')
    for path in sys.path:
        if path != '':
            print(f'\t{path}')
    
from configparser import ConfigParser

config = ConfigParser()

config.read('config.ini')

sheetPath = config.get('General', 'Casesheet path', fallback='testcases.xlsx').strip()
exportPath = config.get('General', 'Export folder', fallback='export').strip()
pythonPath = config.get('Python', 'Python path', fallback='').strip()
volley = config.getint('PSCAD', 'Volley', fallback=16)
animation = config.getboolean('PSCAD', 'Animation', fallback=False)
fortranVersion = config.get('PSCAD', 'Fortran version').strip()
workspacePath = config.get('PSCAD', 'Workspace').strip()

if pythonPath:
    sys.path.append(pythonPath)

from datetime import datetime
import shutil
import psutil #type: ignore
from typing import List, Optional
import pandas as pd
import warnings
import sim_interface as si
import case_setup as cs
from pscad_update_ums import updateUMs

# To suppress openpyxl warning messages
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")      

try:
    import mhi.pscad
except ImportError:
    print("Could not import mhi.pscad. Make sure PSCAD Automation Library is installed and available in your Python environment.")
    sys.exit(1)

def connectPSCAD() -> mhi.pscad.PSCAD:
    pid = [p.info for p in psutil.process_iter(attrs=['pid', 'name']) if 'Pscad.exe' in p.info['name']][0]['pid']
    ports = [con.laddr.port for con in psutil.net_connections() if con.status == psutil.CONN_LISTEN and con.pid == pid]

    if len(ports) == 0: #type: ignore
        print('No PSCAD listening ports found!\n')
        return None
    elif len(ports) > 1: #type: ignore
        print('WARNING: Multiple PSCAD listening ports found. Using the first one.')
        
    try:
        pscad = mhi.pscad.connect(port = ports[0]) #type: ignore
    except (AttributeError, Exception) as e:
        print(f"Connection failed: {e}. Proceeding to launch new instance.\n")
        return None
     
    return pscad    
    
def startPSCAD():
   
    # Launch PSCAD
    print('Starting PSCAD v5.0.2\n')
    pscad = mhi.pscad.launch(version='5.0.2',
                             silence=True,
                             splash=False,
                             minimize=True,
                             load_user_profile=False)
    
    if pscad:
        ## PSCAD Licence management
        # Release certificate if already exists
        pscad.release_certificate()
        
        # Lets try to get a license, query server for list of available licenses.
        # Grab the first license found and use the certificate to license PSCAD
        if(pscad.logged_in() == True):
            certs = pscad.get_available_certificates()
            if len(certs) > 0:
                # finding a license with open instances
                for cert in list(certs.values()):
                    if cert.meets([('EMTDC Instances', volley)]):
                        print('Acquiring Certificate Now! : %s', str(cert))
                        pscad.get_certificate(cert)
                        print('PSCAD should have a license now\n')
                        break
                if pscad.licensed() == False:
                    print(f'All PSCAD Licenses that meet the volley requirement of {volley}, are in use right now!')
            else:
                print('No certificate licenses available on server')
                print('Starting PSCAD in unlicensed mode')
        else:
            print('You must log in (top right on PSCAD) and then restart script')
                
        ## Set some PSCAD settings - can only be done with a valid license
        pscad_options = {'start_page_startup':False,
                         'cl_use_advanced': True}
        
        pscad.settings(pscad_options)

        # Open PSCAD workspace
        pscad.load(workspacePath)

        # Get valid Fortran comilers for this machine        
        available_fortrans = pscad.setting_range('fortran_version')
        valid_fortrans = [f for f in available_fortrans if 'GFortran' not in f]

        if fortranVersion == '' or 'GFortran' in fortranVersion or fortranVersion not in valid_fortrans:
            print('A valid Fortran compiler other than GFortran has to be specified when running from the command line')
            print('Valid options for this machine:')
            for valid_fortran in valid_fortrans:
                print(f'  * {valid_fortran}')
            print()
            exitPSCAD(pscad)
            sys.exit(1)
        else:
            print(f'Fortran version set to {fortranVersion}')
            pscad.settings({'fortran_version': fortranVersion})
                                
        return pscad
    else:
        print('PSCAD could not be started')
        return    
    
def exitPSCAD(pscad):
    print('Releasing All Certificate...')
    pscad.release_all_certificates()
    print('Quiting PSCAD...')
    pscad.quit()
    print('Done.')   
        
def outToCsv(srcPath : str, dstPath : str):
    """
    Converts PSCAD .out file into .csv file
    """
    with open(srcPath) as out, \
            open(dstPath, 'w') as csv:
        csv.writelines(','.join(line.split()) +'\n' for line in out)

def moveFiles(srcPath : str, dstPath : str, types : List[str], suffix : str = '') -> None:
    '''
    Moves files of the specified types from srcPath to dstPath.
    '''
    for file in os.listdir(srcPath):
        _, typ = os.path.splitext(file)
        if typ in types:
            shutil.move(os.path.join(srcPath, file), os.path.join(dstPath, file + suffix))

def taskIdToRank(psoutFolder : str, projectName : str, emtCases : List[cs.Case], rank: int):
    '''
    Changes task ID to rank of the .psout files in psoutFolder.
    '''
    for file in os.listdir(psoutFolder):
        _, fileName = os.path.split(file)
        root, typ = os.path.splitext(fileName)
        if rank is None:
            if typ == '.psout_taskid' and root.startswith(projectName + '_'):
                suffix = root[len(projectName) + 1:]
                parts = suffix.split('_')
                if  len(parts) > 0 and parts[0].isnumeric():
                    taskId = int(parts[0])
                    if taskId - 1 < len(emtCases):
                        parts[0] = str(emtCases[taskId  - 1].rank)
                        newName = projectName + '_' + '_'.join(parts) + typ.replace('_taskid', '')
                        print(f'Renaming {fileName} to {newName}')
                        os.rename(os.path.join(psoutFolder, fileName), os.path.join(psoutFolder, newName))
                    else:
                        print(f'WARNING: {fileName} has a task ID that is out of bounds. Ignoring file.')
                else:
                    print(f'WARNING: {fileName} has an invalid task ID. Ignoring file.')
        else:
            if typ == '.psout_taskid':
                newName = f'{projectName}_{rank}.psout'
            else:
                print(f'WARNING: {fileName} is of unknown type. Ignoring file.')
                continue
            print(f'Renaming {fileName} to {newName}')
            os.rename(os.path.join(psoutFolder, fileName), os.path.join(psoutFolder, newName))
            
def cleanUpPsoutFiles(buildPath : str, exportPath : str, projectName : str) -> str:
    '''
    Cleans up the build folder by moving .psout files to an time-stamped results folder in the export path.
    Return path to .psout folder.
    '''
    # Create the exportPath if requied
    if not os.path.exists(exportPath):
        os.mkdir(exportPath)
    else:
        for dir in os.listdir(exportPath):
            _dir = os.path.join(exportPath, dir)
            if os.path.isdir(_dir) and dir.startswith('MTB_'):
                if os.listdir(_dir) == []:
                    shutil.rmtree(_dir)

    #Creating a datetime stamped results subfolder
    resultsFolder = f'MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}'

    #Move .psout files away from build folder into results subfolder in the export folder
    psoutFolder = os.path.join(exportPath, resultsFolder)
    os.mkdir(psoutFolder)
    moveFiles(buildPath, psoutFolder, ['.psout'], '_taskid')

    return psoutFolder

def cleanBuildfolder(buildPath : str):
    '''
    "Cleans" the build folder by trying to delete it.
    '''
    try:
        shutil.rmtree(buildPath)
    except FileNotFoundError:
        pass

def findMTB(pscad : mhi.pscad.PSCAD) -> mhi.pscad.UserCmp:
    '''
    Finds the MTB block in the project.
    '''
    projectLst = pscad.projects()
    MTBcand : Optional[mhi.pscad.UserCmp] = None
    for prjDic in projectLst:
        if prjDic['type'].lower() == 'case':
            project = pscad.project(prjDic['name'])
            MTBs : List[mhi.pscad.UserCmp]= project.find_all(Name_='$MTB_9124$') #type: ignore
            if len(MTBs) > 0:
                if MTBcand or len(MTBs) > 1:
                    exit('Multiple MTB blocks found in workspace.')
                else:
                    MTBcand = MTBs[0]

    if not MTBcand:
        exit('No MTB block found in workspace.')
    return MTBcand

def addInterfaceFile(project : mhi.pscad.Project):
    '''
    Adds the interface file to the project.
    '''
    resList = project.resources()
    for res in resList:
        if res.path == r'.\interface.f' or res.name == 'interface.f':
            return

    print('Adding interface.f to project')
    project.create_resource(r'.\interface.f')

def writeCaseRankTaskIdCSV(emtCases):
    data = []
    for idx, case in enumerate(emtCases, start=1):
        data.append({'Case Rank': case.rank, 'Task ID': idx, 'Case Name': case.Name})
    
    df = pd.DataFrame(data)
    df.to_csv('caseRankTaskID.csv', index=False)
    
def main():
    print()
    print('execute_pscad.py started at:', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '\n')
    
    pscad = connectPSCAD()
    
    # If the script is not executed from within PSCAD, run PSCAD as an external client
    if pscad is None: 
        runningAsEternalClient = True
        pscad = startPSCAD()
    else:
        runningAsEternalClient = False

    plantSettings, channels, _, _, emtCases = cs.setup(sheetPath, pscad = True, pfEncapsulation = None)

    #Print plant settings from casesheet
    print('Plant settings:')
    for setting in plantSettings.__dict__:
        print(f'{setting} : {plantSettings.__dict__[setting]}')
    print()
    
    #Prepare MTB based on execution mode
    MTB = findMTB(pscad)
    project = pscad.project(MTB.project_name)
    caseList = []
    for case in emtCases:
        caseList.append(case.rank)
    
    if MTB.parameters()['par_mode'] == 'VOLLEY':
        #Output ranks in relation to task 
        print('---------EXECUTING VOLLEY MODE---------')
        print('Rank / Task ID / Casename:')
        for case in emtCases:
            print(f'{case.rank} / {emtCases.index(case) + 1} / {case.Name}')
        singleRank = None
    elif MTB.parameters()['par_mode'] == 'MANUAL' and MTB.parameters()['par_manualrank'] in caseList:
        #Output rank in relation to task id
        singleRank = MTB.parameters()['par_manualrank']
        singleName = emtCases[caseList.index(MTB.parameters()['par_manualrank'])].Name
        print(f'Executing only Rank {singleRank}: {singleName}')
        print(f'Excecuting only Rank {singleRank}: {singleName}')
    else:
        raise ValueError('Invalid rank selected for par_manualrank in MTB block.')

    writeCaseRankTaskIdCSV(emtCases) # Save "Case Rank", "TaskID", "Case Name" in a .csv file for PSCAD OOM Recovery

    print()
    si.renderFortran('interface.f', channels)
    
    #Set executed flag
    MTB.parameters(executed = 1) #type: ignore  

    #Update pgb names for all unit measurement components
    updateUMs(pscad)

    #Add interface file to project
    addInterfaceFile(project)

    buildFolder : str = project.temp_folder #type: ignore
    cleanBuildfolder(buildFolder) #type: ignore

    project.parameters(time_duration = 999,
                       time_step = plantSettings.PSCAD_Timestep,
                       sample_step = '1000',
                       PlotType = 'PSOUT',
                       output_filename = f'{plantSettings.Projectname}.psout',
                       SnapType = 0) #type: ignore

    pscad.remove_all_simulation_sets()
    pmr = pscad.create_simulation_set('MTB')
    pmr.add_tasks(MTB.project_name)
    project_pmr = pmr.task(MTB.project_name)
    
    project_pmr.parameters(ammunition = len(emtCases) if MTB.parameters()['par_mode'] == 'VOLLEY' else 1,
                           volley = volley,
                           affinity = 2) #type: ignore
    
    project_pmr.overrides(state_animation = animation,
                          only_in_use_channels = True)
                          
    pscad.run_simulation_sets('MTB') #type: ignore ??? By sideeffect changes current working directory ???
    os.chdir(executeFolder)

    psoutFolder = cleanUpPsoutFiles(buildFolder, exportPath, plantSettings.Projectname)
    print()
    taskIdToRank(psoutFolder, plantSettings.Projectname, emtCases, singleRank)

    print('execute_pscad.py finished at: ', datetime.now().strftime('%m-%d %H:%M:%S'))
    
    if runningAsEternalClient:
        exitPSCAD(pscad)

if __name__ == '__main__':
    main()

if LOG_FILE:
    LOG_FILE.close()
