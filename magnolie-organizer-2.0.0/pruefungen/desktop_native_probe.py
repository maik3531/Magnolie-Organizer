#!/usr/bin/env python3
"""Run under xvfb-run; uses ephemeral WebKit and synthetic data only."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "bin"))
temporary = tempfile.TemporaryDirectory(prefix="magnolie-desktop-probe-", dir="/tmp/opencode")
for variable, directory in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                            ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                            ("XDG_RUNTIME_DIR", "runtime")):
    target = Path(temporary.name) / directory
    target.mkdir(mode=0o700)
    os.environ[variable] = str(target)
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["NO_AT_BRIDGE"] = "1"
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)

from magnolie_asset import read_asset
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk, WebKit2

tree = ast.parse((root / "bin/magnolie-organizer").read_text())
nodes = [node for node in tree.body if
         isinstance(node, ast.FunctionDef) and node.name in ("organizer_ressource", "organizer_navigation", "_text_sha256") or
         isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
         ("ORGANIZER_URI", "_ORGANIZER_RESSOURCEN") for target in node.targets)]
policy = {"os": os, "json": json, "normalisiere_sprache": lambda value, *_: value}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "native-policy", "exec"), policy)
uid_block = next(node for node in ast.walk(tree) if isinstance(node, ast.If) and any(
    isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "instanz_hash"
        for target in statement.targets) for statement in node.body))
uid_code = compile(ast.Module(body=uid_block.body, type_ignores=[]), "native-instance-identity", "exec")
for uri in ("file:///etc/passwd", "https://example.invalid/index.html",
            "magnolie-organizer://user@app/index.html", "magnolie-organizer://app:443/index.html",
            "magnolie-organizer://app/../index.html", "magnolie-organizer://app/%2e%2e/index.html",
            "magnolie-organizer://app/index.html?extra=1"):
    assert policy["organizer_ressource"](uri, str(root / "web"), "en") is None

context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_display_isolated"):
    getattr(security, method)("magnolie-organizer")

def resource(request):
    match = policy["organizer_ressource"](request.get_uri(), str(root / "web"), "en")
    content = (read_asset(match[0], 1, 1) if match[1] == "image/png" else Path(match[0]).read_bytes()) if match else b""
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(content)), len(content), match[1] if match else "text/plain")

context.register_uri_scheme("magnolie-organizer", resource)
manager = WebKit2.UserContentManager()
manager.register_script_message_handler("desktop_probe")
manager.add_script(WebKit2.UserScript.new("window.__MAGNOLIE_BRUECKE__='desktop_probe';",
    WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
view = WebKit2.WebView(web_context=context, user_content_manager=manager)
window = Gtk.Window()
window.set_default_size(1200, 800)
window.add(view)
loop = GLib.MainLoop()
state = {"font": False, "image": False, "instance": False, "guard": False, "saved": False, "closed": False}

def evaluate(script):
    view.evaluate_javascript(script, -1, None, None, None, None, None)

def message(_manager, value):
    data = json.loads(value.get_js_value().to_string())
    if data.get("probe") == "font":
        state["font"] = data.get("loaded") == 1
        state["image"] = data.get("image") is True
        evaluate("""
            App.init({daten:{aufgaben:[{id:'native-series',uid:'native-series',titel:'Synthetic series',
              startDatum:'2026-01-01',faellig:'2026-01-01',startZeit:'12:00',faelligZeit:'13:00',
              icsRoundtrip:['DTSTART:20260101T120000Z','DUE:20260101T130000Z','RRULE:FREQ=DAILY']}]},
              neu:false,regional:{language:'en',timeZone:'UTC'}});
            OrganizerTest.wechsel('aufgaben');
            const complete=()=>{
              const button=document.querySelector('.check');
              if(!button || button.disabled){setTimeout(complete,10);return;}
              button.click();
              const done=OrganizerTest.daten().aufgaben.find(task=>task.erledigt);
              window.webkit.messageHandlers.desktop_probe.postMessage(JSON.stringify({probe:'instance',
                uid:done.uid,rid:done.icsRoundtrip.find(line=>line.startsWith('RECURRENCE-ID:'))}));
              OrganizerTest.wechsel('kalender').then(()=>{
                OrganizerTest.oeffneTerminBlatt(null,'2026-09-10');
                const title=document.querySelector('#tb-titel'); title.value='Synthetic native draft';
                title.dispatchEvent(new Event('input',{bubbles:true}));
                App.vorBeenden();
                window.webkit.messageHandlers.desktop_probe.postMessage(JSON.stringify({probe:'guard',
                  present:!!document.querySelector('#aenderungen-schleier')}));
              });
            }; complete();
        """)
    elif data.get("probe") == "instance":
        value = data["rid"].split(":", 1)[1]
        scope = {"uid_wert": "native-series", "recurrence_params": {}, "recurrence_id": value}
        exec(uid_code, policy, scope)
        state["instance"] = data["uid"] == scope["uid_wert"]
    elif data.get("probe") == "guard":
        state["guard"] = data.get("present") is True and not state["saved"]
        evaluate("Array.from(document.querySelectorAll('#aenderungen-schleier button')).find(b=>b.textContent==='Save').click();")
    elif data.get("cmd") == "speichern":
        content = json.loads(data["text"])
        state["saved"] = any(item.get("titel") == "Synthetic native draft" for item in content.get("termine", []))
        evaluate("App.gespeichert(%s);" % json.dumps({"id": data["id"], "ok": True}))
    elif data.get("cmd") == "beenden_bereit":
        state["closed"] = state["saved"]
        loop.quit()

def loaded(_view, event):
    if event == WebKit2.LoadEvent.FINISHED:
        evaluate("const image=new Image(); image.src='kaffee-qr.png'; Promise.all([document.fonts.load('24px \"Magnolie Handschrift\"'),image.decode()]).then(([fonts])=>window.webkit.messageHandlers.desktop_probe.postMessage(JSON.stringify({probe:'font',loaded:fonts.length,image:image.naturalWidth>0}))); ")

manager.connect("script-message-received::desktop_probe", message)
view.connect("load-changed", loaded)
view.load_uri("magnolie-organizer://app/index.html")
window.show_all()
GLib.timeout_add_seconds(25, lambda: (loop.quit(), False)[1])
loop.run()
window.destroy()
assert all(state.values()), state
print("GTK/WEBKIT DESKTOP PROBE PASSED", json.dumps(state))
temporary.cleanup()
