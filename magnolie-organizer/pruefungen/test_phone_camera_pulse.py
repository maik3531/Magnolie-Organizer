"""Persistent original libpulse context model; no host source/module changes."""
from pathlib import Path
import ctypes as C
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_camera_pulse as pulse


class NativePulse:
    def __init__(self):
        self.state = 4
        self.calls = []
        self.name = b'magnolie_phone_' + b'a' * 32
        self.reject_load = self.reject_unload = self.wrong_format = self.restart = self.suppress_load_result = False
        self.callback = None
        self.missing_source_queries = 0
        self.source_error = 5

    def pa_threaded_mainloop_new(self): self.calls.append('loop-new'); return 10
    def pa_threaded_mainloop_get_api(self, loop): assert loop == 10; return 20
    def pa_context_new(self, api, name): assert api == 20; self.calls.append('context-new'); return 30
    def pa_context_set_state_callback(self, context, callback, userdata): self.callback = callback
    def pa_context_connect(self, context, server, flags, userdata):
        assert context == 30 and server is None and flags == 1
        self.calls.append('connect-original-no-autospawn'); return 0
    def pa_threaded_mainloop_start(self, loop): self.callback(30, None); return 0
    def pa_context_get_state(self, context): assert context == 30; return self.state
    def pa_context_errno(self, context): assert context == 30; return self.source_error
    def pa_threaded_mainloop_lock(self, loop): pass
    def pa_threaded_mainloop_unlock(self, loop): pass
    def pa_context_load_module(self, context, name, arguments, callback, userdata):
        assert context == 30 and name == b'module-pipe-source'
        assert b'format=s16le rate=48000 channels=1' in arguments
        self.calls.append('load-original')
        if not self.suppress_load_result:
            callback(context, 0xffffffff if self.reject_load else 42, None)
        return 50
    def pa_context_get_source_info_by_name(self, context, name, callback, userdata):
        assert context == 30 and name == self.name
        self.calls.append('query-original-source')
        if self.missing_source_queries:
            self.missing_source_queries -= 1
            callback(context, None, -1, None)
            return 51
        value = pulse._SourcePrefix()
        value.name = self.name; value.index = 9
        value.sample_spec.format = 5 if self.wrong_format else 3
        value.sample_spec.rate = 48000; value.sample_spec.channels = 1
        callback(context, C.pointer(value), 0, None); callback(context, None, 1, None); return 51
    def pa_context_unload_module(self, context, index, callback, userdata):
        assert context == 30 and index == 42
        self.calls.append('unload-original')
        if self.restart:
            self.state = 5
            self.callback(context, None)
        else:
            callback(context, 0 if self.reject_unload else 1, None)
        return 52
    def pa_operation_cancel(self, operation): self.calls.append(('cancel', operation))
    def pa_operation_unref(self, operation): self.calls.append(('unref', operation))
    def pa_threaded_mainloop_stop(self, loop): self.calls.append('loop-stop')
    def pa_context_disconnect(self, context): self.calls.append('disconnect-original')
    def pa_context_unref(self, context): self.calls.append('context-unref')
    def pa_threaded_mainloop_free(self, loop): self.calls.append('loop-free')


def source(native):
    return pulse.PulsePipeSource('magnolie_phone_' + 'a' * 32, '/private/webcam/microphone.pcm', library_factory=lambda: native)


def test_one_original_native_context_loads_inspects_unloads_and_is_reaped():
    native = NativePulse(); value = source(native)
    assert value.module == 42
    value.require(); value.close(); value.close()
    assert native.calls.count('context-new') == 1 and native.calls.count('unload-original') == 1
    assert native.calls[-4:] == ['loop-stop', 'disconnect-original', 'context-unref', 'loop-free']
    with pytest.raises(pulse.PulseUnavailable, match='retired'): value.require()


@pytest.mark.parametrize('moment', ['before_unload', 'inside_unload'])
def test_server_restart_never_reconnects_or_unloads_reused_id_on_new_server(moment):
    native = NativePulse(); value = source(native)
    if moment == 'before_unload': native.state = 5
    else: native.restart = True
    with pytest.raises(pulse.PulseUnavailable, match='retired'): value.close()
    assert native.calls.count('context-new') == 1 and native.calls.count('connect-original-no-autospawn') == 1
    assert native.calls[-4:] == ['loop-stop', 'disconnect-original', 'context-unref', 'loop-free']
    assert value.context is None and value.loop is None and not value.started
    # No new context, lookup or same-integer operation on the new server exists.
    with pytest.raises(pulse.PulseUnavailable, match='retired'): value.require()


def test_unload_failure_is_visible_but_native_loop_is_still_stopped():
    native = NativePulse(); value = source(native); native.reject_unload = True
    with pytest.raises(pulse.PulseUnavailable, match='shutdown_pending'): value.close()
    assert value.context is None and value.loop is None and not value.started


@pytest.mark.parametrize('failure', ['load', 'format'])
def test_missing_module_or_substituted_native_audio_format_fails_only_this_feature(failure):
    native = NativePulse()
    native.reject_load = failure == 'load'; native.wrong_format = failure == 'format'
    with pytest.raises(pulse.PulseUnavailable): source(native)
    assert native.calls[-4:] == ['loop-stop', 'disconnect-original', 'context-unref', 'loop-free']
    assert native.calls.count('unload-original') == (1 if failure == 'format' else 0)


def test_library_is_optional_and_missing_library_does_not_start_any_service(monkeypatch):
    monkeypatch.setattr(pulse.ctypes.util, 'find_library', lambda _: None)
    with pytest.raises(pulse.PulseUnavailable, match='library_unavailable'):
        pulse._library()


def test_import_never_probes_or_loads_optional_native_audio_library():
    code = '''import sys,ctypes
sys.path.insert(0,sys.argv[1])
def forbidden(*args,**kwargs):raise AssertionError('native audio loaded at import')
ctypes.CDLL=forbidden
import magnolie_phone_camera_pulse
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
        str(Path(__file__).resolve().parents[1] / 'bin')], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_uncertain_load_never_reports_clean_stop_or_guesses_a_module_id(monkeypatch):
    # Bounded-operation timeout model; do not alter the production 3-second limit.
    event_type = pulse.threading.Event
    class ExpiredWait(event_type):
        def wait(self, timeout=None): return self.is_set()
    monkeypatch.setattr(pulse.threading, 'Event', ExpiredWait)
    native = NativePulse(); native.suppress_load_result = True
    with pytest.raises(pulse.PulseUnavailable, match='shutdown_pending'): source(native)
    assert 'unload-original' not in native.calls
    assert native.calls[-4:] == ['loop-stop', 'disconnect-original', 'context-unref', 'loop-free']


def test_confirmed_module_waits_for_exact_source_without_reload_or_new_context():
    native = NativePulse(); native.missing_source_queries = 2
    value = source(native)
    try:
        assert value.module == 42 and native.calls.count('query-original-source') == 3
        assert native.calls.count('context-new') == native.calls.count('load-original') == 1
    finally: value.close()


def test_source_permission_error_is_not_retried_as_startup_readiness():
    native = NativePulse(); native.missing_source_queries = 1; native.source_error = 1
    with pytest.raises(pulse.PulseUnavailable, match='format_unsupported'): source(native)
    assert native.calls.count('query-original-source') == 1 and native.calls.count('unload-original') == 1


def test_missing_source_wait_has_one_absolute_deadline_and_original_cleanup(monkeypatch):
    native = NativePulse(); native.missing_source_queries = 100
    ticks = iter(range(100))
    monkeypatch.setattr(pulse.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(pulse.PulseUnavailable, match='source_start_timeout'): source(native)
    assert native.calls.count('load-original') == 1 and native.calls.count('unload-original') == 1
