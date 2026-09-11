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
class SelectNode:
    columnas: list
    tabla: str
    where: object = None
    order_by: OrderBy = None
    group_by: str = None


@dataclass
class InsertNode:
    tabla: str
    valores: list


@dataclass
class DeleteNode:
    tabla: str
    where: object = None