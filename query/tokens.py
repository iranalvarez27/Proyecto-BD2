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

    BEGIN = 33
    TRANSACTION = 34
    START = 35
    COMMIT = 36
    END = 37
    ROLLBACK = 38
    ABORT = 39

    EXPLAIN = 40
    ANALYZE = 41

    CREATE = 42
    TABLE = 43
    PRIMARY = 44
    KEY = 45
    USING = 46

    DROP = 47

    BETWEEN = 48

    MINUS = 49
    POINT = 50
    POLYGON = 51
    LIMIT = 52
    INDEX = 53

    UPDATE = 54
    SET = 55
    LIKE = 56
    IN = 57
    NOT = 58

KEYWORDS = {"select": TokenType.SELECT, "from": TokenType.FROM, "where": TokenType.WHERE,
            "insert": TokenType.INSERT, "into": TokenType.INTO, "values": TokenType.VALUES,
            "delete": TokenType.DELETE, "order": TokenType.ORDER, "by": TokenType.BY,
            "group": TokenType.GROUP, "asc": TokenType.ASC, "desc": TokenType.DESC,
            "and": TokenType.AND, "or": TokenType.OR,
            "join": TokenType.JOIN, "on": TokenType.ON,
            "begin": TokenType.BEGIN, "transaction": TokenType.TRANSACTION,
            "start": TokenType.START, "commit": TokenType.COMMIT, "end": TokenType.END,
            "rollback": TokenType.ROLLBACK, "abort": TokenType.ABORT,
            "explain": TokenType.EXPLAIN, "analyze": TokenType.ANALYZE,
            "create": TokenType.CREATE, "table": TokenType.TABLE,
            "primary": TokenType.PRIMARY, "key": TokenType.KEY, "using": TokenType.USING,
            "drop": TokenType.DROP, "between": TokenType.BETWEEN, "point": TokenType.POINT,
            "polygon": TokenType.POLYGON, "limit": TokenType.LIMIT, "index": TokenType.INDEX,
            "update": TokenType.UPDATE, "set": TokenType.SET, "like": TokenType.LIKE,
            "in": TokenType.IN, "not": TokenType.NOT,}

@dataclass
class Token:
    type: TokenType
    value: str
    pos: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.pos})"