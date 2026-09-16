"""Native Tab/undo + storage and geometry checks of the actual source UI.

Use text_editor_isolated.sh --web linux|windows. No application backend is run.
Keyboard input uses XTest; selection setup and negative composition guards use
DOM APIs. All fixture data and captured bridge saves are synthetic.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urlsplit

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2

parser = argparse.ArgumentParser()
parser.add_argument("--web", choices=("linux", "windows"), required=True)
args = parser.parse_args()
assert os.environ.get("MAGNOLIE_EDITOR_ISOLATED") == "1"
assert not Path("/dev/dri").exists() and not list(Path("/dev").glob("nvidia*"))
assert len(os.sched_getaffinity(0)) <= 2
web = Path("/home/source") / args.web
output = Path("/tmp/evidence") / args.web
output.mkdir(exist_ok=True)
started = time.monotonic()
results, screens = [], []
Gtk.init([])
context = WebKit2.WebContext.new_ephemeral()
for method in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure",
               "register_uri_scheme_as_display_isolated"):
    getattr(context.get_security_manager(), method)("magnolie-organizer")


def serve(request):
    name = urlsplit(request.get_uri()).path.lstrip("/")
    if name == "i18n-active.js":
        name = "i18n/de.js"
    asset = (web / name).resolve()
    if not asset.is_relative_to(web) or not asset.is_file():
        request.finish_error(GLib.Error("Missing fixture asset"))
        return
    data = asset.read_bytes()
    if name == "anwendung.js":
        data = data.replace(b"window.OrganizerTest = {", b"window.OrganizerTest = { bindeSchreibTab, htmlZuText, textZuHtml, beendeModal,")
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data),
                   mimetypes.guess_type(name)[0] or "application/octet-stream")


context.register_uri_scheme("magnolie-organizer", serve)
view = WebKit2.WebView.new_with_context(context)
view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
view.get_settings().set_enable_write_console_messages_to_stdout(True)
view.get_user_content_manager().add_script(WebKit2.UserScript.new("""
window.__MAGNOLIE_SPRACHE__ = 'de';
window.__MAGNOLIE_BRUECKE__ = 'editorTest';
window.saves = []; window.commands = []; window.events = [];
window.webkit = {messageHandlers:{editorTest:{postMessage(raw) {
  const message = JSON.parse(raw); commands.push(message);
  if (message.cmd === 'speichern') {
    saves.push(JSON.parse(message.text));
    setTimeout(() => App.gespeichert({id:message.id, ok:true}), 0);
  }
}}}};
for (const kind of ['keydown','beforeinput','input','compositionstart','compositionend','touchstart'])
  document.addEventListener(kind, e => events.push({kind, key:e.key, trusted:e.isTrusted,
    code:e.code, keyCode:e.keyCode, shift:e.shiftKey, ctrl:e.ctrlKey,
    data:e.data, inputType:e.inputType, target:e.target.id || e.target.className}), true);
""", WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
window = Gtk.Window(title="Synthetic editor usability checks")
window.set_default_size(1280, 1000)
window.add(view)
window.show_all()


def wait(ms=160):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


def js(script):
    loop, result = GLib.MainLoop(), []
    def done(obj, task, _):
        try:
            result.append(json.loads(obj.evaluate_javascript_finish(task).to_string()))
        except Exception as error:
            result.append(error)
        loop.quit()
    view.evaluate_javascript("JSON.stringify((() => {" + script + "})())", -1,
                             None, None, None, done, None)
    timer = GLib.timeout_add_seconds(12, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timer)
    assert result and not isinstance(result[0], Exception), result
    return result[0]


def key(*keys):
    for stroke in keys:
        offset = js("return events.length;")
        expected = {"Return":"Enter", "space":" ", "Left":"ArrowLeft", "Right":"ArrowRight"}.get(stroke.split("+")[-1], stroke.split("+")[-1])
        subprocess.run(["xdotool", "key", "--delay", "65", stroke], check=True, timeout=10)
        for _ in range(20):
            wait(100)
            if js(f"return events.slice({offset}).some(e => e.kind==='keydown' && (e.key.toLowerCase()==={json.dumps(expected.lower())} || ({json.dumps(expected)}==='Tab' && e.code==='Tab')));"):
                break
        else:
            raise AssertionError(("native key not delivered", stroke, js("return events.slice(-12);")))
        wait(150)


def load(data=None):
    loop = GLib.MainLoop()
    handler = view.connect("load-changed", lambda _, event: loop.quit() if event == WebKit2.LoadEvent.FINISHED else None)
    view.load_uri("magnolie-organizer://app/index.html")
    timer = GLib.timeout_add_seconds(25, lambda: (loop.quit(), False)[1])
    loop.run()
    GLib.source_remove(timer)
    view.disconnect(handler)
    js("App.init(" + json.dumps({"daten": data or {}, "neu": False,
        "regional": {"language": "de", "timeZone": "UTC"}}) + "); OrganizerTest.oeffneBuch(); return true;")
    wait(700)


def screen(name):
    wait(1100)
    pixbuf = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
        window.get_allocated_width(), window.get_allocated_height())
    pixbuf.savev(str(output / (name + ".png")), "png", [], [])
    screens.append(name + ".png")


def setup(kind, text="AlphaBeta", html=None):
    load()
    js("""
const d = OrganizerTest.daten();
d.notizen = [{id:'note-stable', titel:'Synthetic note', text:'', html:'', anhaenge:[]}];
d.einstellungen.allgemein.customTab.enabled = true;
d.customOrganizer.modules = [{id:'module-stable',type:'notes',title:'Synthetic text',page:'left',order:0,
 items:[{id:'text-stable',title:'Synthetic text',text:'',html:''}]}];
return true;
""")
    if kind == "note":
        js("OrganizerTest.zustand().notizen.auswahlId = 'note-stable'; OrganizerTest.wechsel('notizen'); return true;")
        selector = "#notiz-text"
    elif kind == "custom":
        js("OrganizerTest.wechsel('custom'); return true;")
        selector = ".custom-text-editor"
    else:
        js("OrganizerTest.oeffneTerminBlatt(null, '2026-09-14'); document.querySelector('#tb-titel').value = 'Synthetic diary'; return true;")
        selector = "#tb-notiz"
    wait()
    js("window.field = document.querySelector(" + json.dumps(selector) + "); return !!field;")
    reset(text, html)


def reset(text, html=None, start=None, end=None):
    start = len(text) if start is None else start
    end = start if end is None else end
    js("""
field.focus();
if (field.tagName === 'TEXTAREA') { field.value = __TEXT__; field.setSelectionRange(START, END); }
else {
  field.innerHTML = __HTML__ === null ? OrganizerTest.textZuHtml(__TEXT__) : __HTML__;
  const walker = document.createTreeWalker(field, NodeFilter.SHOW_TEXT), nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const point = offset => {for (const n of nodes) {if (offset <= n.length) return [n, offset]; offset -= n.length;} return [field,0];};
  const r = document.createRange(); r.setStart(...point(START)); r.setEnd(...point(END));
  getSelection().removeAllRanges(); getSelection().addRange(r);
}
window.events = [];
return true;
""".replace("__TEXT__", json.dumps(text)).replace("__HTML__", json.dumps(html))
       .replace("START", str(start)).replace("END", str(end)))


def state():
    return js("""return {text:field.tagName === 'TEXTAREA' ? field.value : OrganizerTest.htmlZuText(field),
html:field.innerHTML, focus:document.activeElement === field, events,
start:field.selectionStart, end:field.selectionEnd,
hint:document.getElementById(field.getAttribute('aria-describedby'))?.textContent};""")


completed = False
try:
    for kind in ("note", "custom", "diary"):
        setup(kind)
        for name, text, start, end, expected in (
            ("middle", "AlphaBeta", 5, 5, "Alpha\tBeta"),
            ("selection", "AlphaBeta", 0, 5, "\tBeta"),
            ("empty", "", 0, 0, "\t"),
            ("repeated", "\tAlpha\t", 7, 7, "\tAlpha\t\t"),
        ):
            reset(text, start=start, end=end)
            key("Tab")
            after = state()
            assert after["text"] == expected and after["focus"], (kind, name, after)
            inputs = [e for e in after["events"] if e["kind"] == "input"]
            assert len(inputs) == 1 and inputs[0]["trusted"], (kind, name, inputs)
            assert len([e for e in after["events"] if e["kind"] == "beforeinput"]) == 1, after
            assert any(e["kind"] == "keydown" and e["key"] == "Tab" and e["trusted"] for e in after["events"])
            key("ctrl+z")
            assert state()["text"] == text, (kind, name, "undo", state())
            key("ctrl+shift+z")
            assert state()["text"] == expected, (kind, name, "redo", state())
            key("shift+Tab")
            assert not state()["focus"] and state()["text"] == expected, (kind, name, "leave")
            js("field.focus(); return true;")
            key("ctrl+Tab")
            assert not state()["focus"] and state()["text"] == expected, (kind, name, "leave-forward")
            if kind == "diary":
                assert js("return !!document.activeElement.closest('.termin-blatt');")
            results.append({"kind":kind, "case":name, "after":after, "undoRedoLeave":True})
        if kind != "diary":
            reset("AlphaBeta", "<b>Alpha</b><i>Beta</i>", 2, 7)
            key("Tab")
            assert state()["text"] == "Al\tta" and "<b>" in state()["html"] and "<i>" in state()["html"], state()
            key("ctrl+z")
            assert state()["text"] == "AlphaBeta", state()
            results.append({"kind":kind, "case":"formatted-selection", "state":state()})
        # Real private-X clipboard paste must participate in the same native
        # history as Tab, without flattening existing rich text or line height.
        if kind != "diary":
            setup(kind, "AlphaBeta", "<b>Alpha</b><i>Beta</i>")
        reset("AlphaBeta", None if kind == "diary" else "<b>Alpha</b><i>Beta</i>", 5, 5)
        line_height = js("return getComputedStyle(field).lineHeight;")
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text("Paste\tText", -1)
        key("ctrl+v")
        pasted = state()
        assert pasted["text"] == "AlphaPaste\tTextBeta", (kind, "clipboard-paste", pasted)
        key("ctrl+z")
        assert state()["text"] == "AlphaBeta", (kind, "undo-paste-alone", state())
        key("ctrl+y")
        assert state()["text"] == "AlphaPaste\tTextBeta", (kind, "redo-paste-alone", state())
        # Native typing may coalesce adjacent insertText operations. A real
        # caret move establishes a new edit group before checking two undos.
        key("Left", "Right")
        key("Tab")
        assert state()["text"] == "AlphaPaste\tText\tBeta", (kind, "paste-then-tab", state())
        key("ctrl+z")
        assert state()["text"] == "AlphaPaste\tTextBeta", (kind, "undo-tab-after-paste", state())
        key("ctrl+z")
        assert state()["text"] == "AlphaBeta", (kind, "undo-paste", state())
        key("ctrl+y")
        assert state()["text"] == "AlphaPaste\tTextBeta", (kind, "redo-paste", state())
        if kind != "diary":
            assert "<b>" in state()["html"] and "<i>" in state()["html"], (kind, "paste-formatting", state())
        assert js("return getComputedStyle(field).lineHeight;") == line_height
        results.append({"kind":kind, "case":"native-clipboard-tab-undo-redo-format-lineheight", "state":state()})
        reset("守る Alpha")
        js("field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'あ'})); return true;")
        key("Tab")
        assert state()["text"] == "守る Alpha", state()
        js("field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'あ'})); return true;")
        reset("Read only")
        js("if(field.tagName === 'TEXTAREA') field.readOnly = true; else field.contentEditable = 'false'; return true;")
        key("Tab")
        assert state()["text"] == "Read only", state()
        js("if(field.tagName === 'TEXTAREA') field.readOnly = false; else field.contentEditable = 'true'; return true;")
        reset("Cancel")
        js("field.addEventListener('beforeinput', e => e.preventDefault(), {once:true}); return true;")
        key("Tab")
        assert state()["text"] == "Cancel" and not any(e["kind"] == "input" for e in state()["events"]), state()
        if kind != "diary":
            reset("Outside")
            js("getSelection().removeAllRanges(); return true;")
            key("Tab")
            assert state()["text"] == "Outside", state()
            reset("Outside")
            js("const n = document.createElement('span'); n.textContent='untouched'; document.body.append(n); const r = document.createRange(); r.selectNodeContents(n); getSelection().removeAllRanges(); getSelection().addRange(r); return true;")
            key("Tab")
            assert state()["text"] == "Outside", state()
        results.append({"kind":kind,"case":"composition-readonly-cancel-selection-guards","passed":True})
        reset("IME ")
        # Drive the actual native WebKit input-method context, not execCommand
        # or a synthetic InputEvent, for non-keyboard Unicode text entry.
        view.get_input_method_context().emit("committed", "日本語 العربية")
        wait(250)
        assert state()["text"] == "IME 日本語 العربية", state()
        assert any(e["kind"] == "input" and e["trusted"] for e in state()["events"]), state()
        key("Tab")
        assert state()["text"] == "IME 日本語 العربية\t", state()
        results.append({"kind":kind,"case":"native-ime-commit-then-tab","state":state()})
        reset("First")
        key("Tab", "B", "Return", "Tab", "C", "Tab")
        expected = "First\tB\n\tC\t"
        assert state()["text"] == expected, (kind, "multiline", state())
        if kind == "diary":
            js("document.querySelector('.termin-blatt .tb-fuss .hauptknopf, .termin-blatt .hauptknopf, .termin-blatt .haupt').click(); return true;")
        js("OrganizerTest.speichereJetzt(); return true;")
        wait(700)
        saved = js("return saves.at(-1);")
        assert saved, (kind, "missing save")
        (output / (kind + "-saved.json")).write_text(json.dumps(saved, ensure_ascii=False, indent=2))
        value = saved["notizen"][0]["text"] if kind == "note" else saved["customOrganizer"]["modules"][0]["items"][0]["text"] if kind == "custom" else saved["termine"][0]["notiz"]
        assert value == expected, (kind, value)
        section = {"note":"notizen","custom":"custom","diary":"kalender"}[kind]
        if kind != "diary":
            html = js(f"const s=OrganizerTest.druckStoff('{section}'); return OrganizerTest.druckSeite(s.liste,s);")
            assert "\t" in html
            (output / (kind + "-print.html")).write_text(html)
        load(saved)
        if kind == "note":
            js("OrganizerTest.zustand().notizen.auswahlId='note-stable'; OrganizerTest.wechsel('notizen'); window.field=document.querySelector('#notiz-text'); return true;")
        elif kind == "custom":
            js("OrganizerTest.wechsel('custom'); window.field=document.querySelector('.custom-text-editor'); return true;")
        else:
            js("OrganizerTest.oeffneTerminBlatt(OrganizerTest.daten().termine[0]); window.field=document.querySelector('#tb-notiz'); return true;")
        assert state()["text"] == expected, (kind, "reload", state())
        screen(kind + "-reloaded-tabs")
        results.append({"kind":kind,"case":"multiline-save-json-reload","state":state()})
    # Designer: actual localized controls, two columns at normal width, large
    # text/zoom and mobile wrap, real checkbox and modal keyboard traversal.
    load()
    js("""
OrganizerTest.daten().einstellungen.allgemein.customTab.enabled=true;
OrganizerTest.daten().customOrganizer.modules=[
 {id:'keep-note',type:'notes',title:'Synthetic text',page:'left',order:0,items:[{id:'keep-text',text:'Full\tcontent',html:'Full\tcontent'}]},
 {id:'keep-task',type:'tasks',title:'Synthetic tasks',page:'right',order:0,items:[],reminders:true},
 {id:'keep-appointment',type:'appointments',title:'Synthetic appointments',page:'right',order:1,items:[],reminders:false}];
OrganizerTest.wechsel('custom'); return true;
""")
    original = js("return JSON.stringify(OrganizerTest.daten().customOrganizer.modules);")
    locales = ["en"] + sorted(p.stem for p in (web / "i18n").glob("*.js"))
    assert len(locales) == 20, locales
    for locale in locales:
        if locale != "en":
            js((web / "i18n" / (locale + ".js")).read_text() + "; return true;")
        for width, height, zoom in ((1280,1000,1), (390,844,1), *(([(1280,1000,2)]) if locale in ("de","ar","fr") else [])):
            window.resize(width, height)
            view.set_zoom_level(zoom)
            js("MagnolieI18n.setLocale(" + json.dumps(locale) + "); OrganizerTest.oeffneCustomDesigner(); return true;")
            wait(200)
            geometry = js("""
const d=document.querySelector('.custom-designer'), r=d.getBoundingClientRect();
const columns=[...d.querySelectorAll('.custom-designer-blatt')].map(n=>n.getBoundingClientRect());
return {locale:MagnolieI18n.locale(),viewport:[innerWidth,innerHeight], width:r.width,height:r.height,
  overflow:d.scrollWidth-d.clientWidth, outside:r.left < -1 || r.right > innerWidth+1 || r.top < -1 || r.bottom > innerHeight+1,
  columns:columns.map(r=>[r.x,r.y,r.width,r.height]),
  cards:[...d.querySelectorAll('.custom-editor-karte')].map(c=>{
    const label=c.querySelector('.hak') || c.querySelectorAll('.formzeile')[2], button=c.querySelector('.custom-editor-aktionen button');
    const l=label.getBoundingClientRect(), b=button.getBoundingClientRect();
    return {gap:b.top-l.bottom,height:c.getBoundingClientRect().height,button:button.textContent,
      overflow:Math.max(c.scrollWidth-c.clientWidth,button.scrollWidth-button.clientWidth,label.scrollWidth-label.clientWidth)};
  }), hint:OrganizerTest.bindeSchreibTab(document.createElement('textarea')).textContent};
""")
            assert not geometry["outside"] and geometry["overflow"] <= 1, geometry
            assert all(c["gap"] >= 11 and c["overflow"] <= 1 for c in geometry["cards"]), geometry
            if geometry["viewport"][0] > 700:
                assert abs(geometry["columns"][0][1] - geometry["columns"][1][1]) < 1, geometry
            assert geometry["hint"] and (locale == "en" or geometry["hint"] != "Tab: insert a tab stop. Shift+Tab: previous field. Ctrl+Tab: next field."), geometry
            results.append({"case":"designer-layout","zoom":zoom,**geometry})
            if locale in ("de","ar","fr"):
                screen(f"designer-{locale}-{width}-zoom{zoom}")
                if zoom == 2:
                    js("document.querySelector('.custom-designer .hak').closest('article').scrollIntoView({block:'center'}); return true;")
                    screen(f"designer-{locale}-{width}-zoom{zoom}-remove-row")
            js("document.querySelector('.custom-designer-kopf button').click(); return true;")
    assert js("return JSON.stringify(OrganizerTest.daten().customOrganizer.modules);") == original
    window.resize(1280,1000)
    view.set_zoom_level(1)
    js("MagnolieI18n.setLocale('de'); OrganizerTest.oeffneCustomDesigner(); return true;")
    wait()
    js("window.controls=[...document.querySelector('.custom-designer').querySelectorAll('button,input,select')]; controls.at(-1).focus(); return true;")
    key("Tab")
    assert js("return document.activeElement===controls[0];")
    key("shift+Tab")
    assert js("return document.activeElement===controls.at(-1);"), js("return {active:document.activeElement.outerHTML,last:controls.at(-1).outerHTML,events:events.slice(-12)};")
    js("window.check=document.querySelector('.custom-designer input[type=checkbox]'); check.focus(); return true;")
    old = js("return check.checked;")
    key("space")
    assert js("return check.checked;") != old
    key("Tab")
    assert js("return document.activeElement===check.closest('article').querySelector('.custom-editor-aktionen button');")
    key("Escape")
    assert js("return !document.querySelector('.custom-designer');")
    results.append({"case":"native-designer-checkbox-remove-focus-modal-wrap-escape","passed":True})
    # Ordinary form fields still use browser Tab navigation.
    for selector in (".custom-suche", ".custom-text-titel"):
        js("window.other=document.querySelector(" + json.dumps(selector) + "); other.focus(); window.before=other.value; return true;")
        key("Tab")
        assert js("return document.activeElement!==other && other.value===before;")
    results.append({"case":"search-title-form-navigation","passed":True})
    # Render the existing production print HTML with the native print engine.
    Gtk.Settings.get_default().set_property("gtk-print-backends", "file")
    for kind in ("note", "custom"):
        print_view = WebKit2.WebView.new_with_context(context)
        print_view.get_settings().set_enable_javascript(False)
        print_view.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
        print_window = Gtk.OffscreenWindow()
        print_window.add(print_view)
        print_window.show_all()
        loop, operations, errors = GLib.MainLoop(), [], []
        pdf = output / (kind + "-print.pdf")
        def print_loaded(_, event):
            if event != WebKit2.LoadEvent.FINISHED or operations:
                return
            operation = WebKit2.PrintOperation.new(print_view)
            operations.append(operation)
            settings = Gtk.PrintSettings.new()
            settings.set_printer("Print to File")
            settings.set("output-file-format", "pdf")
            settings.set("output-uri", pdf.as_uri())
            operation.set_print_settings(settings)
            operation.connect("failed", lambda _, error: errors.append(str(error)))
            operation.connect("finished", lambda _: loop.quit())
            operation.print_()
        print_view.connect("load-changed", print_loaded)
        timer = GLib.timeout_add_seconds(25, lambda: (errors.append("print timeout"), loop.quit(), False)[-1])
        print_view.load_html((output / (kind + "-print.html")).read_text(), "file:///tmp/")
        loop.run()
        GLib.source_remove(timer)
        print_window.destroy()
        assert not errors and pdf.is_file(), errors
        bbox = subprocess.check_output(["pdftotext", "-bbox", str(pdf), "-"], text=True, timeout=10)
        (output / (kind + "-print-bbox.html")).write_text(bbox)
        words = {w.text: w.attrib for w in ET.fromstring(bbox).findall(".//{*}word")}
        assert all(w in words for w in ("First", "B", "C")), words
        step = float(words["C"]["xMin"]) - float(words["First"]["xMin"])
        stops = (float(words["B"]["xMin"]) - float(words["First"]["xMin"])) / step
        assert step > 5 and abs(stops - round(stops)) < .05, words
        assert float(words["B"]["xMin"]) > float(words["First"]["xMax"]), words
        assert float(words["C"]["yMin"]) > float(words["B"]["yMin"]), words
        results.append({"case":"native-print-pdf-tab-alignment","kind":kind,"words":words})
        # There is no direct note/custom ODT export in the current application.
        # Probe LibreOffice's import of the actual print HTML and of preserved
        # plain text separately, without treating the former as an app feature.
        plain = output / (kind + "-plain.txt")
        plain.write_text("First\tB\n\tC\t")
        conversion = subprocess.run(["libreoffice", "-env:UserInstallation=file:///tmp/editor-lo-profile",
            "--headless", "--convert-to", "odt", "--outdir", str(output),
            str(output / (kind + "-print.html")), str(plain)], text=True, capture_output=True, timeout=30)
        odt_counts = {}
        for suffix in ("print", "plain"):
            odt = output / (kind + "-" + suffix + ".odt")
            assert odt.is_file(), conversion.stdout + conversion.stderr
            with zipfile.ZipFile(odt) as archive:
                xml = archive.read("content.xml")
                (output / (kind + "-" + suffix + "-odt.xml")).write_bytes(xml)
                root = ET.fromstring(xml)
                odt_counts[suffix] = len(root.findall(".//{urn:oasis:names:tc:opendocument:xmlns:text:1.0}tab"))
        assert odt_counts["plain"] == 3, odt_counts
        results.append({"case":"libreoffice-odt-import-probe","kind":kind,"semanticTabs":odt_counts})
    completed = True
finally:
    report = {"completed":completed,"web":args.web,"seconds":round(time.monotonic()-started,2),
      "engine":f"WebKitGTK {WebKit2.MAJOR_VERSION}.{WebKit2.MINOR_VERSION}.{WebKit2.MICRO_VERSION}",
      "cpuAffinity":sorted(os.sched_getaffinity(0)),"sourceSha256":{
          name:hashlib.sha256((web/name).read_bytes()).hexdigest() for name in ("anwendung.js","stil.css")},
      "results":results,"screenshots":screens}
    (output / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({key:value for key,value in report.items() if key != "results"},ensure_ascii=False,indent=2))
    window.destroy()
