"""Existing original-program ordinary task fields must not disappear (#612)."""
import pytest
from test_or6_import import native_fixture, rotate, blocks, CONTRACT
from test_or6_planner import field
from test_startup_read_failure import native
from magnolie_or6 import read_or6, _Document, _string


def test_genuine_ordinary_task_keeps_structured_start_and_due_clocks(native):
    task, = read_or6(native_fixture())['aufgaben']
    expected = {'startDatum': '2026-10-24', 'startZeit': '08:00', 'faellig': '2026-10-24', 'faelligZeit': '18:00'}
    for key, value in expected.items():
        assert task.get(key) == value
    for key, value in CONTRACT['expected']['task'].items():
        assert task[key] == value
    imported, = native.ics_lesen(native.ics_schreiben_aufgaben([task]))['aufgaben']
    for key, value in expected.items():
        assert imported[key] == value
    assert imported['erledigt'] == task['erledigt'] and imported['prio'] == task['prio']


@pytest.mark.parametrize('missing', (7, 8))
def test_absent_native_task_clock_is_not_replaced_with_a_guessed_default(missing):
    raw = native_fixture(); data = rotate(raw, True); doc = _Document(raw)
    reference = next(entry[3] for entry in doc.entries() if entry[0] == 0x300 and _string(entry[1], 9) == CONTRACT['expected']['task']['titel'])
    owner = next(at for at, tag, _ in blocks(data) if tag == 0x300 and doc.reference(at+12) == reference)
    _, length, at = field(data, owner, missing)
    assert length == 8
    data[at:at+8] = b'\x02\x00' + b'\x02' * 6
    task, = read_or6(rotate(data, False))['aufgaben']
    keys = ('startDatum', 'startZeit') if missing == 7 else ('faellig', 'faelligZeit')
    assert all(task.get(key) == '' for key in keys)
    assert task['prio'] == CONTRACT['expected']['task']['prio'] and not task['erledigt']
