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


@pytest.mark.parametrize('valor', [1.2e-05, 0.0, 3.5, -2.25e-12, 7.0])
def test_literal_float_sin_notacion_cientifica(valor):
    nodo = Parser(Lexer(f'INSERT INTO ejemplo VALUES (1, {literal(valor)})').tokenize()).parse()
    assert abs(nodo.valores[1] - valor) < 1e-15
