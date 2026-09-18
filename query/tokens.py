from enum import Enum
from dataclasses import dataclass

class TokenType(Enum):
    SELECT = 1
    FROM = 2
    WHERE = 3
    INSERT = 4
    INTO = 5
    VALUES = 6
    DELETE = 7
    ORDER = 8
    BY = 9
    GROUP = 10
    ASC = 11
    DESC = 12
    AND = 13
    OR = 14
    
    IDENT = 15 
    NUMBER = 16
    STRING = 17 

    EQ = 18       
    NEQ = 19      
    LT = 20        
    LTE = 21       
    GT = 22         
    GTE = 23       

    STAR = 24
    COMMA = 25
    LPAREN = 26
    RPAREN = 27
    
    SEMICOLON = 28
    EOF = 29

    JOIN = 30
    ON = 31
    DOT = 32

KEYWORDS = {"select": TokenType.SELECT, "from": TokenType.FROM, "where": TokenType.WHERE,
            "insert": TokenType.INSERT, "into": TokenType.INTO, "values": TokenType.VALUES,
            "delete": TokenType.DELETE, "order": TokenType.ORDER, "by": TokenType.BY,
            "group": TokenType.GROUP, "asc": TokenType.ASC, "desc": TokenType.DESC,
            "and": TokenType.AND, "or": TokenType.OR,
            "join": TokenType.JOIN, "on": TokenType.ON,}

@dataclass
class Token:
    type: TokenType
    value: str
    pos: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.pos})"