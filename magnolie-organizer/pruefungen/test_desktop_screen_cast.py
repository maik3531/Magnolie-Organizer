"""Controlled async ScreenCast responses and exact lifecycle, not real capture."""

from io import BytesIO
import json
import os
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from gi.repository import Gio, GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_desktop_screen_cast as cast
from magnolie_desktop_screen_portal import DesktopScreenProvider
from magnolie_desktop_screen_output import KWinOutputFeed
from magnolie_desktop_screen_run import DesktopScreenLocalRun, ScreenRunCleanup


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


def streams(kind=4, *, serial=903, node=54, count=1, mapping=None):
    values = {}
    if kind is not None:
        values['source_type'] = GLib.Variant('u', kind)
    if serial is not None:
        values['pipewire-serial'] = GLib.Variant('t', serial)
    if mapping is not None:
        values['mapping_id'] = GLib.Variant('s', mapping)
    return {'streams': GLib.Variant('a(ua{sv})', [(node, values)] * count)}


class TestDesktopScreenCast(unittest.TestCase):
    def owner(self, mode='extend', *, version=6, mirror=3, extended=True, before_virtual_start=None):
        self.bus, self.ready, self.ended, self.alive = Bus(), [], [], True
        self.run = cast.DesktopScreenCast(self.bus, DesktopScreenProvider(':1.9', mirror, extended, 0, version),
                                         mode, 'x11:1234', self.require, self.on_ready, self.ended.append,
                                         before_virtual_start=before_virtual_start)
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
        self.assertFalse(self.run.virtual_start_submitted)
        start = self.setup(response_first=True)
        self.assertTrue(self.run.virtual_start_submitted)
        self.complete(start, streams(), response_first=True)
        self.assertEqual(self.ready, [cast.ScreenCastTarget('extend', 54, 903)])
        self.assertEqual(self.ended, [])
        self.run.stop()
        self.close_session()
        self.assertEqual(self.ended, [True])
        self.assertTrue(self.run.virtual_start_submitted)
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
        self.assertTrue(self.run.virtual_start_submitted)

    def test_monitor_start_never_creates_virtual_output_claim(self):
        self.owner(mode='monitor', mirror=1)
        self.complete(self.setup(), streams(1))
        self.assertEqual(self.ready, [cast.ScreenCastTarget('monitor', 54, 903)])
        self.run.stop()
        self.close_session()
        self.assertEqual(self.ended, [True])
        self.assertFalse(self.run.virtual_start_submitted)

    def test_lost_output_observer_prevents_virtual_start(self):
        def unavailable():
            raise PermissionError('controlled original registry loss')

        self.owner(before_virtual_start=unavailable)
        self.complete(self.create(), {'session_handle': GLib.Variant('s', self.run._session)})
        self.complete(self.bus.take('SelectSources'))
        self.close_session()
        self.assertEqual(self.ended, [True])
        self.assertFalse(self.run.virtual_start_submitted)

    def test_virtual_start_waits_for_barrier_and_submits_only_once(self):
        ready = False
        self.owner(before_virtual_start=lambda: ready)
        self.complete(self.create(), {'session_handle': GLib.Variant('s', self.run._session)})
        self.complete(self.bus.take('SelectSources'))
        self.assertTrue(self.run._tick())
        self.assertEqual(list(self.bus.calls), [])
        self.assertFalse(self.run.virtual_start_submitted)
        ready = True
        self.assertTrue(self.run._tick())
        start = self.bus.take('Start')
        self.assertTrue(self.run.virtual_start_submitted)
        self.assertTrue(self.run._tick())
        self.assertEqual(list(self.bus.calls), [])
        self.complete(start, streams())
        self.run.stop()
        self.close_session()

    def test_revocation_during_barrier_cannot_submit_start(self):
        self.owner(before_virtual_start=lambda: False)
        self.complete(self.create(), {'session_handle': GLib.Variant('s', self.run._session)})
        self.complete(self.bus.take('SelectSources'))
        self.alive = False
        self.assertFalse(self.run._tick())
        self.close_session()
        self.assertFalse(self.run.virtual_start_submitted)

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
        self.assertFalse(self.run.virtual_start_submitted)

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
        self._exercise_portal(use_pipewire=False)

    @unittest.skipUnless(os.environ.get('MAGNOLIE_SCREEN_PRIVATE_PIPEWIRE') == '1',
                         'opt in to private synthetic PipeWire and WirePlumber 0.4')
    def test_portal_passes_real_pipewire_fd_and_original_source_loss_drains(self):
        self._exercise_portal(use_pipewire=True)

    @unittest.skipUnless(os.environ.get('MAGNOLIE_SCREEN_PRIVATE_PIPEWIRE') == '1',
                         'opt in to private synthetic PipeWire and WirePlumber 0.4')
    def test_portal_close_waits_for_the_independently_observed_output_removal(self):
        self._exercise_portal(use_pipewire=True, observe_output=True)

    def _private_sources(self, address):
        runtime = TemporaryDirectory(prefix='magnolie-screen-source-')
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        env = dict(PATH='/usr/bin:/bin', HOME=runtime.name, XDG_RUNTIME_DIR=runtime.name,
                   PIPEWIRE_RUNTIME_DIR=runtime.name, PIPEWIRE_REMOTE='pipewire-0',
                   PIPEWIRE_CONFIG_DIR='/usr/share/pipewire', WIREPLUMBER_CONFIG_DIR='/usr/share/wireplumber',
                   XDG_CACHE_HOME=str(root / 'cache'), XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state'),
                   DBUS_SESSION_BUS_ADDRESS=address, DBUS_SYSTEM_BUS_ADDRESS=f'unix:path={root}/no-system-bus',
                   GIO_USE_VFS='local')

        def launch(argv):
            child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

            def reap():
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(2)
            self.addCleanup(reap)
            return child

        def wait_for(check):
            deadline = monotonic() + 4
            while monotonic() < deadline:
                value = check()
                if value:
                    return value
                sleep(.04)
            self.fail('private PipeWire fixture setup timed out')

        launch(['pipewire', '-c', 'pipewire.conf'])
        endpoint = root / 'pipewire-0'
        wait_for(endpoint.is_socket)
        # policy.conf in WirePlumber 0.4 does not load camera/audio monitors.
        self.assertTrue(Path('/usr/share/wireplumber/policy.conf').is_file())
        launch(['wireplumber', '-c', 'policy.conf'])

        def serial_for(name):
            nodes = json.loads(subprocess.check_output(['pw-dump'], env=env, timeout=2))
            for node in nodes:
                props = node.get('info', {}).get('props', {})
                if props.get('node.name') == name:
                    return props['object.serial']

        def source(pattern):
            name = 'magnolie-test-screen-' + pattern
            process = launch(['gst-launch-1.0', '-q', 'videotestsrc', 'is-live=true', f'pattern={pattern}', '!',
                'video/x-raw,format=RGB,width=57,height=33,framerate=10/1', '!', 'pipewiresink',
                'mode=provide', f'stream-properties=props,node.name={name},media.class=Video/Source'])
            return process, wait_for(lambda: serial_for(name))

        original, serial = source('black')
        unrelated, other_serial = source('white')
        self.assertNotEqual(serial, other_serial)
        with socket.socket(socket.AF_UNIX) as connected:
            connected.connect(str(endpoint))
            fd = connected.detach()
        self.addCleanup(os.close, fd)
        return fd, serial, original, unrelated

    def _exercise_portal(self, *, use_pipewire, observe_output=False):
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
        if use_pipewire:
            from PIL import Image
            read_fd, serial, original, unrelated = self._private_sources(isolated.get_bus_address())
        else:
            serial = 903
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
            self.addCleanup(os.close, read_fd)
            self.addCleanup(os.close, write_fd)
            os.write(write_fd, b'portal-test-fd')
        loop = GLib.MainLoop()
        feed = None
        mapping = 'Virtual-virtual-xdp-kde-magnolie-1'
        if observe_output:
            feed = KWinOutputFeed()
            self.addCleanup(feed.close)
            self.assertTrue(feed.consume(b'+\t1\teDP-1\n'))
            self.assertTrue(feed.consume(b'ready\n'))

        def server(bus, sender, path, iface, method, params, invocation):
            try:
                self.assertEqual(sender, client.get_unique_name())
                calls.append(method)
                if method == 'Close':
                    self.assertEqual(path, portal_owner._session)
                    invocation.return_value(GLib.Variant('()', ()))
                    return
                values = params.unpack()
                if method == 'OpenPipeWireRemote':
                    self.assertEqual(values, (portal_owner._session, {}))
                    descriptors = Gio.UnixFDList.new()
                    position = descriptors.append(read_fd)
                    invocation.return_value_with_unix_fd_list(GLib.Variant('(h)', (position,)), descriptors)
                    return
                options = values[-1]
                request = f'{cast._ROOT}/request/{sender[1:].replace(".", "_")}/{options["handle_token"]}'
                if method == 'CreateSession':
                    session = f'{cast._ROOT}/session/{sender[1:].replace(".", "_")}/{options["session_handle_token"]}'
                    self.assertEqual(session, portal_owner._session)
                    portal.register_object(session, session_xml.interfaces[0], server, None, None)
                    result = {'session_handle': GLib.Variant('s', session)}
                elif method == 'SelectSources':
                    self.assertEqual(values[0], portal_owner._session)
                    self.assertEqual((options['types'], options['multiple'], options['persist_mode']), (4, False, 0))
                    result = {}
                else:
                    self.assertEqual(values[:2], (portal_owner._session, 'x11:1234'))
                    if feed is not None:
                        self.assertTrue(feed.consume(f'+\t2\t{mapping}\n'.encode()))
                    result = streams(serial=serial, mapping=mapping if feed is not None else None)
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
        frames = []
        removed = False
        held_after_portal_close = False

        def watch_jpegs():
            nonlocal removed, held_after_portal_close
            try:
                if feed is not None and run._portal_result and run._capture.finished and run._encoder.drained:
                    self.assertEqual(ended, [])
                    held_after_portal_close = True
                    self.assertTrue(feed.consume(b'-\t2\n'))
                    return False
                frame = run.take_latest()
                if frame is not None:
                    with Image.open(BytesIO(frame.data)) as bitmap:
                        self.assertEqual(bitmap.size, (57, 33))
                        self.assertEqual(bitmap.mode, 'RGB')
                        # RGB conversion and JPEG may round black to 1; the
                        # unrelated white source is nowhere near this bound.
                        self.assertTrue(all(high <= 4 for _, high in bitmap.getextrema()))
                    self.assertTrue(not frames or frame.sequence > frames[-1])
                    frames.append(frame.sequence)
                    if len(frames) == 3:
                        removed = True
                        if feed is not None:
                            self.assertTrue(feed.consume(b'-\t1\n'))  # Not the selected output.
                            run.stop()
                        else:
                            original.terminate()  # Only the selected synthetic producer.
                return True
            except Exception as error:
                errors.append(error)
                run.stop()
                return False

        if use_pipewire:
            run = DesktopScreenLocalRun(client, provider, 'extend', 'x11:1234', 57, 33, lambda: None, finished,
                                       kde_output_feed=feed)
            portal_owner = run._portal
            watcher = GLib.timeout_add(20, watch_jpegs)
        else:
            portal_owner = run = cast.DesktopScreenCast(client, provider, 'extend', 'x11:1234', lambda: None, ready, finished)
            watcher = None

        def expire():
            errors.append(TimeoutError('isolated ScreenCast did not end before the test deadline'))
            loop.quit()
            return False

        timeout = GLib.timeout_add(6500, expire)
        try:
            run.begin()
            loop.run()
        finally:
            run.stop()
            context = GLib.MainContext.default()
            for source_id in (watcher, timeout):
                if source_id is not None and context.find_source_by_id(source_id) is not None:
                    GLib.source_remove(source_id)
        self.assertEqual(errors, [])
        self.assertEqual(calls, ['CreateSession', 'SelectSources', 'Start', 'OpenPipeWireRemote', 'Close'])
        if use_pipewire:
            self.assertTrue(removed)
            self.assertIsNone(unrelated.poll(), 'Unrelated source must still be available')
            self.assertEqual(held_after_portal_close, observe_output)
            self.assertEqual(ended, [ScreenRunCleanup(True, True, True, virtual_start_submitted=True,
                                                      virtual_output_removed=observe_output)])
            self.assertFalse(run.ready)
            self.assertIsNone(run.take_latest())
            return
        self.assertEqual(selected, [cast.ScreenCastTarget('extend', 54, 903)])
        self.assertEqual(ended, [True])
        fd, data, inherited = borrowed[0]
        self.assertEqual((data, inherited), (b'portal-test-fd', False))
        with self.assertRaises(OSError):
            os.fstat(fd)


if __name__ == '__main__':
    unittest.main()
