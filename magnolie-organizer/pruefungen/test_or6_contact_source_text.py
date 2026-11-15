"""Public synthetic contact source fields; no personal fixture bytes."""
import struct
from test_or6_import import native_fixture, rotate, blocks
from magnolie_or6 import read_or6


def contact_source_text():
    data = rotate(native_fixture(), True)
    alias = 'FixtureAlias'.encode('utf-16le')
    extension = '42\0\0X\0'.encode('utf-16le')
    for offset, tag, size in blocks(data):
        if tag != 0x400:
            continue
        count = struct.unpack_from('<I', data, offset + 0x28)[0]
        entries = {struct.unpack_from('<H', data, offset + 0x34 + i * 8)[0]: offset + 0x34 + i * 8 for i in range(count)}
        note = entries.get(39)
        if note is None or struct.unpack_from('<H', data, note + 2)[0] < len(alias):
            continue
        destination = entries.get(40, note)
        address = struct.unpack_from('<I', data, note + 4)[0]
        if destination != note:
            struct.pack_into('<HI', data, note + 2, 0, 0)
        struct.pack_into('<HHI', data, destination, 40, len(alias), address)
        data[offset + address:offset + address + len(alias)] = alias
        entry = entries[34]
        assert struct.unpack_from('<H', data, entry + 2)[0] >= len(extension)
        address = struct.unpack_from('<I', data, entry + 4)[0]
        struct.pack_into('<H', data, entry + 2, len(extension))
        data[offset + address:offset + address + len(extension)] = extension
        return bytes(rotate(data, False))
    raise AssertionError('Synthetic owned contact fields missing')


def test_extra_source_text_survives_without_guessing_phone_semantics():
    original = read_or6(native_fixture())
    result = read_or6(contact_source_text())
    contact, = result['kontakte']
    assert 'Mail merge name: FixtureAlias' in contact['notiz']
    assert 'Lotus Extn slot 1: 42' in contact['notiz']
    assert 'Lotus Extn slot 3: X' in contact['notiz']
    assert 'Lotus Extn slot 2:' not in contact['notiz']
    for key in ('uid', 'telefone', 'telefon', 'emails', 'anschriften'):
        assert contact[key] == original['kontakte'][0][key]
    for key in ('termine', 'aufgaben', 'notizen', 'jahrestage', 'uebersprungen'):
        assert result[key] == original[key]
