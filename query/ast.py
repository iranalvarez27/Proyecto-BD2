from dataclasses import dataclass
from query.tokens import TokenType

@dataclass
class Condition:
    columna: str
    operador: TokenType
    valor: object

@dataclass
class BinaryCondition:
    izquierda: object
    operador: TokenType
    derecha: object

@dataclass
class OrderBy:
    columna: str
    descendente: bool = False

@dataclass
class JoinClause:
    tabla: str
    columna_izquierda: str
    columna_derecha: str

@dataclass
class SelectNode:
    columnas: list
    tabla: str
    where: object = None
    order_by: OrderBy = None
    group_by: str = None
    join: JoinClause = None


@dataclass
class InsertNode:
    tabla: str
    valores: list


@dataclass
class DeleteNode:
    tabla: str
    where: object = None


@dataclass
class BeginNode:
    pass


@dataclass
class CommitNode:
    pass


@dataclass
class RollbackNode:
    pass