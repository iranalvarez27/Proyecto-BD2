import pytest
from query.lexer import Lexer, LexerError
from query.parser import Parser
from recomendacion.repositorio import literal


@pytest.mark.parametrize('texto', ["John's camera", '"quoted"', "'; DELETE FROM x; '`,\\", "", "a''b"])
def test_literal_sql_conserva_texto(texto):
    nodo = Parser(Lexer(f'INSERT INTO ejemplo VALUES (1, {literal(texto)})').tokenize()).parse()
    assert nodo.valores == [1, texto]


def test_comilla_sin_cerrar():
    with pytest.raises(LexerError):
        Lexer("SELECT * FROM x WHERE nombre = 'abc''").tokenize()
