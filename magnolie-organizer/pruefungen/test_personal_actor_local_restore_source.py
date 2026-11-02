"""Actual shared-GUI local source projection -> native metadata-only proof."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sqlite3

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_restore_source import NativeHistoricalRestoreSourceObservation
from test_personal_actor_producer import native
from test_personal_actor_target_observer_runtime import observation_runtime
from test_personal_actor_transport import frame
import magnolie_personal_actor as actor
import uuid


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


@pytest.mark.parametrize('fault', ['none', 'missing', 'changed', 'duplicate'])
def test_actual_authenticated_native_restore_review_binds_choices_to_local_sources_without_queue_save_or_ack(tmp_path, monkeypatch, gui_sources, fault):
    for index, raw in enumerate(gui_sources):
        fixture = copy.deepcopy(raw)
        if fault == 'missing': fixture['book']['papierkorb'] = []
        elif fault == 'changed': fixture['book']['papierkorb'][0]['eintrag']['titel'] = 'Changed source'
        elif fault == 'duplicate': fixture['book']['papierkorb'].append(copy.deepcopy(fixture['book']['papierkorb'][0]))
        service, peer, channel, manifest, book, target, owner, read, snapshot, registry, handle = observation_runtime(
            tmp_path / str(index), monkeypatch, fixture['target']['kind'], source_fixture=fixture)
        service.start_personal_actor(registry, handle)
        request = {'format': fixture['format'], 'run_id': handle.actor_id, 'trigger': 'manual', 'modules': ['notes', 'tasks']}
        service._payload(peer, channel, actor.wire_message(frame('personal_sync.request', request), handle.actor_id))
        body = {'format': 1, 'run_id': handle.actor_id, 'proposal_batch_id': str(uuid.uuid4()), 'sequence': 0, 'last': True,
            'proposals': [dict(target, deleted_ms=2, label='Synthetic historical target')]}
        wire = actor.wire_message(frame('personal_sync.deletion_proposals', body), handle.actor_id)
        service._payload(peer, channel, wire); channel.sent.clear()
        view = service.review_personal_actor_incoming_targets(registry, handle)
        choices = [{'proposal_id': target['proposal_id'], 'decision': 'restore', 'expected_clock': target['clock'], 'confirm_conflict': True}]
        def durable_queue():
            with sqlite3.connect(service.store.database_path) as db:
                return db.execute('SELECT message_id,kind,payload FROM outbox WHERE peer_id=? ORDER BY message_id', (peer['device_id'],)).fetchall()
        before = registry.status(handle); saved = read(); retained = copy.deepcopy(book); queue = durable_queue()
        if fault == 'none':
            result = service.review_personal_actor_historical_restore(registry, handle, view['revision'], choices)
            assert result['action_authorized'] is False and len(result['restore_source_revision']) == 64
            assert result['local_restore_sources'][0]['target'] == target
            assert 'Protected synthetic source' not in json.dumps(result) and 'data:' not in json.dumps(result)
        else:
            with pytest.raises((PermissionError, ValueError)):
                service.review_personal_actor_historical_restore(registry, handle, view['revision'], choices)
        assert registry.status(handle) == before and read() == saved and book == retained
        assert durable_queue() == queue and not channel.sent
