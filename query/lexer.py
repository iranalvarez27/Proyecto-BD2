from query.tokens import Token, TokenType, KEYWORDS

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, texto: str):
        self._texto = texto
        self._pos = 0 
        self._n = len(texto)

    def _actual(self) -> str:
        if self._pos < self._n:
            return self._texto[self._pos]
        return ""

    def _siguiente(self) -> str:
        if self._pos + 1 < self._n:
            return self._texto[self._pos + 1]
        return ""

    def _avanzar(self) -> None:
        self._pos += 1

    def tokenize(self) -> list[Token]:
        tokens = []
        while self._pos < self._n:
            c = self._actual()

            if c.isspace():
                self._avanzar()
                continue

            if c.isalpha() or c == "_":
                tokens.append(self._leer_palabra())
                continue

            if c.isdigit():
                tokens.append(self._leer_numero())
                continue

            if c == "'":
                tokens.append(self._leer_string())
                continue

            tokens.append(self._leer_simbolo())

        tokens.append(Token(TokenType.EOF, "", self._pos))
        return tokens

    def _leer_palabra(self) -> Token:
        inicio = self._pos
        while self._actual().isalnum() or self._actual() == "_":
            self._avanzar()
        texto = self._texto[inicio:self._pos]

        tipo = KEYWORDS.get(texto.lower())
        if tipo is not None:
            return Token(tipo, texto, inicio)
        return Token(TokenType.IDENT, texto, inicio)

    def _leer_numero(self) -> Token:
        inicio = self._pos
        tiene_punto = False
        while self._actual().isdigit() or (self._actual() == "." and not tiene_punto):
            if self._actual() == ".":
                tiene_punto = True
            self._avanzar()
        texto = self._texto[inicio:self._pos]
        return Token(TokenType.NUMBER, texto, inicio)

    def _leer_string(self) -> Token:
        inicio = self._pos
        self._avanzar()
        contenido = []
        while self._actual() != "'":
            if self._actual() == "":
                raise LexerError(f"String sin cerrar en posicion {inicio}")
            contenido.append(self._actual())
            self._avanzar()
        self._avanzar() 
        return Token(TokenType.STRING, "".join(contenido), inicio)

    def _leer_simbolo(self) -> Token:
        c = self._actual()
        inicio = self._pos

        dos = c + self._siguiente()
        if dos == "<=":
            self._avanzar(); self._avanzar()
            return Token(TokenType.LTE, "<=", inicio)
        if dos == ">=":
            self._avanzar(); self._avanzar()
            return Token(TokenType.GTE, ">=", inicio)
        if dos == "!=" or dos == "<>":
            self._avanzar(); self._avanzar()
            return Token(TokenType.NEQ, dos, inicio)

        simple = {"=": TokenType.EQ, "<": TokenType.LT, ">": TokenType.GT,
                 "*": TokenType.STAR,",": TokenType.COMMA, "(": TokenType.LPAREN,
                 ")": TokenType.RPAREN, }

        tipo = simple.get(c)
        if tipo is not None:
            self._avanzar()
            return Token(tipo, c, inicio)

        raise LexerError(f"Caracter inesperado '{c}' en posicion {inicio}")