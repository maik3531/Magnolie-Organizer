"""Run only in an isolated software Xvfb/DBus session. Synthetic, inert transport."""
import ast
import json
import mimetypes
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, WebKit2

root = Path(__file__).resolve().parents[1]
web = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "web"
Gtk.init([])


def wait(ms):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


# Exercise the actual native alert surface, not a mock GTK widget.
tree = ast.parse((root / "bin/magnolie-organizer").read_text())
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "magnolie_meldung" or
    isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MAGNOLIE_MELDUNG_STIL" for target in node.targets)]
native = dict(Gtk=Gtk, Gdk=Gdk, GdkPixbuf=GdkPixbuf, GLib=GLib, _=lambda text: text,
    anzeige_bereit=lambda: True, _meldung_platzieren=lambda window: None, FENSTER_TITEL="Synthetic call alert")
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "native-call-panel", "exec"), native)
photo = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
photo.fill(0x886633ff)
saved, photo_bytes = photo.save_to_bufferv("png", [], [])
assert saved
mapping_latencies = []
for action in ("answer", "reject", "mute", "terminal", "stale-before-map"):
    captured = []
    mapped = []
    ringing = [True]
    started = time.monotonic()
    assert native["magnolie_meldung"]("Incoming call", "Synthetic local contact", 60, False,
        eigene_schleife=False, initialen="SC", foto=bytes(photo_bytes), gueltig=lambda: ringing[0],
        bei_anzeigen=lambda: mapped.append(True) or mapping_latencies.append(round((time.monotonic()-started)*1000, 3)) or True,
        aktionen=[("A", "Answer", lambda: captured.append("answer")),
                  ("R", "Reject", lambda: captured.append("reject")),
                  ("M", "Silence this alert", lambda: captured.append("mute"))])
    if action == "stale-before-map":
        ringing[0] = False; wait(400)
        assert not mapped and not any(window.get_visible() for window in Gtk.Window.list_toplevels())
        continue
    wait(100)
    windows = [window for window in Gtk.Window.list_toplevels() if window.get_visible()]
    assert len(windows) == 1 and windows[0].get_mapped()
    assert windows[0].get_style_context().has_class("magnolie-meldung")
    assert mapped == [True]
    def descendants(widget):
        yield widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children(): yield from descendants(child)
    buttons = {widget.get_accessible().get_name(): widget for widget in descendants(windows[0]) if isinstance(widget, Gtk.Button)}
    avatars = [widget.get_pixbuf() for widget in descendants(windows[0]) if isinstance(widget, Gtk.Image)]
    assert len(avatars) == 1 and avatars[0].get_width() == avatars[0].get_height() == 42
    assert {"Answer", "Reject", "Silence this alert"} <= buttons.keys()
    if action == "terminal":
        ringing[0] = False; wait(400); assert not captured
    else:
        buttons[{"answer": "Answer", "reject": "Reject", "mute": "Silence this alert"}[action]].clicked()
        assert captured == [action]
    assert not any(window.get_visible() for window in Gtk.Window.list_toplevels())
print("GTK native compact alert: answer/reject/mute, mapped ACK, stale-before-map and terminal dismissal passed")
print(json.dumps({"fixture_only": True, "gtk_map_ms": mapping_latencies}))

assert native["magnolie_meldung"]("Incoming call", "Unsupported controls", 60, False,
    eigene_schleife=False, aktionen=[("A", "Answer", None), ("R", "Reject", None),
        ("M", "Silence this alert", lambda: None)])
wait(100)
disabled_window = next(window for window in Gtk.Window.list_toplevels() if window.get_visible())
buttons = {widget.get_accessible().get_name(): widget for widget in descendants(disabled_window) if isinstance(widget, Gtk.Button)}
assert not buttons["Answer"].get_sensitive() and not buttons["Reject"].get_sensitive()
assert buttons["Silence this alert"].get_sensitive()
disabled_window.destroy()

context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_display_isolated"):
    getattr(security, method)("magnolie-organizer")


def serve(request):
    name = urlsplit(request.get_uri()).path.lstrip("/")
    if name == "i18n-active.js": name = "i18n/de.js"
    asset = (web / name).resolve()
    if not asset.is_relative_to(web.resolve()) or not asset.is_file():
        request.finish_error(GLib.Error("Missing test asset")); return
    data = asset.read_bytes()
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data), mimetypes.guess_type(name)[0] or "application/octet-stream")


context.register_uri_scheme("magnolie-organizer", serve)
view = WebKit2.WebView.new_with_context(context)
view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
manager = view.get_user_content_manager()
manager.add_script(WebKit2.UserScript.new("""
window.__MAGNOLIE_SPRACHE__ = 'de'; window.__MAGNOLIE_BRUECKE__ = 'calls';
window.callMessages = [];
window.webkit = {messageHandlers: {calls: {postMessage(text) { callMessages.push(JSON.parse(text)); }}}};
""", WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
window = Gtk.Window(title="Synthetic call WebKit test")
window.set_default_size(1000, 700); window.add(view); window.show_all()
loaded = GLib.MainLoop()
view.connect("load-changed", lambda obj, event: loaded.quit() if event == WebKit2.LoadEvent.FINISHED else None)
view.load_uri("magnolie-organizer://app/index.html")
timeout = GLib.timeout_add_seconds(15, lambda: (loaded.quit(), False)[1]); loaded.run(); GLib.source_remove(timeout)
script = """
(() => {
 const check = (ok, message) => { if (!ok) throw new Error(message); };
 const data = OrganizerTest.leereDaten();
 data.einstellungen.adressen.kommunikation.anruf = {art:'magnolie', telefonId:'synthetic-peer', eingehendBenachrichtigen:true, computerTelefonie:true};
 App.init({daten:data, neu:false, regional:{language:'de'}});
 const peer = {device_id:'synthetic-peer', state:'online_wifi', local_grants:{grants:{incoming_call_state:true,answer_call:true,end_call:true}},
 grants:{grants:{incoming_call_state:true,answer_call:true,end_call:true}}, capabilities:{items:{incoming_call_state:{available:true,versions:[2]},answer_call:{available:true,versions:[1]},end_call:{available:true,versions:[1,2]}}}};
 App.telefonStand({peers:[peer]});
  const event = {device_id:'synthetic-peer', call_ref:crypto.randomUUID(), revision:1,state:'ringing',direction:'outgoing',number:'',number_status:'not_shared',started_ms:Date.now(),occurred_ms:Date.now(),offhook_ms:0,ended_ms:0,control_origin:'unknown'};
 callMessages.length=0;
 App.telefonEingehenderAnruf(event);
 App.telefonEingehenderAnruf({...event,state:'offhook',offhook_ms:Date.now(),revision:2});
 check(!callMessages.some(m=>m.cmd==='telefon_anruf_anzeigen'),'outgoing raised incoming alert');
  check(!document.querySelector('#anruf-schleier'),'unbound offhook opened book dialog');
  event.call_ref = crypto.randomUUID();
 callMessages.length=0;
 App.telefonEingehenderAnruf({...event,direction:'incoming'});
  check(callMessages.filter(m=>m.cmd==='telefon_anruf_anzeigen').length===1,'missing compact native alert');
  check(callMessages.find(m=>m.cmd==='telefon_anruf_anzeigen').stil==='magnolie','reminder style bypassed own call popup');
 check(!document.querySelector('#anruf-schleier'),'incoming opened full call dialog');
 callMessages.length=0;
 App.telefonEingehenderAnruf({...event,direction:'incoming',notify:false});
 check(!callMessages.some(m=>m.cmd==='telefon_anruf_anzeigen'),'revoked daemon consent ignored');
 App.telefonEingehenderAnruf({...event,direction:'incoming',device_id:'wrong-peer'});
 check(!callMessages.some(m=>m.cmd==='telefon_anruf_anzeigen'),'wrong peer alert');
 return 'WebKit call-state bridge checks passed';
})()
"""
done, result = GLib.MainLoop(), []


def finished(obj, task, _data):
    try: result.append(obj.evaluate_javascript_finish(task).to_string())
    except Exception as error: result.append(error)
    done.quit()


for visible in (True, False):
    if not visible: window.hide()
    done, result = GLib.MainLoop(), []
    view.evaluate_javascript(script, -1, None, None, None, finished, None)
    timeout = GLib.timeout_add_seconds(15, lambda: (done.quit(), False)[1]); done.run(); GLib.source_remove(timeout)
    assert result and not isinstance(result[0], Exception), result
    print(result[0] + (" (visible)" if visible else " (hidden/tray)"))
window.destroy()
