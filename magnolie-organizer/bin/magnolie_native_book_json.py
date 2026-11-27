"""Local saved-book structure only; NOT telephone wire canonicalization.

Unrelated legitimate drawing coordinates may be fractional. Keep number/bool
types distinct and reject nonfinite numbers; never use this for a wire record,
projection hash, clock, admission decision or public protocol signature.
"""
import hashlib
import json


def canonical_book(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def parse_book(raw):
    """Read a local book without weakening the separate telephone JSON codec."""
    def unique_object(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate native book JSON key')
            value[key] = item
        return value

    def nonfinite(_value):
        raise ValueError('non-finite native book number')

    value = json.loads(raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw,
                       object_pairs_hook=unique_object, parse_constant=nonfinite)
    if type(value) is not dict:
        raise ValueError('invalid native book JSON object')
    # Also reject finite-looking JSON tokens that overflow to infinity (1e999).
    canonical_book(value)
    return value


def book_hash(value):
    return hashlib.sha256(canonical_book(value)).hexdigest()


def same_book(left, right):
    return canonical_book(left) == canonical_book(right)
