"""#753: timing evidence must remain accurate and transparent to the receiver."""
import json
from pathlib import Path
from threading import Event, Thread

import pytest

from photo_receive_timing import PhaseRecorder, PhotoReceiveTiming, install_receive_timing


def test_disabled_probe_never_reads_clock_or_repeats_original_call():
    def forbidden_clock():
        pytest.fail('An inactive probe read the clock')

    probe = PhaseRecorder(clock=forbidden_clock)
    token = object()
    calls = []

    def original(value, *, option):
        calls.append((value, option))
        return token

    assert probe.call('receive', original, token, option=True) is token
    assert calls == [(token, True)]


def test_nested_phases_report_inclusive_and_exclusive_time_separately():
    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    probe.start()

    def child():
        tick[0] = 15

    def parent():
        tick[0] = 5
        probe.call('preferences', child)
        tick[0] = 30

    probe.call('publication', parent)
    tick[0] = 40
    report = probe.snapshot()
    assert report['elapsed_ns'] == 40
    outer, inner = (report['phases'][key] for key in ('publication', 'preferences'))
    assert (outer['inclusive_ns'], outer['exclusive_ns']) == (30, 20)
    assert (inner['inclusive_ns'], inner['exclusive_ns']) == (10, 10)
    assert outer['started'] == outer['completed'] == inner['completed'] == 1
    assert outer['active'] == inner['active'] == 0
    assert report['active_spans'] == []


def test_snapshot_accounts_for_active_child_without_counting_it_twice():
    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    probe.start()
    captured = []

    def child():
        tick[0] = 20
        captured.append(probe.snapshot())
        tick[0] = 25

    def parent():
        tick[0] = 5
        probe.call('preferences', child)
        tick[0] = 35

    probe.call('publication', parent)
    report = captured[0]
    outer, inner = (report['phases'][key] for key in ('publication', 'preferences'))
    assert (outer['inclusive_ns'], outer['exclusive_ns']) == (20, 5)
    assert (inner['inclusive_ns'], inner['exclusive_ns']) == (15, 15)
    assert outer['completed'] == inner['completed'] == 0
    assert outer['active'] == inner['active'] == 1
    spans = {span['phase']: span for span in report['active_spans']}
    assert spans['publication']['lane'] == spans['preferences']['lane']
    assert spans['preferences']['depth'] == spans['publication']['depth'] + 1
    assert spans['publication']['self_ns'] == 5
    assert spans['preferences']['elapsed_ns'] == 15


def test_parallel_workers_are_not_nested_and_snapshot_does_not_wait_for_them():
    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    probe.start()
    entered = [Event(), Event()]
    release = Event()
    captured = []
    failures = []
    reported = Event()

    def work(index):
        entered[index].set()
        assert release.wait(3)

    def run(index):
        try:
            probe.call(('receiver', 'fixture')[index], work, index)
        except BaseException as error:
            failures.append(error)

    def capture():
        try:
            captured.append(probe.snapshot())
        except BaseException as error:
            failures.append(error)
        finally:
            reported.set()

    workers = [Thread(target=run, args=(index,), daemon=True) for index in range(2)]
    observer = Thread(target=capture, daemon=True)
    try:
        workers[0].start()
        assert entered[0].wait(1)
        tick[0] = 10
        workers[1].start()
        assert entered[1].wait(1)
        tick[0] = 20
        observer.start()
        assert reported.wait(1), 'Snapshot waited for a running product call'
        assert not release.is_set()
        report = captured[0]
        assert report['phases']['receiver']['exclusive_ns'] == 20
        assert report['phases']['fixture']['exclusive_ns'] == 10
        spans = report['active_spans']
        assert len(spans) == 2 and len({span['lane'] for span in spans}) == 2
        assert len({span['depth'] for span in spans}) == 1
    finally:
        tick[0] = 30
        release.set()
        for thread in (*workers, observer):
            if thread.ident is not None:
                thread.join(2)
                assert not thread.is_alive()
    assert not failures


def test_return_and_exception_identity_survive_instrumentation():
    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    probe.start()
    token = object()
    failure = RuntimeError('synthetic operation failed')
    calls = []

    def original(value, *, fail):
        calls.append((value, fail))
        tick[0] += 7
        if fail:
            raise failure
        return value

    assert probe.call('receive', original, token, fail=False) is token
    with pytest.raises(RuntimeError) as raised:
        probe.call('receive', original, token, fail=True)
    assert raised.value is failure
    assert calls == [(token, False), (token, True)]
    row = probe.snapshot()['phases']['receive']
    assert row['started'] == row['completed'] == 2
    assert row['errors'] == 1 and row['inclusive_ns'] == 14


def test_report_does_not_capture_arguments_return_values_or_exception_text():
    probe = PhaseRecorder(clock=lambda: 0)
    probe.start()
    private = 'PRIVATE-photo-path-device-id-key-and-content'
    payload = {'path': private, 'bytes': private.encode()}

    def success(value):
        return value

    def failure(value):
        raise ValueError(value['path'])

    assert probe.call('publish', success, payload) is payload
    with pytest.raises(ValueError):
        probe.call('publish', failure, payload)
    encoded = json.dumps(probe.snapshot(), sort_keys=True)
    assert private not in encoded
    assert 'ValueError' not in encoded
    assert probe.snapshot()['phases']['publish']['errors'] == 1


def test_freeze_keeps_deadline_snapshot_before_running_call_and_teardown_finish():
    tick = [0]
    clock_allowed = [True]

    def clock():
        assert clock_allowed[0], 'Frozen measurement read a teardown clock'
        return tick[0]

    probe = PhaseRecorder(clock=clock)
    probe.start()
    captured = []
    token = object()

    def publication():
        tick[0] = 12
        captured.append(probe.freeze())
        clock_allowed[0] = False
        tick[0] = 99
        return token

    assert probe.call('publish', publication) is token
    assert probe.call('teardown', lambda: token) is token
    report = probe.snapshot()
    assert report == captured[0]
    assert report['elapsed_ns'] == 12
    assert report['phases']['publish']['completed'] == 0
    assert report['phases']['publish']['active'] == 1
    assert report['active_spans'][0]['elapsed_ns'] == 12
    assert 'teardown' not in report['phases']
    # A caller cannot accidentally mutate the retained evidence.
    captured[0]['phases']['publish']['inclusive_ns'] = -1
    report['active_spans'].clear()
    stable = probe.snapshot()
    assert stable['phases']['publish']['inclusive_ns'] == 12
    assert len(stable['active_spans']) == 1


def test_repeated_phase_aggregates_calls_errors_and_worst_duration():
    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    probe.start()

    def checkpoint(duration, fail):
        tick[0] += duration
        if fail:
            raise LookupError('fixture failure')

    probe.call('mapping', checkpoint, 3, False)
    with pytest.raises(LookupError):
        probe.call('mapping', checkpoint, 11, True)
    probe.call('mapping', checkpoint, 5, False)
    row = probe.snapshot()['phases']['mapping']
    assert row['started'] == row['completed'] == 3
    assert row['active'] == 0 and row['errors'] == 1
    assert row['inclusive_ns'] == row['exclusive_ns'] == 19
    assert row['max_ns'] == 11


def test_deadline_report_preserves_pre_cleanup_counts_and_active_phase(tmp_path):
    probe = PhotoReceiveTiming()
    probe.start()
    private = 'PRIVATE-content-received-after-deadline'
    for event in ('chunk_request', 'activity_started', 'status', 'discover'):
        probe.event(event)
    probe.mark('deadline_wait_started')

    def publishing(payload):
        probe.checkpoint(deadline_met=False, automatic_mode=True)
        # Teardown and a later completion cannot rewrite the failing boundary.
        probe.event('saved_message')
        probe.event('activity_ended')
        probe.event('peer_error')
        return payload

    assert probe.call('publish', publishing, private) is private
    probe.call('late_cleanup', lambda: None)
    output = tmp_path / 'photo-receive-timing.json'
    probe.write(output)
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['limit_seconds'] == 12 and report['deadline_met'] is False
    assert report['checkpoint_reached'] is True
    assert report['deadline_event'] == 'activity_ended'
    assert report['chunk_requests'] == 1 and report['saved_messages'] == 0
    assert report['peer_errors'] == 0
    assert report['activity_started'] == 1 and report['activity_ended'] == 0
    assert report['status_requests'] == report['discover_requests'] == 1
    phase = report['timing']['phases']['publish']
    assert phase['active'] == 1 and phase['completed'] == 0
    timing = report['timing']
    assert timing['events']['chunk_request'] == 1
    assert timing['events'].get('saved_message', 0) == 0
    assert timing['events'].get('activity_ended', 0) == 0
    assert timing['events'].get('peer_error', 0) == 0
    assert report['wait_elapsed_ns'] == timing['elapsed_ns'] - timing['marks_ns']['deadline_wait_started']
    assert 'late_cleanup' not in report['timing']['phases']
    assert private not in output.read_text(encoding='utf-8')


def test_failure_before_deadline_checkpoint_is_not_reported_as_pass_or_timeout(tmp_path):
    probe = PhotoReceiveTiming()
    probe.start()
    probe.event('activity_started')
    output = tmp_path / 'early-failure.json'
    probe.write(output)
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['deadline_met'] is None
    assert report['checkpoint_reached'] is False
    assert report['timing']['events']['activity_started'] == 1
    probe.event('activity_ended')
    probe.write(output)
    assert json.loads(output.read_text(encoding='utf-8')) == report


def test_installed_wrappers_keep_preference_and_mapping_sync_separate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'bin'))
    from magnolie_photo_preferences import ProtectedPhotoPreferences
    from magnolie_photo_mappings import ProtectedPhotoMappings

    tick = [0]
    probe = PhaseRecorder(clock=lambda: tick[0])
    preferences = object.__new__(ProtectedPhotoPreferences)
    mappings = object.__new__(ProtectedPhotoMappings)
    token = object()
    calls = []
    actual_sync = ProtectedPhotoPreferences._sync

    def synthetic_sync(owner):
        calls.append(owner)
        tick[0] += 4
        return token

    with monkeypatch.context() as patch:
        patch.setattr(ProtectedPhotoPreferences, '_sync', synthetic_sync)
        install_receive_timing(patch, probe)
        probe.start()
        assert preferences._sync() is token
        assert mappings._sync() is token
        assert calls == [preferences, mappings]
        phases = probe.snapshot()['phases']
        assert set(phases) == {'preferences.sync', 'mappings.sync'}
        for row in phases.values():
            assert row['started'] == row['completed'] == 1
            assert row['inclusive_ns'] == row['exclusive_ns'] == 4
    assert ProtectedPhotoPreferences._sync is actual_sync
    assert '_sync' not in ProtectedPhotoMappings.__dict__
