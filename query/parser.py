from query.tokens import Token, TokenType
from query.ast import (
    SelectNode, InsertNode, DeleteNode, UpdateNode, Condition, BinaryCondition, NotCondition,
    OrderBy, JoinClause, AggregateCall, ColumnRef, SubquerySelect,
    BeginNode, CommitNode, RollbackNode, ExplainNode, ColumnDef, CreateTableNode, DropTableNode,
    PointLiteral, PolygonLiteral, FuncCall, SpatialCondition, CreateIndexNode,
)

class ParserError(Exception):
    pass

OPERADORES_COMP = [TokenType.EQ, TokenType.NEQ, TokenType.LT, TokenType.LTE, TokenType.GT, TokenType.GTE]
TIPOS_INDICE_CREATE_INDEX = {"btree": "bplus", "bplus": "bplus", "hash": "hash", "rtree": "rtree"}
FUNCIONES_AGREGADAS = {"count", "sum", "avg"}
LAT_MIN, LAT_MAX = -90.0, 90.0
LON_MIN, LON_MAX = -180.0, 180.0

class Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def actual(self):
        return self._tokens[self._pos]

    def siguiente(self, offset: int = 1):
        idx = self._pos + offset
        if idx < len(self._tokens):
            return self._tokens[idx]
        return self._tokens[-1]

    def avanzar(self):
        tok = self._tokens[self._pos]
        if tok.type != TokenType.EOF:
            self._pos += 1
        return tok

    def coincide(self, tipo):
        if self.actual().type == tipo:
            return True
        return False

    def esperar(self, tipo):
        if self.coincide(tipo):
            return self.avanzar()
        t = self.actual()
        raise ParserError(f"pos {t.pos}: esperaba {tipo.name}, salio {t.type.name} ({t.value})")

    def parse(self):
        if self.coincide(TokenType.SELECT):
            nodo = self.parse_select()
        elif self.coincide(TokenType.INSERT):
            nodo = self.parse_insert()
        elif self.coincide(TokenType.DELETE):
            nodo = self.parse_delete()
        elif self.coincide(TokenType.UPDATE):
            nodo = self.parse_update()
        elif self.coincide(TokenType.BEGIN) or self.coincide(TokenType.START):
            nodo = self.parse_begin()
        elif self.coincide(TokenType.COMMIT) or self.coincide(TokenType.END):
            nodo = self.parse_commit()
        elif self.coincide(TokenType.ROLLBACK) or self.coincide(TokenType.ABORT):
            nodo = self.parse_rollback()
        elif self.coincide(TokenType.EXPLAIN):
            nodo = self.parse_explain()
        elif self.coincide(TokenType.CREATE):
            if self.siguiente().type == TokenType.INDEX:
                nodo = self.parse_create_index()
            else:
                nodo = self.parse_create_table()
        elif self.coincide(TokenType.DROP):
            nodo = self.parse_drop_table()
        else:
            raise ParserError(f"error en la consulta, empieza con {self.actual().value}")

        if self.coincide(TokenType.SEMICOLON):
            self.avanzar()
        self.esperar(TokenType.EOF)
        return nodo

    def parse_begin(self):
        # BEGIN [TRANSACTION] | START TRANSACTION
        self.avanzar()  # BEGIN o START
        if self.coincide(TokenType.TRANSACTION):
            self.avanzar()
        return BeginNode()

    def parse_commit(self):
        # COMMIT [TRANSACTION] | END TRANSACTION
        self.avanzar()  # COMMIT o END
        if self.coincide(TokenType.TRANSACTION):
            self.avanzar()
        return CommitNode()

    def parse_rollback(self):
        # ROLLBACK | ABORT
        self.avanzar()
        return RollbackNode()

    def parse_explain(self):
        self.esperar(TokenType.EXPLAIN)
        analyze = False
        if self.coincide(TokenType.ANALYZE):
            self.avanzar()
            analyze = True

        if self.coincide(TokenType.SELECT):
            statement = self.parse_select()
        elif self.coincide(TokenType.INSERT):
            statement = self.parse_insert()
        elif self.coincide(TokenType.DELETE):
            statement = self.parse_delete()
        elif self.coincide(TokenType.UPDATE):
            statement = self.parse_update()
        else:
            t = self.actual()
            raise ParserError(
                f"pos {t.pos}: EXPLAIN solo soporta SELECT, INSERT, DELETE o UPDATE, salio {t.type.name} ({t.value})")
        return ExplainNode(statement, analyze)

    def parse_create_table(self):
        self.esperar(TokenType.CREATE)
        self.esperar(TokenType.TABLE)
        tabla = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.LPAREN)
        columnas = [self.parse_column_def()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            columnas.append(self.parse_column_def())
        self.esperar(TokenType.RPAREN)

        storage = "heap"
        if self.coincide(TokenType.USING):
            self.avanzar()
            tok = self.esperar(TokenType.IDENT)
            valor = tok.value.lower()
            if valor not in ("heap", "sequential"):
                raise ParserError(f"pos {tok.pos}: USING debe ser HEAP o SEQUENTIAL, salio '{tok.value}'")
            storage = valor
        return CreateTableNode(tabla, columnas, storage)

    def parse_drop_table(self):
        self.esperar(TokenType.DROP)
        self.esperar(TokenType.TABLE)
        tabla = self.esperar(TokenType.IDENT).value
        return DropTableNode(tabla)

    def parse_create_index(self):
        self.esperar(TokenType.CREATE)
        self.esperar(TokenType.INDEX)
        self.esperar(TokenType.ON)
        tabla = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.LPAREN)
        columna = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.RPAREN)

        tipo_indice = "bplus"
        if self.coincide(TokenType.USING):
            self.avanzar()
            tok = self.esperar(TokenType.IDENT)
            valor = tok.value.lower()
            if valor not in TIPOS_INDICE_CREATE_INDEX:
                raise ParserError(f"pos {tok.pos}: USING debe ser BTREE, HASH o RTREE, salio '{tok.value}'")
            tipo_indice = TIPOS_INDICE_CREATE_INDEX[valor]
        return CreateIndexNode(tabla, columna, tipo_indice)

    def parse_column_def(self):
        nombre = self.esperar(TokenType.IDENT).value
        if self.coincide(TokenType.POINT):
            tipo_tok = self.avanzar()
        else:
            tipo_tok = self.esperar(TokenType.IDENT)
        tamano = None
        if self.coincide(TokenType.LPAREN):
            self.avanzar()
            tam_tok = self.esperar(TokenType.NUMBER)
            tamano = int(tam_tok.value)
            self.esperar(TokenType.RPAREN)
        is_pk = False
        if self.coincide(TokenType.PRIMARY):
            self.avanzar()
            self.esperar(TokenType.KEY)
            is_pk = True
        return ColumnDef(nombre, tipo_tok.value, tamano, is_pk)

    def parse_select(self):
        self.esperar(TokenType.SELECT)
        cols = self.parse_columnas()
        self.esperar(TokenType.FROM)
        tabla = self.esperar(TokenType.IDENT).value

        joins = []
        while self.coincide(TokenType.JOIN):
            joins.append(self.parse_join())

        where = None
        order_by = None
        group_by = None

        if self.coincide(TokenType.WHERE):
            self.avanzar()
            where = self.parse_condicion()

        while self.coincide(TokenType.ORDER) or self.coincide(TokenType.GROUP):
            if self.coincide(TokenType.ORDER):
                order_by = self.parse_order_by()
            else:
                group_by = self.parse_group_by()

        limit = None
        if self.coincide(TokenType.LIMIT):
            self.avanzar()
            tok = self.esperar(TokenType.NUMBER)
            if "." in tok.value:
                raise ParserError(f"pos {tok.pos}: LIMIT necesita un entero, salio '{tok.value}'")
            limit = int(tok.value)

        return SelectNode(cols, tabla, where, order_by, group_by, joins, limit)

    def parse_join(self):
        self.esperar(TokenType.JOIN)
        tabla = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.ON)
        col_izq = self.parse_columna_ref()
        self.esperar(TokenType.EQ)
        col_der = self.parse_columna_ref()
        return JoinClause(tabla, col_izq, col_der)

    def parse_columna_ref(self):
        nombre = self.esperar(TokenType.IDENT).value
        if self.coincide(TokenType.DOT):
            self.avanzar()
            campo = self.esperar(TokenType.IDENT).value
            return f"{nombre}.{campo}"
        return nombre

    def parse_numero_con_signo(self):
        negativo = False
        if self.coincide(TokenType.MINUS):
            self.avanzar()
            negativo = True
        tok = self.esperar(TokenType.NUMBER)
        valor = float(tok.value) if "." in tok.value else int(tok.value)
        return -valor if negativo else valor

    def parse_point_literal(self):
        pos = self.actual().pos
        self.esperar(TokenType.POINT)
        self.esperar(TokenType.LPAREN)
        lat = self.parse_numero_con_signo()
        self.esperar(TokenType.COMMA)
        lon = self.parse_numero_con_signo()
        self.esperar(TokenType.RPAREN)
        if not (LAT_MIN <= lat <= LAT_MAX):
            raise ParserError(f"pos {pos}: POINT invalido, latitud {lat} fuera de rango "
                f"[{LAT_MIN}, {LAT_MAX}]")
        if not (LON_MIN <= lon <= LON_MAX):
            raise ParserError(f"pos {pos}: POINT invalido, longitud {lon} fuera de rango "
                f"[{LON_MIN}, {LON_MAX}]")
        return PointLiteral(float(lat), float(lon))

    def parse_polygon_literal(self):
        self.esperar(TokenType.POLYGON)
        self.esperar(TokenType.LPAREN)
        puntos = [self.parse_point_literal()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            puntos.append(self.parse_point_literal())
        self.esperar(TokenType.RPAREN)
        if len(puntos) < 3:
            raise ParserError("POLYGON necesita al menos 3 vertices")
        return PolygonLiteral(puntos)

    def parse_func_call(self):
        nombre = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.LPAREN)
        argumentos = []
        if not self.coincide(TokenType.RPAREN):
            argumentos.append(self.parse_expr_argumento())
            while self.coincide(TokenType.COMMA):
                self.avanzar()
                argumentos.append(self.parse_expr_argumento())
        self.esperar(TokenType.RPAREN)
        return FuncCall(nombre.lower(), argumentos)

    def parse_expr_argumento(self):
        if self.coincide(TokenType.POINT):
            return self.parse_point_literal()
        if self.coincide(TokenType.POLYGON):
            return self.parse_polygon_literal()
        if self.coincide(TokenType.MINUS) or self.coincide(TokenType.NUMBER):
            return self.parse_numero_con_signo()
        if self.coincide(TokenType.STRING):
            return self.avanzar().value
        if self.coincide(TokenType.IDENT):
            return self.parse_columna_ref()
        t = self.actual()
        raise ParserError(f"pos {t.pos}: argumento de funcion invalido '{t.value}'")

    def parse_columnas(self):
        if self.coincide(TokenType.STAR):
            self.avanzar()
            return ["*"]
        cols = [self.parse_item_columna()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            cols.append(self.parse_item_columna())
        return cols

    def parse_item_columna(self):
        if self.coincide(TokenType.IDENT) and self.siguiente().type == TokenType.LPAREN:
            return self.parse_aggregate_call()
        return self.parse_columna_ref()

    def parse_aggregate_call(self):
        tok = self.esperar(TokenType.IDENT)
        nombre = tok.value.lower()
        if nombre not in FUNCIONES_AGREGADAS:
            raise ParserError(f"pos {tok.pos}: funcion '{tok.value}' no reconocida en el SELECT "
                f"(agregadas disponibles: {', '.join(sorted(FUNCIONES_AGREGADAS))})")
        self.esperar(TokenType.LPAREN)
        if self.coincide(TokenType.STAR):
            self.avanzar()
            columna = "*"
        else:
            columna = self.parse_columna_ref()
        self.esperar(TokenType.RPAREN)
        return AggregateCall(nombre, columna)

    def parse_order_by(self):
        self.esperar(TokenType.ORDER)
        self.esperar(TokenType.BY)

        if self.coincide(TokenType.IDENT) and self.siguiente().type == TokenType.LPAREN:
            funcion = self.parse_func_call()
            desc = False
            if self.coincide(TokenType.DESC):
                self.avanzar()
                desc = True
            elif self.coincide(TokenType.ASC):
                self.avanzar()
            return OrderBy(funcion=funcion, descendente=desc)

        col = self.parse_columna_ref()
        desc = False
        if self.coincide(TokenType.DESC):
            self.avanzar()
            desc = True
        elif self.coincide(TokenType.ASC):
            self.avanzar()
        return OrderBy(col, desc)

    def parse_group_by(self):
        self.esperar(TokenType.GROUP)
        self.esperar(TokenType.BY)
        return self.parse_columna_ref()

    def parse_insert(self):
        self.esperar(TokenType.INSERT)
        self.esperar(TokenType.INTO)
        tabla = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.VALUES)
        self.esperar(TokenType.LPAREN)
        valores = self.parse_valores()
        self.esperar(TokenType.RPAREN)
        return InsertNode(tabla, valores)

    def parse_valores(self):
        valores = [self.parse_valor()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            valores.append(self.parse_valor())
        return valores

    def parse_delete(self):
        self.esperar(TokenType.DELETE)
        self.esperar(TokenType.FROM)
        tabla = self.esperar(TokenType.IDENT).value
        where = None
        if self.coincide(TokenType.WHERE):
            self.avanzar()
            where = self.parse_condicion()
        return DeleteNode(tabla, where)

    def parse_update(self):
        self.esperar(TokenType.UPDATE)
        tabla = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.SET)
        asignaciones = [self.parse_asignacion()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            asignaciones.append(self.parse_asignacion())
        where = None
        if self.coincide(TokenType.WHERE):
            self.avanzar()
            where = self.parse_condicion()
        return UpdateNode(tabla, asignaciones, where)

    def parse_asignacion(self):
        columna = self.esperar(TokenType.IDENT).value
        self.esperar(TokenType.EQ)
        valor = self.parse_valor_literal()
        return (columna, valor)

    def parse_valor_literal(self):
        if self.coincide(TokenType.MINUS) or self.coincide(TokenType.NUMBER):
            return self.parse_numero_con_signo()
        if self.coincide(TokenType.STRING):
            return self.avanzar().value
        if self.coincide(TokenType.POINT):
            return self.parse_point_literal()
        tok = self.actual()
        raise ParserError(f"pos {tok.pos}: valor invalido en SET '{tok.value}'")

    def parse_condicion(self):
        return self.parse_or()

    def parse_or(self):
        izq = self.parse_and()
        while self.coincide(TokenType.OR):
            self.avanzar()
            der = self.parse_and()
            izq = BinaryCondition(izq, TokenType.OR, der)
        return izq

    def parse_and(self):
        izq = self.parse_not()
        while self.coincide(TokenType.AND):
            self.avanzar()
            der = self.parse_not()
            izq = BinaryCondition(izq, TokenType.AND, der)
        return izq

    def parse_not(self):
        if self.coincide(TokenType.NOT):
            self.avanzar()
            interior = self.parse_not()
            return NotCondition(interior)
        return self.parse_comparacion()

    def parse_comparacion(self):
        if self.coincide(TokenType.LPAREN):
            self.avanzar()
            expr = self.parse_condicion()
            self.esperar(TokenType.RPAREN)
            return expr

        if self.coincide(TokenType.IDENT) and self.siguiente().type == TokenType.LPAREN:
            funcion = self.parse_func_call()
            if self.actual().type in OPERADORES_COMP:
                op = self.avanzar().type
                valor = self.parse_valor()
                return SpatialCondition(funcion, op, valor)
            return SpatialCondition(funcion)

        col = self.parse_columna_ref()

        negar = False
        if self.coincide(TokenType.NOT):
            self.avanzar()
            negar = True

        if self.coincide(TokenType.LIKE):
            self.avanzar()
            tok = self.esperar(TokenType.STRING)
            cond = Condition(col, TokenType.LIKE, tok.value)
            return NotCondition(cond) if negar else cond

        if self.coincide(TokenType.IN):
            self.avanzar()
            self.esperar(TokenType.LPAREN)
            if self.coincide(TokenType.SELECT):
                valor = SubquerySelect(self.parse_select())
            else:
                valor = self.parse_valores()
            self.esperar(TokenType.RPAREN)
            cond = Condition(col, TokenType.IN, valor)
            return NotCondition(cond) if negar else cond

        if self.coincide(TokenType.BETWEEN):
            self.avanzar()
            bajo = self.parse_valor()
            self.esperar(TokenType.AND)
            alto = self.parse_valor()
            cond = BinaryCondition(
                Condition(col, TokenType.GTE, bajo), TokenType.AND, Condition(col, TokenType.LTE, alto))
            return NotCondition(cond) if negar else cond

        if negar:
            t = self.actual()
            raise ParserError(f"pos {t.pos}: NOT solo se puede usar antes de LIKE, IN o BETWEEN "
                f"(salio {t.type.name})")

        if self.actual().type not in OPERADORES_COMP:
            raise ParserError(f"pos {self.actual().pos}: falta operador de comparacion")
        op = self.avanzar().type
        valor = self.parse_valor()
        return Condition(col, op, valor)

    def parse_valor(self):
        if self.coincide(TokenType.MINUS) or self.coincide(TokenType.NUMBER):
            return self.parse_numero_con_signo()
        if self.coincide(TokenType.STRING):
            return self.avanzar().value
        if self.coincide(TokenType.POINT):
            return self.parse_point_literal()
        if self.coincide(TokenType.IDENT):
            return ColumnRef(self.parse_columna_ref())
        tok = self.actual()
        raise ParserError(f"pos {tok.pos}: valor invalido '{tok.value}'")