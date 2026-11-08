import pytest
from recomendacion.fusion import fusionar

PESOS = dict(visual=1, texto=1, metadata=0, compras=0)


def test_fusion_deduplica_y_explica():
    r = fusionar({'visual': [(1, .9), (1, .9), (2, .8)], 'texto': [(2, 100), (1, 50)]}, PESOS)
    assert [p['id'] for p in r] == [1, 2]
    assert all(sum(p['aportes_pct'].values()) == pytest.approx(100) for p in r)


def test_modalidad_ausente_redistribuye_peso():
    r = fusionar({'visual': [(1, .1)]}, PESOS)
    assert r[0]['score_total'] == pytest.approx(1 / 61)
    assert fusionar({}, PESOS) == []


@pytest.mark.parametrize('valor', [-1, float('nan'), float('inf')])
def test_pesos_invalidos(valor):
    with pytest.raises(ValueError):
        fusionar({}, {**PESOS, 'visual': valor})
