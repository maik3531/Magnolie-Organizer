"""Synthetic unknown-note format; no user records or original-file bytes."""
import struct
import pytest

from test_or6_import import native_fixture, rotate, blocks
from magnolie_or6 import read_or6


def note_body(body):
    data = rotate(native_fixture(), True)
    note = next(offset for offset, tag, size in blocks(data) if tag == 0x510)
    count = struct.unpack_from('<I', data, note + 0x28)[0]
    for index in range(count):
        entry = note + 0x34 + index * 8
        fid, length, value = struct.unpack_from('<HHI', data, entry)
        if fid != 8:
            continue
        assert len(body) <= length
        struct.pack_into('<H', data, entry + 2, len(body))
        if len(body) <= 4:
            data[entry + 4:entry + 8] = body.ljust(4, b'\0')
        else:
            data[note + value:note + value + len(body)] = body
        return bytes(rotate(data, False))
    raise AssertionError('Synthetic note field missing')


def test_unknown_note_does_not_block_supported_collections():
    original = read_or6(native_fixture())
    result = read_or6(note_body(b'fixture'))
    assert result['notizen'] == []
    assert result['uebersprungen'] == original['uebersprungen'] + 1
    for key in ('kontakte', 'termine', 'aufgaben', 'jahrestage', 'geburtstage'):
        assert result[key] == original[key]
    assert 'Unsupported entries' in result['bericht']


@pytest.mark.parametrize('body', (b'', b'\0\xff\x02'))
def test_known_empty_note_remains_title_only(body):
    result = read_or6(note_body(body))
    assert len(result['notizen']) == 1
    assert result['notizen'][0]['text'] == ''
    assert result['uebersprungen'] == 0


def test_recognized_but_malformed_rtf_is_not_downgraded_to_unsupported():
    with pytest.raises(ValueError):
        read_or6(note_body(b'{\\rtf1 incomplete'))
