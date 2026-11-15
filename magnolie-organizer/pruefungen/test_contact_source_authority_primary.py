"""Actual primary authentication is not a native SaveACK or source permission."""
import base64
import hashlib
import json
from pathlib import Path
import threading
from types import MethodType, SimpleNamespace

import pytest

from test_startup_read_failure import native
from magnolie_contact_source_authority import NativeContactSourcePrimaryBook
from magnolie_native_book_json import book_hash


@pytest.mark.parametrize('mode', ['plain', 'encrypted', 'locked', 'load-error', 'missing-key', 'wrong-key-id',
    'wrong-key', 'ciphertext-tampered', 'changed-during-read', 'invalid-json', 'not-object'])
def test_actual_primary_observation_authenticates_disk_not_loaded_memory(native, monkeypatch, mode):
    data = {'kontakte': [{'uid': 'synthetic-original'}], 'fraction': 1.25}
    text = json.dumps(data, ensure_ascii=False, indent=2)
    encrypted = mode not in ('plain', 'invalid-json', 'not-object')
    raw, dek, key_id = text, None, None
    if encrypted:
        raw, dek, key_id, _ = native.daten_huelle_anlegen(text, 'synthetic-only-primary')
    if mode == 'invalid-json': raw = '{broken'
    if mode == 'not-object': raw = '[]'
    native.speichere_text(raw)
    host = SimpleNamespace(_daten_sperre=threading.RLock(), _gesperrt=mode == 'locked',
        _ladefehler='Controlled load error' if mode == 'load-error' else '',
        _daten_dek=dek, _daten_dek_kennung=key_id, _aktuelle_daten={'loaded-memory': 'not authority'})
    observe = MethodType(native.Fenster._kontakt_quellen_hauptdatei_aufnahme, host)
    if mode == 'missing-key': host._daten_dek = None
    if mode == 'wrong-key-id': host._daten_dek_kennung = b'wrong-key-id'
    if mode == 'wrong-key': host._daten_dek = b'x' * 32
    if mode == 'ciphertext-tampered':
        envelope = json.loads(raw)
        ciphertext = bytearray(base64.b64decode(envelope['daten']))
        ciphertext[0] ^= 1
        envelope['daten'] = base64.b64encode(ciphertext).decode('ascii')
        Path(native.daten_datei()).write_text(json.dumps(envelope))
    actual = native._erinnerungsprofil_lesen; calls = []
    def read(*args, **kwargs):
        assert kwargs.get('dauerhaft') is True
        value = actual(*args, **kwargs); calls.append(True)
        if mode == 'changed-during-read' and len(calls) == 2: return value[0], 'a' * 64
        return value
    monkeypatch.setattr(native, '_erinnerungsprofil_lesen', read)
    if mode in ('plain', 'encrypted'):
        observed = observe()
        assert type(observed) is NativeContactSourcePrimaryBook
        assert observed.content_sha256 == book_hash(data)
        assert observed.saved_sha256 == hashlib.sha256(raw.encode()).hexdigest()
        assert observed.binding == str(Path(native.daten_datei()).resolve())
        assert len(calls) == 2 and host._aktuelle_daten == {'loaded-memory': 'not authority'}
        assert not hasattr(host, '_kontakt_quellen_buch'), 'Disk read constructed saved authority'
    else:
        with pytest.raises(Exception): observe()
        if mode in ('locked', 'load-error'): assert calls == []
