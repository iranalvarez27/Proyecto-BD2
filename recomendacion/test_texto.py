from recomendacion.texto import terminos_relevantes


class IndiceFalso:
    idioma, stemming = 'english', True

    def __init__(self, df, n=1000):
        self._df, self._n = df, n

    def total_docs(self):
        return self._n

    def df(self, termino):
        return self._df.get(termino, 0)


def test_prioriza_terminos_repetidos_y_raros_en_la_coleccion():
    indice = IndiceFalso({'speaker': 40, 'waterproof': 8, 'bluetooth': 300, 'the': 900, 'oontz': 2})
    texto = 'Bluetooth speaker, waterproof speaker. The OontZ speaker is waterproof and bluetooth ready'
    # waterproof repite menos que speaker pero es mas rara; oontz (df < 5) y ready quedan fuera
    assert terminos_relevantes(indice, texto) == ['waterproof', 'speaker', 'bluetooth']


def test_texto_sin_terminos_repetidos_no_da_terminos():
    indice = IndiceFalso({'webcam': 20, 'hd': 100})
    assert terminos_relevantes(indice, 'HD webcam') == []


def test_limite_de_terminos():
    indice = IndiceFalso({f'w{i}': 10 + i for i in range(40)})
    texto = ' '.join(f'w{i} w{i}' for i in range(40))
    assert len(terminos_relevantes(indice, texto, max_terminos=25)) == 25
