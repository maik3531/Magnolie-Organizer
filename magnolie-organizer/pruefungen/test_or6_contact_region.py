"""Synthetic native State slots, including an empty middle position."""
import struct
from test_or6_contact_source_text import contact_source_text, rotate, blocks
from magnolie_or6 import read_or6


def contact_regions():
    data = rotate(contact_source_text(), True)
    text = 'BE\0\0HE\0'.encode('utf-16le')
    for offset, tag, size in blocks(data):
        if tag != 0x400:
            continue
        count = struct.unpack_from('<I', data, offset + 0x28)[0]
        entries = {struct.unpack_from('<H', data, offset + 0x34 + i * 8)[0]: offset + 0x34 + i * 8 for i in range(count)}
        spare = entries.get(40)
        if spare is None or struct.unpack_from('<H', data, spare + 2)[0] < len(text):
            continue
        address = struct.unpack_from('<I', data, spare + 4)[0]
        struct.pack_into('<HHI', data, entries[30], 30, len(text), address)
        struct.pack_into('<HI', data, spare + 2, 0, 0)
        data[offset + address:offset + address + len(text)] = text
        return bytes(rotate(data, False))
    raise AssertionError('Synthetic state slots missing')


def test_state_slots_remain_structured_without_promoting_an_empty_home_slot():
    original = read_or6(contact_source_text())['kontakte'][0]
    contact, = read_or6(contact_regions())['kontakte']
    assert [a.get('region') for a in contact['anschriften']] == ['BE', 'HE']
    assert contact['anschriften'][0]['typen'] == ['WORK']
    assert contact['anschriften'][1]['typen'] == []
    for key in ('strasse', 'plz', 'ort', 'land'):
        assert contact['anschriften'][0][key] == original['anschriften'][0][key]
    assert contact['telefone'] == original['telefone'] and contact['uid'] == original['uid']
    assert 'State: BE; HE' in contact['notiz']
