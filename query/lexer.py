from query.tokens import Token, TokenType, KEYWORDS

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, texto: str):
        self._texto = texto
        self._pos = 0
        self._n = len(texto)

    def actual(self) -> str:
        if self._pos < self._n:
            return self._texto[self._pos]
        return ""

    def siguiente(self) -> str:
        if self._pos + 1 < self._n:
            return self._texto[self._pos + 1]
        return ""

    def avanzar(self) -> None:
        self._pos += 1

    def tokenize(self) -> list[Token]:
        tokens = []
        while self._pos < self._n:
            c = self.actual()

            if c.isspace():
                self.avanzar()
                continue

            if c.isalpha() or c == "_":
                tokens.append(self.leer_palabra())
                continue

            if c.isdigit():
                tokens.append(self.leer_numero())
                continue

            if c == "'":
                tokens.append(self.leer_string())
                continue

            tokens.append(self.leer_simbolo())

        tokens.append(Token(TokenType.EOF, "", self._pos))
        return tokens

    def leer_palabra(self) -> Token:
        inicio = self._pos
        while self.actual().isalnum() or self.actual() == "_":
            self.avanzar()
        texto = self._texto[inicio:self._pos]

        tipo = KEYWORDS.get(texto.lower())
        if tipo is not None:
            return Token(tipo, texto, inicio)
        return Token(TokenType.IDENT, texto, inicio)

    def leer_numero(self) -> Token:
        inicio = self._pos
        tiene_punto = False
        while self.actual().isdigit() or (self.actual() == "." and not tiene_punto):
            if self.actual() == ".":
                tiene_punto = True
            self.avanzar()
        texto = self._texto[inicio:self._pos]
        return Token(TokenType.NUMBER, texto, inicio)

    def leer_string(self) -> Token:
        inicio = self._pos
        self.avanzar()
        contenido = []
        while self.actual() != "'":
            if self.actual() == "":
                raise LexerError(f"string sin cerrar en posicion {inicio}")
            contenido.append(self.actual())
            self.avanzar()
        self.avanzar()
        return Token(TokenType.STRING, "".join(contenido), inicio)

    def leer_simbolo(self) -> Token:
        c = self.actual()
        inicio = self._pos

        if c == "<" and self.siguiente() == "=":
            self.avanzar()
            self.avanzar()
            return Token(TokenType.LTE, "<=", inicio)
        if c == ">" and self.siguiente() == "=":
            self.avanzar()
            self.avanzar()
            return Token(TokenType.GTE, ">=", inicio)
        if c == "!" and self.siguiente() == "=":
            self.avanzar()
            self.avanzar()
            return Token(TokenType.NEQ, "!=", inicio)
        if c == "<" and self.siguiente() == ">":
            self.avanzar()
            self.avanzar()
            return Token(TokenType.NEQ, "<>", inicio)

        simple = {"=": TokenType.EQ, "<": TokenType.LT, ">": TokenType.GT,
                 "*": TokenType.STAR, ",": TokenType.COMMA, "(": TokenType.LPAREN,
                 ")": TokenType.RPAREN, ";": TokenType.SEMICOLON, ".": TokenType.DOT,
                 "-": TokenType.MINUS}

        if c in simple:
            self.avanzar()
            return Token(simple[c], c, inicio)

        raise LexerError(f"caracter inesperado '{c}' en posicion {inicio}")