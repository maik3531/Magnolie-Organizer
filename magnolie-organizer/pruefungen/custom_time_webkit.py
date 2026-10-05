"""Native X11 keyboard/wheel regression, ephemeral WebKit, inert bridge only.

Run under isolated Xvfb (never the desktop display), with --web and --output.
--before records installed/baseline behavior without applying fixed assertions.
Only the test export is injected; the time widget and handlers are unmodified.
"""
import argparse
import hashlib
import json
import locale
import mimetypes
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
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
parser.add_argument("--regional-only", action="store_true")
parser.add_argument("--tracking-only", action="store_true")
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
for method in ("register_uri_scheme_as_secure",
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
        data = data.replace(b"window.OrganizerTest = {", b"window.OrganizerTest = { eingabe, oeffneCustomEintrag, oeffneTerminBlatt, oeffneSmsPlanung, pruefeSmsPlanung, beendeModal,")
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
window.timeSheets = [];
window.testCommands = [];
window.webkit = {messageHandlers: {timeTest: {postMessage(text) {
  const message = JSON.parse(text);
  testCommands.push(message.cmd);
  if (message.cmd === 'zeit_ods') timeSheets.push(message.sheet);
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
    if (e.target.type === 'time' || e.target.classList?.contains('zeitfeld')) nativeEvents.push({kind, trusted: e.isTrusted,
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
const dialog = document.querySelector('.druck-blatt') || [...document.querySelectorAll('.eingabe-dialog')].at(-1);
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


def print_time_pdf(html, name, markers, labels, overflow=False):
    # Same native file-printer path as planner_print_files.py, inside this sandbox.
    locale.setlocale(locale.LC_MESSAGES, "C")
    Gtk.Settings.get_default().set_property("gtk-print-backends", "file")
    pdf = args.output / (name + ".pdf")
    (args.output / (name + ".html")).write_text(html)
    print_view = WebKit2.WebView.new_with_context(context)
    print_view.get_settings().set_enable_javascript(False)
    print_view.get_settings().set_print_backgrounds(True)
    print_view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
    print_window = Gtk.OffscreenWindow()
    print_window.add(print_view)
    print_window.show_all()
    loop, errors, operations = GLib.MainLoop(), [], []

    def loaded(_view, event):
        if event != WebKit2.LoadEvent.FINISHED or operations:
            return
        operation = WebKit2.PrintOperation.new(print_view)
        operations.append(operation)
        settings = Gtk.PrintSettings.new()
        settings.set_printer("Print to File")
        settings.set("output-file-format", "pdf")
        settings.set("output-uri", pdf.as_uri())
        page = Gtk.PageSetup.new()
        page.set_paper_size(Gtk.PaperSize.new("iso_a4"))
        page.set_orientation(Gtk.PageOrientation.PORTRAIT)
        settings.set_orientation(page.get_orientation())
        for side in ("top", "bottom", "left", "right"):
            getattr(page, "set_" + side + "_margin")(5 if side in ("top", "bottom") else 20, Gtk.Unit.MM)
        operation.set_page_setup(page)
        operation.set_print_settings(settings)
        operation.connect("failed", lambda _op, error: errors.append(str(error)))
        operation.connect("finished", lambda _op: loop.quit())
        operation.print_()

    print_view.connect("load-changed", loaded)
    timer = GLib.timeout_add_seconds(30, lambda: (errors.append("Print timeout"), loop.quit(), False)[-1])
    print_view.load_html(html, "magnolie-organizer://app/")
    loop.run()
    if not errors:
        GLib.source_remove(timer)
    print_window.destroy()
    assert not errors and pdf.is_file(), errors
    info = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
    text = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
    (args.output / (name + ".txt")).write_text(text)
    pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M)[1])
    assert pages > 1 if overflow else pages == 1, (name, info)
    dimensions = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts \(A4\)", info)
    assert dimensions and abs(float(dimensions[1]) - 595.28) < 1 and abs(float(dimensions[2]) - 841.89) < 1, info
    assert all(marker in text for marker in markers), (name, text)
    boxes = ET.fromstring(subprocess.check_output(["pdftotext", "-bbox", str(pdf), "-"]))
    for page in boxes.findall(".//{*}page"):
        assert all(0 <= float(word.get("xMin")) < float(word.get("xMax")) <= float(page.get("width")) and
            0 <= float(word.get("yMin")) < float(word.get("yMax")) <= float(page.get("height"))
            for word in page.findall(".//{*}word")), (name, "Text outside the paper")
    page_texts = [page for page in text.split("\f") if page.strip()]
    shaped = any("\u0900" <= char <= "\u097f" or "\u0600" <= char <= "\u06ff" or "\u3000" <= char <= "\u9fff"
        for char in labels["columns"][2])
    if shaped:
        # Poppler drops some Indic/CJK glyph mappings and reorders Arabic. Keep
        # raster evidence instead of treating its plain-text output as glyph loss.
        assert labels["columns"][2] in html and labels["signature"] in html
        subprocess.run(["pdftoppm", "-singlefile", "-r", "120", "-png", str(pdf), str(pdf.with_suffix(""))],
            check=True, capture_output=True, timeout=30)
    else:
        assert all(labels["columns"][2] in page for page in page_texts), (name, "Missing repeated column header")
        assert labels["signature"] in page_texts[-1] and labels["total"] in page_texts[-1]
        assert all(labels["signature"] not in page and labels["total"] not in page for page in page_texts[:-1])
    return {"case": name, "pages": pages, "complete": True, "labelsExtractable": not shaped}


load()
results = []
completed = False
try:
    if args.tracking_only:
        click("#deckel", offset=200)
        wait(1000)
        evaluate("""
MagnolieI18n.setLocale('en');
const d = OrganizerTest.daten();
Object.assign(d.einstellungen.regional, {formatLocale:'en-US', hourCycle:'h12', timeZone:'UTC'});
d.zeiterfassung = {enabled:true, actor:'11111111-1111-4111-8111-111111111111', counter:1, conflicts:{}, reportName:'Synthetic name',
  entries:[{id:'22222222-2222-4222-8222-222222222222',startMinute:Date.parse('2026-09-13T08:00:00Z')/60000,
    endMinute:Date.parse('2026-09-13T17:00:00Z')/60000,pauseMinute:null,pauseMinutes:30,zone:'UTC',
    type:'Recorded activity',note:'Synthetic time record',modifiedMs:1,deleted:false,
    clock:{'11111111-1111-4111-8111-111111111111':1},pausePlan:null}]};
OrganizerTest.wechsel('planer'); OrganizerTest.wechsel('kalender');
return true;
""")
        screenshot("tracking-calendar")
        click('.zeit-marke[data-zeit-tag="2026-09-13"]')
        click("#zeit-von-zeit")
        xdo("key", "ctrl+a")
        xdo("type", "--clearmodifiers", "--delay", "60", "08:15 AM")
        xdo("key", "Tab")
        assert evaluate("return document.querySelector('#zeit-von-zeit').value;") == "08:15"
        click("#zeit-dauer")
        xdo("key", "ctrl+a")
        xdo("type", "--clearmodifiers", "--delay", "60", "168:30")
        assert evaluate("return document.querySelector('#zeit-bis-zeit').value;") == "09:15"
        screenshot("tracking-editor")
        click("#zeit-editor-schleier .hauptknopf")
        assert not evaluate("return !!document.querySelector('#zeit-editor-schleier');")
        evaluate("OrganizerTest.speichereJetzt(); return true;")
        wait(300)
        saved = evaluate("return timeSaves.at(-1);")
        entry = saved["zeiterfassung"]["entries"][0]
        assert entry["endMinute"] - entry["startMinute"] - entry["pauseMinutes"] == 168 * 60 + 30
        assert not saved["termine"]
        load(saved)
        assert evaluate("return OrganizerTest.daten().zeiterfassung.entries[0].id;") == entry["id"]
        evaluate("""
OrganizerTest.zustand().planer.jahr=2026; OrganizerTest.zustand().kalender.monat=8;
OrganizerTest.oeffneDruckvorschau(null,'planer'); return true;
""")
        click("#planer-druck-art")
        xdo("key", "End", "Return")
        assert evaluate("return document.querySelector('#planer-druck-art').value;") == "time"
        screenshot("tracking-print")
        click("#zeit-druck-alle-tage", offset=6)
        assert evaluate("return document.querySelector('#druck-schleier .ods-knopf').disabled;")
        click('[data-zeit-druck-tag="13"]', offset=6)
        screenshot("tracking-print-selected")
        click("#druck-schleier .ods-knopf")
        sheet = evaluate("return timeSheets.at(-1);")
        assert sheet["month"] == "2026-09" and sheet["days"] == [13]
        assert sheet["entries"][0]["id"] == entry["id"]
        (args.output / "time-sheet-payload.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2))
        results.append({"case":"tracking-calendar-keyboard-restart-ods", "entry":entry, "month":sheet["month"]})
        cases = [(None, 1, "tracking-month"), (None, 3, "tracking-overflow"), (None, 0, "tracking-long-note")]
        if args.all_locales:
            for catalog in sorted((web / "i18n").glob("*.js")):
                evaluate(catalog.read_text() + "; return true;")
            cases.extend((language, 1, "tracking-month-" + language) for language in
                ("en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "nl-NL", "pt-PT", "ru-RU", "cs-CZ", "pl-PL",
                 "hsb-DE", "da-DK", "nb-NO", "hi-IN", "zh-CN", "ja-JP", "ar-EG", "uk-UA", "be-BY", "tr-TR"))
        for language, count, name in cases:
            if language:
                evaluate("MagnolieI18n.setLocale(" + json.dumps(language) + "); Object.assign(OrganizerTest.daten().einstellungen.regional, " +
                    json.dumps({"formatLocale": language, "hourCycle": "h12"}) + "); return true;")
            rendered = evaluate("""
const sheet = OrganizerTest.zeitOdsNutzlast(2026,9).sheet;
const source = OrganizerTest.daten().zeiterfassung.entries[0]; sheet.entries = [];
for (let day=1; day<=31; day++) for (let slot=0; slot<""" + str(count) + """; slot++) {
  const start = Date.UTC(2026,9,day,6+slot*5)/60000;
  sheet.entries.push({...source, id:crypto.randomUUID(), startMinute:start, endMinute:start+270,
    localStartMinute:start, localEndMinute:start+270, pauseMinutes:30, note:'',
    type:'ENTRY-'+String(sheet.entries.length+1).padStart(3,'0')});
}
let markers=[];
if(!sheet.entries.length) {
  markers=Array.from({length:160},(_,i)=>'LINE-'+String(i+1).padStart(3,'0'));
  const start=Date.UTC(2026,9,13,8)/60000; sheet.days=[13];
  sheet.entries=[{...source,id:crypto.randomUUID(),startMinute:start,endMinute:start+270,
    localStartMinute:start,localEndMinute:start+270,pauseMinutes:30,zone:'UTC',note:markers.join('\\n'),type:'LONGNOTE'}];
}
const html=OrganizerTest.zeitDruckSeite(sheet);
const parsed=new DOMParser().parseFromString(html,'text/html');
const printed=Array.from(parsed.querySelectorAll('tbody tr:not(.totals)'));
if (printed.length!==Math.max(40,sheet.entries.length)) throw new Error('Timesheet record rows lost or duplicated');
if (parsed.querySelector('thead tr:last-child').children.length!==6) throw new Error('Template must have six visible columns');
if (html.includes('ENTRY-') || html.includes('LINE-')) throw new Error('Internal record details leaked into compact timesheet');
return {html, markers:[], labels:sheet.labels};
""")
            results.append(print_time_pdf(rendered["html"], name, rendered["markers"], rendered["labels"], overflow=count > 1))
        completed = True
        print(f"Native time-tracking calendar, keyboard, restart and ODS handoff passed: {web}", flush=True)
        sys.exit(0)
    if args.regional_only:
        regional_field = '#custom-eintrag-schleier .zeitfeld'
        for catalog in sorted((web / "i18n").glob("*.js")):
            evaluate(catalog.read_text() + "; return true;")
        roundtrips = evaluate("""
let count = 0;
for (const locale of ['en-US','de-DE','fr-FR','es-ES','it-IT','nl-NL','pt-PT','ru-RU','cs-CZ','pl-PL',
  'hsb-DE','da-DK','nb-NO','hi-IN','zh-CN','ja-JP','ar-EG','uk-UA','be-BY','tr-TR']) {
  MagnolieI18n.setLocale(locale);
  Object.assign(OrganizerTest.daten().einstellungen.regional, {formatLocale:locale, hourCycle:'h12'});
  for (const time of ['00:00','00:35','11:59','12:00','14:35','23:59']) {
    const field = OrganizerTest.eingabe('time', time);
    const visible = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').get.call(field);
    if (field.value !== time || !field.checkValidity()) throw new Error(locale + ': ' + time + ' -> ' + visible + ' -> ' + field.value);
    count++;
  }
}
return count;
""")
        results.append({"case": "twenty-language-native-roundtrip", "count": roundtrips})
        evaluate("MagnolieI18n.setLocale('en'); Object.assign(OrganizerTest.daten().einstellungen.regional, {formatLocale:'en-US', hourCycle:'h12'}); return true;")
        for kind in ("appointments", "tasks"):
            for text, expected in (("12:05 AM", "00:05"), ("12:05 PM", "12:05"),
                                   ("02:35 PM", "14:35"), ("02:35", None), ("", "")):
                evaluate("""
const old = document.querySelector('#custom-eintrag-schleier');
if (old) { OrganizerTest.beendeModal(old); old.remove(); }
const item = {id:'entry', title:'Synthetic', time:'14:35', date:'2026-10-04', due:'2026-10-04', note:''};
const module = {id:'regional', type:""" + json.dumps(kind) + """, title:'Synthetic', items:[item]};
OrganizerTest.daten().customOrganizer.modules = [module];
OrganizerTest.oeffneCustomEintrag(module, item);
window.nativeEvents = [];
return true;
""")
                click(regional_field)
                xdo("key", "ctrl+a")
                if text:
                    xdo("type", "--clearmodifiers", "--delay", "60", text)
                else:
                    xdo("key", "BackSpace")
                state = evaluate("""
const field = document.querySelector('#custom-eintrag-schleier .zeitfeld');
return {value:field.value, valid:field.checkValidity(),
  visible:Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').get.call(field), events:nativeEvents};
""")
                assert state["visible"] == text, state
                assert any(event["kind"] == "input" and event["trusted"] for event in state["events"]), state
                if expected is not None:
                    assert state["valid"] and state["value"] == expected, state
                else:
                    assert not state["valid"], state
                if text == "02:35 PM":
                    screenshot("regional-" + kind)
                click(apply)
                after = evaluate("return {open:!!document.querySelector('#custom-eintrag-schleier'), time:OrganizerTest.daten().customOrganizer.modules[0].items[0].time};")
                assert after == {"open": expected is None, "time": "14:35" if expected is None else expected}, after
                results.append({"kind": kind, "typed": text, "before": state, "after": after})
        completed = True
        print(f"{len(results)} trusted-input regional time cases passed: {web}", flush=True)
        sys.exit(0)
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
