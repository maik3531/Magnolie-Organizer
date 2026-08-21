#!/usr/bin/env python3
"""Erzeugt die Handbuch-Druckfassung mit demselben WebKit wie das Programm."""

import os
import sys
import gettext

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import GLib, Gtk, WebKit2


def haupt():
    if len(sys.argv) != 2:
        sys.stderr.write("Aufruf: druck_pdf.py ZIEL.pdf\n")
        return 2

    ziel = os.path.abspath(sys.argv[1])
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
    ansicht = WebKit2.WebView()
    druckansicht = WebKit2.WebView()

    def beenden(code, meldung=None):
        status["code"] = code
        if meldung:
            sys.stderr.write(meldung + "\n")
        schleife.quit()

    def bei_druckfehler(_auftrag, fehler):
        beenden(1, "Drucken fehlgeschlagen: %s" % fehler.message)

    def bei_druckende(_auftrag):
        beenden(0)

    def drucken(_ansicht, ereignis):
        if ereignis != WebKit2.LoadEvent.FINISHED:
            return
        auftrag = WebKit2.PrintOperation.new(_ansicht)
        einstellung = Gtk.PrintSettings()
        einstellung.set_printer(gettext.dgettext("gtk30", "Print to File"))
        einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
        einstellung.set(Gtk.PRINT_SETTINGS_OUTPUT_URI,
                        GLib.filename_to_uri(ziel, None))
        auftrag.set_print_settings(einstellung)
        auftrag.connect("failed", bei_druckfehler)
        auftrag.connect("finished", bei_druckende)
        auftrag.print_()

    def bei_druckfassung(_ansicht, ergebnis, _daten):
        try:
            wert = _ansicht.evaluate_javascript_finish(ergebnis)
            html = wert.to_string()
        except Exception as fehler:
            beenden(1, "Druckfassung konnte nicht gelesen werden: %s" % fehler)
            return
        druckansicht.connect("load-changed", drucken)
        druckansicht.load_html(html, GLib.filename_to_uri(web + os.sep, None))

    def bei_ladewechsel(_ansicht, ereignis):
        if ereignis != WebKit2.LoadEvent.FINISHED:
            return
        _ansicht.evaluate_javascript(
            "Handbuch.druckFassung()", -1, None, None, None,
            bei_druckfassung, None)

    ansicht.connect("load-changed", bei_ladewechsel)
    ansicht.load_uri(GLib.filename_to_uri(start, None))
    GLib.timeout_add_seconds(60, lambda: beenden(1, "Zeitüberschreitung") or False)
    schleife.run()
    return status["code"]


if __name__ == "__main__":
    sys.exit(haupt())
