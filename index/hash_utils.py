import hashlib
from typing import Any


def stable_hash(key: Any) -> int:
    """Deterministic, unlike Python's built-in hash()"""
    raw = str(key).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
