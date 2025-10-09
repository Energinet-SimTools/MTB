from enum import Enum

class CursorType(Enum):
    START      = 0
    END        = 1
    DELTA      = 2
    MIN        = 3
    MAX        = 4
    MEAN       = 5    
    GRAD_MIN   = 6
    GRAD_MAX   = 7
    GRAD_MEAN  = 8
    RESPONSE   = 9
    RISE_FALL  = 10
    SETTLING   = 11
    OVERSHOOT  = 12
    FSM_DROOP  = 13
    LFSM_DROOP = 14
    QU_DROOP   = 15

    @classmethod
    def from_string(cls, string : str):
        try:
            return cls[string.upper()]
        except KeyError:
            raise ValueError(f"{string} is not a valid {cls.__name__}")