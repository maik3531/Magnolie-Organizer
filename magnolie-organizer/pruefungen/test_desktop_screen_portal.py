"""Passive portal probing with actual GLib variants, no session creation."""

import sys
import unittest
from pathlib import Path

from gi.repository import Gio, GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_desktop_screen_portal import DesktopScreenProvider, read_desktop_screen_provider


def uint(value):
    return GLib.Variant('u', value)


class Bus:
    def __init__(self, *, names=(':1.9', ':1.9'), screen=None, remote=None):
        self.names = iter(names)
        self.fields = {'ScreenCast': screen, 'RemoteDesktop': remote}
        self.calls = []

    def call_sync(self, destination, path, interface, member, parameters, result, flags, timeout, cancellable):
        name, = parameters.unpack()
        self.calls.append((destination, path, interface, member, name))
        assert flags == Gio.DBusCallFlags.NO_AUTO_START and 0 < timeout <= 350
        if member == 'GetNameOwner':
            assert destination == interface == 'org.freedesktop.DBus' and name == 'org.freedesktop.portal.Desktop'
            owner = next(self.names)
            if owner is not None:
                return GLib.Variant('(s)', (owner,))
        else:
            assert destination == ':1.9' and path == '/org/freedesktop/portal/desktop'
            assert member == 'GetAll' and interface == 'org.freedesktop.DBus.Properties'
            fields = self.fields[name.rsplit('.', 1)[-1]]
            if fields is not None:
                return GLib.Variant('(a{sv})', (fields,))
        raise GLib.Error('controlled unavailable interface or owner')


class TestDesktopScreenPortal(unittest.TestCase):
    def test_missing_portal_never_activates_service(self):
        bus = Bus(names=(None,))
        self.assertEqual(read_desktop_screen_provider(bus), DesktopScreenProvider())
        self.assertEqual(len(bus.calls), 1)

    def test_existing_screen_without_virtual_does_not_grant_input(self):
        bus = Bus(screen={'version': uint(5), 'AvailableSourceTypes': uint(3)})
        self.assertEqual(read_desktop_screen_provider(bus), DesktopScreenProvider(':1.9', 3, False, 0))

    def test_virtual_is_not_fallback_to_regular_screen(self):
        for version, candidate in ((2, False), (3, True)):
            with self.subTest(version=version):
                bus = Bus(screen={'version': uint(version), 'AvailableSourceTypes': uint(4)})
                self.assertEqual(read_desktop_screen_provider(bus), DesktopScreenProvider(':1.9', 0, candidate, 0))

    def test_remote_devices_and_unknown_bits_do_not_imply_viewing(self):
        bus = Bus(remote={'version': uint(2), 'AvailableDeviceTypes': uint(0x80000002)})
        self.assertEqual(read_desktop_screen_provider(bus), DesktopScreenProvider(':1.9', 0, False, 2))

    def test_wrong_signature_and_missing_fields_fail_closed_separately(self):
        bus = Bus(screen={'version': uint(5), 'AvailableSourceTypes': GLib.Variant('i', 7)},
                  remote={'AvailableDeviceTypes': uint(7)})
        self.assertEqual(read_desktop_screen_provider(bus), DesktopScreenProvider(':1.9'))

    def test_replaced_owner_or_cancelled_probe_has_no_candidates(self):
        fields = {'version': uint(5), 'AvailableSourceTypes': uint(7)}
        self.assertEqual(read_desktop_screen_provider(Bus(names=(':1.9', ':1.10'), screen=fields)), DesktopScreenProvider())
        cancel = Gio.Cancellable()
        cancel.cancel()
        self.assertEqual(read_desktop_screen_provider(Bus(screen=fields), cancel), DesktopScreenProvider())


if __name__ == '__main__':
    unittest.main()
