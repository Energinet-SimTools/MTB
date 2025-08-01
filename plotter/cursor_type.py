from enum import Enum

class CursorType(Enum):
    MIN        = 1
    MAX        = 2
    MEAN       = 3    
    GRAD_MIN   = 4
    GRAD_MAX   = 5
    GRAD_MEAN  = 6
    RESPONSE   = 7
    RISE_FALL  = 8
    SETTLING   = 9
    OVERSHOOT  = 10
    FSM_SLOPE  = 11
    LFSM_SLOPE = 12
    QU_SLOPE   = 13

    @classmethod
    def from_string(cls, string : str):
        try:
            return cls[string.upper()]
        except KeyError:
            raise ValueError(f"{string} is not a valid {cls.__name__}")