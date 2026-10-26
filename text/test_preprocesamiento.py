import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from text.preprocesamiento import contar_terminos, normalizar, preprocesar, tokenizar


def test_ejemplo_bag_of_words_de_clase():
    documentos = [
        "La casa es grande",
        "El gato está en la casa",
        "La casa es bonita y grande",
        "El sol brilla sobre la casa",
    ]
    procesados = [preprocesar(d, stemming=False) for d in documentos]
    assert procesados == [
        ["casa", "grande"],
        ["gato", "casa"],
        ["casa", "bonita", "grande"],
        ["sol", "brilla", "casa"],
    ]


def test_stemming_une_palabras_de_la_misma_raiz():
    assert preprocesar("Mis amigas y amigos peruanos son estudiosos.") == ["amig", "amig", "peruan", "estudi"]
    assert preprocesar("autorizar") == preprocesar("autorización")


def test_siglas_con_y_sin_puntos_coinciden():
    assert preprocesar("La O.N.U. aprobó") == preprocesar("la ONU aprobo")
    assert normalizar("O.N.U") == "onu"


def test_consulta_sin_tildes_coincide_con_documento():
    assert preprocesar("Programación en Perú") == preprocesar("programacion en peru")


def test_conserva_la_enie():
    assert normalizar("Año Niño") == "año niño"
    assert preprocesar("año") != preprocesar("ano")


def test_tokenizacion_quita_puntuacion_y_letras_sueltas():
    assert tokenizar(normalizar('Laptop HP 15", 8GB RAM; ¡oferta!')) == ["laptop", "hp", "15", "8gb", "ram", "oferta"]
    assert tokenizar("a b 4 x") == ["4"]


def test_descarta_tokens_demasiado_largos():
    pegado = "504c1931101haierle19b13200le19b13200ale1" * 3
    assert tokenizar(f"bateria {pegado} haier") == ["bateria", "haier"]
    assert tokenizar("x" * 50) == ["x" * 50]


def test_ingles():
    assert preprocesar("Machine Learning for the laptops", idioma="english") == ["machin", "learn", "laptop"]


def test_contar_terminos_da_el_tf():
    assert contar_terminos("seguro de carro, seguro de auto") == {"segur": 2, "carr": 1, "aut": 1}


def test_texto_vacio_o_solo_stopwords():
    assert preprocesar("") == []
    assert preprocesar("de la y el") == []


def test_idioma_no_soportado():
    with pytest.raises(ValueError):
        preprocesar("hola", idioma="french")
