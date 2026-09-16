"""Native X11 keyboard/wheel regression, ephemeral WebKit, inert bridge only.

Run under isolated Xvfb (never the desktop display), with --web and --output.
--before records installed/baseline behavior without applying fixed assertions.
Only the test export is injected; the time widget and handlers are unmodified.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2

parser = argparse.ArgumentParser()
parser.add_argument("--web", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--before", action="store_true")
parser.add_argument("--locale", choices=("de", "en"), default="de")
parser.add_argument("--all-locales", action="store_true")
args = parser.parse_args()
assert os.environ.get("MAGNOLIE_TIME_ISOLATED") == "1", "Use custom_time_isolated.sh"
assert not Path("/dev/dri").exists() and not list(Path("/dev").glob("nvidia*"))
started = time.monotonic()
web = args.web.resolve()
args.output.mkdir(parents=True, exist_ok=True)
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
Gtk.init([])
context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure",
               "register_uri_scheme_as_display_isolated"):
    getattr(security, method)("magnolie-organizer")


def serve(request):
    name = urlsplit(request.get_uri()).path.lstrip("/")
    if name == "i18n-active.js":
        name = "i18n/de.js"  # English is the source language, loaded below via App.init.
    asset = (web / name).resolve()
    if not asset.is_relative_to(web) or not asset.is_file():
        request.finish_error(GLib.Error("Missing test asset"))
        return
    data = asset.read_bytes()
    if name == "anwendung.js":
        data = data.replace(b"window.OrganizerTest = {", b"window.OrganizerTest = { oeffneCustomEintrag, oeffneTerminBlatt, oeffneSmsPlanung, pruefeSmsPlanung, beendeModal,")
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data),
                   mimetypes.guess_type(name)[0] or "application/octet-stream")


context.register_uri_scheme("magnolie-organizer", serve)
view = WebKit2.WebView.new_with_context(context)
view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
view.get_settings().set_enable_write_console_messages_to_stdout(True)
manager = view.get_user_content_manager()
manager.add_script(WebKit2.UserScript.new("""
window.__MAGNOLIE_SPRACHE__ = 'de';
window.__MAGNOLIE_BRUECKE__ = 'timeTest';
const RealDate = Date;
window.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : ['2026-09-13T09:22:00Z'])); }
  static now() { return new RealDate('2026-09-13T09:22:00Z').getTime(); }
};
window.timeSaves = [];
window.testCommands = [];
window.webkit = {messageHandlers: {timeTest: {postMessage(text) {
  const message = JSON.parse(text);
  testCommands.push(message.cmd);
  if (message.cmd === 'speichern') {
    timeSaves.push(JSON.parse(message.text));
    setTimeout(() => App.gespeichert({id: message.id, ok: true}), 0);
  }
}}}};
window.nativeEvents = [];
window.browserReports = 0;
const nativeReportValidity = HTMLInputElement.prototype.reportValidity;
HTMLInputElement.prototype.reportValidity = function() {
  browserReports++;
  return nativeReportValidity.call(this);
};
for (const kind of ['keydown', 'wheel', 'input', 'change', 'blur'])
  document.addEventListener(kind, e => {
    if (e.target.type === 'time') nativeEvents.push({kind, trusted: e.isTrusted,
      key: e.key, deltaY: e.deltaY, deltaX: e.deltaX, shift: e.shiftKey, value: e.target.value});
  }, true);
""", WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
window = Gtk.Window(title="Isolated custom time test")
window.set_default_size(1100, 850)
window.add(view)
window.show_all()


def wait(ms=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


def evaluate(script):
    loop, result = GLib.MainLoop(), []

    def finished(obj, task, _data):
        try:
            result.append(json.loads(obj.evaluate_javascript_finish(task).to_string()))
        except Exception as error:
            result.append(error)
        loop.quit()

    view.evaluate_javascript("JSON.stringify((() => {" + script + "})())", -1,
                             None, None, None, finished, None)
    timeout = GLib.timeout_add_seconds(15, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timeout)
    if not result or isinstance(result[0], Exception):
        raise AssertionError(result)
    return result[0]


def xdo(*command):
    # WebKit can still be processing the previous native event on the two-CPU
    # software-rendering budget. Give successive physical key events time to land.
    if command[0] == "key":
        command = ("key", "--delay", "60", *command[1:])
    subprocess.run(["xdotool", *map(str, command)], check=True)
    wait(200)


def click(selector, offset=12):
    rect = evaluate(f"const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.x, r.y, r.height];")
    xdo("mousemove", round(rect[0] + offset), round(rect[1] + rect[2] / 2), "click", 1)


field = '#custom-eintrag-schleier input[type="time"]'
apply = ".custom-eintrag-aktionen .haupt"


def snapshot():
    return evaluate("""
const f = document.querySelector('#custom-eintrag-schleier input[type="time"]');
return {field: f && {value: f.value, bad: f.validity.badInput, focused: document.activeElement === f,
  placeholder: f.placeholder, validationMessage: f.validationMessage,
  label: f.labels?.[0]?.textContent, describedBy: f.getAttribute('aria-describedby'),
  invalid: f.getAttribute('aria-invalid'), title: f.title},
  items: OrganizerTest.daten().customOrganizer.modules[0].items,
  feedback: document.querySelector('#custom-zeit-fehler')?.textContent || document.querySelector('#zettel').textContent,
  feedbackVisible: !!document.querySelector('#custom-zeit-fehler:not(.verborgen)'),
  browserReports, events: nativeEvents};
""")


screens = []


def screenshot(name):
    wait(200)
    pixbuf = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
                                       window.get_allocated_width(), window.get_allocated_height())
    pixbuf.savev(str(args.output / (name + ".png")), "png", [], [])
    metrics = evaluate("""
const dialog = [...document.querySelectorAll('.eingabe-dialog')].at(-1);
const r = dialog?.getBoundingClientRect();
const fields = dialog ? [...dialog.querySelectorAll('input[type="time"], button, label, .einst-warnung, .einst-hinweis')]
  .filter(n => n.getClientRects().length) : [];
return {viewport:[innerWidth, innerHeight], dialog:r && [r.x,r.y,r.width,r.height],
  horizontalOverflow:dialog ? Math.max(0, dialog.scrollWidth-dialog.clientWidth) : 0,
  controlOverflows:fields.filter(n => n.scrollWidth > n.clientWidth + 1).map(n => n.textContent),
  outside:!!r && (r.left < 0 || r.top < 0 || r.right > innerWidth+1 || r.bottom > innerHeight+1)};
""")
    metrics["file"] = name + ".png"
    screens.append(metrics)
    if not args.before:
        assert not metrics["outside"] and not metrics["horizontalOverflow"] and not metrics["controlOverflows"], metrics


def load(data=None):
    loaded = GLib.MainLoop()
    handler = view.connect("load-changed", lambda _view, event: loaded.quit() if event == WebKit2.LoadEvent.FINISHED else None)
    view.load_uri("magnolie-organizer://app/index.html")
    load_timeout = GLib.timeout_add_seconds(30, lambda: (loaded.quit(), False)[1])
    loaded.run()
    GLib.source_remove(load_timeout)
    view.disconnect(handler)
    evaluate("App.init(" + json.dumps({"daten": data or {}, "neu": False,
        "regional": {"language": args.locale, "timeZone": "UTC"}}) + "); return true;")
    wait(1500)


load()
results = []
completed = False
try:
    for kind in ("appointments", "tasks"):
        for edit in (False, True):
            for action in ("default", "default-hour", "hour", "minute", "wheel", "shift-wheel", "reverse-wheel", "unfocused-wheel",
                           "midnight-hour", "midnight-minute", "lower-limit", "upper-limit",
                           "partial", "empty", "partial-wheel", "empty-wheel", "keyboard-apply", "focused-apply",
                           "clear-minute", "clear-all", "minute-only", "tab-arrow-apply"):
                evaluate(f"""
const old = document.querySelector('#custom-eintrag-schleier');
if (old) {{ OrganizerTest.beendeModal(old); old.remove(); }}
const item = {{id:'entry', title:'Synthetic time test', time:'09:30',
  date:'2026-09-13', due:'2026-09-13', note:''}};
const module = {{id:'time-module', type:{json.dumps(kind)}, title:'Synthetic', items:{str(edit).lower()} ? [item] : []}};
OrganizerTest.daten().customOrganizer.modules = [module];
OrganizerTest.oeffneCustomEintrag(module, {str(edit).lower()} ? item : null);
document.querySelector('#zettel').textContent = '';
OrganizerTest.daten().einstellungen.schrift.radRichtung = 'up-earlier';
window.nativeEvents = [];
return true;
""")
                initial = snapshot()
                expected = "09:30" if edit else evaluate("return OrganizerTest.vorgabeZeiten().zeit;")
                if action not in ("default", "default-hour"):
                    start = "" if action in ("partial", "empty", "partial-wheel", "empty-wheel", "minute-only") else (
                        "23:00" if action == "midnight-hour" else "00:59" if action == "midnight-minute" else
                        "00:00" if action == "lower-limit" else "23:55" if action == "upper-limit" else "09:30")
                    evaluate(f"document.querySelector({json.dumps(field)}).value = {json.dumps(start)}; return true;")
                    expected = start
                click(field)
                if action in ("default-hour", "hour", "keyboard-apply", "focused-apply"):
                    xdo("key", "1", "0")
                    expected = "10:30"
                if action == "minute":
                    xdo("key", "Right", "4", "5")
                    expected = "09:45"
                if action == "minute-only":
                    xdo("key", "Right", "4", "5")
                if action == "tab-arrow-apply":
                    xdo("key", "Up", "Tab")
                    expected = "10:30"
                    # Tab through the native minute segment and remaining form controls.
                    for _ in range(14):
                        if evaluate(f"return document.activeElement === document.querySelector({json.dumps(apply)});"):
                            break
                        xdo("key", "Tab")
                    assert evaluate(f"return document.activeElement === document.querySelector({json.dumps(apply)});")
                if action in ("midnight-hour", "midnight-minute"):
                    xdo("key", *( ["Right", "Up"] if action == "midnight-minute" else ["Up"] ))
                    expected = "00:00"
                if action in ("partial", "partial-wheel"):
                    xdo("key", "1", "0")
                if action in ("clear-minute", "clear-all"):
                    xdo("key", "Right", "BackSpace")
                    if action == "clear-all":
                        xdo("key", "Left", "BackSpace")
                        expected = ""
                if action in ("wheel", "shift-wheel", "reverse-wheel", "lower-limit", "upper-limit", "partial-wheel", "empty-wheel"):
                    if action == "reverse-wheel":
                        evaluate("OrganizerTest.daten().einstellungen.schrift.radRichtung = 'up-later'; return true;")
                    if action == "shift-wheel":
                        xdo("keydown", "Shift_L")
                    xdo("click", 5 if action == "upper-limit" else 4)
                    if action == "shift-wheel":
                        xdo("keyup", "Shift_L")
                    expected = {"wheel":"09:25", "shift-wheel":"08:30", "reverse-wheel":"09:35"}.get(action, expected)
                if action == "unfocused-wheel":
                    evaluate(f"document.querySelector({json.dumps(apply)}).focus(); return true;")
                    xdo("click", 4)
                    assert not snapshot()["field"]["focused"]
                before = snapshot()
                label = kind + ("-edit-" if edit else "-new-") + action
                if kind == "appointments" and not edit and action in ("default", "default-hour", "hour", "wheel", "partial"):
                    screenshot(label + "-before-apply")
                if action == "tab-arrow-apply":
                    xdo("key", "Return")
                elif action == "keyboard-apply":
                    evaluate(f"document.querySelector({json.dumps(apply)}).focus(); return true;")
                    xdo("key", "Return")
                elif action == "focused-apply":
                    assert before["field"]["focused"]
                    evaluate(f"document.querySelector({json.dumps(apply)}).click(); return true;")
                else:
                    click(apply)
                after = snapshot()
                results.append({"case":label, "initial":initial, "before":before, "after":after})
                if kind == "appointments" and not edit and action in ("default-hour", "hour", "partial"):
                    screenshot(label + "-after-apply")
                if not args.before:
                    assert after["browserReports"] == 0, label
                    assert initial["field"]["value"] == ("09:30" if edit else evaluate("return OrganizerTest.vorgabeZeiten().zeit;")), label
                    if action in ("partial", "partial-wheel", "clear-minute", "minute-only"):
                        assert before["field"]["bad"] and not before["field"]["value"], (label, before)
                        assert after["field"] and after["items"] == initial["items"], (label, after)
                        assert after["feedback"] == evaluate("return MagnolieI18n.gettext('Enter both hours and minutes, or leave the time completely empty.');"), (label, after)
                        assert after["feedbackVisible"], label
                    else:
                        assert before["field"]["value"] == expected, (label, before, expected)
                        assert after["field"] is None and after["items"][0]["time"] == expected, (label, after, expected)
                        assert after["items"][0]["date" if kind == "appointments" else "due"] == "2026-09-13", label
                        evaluate("OrganizerTest.speichereJetzt(); return true;")
                        wait()
                        assert evaluate("return timeSaves.at(-1).customOrganizer.modules[0].items[0].time;") == expected, label
                    if "wheel" in action or action in ("lower-limit", "upper-limit"):
                        assert any(e["kind"] == "wheel" and e["trusted"] for e in before["events"]), label
    for action in ("wheel", "shift-wheel", "reverse-wheel", "hour", "midnight", "unfocused-wheel"):
        evaluate("""
const old = document.querySelector('#custom-eintrag-schleier') || document.querySelector('#termin-schleier');
if (old) { OrganizerTest.beendeModal(old); old.remove(); }
OrganizerTest.oeffneTerminBlatt(null, '2026-09-13');
OrganizerTest.daten().einstellungen.schrift.radRichtung = 'up-earlier';
window.nativeEvents = [];
return true;
""")
        click("#tb-zeit")
        if action == "reverse-wheel":
            evaluate("OrganizerTest.daten().einstellungen.schrift.radRichtung = 'up-later'; return true;")
        if action == "shift-wheel":
            xdo("keydown", "Shift_L")
        if action == "unfocused-wheel":
            evaluate("document.querySelector('#tb-endzeit').focus(); return true;")
        if "wheel" in action:
            xdo("click", 4)
        if action == "shift-wheel":
            xdo("keyup", "Shift_L")
        if action == "hour":
            xdo("key", "1", "0")
        if action == "midnight":
            evaluate("document.querySelector('#tb-zeit').value = '23:00'; return true;")
            xdo("key", "Up")
        state = evaluate("""
return {time:document.querySelector('#tb-zeit').value, end:document.querySelector('#tb-endzeit').value,
  date:document.querySelector('#tb-datum-von').value, events:nativeEvents};
""")
        results.append({"case":"calendar-" + action, "after":state})
        screenshot("calendar-" + action)
        if not args.before:
            assert state["time"] == {"wheel":"09:25", "shift-wheel":"08:30", "reverse-wheel":"09:35",
                                     "hour":"10:30", "midnight":"00:00", "unfocused-wheel":"09:30"}[action], (action, state)
            assert evaluate("return OrganizerTest.datumswert(document.querySelector('#tb-datum-von'));") == "2026-09-13", state
            if "wheel" in action or action == "hour":
                assert state["end"] == {"wheel":"09:55", "shift-wheel":"09:00", "reverse-wheel":"10:05",
                                        "hour":"11:00", "unfocused-wheel":"10:00"}[action], (action, state)
    # Persist through the actual bridge payload, then reload the entire frontend.
    # The transport is inert; only a synthetic saved document crosses the restart.
    if not args.before:
        old_plans = [{"id": "restart-" + status, "kontaktId": "synthetic",
            "nummer": "+12025550123", "land": "US", "text": "Synthetic " + status,
            "zeit": 1, "status": status, "clientRef": "plan:restart-" + status if status != "planned" else "",
            "fehler": ""} for status in ("planned", "queued", "uncertain")]
        load({"smsPlanung": old_plans})  # Upgrade: preference is absent, even with overdue plans.

        def sms_open():
            return evaluate("""
App.telefonStand({enabled:false, peers:[], kdeconnect:{available:false}});
App.telefonAntwort({nummer:'+12025550123', device_id:'b'.repeat(32)});
window.scheduleButton = [...document.querySelectorAll('.sms-komponist > button')]
  .find(b => b.textContent === MagnolieI18n.gettext('Schedule'));
document.querySelector('.sms-praegung').click();
return {enabled:OrganizerTest.daten().einstellungen.adressen.smsSchedulingEnabled,
  hidden:getComputedStyle(scheduleButton).display === 'none',
  checked:document.querySelector('.sms-einstellungen-dialog input[type="checkbox"]').checked,
  plans:OrganizerTest.daten().smsPlanung};
""")

        def no_send():
            commands = evaluate("return testCommands;")
            assert not any("senden" in cmd or "send" in cmd for cmd in commands), commands
            assert not any(cmd in ("telefon_freigabe", "personal_sync_senden") for cmd in commands), commands
            return commands

        initial_sms = sms_open()
        assert initial_sms == {"enabled": False, "hidden": True, "checked": False, "plans": old_plans}, initial_sms
        evaluate("scheduleButton.click(); return true;")
        assert not evaluate("return !!document.querySelector('.sms-planung-dialog');"), "disabled handler must reject direct invocation"
        screenshot("sms-upgrade-off-settings")
        for enabled in (True, False):
            click('.sms-einstellungen-dialog input[type="checkbox"]', 6)
            assert evaluate("return OrganizerTest.daten().einstellungen.adressen.smsSchedulingEnabled;") is enabled
            assert evaluate("return getComputedStyle(scheduleButton).display === 'none';") is not enabled
            assert evaluate("return OrganizerTest.daten().smsPlanung;") == old_plans
            screenshot("sms-settings-" + ("on" if enabled else "off"))
            evaluate("OrganizerTest.speichereJetzt(); return true;")
            wait(200)
            saved = evaluate("return timeSaves.at(-1);")
            assert saved["einstellungen"]["adressen"]["smsSchedulingEnabled"] is enabled
            commands = no_send()
            load(saved)
            restored = sms_open()
            assert restored == {"enabled": enabled, "hidden": not enabled, "checked": enabled, "plans": old_plans}, restored
            results.append({"case": "sms-restart-" + str(enabled).lower(), "after": restored, "commands": commands})
        # Reviewing retained plans while disabled is possible from SMS settings.
        evaluate("""
[...document.querySelectorAll('.sms-einstellungen-dialog button')]
  .find(b => b.textContent === MagnolieI18n.gettext('Pending SMS messages')).click();
return true;
""")
        assert evaluate("return document.querySelectorAll('.sms-planung-eintrag').length;") == 3
        assert not evaluate("return !!document.querySelector('.sms-planung-zeile');")
        screenshot("sms-paused-plans")
        evaluate("""
App.telefonStand({enabled:false, peers:[], kdeconnect:{available:true, device_id:'b'.repeat(32)}});
OrganizerTest.pruefeSmsPlanung();
return true;
""")
        assert evaluate("return OrganizerTest.daten().smsPlanung;") == old_plans
        results.append({"case":"sms-disabled-overdue-with-phone", "commands":no_send()})

    if args.all_locales and not args.before:
        load()
        for catalog in sorted((web / "i18n").glob("*.js")):
            evaluate(catalog.read_text() + "; return true;")
        contract = json.loads((Path(__file__).resolve().parents[2] / "contracts/ui-bugfixes.json").read_text())["translations"]
        for locale, translations in contract.items():
            evaluate(f"MagnolieI18n.setLocale({json.dumps(locale)}); return true;")
            sms_open()
            labels = evaluate("""
const dialog = document.querySelector('.sms-einstellungen-dialog');
return [dialog.querySelector('label.hak').textContent.trim(),
  dialog.querySelector('.einst-hinweis').textContent,
  document.querySelector('.sms-planung-hinweis').textContent];
""")
            assert labels == translations[:3], (locale, labels)
            screenshot("labels-" + locale + "-sms")
            evaluate("""
for (let i=0; i<3; i++) document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
const module = {id:'locale-time', type:'tasks', title:'Synthetic', items:[]};
OrganizerTest.daten().customOrganizer.modules = [module];
OrganizerTest.oeffneCustomEintrag(module);
document.querySelector('#custom-eintrag-schleier input[type="time"]').value = '';
return true;
""")
            click(field)
            xdo("key", "1", "0")
            # Real incomplete native input; never fabricate validity.badInput.
            assert snapshot()["field"]["bad"], locale
            click(apply)
            state = snapshot()
            translated = evaluate("return MagnolieI18n.gettext('Enter both hours and minutes, or leave the time completely empty.');")
            assert state["feedback"] == translated and state["feedbackVisible"] and state["browserReports"] == 0, (locale, state)
            assert state["field"]["invalid"] == "true" and state["field"]["describedBy"] == "custom-zeit-fehler"
            assert state["field"]["label"] == evaluate("return MagnolieI18n.gettext('Time');"), locale
            if locale != "en":
                assert translated != "Enter both hours and minutes, or leave the time completely empty.", locale
            screenshot("labels-" + locale + "-time")
            results.append({"case":"localized-native-validation-" + locale, "after":state, "smsLabels":labels})
            evaluate("const old = document.querySelector('#custom-eintrag-schleier'); OrganizerTest.beendeModal(old); old.remove(); return true;")
        no_send()
    completed = True
    print(f"{len(results)} native cases completed; {len(screens)} screens; "
          f"{time.monotonic() - started:.1f}s: {web} ({args.locale})", flush=True)
finally:
    report = {"web":str(web), "sha256":hashlib.sha256((web / "anwendung.js").read_bytes()).hexdigest(),
              "webkit":[WebKit2.get_major_version(), WebKit2.get_minor_version(), WebKit2.get_micro_version()],
              "cpus":sorted(os.sched_getaffinity(0)), "before":args.before, "locale":args.locale,
              "wallSeconds":round(time.monotonic() - started, 3),
              "completed":completed, "nativeKeyDelayMs":60,
              "devicesHidden":True, "softwareRendering":True, "networkIsolated":True,
              "screens":screens, "cases":results}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    window.destroy()
