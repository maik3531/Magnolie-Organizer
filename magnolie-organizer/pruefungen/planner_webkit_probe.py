#!/usr/bin/env python3
"""Native Planner regression. Only copied assets and synthetic, ephemeral profiles.

Run with xvfb-run -a /usr/bin/python3; no launcher, services, or user data are run.
--profile instruments function calls in the served response, not the asset copy.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--web", type=Path, default=Path("/usr/share/magnolie-organizer/web"))
parser.add_argument("--deb", type=Path, help="Extract immutable published assets, never install or run the launcher")
parser.add_argument("--tier", choices=("complex", "compatible"), default="complex")
parser.add_argument("--prints", action="store_true", help="Check optional print fields on the same synthetic payload")
parser.add_argument("--scenario", choices=("empty", "realistic", "large"), default="realistic")
parser.add_argument("--profile", action="store_true")
parser.add_argument("--cycles", type=int, default=10)
parser.add_argument("--timeout", type=int, default=90)
parser.add_argument("--gate", action="store_true")
parser.add_argument("--checks", action="store_true", help="Run Planner semantic regressions instead of timing")
parser.add_argument("--month-stability", action="store_true", help="Check recurring month entries and native tab navigation")
parser.add_argument("--software-compositor", action="store_true", help="Use launcher-default compositing with Mesa llvmpipe only")
parser.add_argument("--http", action="store_true", help="Use loopback HTTP for the Windows blob-only worker CSP")
parser.add_argument("--paint-controls", action="store_true", help="Measure animation-only and identical raster texture controls")
parser.add_argument("--paint-benchmark", action="store_true", help="Independent native CSS rectangle benchmark, not an app gate")
parser.add_argument("--grid-control", action="store_true", help="Diagnostic explicit Planner grid track minima")
parser.add_argument("--css-benchmark", action="store_true", help="Static book CSS benchmark without application JavaScript")
parser.add_argument("--paint-containment", choices=("animation", "always"), help="Diagnostic page paint containment")
parser.add_argument("--page-layers", action="store_true", help="Diagnostic preallocated page animation layers")
parser.add_argument("--quiet", action="store_true", help="Keep per-step evidence in JSON without live console logging")
parser.add_argument("--legacy", action="store_true", help="Replay the archived pre-clarification fixture unchanged")
parser.add_argument("--baseline", action="store_true", help="Record installed behavior without asserting the new Planner contract")
parser.add_argument("--tab-budget", type=int, default=500, help="End-to-end XTest tab activation budget in milliseconds")
args = parser.parse_args()
allowed = sorted(os.sched_getaffinity(0))
cpus, cores = [], set()
for cpu in allowed:
    topology = Path("/sys/devices/system/cpu/cpu%s/topology" % cpu)
    core = ((topology / "physical_package_id").read_text().strip(), (topology / "core_id").read_text().strip())
    if core not in cores:
        cpus.append(cpu); cores.add(core)
    if len(cpus) == 2:
        break
cpus += [cpu for cpu in allowed if cpu not in cpus][:2-len(cpus)]
os.sched_setaffinity(0, cpus)
assert not (args.http and args.profile), "Function instrumentation uses the native URI handler"
assert not (args.css_benchmark and args.http), "Static CSS benchmark uses the native URI handler"
assert os.environ.get("DISPLAY"), "Run under xvfb-run"
assert not os.environ.get("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS")
if not os.environ.get("MAGNOLIE_PLANNER_NO_DEVICES"):
    os.environ["MAGNOLIE_PLANNER_NO_DEVICES"] = "1"
    os.execvp("bwrap", ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--bind", "/tmp", "/tmp",
                        "--unshare-pid", "--die-with-parent", sys.executable, *sys.argv])
assert not Path("/dev/dri").exists() and not list(Path("/dev").glob("nvidia*")), "GPU devices must be hidden"
workspace = Path(tempfile.mkdtemp(prefix="magnolie-planner-", dir="/tmp/opencode"))
for variable in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
    directory = workspace / variable.lower()
    directory.mkdir(mode=0o700)
    os.environ[variable] = str(directory)
os.environ.update(LIBGL_ALWAYS_SOFTWARE="1", GSK_RENDERER="cairo", GDK_BACKEND="x11",
                  LP_NUM_THREADS="2", OMP_NUM_THREADS="2",
                  GALLIUM_DRIVER="llvmpipe", __GLX_VENDOR_LIBRARY_NAME="mesa",
                  __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json",
                  WEBKIT_DISABLE_DMABUF_RENDERER="1", GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1")
os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
sys.dont_write_bytecode = True

def identity(path):
    stat = path.stat()
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}

package_identity = None
if args.deb:
    package_identity = identity(args.deb)
    extracted = workspace / "published"
    subprocess.run(["dpkg-deb", "--extract", str(args.deb.resolve()), str(extracted)], check=True)
    for path in extracted.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    original = extracted / "usr/share/magnolie-organizer/web"
else:
    original = args.web.resolve()
assert original.name == "web" and (original / "anwendung.js").is_file() and (original / "index.html").is_file()
before = {str(path.relative_to(original)): identity(path) for path in original.rglob("*") if path.is_file()}
web = workspace / "assets"
shutil.copytree(original, web, copy_function=shutil.copy2)
for relative, expected in before.items():
    assert identity(original / relative) == identity(web / relative) == expected, "Assets changed during snapshot"
    (web / relative).chmod(0o444)
script_name = "planner_regressions.js" if args.checks else "planner_webkit_probe.js"
if args.month_stability:
    assert not args.legacy and not args.css_benchmark and not args.profile
    script_name = "month_recurrence_webkit.js"
if args.legacy:
    script_name = "planner_legacy_regressions.js" if args.checks else "planner_legacy_probe.js"
script_path = Path(__file__).with_name("planner_css_benchmark.js" if args.css_benchmark else script_name)
script_identity = identity(script_path)
probe_script = script_path.read_bytes()
assert hashlib.sha256(probe_script).hexdigest() == script_identity["sha256"]
if args.prints:
    print_script = Path(__file__).with_name("planner_print_regressions.js")
    probe_script = print_script.read_bytes() + b"\n" + probe_script
(workspace / "probe.js").write_bytes(probe_script)
(workspace / "probe.js").chmod(0o444)
shutil.copy2(Path(__file__), workspace / "driver.py")
(workspace / "driver.py").chmod(0o444)
# Source/deb probes must not depend on or inspect an unrelated host installation.
installed_context = not args.deb and original == Path("/usr/share/magnolie-organizer/web")
manifest = {"source": str(original), "assets": before, "profile": args.profile,
            "month_stability": args.month_stability,
            "scenario": args.scenario, "cycles": args.cycles,
            "software_compositor": args.software_compositor,
            "gpu_devices_hidden": True, "http": args.http,
            "cpus": sorted(os.sched_getaffinity(0)), "paint_controls": args.paint_controls,
            "physical_cores": sorted(cores),
            "paint_benchmark": args.paint_benchmark,
            "grid_control": args.grid_control,
            "css_benchmark": args.css_benchmark,
            "paint_containment": args.paint_containment,
            "page_layers": args.page_layers,
            "quiet": args.quiet,
             "legacy": args.legacy, "baseline": args.baseline,
             "tier": args.tier, "prints": args.prints,
             "published_deb": {"path": str(args.deb.resolve()), **package_identity} if args.deb else None,
             "published_version": subprocess.check_output(["dpkg-deb", "-f", str(args.deb), "Version"], text=True).strip() if args.deb else None,
            "tab_budget_ms": args.tab_budget,
            "input": "X11 XTest pointer; visible hit targets; trusted click events",
            "driver": identity(Path(__file__)),
             "script": script_identity, "combined_script_sha256": hashlib.sha256(probe_script).hexdigest(),
             "launcher": identity(Path("/usr/bin/magnolie-organizer")) if installed_context else None,
             "package": subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", "magnolie-organizer"], text=True)
                        if installed_context else None}
(workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
print("EVIDENCE", workspace, flush=True)

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gio, GLib, Gtk, WebKit2, GdkX11

context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure", "register_uri_scheme_as_display_isolated"):
    getattr(security, method)("magnolie-organizer")

def serve(request):
    uri = urlsplit(request.get_uri())
    relative = uri.path.lstrip("/")
    if relative == "i18n-active.js":
        relative = "i18n/de.js"
    path = (web / relative).resolve()
    if uri.netloc != "app" or not path.is_relative_to(web) or not path.is_file():
        request.finish_error(GLib.Error("Not a probe asset"))
        return
    data = path.read_bytes()
    if args.css_benchmark and relative == "anwendung.js":
        data = b"/* Diagnostic CSS scene: application JavaScript is not loaded. */"
    if args.profile and relative == "anwendung.js":
        instrumentation = "window.plannerProfile = {};\n"
        instrumentation += """{
          const focus = HTMLElement.prototype.focus;
          HTMLElement.prototype.focus = function(...args) {
            if (!this.classList.contains('registerknopf')) return focus.apply(this,args);
            const p = window.plannerProfile.registerFocus ||= {calls:0,ms:0,max:0};
            const start=performance.now();
            try { return focus.apply(this,args); } finally {
              const ms=performance.now()-start; p.calls++; p.ms+=ms; p.max=Math.max(p.max,ms);
            }
          };
          const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
          Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {...descriptor, get() {
            if (this.id !== 'seiten') return descriptor.get.call(this);
            const p = window.plannerProfile.forcedPageLayout ||= {calls:0, ms:0, max:0};
            const start = performance.now();
            try { return descriptor.get.call(this); } finally {
              const ms = performance.now()-start; p.calls++; p.ms+=ms; p.max=Math.max(p.max,ms);
            }
          }});
        }\n"""
        for name in ("zeichneAlles", "zeichneRegister", "leereSeiten", "zeichnePlaner", "termineAm", "terminVerzeichnis", "icsRuntime",
                     "icsSerienAbstimmen", "feiertageAm", "tagmarkenAm", "urlaubeAm"):
            instrumentation += f"""{name} = new Proxy({name}, {{apply(fn, self, args) {{
              const p = window.plannerProfile['{name}'] ||= {{calls:0, ms:0, max:0}};
              const start = performance.now(); p.calls++;
              try {{ return Reflect.apply(fn, self, args); }} finally {{
                const ms = performance.now()-start; p.ms += ms; p.max = Math.max(p.max,ms);
              }}
            }}}});\n"""
        data = data.replace(b"  window.OrganizerTest = {", instrumentation.encode() + b"  window.OrganizerTest = {")
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data),
                   mimetypes.guess_type(path)[0] or "application/octet-stream")

context.register_uri_scheme("magnolie-organizer", serve)
manager = WebKit2.UserContentManager()
manager.register_script_message_handler("planner_probe")
manager.add_script(WebKit2.UserScript.new("window.__MAGNOLIE_BRUECKE__='planner_probe';window.__MAGNOLIE_SPRACHE__='de';",
    WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
view = WebKit2.WebView(web_context=context, user_content_manager=manager)
if not args.software_compositor:
    view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
window = Gtk.Window()
window.set_default_size(1200, 800)
window.add(view)
loop = GLib.MainLoop()
events = []
host_gaps = []
last_host = time.monotonic()
paint_sample = None
paint_samples = []
def web_cpu_ms():
    total = 0
    # /proc contains only this test's children in the outer PID namespace.
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = path.read_text()
            if "(WebKitWebProces)" not in raw:
                continue
            fields = raw.rsplit(")", 1)[1].split()
            total += int(fields[11]) + int(fields[12])
        except (FileNotFoundError, ProcessLookupError):
            pass
    return total * 1000 / os.sysconf("SC_CLK_TCK")

def painted(_view, _cr):
    if paint_sample is not None:
        paint_sample["draws"].append((time.monotonic() - paint_sample["started"]) * 1000)
    return False
view.connect_after("draw", painted)
def heartbeat():
    global last_host
    now = time.monotonic()
    host_gaps.append((now - last_host) * 1000)
    last_host = now
    return True

def message(_manager, value):
    global paint_sample
    event = json.loads(value.get_js_value().to_string())
    if event.get("probe"):
        if event["probe"] == "synthetic-profile":
            payload = json.dumps(event.pop("data"), sort_keys=True, separators=(",", ":")).encode()
            (workspace / "synthetic-payload.json").write_bytes(payload)
            (workspace / "synthetic-payload.json").chmod(0o444)
            event["sha256"] = hashlib.sha256(payload).hexdigest()
            manifest["synthetic_payload_sha256"] = event["sha256"]
            (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
        elif event["probe"] == "start":
            paint_sample = {"name": event["name"], "started": time.monotonic(), "draws": [], "web_cpu": web_cpu_ms()}
        elif event["probe"] == "sample" and paint_sample is not None:
            paint_samples.append({"name": paint_sample["name"], "gtk_draw_ms": paint_sample["draws"]})
            event["gtk_first_draw_ms"] = next(iter(paint_sample["draws"]), None)
            event["web_process_cpu_ms"] = web_cpu_ms() - paint_sample["web_cpu"]
            paint_sample = None
        elif event["probe"] == "snapshot":
            def snapshot_ready(obj, result):
                try:
                    surface = obj.get_snapshot_finish(result)
                    surface.write_to_png(str(workspace / (event["name"] + ".png")))
                    view.evaluate_javascript("window.plannerSnapshotDone()", -1, None, None, None, None, None)
                except Exception as error:
                    events.append({"probe": "failure", "error": str(error)})
                    loop.quit()
            view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE,
                              None, snapshot_ready)
        elif event["probe"] == "native-click":
            scale = view.get_scale_factor()
            process = Gio.Subprocess.new(["xdotool", "mousemove", "--window",
                str(GdkX11.X11Window.get_xid(window.get_window())),
                str(round(event["x"] * scale)), str(round(event["y"] * scale)),
                "click", "--delay", "0", "1"], Gio.SubprocessFlags.NONE)
            process.wait_async(None, lambda obj, result: obj.wait_finish(result))
        elif event["probe"] == "print-artifact":
            name = event["name"]
            assert name.replace("-", "").isalnum()
            (workspace / (name + ".html")).write_text(event.pop("html"))
            (workspace / (name + ".json")).write_text(json.dumps(event.pop("data"), indent=2))
        events.append(event)
        if not args.quiet or event["probe"] in ("done", "failure"):
            print(json.dumps(event), flush=True)
        if event["probe"] in ("done", "failure"):
            loop.quit()
    elif event.get("cmd") == "speichern":
        view.evaluate_javascript("App.gespeichert(%s)" % json.dumps({"id": event["id"], "ok": True}),
                                 -1, None, None, None, None, None)
    elif event.get("cmd") in ("drucken", "planer_ods"):
        view.evaluate_javascript("window.plannerBridgeReply(%s)" % json.dumps(event),
                                 -1, None, None, None, None, None)

def loaded(_view, event):
    if event == WebKit2.LoadEvent.FINISHED:
        script = probe_script.decode()
        script = "window.plannerProbeOptions=" + json.dumps(vars(args), default=str) + ";\n" + script
        view.evaluate_javascript(script, -1, None, None, None, None, None)

manager.connect("script-message-received::planner_probe", message)
view.connect("load-changed", loaded)
view.connect("web-process-terminated", lambda _view, reason: (events.append({"probe": "terminated", "reason": str(reason)}), loop.quit()))
server = None
if args.http:
    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
    from threading import Thread
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *values, **kwargs):
            super().__init__(*values, directory=str(web), **kwargs)
        def translate_path(self, path):
            if urlsplit(path).path == "/i18n-active.js":
                path = "/i18n/de.js"
            return super().translate_path(path)
        def log_message(self, *_values):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
view.load_uri("http://127.0.0.1:%s/index.html" % server.server_port if server else "magnolie-organizer://app/index.html")
window.show_all()
GLib.timeout_add(10, heartbeat)
GLib.timeout_add_seconds(args.timeout, lambda: (events.append({"probe": "timeout"}), loop.quit(), False)[-1])
loop.run()
manifest["source_unchanged"] = all(identity(original / relative) == expected for relative, expected in before.items())
manifest["deb_unchanged"] = not args.deb or identity(args.deb) == package_identity
(workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
assert manifest["source_unchanged"] and manifest["deb_unchanged"]
window.destroy()
if server:
    server.shutdown()
report = {"events": events, "native_paints": paint_samples, "host_heartbeat_max_ms": max(host_gaps, default=0),
          "webkit": "%s.%s.%s" % (WebKit2.get_major_version(), WebKit2.get_minor_version(), WebKit2.get_micro_version())}
samples = [event for event in events if event.get("probe") == "sample"]
report["summary"] = {"samples": len(samples),
    "max_frame_ms": max((event["frames"]["max"] for event in samples), default=0),
    "max_js_heartbeat_ms": max((event["heartbeat"]["max"] for event in samples), default=0),
    "max_js_activity_gap_ms": max((event.get("maxJsActivityGapMs", 0) for event in samples), default=0),
    "max_input_dispatch_ms": max((event["inputDispatchMs"] for event in samples), default=0)}
(workspace / "results.json").write_text(json.dumps(report, indent=2))
print("HOST", json.dumps({key: value for key, value in report.items() if key not in ("events", "native_paints")}), flush=True)
sys.exit(0 if events and events[-1].get("probe") == "done" and events[-1].get("ok") else 1)
