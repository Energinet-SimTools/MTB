'''
This module contains classes and functions for interfacing with Powerfactory and PSCAD.
Powerfactory is interfaced through a simple abstraction of the native Powerfactory interface.
PSCAD is interfaced through rendered fortran code.
'''
from __future__ import annotations 
from abc import ABC, abstractmethod
from typing import Union, Dict, List, Tuple, Optional, Callable
from math import isnan
from copy import copy
from warnings import warn
from os.path import join, split, splitext, exists, abspath, basename
from os import mkdir, getcwd
from glob import glob
import pandas as pd

try:
    import powerfactory as pf #type: ignore
    print(f'Imported powerfactory module from {pf.__file__}')
except ImportError:
    warn('sim_interface.py: Powerfactory module not found.')

try:
    import jinja2
    print(f'Imported jinja2 module from {jinja2.__file__}')
except ImportError:
    warn('sim_interface.py: jinja2 module not found. (pscad functionality disabled)')


MEAS_FILE_FOLDER : str = 'recordings_scaled' # constant

pf_time_offset : float = 0.0
pscad_time_offset : float = 0.0

class PFinterface(ABC):
    '''
    Defines interface for encapsulation of Powerfactory native interface.
    '''
    @abstractmethod
    def setAttribute(self, target : str, attribute : str, value : Union[str, float, int]) -> None:
        ...

    @abstractmethod
    def getAttribute(self, target : str, attribute : str) -> Optional[Union[str, float, int, pf.DataObject]]:
        ...

    @abstractmethod
    def newParamEvent(self, name : str, target : str, attrib : str, value : float, time : float) -> None:
        ...

class PFencapsulation(PFinterface):
    '''
    Encapsulates Powerfactory native interface. Used to set and get attributes and create parameter events.
    '''
    def __init__(self, app : pf.Application, root : pf.DataObject):
        self.__app__ = app
        self.__root__ = root

    def __findPfObject__(self, target : str) -> Optional[pf.DataObject]:
        if target == '':
            obj = None
        elif target.startswith('$studycase$\\'):
            scPath = target.split('\\')[-1]
            obj = self.__app__.GetFromStudyCase(scPath)
        elif target.startswith('$parent$\\'):
            parentPFe = PFencapsulation(self.__app__, self.__root__.GetParent())
            obj = parentPFe.__findPfObject__(target.lower().replace('$parent$\\', '', 1))
        elif target.startswith('\\'):
            userPFe = PFencapsulation(self.__app__, self.__app__.GetCurrentUser().GetParent())
            while target.startswith('\\'):
                target = target[1:]
            obj = userPFe.__findPfObject__(target)
        else:
            obj = self.__root__.SearchObject(target)

        if obj is None and target != '':
            raise RuntimeError(f'Object "{target}" not found.')

        return obj

    def setAttribute(self, target : str, attribute : str, value : Union[str, float, int]) -> None:
        if target == '':
            raise ValueError('Target cannot be empty string.')
        
        obj = self.__findPfObject__(target)
        assert obj is not None

        attribTypes = pf.DataObject.AttributeType
        objAttribType = obj.GetAttributeType(attribute)
        
        if objAttribType == attribTypes.INVALID:
            raise KeyError(f'Attribute {attribute} not found in object {obj.GetFullName(0)}')

        if objAttribType == attribTypes.OBJECT or objAttribType == attribTypes.OBJECT_VEC:
            if isinstance(value, str):
                newValue = self.__findPfObject__(value)
            else:
                raise TypeError('Attribute is of type OBJECT or OBJECT_VEC. Value must be a string containing the path to the set object.')

            obj.SetAttribute(attribute, newValue)

        elif objAttribType == attribTypes.STRING or objAttribType == attribTypes.STRING_VEC:
            obj.SetAttribute(attribute, str(value))

        elif objAttribType == attribTypes.DOUBLE or objAttribType== attribTypes.DOUBLE_MAT or objAttribType == attribTypes.DOUBLE_VEC:
            obj.SetAttribute(attribute, float(value)) #type: ignore
        
        elif objAttribType == attribTypes.INTEGER or objAttribType == attribTypes.INTEGER_VEC or objAttribType == attribTypes.INTEGER64 or objAttribType == attribTypes.INTEGER64_VEC:
            obj.SetAttribute(attribute, int(value)) #type: ignore
        
        else:
            raise RuntimeError(f'Attribute {attribute} of type {objAttribType} not supported.')
        
        #self.__app__.WriteChangesToDb()

    def getAttribute(self, target : str, attribute : str) -> Optional[Union[str, float, int, pf.DataObject]]:
        if target == '':
            raise ValueError('Target cannot be empty string.')
        
        obj = self.__findPfObject__(target)
        assert obj is not None

        attribTypes = pf.DataObject.AttributeType
        objAttribType = obj.GetAttributeType(attribute)
        
        if objAttribType == attribTypes.INVALID:
            raise KeyError(f'Attribute {attribute} not found in object {obj.GetFullName(0)}')

        value = obj.GetAttribute(attribute)

        if objAttribType == attribTypes.OBJECT or objAttribType == attribTypes.OBJECT_VEC:
            return value
        elif objAttribType == attribTypes.STRING or objAttribType == attribTypes.STRING_VEC:
            return str(value)
        elif objAttribType == attribTypes.DOUBLE or objAttribType== attribTypes.DOUBLE_MAT or objAttribType == attribTypes.DOUBLE_VEC:
            return float(value)
        elif objAttribType == attribTypes.INTEGER or objAttribType == attribTypes.INTEGER_VEC or objAttribType == attribTypes.INTEGER64 or objAttribType == attribTypes.INTEGER64_VEC:
            return int(value)
        else:
            raise RuntimeError(f'Attribute {attribute} of type {objAttribType} not supported.')  

    def newParamEvent(self, name : str, target : str, attrib : str, value : float, time : float) -> None:
        studycase = self.__app__.GetActiveStudyCase()

        if not studycase:
            raise RuntimeError('No studycase active. Cannot create parameter event.')
        
        eventFolder = self.__app__.GetFromStudyCase('IntEvt')
        if not eventFolder:
            eventFolder = studycase.CreateObject('IntEvt')
        assert eventFolder is not None
   
        event : pf.DataObject = eventFolder.CreateObject('EvtParam', name)
        obj = self.__findPfObject__(target)
        event.SetAttribute('p_target', obj)
        event.SetAttribute('time', time)
        event.SetAttribute('variable', attrib)
        event.SetAttribute('value', str(value))
        #self.__app__.WriteChangesToDb()

class Waveform(ABC):
    @property
    @abstractmethod
    def s0(self) -> float:
        ...

    @abstractmethod
    def add(self, t : float, s : float, r : float = 0.0) -> None:
        ...

class Piecewise(Waveform):
    """
    Piecewise defined waveform. At every defined point in time the waveform is set to "s" and continues with gradient "r".
    Only used in the signal type channel.
    """
    def __init__(self, s0 : float) -> None:
        self.__t__ : List[float] = [0.0]
        self.__s__ : List[float] = [s0]
        self.__r__ : List[float] = [0.0]
    
    def add(self, t : float, s : float, r : float = 0.0) -> None:            
        if isnan(t):
            raise ValueError('t must be a float')

        assert len(self.__t__) == len(self.__s__) == len(self.__r__)
        assert len(self.__t__) > 0
        assert self.__t__[0] == 0.0

        if t < 0.0:
            if isnan(s):
                raise ValueError('Initial value of piecewise must be a float')
            self.__s__[0] = s
            return

        i = len(self.__t__) - 1

        while(True):
            if t >= self.__t__[i]:
                if t > self.__t__[i] or t == 0.0:
                    newIndex = i + 1
                else:
                    newIndex = i
                
                if t > self.__t__[i]:
                    donorIndex = i
                else:
                    donorIndex = max(i - 1, 0)
                
                if isnan(s):
                    dt = t - self.__t__[donorIndex]
                    s = self.__s__[donorIndex] + self.__r__[donorIndex] * dt
                
                if isnan(r):
                    r = self.__r__[donorIndex]
            
                self.__t__.insert(newIndex, t)
                self.__s__.insert(newIndex, s)
                self.__r__.insert(newIndex, r)
                break
            i -= 1

    def t_pscad(self, minLength : int = 0) -> List[float]:
        return self.__tf__(minLength, pscad_time_offset)
        
    def t_pf(self, minLength : int = 0) -> List[float]:
        return self.__tf__(minLength, pf_time_offset)

    def __tf__(self, minLength : int = 0, offset : float = 0.0) -> List[float]:
        _t = [0.0] + [t + offset for t in self.__t__[1:]]
        if len(_t) >= minLength:
            return _t
        else:
            return _t + (minLength - len(_t)) * [0.0]

    def s(self, minLength : int = 0) -> List[float]:
        if len(self.__s__) >= minLength:
            return self.__s__
        else:
            return self.__s__ + (minLength - len(self.__s__)) * [0.0]

    def r(self, minLength : int = 0) -> List[float]:
        if len(self.__r__) >= minLength:
            return self.__r__
        else:
            return self.__r__ + (minLength - len(self.__r__)) * [0.0]

    @property
    def len(self):
        return len(self.__t__)

    def __eq__(self, other : object) -> bool:
        if isinstance(other, type(self)):
            return self.__t__ == other.__t__ and self.__s__ == other.__s__ and self.__r__ == other.__r__
        else:
            return False
    @property
    def s0(self) -> float:
        return self.__s__[0]

class Recorded(Waveform):  
    """
    Waveform defined in specified column in file. Time must be first column (column = 0). Supports powerfactory ElmFile format, PSCAD legacy .out and .csv with dot decimal and semi-colon seperator.
    Only used in signal type channel.
    """  
    def __init__(self, path : str, column : int, pf : bool, pscad : bool, scale : float = 1.0) -> None:
        if not pf and not pscad:
            warn(f'Recorded waveform (source: {path}) is not either set to be pf or pscad or both.')
        
        self.__path__ : str = path
        self.__column__ : int = column
        self.__pf__ : bool = pf
        self.__pscad__ : bool = pscad
        self.__scale__ : float = scale
        
        self.__pfPath__ : Optional[str] = None
        self.__pscadPath__ : Optional[str] = None
        self.__pfLen__ : float = 0.0
        self.__pscadLen__ : float = 0.0
        self.__s0__ : float = 0.0

        self.__loadFile__()

    def __eq__(self, other : object) -> bool:
        if isinstance(other, type(self)):
            return self.__pfPath__ == other.__pfPath__ and self.__pscadPath__ == other.__pscadPath__
        else:
            return False

    def __loadFile__(self) -> None:
        if not self.__pscad__ and not self.__pf__:
            return None
        
        _, pathFilename = split(self.__path__)
        pathName, pathExtension = splitext(pathFilename)
        
        reader = open(self.__path__, 'r')

        if pathExtension.lower() == '.meas' or pathExtension.lower() == '.out':    
            lineBuffer = reader.readlines()
            data : List[List[float]] = []

            def parseLine(line : str, linenr : int, column : int, file : str) -> List[float]:
                floatBuffer : str = ''
                line += '\n'
                colNr : int = -1
                time : float = 0.0

                for c in line:
                    if not c in [',',' ','\t','\n']:
                        floatBuffer += c
                    else:
                        if len(floatBuffer) > 0:
                            colNr += 1
                            try:
                                if colNr == 0:
                                    time = float(floatBuffer)
                                elif colNr == column:
                                    return [time, float(floatBuffer)]
                            except ValueError:
                                raise RuntimeError(f'Could not parse line nr: {linenr} in "{file}". Value "{floatBuffer}" not understandable as float. Exiting.')
                            floatBuffer = ''
                            
                raise RuntimeError(f'Could not parse line nr: {linenr} in "{file}". Column {column} not found.')

            i = 2
            for line in lineBuffer[1:]:
                data.append(parseLine(line, i, self.__column__, self.__path__))
                i += 1

            df : pd.DataFrame = pd.DataFrame(data)

        elif pathExtension.lower() == '.csv':                
            df : pd.DataFrame = pd.read_csv(self.__path__, sep=';', decimal='.', header=None, skiprows=1) # type: ignore
        else:
            raise RuntimeError(f'Unknown filetype of: {self.__path__}.')
        
        #Data is loaded
        df = df.set_index(0) # type: ignore         
        df.sort_index(ascending=True, inplace=True) # type: ignore   
        df = df * self.__scale__
        self.__s0__ = float(df.iloc[0,0]) # type: ignore
        time = df.index # type: ignore 

        if not exists(MEAS_FILE_FOLDER):
            mkdir(MEAS_FILE_FOLDER)

        if self.__pf__:
            df.index = df.index + pf_time_offset # type: ignore
            df.rename(index={df.index[0] : time[0]}, inplace=True) # type: ignore

            recFilePath = join(MEAS_FILE_FOLDER , f'{pathName}_{self.__column__}_{self.__scale__}_{pf_time_offset}.meas')
            measData : str = df.to_csv(None, sep = ' ', header=False, index_label=False).replace('\r\n','\n') # type: ignore
            measData = '1\n' + measData
            f = open(recFilePath, 'w')
            f.write(measData)
            f.close()           
            self.__pfPath__ = recFilePath
            self.__pfLen__ = df.index[-1] # type: ignore

        if self.__pscad__:
            if self.__pf__ and pf_time_offset != pscad_time_offset:
                df.index = time
            
            if not self.__pf__ or pf_time_offset != pscad_time_offset:
                df.index = df.index + pscad_time_offset # type: ignore
                df.rename(index={df.index[0] : time[0]}, inplace=True) # type: ignore
            
            recFilePath = join(MEAS_FILE_FOLDER , f'{pathName}_{self.__column__}_{self.__scale__}_{pscad_time_offset}.out')
            measData = df.to_csv(None, sep = ' ', header=False, index_label=False).replace('\r\n','\n') # type: ignore
            measData = '\n' + measData
            f = open(recFilePath, 'w')
            f.write(measData)
            f.close()
            
            if len(glob('*.pswx')) == 0:
                if len(glob('..\*.pswx')) > 0:
                    mtbBasePaht = basename(getcwd())
                    recFilePath = join(mtbBasePaht, recFilePath)
                else:
                    raise RuntimeError('Could not find a PSCAD Workspace file ("*.pswx") in the current or parent folder.')

            self.__pscadPath__ = recFilePath
            self.__pscadLen__ = df.index[-1] # type: ignore

    @property
    def pfLen(self):
        if self.__pfPath__ == None:
            warn(f'Recorded waveform (source: {self.__path__}) pfLen call with pfPath set to None. Returning 0.0.')
        return self.__pfLen__

    @property
    def pscadLen(self):
        if self.__pscadPath__ == None:
             warn(f'Recorded waveform (source: {self.__path__}) pscadLen call with pscadPath set to None. Returning 0.0.')
        return self.__pscadLen__

    @property
    def s0(self) -> float:
        return self.__s0__

    @property
    def pfPath(self):
        if self.__pfPath__ == None:
            raise RuntimeError('pfPath not set.')
        return self.__pfPath__

    @property
    def pscadPath(self):
        if self.__pscadPath__ == None:
            raise RuntimeError('pscadPath not set.')
        return self.__pscadPath__
    
    def add(self, t: float, s: float, r: float = 0) -> None:
        warn(f'Recorded waveform (source: {self.__path__}) .add method called. Ignoring.')

class Channel(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

class FortranRenderable(ABC):
    @abstractmethod
    def renderFortran(self) -> str:
        ...

class PfApplyable(ABC):
    @abstractmethod
    def applyToPF(self, rank : int) -> None:
        ...
    
    @property
    @abstractmethod
    def pfInterface(self) -> Optional[PFinterface]:
        ...

#CHANNEL TYPES
class Constant(Channel, FortranRenderable, PfApplyable):
    """
    Constant (irespective of rank and time) value passed to Powerfactory and PSCAD.
    """
    def __init__(self, name : str, value : Union[float, int, bool], pscad : bool, pfInterface : Optional[PFinterface]) -> None:
        self.__name__ = name
        self.__PSCAD__ = pscad
        self.__value__ : float = float(value)
        self.__PFsubs__ : List[Tuple[str, str]] = []
        self.__pfInterface__ : Optional[PFinterface] = pfInterface 
        self.__signalTemplate__ : str = \
f"""subroutine {name}_const(y)
    implicit none
    real, intent(out) :: y

    y = {value}

end subroutine {name}_const"""

    @property
    def value(self) -> Union[float, int]:
        return self.__value__
    
    @property
    def pfInterface(self) -> Optional[PFinterface]:
        return self.__pfInterface__

    @property
    def name(self) -> str:
        return self.__name__

    def renderFortran(self) -> str:
        if self.__PSCAD__:
            return self.__signalTemplate__
        else:
            return ''

    def addPFsub(self, target : str, attribute : str) -> None:
        if not (target, attribute) in self.__PFsubs__:
            self.__PFsubs__.append((target, attribute))

    @property
    def PFsubs(self):
        return self.__PFsubs__

    def applyToPF(self, rank : int) -> None:
        if self.pfInterface == None:
            warn(f'Powerfactory interface not set on constant: {self.name}. Ignoring.')
            return None
        
        for target, attrib in self.__PFsubs__:
            self.pfInterface.setAttribute(target, attrib, self.value)

class Signal(Channel, FortranRenderable, PfApplyable):
    """
    Dynamic value both in respect to time and rank passed to Powerfactory and PSCAD.
    Each rank can either contain a piecewise defined waveform or a recorded waveform.
    """        
    def __init__(self, name : str, pscad : bool, pfInterface : Optional[PFinterface]) -> None:
        self.__name__ : str = name
        self.__PSCAD__ : bool = pscad
        self.__waveforms__ : Dict[int, Waveform] = dict()
        self.__PFsubs_S__ : List[Tuple[str, str,  Optional[Callable[[Signal, float], float]]]]= []
        self.__PFsubs_S0__ : List[Tuple[str, str,  Optional[Callable[[Signal, float], float]]]] = []
        self.__PFsubs_R__ : List[Tuple[str, str,  Optional[Callable[[Signal, float], float]]]]= []
        self.__PFsubs_T__ : List[Tuple[str, str, Optional[Callable[[Signal, float], float]]]] = []
        self.__pfInterface__ : Optional[PFinterface] = pfInterface
        self.__ElmFile__ : Optional[str] = None #Optional path to ElmFile object

        self.__signalTemplate__ = \
"""subroutine {{ signal.name }}_signal(rank, y)
    include 'emtstor.h'
    include 's1.h'  
    implicit none

    integer, intent(in) :: rank
    real, intent(out) ::  y
    integer :: inrank{% if hasPiecewise %}, events, index{% endif %}

    {% if hasPiecewise %}
    real  :: tx({{ arraySize }})
    real :: sy({{ arraySize }})
    real :: ry({{ arraySize }})
    {% endif %}

    {% if hasRecorded %}
    real :: frout(11) 
    {% endif %}

    if(TIMEZERO) then
        {% if hasPiecewise %}
        index = 1
        {% endif %}
        inrank = rank
        STORI(NSTORI + 1) = inrank
    else    
        {% if hasPiecewise %}
        index = STORI(NSTORI)
        {% endif %}
        inrank = STORI(NSTORI + 1)
    endif
    
    {% if hasPiecewise %}
    events = -1
    {% endif %}

    ranks: select case(inrank)
    {% for rank in signal.ranks %}
    {% if isinstance(signal[rank], PiecewiseClass) %}
    case({{ rank }})
        tx = {{ signal[rank].t_pscad(arraySize) }}
        sy = {{ signal[rank].s(arraySize) }}
        ry = {{ signal[rank].r(arraySize) }}
        events = {{ signal[rank].len }}         
    {% elif isinstance(signal[rank], RecordedClass) %}
    case({{ rank }})
        NSTORI = NSTORI + 2
        call FILEREAD2("{{ signal[rank].pscadPath }}", 0, 2, 0, 0, 0.0, 1.0, 0.0, frout)
        y = frout(2)
    {% endif %}
    {% endfor %}
    case default
        y = 0.0
        NSTORI = NSTORI + 5
        NSTORF = NSTORF + 35
    end select ranks

    {% if hasPiecewise %}
    if( events > -1) then
        if ( index < events ) then
            if ( TIME >= tx(index + 1) ) then
                index = index + 1
            endif
        endif
        y =  sy(index) + (TIME - tx(index)) * ry(index)
        STORI(NSTORI) = index
        NSTORI = NSTORI + 5
        NSTORF = NSTORF + 35
    endif
    {% endif %}
end subroutine {{ signal.name }}_signal"""
        
    @property
    def name(self):
        return self.__name__
    
    @property
    def pfInterface(self) -> Optional[PFinterface]:
        return self.__pfInterface__

    @property
    def ElmFile(self):
        return self.__ElmFile__
    
    def setElmFile(self, path : str) -> None:
        self.__ElmFile__ = path

    def __setitem__(self, rank : int, wave : Union[Waveform, float, int]) -> None:
        if isinstance(wave, float) or isinstance(wave, int):
            wave = Piecewise(float(wave))
        self.__waveforms__[rank] = wave

    def __getitem__(self, rank : int) -> Waveform:
        return self.__waveforms__[rank]

    def __arraySize__(self) -> int:
        maxLength = -1
        for rank in self.ranks:
            wf = self[rank]
            if isinstance(wf, Piecewise):
                maxLength = max(wf.len, maxLength)

        return maxLength
    
    @property
    def ranks(self):
        return self.__waveforms__.keys()

    def __groupRanks__(self):
        #TODO: Refactor, this is dirty
        groups : List[List[Tuple[int, Waveform]]]= []
        for rank in self.ranks:
            wf = self[rank]
            foundGroup = False
            for group in groups:
                if wf == group[0][1] or \
                    isinstance(wf, Recorded) and isinstance(group[0][1], Recorded) and wf.pscadPath == group[0][1].pscadPath:
                    group.append((rank, wf)) 
                    foundGroup = True
                    continue

            if not foundGroup:
                groups.append([(rank, wf)])
        
        groupedSignal = copy(self)
        groupedSignal.__waveforms__ = dict()

        for group in groups:
            group = sorted(group)
            
            groupIndex = lastPlaced = group[0][0]
            ranks = f'{group[0][0]}'    

            for wave in group[1:]:
                if wave[0] == groupIndex + 1:
                    groupIndex = wave[0]
                else:
                    if groupIndex == lastPlaced:
                        ranks += f', {wave[0]}'
                    elif groupIndex == lastPlaced + 1:
                        ranks += f',{groupIndex}, {wave[0]}'
                    else:
                        ranks += f':{groupIndex}, {wave[0]}'

                    groupIndex = lastPlaced = wave[0]
                    
            if groupIndex == lastPlaced + 1:
                ranks += f',{groupIndex}'
            elif groupIndex > lastPlaced:
                ranks += f':{groupIndex}'

            groupedSignal.__waveforms__[ranks] = group[0][1] #type: ignore
        return groupedSignal
        
    def renderFortran(self) -> str:
        if self.__PSCAD__:
            hasPiecewise : bool = False
            hasRecorded : bool = False 

            for rank in self.ranks:
                wf = self[rank]
                hasPiecewise = hasPiecewise or isinstance(wf, Piecewise)
                hasRecorded = hasRecorded or isinstance(wf, Recorded)

            template = jinja2.Environment(loader=jinja2.BaseLoader,trim_blocks=True,lstrip_blocks=True).from_string(self.__signalTemplate__) #type: ignore
            return template.render(signal = self.__groupRanks__(),
                                    hasPiecewise = hasPiecewise,
                                    hasRecorded = hasRecorded,
                                    arraySize = self.__arraySize__(),
                                    PiecewiseClass = Piecewise,
                                    RecordedClass = Recorded,
                                    isinstance = isinstance)
        else:
            return ''

    def addPFsub_S(self, target : str, attribute : str, func : Optional[Callable[[Signal, float], float]] = None):
        if not (target, attribute, func) in self.__PFsubs_S__:
            self.__PFsubs_S__.append((target, attribute, func))

    def addPFsub_S0(self, target : str, attribute : str, func : Optional[Callable[[Signal, float], float]] = None):
        if not (target, attribute, func) in self.__PFsubs_S0__:
            self.__PFsubs_S0__.append((target, attribute, func))

    def addPFsub_R(self, target : str, attribute : str, func : Optional[Callable[[Signal, float], float]] = None):
        if not (target, attribute, func) in self.__PFsubs_R__:
            self.__PFsubs_R__.append((target, attribute, func))

    def addPFsub_T(self, target : str, attribute : str, func : Optional[Callable[[Signal, float], float]] = None):
        if not (target, attribute, func) in self.__PFsubs_T__:
            self.__PFsubs_T__.append((target, attribute, func))

    def applyToPF(self, rank: int) -> None:
        if self.pfInterface == None:
            warn(f'Powerfactory interface not set on signal: {self.name}. Ignoring.')
            return None

        wf = self.__waveforms__[rank]

        if isinstance(wf, Piecewise):
            for target, attrib, func in self.__PFsubs_S__:
                for i in range(wf.len):
                    if wf.t_pf(0)[i] != 0.0:
                        if func != None:
                            attValue = func(self, wf.s(0)[i])
                        else:
                            attValue = wf.s(0)[i]

                        self.pfInterface.newParamEvent(f'{self.name}_s', target, attrib, attValue, wf.t_pf(0)[i])
            
            for target, attrib, func in self.__PFsubs_R__:
                for i in range(wf.len):
                    if wf.t_pf(0)[i] != 0.0:
                        if func != None:
                            attValue = func(self, wf.r(0)[i])
                        else:
                            attValue = wf.r(0)[i]

                        self.pfInterface.newParamEvent(f'{self.name}_s', target, attrib, attValue, wf.t_pf(0)[i])

            if self.ElmFile != None:
                self.pfInterface.setAttribute(self.ElmFile, 'e:outserv', 1)
                self.pfInterface.setAttribute(self.ElmFile, 'e:f_name', '')

        elif isinstance(wf, Recorded):
            if self.ElmFile != None:
                self.pfInterface.setAttribute(self.ElmFile, 'e:outserv', 0)
                self.pfInterface.setAttribute(self.ElmFile, 'e:f_name', abspath(wf.pfPath))

        for target, attrib, func in self.__PFsubs_S0__:
            if func != None:
                attValue = func(self, wf.s0)
            else:
                attValue = wf.s0

            self.pfInterface.setAttribute(target, attrib, attValue)

        for target, attrib, func in self.__PFsubs_T__:
            if isinstance(wf, Piecewise):
                typ = 0.0
            else:
                assert isinstance(wf, Recorded)
                typ = 1.0

            if func != None:
                attValue = func(self, typ)
            else:
                attValue = typ

            self.pfInterface.setAttribute(target, attrib, attValue)

class String(Channel, PfApplyable):
    """
    String value, only dynamic in respect to rank, passed to Powerfactory.
    """          
    def __init__(self, name : str, pfInterface : Optional[PFinterface]) -> None:
        self.__name__ : str = name
        self.__strings__ : Dict[int, str] = dict()
        self.__PFsubs__ : List[Tuple[str, str]] = []
        self.__pfInterface__ : Optional[PFinterface] = pfInterface
    
    @property
    def name(self):
        return self.__name__
    
    @property
    def pfInterface(self) -> Optional[PFinterface]:
        return self.__pfInterface__

    def __getitem__(self, rank : int) -> str:
        return self.__strings__[rank]

    def __setitem__(self, rank : int, string : str) -> None:
        self.addRank(rank, string)

    def addRank(self, rank : int, string : str) -> None:
        self.__strings__[rank] = string

    @property
    def ranks(self):
        return self.__strings__.keys()

    def addPFsub(self, target : str, attribute : str):
        if not (target, attribute) in self.__PFsubs__:
            self.__PFsubs__.append((target, attribute))

    @property
    def PFsubs(self):
        return self.__PFsubs__       

    def applyToPF(self, rank: int) -> None:
        if self.pfInterface == None:
            warn(f'Powerfactory interface not set on string: {self.name}. Ignoring.')
            return None

        for target, attribute in self.__PFsubs__:
            self.pfInterface.setAttribute(target, attribute, self.__strings__[rank])

class PfObjRefer(String):
    """
    Powerfactory object reference dynamic in respect to rank. Reference defined as path relative to rootobject passed to .applyToPF function.
    """           
    def applyToPF(self, rank: int) -> None:
        if self.pfInterface == None:
            warn(f'Powerfactory interface not set on PfObjRefer: {self.name}. Ignoring.')
            return None

        if self.__strings__[rank] == '$nochange$':
            return None
        
        for target, attribute in self.__PFsubs__:
            self.pfInterface.setAttribute(target, attribute, self.__strings__[rank])

def renderFortran(path : str, channels : List[Channel]) -> None:
    """
    Renders all releavant signals and constants in a list to a single fortran file.
    """ 
    
    fortranCode = ''  
    for channel in channels:
        if isinstance(channel, FortranRenderable):
            fortranCode += channel.renderFortran() + '\n\n'

    with open(path, mode='w') as f:
        f.write(fortranCode)
        f.close()

def applyToPowerfactory(channels : List[Channel], rank : int):          
    """
    Apply all channel setups in list to Powerfactory.
    """ 
    for channel in channels:
        if isinstance(channel, PfApplyable):
            channel.applyToPF(rank)
