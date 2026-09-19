import heapq
import os
from common.page import PAGE_SIZE
from common.record import Record

MAX_REPARTITION = 4


def external_sort(rows, key, schema, buffer_pages, tmp_dir, reverse=False, stats=None):
    if stats is None:
        stats = {}
    columns = [c.name for c in schema.columns]
    budget = buffer_pages * PAGE_SIZE
    runs = []
    buffer, used = [], 0

    for row in rows:
        size = Record([row[c] for c in columns]).packed_size(schema)
        if buffer and used + size > budget:
            buffer.sort(key=key, reverse=reverse)
            runs.append(_write_run(buffer, columns, schema, tmp_dir, f"sort_{len(runs)}"))
            buffer, used = [], 0
        buffer.append(row)
        used += size

    buffer.sort(key=key, reverse=reverse)
    if not runs:
        stats.update(runs=0, passes=0)
        return iter(buffer)
    if buffer:
        runs.append(_write_run(buffer, columns, schema, tmp_dir, f"sort_{len(runs)}"))
    stats.update(runs=len(runs), passes=0)

    fan_in = max(2, buffer_pages - 1)
    while len(runs) > fan_in:
        level = stats["passes"]
        groups = [runs[i:i + fan_in] for i in range(0, len(runs), fan_in)]
        runs = [
            _write_run(_merge(group, key, schema, reverse), columns, schema,
                       tmp_dir, f"merge_{level}_{j}")
            for j, group in enumerate(groups)
        ]
        stats["passes"] += 1
    stats["passes"] += 1
    return _merge(runs, key, schema, reverse)


def external_group_by(rows, key, agg, schema, buffer_pages, tmp_dir, stats=None, _depth=0):
    if stats is None:
        stats = {}
    if _depth == 0:
        stats.update(partitions=0, repartitions=0)
    columns = [c.name for c in schema.columns]
    budget = buffer_pages * PAGE_SIZE
    n_parts = max(2, buffer_pages - 1)
    paths = [os.path.join(tmp_dir, f"group_{_depth}_{i}.run") for i in range(n_parts)]
    sizes = [0] * n_parts
    stats["partitions"] += n_parts

    files = [open(p, "wb") for p in paths]
    try:
        for row in rows:
            packed = Record([row[c] for c in columns]).pack(schema)
            i = hash((_depth, key(row))) % n_parts
            files[i].write(packed)
            sizes[i] += len(packed)
    finally:
        for f in files:
            f.close()

    result = {}
    for path, size in zip(paths, sizes):
        partition = _read_run(path, schema)
        if size > budget and _depth < MAX_REPARTITION:
            stats["repartitions"] += 1
            result.update(external_group_by(
                partition, key, agg, schema, buffer_pages, tmp_dir, stats, _depth + 1))
        else:
            for row in partition:
                k = key(row)
                result[k] = agg(result.get(k), row)
    return result


def external_hash_join(left, key_left, right, key_right, schema_left, schema_right,
                        buffer_pages, tmp_dir, combine, stats=None, _depth=0):
    if stats is None:
        stats = {}
    if _depth == 0:
        stats.update(partitions=0, repartitions=0)
    columns_left = [c.name for c in schema_left.columns]
    columns_right = [c.name for c in schema_right.columns]
    budget = buffer_pages * PAGE_SIZE
    n_parts = max(2, buffer_pages - 1)
    stats["partitions"] += n_parts

    left_paths = [os.path.join(tmp_dir, f"joinL_{_depth}_{i}.run") for i in range(n_parts)]
    right_paths = [os.path.join(tmp_dir, f"joinR_{_depth}_{i}.run") for i in range(n_parts)]
    left_sizes = _partition_to_disk(left, key_left, columns_left, schema_left, left_paths, _depth, n_parts)
    right_sizes = _partition_to_disk(right, key_right, columns_right, schema_right, right_paths, _depth, n_parts)

    for i in range(n_parts):
        if left_sizes[i] == 0 or right_sizes[i] == 0:
            os.remove(left_paths[i])
            os.remove(right_paths[i])
            continue

        menor = min(left_sizes[i], right_sizes[i])
        if menor <= budget or _depth >= MAX_REPARTITION:
            yield from _join_partition_in_memory(left_paths[i], left_sizes[i], key_left, schema_left,
                right_paths[i], right_sizes[i], key_right, schema_right,combine,)
        else:
            stats["repartitions"] += 1
            yield from external_hash_join(_read_run(left_paths[i], schema_left), key_left, _read_run(right_paths[i], schema_right), key_right,
                schema_left, schema_right, buffer_pages, tmp_dir, combine, stats, _depth + 1,)


def _partition_to_disk(rows, key, columns, schema, paths, depth, n_parts):
    sizes = [0] * n_parts
    files = [open(p, "wb") for p in paths]
    try:
        for row in rows:
            packed = Record([row[c] for c in columns]).pack(schema)
            i = hash((depth, key(row))) % n_parts
            files[i].write(packed)
            sizes[i] += len(packed)
    finally:
        for f in files:
            f.close()
    return sizes


def _join_partition_in_memory(left_path, left_size, key_left, schema_left, right_path, right_size, key_right, schema_right, combine):
    if left_size <= right_size:
        build_path, build_key, build_schema = left_path, key_left, schema_left
        probe_path, probe_key, probe_schema = right_path, key_right, schema_right
        build_is_left = True
    else:
        build_path, build_key, build_schema = right_path, key_right, schema_right
        probe_path, probe_key, probe_schema = left_path, key_left, schema_left
        build_is_left = False

    tabla_hash = {}
    for row in _read_run(build_path, build_schema):
        tabla_hash.setdefault(build_key(row), []).append(row)

    for row in _read_run(probe_path, probe_schema):
        for match in tabla_hash.get(probe_key(row), ()):
            yield combine(match, row) if build_is_left else combine(row, match)

# runs

def _write_run(rows, columns, schema, tmp_dir, name):
    path = os.path.join(tmp_dir, f"{name}.run")
    with open(path, "wb") as f:
        for row in rows:
            f.write(Record([row[c] for c in columns]).pack(schema))
    return path


def _read_run(path, schema):
    columns = [c.name for c in schema.columns]
    try:
        with open(path, "rb") as f:
            while (record := Record.read_from(f, schema)) is not None:
                yield dict(zip(columns, record.values))
    finally:
        os.remove(path)


def _merge(paths, key, schema, reverse):
    wrap = _Desc if reverse else (lambda v: v)
    readers = [_read_run(p, schema) for p in paths]
    heap = []
    for i, reader in enumerate(readers):
        row = next(reader, None)
        if row is not None:
            heap.append((wrap(key(row)), i, row))
    heapq.heapify(heap)

    while heap:
        _, i, row = heapq.heappop(heap)
        yield row
        row = next(readers[i], None)
        if row is not None:
            heapq.heappush(heap, (wrap(key(row)), i, row))


class _Desc:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return other.value < self.value
