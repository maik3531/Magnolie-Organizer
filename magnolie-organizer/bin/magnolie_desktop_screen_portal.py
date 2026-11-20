"""Passive Linux provider discovery for separate desktop-to-phone modes (#245).

Run on a worker with the caller's existing session bus, not on the GTK thread.
This never starts a portal, requests consent, creates an output or grants input.
"""

from dataclasses import dataclass

from gi.repository import Gio, GLib


_DESTINATION = 'org.freedesktop.portal.Desktop'
_PATH = '/org/freedesktop/portal/desktop'
_PROPERTIES = 'org.freedesktop.DBus.Properties'
_DBUS = 'org.freedesktop.DBus'
_QUERY_MS = 350
_UNSIGNED = GLib.VariantType.new('u')
MONITOR, WINDOW, VIRTUAL = 1, 2, 4
KEYBOARD, POINTER, TOUCHSCREEN = 1, 2, 4


@dataclass(frozen=True)
class DesktopScreenProvider:
    owner: str | None = None
    mirror_sources: int = 0
    extended_output: bool = False
    input_devices: int = 0


def read_desktop_screen_provider(bus, cancellable=None):
    """Read-only candidates, pinned to one unique owner for this observation.

    A subsequent native operation must recheck its own session/owner and obtain
    the real permission. These values cannot authorize a Start or input.
    """
    unavailable = DesktopScreenProvider()
    if bus is None:
        return unavailable

    def call(destination, path, interface, method, param, result):
        return bus.call_sync(destination, path, interface, method,
                             GLib.Variant('(s)', (param,)), GLib.VariantType.new(result),
                             Gio.DBusCallFlags.NO_AUTO_START, _QUERY_MS, cancellable)

    def current_owner():
        result = call(_DBUS, '/org/freedesktop/DBus', _DBUS, 'GetNameOwner', _DESTINATION, '(s)')
        owner, = result.unpack()
        return owner if owner.startswith(':') else None

    def read_interface(owner, kind, capability):
        try:
            result = call(owner, _PATH, _PROPERTIES, 'GetAll', f'org.freedesktop.portal.{kind}', '(a{sv})')
            fields = result.get_child_value(0)
            values = [fields.lookup_value(key, _UNSIGNED) for key in ('version', capability)]
            if all(value is not None for value in values):
                return tuple(value.unpack() for value in values)
        except GLib.Error:
            pass
        return 0, 0

    try:
        owner = current_owner()
        if owner is None:
            return unavailable
        screen_version, sources = read_interface(owner, 'ScreenCast', 'AvailableSourceTypes')
        input_version, devices = read_interface(owner, 'RemoteDesktop', 'AvailableDeviceTypes')
        if current_owner() != owner or (cancellable is not None and cancellable.is_cancelled()):
            return unavailable
    except GLib.Error:
        return unavailable

    return DesktopScreenProvider(owner,
                                 sources & (MONITOR | WINDOW) if screen_version >= 1 else 0,
                                 screen_version >= 3 and bool(sources & VIRTUAL),
                                 devices & (KEYBOARD | POINTER | TOUCHSCREEN) if input_version >= 1 else 0)
