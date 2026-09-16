"""Synthetic native D-Bus contract; never contacts a real phone or desktop bus."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_kdeconnect as kde
import magnolie_setup_state as setup
import magnolie_hintergrund as background


class Variant:
    def __init__(self, signature, value):
        self.signature, self.value = signature, value
    def unpack(self):
        return self.value
    def get_type_string(self):
        return self.signature


GLIB = SimpleNamespace(Variant=Variant, VariantType=SimpleNamespace(new=lambda value: value))


class Bus:
    def __init__(self):
        self.owner = ':1.10'
        self.ids = ['a' * 32]
        self.props = {'a' * 32: {'isPaired': True, 'isReachable': True, 'type': 'phone', 'name': 'Phone'}}
        self.sms = True
        self.calls = []
        self.running = True
        self.activatable = ['org.kde.kdeconnect']
        self.fail_send = False
    def call_sync(self, owner, path, interface, method, parameters, reply, flags, timeout, cancellable):
        assert flags == 4 and 0 < timeout <= 1500
        args = parameters.unpack() if parameters else ()
        self.calls.append((owner, path, interface, method, args))
        if method == 'GetNameOwner':
            if not self.running:
                raise RuntimeError('no owner')
            return Variant('(s)', (self.owner,))
        if method == 'NameHasOwner':
            return Variant('(b)', (self.running,))
        if method == 'ListActivatableNames':
            return Variant('(as)', (self.activatable,))
        assert owner == self.owner
        if method == 'devices':
            assert args == (False, True)
            return Variant('(as)', (self.ids,))
        if method == 'GetAll':
            return Variant('(a{sv})', (self.props[path.rsplit('/', 1)[1]],))
        if method == 'hasPlugin':
            assert args == ('kdeconnect_sms',)
            return Variant('(b)', (self.sms,))
        assert method == 'sendSms', method
        if self.fail_send:
            raise TimeoutError('submission may have occurred')
        return Variant('()', ())


def native(bus=None):
    bus = bus or Bus()
    gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NO_AUTO_START=4),
        BusType=SimpleNamespace(SESSION=0), bus_get_sync=lambda *_: bus)
    return kde.KDEConnectNativeBackend(bus, gio, GLIB), gio


def test_native_factory_never_binds_starts_daemon_or_creates_identity(tmp_path):
    backend, gio = native()
    with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio, GLib=GLIB)}), \
            patch.object(kde, 'KDEConnectSMSBackend', side_effect=AssertionError('direct backend')):
        selected = kde.create_backend(str(tmp_path / 'identity'))
        assert selected.native and selected.start()
        assert selected.status()['service_running']
        assert not list(tmp_path.iterdir())
        selected.stop()
        assert not any(c[3] in ('StartServiceByName', 'requestPairing', 'setPluginEnabled') for c in backend.bus.calls)
        backend.bus.running = False
        assert kde.create_backend(str(tmp_path)).native


def test_filtered_bus_and_occupied_udp_still_do_not_compete(tmp_path):
    backend, gio = native()
    backend.bus.running = False
    backend.bus.activatable = []
    with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio, GLib=GLIB)}), \
            patch('builtins.open', side_effect=lambda *_a, **_k: io.StringIO('header\n 0: 00000000:06B4\n')), \
            patch.object(kde, 'KDEConnectSMSBackend', side_effect=AssertionError('direct backend')):
        selected = kde.create_backend(str(tmp_path))
        assert selected.start() is True
        assert selected.status()['reason'] == 'native_service_unavailable'


def test_direct_remains_available_when_no_native_service_or_port_owner(tmp_path):
    backend, gio = native()
    backend.bus.running = False
    backend.bus.activatable = []
    with patch.dict(sys.modules, {'gi.repository': SimpleNamespace(Gio=gio, GLib=GLIB)}), \
            patch('builtins.open', side_effect=lambda *_a, **_k: io.StringIO('header\n')), \
            patch.object(kde, 'KDEConnectSMSBackend') as direct:
        assert kde.create_backend(str(tmp_path)) is direct.return_value
        direct.assert_called_once_with(str(tmp_path), device_name=None, callback=None)


def test_trust_identity_dedup_and_explicit_sms_selection():
    backend, _ = native()
    bus = backend.bus
    bus.ids = ['a' * 32, 'a' * 32, '../../other', 'b' * 32, 'c' * 32, 'd' * 32]
    bus.props.update({'b' * 32: dict(bus.props['a' * 32]),
                      'c' * 32: dict(bus.props['a' * 32], isPaired=False),
                      'd' * 32: dict(bus.props['a' * 32], type='desktop')})
    status = backend.status()
    assert status['device_count'] == 2 and not status['available']
    assert len(status['devices']) == 2  # Same names are NOT identity equivalence.
    with pytest.raises(kde.ProtocolError):
        backend.send_sms('+49123456789', 'Hi')
    result = backend.send_sms('+49123456789', 'Hi', 'b' * 32)
    assert result['state'] == 'queued' and result['device_id'] == 'b' * 32
    sends = [c for c in bus.calls if c[3] == 'sendSms']
    assert len(sends) == 1 and sends[0][0] == ':1.10'
    assert sends[0][4][0][0].signature == '(s)'
    assert sends[0][4][0][0].unpack() == ('+49123456789',)
    assert sends[0][4][1:] == ('Hi', [], -1)


@pytest.mark.parametrize('change', ['unpaired', 'offline', 'plugin', 'owner'])
def test_native_send_revalidates_and_never_retries(change):
    backend, _ = native()
    assert backend.status()['available']
    if change == 'unpaired':
        backend.bus.props['a' * 32]['isPaired'] = False
    elif change == 'offline':
        backend.bus.props['a' * 32]['isReachable'] = False
    elif change == 'plugin':
        backend.bus.sms = False
    else:
        backend._owner = Mock(side_effect=[':1.10', ':1.11'])
    with pytest.raises(kde.ProtocolError):
        backend.send_sms('+49123456789', 'Hi')
    assert not any(c[3] == 'sendSms' for c in backend.bus.calls)
    backend, _ = native()
    backend.bus.fail_send = True
    with pytest.raises(TimeoutError):
        backend.send_sms('+49123456789', 'Hi')
    assert sum(c[3] == 'sendSms' for c in backend.bus.calls) == 1


def test_native_cannot_apply_incoming_data_even_if_permissions_were_saved(tmp_path):
    backend, _ = native()
    callback = backend.callback = Mock()
    with patch('builtins.open', side_effect=AssertionError('file access')):
        for flags in ({'file_enabled': True}, {'clipboard_enabled': True, 'clipboard_mode': 'automatic'}):
            with pytest.raises(kde.ProtocolError, match='cannot enforce Magnolie approvals'):
                backend.configure_receive(device_id='a' * 32, download_directory=str(tmp_path), **flags)
        with pytest.raises(kde.ProtocolError):
            backend.accept_receive('unapproved', str(tmp_path))
        for operation in (lambda: backend.begin_pairing('a' * 32),
                          lambda: backend.complete_pairing('a' * 32),
                          lambda: backend.confirm_pairing(True)):
            with pytest.raises(kde.ProtocolError):
                operation()
    assert not backend.reject_receive('unapproved')
    assert not any(backend.status()['capabilities'][name] for name in
                   ('clipboard_receive', 'file_receive', 'sms_receive', 'sms_history', 'pairing'))
    assert backend.status()['receive']['proposals'] == []
    callback.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_native_setup_selects_trusted_ids_without_pairing_or_notes_changes(tmp_path):
    backend, _ = native()
    backend.bus.ids.append('b' * 32)
    backend.bus.props['b' * 32] = dict(backend.bus.props['a' * 32])
    notes = Mock()
    notes.report.return_value = {'peers': []}
    services = setup.SetupPhoneServices(lambda: str(tmp_path), lambda: 'Test',
                                       kde=backend, phone=notes, borrowed=True)
    result = services.connect('kdeconnect', lambda prompt: prompt['devices'][1]['uid'])
    assert result['deviceId'] == 'b' * 32 and result['authenticated']
    assert services.connected() == ['kdeconnect']
    notes.start.assert_not_called()
    notes.stop.assert_not_called()
    notes.open_pairing.assert_not_called()
    assert not any(c[3] in ('requestPairing', 'setPluginEnabled') for c in backend.bus.calls)
    saved = []
    services._commit_startup_local(['kdeconnect'],
        settings_getter=lambda: background.normalize_settings({}), settings_setter=saved.append,
        start_service=False)
    assert saved[0]['enabled'] and saved[0]['autostart']
    assert not any(saved[0]['permissions'].values())


def test_native_capabilities_are_disabled_and_explained_in_existing_settings():
    text = (Path(__file__).resolve().parents[1] / 'web/anwendung.js').read_text()
    assert 'const empfangMoeglich = !nativesKde &&' in text
    assert '} else if (!nativesKde) {' in text
    assert kde.NATIVE_KDE_LIMIT in text and kde.NATIVE_KDE_NOTICE in text


def test_native_explanations_have_manual_translations_in_all_twenty_languages(tmp_path):
    import gettext
    import subprocess
    root = Path(__file__).resolve().parents[1]
    languages = (root / 'po/LINGUAS').read_text().split()
    assert len(languages) == 19  # English is the source language.
    for language in languages:
        compiled = tmp_path / (language + '.mo')
        subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(compiled),
                        str(root / 'po' / (language + '.po'))], check=True)
        with compiled.open('rb') as source:
            catalog = gettext.GNUTranslations(source)
        for message in (kde.NATIVE_KDE_NOTICE, kde.NATIVE_KDE_LIMIT, kde.NATIVE_KDE_UNAVAILABLE):
            assert catalog.gettext(message) and catalog.gettext(message) != message, (language, message)


def test_activation_token_is_owner_id_bound_one_shot_and_thread_local():
    notification = Mock()
    notification.get_property.return_value = 42
    notification.get_activation_token.return_value = None
    proxy = Mock()
    proxy.get_name_owner.return_value = ':1.8'
    activation = background.NotificationActivation.__new__(background.NotificationActivation)
    activation.notification, activation.proxy, activation.handler = notification, proxy, 1
    activation.token = activation.owner = ''
    activation.server_owner, activation.invoked = ':1.8', False
    for sender, ident in ((':1.spoof', 42), (':1.8', 43)):
        activation._signal(proxy, sender, 'ActivationToken', Variant('(us)', (ident, 'bad')))
        assert not activation.token
    activation._signal(proxy, ':1.8', 'ActivationToken', Variant('(us)', (42, 'valid-token')))
    observed = []
    def callback():
        observed.append(background.notification_launch_environment().get('XDG_ACTIVATION_TOKEN'))
        assert background.notification_launch_environment()['DESKTOP_STARTUP_ID'] == 'valid-token'
        import threading
        thread = threading.Thread(target=lambda: observed.append(background.notification_activation_token()))
        thread.start()
        thread.join()
    with patch.dict(background.os.environ, {'XDG_ACTIVATION_TOKEN': 'stale-inherited', 'DESKTOP_STARTUP_ID': 'stale'}):
        activation.invoke(callback)
        activation.invoke(callback)
        assert 'XDG_ACTIVATION_TOKEN' not in background.notification_launch_environment()
        assert 'DESKTOP_STARTUP_ID' not in background.notification_launch_environment()
    assert observed == ['valid-token', '']
    proxy.disconnect.assert_called_once_with(1)


def test_activation_owner_restart_discards_old_token_even_with_libnotify_getter():
    activation = background.NotificationActivation.__new__(background.NotificationActivation)
    activation.notification = Mock(get_activation_token=lambda: 'old-token')
    activation.proxy = Mock(get_name_owner=lambda: ':1.new')
    activation.handler, activation.invoked = 1, False
    activation.token, activation.owner, activation.server_owner = 'old-token', ':1.old', ':1.old'
    activation._signal(activation.proxy, ':1.new', 'ActivationToken', Variant('(us)', (42, 'foreign-token')))
    assert activation.token == 'old-token'
    observed = []
    activation.invoke(lambda: observed.append(background.notification_activation_token()))
    assert observed == ['']


def test_notification_capability_failure_and_explicit_refusal_are_not_success():
    notify = Mock()
    notify.init.return_value = True
    notify.get_server_caps.side_effect = RuntimeError('no service')
    with patch.dict(sys.modules, {'gi': SimpleNamespace(require_version=lambda *_: None),
                                  'gi.repository': SimpleNamespace(Notify=notify)}):
        notifications = background.NativeNotifications(GLIB)
    assert not notifications.available and not notifications.actions_supported
    notify.get_server_caps.side_effect = None
    notify.get_server_caps.return_value = ['actions']
    notify.Notification.new.return_value.show.return_value = False
    with patch.dict(sys.modules, {'gi': SimpleNamespace(require_version=lambda *_: None),
                                  'gi.repository': SimpleNamespace(Notify=notify)}):
        notifications = background.NativeNotifications(GLIB)
        assert notifications.show('test', 'body', key='test') is False
    assert not notifications.notifications and not notifications.keyed_notifications


def test_real_private_dbus_wire_contract():
    import subprocess
    result = subprocess.run(['dbus-run-session', '--', '/usr/bin/python3', __file__, '--private-dbus'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PRIVATE DBUS PASS' in result.stdout


def test_single_instance_uses_gtk_platform_activation_without_changing_routing():
    import ast
    text = (Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer').read_text()
    function = next(node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)
                    and node.name == 'einzelinstanz_anmelden')
    for remote in (False, True):
        app = Mock()
        app.get_is_remote.return_value = remote
        gtk = SimpleNamespace(Application=SimpleNamespace(new=Mock(return_value=app)))
        gio = SimpleNamespace(ApplicationFlags=SimpleNamespace(FLAGS_NONE=0), SimpleAction=Mock())
        namespace = {'Gtk': gtk, 'Gio': gio, 'GLib': GLIB, 'debug_notiz': lambda *_a, **_k: None}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<native-singleton>', 'exec'), namespace)
        assert namespace['einzelinstanz_anmelden']('io.test.Magnolie', lambda: None) == (app, remote)
        gtk.Application.new.assert_called_once_with('io.test.Magnolie', 0)
        assert app.activate.call_count == int(remote)
        assert app.hold.call_count == int(not remote)
    assert 'fenster.set_application(anwendung)' in text
    assert 'fenster.set_startup_id(startup_token)' in text


def test_gui_owned_and_recovery_paths_use_the_same_native_selector(tmp_path):
    import ast
    import os
    import threading
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer').read_text())
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == 'KDEConnectSMSBackend' for n in ast.walk(tree))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_kdeconnect_backend')
    backend, _ = native()
    factory = Mock(return_value=backend)
    namespace = {'os': os, '_KDECONNECT_BACKEND': None, '_KDECONNECT_SPERRE': threading.Lock(),
        'daemon_available': lambda: False, 'background_daemon_status': lambda: 'stopped',
        'daten_verzeichnis': lambda: str(tmp_path), 'create_backend': factory}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<native-gui-selector>', 'exec'), namespace)
    callback = Mock()
    assert namespace['_kdeconnect_backend'](callback) is backend
    assert namespace['_kdeconnect_backend']() is backend
    factory.assert_called_once_with(str(tmp_path / 'kdeconnect'), callback=callback)


if __name__ == '__main__':
    import threading
    from gi.repository import Gio, GLib
    assert sys.argv[1:] == ['--private-dbus']
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
        'RequestName', GLib.Variant('(su)', ('org.kde.kdeconnect', 0)), None, Gio.DBusCallFlags.NONE, 1000, None)
    xml = '''<node>
    <interface name="org.kde.kdeconnect.daemon"><method name="devices">
      <arg type="b" direction="in"/><arg type="b" direction="in"/><arg type="as" direction="out"/>
    </method></interface>
    <interface name="org.kde.kdeconnect.device">
      <property name="isPaired" type="b" access="read"/>
      <property name="isReachable" type="b" access="read"/>
      <property name="type" type="s" access="read"/>
      <property name="name" type="s" access="read"/>
      <method name="hasPlugin"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
    </interface>
    <interface name="org.kde.kdeconnect.device.sms"><method name="sendSms">
      <arg type="av" direction="in"/><arg type="s" direction="in"/>
      <arg type="av" direction="in"/><arg type="x" direction="in"/>
    </method></interface></node>'''
    interfaces = Gio.DBusNodeInfo.new_for_xml(xml).interfaces
    paired = [True]
    sent = []
    def method(connection, sender, path, interface, name, parameters, invocation):
        if name == 'devices':
            assert parameters.unpack() == (False, True)
            result = GLib.Variant('(as)', (['a' * 32, 'a' * 32, '../invalid'],))
        elif name == 'hasPlugin':
            assert parameters.unpack() == ('kdeconnect_sms',)
            result = GLib.Variant('(b)', (True,))
        else:
            assert name == 'sendSms' and parameters.get_type_string() == '(avsavx)'
            sent.append(parameters.unpack())
            result = GLib.Variant('()', ())
        invocation.return_value(result)
    def prop(connection, sender, path, interface, name):
        values = {'isPaired': ('b', paired[0]), 'isReachable': ('b', True),
                  'name': ('s', 'Synthetic phone'), 'type': ('s', 'phone')}
        return GLib.Variant(*values[name])
    path = '/modules/kdeconnect/devices/' + 'a' * 32
    registrations = [bus.register_object('/modules/kdeconnect', interfaces[0], method, None, None),
                     bus.register_object(path, interfaces[1], method, prop, None),
                     bus.register_object(path + '/sms', interfaces[2], method, None, None)]
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run)
    thread.start()
    original_socket = kde.socket.socket
    def local_socket(family=kde.socket.AF_INET, *args, **kwargs):
        # Recent PyGObject uses a Unix socketpair for its signal wakeup pipe.
        assert family == kde.socket.AF_UNIX, 'network socket'
        return original_socket(family, *args, **kwargs)
    try:
        with patch.object(kde.socket, 'socket', side_effect=local_socket):
            backend = kde.create_backend('/must-not-create')
            assert backend.native and backend.start() and backend.status()['device_count'] == 1
            backend.send_sms('+49123456789', 'Synthetic')
            assert sent == [([('+49123456789',)], 'Synthetic', [], -1)], sent
            callback = backend.callback = Mock()
            for channel in ('clipboard', 'share'):
                bus.emit_signal(None, path + '/' + channel, 'org.kde.kdeconnect.device.' + channel,
                                'received', GLib.Variant('(s)', ('unapproved synthetic data',)))
            bus.flush_sync(None)
            with pytest.raises(kde.ProtocolError):
                backend.configure_receive(clipboard_enabled=True, file_enabled=True)
            paired[0] = False
            assert not backend.status()['available']
            with pytest.raises(kde.ProtocolError):
                backend.send_sms('+49123456789', 'Must not send')
            assert len(sent) == 1
            callback.assert_not_called()
            backend.stop()
        print('PRIVATE DBUS PASS: native wire signature, deduplication, trust revocation, no inbound application')
    finally:
        loop.quit()
        thread.join(2)
        for registration in registrations:
            bus.unregister_object(registration)
