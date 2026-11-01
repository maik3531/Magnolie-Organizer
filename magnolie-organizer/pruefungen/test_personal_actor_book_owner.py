"""Native book authority lifetime; no document-tracking or transport side effects."""
import re
import ast
import copy
import hashlib
import json
from types import SimpleNamespace, MethodType
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_personal_actor_store import NativeBookOwnerScope, NativeProducerBookSnapshot


def test_readiness_alone_does_not_replace_actual_native_book_availability():
    owner = NativeBookOwnerScope()
    assert owner.current("profile-a", True) is None
    owner.set_ready(True)
    assert owner.current("profile-a", False) is None
    source = owner.current("profile-a", True)
    assert re.fullmatch(r"[0-9a-f]{64}", source)
    owner.set_ready(True)
    assert owner.current("profile-a", True) == source


def test_lock_regrant_profile_and_restore_changes_never_inherit_a_book_source():
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    first = owner.current("profile-a", True)
    owner.set_ready(False); owner.set_ready(True)
    unlocked = owner.current("profile-a", True)
    assert unlocked and unlocked != first
    other = owner.current("profile-b", True)
    assert other and other != unlocked
    owner.invalidate()
    restored = owner.current("profile-b", True)
    assert restored and restored != other
    assert owner.current("profile-b", False) is None
    assert owner.current("profile-b", True) != restored


def test_native_save_observations_require_actual_lifecycle_and_never_inherit_proofs():
    owner = NativeBookOwnerScope()
    assert owner.record_saved("profile-a", True, "a" * 64) is None
    owner.set_ready(True)
    source = owner.current("profile-a", True)
    assert owner.save_state("profile-a", True) == {"book_source": source, "sequence": 0, "sha256": ""}
    first = owner.record_saved("profile-a", True, "a" * 64)
    second = owner.record_saved("profile-a", True, "a" * 64)
    assert first["sequence"] == 1 and second["sequence"] == 2 and second["book_source"] == source
    second["sequence"] = 900
    assert owner.save_state("profile-a", True)["sequence"] == 2
    for retire in (lambda: owner.set_ready(False), owner.invalidate, lambda: owner.current("profile-b", True)):
        retire(); owner.set_ready(True)
        current = owner.save_state("profile-a", True)
        assert current["book_source"] != source and current["sequence"] == 0 and current["sha256"] == ""
        source = current["book_source"]
        owner.record_saved("profile-a", True, "b" * 64)
    assert owner.record_saved("profile-a", False, "c" * 64) is None


@pytest.mark.parametrize("value", [None, "client-saved", "A" * 64, "a" * 63])
def test_invalid_save_hashes_cannot_enter_native_observations(value):
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    with pytest.raises((TypeError, ValueError)): owner.record_saved("profile-a", True, value)
    assert owner.save_state("profile-a", True)["sequence"] == 0


def producer_fixture():
    data = {'notizen': [{'id': 'synthetic', 'text': 'Grüße 🌸'}], 'personalSync': {}}
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    saved = owner.record_saved('native-producer-profile', True, hashlib.sha256(raw.encode()).hexdigest())
    content = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    recorded = (saved['book_source'], saved['sequence'], content)
    return owner, data, saved, recorded


def test_fresh_structured_producer_snapshot_keeps_raw_writer_and_content_proofs_distinct():
    owner, data, saved, recorded = producer_fixture()
    snapshot = NativeProducerBookSnapshot.capture(lambda: owner.save_state('native-producer-profile', True), lambda: data, lambda: recorded)
    assert snapshot.saved_book == saved and snapshot.book() == data
    assert snapshot.saved_sha256 != snapshot.content_sha256 == recorded[2]
    copied = snapshot.book(); copied['notizen'][0]['text'] = 'Caller edit'
    copied_state = snapshot.saved_book; copied_state['sequence'] = 999
    assert snapshot.book() == data and snapshot.saved_book == saved
    assert 'Grüße' not in repr(snapshot) and saved['book_source'] not in repr(snapshot)
    with pytest.raises(AttributeError): snapshot.text = '{}'


@pytest.mark.parametrize('gate', ('new-save', 'lock', 'restore', 'profile', 'changed-copy', 'changed-recorded'))
def test_producer_capture_denies_native_changes_without_reusing_old_content(gate):
    owner, data, saved, recorded = producer_fixture()
    observed = [recorded]
    def read_data():
        if gate == 'new-save': owner.record_saved('native-producer-profile', True, saved['sha256'])
        if gate == 'lock': owner.set_ready(False)
        if gate == 'restore': owner.invalidate()
        if gate == 'profile': owner.current('another-profile', True)
        if gate == 'changed-recorded': observed[0] = (*recorded[:2], 'b' * 64)
        result = copy.deepcopy(data)
        if gate == 'changed-copy': result['notizen'][0]['text'] = 'Uncommitted native change'
        return result
    assert NativeProducerBookSnapshot.capture(lambda: owner.save_state('native-producer-profile', True), read_data, lambda: observed[0]) is None


@pytest.mark.parametrize('invalid', ('no-save', 'boolean-sequence', 'missing-data', 'wrong-fingerprint', 'wrong-owner', 'array', 'nan'))
def test_producer_capture_requires_exact_native_saved_book_observations(invalid):
    owner, data, saved, recorded = producer_fixture()
    if invalid == 'no-save': saved = None
    if invalid == 'boolean-sequence': saved['sequence'] = True
    if invalid == 'missing-data': data = None
    if invalid == 'wrong-fingerprint': recorded = (*recorded[:2], 'b' * 64)
    if invalid == 'wrong-owner': recorded = ('b' * 64, *recorded[1:])
    if invalid == 'array': data = []
    if invalid == 'nan': data['invalid'] = float('nan')
    assert NativeProducerBookSnapshot.capture(lambda: saved, lambda: data, lambda: recorded) is None


def test_actual_gui_native_snapshot_provider_uses_writer_record_not_a_daemon_cache():
    source = Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer'
    names = {'_telefon_actor_buchnachweis', '_telefon_actor_producer_buch'}
    nodes = [node for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    namespace = {'json': json, 'hashlib': hashlib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    owner, data, saved, recorded = producer_fixture()
    host = SimpleNamespace(_notes_actor_book_owner=owner, _aktuelle_daten=data, _notes_actor_saved_data=recorded,
        _telefon_actor_buchbindung=lambda: ('native-producer-profile', True))
    for name in names: setattr(host, name, MethodType(namespace[name], host))
    snapshot = host._telefon_actor_producer_buch()
    assert snapshot.saved_book == saved and snapshot.book() == data
    host._aktuelle_daten['notizen'][0]['text'] = 'Native unsaved edit'
    assert host._telefon_actor_producer_buch() is None
    assert snapshot.book()['notizen'][0]['text'] == 'Grüße 🌸'
    owner.set_ready(False)
    assert host._telefon_actor_producer_buch() is None
