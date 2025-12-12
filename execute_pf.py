'''
Executes the Powerplant model testbench in Powerfactory.
'''
from __future__ import annotations 
DEBUG = True
import os
#Ensure right working directory
executePath = os.path.abspath(__file__)
executeFolder = os.path.dirname(executePath)
os.chdir(executeFolder)

from configparser import ConfigParser

class readConfig:
  def __init__(self) -> None:
    self.cp = ConfigParser(allow_no_value=True)
    self.cp.read('config.ini')
    self.parsedConf = self.cp['config']
    self.sheetPath = str(self.parsedConf['Casesheet path'])
    self.pythonPath = str(self.parsedConf['Python path'])
    self.volley = int(self.parsedConf['Volley'])
    self.parallel = bool(self.parsedConf['Parallel'])
    self.exportPath = str(self.parsedConf['Export folder'])
    self.QDSLcopyGrid = str(self.parsedConf['QDSL copy grid'])

config = readConfig()
import sys
sys.path.append(config.pythonPath)

from typing import Optional, Tuple, List, Union
if getattr(sys, 'gettrace', None) is not None:
  sys.path.append('C:\\Program Files\\DIgSILENT\\PowerFactory 2024 SP4\\Python\\3.8')
import powerfactory as pf #type: ignore

import re
import time
from datetime import datetime
import case_setup as cs
import sim_interface as si

def script_GetExtObj(script : pf.ComPython, name : str) -> Optional[pf.DataObject]:
  '''
  Get script external object.
  '''
  retVal : List[Union[int, pf.DataObject, None]] = script.GetExternalObject(name)
  assert isinstance(retVal[1], (pf.DataObject, type(None)))
  return retVal[1]

def script_GetStr(script : pf.ComPython, name : str) -> Optional[str]:
  '''
  Get script string parameter.
  '''
  retVal : List[Union[int, str]] = script.GetInputParameterString(name)
  if retVal[0] == 0:
    assert isinstance(retVal[1], str)
    return retVal[1]
  else:
    return None

def script_GetDouble(script : pf.ComPython, name : str) -> Optional[float]:
  '''
  Get script double parameter.
  '''
  retVal : List[Union[int, float]] = script.GetInputParameterDouble(name)
  if retVal[0] == 0:
    assert isinstance(retVal[1], float)
    return retVal[1]
  else:
    return None

def script_GetInt(script : pf.ComPython, name : str) -> Optional[int]:
  '''
  Get script integer parameter.
  '''
  retVal : List[Union[int, int]] = script.GetInputParameterInt(name)
  if retVal[0] == 0:
    assert isinstance(retVal[1], int)
    return retVal[1]
  else:
    return None

def connectPF() -> Tuple[pf.Application, pf.IntPrj, pf.ComPython, int]:
  '''
  Connects to the powerfactory application and returns the application, project and this script object.
  '''
  app : Optional[pf.Application] = pf.GetApplicationExt()
  if not app:
    raise RuntimeError('No connection to powerfactory application')
  app.Show()
  app.ClearOutputWindow()
  app.PrintInfo(f'Powerfactory application connected externally. Executable: {sys.executable}')
  app.PrintInfo(f'Imported powerfactory module from {pf.__file__}')

  version : str = pf.__version__
  pfVersion = 2000 + int(version.split('.')[0])
  app.PrintInfo(f'Powerfactory version registred: {pfVersion}')

  project : Optional[pf.IntPrj] = app.GetActiveProject() #type: ignore

  if DEBUG:
    while project is None:
        time.sleep(1)
        project = app.GetActiveProject() #type: ignore

  assert project is not None

  networkData = app.GetProjectFolder('netdat')
  assert networkData is not None

  thisScript : pf.ComPython = networkData.SearchObject('MTB\\MTB\\execute.ComPython') #type: ignore
  assert thisScript is not None

  return app, project, thisScript, pfVersion

def resetProjectUnits(project : pf.IntPrj) -> None:
  '''
  Resets the project units to the default units.
  '''
  SetPrj = project.SearchObject('Settings.SetFold')
  if SetPrj:
    SetPrj.Delete()

  project.Deactivate() 
  project.Activate() 

def setupResFiles(app : pf.Application, script : pf.ComPython, root : pf.DataObject):
  '''
  Setup the result files for the studycase.
  '''
  elmRes : pf.ElmRes = app.GetFromStudyCase('ElmRes') #type: ignore
  assert elmRes is not None

  measurementBlock = root.SearchObject('measurements.ElmDsl')
  assert measurementBlock is not None

  elmRes.AddVariable(measurementBlock, 's:Ia_pu')
  elmRes.AddVariable(measurementBlock, 's:Ib_pu')
  elmRes.AddVariable(measurementBlock, 's:Ic_pu')
  elmRes.AddVariable(measurementBlock, 's:Vab_pu')
  elmRes.AddVariable(measurementBlock, 's:Vag_pu')
  elmRes.AddVariable(measurementBlock, 's:Vbc_pu')
  elmRes.AddVariable(measurementBlock, 's:Vbg_pu')
  elmRes.AddVariable(measurementBlock, 's:Vca_pu')
  elmRes.AddVariable(measurementBlock, 's:Vcg_pu')
  elmRes.AddVariable(measurementBlock, 's:f_hz')
  elmRes.AddVariable(measurementBlock, 's:neg_Id_pu')
  elmRes.AddVariable(measurementBlock, 's:neg_Imag_pu')
  elmRes.AddVariable(measurementBlock, 's:neg_Iq_pu')
  elmRes.AddVariable(measurementBlock, 's:neg_Vmag_pu')
  elmRes.AddVariable(measurementBlock, 's:pos_Id_pu') 
  elmRes.AddVariable(measurementBlock, 's:pos_Imag_pu') 
  elmRes.AddVariable(measurementBlock, 's:pos_Iq_pu') 
  elmRes.AddVariable(measurementBlock, 's:pos_Vmag_pu') 
  elmRes.AddVariable(measurementBlock, 's:ppoc_pu')  
  elmRes.AddVariable(measurementBlock, 's:qpoc_pu') 

  signals = [
      'mtb_s_pref_pu.ElmDsl',
      'mtb_s_qref.ElmDsl',
      'mtb_s_qref_q_pu.ElmDsl',
      'mtb_s_qref_qu_pu.ElmDsl',
      'mtb_s_qref_pf.ElmDsl',
      'mtb_s_qudroop.ElmDsl',
      'mtb_s_pavail_pu.ElmDsl',
      'mtb_s_qref_3.ElmDsl',
      'mtb_s_qref_4.ElmDsl',
      'mtb_s_qref_5.ElmDsl',
      'mtb_s_qref_6.ElmDsl',
      'mtb_s_1.ElmDsl',
      'mtb_s_2.ElmDsl',
      'mtb_s_3.ElmDsl',
      'mtb_s_4.ElmDsl',
      'mtb_s_5.ElmDsl',
      'mtb_s_6.ElmDsl',
      'mtb_s_7.ElmDsl',
      'mtb_s_8.ElmDsl',
      'mtb_s_9.ElmDsl',
      'mtb_s_10.ElmDsl'
  ]

  for signal in signals:
    signalObj = root.SearchObject(signal)
    assert signalObj is not None
    elmRes.AddVariable(signalObj, 's:yo')

  # Include measurement objects and set alias
  for i in range(1, 100):
    Meas_obj_n = script_GetExtObj(script, f'Meas_obj_{i}')
    if Meas_obj_n is not None:
      Meas_obj_n_signals = script_GetStr(script, f'Meas_obj_{i}_signals')
      assert Meas_obj_n_signals is not None
      Meas_obj_n_signals = Meas_obj_n_signals.split(';')

      for signal in Meas_obj_n_signals:
        if signal != '':
          elmRes.AddVariable(Meas_obj_n, signal)
      
      Meas_obj_n_alias = script_GetStr(script, f'Meas_obj_{i}_alias')
      assert Meas_obj_n_alias is not None
      Meas_obj_n.SetAttribute('for_name', Meas_obj_n_alias)

def setupExport(app : pf.Application, filename : str):
    '''
    Setup the export component for the studycase.
    '''
    comRes : pf.ComRes = app.GetFromStudyCase('ComRes') #type: ignore
    elmRes : pf.ElmRes = app.GetFromStudyCase('ElmRes') #type: ignore
    assert comRes is not None
    assert elmRes is not None

    csvFileName = f'{filename}.csv'
    comRes.SetAttribute('pResult', elmRes)
    comRes.SetAttribute('iopt_exp', 6)
    comRes.SetAttribute('iopt_sep', 0)
    comRes.SetAttribute('ciopt_head', 1)
    comRes.SetAttribute('iopt_locn', 4)
    comRes.SetAttribute('dec_Sep', ',')
    comRes.SetAttribute('col_Sep', ';')
    comRes.SetAttribute('f_name', csvFileName)
    
def setupPlots(app : pf.Application, root : pf.DataObject):
  '''
  Setup the plots for the studycase.
  '''
  measurementBlock = root.SearchObject('measurements.ElmDsl') 
  assert measurementBlock is not None

  board : pf.SetDesktop = app.GetFromStudyCase('SetDesktop') #type: ignore
  assert board is not None

  plots : List[pf.GrpPage]= board.GetContents('*.GrpPage',1) #type: ignore

  for p in plots:
    p.RemovePage()

  # Create pages
  plotPage : pf.GrpPage = board.GetPage('Plot', 1, 'GrpPage') #type: ignore
  assert plotPage is not None

  # PQ plot
  pqPlot : pf.PltLinebarplot = plotPage.GetOrInsertPlot('PQ', 1) #type: ignore
  assert pqPlot is not None
  pqPlotDS : pf.PltDataseries = pqPlot.GetDataSeries() #type: ignore
  assert pqPlotDS is not None
  pqPlotDS.AddCurve(measurementBlock, 's:ppoc_pu') 
  pqPlotDS.AddCurve(measurementBlock, 's:qpoc_pu') 
  pqPlot.DoAutoScale() 

  # U plot
  uPlot : pf.PltLinebarplot = plotPage.GetOrInsertPlot('U', 1) #type: ignore
  assert uPlot is not None
  uPlotDS : pf.PltDataseries = uPlot.GetDataSeries() #type: ignore
  assert uPlotDS is not None
  uPlotDS.AddCurve(measurementBlock, 's:pos_Vmag_pu') 
  uPlotDS.AddCurve(measurementBlock, 's:neg_Vmag_pu') 
  uPlot.DoAutoScale() 

  # I plot
  iPlot : pf.PltLinebarplot = plotPage.GetOrInsertPlot('I', 1) #type: ignore 
  assert iPlot is not None
  iPlotDS : pf.PltDataseries = iPlot.GetDataSeries() #type: ignore
  assert iPlotDS is not None
  iPlotDS.AddCurve(measurementBlock, 's:pos_Id_pu') 
  iPlotDS.AddCurve(measurementBlock, 's:pos_Iq_pu') 
  iPlotDS.AddCurve(measurementBlock, 's:neg_Id_pu') 
  iPlotDS.AddCurve(measurementBlock, 's:neg_Iq_pu') 
  iPlot.DoAutoScale() 

  # F plot
  fPlot : pf.PltLinebarplot = plotPage.GetOrInsertPlot('F', 1) #type: ignore
  assert fPlot is not None
  fPlotDS : pf.PltDataseries = fPlot.GetDataSeries() #type: ignore
  assert fPlotDS is not None
  fPlotDS.AddCurve(measurementBlock, 's:f_hz') 
  fPlot.DoAutoScale() 

  app.WriteChangesToDb()

def addCustomSubscribers(thisScript : pf.ComPython, channels : List[si.Channel]) -> None:
  '''
  Add custom subscribers to the channels. For example, references applied as parameter events directly to control blocks.
  '''
  def getChnlByName(name : str) -> si.Channel:
    for ch in channels:
      if ch.name == name:
        return ch
    raise RuntimeError(f'Channel {name} not found.')

  custConfStr = script_GetStr(thisScript, 'sub_conf_str')
  assert isinstance(custConfStr, str)

  def convertToConfStr(param : str, signal : str) -> str:
    sub_obj = script_GetExtObj(thisScript, f'{param}_sub')
    sub_attrib = script_GetStr(thisScript, f'{param}_sub_attrib')
    assert isinstance(sub_attrib, str)
    if sub_obj is not None and sub_attrib != '':
      sub_scale = script_GetDouble(thisScript, f'{param}_sub_scale')
      assert isinstance(sub_scale, float)
      sub_signal = getChnlByName(f'{signal}')
      assert isinstance(sub_signal, si.Signal)
      return f'\\{sub_obj.GetFullName()}:{sub_attrib}={signal}:S~{sub_scale} * x' 
    return ''

  pavail_conf = convertToConfStr('Pavail', 'mtb_s_pavail_pu')
  pref_conf = convertToConfStr('Pref', 'mtb_s_pref_pu')
  qref1_conf = convertToConfStr('Qref_q', 'mtb_s_qref_q_pu')
  qref2_conf = convertToConfStr('Qref_qu', 'mtb_s_qref_qu_pu')
  qref3_conf = convertToConfStr('Qref_pf', 'mtb_s_qref_pf')
  qudroop_conf = convertToConfStr('QUdroop', 'mtb_s_qudroop')
  custom1_conf = convertToConfStr('Custom1', 'mtb_s_1')
  custom2_conf = convertToConfStr('Custom2', 'mtb_s_2')
  custom3_conf = convertToConfStr('Custom3', 'mtb_s_3')
  custom4_conf = convertToConfStr('Custom4', 'mtb_s_4')
  custom5_conf = convertToConfStr('Custom5', 'mtb_s_5')
  custom6_conf = convertToConfStr('Custom6', 'mtb_s_6')
  custom7_conf = convertToConfStr('Custom7', 'mtb_s_7')
  custom8_conf = convertToConfStr('Custom8', 'mtb_s_8')
  custom9_conf = convertToConfStr('Custom9', 'mtb_s_9')
  custom10_conf = convertToConfStr('Custom10', 'mtb_s_10')

  configs = (
              custConfStr.split(';') + 
              [pavail_conf, pref_conf, qref1_conf, qref2_conf, qref3_conf,qudroop_conf, 
               custom1_conf, custom2_conf, custom3_conf, custom4_conf, custom5_conf, 
               custom6_conf, custom7_conf, custom8_conf, custom9_conf, custom10_conf]
             )

  confFilterStr = r"^([^:*?=\",~|\n\r]+):((?:\w:)?\w+(?::\d+)?)=(\w+):(S|s|S0|s0|R|r|T|t|C|c)~(.*)"
  confFilter = re.compile(confFilterStr)

  for config in configs:
    confFilterMatch = confFilter.match(config)
    if confFilterMatch is not None:
      obj = confFilterMatch.group(1)
      attrib = confFilterMatch.group(2)
      sub = confFilterMatch.group(3)
      typ = confFilterMatch.group(4)
      lamb = confFilterMatch.group(5)

      chnl = getChnlByName(sub)
      if isinstance(chnl, si.Signal):
        if typ.lower() == 's' or typ.lower() == 'c':
          chnl.addPFsub_S(obj, attrib, lambda _,x,l=lamb : eval(l))
        elif typ.lower() == 's0':
          chnl.addPFsub_S0(obj, attrib, lambda _,x,l=lamb : eval(l)) #Not exactly safe
        elif typ.lower() == 'r':
          chnl.addPFsub_R(obj, attrib, lambda _,x,l=lamb : eval(l))
        elif typ.lower() == 't':
          chnl.addPFsub_T(obj, attrib, lambda _,x,l=lamb : eval(l))
      elif isinstance(chnl, si.Constant) or isinstance(chnl, si.PfObjRefer) or isinstance(chnl, si.String):
          chnl.addPFsub(obj, attrib)

def main():
  # Connect to Powerfactory
  app, project, thisScript, pfVersion = connectPF()

  # Check if any studycase is active
  currentStudyCase : Optional[pf.IntCase] = app.GetActiveStudyCase() #type: ignore

  if currentStudyCase is None:
    raise RuntimeError('Please activate a studycase.')

  studyTime : int = currentStudyCase.GetAttribute('iStudyTime')

  # Get and check for active grids
  networkData = app.GetProjectFolder('netdat')
  assert networkData is not None
  grids : List[pf.ElmNet] = networkData.GetContents('.ElmNet', 1) #type: ignore
  activeGrids = list(filter(lambda x : x.IsCalcRelevant(), grids))

  if len(activeGrids) == 0:
    raise RuntimeError('No active grids.')

  # Make project backup
  project.CreateVersion(f'PRE_MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}') 

  resetProjectUnits(project)
  currentStudyCase.Consolidate() 

  netFolder = app.GetProjectFolder('netmod')
  assert netFolder is not None
  varFolder = app.GetProjectFolder('scheme')

  # Create variation folder
  if varFolder is None:
    varFolder = netFolder.CreateObject('IntPrjfolder', 'Variations')
    varFolder.SetAttribute('iopt_typ', 'scheme')

  # Create studycase folder
  studyCaseFolder = app.GetProjectFolder('study')
  if studyCaseFolder is None:
    studyCaseFolder = project.CreateObject('IntPrjfolder', 'Study Cases')
    studyCaseFolder.SetAttribute('iopt_typ', 'study')

  # Create task automation
  taskAuto : pf.ComTasks = studyCaseFolder.CreateObject('ComTasks') #type: ignore
  taskAuto.SetAttribute('iEnableParal', int(config.parallel))
  taskAuto.SetAttribute('parMethod', 0)
  (taskAuto.GetAttribute('parallelSetting')).SetAttribute('procTimeOut', 3600)

  # Find root object
  root = thisScript.GetParent()

  # Read and setup cases from sheet
  pfInterface = si.PFencapsulation(app, root)
  plantSettings, channels, cases, maxRank, ___ = cs.setup(casesheetPath = config.sheetPath, 
                                                     pscad = False,
                                                     pfEncapsulation = pfInterface)

  # Add user channel subscribers
  addCustomSubscribers(thisScript, channels)
  
  #Create export folder if it does not exist
  if not os.path.exists(config.exportPath):
    os.makedirs(config.exportPath)

  #Creating a datetime stamped subfolder
  datetimeFolder = f'MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}'

  #Create the folder for the PowerFactory CSV results
  csvFolder = os.path.join(config.exportPath, datetimeFolder)
  os.mkdir(csvFolder)
  
  # Find initializer script object
  initScript : pf.ComDpl = root.SearchObject('initializer_script.ComDpl') #type: ignore
  assert initScript is not None

  # List of created studycases for later activation
  studycases : List[pf.IntCase] = []

  currentStudyCase.Deactivate() 

  # Filter cases if Only_setup > 0
  onlySetup = script_GetInt(thisScript, 'Only_setup')
  assert isinstance(onlySetup, int)

  if onlySetup > 0:
    cases = list(filter(lambda x : x.rank == onlySetup, cases))

  app.EchoOff()
  for case in cases:
    if case.RMS:
      # Set-up studycase, variation and balance      
      caseName = f'{str(case.rank).zfill(len(str(maxRank)))}_{case.Name}'.replace('.', '')
      exportName = os.path.join(os.path.abspath(csvFolder), f'{plantSettings.Projectname}_{case.rank}')
      newStudycase : pf.IntCase = studyCaseFolder.CreateObject('IntCase', caseName) #type: ignore
      assert newStudycase is not None
      studycases.append(newStudycase)
      newStudycase.Activate()      
      newStudycase.SetStudyTime(studyTime) 

      # Activate the relevant networks
      for g in activeGrids:
          g.Activate() 

      newVar : pf.IntScheme = varFolder.CreateObject('IntScheme', caseName) #type: ignore
      assert newVar is not None
      newStage : pf.IntSstage = newVar.CreateObject('IntSstage', caseName) #type: ignore
      assert newStage is not None
      newStage.SetAttribute('e:tAcTime', studyTime)
      newVar.Activate() 
      newStage.Activate() 

      si.applyToPowerfactory(channels, case.rank)

      initScript.Execute() 

      ### WORKAROUND FOR QDSL FAILING WHEN IN MTB-GRID ###
      #TODO: REMOVE WHEN FIXED
      if config.QDSLcopyGrid != '':
        qdslInitializer = root.SearchObject('initializer_qdsl.ElmQdsl')
        assert qdslInitializer is not None
        for g in activeGrids:
          gridName = g.GetFullName() 
          assert isinstance(gridName, str)
          if gridName.lower().endswith(f'{config.QDSLcopyGrid.lower()}.elmnet'):
            g.AddCopy(qdslInitializer) #type: ignore
          
        qdslInitializer.SetAttribute('outserv', 1) 
      ### END WORKAROUND ###

      inc = app.GetFromStudyCase('ComInc')
      assert inc is not None
      sim = app.GetFromStudyCase('ComSim')
      assert sim is not None
      comRes : pf.ComRes = app.GetFromStudyCase('ComRes') #type: ignore
      assert comRes is not None

      taskAuto.AppendStudyCase(newStudycase) 
      taskAuto.AppendCommand(inc, -1) 
      taskAuto.AppendCommand(sim, -1) 
      taskAuto.AppendCommand(comRes, -1)
      setupResFiles(app, thisScript, root)
      app.WriteChangesToDb()
      setupExport(app, exportName)
      app.WriteChangesToDb()
      newStudycase.Deactivate() 
      app.WriteChangesToDb()

  app.EchoOn()
  
  if onlySetup == 0:
    taskAuto.Execute() 
  
  if pfVersion >= 2024:
    for studycase in studycases:
      studycase.Activate() 
      setupPlots(app, root)
      app.WriteChangesToDb()
      studycase.Deactivate() 
      app.WriteChangesToDb()
  else:
    app.PrintWarn('Plot setup not supported for PowerFactory versions older than 2024.')
  
  # Create post run backup
  postBackup = script_GetInt(thisScript, 'Post_run_backup')
  assert isinstance(postBackup, int)
  if postBackup > 0:
    project.CreateVersion(f'POST_MTB_{datetime.now().strftime(r"%d%m%Y%H%M%S")}')

if __name__ == "__main__":
  main()