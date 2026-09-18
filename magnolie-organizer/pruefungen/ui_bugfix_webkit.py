#!/usr/bin/env python3
"""Both source UIs, 20 locales, four viewports, software-only ephemeral WebKit.

Run with xvfb-run -a -s '-screen 0 1920x1080x24 -nolisten tcp' /usr/bin/python3 -B.
No native backend, network, GPU device, real profile or product build is used.
"""
import fcntl
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
assert os.environ.get("DISPLAY")
assert not os.environ.get("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS")
if not os.environ.get("MAGNOLIE_UI_BUGFIX_ISOLATED"):
    os.environ["MAGNOLIE_UI_BUGFIX_ISOLATED"] = "1"
    os.execvp("bwrap", ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/home", "--ro-bind", str(ROOT), str(ROOT),
        "--dev", "/dev", "--bind", "/tmp", "/tmp", "--unshare-net", "--unshare-pid", "--die-with-parent", sys.executable, *sys.argv])
assert not Path("/dev/dri").exists() and not list(Path("/dev").glob("nvidia*"))
lock = open("/tmp/opencode/native-layout.lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
output = Path(tempfile.mkdtemp(prefix="ui-bugfix-webkit-", dir="/tmp/opencode"))
for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
    directory = output / key.lower()
    directory.mkdir(mode=0o700)
    os.environ[key] = str(directory)
os.environ.update(GDK_BACKEND="x11", GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1",
    LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe", LP_NUM_THREADS="2", OMP_NUM_THREADS="2",
    __GLX_VENDOR_LIBRARY_NAME="mesa", WEBKIT_DISABLE_DMABUF_RENDERER="1",
    __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json")
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
sys.dont_write_bytecode = True

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk, WebKit2

script = (ROOT / "magnolie-organizer-windows/tests/ui-bugfix-probe.js").read_text()
locales = list(json.loads((ROOT / "contracts/ui-bugfixes.json").read_text())["translations"])
results, commands, sources = [], [], {}
print("EVIDENCE", output, flush=True)


def evaluate(code):
    values, loop = [], GLib.MainLoop()

    def finished(obj, task, _data):
        try:
            values.append(json.loads(obj.evaluate_javascript_finish(task).to_string()))
        except Exception as error:
            values.append(error)
        loop.quit()

    view.evaluate_javascript(code, -1, None, None, None, finished, None)
    loop.run()
    if isinstance(values[0], Exception):
        raise values[0]
    return values[0]


def mock_bridge(_manager, value):
    message = json.loads(value.get_js_value().to_string())
    commands.append(message.get("cmd"))
    if message.get("cmd") == "speichern":
        view.evaluate_javascript("App.gespeichert(" + json.dumps({"id": message["id"], "ok": True}) + ")",
            -1, None, None, None, None, None)


for platform, relative in (("linux", "magnolie-organizer/web"), ("windows", "magnolie-organizer-windows/app/web")):
    web = ROOT / relative
    assets = {str(p.relative_to(web)): p.read_bytes() for p in web.rglob("*") if p.is_file()}
    sources[platform] = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    catalogs = sorted(name for name in assets if name.startswith("i18n/") and name.endswith(".js"))
    for width, height in ((1920, 1080), (1024, 768), (390, 844), (640, 480)):
        context = WebKit2.WebContext.new_ephemeral()
        security = context.get_security_manager()
        for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_display_isolated"):
            getattr(security, method)("magnolie-organizer")

        def serve(request):
            uri = urlsplit(request.get_uri())
            name = "i18n/de.js" if uri.path == "/i18n-active.js" else uri.path.lstrip("/")
            data = assets.get(name)
            if uri.netloc != "app" or data is None:
                request.finish_error(GLib.Error("Not a source asset"))
                return
            request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data),
                mimetypes.guess_type(name)[0] or "application/octet-stream")

        context.register_uri_scheme("magnolie-organizer", serve)
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler("ui_probe_sink")
        manager.add_script(WebKit2.UserScript.new("window.__MAGNOLIE_BRUECKE__='ui_probe_sink';",
            WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
        manager.connect("script-message-received::ui_probe_sink", mock_bridge)
        view = WebKit2.WebView(web_context=context, user_content_manager=manager)
        view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
        window = Gtk.Window()
        window.set_default_size(width, height)
        window.add(view)
        window.show_all()
        loaded = GLib.MainLoop()
        view.connect("load-changed", lambda _view, event: loaded.quit() if event == WebKit2.LoadEvent.FINISHED else None)
        watchdog = GLib.timeout_add_seconds(600, lambda: os._exit(2))
        view.load_uri("magnolie-organizer://app/index.html")
        loaded.run()
        evaluate("\n".join(assets[name].decode() for name in catalogs) + "\n" + script + """
          App.init({daten: {}, neu:false, regional:{language:'en',timeZone:'UTC'}});
          OrganizerTest.oeffneBuch(); JSON.stringify(true);
        """)
        for locale in locales:
            for screen in ("sms-off", "settings", "sms-on", "plans", "designer", "device"):
                try:
                    evaluate(f"JSON.stringify(uiBugfixPrepare({json.dumps(locale)}, {json.dumps(screen)}))")
                    ready = GLib.MainLoop()
                    GLib.timeout_add(40, lambda: (ready.quit(), False)[1])
                    ready.run()
                    result = evaluate(f"JSON.stringify(uiBugfixMeasure({json.dumps(screen)}))")
                    assert result["viewport"] == [width, height]
                    assert result["locale"] == locale.replace("_", "-").lower()
                except Exception as error:
                    result = {"locale": locale, "screen": screen, "errors": [str(error)]}
                result.update(platform=platform, size=[width, height])
                if result["errors"] or locale == "de":
                    filename = f"{platform}-{width}x{height}-{locale}-{screen}.png"
                    loop = GLib.MainLoop()

                    def captured(obj, task, _data):
                        obj.get_snapshot_finish(task).write_to_png(str(output / filename))
                        loop.quit()

                    view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, captured, None)
                    loop.run()
                    result["screenshot"] = filename
                results.append(result)
        GLib.source_remove(watchdog)
        window.destroy()
        print(platform, width, height, "cases", len(results), "failures", sum(bool(r["errors"]) for r in results), flush=True)

report = {"engine": f"WebKitGTK {WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()}",
    "networkIsolated": True, "gpuDevicesHidden": True, "productionBridge": False,
    "sourceSnapshots": sources, "commands": commands, "results": results}
(output / "report.json").write_text(json.dumps(report, indent=2))
assert not any("senden" in (cmd or "") or "send" in (cmd or "") for cmd in commands), commands
failures = [r for r in results if r["errors"]]
print("RESULT", len(results), "cases;", len(failures), "failures; no SMS dispatched", flush=True)
sys.exit(bool(failures))
