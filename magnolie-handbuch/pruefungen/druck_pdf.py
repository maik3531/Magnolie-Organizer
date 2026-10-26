#!/usr/bin/env python3
"""Paginate in native WebKit and exercise the product's semantic PDF print path."""

import os
import sys
import gettext
import json
import importlib.machinery
import importlib.util

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gio, GLib, Gtk, WebKit2

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "bin")))
from magnolie_asset import read_handbook_request


def haupt():
    if len(sys.argv) != 2:
        sys.stderr.write("Aufruf: druck_pdf.py ZIEL.pdf\n")
        return 2

    nur_layout = sys.argv[1] == "--layout-only"
    ziel = os.path.abspath(sys.argv[1])
    sprache = os.environ.get("MAGNOLIE_HANDBUCH_TEST_LANGUAGE", "de")
    druck_optionen = {}
    if os.environ.get("MAGNOLIE_HANDBUCH_TEST_RESERVE_MM"):
        druck_optionen["reserveMm"] = float(os.environ["MAGNOLIE_HANDBUCH_TEST_RESERVE_MM"])
    web = os.environ.get(
        "MAGNOLIE_HANDBUCH_WEB",
        os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "web")),
    )
    start = os.path.join(web, "index.html")
    if not os.path.isfile(start):
        sys.stderr.write("Handbuch nicht gefunden: %s\n" % start)
        return 2

    schleife = GLib.MainLoop()
    status = {"code": 1}
    # The process-local context owns the Python URI callback and can be torn
    # down with the two views instead of surviving into interpreter shutdown.
    kontext = WebKit2.WebContext.new_ephemeral()
    def ressource(anfrage):
        try:
            antwort = read_handbook_request(anfrage.get_uri(), web)
        except (OSError, ValueError):
            antwort = None
        daten, mime = antwort or (b"", "text/plain")
        anfrage.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(daten)), len(daten), mime)
    kontext.register_uri_scheme("magnolie-handbuch", ressource)
    sicherheit = kontext.get_security_manager()
    for methode in ("register_uri_scheme_as_local", "register_uri_scheme_as_secure",
                    "register_uri_scheme_as_display_isolated"):
        try:
            getattr(sicherheit, methode)("magnolie-handbuch")
        except AttributeError:
            pass
    ansicht = WebKit2.WebView.new_with_context(kontext)
    druckansicht = WebKit2.WebView.new_with_context(kontext)
    nativer_weg = not nur_layout
    ansicht.get_user_content_manager().add_script(WebKit2.UserScript.new(
        "window.MAGNOLIE_NATIVE_SEMANTIC_PDF = true;", WebKit2.UserContentInjectedFrames.TOP_FRAME,
        WebKit2.UserScriptInjectionTime.START, ["magnolie-handbuch://app/*"], None))
    notes_probe = os.environ.get("MAGNOLIE_HANDBUCH_TEST_NOTES") == "1"
    fenster = Gtk.Window() if nativer_weg or notes_probe else None
    if fenster:
        fenster.set_default_size(1280, 860)
        fenster.add(ansicht)
        fenster.show_all()

    def beenden(code, meldung=None):
        if status.get("beendet"):
            return
        status["beendet"] = True
        status["code"] = code
        if meldung:
            sys.stderr.write(meldung + "\n")
        for dialog in Gtk.Window.list_toplevels():
            if dialog.__gtype__.name == "GtkPrintUnixDialog":
                dialog.response(Gtk.ResponseType.CANCEL)
        schleife.quit()

    def bei_druckfehler(_auftrag, fehler):
        beenden(1, "Drucken fehlgeschlagen: %s" % fehler.message)

    def bei_druckende(_auftrag):
        beenden(0)

    def layout_geprueft(_ansicht, ergebnis, _daten):
        try:
            werte = json.loads(_ansicht.evaluate_javascript_finish(ergebnis).to_string())
            erwartet = "rtl" if sprache.split("-")[0] == "ar" else "ltr"
            assert werte["dir"] == erwartet and werte["paragraph"] == erwartet, werte
            assert werte["pages"] >= 164, werte
            if nur_layout:
                print(json.dumps(werte, ensure_ascii=True))
                beenden(0)
                return
        except Exception as fehler:
            beenden(1, "Print layout check failed: " + str(fehler))
            return
        druckauftrag(_ansicht)

    def drucken(_ansicht, ereignis):
        if ereignis != WebKit2.LoadEvent.FINISHED:
            return
        _ansicht.evaluate_javascript("JSON.stringify({dir:document.documentElement.dir,"
            "paragraph:getComputedStyle(document.querySelector('p')).direction,"
            "pages:document.querySelectorAll('.blatt').length})", -1, None, None, None,
            layout_geprueft, None)

    def druckauftrag(_ansicht):
        auftrag = WebKit2.PrintOperation.new(_ansicht)
        seite = Gtk.PageSetup()
        seite.set_paper_size(Gtk.PaperSize.new("iso_a4"))
        seite.set_orientation(Gtk.PageOrientation.LANDSCAPE)
        for rand in ("top", "bottom", "left", "right"):
            getattr(seite, "set_" + rand + "_margin")(0, Gtk.Unit.MM)
        auftrag.set_page_setup(seite)
        einstellung = Gtk.PrintSettings()
        einstellung.set_printer(gettext.dgettext("gtk30", "Print to File"))
        einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
        einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_URI,
                        GLib.filename_to_uri(ziel, None))
        auftrag.set_print_settings(einstellung)
        auftrag.connect("failed", bei_druckfehler)
        auftrag.connect("finished", bei_druckende)
        auftrag.print_()

    def nativ_drucken(html):
        pfad = os.environ.get("MAGNOLIE_HANDBUCH_TEST_PROGRAMM") or os.path.join(
            os.path.dirname(__file__), "..", "bin", "magnolie-handbuch")
        lader = importlib.machinery.SourceFileLoader("handbuch_druck_produkt", pfad)
        spec = importlib.util.spec_from_loader(lader.name, lader)
        modul = importlib.util.module_from_spec(spec)
        lader.exec_module(modul)
        dateidrucker = gettext.dgettext("gtk30", "Print to File")
        ziel_uri = GLib.filename_to_uri(ziel, None)

        def bestaetigen():
            for dialog in Gtk.Window.list_toplevels():
                if dialog.__gtype__.name != "GtkPrintUnixDialog":
                    continue
                try:
                    drucker = dialog.get_property("selected-printer")
                    if drucker is None:
                        return True
                    einstellung = dialog.get_property("print-settings")
                    if (drucker.get_property("name") != dateidrucker or
                            not drucker.get_property("is-virtual") or
                            einstellung.get(Gtk.PRINT_SETTINGS_OUTPUT_URI) != ziel_uri):
                        return True
                    if os.environ.get("MAGNOLIE_HANDBUCH_PRINT_DIAGNOSTIC"):
                        werte = {}
                        einstellung.foreach(lambda key, value, _data: werte.update({key: value}), None)
                        seite = dialog.get_property("page-setup")
                        print(json.dumps({"settings": werte, "margins": [getattr(seite, "get_" + rand + "_margin")(Gtk.Unit.MM)
                            for rand in ("top", "bottom", "left", "right")]}, ensure_ascii=True), flush=True)
                    dialog.response(Gtk.ResponseType.OK)
                    return False
                except Exception as fehler:
                    beenden(1, "Nativer Druckdialog konnte nicht geprüft werden: " + str(fehler))
                    return False
            return True

        import magnolie_print_operation as druck_implementation
        produkt_auftrag = druck_implementation.PdfPrintOperation
        def auftrag_neu(parent, title, markup, root, complete, translate):
            def fertig(ok, result):
                if not ok:
                    parent._closing = True
                complete(ok, result)
                beenden(0 if ok else 1, None if ok else "Nativer PDF-Druck fehlgeschlagen: " + str(result))
            auftrag = produkt_auftrag(parent, title, markup, root, fertig, translate,
                runtime_dir=os.environ.get("MAGNOLIE_PDF_TEST_RUNTIME"))
            einstellung = Gtk.PrintSettings()
            einstellung.set_printer(dateidrucker)
            einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
            einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_URI, ziel_uri)
            auftrag.set_print_settings(einstellung)
            GLib.timeout_add(500, bestaetigen)
            return auftrag

        # Keep the actual product chooser, worker, backend options and PDF send.
        # Only preselect the verified virtual destination and build-time runtime.
        fenster._web_verzeichnis = web
        fenster._closing = False
        fenster._print_shutdown_timeout = None
        druck_implementation.PdfPrintOperation = auftrag_neu
        try:
            modul.Fenster._drucken(fenster, html)
        finally:
            druck_implementation.PdfPrintOperation = produkt_auftrag

    def bei_druckfassung(_ansicht, ergebnis, _daten):
        try:
            wert = _ansicht.evaluate_javascript_finish(ergebnis)
            html = wert.to_string()
        except Exception as fehler:
            beenden(1, "Druckfassung konnte nicht gelesen werden: %s" % fehler)
            return
        if os.environ.get("MAGNOLIE_HANDBUCH_TEST_HTML_ONLY") == "1":
            with open(ziel, "w", encoding="utf-8") as output:
                output.write(html)
            print(json.dumps({"nativePrintHtml": "PASS", "language": sprache}), flush=True)
            beenden(0)
            return
        if nativer_weg:
            nativ_drucken(html)
        else:
            druckansicht.connect("load-changed", drucken)
            druckansicht.load_html(html, "magnolie-handbuch://app/")

    notes_ids = ["android-notes-connections", "android-notes-list-sorting", "android-notes-properties",
                 "android-notes-swipes", "android-notes-print-version", "android-tasks-reminders"]
    notes_state = {"attempt": 0, "position": 0, "steps": [], "results": [], "images": set(), "screenshots": set()}

    def notes_next():
        if notes_state["position"] >= len(notes_state["steps"]):
            try:
                assert len(notes_state["images"]) == 8, notes_state["images"]
                result = {"passed": True, "language": sprache, "chapterPages": 22,
                          "images": sorted(notes_state["images"]), "steps": notes_state["results"]}
                with open(os.path.splitext(ziel)[0] + ".notes.json", "w", encoding="utf-8") as output:
                    json.dump(result, output, ensure_ascii=False, indent=2)
                print(json.dumps({"notes": "PASS", "language": sprache, "parts": len(result["steps"]), "images": 8}), flush=True)
                ansicht.evaluate_javascript("Handbuch.druckFassung(%s)" % json.dumps(druck_optionen), -1, None, None, None, bei_druckfassung, None)
            except Exception as error:
                beenden(1, "Notes native result failed: " + str(error))
            return False
        step = notes_state["steps"][notes_state["position"]]
        script = "Handbuch.blaettereZu(%d); true" % step["index"]
        ansicht.evaluate_javascript(script, -1, None, None, None, None, None)
        GLib.timeout_add(250, notes_inspect)
        return False

    def notes_inspect():
        script = """JSON.stringify({text:document.querySelector('#seiten').textContent,
          overflow:[...document.querySelectorAll('#seiten .seiten-inhalt')].filter(n=>n.clientHeight>0&&n.scrollHeight>n.clientHeight+2).map(n=>({height:n.clientHeight,scroll:n.scrollHeight})),
          images:[...document.querySelectorAll('#seiten img')].filter(n=>n.getAttribute('src').includes('notes-native-')).map(n=>({name:n.getAttribute('src').split('/').pop(),ready:n.complete&&n.naturalWidth>0})),
          links:[...document.querySelectorAll('#seiten [data-page-title="true"]')].map(n=>({id:n.dataset.page,text:n.textContent}))})"""
        ansicht.evaluate_javascript(script, -1, None, None, None, notes_inspected, None)
        return False

    def notes_inspected(_view, finished, _data):
        try:
            result = json.loads(_view.evaluate_javascript_finish(finished).to_string())
            step = notes_state["steps"][notes_state["position"]]
            assert step["title"] in result["text"], step
            assert not result["overflow"], {"page": step, "overflow": result["overflow"]}
            assert all(image["ready"] for image in result["images"]), result["images"]
            assert all(link["text"].strip() for link in result["links"]), result["links"]
            notes_state["images"].update(image["name"] for image in result["images"])
            notes_state["results"].append({"id": step["id"], "partIndex": step["index"], "images": result["images"], "links": result["links"]})
            if os.environ.get("MAGNOLIE_HANDBUCH_TEST_NOTES_SCREENSHOTS") == "1" and step["id"] not in notes_state["screenshots"]:
                notes_state["screenshots"].add(step["id"])
                _view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, notes_snapshot, step)
            else:
                notes_follow_reference()
        except Exception as error:
            beenden(1, "Notes native UI failed: " + str(error))

    def notes_snapshot(view, finished, step):
        try:
            snapshot = view.get_snapshot_finish(finished)
            snapshot.write_to_png(os.path.splitext(ziel)[0] + "-" + step["id"] + ".png")
            notes_follow_reference()
        except Exception as error:
            beenden(1, "Notes native screenshot failed: " + str(error))

    def notes_follow_reference():
        script = """(() => {const link=document.querySelector('#seiten [data-page-title="true"]');
          if(!link)return JSON.stringify({clicked:false,ok:true});
          const target=Handbuch.seiten().find(p=>p.id===link.dataset.page);link.click();
          return JSON.stringify({clicked:true,ok:!!target&&document.querySelector('#seiten').textContent.includes(target.titel)});})()"""
        ansicht.evaluate_javascript(script, -1, None, None, None, notes_reference_checked, None)

    def notes_reference_checked(view, finished, _data):
        try:
            result = json.loads(view.evaluate_javascript_finish(finished).to_string())
            assert result["ok"], result
            notes_state["results"][-1]["reference"] = result
            notes_state["position"] += 1
            GLib.idle_add(notes_next)
        except Exception as error:
            beenden(1, "Notes native reference failed: " + str(error))

    def notes_ready(_view, finished, _data):
        try:
            result = json.loads(_view.evaluate_javascript_finish(finished).to_string())
            assert result["pages"] == 22 and result["searchable"], result
            assert result["language"] == sprache.replace("_", "-").lower(), result
            if not result["ready"]:
                notes_state["attempt"] += 1
                assert notes_state["attempt"] < 50, "Native Notes images/fonts did not load"
                GLib.timeout_add(100, notes_prepare)
                return
            notes_state["steps"] = result["steps"]
            assert notes_state["steps"], result
            GLib.timeout_add(600, notes_next)
        except Exception as error:
            beenden(1, "Notes native preparation failed: " + str(error))

    def notes_prepare():
        script = """(() => { MagnolieI18n.setLocale(%s);Handbuch.oeffneBuch();
          window.__notesImages ||= ['properties','task-properties','delete','swipe-settings','sort','task-sort','due-today','about'].map(name=>{const img=new Image();img.src='notes-native-'+name+'.png';return img});
          const ready=window.__notesImages.every(img=>img.complete&&img.naturalWidth>0)&&(!document.fonts||document.fonts.status==='loaded');
          if(ready)Handbuch.neuUmbrechen();const ids=%s,pages=Handbuch.seiten();
          return JSON.stringify({ready,language:document.documentElement.lang,pages:pages.filter(p=>p.kapitel==='Magnolie Notes').length,
            searchable:ids.every(id=>Handbuch.suche(pages.find(p=>p.id===id).titel).includes(id)),
            steps:Handbuch.anzeige().map((p,index)=>({id:p.quellId,index,title:pages.find(v=>v.id===p.quellId)?.titel||''})).filter(p=>ids.includes(p.id))}); })()""" % (json.dumps(sprache), json.dumps(notes_ids))
        ansicht.evaluate_javascript(script, -1, None, None, None, notes_ready, None)
        return False

    def bei_ladewechsel(_ansicht, ereignis):
        if ereignis != WebKit2.LoadEvent.FINISHED:
            return
        if notes_probe:
            notes_prepare()
            return
        _ansicht.evaluate_javascript(
            "MagnolieI18n.setLocale(%s); Handbuch.druckFassung(%s)" % (json.dumps(sprache), json.dumps(druck_optionen)), -1, None, None, None,
            bei_druckfassung, None)

    ansicht.connect("load-changed", bei_ladewechsel)
    ansicht.load_uri("magnolie-handbuch://app/index.html")
    GLib.timeout_add_seconds(300, lambda: beenden(1, "Zeitüberschreitung") or False)
    schleife.run()
    ansicht.stop_loading()
    druckansicht.stop_loading()
    ansicht.destroy()
    druckansicht.destroy()
    if fenster:
        if getattr(fenster, "_druckansicht", None):
            fenster._druckansicht.shutdown()
        fenster.destroy()
    return status["code"]


if __name__ == "__main__":
    sys.exit(haupt())
