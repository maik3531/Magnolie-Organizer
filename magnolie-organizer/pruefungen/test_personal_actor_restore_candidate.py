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
    return load_gui_candidates()


@pytest.fixture(scope='module')
def gui_drawing_candidates():
    return load_gui_candidates(drawing=True)


def load_gui_candidates(drawing=False):
    node = os.environ.get('NODE') or shutil.which('node') or shutil.which('nodejs')
    if not node:
        pytest.skip('Existing Node runtime required for actual GUI candidate parity')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, str(root / 'magnolie-organizer-windows/tests/mcp-notes-historical-source-fixture.js'), '--candidate'] + (['--drawing'] if drawing else []),
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


@pytest.mark.parametrize('fault', ['none', 'coordinate', 'boolean-type'])
def test_unrelated_actual_gui_fractional_drawing_is_preserved_exactly_and_never_becomes_wire_content(gui_drawing_candidates, fault):
    for fixture in gui_drawing_candidates:
        original = copy.deepcopy(fixture); candidate = json.loads(fixture['candidate_text'])
        drawing = candidate['customOrganizer']['modules'][0]['drawing']
        assert drawing['strokes'][0]['points'][0][0] == 0.1 and drawing['strokes'][0]['width'] == 1.5
        if fault == 'coordinate': drawing['strokes'][0]['points'][0][0] = 0.1001
        elif fault == 'boolean-type': drawing['autoSize'] = 1
        if fault == 'none':
            proof, book, snapshot = prepare(fixture)
            assert book == fixture['book'] and len(proof.after_content_sha256) == 64
        else:
            with pytest.raises(PermissionError, match='delta_changed'):
                prepare(fixture, json.dumps(candidate, ensure_ascii=False))
        assert fixture == original


def test_local_drawing_comparison_does_not_relax_telephone_canonical_numbers_or_boolean_types():
    import magnolie_personal_sync as personal
    from magnolie_native_book_json import same_book
    assert same_book({'point': 0.1}, {'point': 0.1}) and not same_book({'enabled': False}, {'enabled': 0})
    with pytest.raises(ValueError): personal.canonical({'point': 0.1})
    with pytest.raises(ValueError): same_book({'point': float('nan')}, {'point': float('nan')})
