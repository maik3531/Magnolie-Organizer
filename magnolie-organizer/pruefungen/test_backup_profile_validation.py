"""Legacy backup plausibility before restore; isolated actual reader/handlers."""
import json
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native


@pytest.mark.parametrize('data', (
    {}, {'unrelated': True}, {'notizen': 'not a list'}, {'kontakte': {}},
    {'einstellungen': []}, {'notizen': [], 'aufgaben': True}, {'notizen': None},
    {'customOrganizer': []}, {'notizen': [], 'gesundheit': 'invalid'},
))
def test_unrelated_or_wrong_shape_backup_is_rejected(native, tmp_path, data):
    path = tmp_path / 'bad.json'; text = json.dumps(data); path.write_text(text)
    result = native.sicherung_lesen(str(path))
    assert not result['ok']
    assert path.read_text() == text


@pytest.mark.parametrize('data', (
    {'notizen': []}, {'notizen': [{'id': 'n', 'text': 'Synthetic note'}]},
    {'einstellungen': {}}, {'gesundheit': {'future': [1]}},
    {'notizen': None, 'termine': []}, {'kontakte': [], 'future': {'keep': [1, 2]}},
    {'version': 1, 'aufgaben': [{'titel': 'Legacy task'}]},
))
def test_valid_empty_or_legacy_partial_backup_preserves_unknown_values(native, tmp_path, data):
    path = tmp_path / 'legacy.json'; path.write_text(json.dumps(data))
    result = native.sicherung_lesen(str(path))
    assert result['ok'] and result['daten'] == data
    assert native.sicherung_lesen(str(path), expected_revision=result['revision'])['ok']
    path.write_text(json.dumps({'unrelated': True}))
    changed = native.sicherung_lesen(str(path), expected_revision=result['revision'])
    assert not changed['ok'] and changed['code'] == 'conflict'


@pytest.mark.parametrize('valid', (False, True))
def test_encrypted_legacy_backup_uses_same_shape_guard(native, tmp_path, valid):
    data = {'notizen': []} if valid else {'notizen': 'not a list'}
    path = tmp_path / 'encrypted.json'; path.write_text(native.verschluesseln(json.dumps(data), 'synthetic-backup-only'))
    assert native.sicherung_lesen(str(path))['brauchtKennwort']
    result = native.sicherung_lesen(str(path), 'synthetic-backup-only')
    assert result['ok'] is valid
    if valid:
        assert result['daten'] == data


def test_actual_preview_and_restore_reject_before_lock_snapshot_or_write(native, tmp_path):
    path = tmp_path / 'unrelated.json'; path.write_text('{"unrelated":true}')
    answers = []
    class NoMutation:
        def acquire(self):
            raise AssertionError('Invalid backup reached the restore mutation lock')
    window = SimpleNamespace(_kennwort='', _daten_sperre=NoMutation(),
                             antwort=lambda name, payload: answers.append((name, payload)))
    native.Fenster._sicherung_pruefen(window, str(path), request_id='preview')
    assert answers[-1][0] == 'App.sicherungAusgewaehlt' and not answers[-1][1]['ok']
    native.Fenster._sicherung_wiederherstellen(window, str(path), request_id='restore')
    assert answers[-1][0] == 'App.sicherungWiederhergestellt' and not answers[-1][1]['ok']
    assert answers[-1][1]['committed'] is False and window._operation_laeuft is False
