import pytest
from recomendacion.fusion import fusionar, normalizar

PESOS = dict(visual=1, texto=1, metadata=0, compras=0)


def test_fusion_deduplica_y_explica():
    r = fusionar({'visual': [(1, .9), (1, .9), (2, .8)], 'texto': [(2, 100), (1, 50)]}, PESOS)
    assert {p['id'] for p in r} == {1, 2}
    assert all(sum(p['aportes_pct'].values()) == pytest.approx(100) for p in r)


def test_combinacion_convexa_de_minmax():
    # visual: 1 -> 1, 2 -> 0; texto: 2 -> 1, 1 -> 0; con pesos 3:1 gana el mejor visual
    r = fusionar({'visual': [(1, .9), (2, .8)], 'texto': [(2, 100), (1, 50)]}, {**PESOS, 'visual': 3})
    assert [p['id'] for p in r] == [1, 2]
    assert r[0]['score_total'] == pytest.approx(.75)
    assert r[1]['score_total'] == pytest.approx(.25)


def test_modalidad_ausente_redistribuye_peso():
    r = fusionar({'visual': [(1, .1)]}, PESOS)
    assert r[0]['score_total'] == pytest.approx(1.0)
    assert fusionar({}, PESOS) == []


def test_escala_global_conserva_la_confianza():
    pesos = dict(visual=0, texto=0, metadata=0, compras=1)
    fuerte = fusionar({'compras': [(1, .072)]}, pesos, {'compras': .3})
    casual = fusionar({'compras': [(2, .0077)]}, pesos, {'compras': .3})
    assert fuerte[0]['score_total'] == pytest.approx(.24)
    assert casual[0]['score_total'] == pytest.approx(.0077 / .3)
    # sin escala global, min-max llevaria los dos a 1
    assert fusionar({'compras': [(2, .0077)]}, pesos)[0]['score_total'] == pytest.approx(1.0)


def test_normalizar_recorta_y_tolera_listas_constantes():
    assert normalizar([.5, .5]) == [1.0, 1.0]
    assert normalizar([.6, .1], escala=.3) == [1.0, pytest.approx(1 / 3)]


@pytest.mark.parametrize('valor', [-1, float('nan'), float('inf')])
def test_pesos_invalidos(valor):
    with pytest.raises(ValueError):
        fusionar({}, {**PESOS, 'visual': valor})


def test_escala_global_ignora_extremos():
    from recomendacion.afinidades import escala_global
    scores = [i / 1000 for i in range(1000)] + [50.0]
    assert escala_global(scores) == pytest.approx(.99, abs=.002)
    assert escala_global([]) is None
    assert escala_global([0.0, 0.0]) is None
