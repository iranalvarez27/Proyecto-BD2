"""Smoke test de los contratos JSON usados por las visualizaciones del frontend."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.engine_adapter import EngineAdapter


def main() -> None:
    # El BufferPool conserva handles abiertos hasta que termina el proceso en
    # Windows; por eso el directorio temporal ignora un fallo de limpieza final.
    with tempfile.TemporaryDirectory(prefix="bd2-viz-", ignore_cleanup_errors=True) as data_dir:
        engine = EngineAdapter(data_dir)

        mutation = engine.execute_query(
            "INSERT INTO estudiantes VALUES "
            "(99, 'Prueba Visual', 'Ciencia de Datos', 18.0);",
            "viz-test",
        )
        assert mutation["status"] == "success", mutation
        animations = mutation["visualize"]["animations"]
        assert {item["kind"] for item in animations} >= {"bplus", "hash"}
        print("mutation", [(item["kind"], len(item.get("disk_events", []))) for item in animations])

        spatial = engine.execute_query(
            "SELECT * FROM tiendas WHERE "
            "distancia(ubicacion, POINT(-12.0931, -77.0465)) < 2000;",
            "viz-test",
        )
        assert spatial["status"] == "success", spatial
        rtree_info = spatial["spatial"]["rtree"]
        trace = rtree_info["trace"]
        order = trace["order"]
        assert order, "la traza del R-Tree vino vacia"
        assert all("type" in event for event in order)
        assert all(event["type"] in ("visit", "prune", "hit") for event in order)
        tree = rtree_info["tree"]
        assert tree["nodes"], "el snapshot del R-Tree vino vacio"
        node_ids = {node["id"] for node in tree["nodes"]}
        assert all(event["id"] in node_ids for event in order if event["type"] in ("visit", "prune"))
        visited = {e["id"] for e in order if e["type"] == "visit"}
        pruned = {e["id"] for e in order if e["type"] == "prune"}
        print("rtree", len(visited), len(pruned), len(order))

        reorganized = engine.reorganize_table("cursos")
        sequential = reorganized["visualize"]["sequential"]
        assert sequential["before"] is not None and sequential["after"] is not None
        print("sequential", len(sequential["before"]["main"]), len(sequential["after"]["main"]))


if __name__ == "__main__":
    main()
