"""Tool: sha256_hex_hash
Task: Write a function that returns the SHA-256 hash of a string as hex.
Born after 1 attempt(s)."""

import hashlib

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()
