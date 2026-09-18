import hashlib
import struct
from typing import Any


class UnhashableKeyType(Exception):
    def __init__(self, value: Any):
        self.value = value
        super().__init__(
            f"{value!r} ({type(value).__name__}) cannot be a hash index key: "
            "float equality is not bit-exact (0.0 vs -0.0, NaN). Use a B+ tree."
        )


def _tagged_bytes(key: Any) -> bytes:
    # the type tag keeps 1 and "1" from colliding
    if isinstance(key, bool):
        return b"b" + (b"\x01" if key else b"\x00")
    if isinstance(key, int):
        return b"i" + struct.pack("<q", key)
    if isinstance(key, str):
        return b"s" + key.encode("utf-8")
    if isinstance(key, bytes):
        return b"s" + key
    raise UnhashableKeyType(key)


def stable_hash(key: Any) -> int:
    return int.from_bytes(
        hashlib.blake2b(_tagged_bytes(key), digest_size=8).digest(), "big"
    )
