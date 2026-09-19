from query.tokens import Token, TokenType
from query.ast import (
    SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition, OrderBy, JoinClause,
    BeginNode, CommitNode, RollbackNode, ExplainNode, ColumnDef, CreateTableNode, DropTableNode,
)

class ParserError(Exception):
    pass

OPERADORES_COMP = [TokenType.EQ, TokenType.NEQ, TokenType.LT, TokenType.LTE, TokenType.GT, TokenType.GTE]

class Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def actual(self):
        return self._tokens[self._pos]

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
        elif self.coincide(TokenType.BEGIN) or self.coincide(TokenType.START):
            nodo = self.parse_begin()
        elif self.coincide(TokenType.COMMIT) or self.coincide(TokenType.END):
            nodo = self.parse_commit()
        elif self.coincide(TokenType.ROLLBACK) or self.coincide(TokenType.ABORT):
            nodo = self.parse_rollback()
        elif self.coincide(TokenType.EXPLAIN):
            nodo = self.parse_explain()
        elif self.coincide(TokenType.CREATE):
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
        else:
            t = self.actual()
            raise ParserError(
                f"pos {t.pos}: EXPLAIN solo soporta SELECT, INSERT o DELETE, salio {t.type.name} ({t.value})")
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
        # DROP TABLE nombre
        self.esperar(TokenType.DROP)
        self.esperar(TokenType.TABLE)
        tabla = self.esperar(TokenType.IDENT).value
        return DropTableNode(tabla)

    def parse_column_def(self):
        nombre = self.esperar(TokenType.IDENT).value
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

        join = None
        if self.coincide(TokenType.JOIN):
            join = self.parse_join()

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

        return SelectNode(cols, tabla, where, order_by, group_by, join)

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

    def parse_columnas(self):
        if self.coincide(TokenType.STAR):
            self.avanzar()
            return ["*"]
        cols = [self.parse_columna_ref()]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            cols.append(self.parse_columna_ref())
        return cols

    def parse_order_by(self):
        self.esperar(TokenType.ORDER)
        self.esperar(TokenType.BY)
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
        izq = self.parse_comparacion()
        while self.coincide(TokenType.AND):
            self.avanzar()
            der = self.parse_comparacion()
            izq = BinaryCondition(izq, TokenType.AND, der)
        return izq

    def parse_comparacion(self):
        if self.coincide(TokenType.LPAREN):
            self.avanzar()
            expr = self.parse_condicion()
            self.esperar(TokenType.RPAREN)
            return expr

        col = self.parse_columna_ref()

        if self.coincide(TokenType.BETWEEN):
            self.avanzar()
            bajo = self.parse_valor()
            self.esperar(TokenType.AND)
            alto = self.parse_valor()
            return BinaryCondition(
                Condition(col, TokenType.GTE, bajo), TokenType.AND, Condition(col, TokenType.LTE, alto))

        if self.actual().type not in OPERADORES_COMP:
            raise ParserError(f"pos {self.actual().pos}: falta operador de comparacion")
        op = self.avanzar().type
        valor = self.parse_valor()
        return Condition(col, op, valor)

    def parse_valor(self):
        tok = self.actual()
        if tok.type == TokenType.NUMBER:
            self.avanzar()
            if "." in tok.value:
                return float(tok.value) 
            else:
                return int(tok.value)
        if tok.type == TokenType.STRING:
            self.avanzar()
            return tok.value
        raise ParserError(f"pos {tok.pos}: valor invalido '{tok.value}'")