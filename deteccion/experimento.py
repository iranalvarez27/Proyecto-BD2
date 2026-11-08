import argparse
import csv
import os
from pathlib import Path

import numpy as np

from index.vector.exacto import knn_exacto_lote
from multimedia import bovw, config
from multimedia.mfcc import cargar_audio

REPRESENTACIONES = {"A_boaw": lambda x: x, "B_raiz": np.sqrt}
MODIFICACIONES = ("ninguna", "ruido", "volumen", "tempo")


def cargar_rutas(ruta_objetos: Path) -> dict[str, str]:
    with open(ruta_objetos, encoding="utf-8", newline="") as f:
        return {fila[0]: fila[1] for fila in csv.reader(f) if fila and fila[0] != "id"}


def modificar(y, mod: str, rng) -> tuple[np.ndarray, float]:

    if mod == "ruido":
        return y + rng.normal(0, np.sqrt(np.mean(y ** 2)) / 10, len(y)).astype(np.float32), 1.0
    if mod == "volumen":
        return y * 0.4, 1.0
    if mod == "tempo":
        import librosa
        return librosa.effects.time_stretch(y, rate=1.05), 1.05
    return y, 1.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--n", type=int, default=10_000, help="tamano de la coleccion de audio")
    ap.add_argument("--pistas", type=int, default=20)
    ap.add_argument("--dur", type=float, default=10.0, help="duracion del fragmento (s)")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--paso", type=float, default=0.5, help="salto entre ventanas (s)")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--objetos", default=None, help="CSV id,ruta (por defecto bench/data/fma/objetos.csv)")
    args = ap.parse_args(argv)

    rng = np.random.default_rng(args.semilla)
    ruta_objetos = Path(args.objetos) if args.objetos else config.RAIZ / "bench" / "data" / "fma" / "objetos.csv"
    rutas = cargar_rutas(ruta_objetos)

    vectores, ids = bovw.cargar_coleccion("audio", args.n)
    pistas_ids = np.array([str(o[0]) for o in ids])
    segs_ids = np.array([int(o[1]) for o in ids])
    existentes = set(zip(pistas_ids.tolist(), segs_ids.tolist()))
    pistas = [p for p in dict.fromkeys(pistas_ids.tolist()) if p in rutas]
    elegidas = [pistas[i] for i in rng.choice(len(pistas), size=min(args.pistas, len(pistas)), replace=False)]

    ext = bovw._extractor("audio", args.n)
    sr, seg_s = int(ext.meta["sr"]), float(ext.meta.get("seg_s", config.SEG_S))
    print(f"coleccion: {len(ids):,} segmentos de {seg_s:g}s, {len(set(pistas_ids.tolist())):,} pistas | "
          f"{len(elegidas)} pistas de prueba, fragmento {args.dur:g}s, paso {args.paso:g}s, k={args.k}")

    bases = {nombre: f(vectores) for nombre, f in REPRESENTACIONES.items()}

    acum = {(m, r): np.zeros(7) for m in MODIFICACIONES for r in REPRESENTACIONES}

    for pid in elegidas:
        y = cargar_audio(rutas[pid], sr)
        if len(y) < int((args.dur + seg_s) * sr):
            continue
        inicio = rng.uniform(0, len(y) / sr - args.dur)
        frag = y[int(inicio * sr): int((inicio + args.dur) * sr)]
        for mod in MODIFICACIONES:
            fm, factor = modificar(frag, mod, rng)
            t_ini, Q = ext.vectores_senal(fm, args.paso)
            for nombre, f in REPRESENTACIONES.items():
                pos, dist = knn_exacto_lote(f(Q), bases[nombre], args.k, "cosine")
                a = acum[(mod, nombre)]
                for t, fila, d in zip(t_ini, pos, dist):
                    t_orig = inicio + t * factor
                    esperados = {int(t_orig // seg_s) + j for j in (0, 1)}
                    if not any((pid, s) in existentes for s in esperados):
                        continue
                    ok = pistas_ids[fila] == pid
                    a[0] += 1
                    a[1] += ok.any()
                    cerca = ok & (np.abs(segs_ids[fila] - t_orig // seg_s) <= 1)
                    a[2] += cerca.any()
                    sim = 1 - d
                    if ok.any():
                        a[3] += sim[ok].max(); a[4] += 1
                    if (~ok).any():
                        a[5] += sim[~ok].max(); a[6] += 1

    print(f"\n{'modificacion':<12} {'repr':<8} {'ventanas':>8} {'recall_pista':>13} {'recall_pos':>11} "
          f"{'sim_correcta':>13} {'sim_otras':>10}")
    for (mod, nombre), a in acum.items():
        if a[0] == 0:
            continue
        print(f"{mod:<12} {nombre:<8} {int(a[0]):>8} {a[1] / a[0]:>13.3f} {a[2] / a[0]:>11.3f} "
              f"{a[3] / max(a[4], 1):>13.3f} {a[5] / max(a[6], 1):>10.3f}")
    print("\nsim_correcta: mejor similitud coseno de un vecino de la pista correcta; "
          "sim_otras: mejor similitud de un vecino de otra pista (sirve para calibrar el umbral).")


if __name__ == "__main__":
    main()
