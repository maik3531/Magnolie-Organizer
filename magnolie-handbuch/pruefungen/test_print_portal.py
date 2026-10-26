"""Real private D-Bus portal protocol, FD passing and cancellation (#236)."""
import os
from pathlib import Path
import sys

os.environ["NO_AT_BRIDGE"] = "1"
os.environ["GIO_USE_VFS"] = "local"
os.environ["GSETTINGS_BACKEND"] = "memory"
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk
import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_print_portal import PortalPrint, BUS, PATH, INTERFACE, REQUEST

XML = """<node><interface name='org.freedesktop.portal.Print'>
<method name='PreparePrint'><arg type='s' direction='in'/><arg type='s' direction='in'/>
<arg type='a{sv}' direction='in'/><arg type='a{sv}' direction='in'/><arg type='a{sv}' direction='in'/><arg type='o' direction='out'/></method>
<method name='Print'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='h' direction='in'/>
<arg type='a{sv}' direction='in'/><arg type='o' direction='out'/></method>
</interface><interface name='org.freedesktop.portal.Request'><method name='Close'/>
<signal name='Response'><arg type='u'/><arg type='a{sv}'/></signal></interface></node>"""


@pytest.fixture
def service():
    bus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
    bus.up()
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    server = Gio.DBusConnection.new_for_address_sync(bus.get_bus_address(), flags, None, None)
    client = Gio.DBusConnection.new_for_address_sync(bus.get_bus_address(), flags, None, None)
    server.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
        GLib.Variant("(su)", (BUS, 0)), GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 1000, None)
    info = Gio.DBusNodeInfo.new_for_xml(XML)
    state = {"printed": [], "closed": [], "requests": [], "mode": "normal"}
    registrations = []
    def close_request(_connection, _sender, path, _interface, _method, _parameters, invocation):
        state["closed"].append(path)
        invocation.return_value(None)
    def method(connection, sender, _path, _interface, name, parameters, invocation):
        try:
            options = parameters.get_child_value(4 if name == "PreparePrint" else 3)
            token = options.lookup_value("handle_token", GLib.VariantType.new("s")).get_string()
            handle = "/org/freedesktop/portal/desktop/request/" + sender.lstrip(":").replace(".", "_") + "/" + token
            registrations.append(server.register_object(handle, info.lookup_interface(REQUEST), close_request, None, None))
            assert options.lookup_value("supported_output_file_formats", GLib.VariantType.new("as")).unpack() == ["pdf"]
            state["requests"].append(name)
            if name == "PreparePrint":
                reply = {"settings": parameters.get_child_value(2), "page-setup": parameters.get_child_value(3)}
                if state["mode"] != "incomplete":
                    reply["token"] = GLib.Variant("u", 42)
            else:
                assert options.lookup_value("token", GLib.VariantType.new("u")).get_uint32() == 42
                index = parameters.get_child_value(2).get_handle()
                descriptor = invocation.get_message().get_unix_fd_list().get(index)
                with os.fdopen(descriptor, "rb") as stream:
                    state["printed"].append(stream.read(65536))
                reply = {}
            invocation.return_value(GLib.Variant("(o)", (handle,)))
            def respond():
                connection.emit_signal(sender, handle, REQUEST, "Response", GLib.Variant("(ua{sv})", (0, reply)))
                return False
            if state["mode"] == "late":
                GLib.timeout_add(100, respond)
            else:
                GLib.idle_add(respond)
        except Exception as error:
            invocation.return_dbus_error("org.example.InvalidFixture", str(error))
    registrations.append(server.register_object(PATH, info.lookup_interface(INTERFACE), method, None, None))
    try:
        yield client, state
    finally:
        client.close_sync(None)
        for registration in registrations:
            server.unregister_object(registration)
        server.close_sync(None)
        bus.down()


def settings():
    value = Gtk.PrintSettings()
    value.set_n_copies(2)
    value.set_number_up(2)
    setup = Gtk.PageSetup()
    setup.set_orientation(Gtk.PageOrientation.LANDSCAPE)
    return value, setup


def test_prepare_preserves_settings_and_print_passes_original_pdf_descriptor(service, tmp_path):
    connection, state = service
    source = tmp_path / "owned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(842, 595)
    writer.write(source)
    portal = PortalPrint(None, "Owned synthetic PDF", connection)
    loop = GLib.MainLoop()
    results = []
    def printed(ok, result):
        results.append((ok, result))
        loop.quit()
    def prepared(ok, result):
        assert ok, result
        assert result["settings"].get_n_copies() == 2
        assert result["settings"].get_number_up() == 2
        assert result["page_setup"].get_orientation() == Gtk.PageOrientation.LANDSCAPE
        portal.send(source, printed)
    portal.prepare(*settings(), prepared)
    timeout = GLib.timeout_add_seconds(5, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timeout)
    portal.close()
    assert results == [(True, {"stage": "portal_accepted"})]
    assert state["printed"] == [source.read_bytes()]
    assert state["requests"] == ["PreparePrint", "Print"]


def test_cancel_closes_request_and_late_acceptance_cannot_start_printing(service):
    connection, state = service
    state["mode"] = "late"
    portal = PortalPrint(None, "Owned cancellation", connection)
    loop, results = GLib.MainLoop(), []
    portal.prepare(*settings(), lambda ok, result: results.append((ok, result)))
    GLib.timeout_add(30, lambda: (portal.cancel(), False)[1])
    GLib.timeout_add(250, lambda: (loop.quit(), False)[1])
    loop.run()
    assert results == [(False, "cancelled")]
    assert len(state["closed"]) == 1
    assert state["requests"] == ["PreparePrint"] and not state["printed"]


def test_incomplete_prepare_reply_never_becomes_print_permission(service):
    connection, state = service
    state["mode"] = "incomplete"
    portal = PortalPrint(None, "Owned invalid reply", connection)
    loop, results = GLib.MainLoop(), []
    portal.prepare(*settings(), lambda ok, result: (results.append((ok, result)), loop.quit()))
    timeout = GLib.timeout_add_seconds(5, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timeout)
    portal.close()
    assert len(results) == 1 and results[0][0] is False
    assert "Incomplete" in results[0][1]
    assert not state["printed"]
