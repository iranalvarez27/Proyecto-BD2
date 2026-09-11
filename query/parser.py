from query.tokens import Token, TokenType
from query.ast import SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition, OrderBy

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
        else:
            raise ParserError(f"error en la consulta, empieza con {self.actual().value}")

        if self.coincide(TokenType.SEMICOLON):
            self.avanzar()
        self.esperar(TokenType.EOF)
        return nodo

    def parse_select(self):
        self.esperar(TokenType.SELECT)
        cols = self.parse_columnas()
        self.esperar(TokenType.FROM)
        tabla = self.esperar(TokenType.IDENT).value

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

        return SelectNode(cols, tabla, where, order_by, group_by)

    def parse_columnas(self):
        if self.coincide(TokenType.STAR):
            self.avanzar()
            return ["*"]
        cols = [self.esperar(TokenType.IDENT).value]
        while self.coincide(TokenType.COMMA):
            self.avanzar()
            cols.append(self.esperar(TokenType.IDENT).value)
        return cols

    def parse_order_by(self):
        self.esperar(TokenType.ORDER)
        self.esperar(TokenType.BY)
        col = self.esperar(TokenType.IDENT).value
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
        return self.esperar(TokenType.IDENT).value

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

        col = self.esperar(TokenType.IDENT).value
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