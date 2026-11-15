"""Status semantics independently toggled in original Lotus UI (#567)."""
import struct

import pytest

from test_or6_import import native_fixture, rotate, blocks
from magnolie_or6 import read_or6


@pytest.mark.parametrize('status,completion,expected', [
    (1, False, False), (2, False, False), (4, True, True),
    (1, True, False), (2, True, False),
])
def test_explicit_native_task_status_takes_precedence_over_completion_date(status, completion, expected):
    # Original-program controls: dated open/future=2; checked complete=4;
    # reopened same native record=2. Existing original-authored overdue=1.
    # Real reexports can retain completion timestamps on open status records.
    raw = native_fixture()
    original = read_or6(raw)
    data = rotate(raw, True)
    for offset, tag, size in blocks(data):
        if tag != 0x300:
            continue
        for index in range(struct.unpack_from('<I', data, offset + 0x28)[0]):
            entry = offset + 0x34 + index * 8
            fid, length, address = struct.unpack_from('<HHI', data, entry)
            if fid == 20:
                assert length == 4
                struct.pack_into('<I', data, entry + 4, status)
            elif fid == 19:
                assert length == 8
                value = struct.pack('<HBBBBBB', 2026, 11, 13, 12, 0, 0, 0) if completion else b'\x02\x00' + b'\x02' * 6
                data[offset + address:offset + address + 8] = value
    result = read_or6(bytes(rotate(data, False)))
    task, = result['aufgaben']
    assert task['erledigt'] is expected
    assert {k: v for k, v in task.items() if k != 'erledigt'} == {k: v for k, v in original['aufgaben'][0].items() if k != 'erledigt'}
    for collection in ('termine', 'kontakte', 'notizen', 'jahrestage'):
        assert result[collection] == original[collection]
