#!/usr/bin/env python3
"""Erzeugt die Handbuch-Druckfassung mit demselben WebKit wie das Programm."""

import os
import sys
import gettext
import json
import importlib.machinery
import importlib.util
from types import SimpleNamespace

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
    nativer_weg = os.environ.get("MAGNOLIE_HANDBUCH_TEST_NATIVE") == "1" and not nur_layout
    fenster = Gtk.Window() if nativer_weg else None
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
        pfad = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-handbuch")
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

        def auftrag_neu(view):
            auftrag = WebKit2.PrintOperation.new(view)
            einstellung = Gtk.PrintSettings()
            einstellung.set_printer(dateidrucker)
            einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
            einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_URI, ziel_uri)
            auftrag.set_print_settings(einstellung)
            auftrag.connect("failed", bei_druckfehler)
            auftrag.connect("finished", bei_druckende)
            GLib.timeout_add(100, bestaetigen)
            return auftrag

        # Keep production loading, page setup and printer selection. Only isolate the
        # WebContext and preselect a verified virtual PDF destination for the test.
        modul.WebKit2 = SimpleNamespace(WebView=lambda: WebKit2.WebView.new_with_context(kontext),
            LoadEvent=WebKit2.LoadEvent, PrintOperation=SimpleNamespace(new=auftrag_neu))
        modul.Fenster._drucken(fenster, html)

    def bei_druckfassung(_ansicht, ergebnis, _daten):
        try:
            wert = _ansicht.evaluate_javascript_finish(ergebnis)
            html = wert.to_string()
        except Exception as fehler:
            beenden(1, "Druckfassung konnte nicht gelesen werden: %s" % fehler)
            return
        if nativer_weg:
            nativ_drucken(html)
        else:
            druckansicht.connect("load-changed", drucken)
            druckansicht.load_html(html, "magnolie-handbuch://app/")

    def bei_ladewechsel(_ansicht, ereignis):
        if ereignis != WebKit2.LoadEvent.FINISHED:
            return
        _ansicht.evaluate_javascript(
            "MagnolieI18n.setLocale(%s); Handbuch.druckFassung()" % json.dumps(sprache), -1, None, None, None,
            bei_druckfassung, None)

    ansicht.connect("load-changed", bei_ladewechsel)
    ansicht.load_uri("magnolie-handbuch://app/index.html")
    GLib.timeout_add_seconds(60, lambda: beenden(1, "Zeitüberschreitung") or False)
    schleife.run()
    ansicht.stop_loading()
    druckansicht.stop_loading()
    ansicht.destroy()
    druckansicht.destroy()
    if fenster:
        if getattr(fenster, "_druckansicht", None):
            fenster._druckansicht.destroy()
        fenster.destroy()
    return status["code"]


if __name__ == "__main__":
    sys.exit(haupt())
