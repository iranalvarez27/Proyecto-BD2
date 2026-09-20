import struct
from common.types import Schema, DataType

LENGTH_PREFIX_CODE = "H"
LENGTH_PREFIX_SIZE = struct.calcsize(LENGTH_PREFIX_CODE)

_FIXED_CODES = {
    DataType.SMALLINT: "h",
    DataType.INT: "i",
    DataType.BIGINT: "q",
    DataType.FLOAT: "f",
    DataType.DOUBLE: "d",
    DataType.BOOL: "?",
}


def _fixed_struct_code(col) -> str:
    if col.type == DataType.CHAR:
        return f"{col.size}s"
    if col.type == DataType.POINT:
        return "dd"
    code = _FIXED_CODES.get(col.type)
    if code is None:
        raise ValueError(f"Not a fixed-size type: {col.type}")
    return code


def _campos_struct(col) -> int:
    return 2 if col.type == DataType.POINT else 1


def _header_format(schema: Schema) -> str:
    fixed = "".join(
        _fixed_struct_code(c) for c in schema.columns if c.type != DataType.VARCHAR
    )
    n_varchar = sum(1 for c in schema.columns if c.type == DataType.VARCHAR)
    return "<" + fixed + LENGTH_PREFIX_CODE * n_varchar


class Record:

    def __init__(self, values: list):
        self.values = values

    def __repr__(self) -> str:
        return f"Record({self.values})"

    def pack(self, schema: Schema) -> bytes:
        if len(self.values) != len(schema.columns):
            raise ValueError(f"Expected {len(schema.columns)} values, got {len(self.values)}")
        fixed_values = []
        varchar_raws: list[bytes] = []

        for col, val in zip(schema.columns, self.values):
            if col.type == DataType.VARCHAR:
                raw = val.encode("utf-8")
                if len(raw) > col.size:
                    raise ValueError(
                        f"'{val}' exceeds VARCHAR({col.size}) for column '{col.name}'"
                    )
                varchar_raws.append(raw)
            elif col.type == DataType.CHAR:
                raw = val.encode("utf-8")
                if len(raw) > col.size:
                    raise ValueError(
                        f"'{val}' exceeds CHAR({col.size}) for column '{col.name}'"
                    )
                fixed_values.append(raw)
            elif col.type == DataType.POINT:
                lat, lon = (val.lat, val.lon) if hasattr(val, "lat") else val
                fixed_values.append(float(lat))
                fixed_values.append(float(lon))
            else:
                fixed_values.append(val)

        header_values = fixed_values + [len(raw) for raw in varchar_raws]
        header = struct.pack(_header_format(schema), *header_values)

        return header + b"".join(varchar_raws)

    @staticmethod
    def unpack(data: bytes, schema: Schema) -> "Record":
        fixed_columns = [c for c in schema.columns if c.type != DataType.VARCHAR]
        varchar_columns = [c for c in schema.columns if c.type == DataType.VARCHAR]

        header_format = _header_format(schema)
        header = struct.unpack_from(header_format, data, 0)

        n_fixed_fields = sum(_campos_struct(c) for c in fixed_columns)
        fixed_raw = header[:n_fixed_fields]
        varchar_lengths = header[n_fixed_fields:]

        by_name = {}
        cursor = 0
        for col in fixed_columns:
            if col.type == DataType.CHAR:
                by_name[col.name] = fixed_raw[cursor].decode("utf-8").rstrip("\x00")
                cursor += 1
            elif col.type == DataType.POINT:
                by_name[col.name] = (fixed_raw[cursor], fixed_raw[cursor + 1])
                cursor += 2
            else:
                by_name[col.name] = fixed_raw[cursor]
                cursor += 1

        offset = struct.calcsize(header_format)
        for col, length in zip(varchar_columns, varchar_lengths):
            raw = struct.unpack_from(f"<{length}s", data, offset)[0]
            offset += length
            by_name[col.name] = raw.decode("utf-8")

        return Record([by_name[c.name] for c in schema.columns])

    @staticmethod
    def read_from(stream, schema: Schema) -> "Record | None":
        header_format = _header_format(schema)
        header = stream.read(struct.calcsize(header_format))
        if not header:
            return None
        n_varchar = sum(1 for c in schema.columns if c.type == DataType.VARCHAR)
        fields = struct.unpack(header_format, header)
        body = stream.read(sum(fields[len(fields) - n_varchar:]))
        return Record.unpack(header + body, schema)

    @staticmethod
    def fixed_size(schema: Schema) -> int:
        fixed = "".join(
            _fixed_struct_code(c) for c in schema.columns if c.type != DataType.VARCHAR
        )
        return struct.calcsize("<" + fixed)

    def packed_size(self, schema: Schema) -> int:
        return len(self.pack(schema))
