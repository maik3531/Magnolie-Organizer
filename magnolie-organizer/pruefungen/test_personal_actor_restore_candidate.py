"""Actual GUI candidate text must match the exact independently rebuilt delta."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_restore_candidate import NativeHistoricalRestoreCandidateProof
from test_personal_actor_producer import native


@pytest.fixture(scope='module')
def gui_candidates():
    node = os.environ.get('NODE') or shutil.which('node') or shutil.which('nodejs')
    if not node:
        pytest.skip('Existing Node runtime required for actual GUI candidate parity')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, str(root / 'magnolie-organizer-windows/tests/mcp-notes-historical-source-fixture.js'), '--candidate'],
        check=True, capture_output=True, text=True, timeout=40)
    fixtures = json.loads(result.stdout); assert len(fixtures) == 8
    return fixtures


def prepare(fixture, candidate=None, choices=None, change=None):
    book = copy.deepcopy(fixture['book']); snapshot = native(book)[2]
    state = {'source': 'a' * 64, 'snapshot': snapshot, 'owner': True,
        'scope': scope.create(fixture['members']['notes'], fixture['members']['tasks'])}
    if change:
        change(state)
    proof = NativeHistoricalRestoreCandidateProof.prepare(fixture['peer'], fixture['run'], fixture['format'], [fixture['target']],
        [fixture['choice']] if choices is None else choices, fixture['candidate_text'] if candidate is None else candidate,
        current_owner=lambda: state['owner'], current_source=lambda: state['source'], current_snapshot=lambda: state['snapshot'], current_scope=lambda: state['scope'])
    return proof, book, snapshot


def test_independent_native_delta_accepts_actual_gui_candidates_and_retains_only_metadata(gui_candidates):
    for fixture in gui_candidates:
        proof, book, snapshot = prepare(fixture)
        assert book == fixture['book'] and proof.before_sequence == snapshot.sequence and proof.before_sha256 == snapshot.saved_sha256
        assert proof.after_sha256 == hashlib.sha256(fixture['candidate_text'].encode()).hexdigest()
        candidate = json.loads(fixture['candidate_text'])
        assert proof.after_content_sha256 == hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert proof.before_scope[1] == 1 and len(proof.before_scope[2]) == 64
        assert proof.before_live == (tuple(fixture['members']['notes']), tuple(fixture['members']['tasks']))
        assert fixture['target']['id'] in proof.after_live[0 if fixture['target']['kind'] == 'note' else 1]
        assert all(not isinstance(value, (dict, list)) for value in vars(proof).values())
        assert 'Protected' not in repr(proof) and not hasattr(proof, 'book')


@pytest.mark.parametrize('fault', ['content', 'counter', 'clock', 'extra-entity', 'unrelated-config', 'trash-collateral', 'alias', 'boolean-type', 'missing-choice', 'implicit-confirm', 'delete-choice', 'clock-choice', 'duplicate-json'])
def test_a_claimed_afterhash_cannot_replace_exact_native_delta_and_explicit_choices(gui_candidates, fault):
    for fixture in gui_candidates:
        candidate = json.loads(fixture['candidate_text']); choices = [copy.deepcopy(fixture['choice'])]
        key = fixture['target']['kind'] + '\0' + fixture['target']['id']
        if fault == 'content': candidate['notizen' if fixture['target']['kind'] == 'note' else 'aufgaben'][-1]['titel'] = 'Substituted content'
        elif fault == 'counter': candidate['personalSync']['counter'] += 1
        elif fault == 'clock': candidate['personalSync']['entities'][key]['clock'][0]['counter'] += 1
        elif fault == 'extra-entity': candidate['personalSync']['entities']['note\0foreign'] = {'state': 'live'}
        elif fault == 'unrelated-config': candidate['einstellungen']['historical_synthetic_change'] = True
        elif fault == 'trash-collateral': candidate['papierkorb'] = copy.deepcopy(fixture['book']['papierkorb'])
        elif fault == 'alias': candidate['personalSync']['note_aliases']['foreign-id'] = 'another-id'
        elif fault == 'boolean-type': candidate['personalSync']['entities'][key]['acknowledged_by_peer'] = 0
        elif fault == 'missing-choice': choices = []
        elif fault == 'implicit-confirm': choices[0]['confirm_conflict'] = False
        elif fault == 'delete-choice': choices[0]['decision'] = 'delete'
        elif fault == 'clock-choice': choices[0]['expected_clock'][0]['counter'] += 1
        text = json.dumps(candidate, ensure_ascii=False)
        if fault == 'duplicate-json': text = text[:-1] + ',"personalSync":' + json.dumps(candidate['personalSync']) + '}'
        before = copy.deepcopy(fixture)
        with pytest.raises((PermissionError, ValueError)):
            prepare(fixture, text, choices)
        assert fixture == before
