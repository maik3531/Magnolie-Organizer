"""Operation-local native book projection, never a durable daemon plaintext cache.

Only native owner/writer callbacks may construct and authorize a receiver.
Receiving bytes or a caller's hash alone grants no Actor/target rights. The IPC
adapter must bind callbacks to the exact protected run and GUI-owner lease.
"""
import base64
import binascii
import copy
import hashlib
import json
import re
import secrets
import time

from magnolie_personal_actor_store import NativeProducerBookSnapshot

HEX = re.compile(r'^[a-f0-9]{64}$')
MAX_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 32768


class NativeBookProjection:
    """One bounded transfer with fail-closed cleanup and no implicit resume.

    Identity/source/writer checks run before AND after every append/finish.
    Callback implementations must include registry owner epoch and both TTLs.
    A discarded receiver cannot be reopened with the same token.
    """
    def __init__(self, saved_book, content_sha256, total_bytes, expected_source, *,
                 current_owner, current_source, current_saved_book, clock=time.monotonic):
        if (not isinstance(saved_book, dict) or set(saved_book) != {'book_source', 'sequence', 'sha256'} or
                type(saved_book['sequence']) is not int or saved_book['sequence'] <= 0 or
                any(not isinstance(saved_book[key], str) or HEX.fullmatch(saved_book[key]) is None for key in ('book_source', 'sha256')) or
                not isinstance(content_sha256, str) or HEX.fullmatch(content_sha256) is None or
                not isinstance(expected_source, str) or HEX.fullmatch(expected_source) is None or
                type(total_bytes) is not int or not 2 <= total_bytes <= MAX_BYTES or
                not all(callable(value) for value in (current_owner, current_source, current_saved_book, clock))):
            raise ValueError('invalid_native_book_projection')
        self._saved = copy.deepcopy(saved_book)
        self._content = content_sha256
        self._total = total_bytes
        self._source = expected_source
        self._owner = current_owner
        self._current_source = current_source
        self._current_saved = current_saved_book
        self._clock = clock
        self._deadline = clock() + 30
        self._token = secrets.token_hex(32)
        self._buffer = bytearray()
        self._closed = False
        try:
            self._require(self._token)
        except BaseException:
            self.close()
            raise

    @property
    def token(self):
        return self._token

    @property
    def received_bytes(self):
        return len(self._buffer)

    @property
    def closed(self):
        return self._closed

    def _require(self, token):
        if (self._closed or not isinstance(token, str) or not secrets.compare_digest(token, self._token) or
                self._clock() >= self._deadline or self._owner() is not True or
                self._current_source() != self._source or self._current_saved() != self._saved):
            raise PermissionError('native_book_projection_owner_changed')

    def _authenticate(self, token):
        # A foreign caller must not be able to cancel the legitimate receiver.
        if not isinstance(token, str) or not secrets.compare_digest(token, self._token):
            raise PermissionError('native_book_projection_owner_changed')

    def close(self):
        # Wipe the only mutable transport copy and release it immediately. The
        # caller must also discard a consumed immutable snapshot after Prepare.
        self._buffer[:] = b'\0' * len(self._buffer)
        self._buffer.clear()
        self._closed = True

    def append(self, token, offset, data_base64):
        self._authenticate(token)
        try:
            self._require(token)
            if (type(offset) is not int or offset != len(self._buffer) or not isinstance(data_base64, str) or
                    not 1 <= len(data_base64) <= 4 * ((CHUNK_BYTES + 2) // 3)):
                raise ValueError('invalid_native_book_projection_chunk')
            try:
                raw = base64.b64decode(data_base64, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError('invalid_native_book_projection_chunk') from error
            if not 1 <= len(raw) <= CHUNK_BYTES or len(self._buffer) + len(raw) > self._total:
                raise ValueError('invalid_native_book_projection_chunk')
            self._buffer.extend(raw)
            self._require(token)
            return len(self._buffer)
        except BaseException:
            self.close()
            raise

    def finish(self, token):
        self._authenticate(token)
        try:
            self._require(token)
            if len(self._buffer) != self._total or hashlib.sha256(self._buffer).hexdigest() != self._content:
                raise ValueError('incomplete_native_book_projection')
            text = self._buffer.decode('utf-8', errors='strict')
            def pairs(rows):
                result = {}
                for key, value in rows:
                    if key in result:
                        raise ValueError('duplicate_native_book_key')
                    result[key] = value
                return result
            def constant(_):
                raise ValueError('invalid_native_book_constant')
            book = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
            if not isinstance(book, dict) or json.dumps(book, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) != text:
                raise ValueError('invalid_native_book_projection_content')
            self._require(token)
            return NativeProducerBookSnapshot(self._saved['book_source'], self._saved['sequence'], self._saved['sha256'], self._content, text)
        finally:
            self.close()

    def __repr__(self):
        return f'NativeBookProjection(received_bytes={len(self._buffer)}, closed={self._closed})'
