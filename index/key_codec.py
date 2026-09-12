import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import DataType

# Two entries must always fit in a node page or splitting never terminates:
# 2 * (2 + 8 + K) <= 4096 - 16.
MAX_KEY_SIZE = 2030

MASK64 = (1 << 64) - 1
SIGN_BIT = 1 << 63

_INT_TYPES = frozenset({DataType.SMALLINT, DataType.INT, DataType.BIGINT})
_FLOAT_TYPES = frozenset({DataType.FLOAT, DataType.DOUBLE})
_STR_TYPES = frozenset({DataType.CHAR, DataType.VARCHAR})

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Part of the on-disk format (the metapage's key_type byte): append, never
# renumber.
_TYPE_CODES = {
    DataType.SMALLINT: 1,
    DataType.INT: 2,
    DataType.BIGINT: 3,
    DataType.FLOAT: 4,
    DataType.DOUBLE: 5,
    DataType.BOOL: 6,
    DataType.CHAR: 7,
    DataType.VARCHAR: 8,
}
_TYPE_BY_CODE = {code: dtype for dtype, code in _TYPE_CODES.items()}


class UnorderableKey(Exception):

    def __init__(self, value: Any):
        self.value = value
        super().__init__(
            f"{value!r} cannot be a B+ tree key: NaN compares false against "
            "everything, including itself, so it has no place in an ordering."
        )


class KeyTooLong(Exception):
    def __init__(self, size: int):
        self.size = size
        super().__init__(
            f"key of {size} bytes exceeds MAX_KEY_SIZE ({MAX_KEY_SIZE}): a node "
            "page must always fit two entries or splitting cannot terminate"
        )


class KeyTypeMismatch(Exception):
    def __init__(self, value: Any, dtype: DataType):
        super().__init__(
            f"{value!r} ({type(value).__name__}) is not a valid key for a "
            f"{dtype.value} column"
        )


def type_code(dtype: DataType) -> int:
    """The byte the metapage stores for this column type."""
    try:
        return _TYPE_CODES[dtype]
    except KeyError:
        raise ValueError(f"{dtype} cannot be indexed by a B+ tree") from None


def type_from_code(code: int) -> DataType:
    try:
        return _TYPE_BY_CODE[code]
    except KeyError:
        raise ValueError(f"unknown key type code {code} in metapage") from None


def encode(value: Any, dtype: DataType) -> bytes:
    """Order-preserving: encode(a) < encode(b) as bytes iff a < b as values."""
    raw = _encode(value, dtype)
    if len(raw) > MAX_KEY_SIZE:
        raise KeyTooLong(len(raw))
    return raw


def _encode(value: Any, dtype: DataType) -> bytes:
    if dtype == DataType.BOOL:
        # bool first: it subclasses int, so an int branch would swallow it
        if not isinstance(value, bool):
            raise KeyTypeMismatch(value, dtype)
        return b"\x01" if value else b"\x00"

    if dtype in _INT_TYPES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise KeyTypeMismatch(value, dtype)
        if not INT64_MIN <= value <= INT64_MAX:
            raise ValueError(f"{value} does not fit in a 64-bit integer key")
        # flipping the sign bit makes unsigned byte order match signed order
        return struct.pack(">Q", (value & MASK64) ^ SIGN_BIT)

    if dtype in _FLOAT_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise KeyTypeMismatch(value, dtype)
        value = float(value)
        if value != value:
            raise UnorderableKey(value)
        # -0.0 == 0.0 but their bit patterns differ, and a row stored under
        # -0.0 would be invisible to a lookup for 0.0
        if value == 0.0:
            value = 0.0
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        # negatives run backwards as integers, so they get inverted whole
        bits = (~bits & MASK64) if bits & SIGN_BIT else (bits | SIGN_BIT)
        return struct.pack(">Q", bits)

    if dtype in _STR_TYPES:
        if not isinstance(value, str):
            raise KeyTypeMismatch(value, dtype)
        # UTF-8 preserves code point order; no padding, so "ab" < "abc" falls out
        return value.encode("utf-8")

    raise ValueError(f"{dtype} cannot be indexed by a B+ tree")


def decode(raw: bytes, dtype: DataType) -> Any:
    """Inverse of encode(). Diagnostics only: the hot path never decodes."""
    if dtype == DataType.BOOL:
        return raw != b"\x00"

    if dtype in _INT_TYPES:
        unsigned = struct.unpack(">Q", raw)[0] ^ SIGN_BIT
        return unsigned - (1 << 64) if unsigned & SIGN_BIT else unsigned

    if dtype in _FLOAT_TYPES:
        bits = struct.unpack(">Q", raw)[0]
        bits = (bits & ~SIGN_BIT) if bits & SIGN_BIT else (~bits & MASK64)
        return struct.unpack(">d", struct.pack(">Q", bits))[0]

    if dtype in _STR_TYPES:
        return raw.decode("utf-8")

    raise ValueError(f"{dtype} cannot be indexed by a B+ tree")
