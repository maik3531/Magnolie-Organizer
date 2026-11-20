"""Controlled async ScreenCast responses and exact lifecycle, not real capture."""

import os
import socket
import sys
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from gi.repository import Gio, GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_cast as cast
from magnolie_desktop_screen_portal import DesktopScreenProvider


class Bus:
    def __init__(self):
        self.calls, self.signals = deque(), {}
        self.next_signal = 0
        self.closed = None
        self.open_call = None

    def get_unique_name(self):
        return ':1.42'

    def call(self, destination, path, interface, method, args, signature, flags, timeout, cancel, done, data):
        assert flags == Gio.DBusCallFlags.NO_AUTO_START and timeout == 2000 and cancel is None
        assert destination == (cast._DBUS if method == 'GetNameOwner' else ':1.9')
        self.calls.append((path, interface, method, args, signature, done, data))

    def take(self, method):
        item = self.calls.popleft()
        assert item[2] == method, (method, item[2])
        return item

    def call_finish(self, value):
        if value is None:
            raise GLib.Error('controlled method failure')
        return value

    def call_with_unix_fd_list(self, destination, path, iface, method, args, signature, flags, timeout,
                               fd_list, cancel, callback, data):
        assert (destination, path, iface, method) == (':1.9', cast._ROOT, cast._CAST, 'OpenPipeWireRemote')
        assert flags == Gio.DBusCallFlags.NO_AUTO_START and timeout == 2000 and fd_list is cancel is None
        assert signature.dup_string() == '(h)' and args.get_type_string() == '(oa{sv})'
        assert self.open_call is None
        self.open_call = callback, data

    def call_with_unix_fd_list_finish(self, value):
        return value

    def remote_reply(self, value, fd_list):
        callback, data = self.open_call
        self.open_call = None
        callback(self, (value, fd_list), data)

    def deliver(self, call, result):
        if result is not None:
            assert result.is_of_type(call[4])
        call[-2](self, result, call[-1])

    def signal_subscribe(self, sender, interface, signal, path, arg0, flags, callback, data):
        self.next_signal += 1
        self.signals[self.next_signal] = sender, interface, signal, path, callback, data
        return self.next_signal

    def signal_unsubscribe(self, id):
        del self.signals[id]

    def connect(self, name, callback):
        assert name == 'closed'
        self.closed = callback
        return 1

    def disconnect(self, id):
        assert id == 1
        self.closed = None

    def emit(self, interface, signal, path, params, *, sender=None):
        for want, iface, member, where, callback, data in tuple(self.signals.values()):
            if (iface, member, where) == (interface, signal, path):
                callback(self, sender or want, path, interface, signal, params, data)

    def response(self, path, fields=None, code=0, **kwargs):
        self.emit(cast._REQUEST, 'Response', path, GLib.Variant('(ua{sv})', (code, fields or {})), **kwargs)


def request_path(call):
    token = call[3].unpack()[-1]['handle_token']
    return f'{cast._ROOT}/request/1_42/{token}'


def streams(kind=4, *, serial=903, node=54, count=1):
    values = {}
    if kind is not None:
        values['source_type'] = GLib.Variant('u', kind)
    if serial is not None:
        values['pipewire-serial'] = GLib.Variant('t', serial)
    return {'streams': GLib.Variant('a(ua{sv})', [(node, values)] * count)}


class TestDesktopScreenCast(unittest.TestCase):
    def owner(self, mode='extend', *, version=6, mirror=3, extended=True):
        self.bus, self.ready, self.ended, self.alive = Bus(), [], [], True
        self.run = cast.DesktopScreenCast(self.bus, DesktopScreenProvider(':1.9', mirror, extended, 0, version),
                                         mode, 'x11:1234', self.require, self.on_ready, self.ended.append)
        self.addCleanup(self.run.stop)
        return self.run

    def on_ready(self, owner, target):
        self.assertIs(owner, self.run)
        self.ready.append(target)

    def require(self):
        if not self.alive:
            raise PermissionError('controlled native revoke')

    def create(self, owner=':1.9'):
        self.run.begin()
        self.bus.deliver(self.bus.take('GetNameOwner'), GLib.Variant('(s)', (owner,)))
        if owner == ':1.9':
            return self.bus.take('CreateSession')

    def complete(self, call, fields=None, *, response_first=False, code=0):
        path = request_path(call)
        if response_first:
            self.bus.response(path, fields, code)
            self.assertFalse(self.bus.calls)
        self.bus.deliver(call, GLib.Variant('(o)', (path,)))
        if not response_first:
            self.bus.response(path, fields, code)

    def setup(self, *, response_first=False):
        self.complete(self.create(), {'session_handle': GLib.Variant('s', self.run._session)}, response_first=response_first)
        select = self.bus.take('SelectSources')
        session, opts = select[3].unpack()
        self.assertEqual(session, self.run._session)
        self.assertEqual(opts['types'], cast._MODES[self.run.mode])
        self.assertIs(opts['multiple'], False)
        self.assertNotIn('restore_token', opts)
        if self.run.provider.screen_version >= 4:
            self.assertEqual(opts['persist_mode'], 0)
        else:
            self.assertNotIn('persist_mode', opts)
        self.complete(select)
        start = self.bus.take('Start')
        self.assertEqual(start[3].unpack()[:2], (self.run._session, 'x11:1234'))
        return start

    def close_session(self, result=GLib.Variant('()', ())):
        close = self.bus.take('Close')
        self.assertEqual(close[:2], (self.run._session, cast._SESSION))
        self.bus.deliver(close, result)
        self.assertFalse(self.bus.signals)
        self.assertFalse(self.bus.calls)

    def test_virtual_only_with_original_early_response_and_close(self):
        self.owner()
        start = self.setup(response_first=True)
        self.complete(start, streams(), response_first=True)
        self.assertEqual(self.ready, [cast.ScreenCastTarget('extend', 54, 903)])
        self.assertEqual(self.ended, [])
        self.run.stop()
        self.close_session()
        self.assertEqual(self.ended, [True])
        with self.assertRaises(RuntimeError):
            self.run.begin()

    def test_no_retry_for_wrong_type_missing_type_or_multiple_results(self):
        for fields in (streams(1), streams(None), streams(count=2), streams(serial=None)):
            with self.subTest(fields=fields):
                self.owner()
                self.complete(self.setup(), fields)
                self.assertEqual(self.ready, [])
                self.close_session()
                self.assertEqual(self.ended, [True])

    def test_cancelled_native_chooser_never_selects_stream(self):
        self.owner()
        self.complete(self.setup(), code=1)
        self.assertEqual(self.ready, [])
        self.close_session()
        self.assertEqual(self.ended, [True])

    def test_owner_replaced_before_create_or_after_start(self):
        self.owner()
        self.create(owner=':1.10')
        self.assertFalse(self.bus.calls)
        self.assertEqual(self.ended, [True])
        self.owner()
        self.complete(self.setup(), streams())
        signal = GLib.Variant('(sss)', (cast._PORTAL, ':1.9', ':1.10'))
        self.bus.emit(cast._DBUS, 'NameOwnerChanged', '/org/freedesktop/DBus', signal)
        self.close_session()
        self.assertEqual(self.ended, [False])

    def test_stop_while_create_unacknowledged_does_not_claim_drain(self):
        self.owner()
        create = self.create()
        self.run.stop()
        self.assertFalse(self.bus.calls)
        self.assertEqual(self.ended, [])
        path = request_path(create)
        self.bus.deliver(create, GLib.Variant('(o)', (path,)))
        close = self.bus.take('Close')
        self.assertEqual(close[:2], (path, cast._REQUEST))
        self.bus.deliver(close, GLib.Variant('()', ()))
        self.close_session()
        self.assertEqual(self.ended, [True])

    def test_lost_local_guard_drops_late_success_and_checks_close(self):
        self.owner()
        start = self.setup()
        self.alive = False
        self.complete(start, streams())
        self.assertEqual(self.ready, [])
        self.close_session(None)
        self.assertEqual(self.ended, [False])

    def test_portal_revoke_closes_only_original_and_never_restarts(self):
        self.owner('window', version=3)
        self.complete(self.setup(), streams(2, serial=None))
        foreign = GLib.Variant('(a{sv})', ({},))
        self.bus.emit(cast._SESSION, 'Closed', self.run._session, foreign, sender=':1.100')
        self.assertFalse(self.ended)
        self.bus.emit(cast._SESSION, 'Closed', self.run._session, foreign)
        self.assertFalse(self.bus.calls)
        self.assertEqual(self.ended, [True])

    def test_wrong_method_handle_does_not_close_foreign_request(self):
        self.owner()
        self.bus.deliver(self.create(), GLib.Variant('(o)', ('/foreign/request',)))
        self.close_session()
        self.assertEqual(self.ended, [False])

    def test_bus_loss_does_not_send_late_close_or_publish(self):
        self.owner()
        create = self.create()
        self.bus.closed(self.bus, True, None)
        self.bus.deliver(create, GLib.Variant('(o)', (request_path(create),)))
        self.assertEqual(self.ended, [False])
        self.assertFalse(self.bus.calls or self.bus.signals or self.ready)

    def test_open_once_with_original_target_and_close_only_its_fd(self):
        self.owner()
        self.complete(self.setup(), streams())
        target, = self.ready
        opened = []
        with self.assertRaises(PermissionError):
            self.run.open_pipewire_remote(cast.ScreenCastTarget('extend', 54, 903), opened.append)
        self.run.open_pipewire_remote(target, opened.append)
        with self.assertRaises(PermissionError):
            self.run.open_pipewire_remote(target, opened.append)
        with socket.socket() as endpoint:
            portal_fds = Gio.UnixFDList.new()
            portal_fds.append(endpoint.fileno())
            self.bus.remote_reply(GLib.Variant('(h)', (0,)), portal_fds)
            remote, = opened
            borrowed = remote.fileno()
            self.assertFalse(os.get_inheritable(borrowed))
            self.run.stop()
            self.close_session()
            with self.assertRaises(PermissionError):
                remote.fileno()
            with self.assertRaises(OSError):
                os.fstat(borrowed)
            self.assertEqual(self.ended, [True])
            os.fstat(endpoint.fileno())

    def test_stop_before_fd_reply_waits_and_discards_it(self):
        self.owner()
        self.complete(self.setup(), streams())
        opened = []
        self.run.open_pipewire_remote(self.ready[0], opened.append)
        self.run.stop()
        close = self.bus.take('Close')
        self.bus.deliver(close, GLib.Variant('()', ()))
        self.assertEqual(self.ended, [])
        with socket.socket() as endpoint:
            fd = os.dup(endpoint.fileno())
            portal_fds = Gio.UnixFDList.new_from_array([fd])
            self.bus.remote_reply(GLib.Variant('(h)', (0,)), portal_fds)
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertEqual(opened, [])
        self.assertEqual(self.ended, [True])

    def test_reject_other_fd_index_or_extra_fd_without_leak(self):
        for index, number in ((1, 1), (0, 2)):
            with self.subTest(index=index, number=number), socket.socket() as endpoint:
                self.owner()
                self.complete(self.setup(), streams())
                opened = []
                self.run.open_pipewire_remote(self.ready[0], opened.append)
                descriptors = [os.dup(endpoint.fileno()) for _ in range(number)]
                self.bus.remote_reply(GLib.Variant('(h)', (index,)), Gio.UnixFDList.new_from_array(descriptors))
                self.assertEqual(opened, [])
                self.close_session()
                for fd in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(fd)

    def test_setup_deadline_not_renewed_by_portal_round_trip(self):
        self.owner()
        with patch.object(cast, 'monotonic', return_value=100):
            start = self.setup()
        with patch.object(cast, 'monotonic', return_value=130):
            self.complete(start, streams())
        self.assertFalse(self.ready)
        self.close_session()

    def test_passing_setup_deadline_cannot_be_extended_by_fd_open(self):
        self.owner()
        opened = []
        with patch.object(cast, 'monotonic', return_value=100):
            self.complete(self.setup(), streams())
            self.run.open_pipewire_remote(self.ready[0], opened.append)
        with socket.socket() as endpoint, patch.object(cast, 'monotonic', return_value=130):
            fd = os.dup(endpoint.fileno())
            self.bus.remote_reply(GLib.Variant('(h)', (0,)), Gio.UnixFDList.new_from_array([fd]))
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertFalse(opened)
        self.close_session()


class TestIsolatedGioScreenCast(unittest.TestCase):
    def test_real_gio_dispatch_with_private_portal_double(self):
        # The test's separate daemon has no installed desktop portal. Neither
        # connection can ask the real desktop to capture or create an output.
        isolated = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        isolated.up()
        self.addCleanup(isolated.down)
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        portal, client = [Gio.DBusConnection.new_for_address_sync(isolated.get_bus_address(), flags, None, None) for _ in range(2)]
        for connection in (portal, client):
            connection.set_exit_on_close(False)
            self.addCleanup(connection.close_sync, None)
        claim = portal.call_sync(cast._DBUS, '/org/freedesktop/DBus', cast._DBUS, 'RequestName',
                                 GLib.Variant('(su)', (cast._PORTAL, 4)), GLib.VariantType.new('(u)'),
                                 Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
        self.assertEqual(claim.unpack(), (1,))
        cast_xml = Gio.DBusNodeInfo.new_for_xml(f'''<node><interface name="{cast._CAST}">
            <method name="CreateSession"><arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method>
            <method name="SelectSources"><arg type="o" direction="in"/><arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method>
            <method name="Start"><arg type="o" direction="in"/><arg type="s" direction="in"/><arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method>
            <method name="OpenPipeWireRemote"><arg type="o" direction="in"/><arg type="a{{sv}}" direction="in"/><arg type="h" direction="out"/></method>
            </interface></node>''')
        session_xml = Gio.DBusNodeInfo.new_for_xml(f'''<node><interface name="{cast._SESSION}">
            <method name="Close"/></interface></node>''')
        calls, selected, ended, errors, borrowed = [], [], [], [], []
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        os.write(write_fd, b'portal-test-fd')
        loop = GLib.MainLoop()

        def server(bus, sender, path, iface, method, params, invocation):
            try:
                self.assertEqual(sender, client.get_unique_name())
                calls.append(method)
                if method == 'Close':
                    self.assertEqual(path, run._session)
                    invocation.return_value(GLib.Variant('()', ()))
                    return
                values = params.unpack()
                if method == 'OpenPipeWireRemote':
                    self.assertEqual(values, (run._session, {}))
                    descriptors = Gio.UnixFDList.new()
                    position = descriptors.append(read_fd)
                    invocation.return_value_with_unix_fd_list(GLib.Variant('(h)', (position,)), descriptors)
                    return
                options = values[-1]
                request = f'{cast._ROOT}/request/{sender[1:].replace(".", "_")}/{options["handle_token"]}'
                if method == 'CreateSession':
                    session = f'{cast._ROOT}/session/{sender[1:].replace(".", "_")}/{options["session_handle_token"]}'
                    self.assertEqual(session, run._session)
                    portal.register_object(session, session_xml.interfaces[0], server, None, None)
                    result = {'session_handle': GLib.Variant('s', session)}
                elif method == 'SelectSources':
                    self.assertEqual(values[0], run._session)
                    self.assertEqual((options['types'], options['multiple'], options['persist_mode']), (4, False, 0))
                    result = {}
                else:
                    self.assertEqual(values[:2], (run._session, 'x11:1234'))
                    result = streams()
                bus.emit_signal(sender, request, cast._REQUEST, 'Response', GLib.Variant('(ua{sv})', (0, result)))
                invocation.return_value(GLib.Variant('(o)', (request,)))
            except Exception as error:
                errors.append(error)
                invocation.return_dbus_error('org.magnolie.TestError', 'controlled ScreenCast assertion failed')

        portal.register_object(cast._ROOT, cast_xml.interfaces[0], server, None, None)

        def ready(original, target):
            selected.append(target)
            def remote_ready(remote):
                fd = remote.fileno()
                borrowed.append((fd, os.read(fd, 32), os.get_inheritable(fd)))
                original.stop()
            original.open_pipewire_remote(target, remote_ready)

        def finished(clean):
            ended.append(clean)
            loop.quit()

        provider = DesktopScreenProvider(portal.get_unique_name(), 0, True, 0, 6)
        run = cast.DesktopScreenCast(client, provider, 'extend', 'x11:1234', lambda: None, ready, finished)
        timeout = GLib.timeout_add(4500, lambda: (loop.quit(), False)[1])
        try:
            run.begin()
            loop.run()
        finally:
            run.stop()
            if GLib.MainContext.default().find_source_by_id(timeout) is not None:
                GLib.source_remove(timeout)
        self.assertEqual(errors, [])
        self.assertEqual(calls, ['CreateSession', 'SelectSources', 'Start', 'OpenPipeWireRemote', 'Close'])
        self.assertEqual(selected, [cast.ScreenCastTarget('extend', 54, 903)])
        self.assertEqual(ended, [True])
        fd, data, inherited = borrowed[0]
        self.assertEqual((data, inherited), (b'portal-test-fd', False))
        with self.assertRaises(OSError):
            os.fstat(fd)


if __name__ == '__main__':
    unittest.main()
