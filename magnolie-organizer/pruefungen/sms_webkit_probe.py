#!/usr/bin/env python3
"""Synthetic native SMS geometry/screenshots, both source trees, no production bridge.

Run: xvfb-run -a -s '-screen 0 1920x1080x24 -nolisten tcp' /usr/bin/python3 -B
     pruefungen/sms_webkit_probe.py [--quick]
Uses installed GTK3/WebKit2 4.1, bubblewrap, two CPUs, an ephemeral HOME and no network/GPU devices.
Text zoom is native WebKit zoom-text-only, not page zoom or a replacement stylesheet.
Functional confirmation uses only an inert mock sink and synthetic acknowledgements.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--quick", action="store_true", help="German baseline and 200%% text zoom only")
parser.add_argument("--locales", nargs="+", help="Focus on selected locale codes instead of the default language set")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
assert os.environ.get("DISPLAY"), "Run under Xvfb"
assert not os.environ.get("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS")
if not os.environ.get("MAGNOLIE_SMS_ISOLATED"):
    os.environ["MAGNOLIE_SMS_ISOLATED"] = "1"
    os.execvp("bwrap", ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/home",
        "--ro-bind", str(root), str(root), "--dev", "/dev", "--bind", "/tmp", "/tmp",
        "--unshare-net", "--unshare-pid", "--die-with-parent", sys.executable, *sys.argv])
assert not Path("/dev/dri").exists() and not list(Path("/dev").glob("nvidia*"))
lock = open("/tmp/opencode/native-layout.lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
output = Path(tempfile.mkdtemp(prefix="sms-webkit-", dir="/tmp/opencode"))
for variable in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
    directory = output / variable.lower()
    directory.mkdir(mode=0o700)
    os.environ[variable] = str(directory)
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

script = Path(__file__).with_name("sms_layout_probe.js").read_text()
(output / "sms_layout_probe.js").write_text(script)
(output / "sms_webkit_probe.py").write_bytes(Path(__file__).read_bytes())
results, commands, sources = [], [], {}
functional_results, mock_submissions = [], []
print("EVIDENCE", output, flush=True)


def evaluate(code):
    values = []
    loop = GLib.MainLoop()

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


def snapshot(path):
    errors = []
    loop = GLib.MainLoop()

    def finished(obj, task, _data):
        try:
            obj.get_snapshot_finish(task).write_to_png(str(path))
        except Exception as error:
            errors.append(error)
        loop.quit()

    view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, finished, None)
    loop.run()
    if errors:
        raise errors[0]


def mock_bridge(_manager, value, bridge_view):
    payload = json.loads(value.get_js_value().to_string())
    commands.append(payload.get("cmd"))
    if payload.get("cmd") == "kde_sms_senden":
        mock_submissions.append(payload)  # Record only. No backend or transport exists in this host.
    elif payload.get("cmd") == "speichern":
        ack = json.dumps({"id": payload["id"], "ok": True})
        bridge_view.evaluate_javascript(f"App.gespeichert({ack})", -1, None, None, None, None, None)


for platform, relative in (("linux", "magnolie-organizer/web"),
                           ("windows", "magnolie-organizer-windows/app/web")):
    web = root / relative
    assets = {str(path.relative_to(web)): path.read_bytes() for path in web.rglob("*") if path.is_file()}
    sources[str(web)] = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    catalogs = sorted(name for name in assets if name.startswith("i18n/") and name.endswith(".js"))
    supported = ["en"] + [Path(name).stem.replace("_", "-").lower() for name in catalogs]
    locales = args.locales or (["de"] if args.quick else supported)
    assert set(locales).issubset(supported), "Unsupported probe locale"
    for width, height in ((1920, 1080), (1024, 768), (390, 844), (640, 480)):
        context = WebKit2.WebContext.new_ephemeral()
        security = context.get_security_manager()
        for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_display_isolated"):
            getattr(security, method)("magnolie-organizer")

        def serve(request):
            uri = urlsplit(request.get_uri())
            name = uri.path.lstrip("/")
            if name == "i18n-active.js":
                name = "i18n/de.js"
            data = assets.get(name)
            if uri.netloc != "app" or data is None:
                request.finish_error(GLib.Error("Not a source asset"))
                return
            request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data),
                mimetypes.guess_type(name)[0] or "application/octet-stream")

        context.register_uri_scheme("magnolie-organizer", serve)
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler("sms_probe_sink")
        manager.add_script(WebKit2.UserScript.new("window.__MAGNOLIE_BRUECKE__='sms_probe_sink';",
            WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
        view = WebKit2.WebView(web_context=context, user_content_manager=manager)
        bridge_handler = manager.connect("script-message-received::sms_probe_sink", mock_bridge, view)
        view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
        view.get_settings().set_zoom_text_only(True)
        window = Gtk.Window()
        window.set_default_size(width, height)
        window.add(view)
        window.show_all()
        loaded = GLib.MainLoop()
        view.connect("load-changed", lambda _view, event: loaded.quit() if event == WebKit2.LoadEvent.FINISHED else None)
        watchdog = GLib.timeout_add_seconds(600, lambda: os._exit(2))  # Hang guard, not a performance assertion.
        view.load_uri("magnolie-organizer://app/index.html")
        loaded.run()
        evaluate("\n".join(assets[name].decode() for name in catalogs) + "\n" + script + """
          App.init({daten:{kontakte:[{id:'sms-synthetic',vorname:'Synthetic',nachname:'Contact',
            telefone:[{wert:'+12025550123',typen:['CELL']}]}]},neu:false,regional:{language:'de',timeZone:'UTC'}});
          App.telefonStand({enabled:false,peers:[],kdeconnect:{available:true,device_id:'sms-layout-synthetic-device-00001'}});
          JSON.stringify(true);
        """)
        for scale in ([1, 2] if args.quick else [1, 1.25, 2]):
            view.set_zoom_level(scale)
            for locale in locales:
                for state in ("empty", "plain", "adjusted"):
                    evaluate(f"smsProbePrepare({json.dumps(locale)}, {json.dumps(state)}); JSON.stringify(true)")
                    ready = GLib.MainLoop()

                    def poll():
                        if evaluate("JSON.stringify(window.smsProbeReady)"):
                            ready.quit()
                            return False
                        return True

                    GLib.timeout_add(25, poll)
                    ready.run()
                    result = evaluate(f"JSON.stringify(smsProbeMeasure({json.dumps(state)}))")
                    result.update(platform=platform, size=[width, height], scale=scale, state=state)
                    assert result["viewport"] == [width, height], result["viewport"]
                    assert result["locale"] == locale, (locale, result["locale"])
                    name = f"{platform}-{width}x{height}-{locale}-{int(scale*100)}-{state}"
                    if result["errors"] or (state == "adjusted" and (locale, scale) in
                            (("de", 1), ("de", 2), ("en", 1.25), ("ar", 2), ("fr", 2), ("uk", 2), ("ru", 2), ("be", 2))):
                        result["screenshot"] = name + ".png"
                        snapshot(output / result["screenshot"])
                    results.append(result)
        if width == 640:
            assert len(mock_submissions) == len(functional_results), "Geometry must never submit an SMS"
            evaluate("smsProbePrepare('en', 'adjusted'); JSON.stringify(true)")
            cancel = evaluate("JSON.stringify(smsProbeFunctional('cancel'))")
            evaluate("JSON.stringify(true)")  # Drain preceding bridge messages before checking Cancel.
            assert len(mock_submissions) == len(functional_results), "Cancel/reopen submitted an SMS"
            confirm = evaluate("JSON.stringify(smsProbeFunctional('confirm'))")
            received = GLib.MainLoop()

            def submission_received():
                if len(mock_submissions) > len(functional_results):
                    received.quit()
                    return False
                return True

            GLib.timeout_add(25, submission_received)
            received.run()
            assert len(mock_submissions) == len(functional_results) + 1, "Unexpected mock submission count"
            submission = mock_submissions[-1]
            if platform == "linux":
                confirm["expectedCommand"]["deviceId"] = "sms-layout-synthetic-device-00001"
            assert submission == confirm["expectedCommand"], submission
            ack = json.dumps({"ok": True, "state": "queued", "client_ref": submission["clientRef"]})
            acknowledged = evaluate(f"App.kdeSmsStatus({ack}); JSON.stringify(smsProbeFunctional('ack'))")
            functional_results.append({"platform": platform, "locale": "en", "checks": [cancel, confirm, acknowledged],
                "mockSubmission": submission, "realTransport": False})
        GLib.source_remove(watchdog)
        manager.disconnect(bridge_handler)
        window.destroy()
        print(platform, width, height, "cases", len(results), "failures", sum(bool(r["errors"]) for r in results), flush=True)

changed = [str(Path(web) / name) for web, files in sources.items() for name, digest in files.items()
    if hashlib.sha256((Path(web) / name).read_bytes()).hexdigest() != digest]
unchanged = not changed
report = {"engine": f"WebKitGTK {WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()}",
    "sources": sources, "sourcesUnchanged": unchanged, "changedSourcePaths": changed, "cpus": sorted(os.sched_getaffinity(0)),
    "networkIsolated": True, "gpuDevicesHidden": True, "productionBridge": False,
    "textZoomOnly": True, "commandsIntercepted": commands, "results": results,
    "functionalResults": functional_results, "mockSubmissions": mock_submissions, "realTransport": False}
(output / "report.json").write_text(json.dumps(report, indent=2))
with (output / "measurements.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["platform", "width", "height", "locale", "text_scale", "state", "send_top", "schedule_top",
        "send_height", "schedule_height", "textarea_width", "content_width", "scroll_top", "errors", "screenshot"])
    for result in results:
        boxes = result["boxes"]
        writer.writerow([result["platform"], *result["size"], result["locale"], result["scale"], result["state"],
            boxes["send"]["top"], boxes["schedule"]["top"], boxes["send"]["height"], boxes["schedule"]["height"],
            boxes["textarea"]["width"], boxes["content"]["width"], result["scroll"]["final"],
            "; ".join(result["errors"]), result.get("screenshot", "")])
        if result.get("screenshot"):
            print("MEASURE", result["screenshot"], "Send top/height", boxes["send"]["top"], boxes["send"]["height"],
                "Schedule top/height", boxes["schedule"]["top"], boxes["schedule"]["height"],
                "scroll", result["scroll"]["final"], "errors", result["errors"], flush=True)
assert unchanged, f"Source changed during probe; rerun against a stable snapshot: {changed}"
assert [command for command in commands if command and ("senden" in command or "send" in command)] == ["kde_sms_senden"] * 2, commands
assert len(functional_results) == len(mock_submissions) == 2
failures = [result for result in results if result["errors"]]
functional_failures = [check for result in functional_results for check in result["checks"] if check["errors"]]
for result in functional_results:
    for check in result["checks"]:
        print("FUNCTIONAL CHECK", result["platform"], check["action"], "errors", check["errors"], flush=True)
print("MAX DELTAS", {key: max(abs(r["boxes"]["send"][key] - r["boxes"]["schedule"][key])
    for r in results) for key in ("top", "height")}, flush=True)
print("RESULT", len(results), "measurements;", len(failures), "failures; no outbound SMS", flush=True)
print("FUNCTIONAL", len(functional_results), "frontends;", len(functional_failures), "failures;",
    len(mock_submissions), "mock-only confirmations; no real transport", flush=True)
sys.exit(bool(failures or functional_failures))
