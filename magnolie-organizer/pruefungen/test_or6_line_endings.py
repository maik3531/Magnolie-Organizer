"""Shared synthetic descriptions, never private user data."""
import struct
import pytest
from test_or6_import import native_fixture, rotate, blocks
from test_or6_extensions import fixture
from magnolie_or6 import read_or6


def description(raw, kind, value):
    data = rotate(raw, True)
    text = value.encode('utf-16le')
    for offset, tag, size in blocks(data):
        if tag != kind:
            continue
        count = struct.unpack_from('<I', data, offset + 0x28)[0]
        entries = [offset + 0x34 + i * 8 for i in range(count)]
        selected = next((e for e in entries if struct.unpack_from('<H', data, e)[0] == 9 and struct.unpack_from('<H', data, e + 2)[0] >= len(text)), None)
        if selected is None:
            continue
        address = struct.unpack_from('<I', data, selected + 4)[0]
        struct.pack_into('<H', data, selected + 2, len(text))
        data[offset + address:offset + address + len(text)] = text
        for entry in entries:
            if struct.unpack_from('<H', data, entry)[0] == 16:
                struct.pack_into('<H', data, entry + 2, 0)
                data[entry + 4:entry + 8] = bytes(4)
        return bytes(rotate(data, False))
    raise AssertionError('Synthetic description missing')


@pytest.mark.parametrize('ending', ('\r\n', '\n', '\r'))
@pytest.mark.parametrize('annual', (False, True))
def test_description_lines_preserve_uid_and_unrelated_records(ending, annual):
    raw = fixture('sections-corrected-222.or6') if annual else native_fixture()
    original = read_or6(raw)
    result = read_or6(description(raw, 0x600 if annual else 0x100, ending.join(('A', 'B', 'C'))))
    collection = 'jahrestage' if annual else 'termine'
    entry, = result[collection]
    assert entry['name' if annual else 'titel'] == 'A'
    assert entry['notiz'] == 'B\nC'
    assert entry['uid'] == original[collection][0]['uid']
    assert result['kontakte'] == original['kontakte']
    assert result['notizen'] == original['notizen']
