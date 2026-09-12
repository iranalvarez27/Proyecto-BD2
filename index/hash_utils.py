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
    """Serialize with a type tag, so that 1 and "1" do not collide."""
    # bool first: in Python bool subclasses int, so isinstance(True, int) is True
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
    """Not hash(): that one is randomized per process for str/bytes, so a
    persisted index would lose its keys on restart."""
    return int.from_bytes(
        hashlib.blake2b(_tagged_bytes(key), digest_size=8).digest(), "big"
    )
