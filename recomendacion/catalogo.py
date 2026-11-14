"""Catalogo curado de la tienda a partir de Amazon Reviews 2023 Electronics."""
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

from data import preparar_amazon as amazon

RAIZ = Path(__file__).resolve().parents[1]
DIR_TIENDA = RAIZ / 'data' / 'tienda'
DIR_IMAGENES = RAIZ / 'bench' / 'data' / 'amazon_img' / 'imgs'
N_PRODUCTOS = 10_000
PRECIO_MINIMO = 1.0
MIN_RESENAS = 20

CA, CAP = 'Computers & Accessories', 'Computer Accessories & Peripherals'
AV, IC = 'Audio & Video Accessories', 'Internal Components'

# ruta de Amazon (sin la raiz Electronics) -> (categoria, subcategoria) de la tienda
REGLAS = {
    (CA, 'Computers & Tablets', 'Laptops'): ('Laptops & Computers', 'Laptops'),
    (CA, 'Computers & Tablets', 'Desktops'): ('Laptops & Computers', 'Desktops'),
    (CA, 'Computers & Tablets', 'Tablets'): ('Laptops & Computers', 'Tablets'),
    (CA, 'Computer Components', IC, 'CPU Processors'): ('Components', 'Processors'),
    (CA, 'Computer Components', IC, 'Graphics Cards'): ('Components', 'Graphics Cards'),
    (CA, 'Computer Components', IC, 'Memory'): ('Components', 'Memory'),
    (CA, 'Computer Components', IC, 'Motherboards'): ('Components', 'Motherboards'),
    (CA, 'Computer Components', IC, 'Internal Power Supplies'): ('Components', 'Power Supplies'),
    (CA, 'Computer Components', IC, 'Fans & Cooling'): ('Components', 'Cooling'),
    (CA, 'Computer Components', 'External Components', 'Computer Cases'): ('Components', 'Cases'),
    (CA, CAP, 'Keyboards, Mice & Accessories', 'Keyboards'): ('Peripherals', 'Keyboards'),
    (CA, CAP, 'Keyboards, Mice & Accessories', 'Mice'): ('Peripherals', 'Mice'),
    (CA, CAP, 'Keyboards, Mice & Accessories', 'Keyboard & Mouse Combos'): ('Peripherals', 'Keyboard & Mouse Combos'),
    (CA, CAP, AV, 'Webcams & VoIP Equipment'): ('Peripherals', 'Webcams'),
    (CA, CAP, AV, 'Computer Microphones'): ('Peripherals', 'Microphones'),
    (CA, CAP, 'Input Devices', 'Graphics Tablets'): ('Peripherals', 'Graphics Tablets'),
    (CA, 'Monitors'): ('Monitors', 'Monitors'),
    (CA, 'Networking Products', 'Routers'): ('Networking', 'Routers'),
    (CA, 'Networking Products', 'Modem Router Combos'): ('Networking', 'Routers'),
    (CA, 'Networking Products', 'Whole Home & Mesh Wi-Fi Systems'): ('Networking', 'Mesh Wi-Fi'),
    (CA, 'Networking Products', 'Switches'): ('Networking', 'Switches'),
    (CA, 'Networking Products', 'Wireless Access Points'): ('Networking', 'Access Points'),
    (CA, 'Networking Products', 'Repeaters'): ('Networking', 'Range Extenders'),
    (CA, 'Networking Products', 'Modems'): ('Networking', 'Modems'),
    (CA, 'Networking Products', 'Network Adapters'): ('Networking', 'Network Adapters'),
    (CA, 'Data Storage', 'Internal Solid State Drives'): ('Storage', 'Internal SSDs'),
    (CA, 'Data Storage', 'External Solid State Drives'): ('Storage', 'External SSDs'),
    (CA, 'Data Storage', 'Internal Hard Drives'): ('Storage', 'Internal Hard Drives'),
    (CA, 'Data Storage', 'External Hard Drives'): ('Storage', 'External Hard Drives'),
    (CA, 'Data Storage', 'USB Flash Drives'): ('Storage', 'USB Flash Drives'),
    (CA, 'Data Storage', 'Network Attached Storage'): ('Storage', 'NAS'),
    (CA, CAP, 'Memory Cards'): ('Storage', 'Memory Cards'),
    ('Headphones, Earbuds & Accessories', 'Headphones & Earbuds', 'Earbud Headphones'): ('Audio', 'Earbuds'),
    ('Headphones, Earbuds & Accessories', 'Headphones & Earbuds', 'Over-Ear Headphones'): ('Audio', 'Headphones'),
    ('Headphones, Earbuds & Accessories', 'Headphones & Earbuds', 'On-Ear Headphones'): ('Audio', 'Headphones'),
    (CA, CAP, AV, 'Computer Headsets'): ('Audio', 'Headsets'),
    (CA, CAP, AV, 'Computer Speakers'): ('Audio', 'Computer Speakers'),
    ('Portable Audio & Video', 'Portable Speakers & Docks', 'Portable Bluetooth Speakers'): ('Audio', 'Bluetooth Speakers'),
    ('Home Audio', 'Speakers', 'Sound Bars'): ('Audio', 'Sound Bars'),
    ('Home Audio', 'Speakers', 'Bookshelf Speakers'): ('Audio', 'Bookshelf Speakers'),
    ('Camera & Photo', 'Digital Cameras', 'Point & Shoot Digital Cameras'): ('Cameras', 'Point & Shoot'),
    ('Camera & Photo', 'Digital Cameras', 'DSLR Cameras'): ('Cameras', 'DSLR'),
    ('Camera & Photo', 'Digital Cameras', 'Mirrorless Cameras'): ('Cameras', 'Mirrorless'),
    ('Camera & Photo', 'Lenses', 'Camera Lenses'): ('Cameras', 'Lenses'),
    ('Camera & Photo', 'Video', 'Camcorders'): ('Cameras', 'Camcorders'),
    ('Camera & Photo', 'Video', 'Sports & Action Video Cameras'): ('Cameras', 'Action Cameras'),
    ('Wearable Technology', 'Smartwatches'): ('Smartwatches', 'Smartwatches'),
}
CATEGORIAS = sorted({c for c, _ in REGLAS.values()})
COLUMNAS = amazon.COLUMNAS_PRODUCTOS + ['url']


def clasificar(categorias: list) -> tuple | None:
    ruta = tuple(categorias[1:])
    for largo in range(len(ruta), 0, -1):
        destino = REGLAS.get(ruta[:largo])
        if destino:
            return destino
    return None


def candidatos(ruta_meta) -> dict:
    """Productos completos de las categorias de la tienda, por categoria y subcategoria."""
    grupos = defaultdict(lambda: defaultdict(list))
    vistos = set()
    with gzip.open(ruta_meta, 'rt', encoding='utf-8') as f:
        for linea in f:
            item = json.loads(linea)
            destino = clasificar(item.get('categories') or [])
            if destino is None:
                continue
            p = amazon.producto_completo(item, MIN_RESENAS)
            if p is None or p['precio'] < PRECIO_MINIMO or p['asin'] in vistos:
                continue
            vistos.add(p['asin'])
            p['categoria'], p['subcategoria'] = destino
            grupos[p['categoria']][p['subcategoria']].append(p)
    for subcategorias in grupos.values():
        for lista in subcategorias.values():
            lista.sort(key=lambda p: (-p['num_resenas'], p['asin']))
    return grupos


def intercalar(subcategorias: dict) -> list:
    """Turnos entre subcategorias, cada una ordenada por cantidad de resenas."""
    listas = [subcategorias[s] for s in sorted(subcategorias)]
    return [l[i] for i in range(max(map(len, listas))) for l in listas if i < len(l)]


def con_imagen(orden: list, cupo: int, dir_imagenes: Path) -> list:
    import cv2
    from bench.datasets.amazon_img import descargar_imagenes

    elegidos, inicio = [], 0
    while len(elegidos) < cupo and inicio < len(orden):
        lote = orden[inicio:inicio + int((cupo - len(elegidos)) * 1.1) + 10]
        inicio += len(lote)
        bajados, _ = descargar_imagenes([{**p, 'id': p['asin']} for p in lote], dir_imagenes)
        validos = {p['asin'] for p in bajados if cv2.imread(p['ruta']) is not None}
        elegidos += [p for p in lote if p['asin'] in validos][:cupo - len(elegidos)]
    return elegidos


def _escribir(ruta, columnas, filas):
    temporal = ruta.with_suffix('.tmp')
    with open(temporal, 'w', encoding='utf-8', newline='') as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        escritor.writerows(filas)
    temporal.replace(ruta)


def construir(n=N_PRODUCTOS, salida=DIR_TIENDA, dir_imagenes=DIR_IMAGENES,
              meta=amazon.META, resenas=amazon.RESENAS) -> dict:
    """Arma productos.csv y compras.csv de la tienda; si ya existen con el mismo n, no hace nada."""
    salida = Path(salida)
    ruta_resumen = salida / 'resumen.json'
    if ruta_resumen.exists():
        resumen = json.loads(ruta_resumen.read_text())
        if resumen.get('n_pedido') == n:
            return resumen
    salida.mkdir(parents=True, exist_ok=True)
    amazon.descargar(amazon.URL_META, meta)
    amazon.descargar(amazon.URL_RESENAS, resenas)

    grupos = candidatos(meta)
    cupo, sobra = divmod(n, len(CATEGORIAS))
    productos = []
    for i, categoria in enumerate(CATEGORIAS):
        productos += con_imagen(intercalar(grupos[categoria]), cupo + (i < sobra), Path(dir_imagenes))
    for pid, p in enumerate(productos, 1):
        p['id'] = pid
    _escribir(salida / 'productos.csv', COLUMNAS, ([p[c] for c in COLUMNAS] for p in productos))

    temporal = salida / 'compras.tmp'
    compras, leidas, usuarios = amazon.extraer_compras(resenas, {p['asin']: p['id'] for p in productos}, temporal)
    temporal.replace(salida / 'compras.csv')
    resumen = {'n_pedido': n, 'productos': len(productos), 'compras': compras, 'usuarios': usuarios,
               'resenas_leidas': leidas,
               'por_categoria': {c: sum(p['categoria'] == c for p in productos) for c in CATEGORIAS}}
    ruta_resumen.write_text(json.dumps(resumen, indent=2))
    return resumen


if __name__ == '__main__':
    print(json.dumps(construir(), indent=2))
