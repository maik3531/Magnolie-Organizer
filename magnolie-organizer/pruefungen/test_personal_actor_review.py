"""Private native review binding from shared, independently chosen inputs."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))
import magnolie_personal_actor as actor
import magnolie_personal_sync as personal
import magnolie_content_scope as scope

CASES = json.loads((ROOT / 'contracts/notes-actor-deletion-review.json').read_text())['cases']
SCOPE_CASES = json.loads((ROOT / 'contracts/notes-actor-completion-scope.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_same_native_review_vectors(case):
    before = copy.deepcopy(case)
    if case['valid']:
        value = actor.deletion_review(case['run_id'], case['plan'], case['native_intents'])
        assert set(value) == {'choices', 'intents'}
        assert actor.deletion_review(case['run_id'], value, case['native_intents']) == value
        value['choices'].clear(); value['intents'].clear()
    else:
        with pytest.raises(ValueError):
            actor.deletion_review(case['run_id'], case['plan'], case['native_intents'])
    assert case == before


@pytest.mark.parametrize('name', ('exact-delete', 'prior-verified-incoming-decision'))
def test_native_intent_format_is_an_integer_not_a_boolean(name):
    intent = copy.deepcopy(next(case for case in CASES if case['name'] == name)['native_intents'][0])
    personal.validate_body(intent['kind'], intent['body'])
    intent['body']['format'] = True
    with pytest.raises(ValueError): personal.validate_body(intent['kind'], intent['body'])


def test_notes_and_desktops_share_identical_completion_inputs():
    assert (ROOT / 'contracts/notes-actor-completion-scope.json').read_bytes() == (
        ROOT / 'magnolie-notes/app/src/test/resources/notes-actor-completion-scope.json').read_bytes()


@pytest.mark.parametrize('case', SCOPE_CASES, ids=lambda case: case['name'])
def test_same_exact_completion_scope_vectors(case):
    before = copy.deepcopy(case)
    args = (case['run_id'], case['before'], case['native_targets'], case['decisions'])
    if case['valid']:
        members = actor.completion_members(*args)
        assert members == case['actual_after']['members']
        reference = actor.require_completion_scope(*args, case['actual_after'])
        assert reference == scope.reference(case['actual_after'])
        members['notes'].append('caller-edit'); reference['scope_hash'] = 'caller-edit'
    else:
        with pytest.raises(ValueError): actor.require_completion_scope(*args, case['actual_after'])
    assert case == before
