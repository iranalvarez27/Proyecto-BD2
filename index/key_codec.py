import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import DataType

# Ceiling on a *codified* key. Derived from requiring that two entries always
# fit in a node page, or a split would divide a page that cannot be divided,
# forever:  2 * (2 + 8 + K) <= PAGE_SIZE - NODE_HEADER_SIZE = 4080.
MAX_KEY_SIZE = 2030

MASK64 = (1 << 64) - 1
SIGN_BIT = 1 << 63

_INT_TYPES = frozenset({DataType.SMALLINT, DataType.INT, DataType.BIGINT})
_FLOAT_TYPES = frozenset({DataType.FLOAT, DataType.DOUBLE})
_STR_TYPES = frozenset({DataType.CHAR, DataType.VARCHAR})

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Stable on-disk codes for the metapage's key_type byte. The index stores the
# column type *once* instead of tagging every key, so these numbers are part of
# the file format: append, never renumber.
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
    """A B+ tree places keys by order, so a value with no total order cannot be
    indexed. Only NaN qualifies -- unlike the hash index, which rejects every
    float because it needs bit-exact equality."""

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
    """Order-preserving serialization: encode(a) < encode(b) as bytes if and
    only if a < b as values. That is what lets the tree compare keys with the
    plain bytes '<' and stay ignorant of types."""
    raw = _encode(value, dtype)
    if len(raw) > MAX_KEY_SIZE:
        raise KeyTooLong(len(raw))
    return raw


def _encode(value: Any, dtype: DataType) -> bytes:
    if dtype == DataType.BOOL:
        # bool first: in Python bool subclasses int, so an unguarded int branch
        # would swallow it (same trap as hash_utils._tagged_bytes)
        if not isinstance(value, bool):
            raise KeyTypeMismatch(value, dtype)
        return b"\x01" if value else b"\x00"

    if dtype in _INT_TYPES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise KeyTypeMismatch(value, dtype)
        if not INT64_MIN <= value <= INT64_MAX:
            raise ValueError(f"{value} does not fit in a 64-bit integer key")
        # In two's complement -1 is 0xFF..FF and +1 is 0x00..01, so compared as
        # unsigned bytes -1 would come out *greater*. Flipping the top bit sends
        # negatives (which start with 1) down to the low half and positives up,
        # and there the unsigned order matches the signed one.
        return struct.pack(">Q", (value & MASK64) ^ SIGN_BIT)

    if dtype in _FLOAT_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise KeyTypeMismatch(value, dtype)
        value = float(value)
        if value != value:
            raise UnorderableKey(value)
        # -0.0 == 0.0 is true in Python but their bit patterns differ, so
        # without this a row stored under -0.0 would be invisible to a lookup
        # for 0.0. Collapsing them keeps encode() consistent with ==.
        if value == 0.0:
            value = 0.0
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        # IEEE-754 is built so two positives compare correctly as integers.
        # Negatives run backwards (bigger magnitude = bigger pattern), so they
        # get inverted whole; positives only need their sign bit raised above
        # every negative.
        bits = (~bits & MASK64) if bits & SIGN_BIT else (bits | SIGN_BIT)
        return struct.pack(">Q", bits)

    if dtype in _STR_TYPES:
        if not isinstance(value, str):
            raise KeyTypeMismatch(value, dtype)
        # UTF-8 preserves code point order, so comparing its bytes compares the
        # strings. No padding and no terminator: Python's bytes already order a
        # prefix below its extensions, which is exactly "ab" < "abc".
        return value.encode("utf-8")

    raise ValueError(f"{dtype} cannot be indexed by a B+ tree")


def decode(raw: bytes, dtype: DataType) -> Any:
    """Inverse of encode(). Only for diagnostics and error messages -- the hot
    path compares encoded bytes and never decodes."""
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
