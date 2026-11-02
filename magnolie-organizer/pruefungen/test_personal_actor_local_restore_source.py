"""Actual shared-GUI local source projection -> native metadata-only proof."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_restore_source import NativeHistoricalRestoreSourceObservation
from test_personal_actor_producer import native


@pytest.fixture(scope='module')
def gui_sources():
    node = os.environ.get('NODE') or shutil.which('node') or shutil.which('nodejs')
    if not node:
        pytest.skip('Existing Node runtime required for actual shared-GUI source parity')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, str(root / 'magnolie-organizer-windows/tests/mcp-notes-historical-source-fixture.js')],
        check=True, capture_output=True, text=True, timeout=40)
    fixtures = json.loads(result.stdout)
    assert len(fixtures) == 8
    return fixtures


def observed(fixture, changed=None):
    fixture = copy.deepcopy(fixture); book = fixture['book']
    if changed:
        changed(book, fixture['target'])
    snapshot = native(book)[2]
    state = {'source': 'a' * 64, 'snapshot': snapshot, 'owner': True,
        'scope': scope.create(fixture['members']['notes'], fixture['members']['tasks'])}
    observer = NativeHistoricalRestoreSourceObservation(fixture['peer'], fixture['run'], fixture['format'],
        current_owner=lambda: state['owner'], current_source=lambda: state['source'],
        current_snapshot=lambda: state['snapshot'], current_scope=lambda: state['scope'])
    return observer, fixture, state


def test_real_gui_note_task_and_format_sources_match_native_projection_without_content_or_action_rights(gui_sources):
    for fixture in gui_sources:
        observer, value, state = observed(fixture); before = copy.deepcopy(value['book'])
        result = observer.observe(value['run'], value['target'])
        assert result['local_state'] == 'deleted' and result['metadata_matches'] is True
        assert result['action_authorized'] is False and result['requires_conflict_choice'] is True
        proof = result['local_restore_source']
        assert len(proof['sha256']) == 64 and proof['trash_id'] == value['book']['papierkorb'][0]['id']
        assert 'Synthetic' not in json.dumps(result) and 'Protected' not in json.dumps(result) and 'data:' not in json.dumps(result)
        assert value['book'] == before and state['scope']['members'] == fixture['members']


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign', 'changed', 'hash', 'clock', 'live', 'child', 'scope', 'save', 'source', 'owner'])
def test_local_restore_sources_are_exact_and_stale_or_remote_substitutes_never_become_evidence(gui_sources, fault):
    for fixture in gui_sources:
        def change(book, target):
            piece = book['papierkorb'][0]
            if fault == 'missing': book['papierkorb'] = []
            elif fault == 'duplicate': book['papierkorb'].append(copy.deepcopy(piece))
            elif fault == 'foreign': piece['eintrag']['baumQuelle' if target['kind'] == 'note' else 'delegiertAn'] = 'foreign'
            elif fault == 'changed': piece['eintrag']['titel'] = 'Changed source'
            elif fault == 'hash': target['prior_hash'] = 'f' * 64
            elif fault == 'clock': target['clock'][0]['counter'] += 1
            elif fault == 'live': book['notizen' if target['kind'] == 'note' else 'aufgaben'].append(copy.deepcopy(piece['eintrag']))
            elif fault == 'child' and target['kind'] == 'note':
                book['personalSync']['entities']['attachment\0' + target['id'] + '\0pending-child'] = {'state': 'deleted'}
        if fault == 'child' and fixture['target']['kind'] != 'note':
            continue
        observer, value, state = observed(fixture, change)
        if fault == 'scope': state['scope'] = scope.create(['foreign'], [])
        elif fault == 'save': state['snapshot'] = native(dict(value['book'], synthetic_independent_change=True))[2]
        elif fault == 'source': state['source'] = 'b' * 64
        elif fault == 'owner': state['owner'] = False
        before = copy.deepcopy(value['book'])
        with pytest.raises((PermissionError, ValueError)):
            observer.observe(value['run'], value['target'])
        assert value['book'] == before
