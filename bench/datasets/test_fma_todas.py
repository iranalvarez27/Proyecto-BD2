import json
from pathlib import Path

import pytest

from bench.datasets.fma_todas import inventario, publicar_tabla


def test_inventario_incluye_archivos_pequenos_para_auditar_errores(tmp_path):
    carpeta = tmp_path / 'fma_small' / '035'
    carpeta.mkdir(parents=True)
    (carpeta / '035198.mp3').write_bytes(b'corrupto')
    (carpeta / '035527.mp3').write_bytes(b'original')
    pistas = inventario(tmp_path, 'small', {35527: {'track_id': 35527, 'titulo': 'Downtown'}})
    assert [p['track_id'] for p in pistas] == [35198, 35527]
    assert pistas[1]['titulo'] == 'Downtown'
    assert Path(pistas[0]['ruta']).is_absolute()


def test_fallo_de_construccion_no_publica_tabla_parcial(tmp_path, monkeypatch):
    from bench.datasets import fma
    catalogo = {'version': 1, 'tablas': {'audios_10k': {'archivos': ['audios_10k.bin']}}}
    (tmp_path / 'catalog.json').write_text(json.dumps(catalogo), encoding='utf-8')
    (tmp_path / 'audios_10k.bin').write_bytes(b'coleccion anterior')
    def fallar(pistas, tamanos, destino, metodo_indice):
        (Path(destino) / 'audios_120000.bin').write_bytes(b'incompleto')
        raise RuntimeError('fallo simulado antes de publicar')
    monkeypatch.setattr(fma, 'ingestar_tablas_audio', fallar)
    with pytest.raises(RuntimeError):
        publicar_tabla([], 120000, tmp_path, 'HNSW')
    assert json.loads((tmp_path / 'catalog.json').read_text()) == catalogo
    assert (tmp_path / 'audios_10k.bin').read_bytes() == b'coleccion anterior'
    assert not (tmp_path / 'audios_120000.bin').exists()


def test_publicacion_conserva_otras_tablas(tmp_path, monkeypatch):
    from bench.datasets import fma
    catalogo = {'version': 1, 'tablas': {'audios_10k': {'archivos': ['audios_10k.bin']}}}
    (tmp_path / 'catalog.json').write_text(json.dumps(catalogo), encoding='utf-8')
    tabla = 'audios_120k'
    def construir(pistas, tamanos, destino, metodo_indice):
        destino = Path(destino)
        (destino / (tabla + '.bin')).write_bytes(b'completo')
        (destino / (tabla + '_id_bplus.idx')).write_bytes(b'indice')
        (destino / 'catalog.json').write_text(json.dumps({'version': 1, 'tablas': {
            tabla: {'archivos': [tabla + '.bin'], 'indices': []}}}), encoding='utf-8')
    monkeypatch.setattr(fma, 'ingestar_tablas_audio', construir)
    assert publicar_tabla([], 120000, tmp_path, 'HNSW') == tabla
    publicado = json.loads((tmp_path / 'catalog.json').read_text())
    assert publicado['tablas']['audios_10k'] == catalogo['tablas']['audios_10k']
    assert (tmp_path / (tabla + '.bin')).read_bytes() == b'completo'
    assert (tmp_path / (tabla + '_id_bplus.idx')).read_bytes() == b'indice'


def test_archivos_fallidos_no_interrumpen_expansion_de_segmentos():
    from bench.datasets.fma_todas import fuentes_utilizables
    objetos = [('35527', 'a.mp3'), ('98565', 'b.mp3'), ('99134', 'c.mp3')]
    manifiesto = {'35527': {'estado': 'ok'}, '98565': {'estado': 'error'}}
    assert fuentes_utilizables(objetos, manifiesto) == ['35527']
