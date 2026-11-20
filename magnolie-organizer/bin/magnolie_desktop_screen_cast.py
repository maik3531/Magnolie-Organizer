"""One explicit Linux desktop-to-phone ScreenCast portal session (#245).

Internal source component only; no product caller, PipeWire IO, renderer or
input. All public methods/callbacks are confined to the GTK main context.
"""

from dataclasses import dataclass
import os
from secrets import token_hex
from threading import Event
from time import monotonic
from typing import Optional

from gi.repository import Gio, GLib

from magnolie_desktop_screen_portal import MONITOR, VIRTUAL, WINDOW

_PORTAL = 'org.freedesktop.portal.Desktop'
_ROOT = '/org/freedesktop/portal/desktop'
_CAST = 'org.freedesktop.portal.ScreenCast'
_SESSION = 'org.freedesktop.portal.Session'
_REQUEST = 'org.freedesktop.portal.Request'
_DBUS = 'org.freedesktop.DBus'
_METHOD_MS = 2000
_SETUP_S = 30
_MODES = {'monitor': MONITOR, 'window': WINDOW, 'extend': VIRTUAL}


def _get(fields, key, signature):
    value = fields.lookup_value(key, GLib.VariantType.new(signature))
    return None if value is None else value.unpack()


@dataclass(frozen=True)
class ScreenCastTarget:
    mode: str
    node: int
    serial: Optional[int]


class ScreenCastRemote:
    """One local PipeWire file descriptor, borrowed only by the trusted caller."""

    def __init__(self, owner, fd):
        self._owner, self._fd = owner, fd
        self._capture_claimed = False
        self._retired = Event()

    def fileno(self):
        if not self._owner._current() or self._fd < 0:
            raise PermissionError('screen_cast_original_remote_retired')
        return self._fd

    def _close(self):
        self._retired.set()
        fd, self._fd = self._fd, -1
        if fd >= 0:
            os.close(fd)

    def _claim_capture(self, target):
        # Main context only. The worker gets an owned duplicate, never a
        # borrowed integer that might be reused when the portal closes it.
        if self._capture_claimed or target is not self._owner._target or not target.serial:
            raise PermissionError('screen_cast_original_serial_required')
        fd = os.dup(self.fileno())
        self._capture_claimed = True
        return fd, self._retired, self._owner._deadline


def _target(fields, mode, version):
    streams = fields.lookup_value('streams', GLib.VariantType.new('a(ua{sv})'))
    if streams is None or streams.n_children() != 1:
        raise ValueError('screen_cast_single_stream_required')
    stream = streams.get_child_value(0)
    node = stream.get_child_value(0).get_uint32()
    properties = stream.get_child_value(1)
    if _get(properties, 'source_type', 'u') != _MODES[mode]:
        raise ValueError('screen_cast_original_source_type_required')
    serial = _get(properties, 'pipewire-serial', 't')
    # On v6+ a reusable node ID cannot substitute for the stream serial.
    if (version >= 6 and not serial) or (not serial and not node):
        raise ValueError('screen_cast_original_stream_identity_required')
    return ScreenCastTarget(mode, node, serial or None)


class _Request:
    def __init__(self, run, path, method, args, done):
        self.run, self.path, self.done = run, path, done
        self.ack = self.finished = self.closing = False
        self.response = None
        self.signal = run._subscribe(_REQUEST, 'Response', path, self._responded)
        run._call(_CAST, method, _ROOT, args, '(o)', self._returned)

    def _returned(self, result):
        if self.finished:
            return
        if result is None or result.unpack() != (self.path,):
            self.run._cleanup_ok = False  # Unknown/late work is not a confirmed drain.
            self._finish(None)
            return
        self.ack = True
        self._advance()

    def _responded(self, params):
        if self.finished or self.response is not None:
            return
        if params.get_type_string() != '(ua{sv})':
            self.run.stop()
            return
        self.response = params
        self._advance()

    def cancel(self):
        self.closing = True
        self._advance()

    def _advance(self):
        if self.finished or not self.ack:
            return
        if self.response is not None:
            self._finish(None if self.closing else self.response)
        elif self.closing:
            # Do not send a Close before the exact request has been created.
            # Request.Close does not itself emit a Response.
            self.ack = False
            self.run._call(_REQUEST, 'Close', self.path, None, '()', self._closed)

    def _closed(self, result):
        if result is None and self.response is None:
            self.run._cleanup_ok = False
        self._finish(None)

    def _finish(self, response):
        if self.finished:
            return
        self.finished = True
        self.run.bus.signal_unsubscribe(self.signal)
        self.done(self, response)


class DesktopScreenCast:
    """One selected, non-persistent mode. A target is not an active media stream."""

    def __init__(self, bus, provider, mode, parent_window, require_original, selection_ready, ended):
        supported = _MODES.get(mode)
        if supported is None or provider.owner is None or provider.screen_version < 3 or not (
                provider.extended_output if supported == VIRTUAL else provider.mirror_sources & supported):
            raise PermissionError('screen_cast_mode_unavailable')
        if not isinstance(parent_window, str) or not parent_window.startswith(('wayland:', 'x11:')) or not (
                5 < len(parent_window) <= 512 and parent_window.partition(':')[2] and parent_window.isascii()
                and parent_window.isprintable()):
            raise ValueError('screen_cast_native_parent_window_required')
        self.bus, self.provider, self.mode = bus, provider, mode
        self.parent_window = parent_window
        self._require_original = require_original
        self._ready, self._ended = selection_ready, ended
        name = bus.get_unique_name()
        if not name or not name.startswith(':'):
            raise ValueError('screen_cast_session_bus_required')
        self._sender = name[1:].replace('.', '_')
        self._token = 'm' + token_hex(16)
        self._session = f'{_ROOT}/session/{self._sender}/{self._token}'
        self._phase = 'new'
        self._deadline = 0
        self._request = None
        self._signals = []
        self._bus_signal = None
        self._timer = None
        self._create_submitted = self._session_closed = self._close_pending = self._close_returned = False
        self._bus_lost = False
        self._cleanup_ok = True
        self._target = self._remote = None
        self._remote_attempted = self._remote_pending = False

    def begin(self):
        if self._phase != 'new':
            raise RuntimeError('screen_cast_owner_already_used')
        self._phase = 'setup'
        self._deadline = monotonic() + _SETUP_S
        self._signals.append(self.bus.signal_subscribe(
            _DBUS, _DBUS, 'NameOwnerChanged', '/org/freedesktop/DBus', _PORTAL,
            Gio.DBusSignalFlags.NONE, self._owner_changed, None))
        self._signals.append(self._subscribe(_SESSION, 'Closed', self._session, self._closed_signal))
        self._bus_signal = self.bus.connect('closed', self._bus_closed)
        self._timer = GLib.timeout_add(50, self._tick)
        if self._current():
            self._call(_DBUS, 'GetNameOwner', '/org/freedesktop/DBus', GLib.Variant('(s)', (_PORTAL,)),
                       '(s)', self._ownership_checked, destination=_DBUS)

    def _subscribe(self, interface, member, path, handler):
        def received(_bus, sender, actual_path, iface, signal, params, _data):
            if (sender, actual_path, iface, signal) == (self.provider.owner, path, interface, member):
                handler(params)
        return self.bus.signal_subscribe(self.provider.owner, interface, member, path, None,
                                         Gio.DBusSignalFlags.NONE, received, None)

    def _call(self, interface, method, path, args, signature, done, *, destination=None):
        def returned(bus, result, _data):
            try:
                value = bus.call_finish(result)
            except GLib.Error:
                value = None
            done(value)
        self.bus.call(destination or self.provider.owner, path, interface, method, args,
                      GLib.VariantType.new(signature), Gio.DBusCallFlags.NO_AUTO_START,
                      _METHOD_MS, None, returned, None)

    def _ownership_checked(self, result):
        if not self._current():
            return
        if result is None or result.unpack() != (self.provider.owner,):
            self.stop()
            return
        self._create_submitted = True
        self._new_request('CreateSession', '(a{sv})', (), {'session_handle_token': GLib.Variant('s', self._token)}, self._created)

    def _new_request(self, method, signature, prefix, options, done):
        token = 'm' + token_hex(16)
        options['handle_token'] = GLib.Variant('s', token)
        path = f'{_ROOT}/request/{self._sender}/{token}'
        self._request = _Request(self, path, method, GLib.Variant(signature, (*prefix, options)),
                                 lambda request, response: self._completed(request, response, done))

    def _completed(self, request, response, callback):
        if self._request is not request:
            return
        self._request = None
        if self._phase == 'closing':
            self._finish_or_close()
        elif self._current():
            if response is None or response.get_child_value(0).get_uint32() != 0:
                self.stop()
                return
            try:
                callback(response.get_child_value(1))
            except Exception:
                self.stop()

    def _created(self, fields):
        # This one portal field is a string, despite containing an object path.
        if _get(fields, 'session_handle', 's') != self._session:
            self._cleanup_ok = False
            raise ValueError('screen_cast_original_session_required')
        options = {'types': GLib.Variant('u', _MODES[self.mode]), 'multiple': GLib.Variant('b', False)}
        if self.provider.screen_version >= 4:
            options['persist_mode'] = GLib.Variant('u', 0)
        self._new_request('SelectSources', '(oa{sv})', (self._session,), options, self._selected)

    def _selected(self, _fields):
        self._new_request('Start', '(osa{sv})', (self._session, self.parent_window), {}, self._started)

    def _started(self, fields):
        target = _target(fields, self.mode, self.provider.screen_version)
        if self._current():
            self._phase = 'selected'
            self._target = target
            self._ready(self, target)

    def open_pipewire_remote(self, target, ready):
        """Open once after the approved target, not via a default PipeWire socket."""
        if self._remote_attempted or not self.selection_current(target):
            raise PermissionError('screen_cast_original_selected_target_required')
        self._remote_attempted = self._remote_pending = True

        def returned(bus, result, _data):
            fds = []
            try:
                value, fd_list = bus.call_with_unix_fd_list_finish(result)
                if fd_list is not None:
                    fds = fd_list.steal_fds()
                if len(fds) != 1 or value is None or value.unpack() != (0,):
                    raise ValueError('screen_cast_original_remote_descriptor_required')
                if self._current():
                    os.set_inheritable(fds[0], False)
                    self._remote = ScreenCastRemote(self, fds.pop())
                    ready(self._remote)
            except Exception:
                self.stop()
            finally:
                for fd in fds:
                    try:
                        os.close(fd)
                    except OSError:
                        self._cleanup_ok = False
                self._remote_pending = False
                if self._phase == 'closing':
                    self._finish_or_close()

        try:
            self.bus.call_with_unix_fd_list(self.provider.owner, _ROOT, _CAST, 'OpenPipeWireRemote',
                                            GLib.Variant('(oa{sv})', (self._session, {})), GLib.VariantType.new('(h)'),
                                            Gio.DBusCallFlags.NO_AUTO_START, _METHOD_MS, None, None, returned, None)
        except Exception:
            self._remote_pending = False
            self.stop()
            raise

    def selection_current(self, target):
        return self._phase == 'selected' and self._target is target and self._current()

    @property
    def setup_deadline(self):
        return self._deadline

    def _owner_changed(self, _bus, sender, _path, _iface, _signal, params, _data):
        if sender == _DBUS and params.get_type_string() == '(sss)':
            name, before, after = params.unpack()
            if name == _PORTAL and before == self.provider.owner and after != before:
                self._cleanup_ok = False
                self.stop()

    def _closed_signal(self, params):
        if params.get_type_string() == '(a{sv})':
            self._session_closed = True
            self.stop()

    def _bus_closed(self, *_):
        if self._phase == 'ended':
            return
        self._bus_lost = True
        self._cleanup_ok = False
        if self._phase != 'closing':
            self.stop()
        elif self._request is not None:
            self._request._finish(None)
        else:
            self._finish_or_close()

    def _current(self):
        if self._phase not in ('setup', 'selected'):
            return False
        try:
            self._require_original()
            if self._remote is None and monotonic() >= self._deadline:
                raise TimeoutError('screen_cast_original_deadline')
            return self._phase in ('setup', 'selected')
        except Exception:
            self.stop()
            return False

    def _tick(self):
        # The source may have been removed by synchronous stop/retirement.
        return self._current()

    def stop(self):
        if self._phase in ('closing', 'ended'):
            return
        self._phase = 'closing'
        if self._remote is not None:
            try:
                self._remote._close()
            except OSError:
                self._cleanup_ok = False
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        if self._request is not None:
            if self._bus_lost:
                self._request._finish(None)
            else:
                self._request.cancel()
        else:
            self._finish_or_close()

    def _finish_or_close(self):
        if not self._bus_lost and self._create_submitted and not self._session_closed and not self._close_returned:
            if not self._close_pending:
                self._close_pending = True
                self._call(_SESSION, 'Close', self._session, None, '()', self._session_close_returned)
        elif not self._remote_pending:
            self._finish()

    def _session_close_returned(self, result):
        if self._phase == 'ended':
            return
        self._close_returned = True
        self._session_closed = self._session_closed or result is not None
        if result is None and not self._session_closed:
            self._cleanup_ok = False
        self._finish_or_close()

    def _finish(self):
        self._phase = 'ended'
        for signal in self._signals:
            self.bus.signal_unsubscribe(signal)
        self._signals.clear()
        if self._bus_signal is not None:
            self.bus.disconnect(self._bus_signal)
            self._bus_signal = None
        # This says only that owned portal resources are gone. Native output
        # removal and any consumer drain will need their own evidence.
        self._ended(self._cleanup_ok and (self._session_closed or not self._create_submitted))
