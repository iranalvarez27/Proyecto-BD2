from dataclasses import dataclass, field
from query.tokens import TokenType

@dataclass
class PointLiteral:
    lat: float
    lon: float


@dataclass
class PolygonLiteral:
    puntos: list


@dataclass
class FuncCall:
    nombre: str
    argumentos: list
    alias: str = None


@dataclass
class ColumnRef:
    nombre: str


@dataclass
class SubquerySelect:
    nodo_select: object


@dataclass
class Condition:
    columna: str
    operador: TokenType
    valor: object


@dataclass
class NotCondition:
    interior: object


@dataclass
class SpatialCondition:
    funcion: FuncCall
    operador: TokenType = None
    valor: object = None

@dataclass
class BinaryCondition:
    izquierda: object
    operador: TokenType
    derecha: object

@dataclass
class OrderBy:
    columna: str = None
    descendente: bool = False
    funcion: FuncCall = None

@dataclass
class JoinClause:
    tabla: str
    columna_izquierda: str
    columna_derecha: str


@dataclass
class AggregateCall:
    nombre: str
    columna: str

    def etiqueta(self) -> str:
        return f"{self.nombre}({self.columna})"


@dataclass
class SelectNode:
    columnas: list
    tabla: str
    where: object = None
    order_by: OrderBy = None
    group_by: str = None
    joins: list = field(default_factory=list)
    limit: int = None
    # funciones espaciales en la lista del SELECT, p. ej. distancia(...) AS d
    extras: list = field(default_factory=list)


@dataclass
class InsertNode:
    tabla: str
    valores: list


@dataclass
class DeleteNode:
    tabla: str
    where: object = None


@dataclass
class UpdateNode:
    tabla: str
    asignaciones: list  # lista[tupla[str, object]]
    where: object = None


@dataclass
class SetVarNode:
    nombre: str
    valor: object


@dataclass
class BeginNode:
    pass


@dataclass
class CommitNode:
    pass


@dataclass
class RollbackNode:
    pass


@dataclass
class ExplainNode:
    statement: object
    analyze: bool = False


@dataclass
class ColumnDef:
    nombre: str
    tipo: str
    tamano: int = None
    is_pk: bool = False


@dataclass
class CreateTableNode:
    tabla: str
    columnas: list
    storage: str = "heap"


@dataclass
class DropTableNode:
    tabla: str


@dataclass
class CreateIndexNode:
    tabla: str
    columna: str
    tipo_indice: str = "bplus"  # "bplus" | "hash" | "rtree"
    nombre: str = None