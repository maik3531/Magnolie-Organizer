"""Local saved-book structure only; NOT telephone wire canonicalization.

Unrelated legitimate drawing coordinates may be fractional. Keep number/bool
types distinct and reject nonfinite numbers; never use this for a wire record,
projection hash, clock, admission decision or public protocol signature.
"""
import hashlib
import json


def canonical_book(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def book_hash(value):
    return hashlib.sha256(canonical_book(value)).hexdigest()


def same_book(left, right):
    return canonical_book(left) == canonical_book(right)
