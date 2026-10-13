#!/usr/bin/env python3
"""Real Gio/D-Bus media probe; run ONLY inside a fresh dbus-run-session."""
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from gi.repository import Gio, GLib
from magnolie_kdeconnect import KDEConnectNativeBackend
from magnolie_kde_mpris import DesktopMpris


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus', 'ListNames', None, GLib.VariantType.new('(as)'),
        Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
    assert all(name == 'org.freedesktop.DBus' or name.startswith(':') for name in names), 'Fresh isolated D-Bus required'
    calls = []
    device = 'a' * 32
    media = dict(playerList=['Fixture'], player='Fixture', title='Native fixture', artist='', album='',
                 position=1000, length=20000, volume=50, canSeek=True, isPlaying=False)
    local = dict(CanControl=True, CanPlay=True, CanPause=True, CanSeek=True,
        CanGoNext=True, CanGoPrevious=True, PlaybackStatus='Playing', Volume=0.5, Position=3000000,
        Metadata={'xesam:title': GLib.Variant('s', 'Local fixture'),
            'xesam:artist': GLib.Variant('as', ['Artist']),
            'mpris:length': GLib.Variant('x', 20000000),
            'mpris:trackid': GLib.Variant('o', '/fixture/track')})
    device_props = dict(isPaired=True, isReachable=True, type='phone', name='Fixture phone')
    registrations = []

    def register(path, name, methods, props=None):
        props = props or {}
        xml = '<node><interface name="' + name + '">' + methods
        for key, signature in props.items():
            xml += '<property name="' + key + '" type="' + signature + '" access="readwrite"/>'
        xml += '</interface></node>'
        info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        values = local if name == 'org.mpris.MediaPlayer2.Player' else media if name.endswith('.mprisremote') else device_props

        def method(connection, sender, object_path, interface, member, parameters, invocation):
            args = parameters.unpack(); calls.append((name, member, args))
            if member == 'devices': invocation.return_value(GLib.Variant('(as)', ([device],)))
            elif member == 'hasPlugin': invocation.return_value(GLib.Variant('(b)', (args[0] in ('kdeconnect_sms', 'kdeconnect_mprisremote'),)))
            else: invocation.return_value(GLib.Variant('()', ()))

        def get_property(connection, sender, object_path, interface, prop):
            return GLib.Variant(props[prop], values[prop])

        def set_property(connection, sender, object_path, interface, prop, value):
            calls.append((name, 'Set', (prop, value.unpack())))
            values[prop] = value.unpack(); return True

        registrations.append(bus.register_object(path, info, method, get_property, set_property))

    register('/modules/kdeconnect', 'org.kde.kdeconnect.daemon',
        '<method name="devices"><arg type="b" direction="in"/><arg type="b" direction="in"/><arg type="as" direction="out"/></method>')
    register('/modules/kdeconnect/devices/' + device, 'org.kde.kdeconnect.device',
        '<method name="hasPlugin"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>',
        dict(isPaired='b', isReachable='b', type='s', name='s'))
    register('/modules/kdeconnect/devices/' + device + '/mprisremote', 'org.kde.kdeconnect.device.mprisremote',
        '<method name="requestPlayerList"/><method name="sendAction"><arg type="s" direction="in"/></method>'
        '<method name="seek"><arg type="i" direction="in"/></method>',
        dict(playerList='as', player='s', title='s', artist='s', album='s', position='i', length='i', volume='i', canSeek='b', isPlaying='b'))
    register('/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player',
        '<method name="Play"/><method name="Seek"><arg type="x" direction="in"/></method>'
        '<method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>',
        dict(CanControl='b', CanPlay='b', CanPause='b', CanSeek='b', CanGoNext='b', CanGoPrevious='b',
            PlaybackStatus='s', Volume='d', Position='x', Metadata='a{sv}'))
    for name in ('org.kde.kdeconnect', 'org.mpris.MediaPlayer2.fixture'):
        result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'RequestName', GLib.Variant('(su)', (name, 0)), GLib.VariantType.new('(u)'),
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        assert result == 1
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True); thread.start()
    try:
        native = KDEConnectNativeBackend(bus, Gio, GLib)
        assert native.media_devices()['devices'] == [{'device_id': device, 'device_name': 'Fixture phone'}]
        status = native.media_status(device)
        assert status['players'][0]['title'] == 'Native fixture'
        native.media_command(device, status['token'], 'Fixture', 'Play')
        native.media_command(device, status['token'], 'Fixture', 'volume', 25)
        native.media_command(device, status['token'], 'Fixture', 'position', 5000)
        assert media['volume'] == 25 and media['position'] == 5000
        assert ('org.kde.kdeconnect.device.mprisremote', 'sendAction', ('Play',)) in calls
        desktop = DesktopMpris(bus, Gio, GLib)
        assert desktop.receive({'requestPlayerList': True})[0]['playerList'] == ['org.mpris.MediaPlayer2.fixture']
        state = desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'requestNowPlaying': True})[0]
        assert state['title'] == 'Local fixture' and state['pos'] == 3000 and state['length'] == 20000
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'SetPosition': 5000})
        assert ('org.mpris.MediaPlayer2.Player', 'SetPosition', ('/fixture/track', 5000000)) in calls
        desktop.receive({'player': 'org.mpris.MediaPlayer2.fixture', 'Seek': -1000000})
        assert ('org.mpris.MediaPlayer2.Player', 'Seek', (-1000000,)) in calls
        print('PASS: isolated real Gio/D-Bus native remote controls and local MPRIS; position ms/us, volume, player list, existing unique owners')
    finally:
        loop.quit(); thread.join(1)
        for registration in registrations: bus.unregister_object(registration)


if __name__ == '__main__':
    main()
