"""Planner schema regression: Row is not an event type or a palette index."""
import struct

import pytest

from test_or6_extensions import fixture
from test_or6_import import rotate, blocks
from magnolie_or6 import read_or6


@pytest.mark.parametrize('row,key_id', [(1, None), (7, 2), (2, 7), (0, 0)])
def test_native_planner_row_and_key_id_remain_distinct(row, key_id):
    raw = fixture('sections-corrected-222.or6')
    original = read_or6(raw)
    data = rotate(raw, True)
    for offset, tag, size in blocks(data):
        if tag != 0x200:
            continue
        for i in range(struct.unpack_from('<I', data, offset + 0x28)[0]):
            entry = offset + 0x34 + i * 8
            field = struct.unpack_from('<H', data, entry)[0]
            if field == 18:
                struct.pack_into('<HHI', data, entry, 18, 2, row)
            elif field == 3 and key_id is not None:
                # Synthetic test mutation only: reuse an optional category slot
                # for the independently named native KeyID field, not a color.
                struct.pack_into('<HHI', data, entry, 19, 2, key_id)
    result = read_or6(bytes(rotate(data, False)))
    planner, = [t for t in result['termine'] if t['titel'] == 'OR6-222 Planned span']
    assert 'event type' not in planner['notiz']
    assert 'Lotus planner Row: ' + str(row) in planner['notiz'].splitlines()
    assert ('Lotus planner KeyID: ' + str(key_id) in planner['notiz'].splitlines()) if key_id is not None else 'KeyID:' not in planner['notiz']
    assert not any(k in planner for k in ('farbe', 'kategorie', 'kategorien'))
    basis, = [t for t in original['termine'] if t['uid'] == planner['uid']]
    assert {k: v for k, v in planner.items() if k != 'notiz'} == {k: v for k, v in basis.items() if k != 'notiz'}
    for collection in ('aufgaben', 'kontakte', 'notizen', 'jahrestage'):
        assert result[collection] == original[collection]
