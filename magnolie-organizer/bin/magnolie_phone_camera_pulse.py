"""Optional persistent libpulse owner, loaded ONLY on explicit webcam activation.

One native connection owns module load/query/unload. Never reconnect or apply an
old module index to a new audio server. No microphone capture/default changes.
"""
import ctypes as C
import ctypes.util
import re
import shlex
import threading


class PulseUnavailable(Exception):
    pass


_StateCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)
_IndexCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32, C.c_void_p)
_SuccessCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_void_p)


class _SampleSpec(C.Structure):
    _fields_ = [('format', C.c_int), ('rate', C.c_uint32), ('channels', C.c_uint8)]


class _SourcePrefix(C.Structure):
    # Public pa_source_info prefix only. Do not read beyond these fields.
    _fields_ = [('name', C.c_char_p), ('index', C.c_uint32),
                ('description', C.c_char_p), ('sample_spec', _SampleSpec)]


_SourceCallback = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(_SourcePrefix), C.c_int, C.c_void_p)


def _library():
    # No native loading/probing at module import or base Organizer startup.
    path = ctypes.util.find_library('pulse')
    if not path:
        raise PulseUnavailable('webcam_native_audio_library_unavailable')
    library = C.CDLL(path)
    signatures = {
        'pa_threaded_mainloop_new': (C.c_void_p, []),
        'pa_threaded_mainloop_get_api': (C.c_void_p, [C.c_void_p]),
        'pa_threaded_mainloop_start': (C.c_int, [C.c_void_p]),
        'pa_threaded_mainloop_stop': (None, [C.c_void_p]),
        'pa_threaded_mainloop_free': (None, [C.c_void_p]),
        'pa_threaded_mainloop_lock': (None, [C.c_void_p]),
        'pa_threaded_mainloop_unlock': (None, [C.c_void_p]),
        'pa_context_new': (C.c_void_p, [C.c_void_p, C.c_char_p]),
        'pa_context_connect': (C.c_int, [C.c_void_p, C.c_char_p, C.c_int, C.c_void_p]),
        'pa_context_get_state': (C.c_int, [C.c_void_p]),
        'pa_context_set_state_callback': (None, [C.c_void_p, _StateCallback, C.c_void_p]),
        'pa_context_disconnect': (None, [C.c_void_p]),
        'pa_context_unref': (None, [C.c_void_p]),
        'pa_operation_cancel': (None, [C.c_void_p]),
        'pa_operation_unref': (None, [C.c_void_p]),
        'pa_context_load_module': (C.c_void_p, [C.c_void_p, C.c_char_p, C.c_char_p, _IndexCallback, C.c_void_p]),
        'pa_context_unload_module': (C.c_void_p, [C.c_void_p, C.c_uint32, _SuccessCallback, C.c_void_p]),
        'pa_context_get_source_info_by_name': (C.c_void_p, [C.c_void_p, C.c_char_p, _SourceCallback, C.c_void_p]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    return library


class PulsePipeSource:
    """No automatic reconnection. Failed cleanup remains visible to its owner."""
    def __init__(self, name, pipe, *, library_factory=_library):
        if type(name) is not str or not re.fullmatch('magnolie_phone_[0-9a-f]{32}', name) or type(pipe) is not str or '\0' in pipe:
            raise ValueError('invalid webcam native audio identity')
        self.lock = threading.RLock()
        self.library = library_factory()
        self.loop = self.context = None
        self.started = False
        self.module = None
        self.load_uncertain = False
        self.pending = None
        self.ready = threading.Event()
        self.state_callback = _StateCallback(self._state_changed)
        try:
            self.loop = self.library.pa_threaded_mainloop_new()
            if not self.loop:
                raise PulseUnavailable('webcam_audio_mainloop_unavailable')
            api = self.library.pa_threaded_mainloop_get_api(self.loop)
            self.context = self.library.pa_context_new(api, b'Magnolie phone webcam')
            if not self.context:
                raise PulseUnavailable('webcam_audio_context_unavailable')
            self.library.pa_context_set_state_callback(self.context, self.state_callback, None)
            # PA_CONTEXT_NOAUTOSPAWN: missing audio services stay an optional
            # feature failure, not permission to start a system/user daemon.
            if self.library.pa_context_connect(self.context, None, 1, None) < 0:
                raise PulseUnavailable('webcam_audio_server_unavailable')
            if self.library.pa_threaded_mainloop_start(self.loop) < 0:
                raise PulseUnavailable('webcam_audio_mainloop_unavailable')
            self.started = True
            if not self.ready.wait(3):
                raise PulseUnavailable('webcam_audio_connection_timeout')
            self.require()
            result = []
            def loaded(_context, index, _userdata):
                self.load_uncertain = False
                if index != 0xffffffff:
                    self.module = index
                result.append(index)
                self.pending.set()
            arguments = ('source_name=' + name + ' file=' + shlex.quote(pipe) +
                         ' format=s16le rate=48000 channels=1 channel_map=mono').encode('utf-8')
            self.load_uncertain = True
            self._operation(_IndexCallback(loaded), lambda callback: self.library.pa_context_load_module(
                self.context, b'module-pipe-source', arguments, callback, None))
            if not result or result[0] == 0xffffffff:
                raise PulseUnavailable('webcam_native_audio_source_unsupported')
            self.module = result[0]
            valid = []
            def source(_context, info, end, _userdata):
                if end:
                    valid.append(end > 0)
                    self.pending.set()
                elif info:
                    value = info.contents
                    spec = value.sample_spec
                    valid.append(value.name == name.encode('ascii') and (spec.format, spec.rate, spec.channels) == (3, 48000, 1))
            self._operation(_SourceCallback(source), lambda callback: self.library.pa_context_get_source_info_by_name(
                self.context, name.encode('ascii'), callback, None))
            if valid != [True, True]:
                raise PulseUnavailable('webcam_native_audio_format_unsupported')
        except BaseException:
            self.close()
            raise

    def _state_changed(self, context, _userdata):
        # libpulse thread callback, already under its native lock. No callbacks
        # into UI/transport/store or acquisition of the Python ownership lock.
        state = self.library.pa_context_get_state(context)
        if state in (4, 5, 6):
            self.ready.set()
        if state in (5, 6) and self.pending is not None:
            self.pending.set()

    def require(self):
        with self.lock:
            if self.context is None or not self.started:
                raise PulseUnavailable('webcam_audio_original_context_retired')
            self.library.pa_threaded_mainloop_lock(self.loop)
            try:
                if self.library.pa_context_get_state(self.context) != 4:
                    raise PulseUnavailable('webcam_audio_original_context_retired')
            finally:
                self.library.pa_threaded_mainloop_unlock(self.loop)

    def _operation(self, callback, begin):
        with self.lock:
            self.require()
            done = self.pending = threading.Event()
            self.library.pa_threaded_mainloop_lock(self.loop)
            try:
                operation = begin(callback)
            finally:
                self.library.pa_threaded_mainloop_unlock(self.loop)
            if not operation:
                self.pending = None
                raise PulseUnavailable('webcam_audio_operation_unavailable')
            try:
                if not done.wait(3):
                    raise PulseUnavailable('webcam_audio_operation_timeout')
                self.require()
            finally:
                self.library.pa_threaded_mainloop_lock(self.loop)
                try:
                    self.library.pa_operation_cancel(operation)
                    self.library.pa_operation_unref(operation)
                    self.pending = None
                finally:
                    self.library.pa_threaded_mainloop_unlock(self.loop)

    def close(self):
        with self.lock:
            try:
                if self.load_uncertain:
                    # A cancelled native request might have reached the server.
                    # Do not report a clean stop or guess a historical module ID.
                    raise PulseUnavailable('webcam_audio_owned_module_shutdown_pending')
                if self.module is not None:
                    # Same original native context. It can fail after a server
                    # restart, but can NEVER silently address that new server.
                    success = []
                    def unloaded(_context, accepted, _userdata):
                        success.append(bool(accepted))
                        self.pending.set()
                    self._operation(_SuccessCallback(unloaded), lambda callback: self.library.pa_context_unload_module(
                        self.context, self.module, callback, None))
                    if success != [True]:
                        raise PulseUnavailable('webcam_audio_owned_module_shutdown_pending')
                    self.module = None
            finally:
                # Stop/reap even on failed unload: no hidden native event loop
                # or automatic reconnect survives a retired resource owner.
                if self.started:
                    self.library.pa_threaded_mainloop_stop(self.loop)
                    self.started = False
                if self.context is not None:
                    self.library.pa_context_disconnect(self.context)
                    self.library.pa_context_unref(self.context)
                    self.context = None
                if self.loop is not None:
                    self.library.pa_threaded_mainloop_free(self.loop)
                    self.loop = None
