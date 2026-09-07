from enum import Enum, auto
from dataclasses import dataclass

class TokenType(Enum):
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    INSERT = auto()
    INTO = auto()
    VALUES = auto()
    DELETE = auto()
    ORDER = auto()
    BY = auto()
    GROUP = auto()
    ASC = auto()
    DESC = auto()
    AND = auto()
    OR = auto()
    
    IDENT = auto()   
    NUMBER = auto()   
    STRING = auto()     

    EQ = auto()         
    NEQ = auto()       
    LT = auto()         
    LTE = auto()        
    GT = auto()         
    GTE = auto()        

    STAR = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()

    EOF = auto() 

KEYWORDS = {"select": TokenType.SELECT, "from": TokenType.FROM, "where": TokenType.WHERE,
            "insert": TokenType.INSERT, "into": TokenType.INTO, "values": TokenType.VALUES,
            "delete": TokenType.DELETE, "order": TokenType.ORDER, "by": TokenType.BY,
            "group": TokenType.GROUP, "asc": TokenType.ASC, "desc": TokenType.DESC, 
            "and": TokenType.AND, "or": TokenType.OR,}

@dataclass
class Token:
    type: TokenType
    value: str
    pos: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.pos})"