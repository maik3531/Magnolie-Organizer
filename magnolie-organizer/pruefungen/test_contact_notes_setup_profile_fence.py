"""#640 actual IPC profile fence. Original transaction bodies remain separate proofs."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from test_contact_notes_setup_host import host_case, native


def packet(command, request='first'):
    return dict(cmd=command, requestId=request, snapshotId='synthetic-snapshot', bereiche=['contacts'],
        modus='replace', pfad='/synthetic-not-opened/fixture.magnolie', kennwort='synthetic-only',
        neu='synthetic-new-only', alt='synthetic-old-only', sicherungen=False, sicherungsordner='',
        expectedRevision='synthetic-file-revision', expectedBookRevision='synthetic-book-revision')


def routes(s):
    calls = []
    def record(name):
        def invoke(*args, **kwargs):
            assert s.host is None or s.host.quiesced.is_set()
            assert not s.h.probe._daten_sperre._is_owned() and not s.h.probe._baum_sperre._is_owned()
            assert not getattr(s.h.probe, '_speicher_laeuft', False) and not s.h.probe._speicher_auftraege.unfinished_tasks
            calls.append((name, args, kwargs))
        return invoke
    for name in ('_journal_wiederherstellen', '_sicherung_wiederherstellen', '_gesamtarchiv_importieren',
            '_kennwort_setzen', '_kennwort_entfernen', '_entsperren'):
        setattr(s.h.probe, name, record(name))
    return calls


def until(s, condition):
    deadline = time.monotonic() + 8
    while not condition():
        assert time.monotonic() < deadline, 'Owned profile fence did not settle'
        s.pump(); time.sleep(.001)


def waiting_host(s):
    s.mode = 'cancel-wait'; s.start(); s.ready()
    assert s.arrived.wait(5)


@pytest.mark.parametrize('command', ['bereit', 'entsperren', 'kennwort_setzen', 'kennwort_entfernen',
    'journal_wiederherstellen', 'sicherung_wiederherstellen', 'gesamtarchiv_importieren'])
def test_actual_profile_command_waits_for_owned_setup_and_replays_original_once(host_case, monkeypatch, command):
    s = host_case; calls = routes(s)
    dispatch = s.native.Fenster.bei_nachricht
    waiting_host(s)
    original = packet(command); raw = json.dumps(original)
    dispatch(s.h.probe, raw)
    pending = s.h.probe._notes_original_setup_profile_fence
    assert pending['raw'] == raw and not calls
    callback = list(s.timers.values())[-1][1]
    with pytest.raises(PermissionError): s.start()
    if command == 'bereit':
        # Avoid running unrelated startup services. Verify the exact ordinary
        # ready envelope is re-dispatched once; that route's body is unchanged.
        monkeypatch.setattr(s.native.Fenster, 'bei_nachricht', lambda self, raw: calls.append(('ready-envelope', json.loads(raw), {})))
    until(s, lambda: len(calls) == 1)
    assert s.host.quiesced.is_set() and not s.h.probe._notes_original_setup_profile_fence
    assert pending == {} and callback() is False and len(calls) == 1
    assert not s.notices and not s.h.store.has_desired_consent()
    name, args, kwargs = calls[0]
    if command == 'bereit': assert args == original
    elif command == 'entsperren': assert args == ('synthetic-only',)
    elif command.startswith('kennwort_'):
        assert kwargs == dict(request_id='first', expected_revision='synthetic-file-revision', expected_book_revision='synthetic-book-revision')
    else:
        assert 'first' in args and args[-1] == 'synthetic-file-revision'


def test_profile_fence_keeps_saves_dispatchable_and_drains_real_writer_before_restore(host_case, monkeypatch):
    s = host_case; calls = routes(s); waiting_host(s)
    raw = json.dumps(packet('journal_wiederherstellen'))
    s.native.Fenster.bei_nachricht(s.h.probe, raw)
    text = json.dumps(s.h.probe._aktuelle_daten, ensure_ascii=False)
    for identifier in (9001, 9002):
        s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(dict(cmd='speichern', id=identifier, text=text)))
    assert s.h.probe._speicher_auftraege.unfinished_tasks == 2
    until(s, lambda: s.host.quiesced.is_set())
    for _ in range(3): s.pump()
    assert not calls and s.h.probe._notes_original_setup_profile_fence
    monkeypatch.setattr(s.native, 'erinnerungsdaten_schreiben', lambda **_: True)
    s.h.probe._speicher_auftraege.put(None)
    worker = threading.Thread(target=s.native.Fenster._speicher_lauf, args=(s.h.probe,))
    worker.start(); worker.join(15); assert not worker.is_alive()
    assert [value['id'] for callback, value in s.h.replies if callback == 'App.gespeichert' and value.get('id') in (9001, 9002)] == [9001, 9002]
    until(s, lambda: len(calls) == 1)
    assert not s.h.probe._notes_original_setup_profile_fence


def test_duplicate_profile_intent_is_busy_without_replacing_or_replaying_first(host_case):
    s = host_case; calls = routes(s); waiting_host(s)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('sicherung_wiederherstellen')))
    pending = s.h.probe._notes_original_setup_profile_fence
    version = s.h.probe._notes_original_setup_version
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('kennwort_setzen', 'second')))
    assert s.h.probe._notes_original_setup_profile_fence is pending and s.h.probe._notes_original_setup_version == version
    callback, reply = s.h.replies[-1]
    assert callback == 'App.kennwortStand' and reply['requestId'] == 'second' and reply['code'] == 'busy' and not reply['committed']
    until(s, lambda: len(calls) == 1)
    assert calls[0][0] == '_sicherung_wiederherstellen' and not s.h.store.has_desired_consent()


def test_lost_ui_trust_is_rechecked_before_original_profile_route(host_case):
    s = host_case; calls = routes(s); waiting_host(s)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('gesamtarchiv_importieren')))
    s.h.probe._organizer_vertraut = lambda: False
    until(s, lambda: s.h.probe._notes_original_setup_profile_fence is None)
    assert s.host.quiesced.is_set() and not calls and not s.h.store.has_desired_consent()


def test_failed_defer_scheduler_reports_failure_without_falling_through_to_restore(host_case, monkeypatch):
    s = host_case; calls = routes(s); waiting_host(s)
    def unavailable(*args): raise RuntimeError('synthetic unavailable profile timer')
    monkeypatch.setattr(s.native.GLib, 'timeout_add', unavailable)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('journal_wiederherstellen')))
    assert s.h.probe._notes_original_setup_profile_fence is None and not calls
    callback, reply = s.h.replies[-1]
    assert callback == 'App.journalWiederhergestellt' and reply['code'] == 'native_operation_failed' and not reply['committed']
    s.finish(); assert not calls


def test_exception_after_original_route_entry_reports_unknown_not_a_false_rollback(host_case):
    s = host_case; entered = []
    def original_body(*args):
        entered.append(args)
        raise RuntimeError('synthetic exception after transaction entry')
    s.h.probe._journal_wiederherstellen = original_body
    waiting_host(s)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('journal_wiederherstellen')))
    pending = s.h.probe._notes_original_setup_profile_fence
    continuation = list(s.timers.values())[-1][1]
    until(s, lambda: s.h.probe._notes_original_setup_profile_fence is None)
    callback, result = s.h.replies[-1]
    assert len(entered) == 1 and pending == {} and continuation() is False
    assert callback == 'App.journalWiederhergestellt' and result['code'] == 'native_outcome_unknown' and result['outcomeUnknown'] is True
    assert 'committed' not in result and not result['ok'] and not s.h.store.has_desired_consent()


def test_final_close_discards_owned_deferred_profile_payload_instead_of_replaying_it(host_case):
    s = host_case; calls = routes(s); s.mode = 'cancel-active-probe'; s.start(); s.ready()
    assert s.arrived.wait(5)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('kennwort_entfernen')))
    pending = s.h.probe._notes_original_setup_profile_fence
    assert s.native.Fenster._beenden_endgueltig(s.h.probe) is True and not s.destroyed
    s.release.set()
    until(s, lambda: s.host.quiesced.is_set() and s.h.probe._notes_original_setup_profile_fence is None)
    assert pending == {} and not calls
    assert s.native.Fenster._beenden_endgueltig(s.h.probe) is False and s.destroyed == [True]


def test_no_host_keeps_existing_profile_dispatch_unchanged(host_case):
    s = host_case; calls = routes(s)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('journal_wiederherstellen')))
    assert len(calls) == 1 and not getattr(s.h.probe, '_notes_original_setup_profile_fence', None) and not s.calls


@pytest.mark.parametrize('field', ['_notes_original_setup_host', '_notes_original_setup_profile_fence'])
def test_unknown_foreign_runtime_owner_is_not_stopped_replaced_or_treated_as_joined(host_case, field):
    s = host_case; calls = routes(s); stopped = []
    foreign = SimpleNamespace(stop=lambda: stopped.append(True))
    setattr(s.h.probe, field, foreign)
    s.native.Fenster.bei_nachricht(s.h.probe, json.dumps(packet('journal_wiederherstellen')))
    assert getattr(s.h.probe, field) is foreign and not stopped and not calls and not s.timers
    callback, reply = s.h.replies[-1]
    assert callback == 'App.journalWiederhergestellt' and reply['code'] == 'busy' and not reply['committed']


@pytest.mark.parametrize('field', ['_operation_laeuft', '_sync_laeuft', '_notes_original_setup_exit_pending'])
def test_setup_cannot_start_inside_existing_native_profile_or_sync_operation(host_case, field):
    s = host_case; setattr(s.h.probe, field, True)
    with pytest.raises(PermissionError): s.start()
    assert s.host is None and not s.calls and not s.timers
    if field == '_notes_original_setup_exit_pending':
        with pytest.raises(PermissionError): s.native.Fenster._notes_original_native_setup_prepare(s.h.probe, lambda _: None)
        with pytest.raises(PermissionError): s.native.Fenster._notes_original_native_setup_acquire(s.h.probe)
        with pytest.raises(PermissionError): s.native.Fenster._notes_original_native_setup_candidate(s.h.probe, {})
