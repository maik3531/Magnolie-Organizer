#!/usr/bin/python3
"""Prüft GTK, WebKit, das interne URI-Schema und die echte JS-Brücke."""

import importlib.machinery
import importlib.util
import json
import os
import sys


PROGRAMM = os.environ.get("MAGNOLIE_TEST_PROGRAMM", "/usr/bin/magnolie-organizer")
WEB = os.environ.get("MAGNOLIE_TEST_WEB", "/usr/share/magnolie-organizer/web")

if os.environ.get("MAGNOLIE_ORGANIZER_WEB") or os.environ.get("MAGNOLIE_LOCALE_DIR"):
    raise SystemExit("Quellpfad-Overrides sind im installierten Test nicht erlaubt")

lader = importlib.machinery.SourceFileLoader("magnolie_installiert", PROGRAMM)
spec = importlib.util.spec_from_loader("magnolie_installiert", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)

if not m.GTK_OK:
    raise SystemExit("GTK/WebKit nicht verfügbar: %s" % m.GTK_FEHLER)
initialisiert = m.Gtk.init_check([])
if not (initialisiert[0] if isinstance(initialisiert, tuple) else initialisiert):
    raise SystemExit("GTK konnte die virtuelle Anzeige nicht öffnen")
if not os.environ.get("MAGNOLIE_TEST_WEB") and m.finde_web_verzeichnis() != WEB:
    raise SystemExit("Nicht die installierten Webressourcen gefunden")

erwartet = {
    m.ORGANIZER_URI,
    "magnolie-organizer://app/stil.css",
    "magnolie-organizer://app/i18n.js",
    "magnolie-organizer://app/i18n-active.js",
    "magnolie-organizer://app/i18n-start.js",
    "magnolie-organizer://app/anwendung.js",
}
zustand = {"bereit": False, "layout": False,
           "fehler": "Zeitüberschreitung beim WebKit-Start"}


class Prueffenster(m.Fenster):
    def __init__(self):
        self.angefordert = set()
        super().__init__(WEB)
        self.resize(int(os.environ.get("MAGNOLIE_TEST_WIDTH", "980")),
                    int(os.environ.get("MAGNOLIE_TEST_HEIGHT", "640")))
        self.ansicht.connect("load-changed", self.laden_beobachten)
        m.GLib.timeout_add(3000, self.javascript_diagnose)

    def laden_beobachten(self, _ansicht, ereignis):
        if ereignis == m.WebKit2.LoadEvent.FINISHED:
            m.GLib.timeout_add(500, self.javascript_diagnose)

    def javascript_diagnose(self):
        if zustand["bereit"]:
            return False
        quelltext = ("JSON.stringify({app:typeof App,test:typeof OrganizerTest," +
                     "i18n:typeof MagnolieI18n,bridge:typeof window.__MAGNOLIE_BRUECKE__})")
        self.ansicht.run_javascript(quelltext, None, self.diagnose_fertig, None)
        return False

    def diagnose_fertig(self, ansicht, ergebnis, _daten):
        try:
            wert = ansicht.run_javascript_finish(ergebnis).get_js_value().to_string()
            diagnose = json.loads(wert)
            if not zustand["bereit"]:
                zustand["fehler"] = "JavaScript-Diagnose: %r" % diagnose
        except Exception as fehler:
            zustand["fehler"] = "JavaScript-Diagnose fehlgeschlagen: %s" % fehler

    def _bei_organizer_anfrage(self, anfrage):
        self.angefordert.add(anfrage.get_uri())
        return super()._bei_organizer_anfrage(anfrage)

    def bei_nachricht(self, _inhalte, ergebnis):
        try:
            wert = ergebnis.get_js_value() if hasattr(ergebnis, "get_js_value") else ergebnis
            nachricht = json.loads(wert.to_string())
        except (AttributeError, TypeError, ValueError) as fehler:
            self.fertig("Unlesbare Brückennachricht: %s" % fehler)
            return
        if nachricht.get("cmd") == "ui_ueberlauf":
            fehler = nachricht.get("fehler") or []
            if fehler:
                self.fertig("Übersetzte Bedienelemente laufen über: %s" %
                            json.dumps(fehler[:20], ensure_ascii=False))
                return
            zustand["layout"] = True
            self.ansicht.load_uri("file:///etc/passwd")
            m.GLib.timeout_add(750, self.navigation_pruefen)
            return
        if nachricht.get("cmd") == "ui_diagnose":
            if not zustand["bereit"]:
                zustand["fehler"] = "JavaScript-Diagnose: %r" % nachricht
            return
        if nachricht.get("cmd") != "bereit":
            return
        if not self._organizer_vertraut():
            self.fertig("Die echte Brücke vertraut dem Organizer-Ursprung nicht")
            return
        if self.angefordert != erwartet:
            self.fertig("WebKit lud nicht genau die Startressourcen: %r" %
                        sorted(self.angefordert))
            return
        zustand["bereit"] = True
        super().bei_nachricht(_inhalte, ergebnis)
        m.GLib.timeout_add(1200, self.layout_pruefen)

    def layout_pruefen(self):
        sprachen = ["en"] + list(m.UNTERSTUETZTE_SPRACHEN)
        quelltext = """
(async function () {
 let aktuelleSprache = "Start";
 try {
  const sprachen = %s;
  for (const sprache of sprachen.filter((wert) =>
      wert !== "en" && wert !== window.__MAGNOLIE_SPRACHE__)) {
   await new Promise((fertig, fehler) => {
    const script = document.createElement("script");
    script.src = "i18n/" + sprache + ".js";
    script.onload = fertig;
    script.onerror = fehler;
    document.head.append(script);
   });
  }
  const bereiche = ["kalender", "aufgaben", "adressen", "notizen", "jahrestage", "planer", "gesundheit"];
  const basis = JSON.parse(JSON.stringify(OrganizerTest.daten()));
  const fehler = [];
  const warten = () => new Promise((fertig) => requestAnimationFrame(() => requestAnimationFrame(fertig)));
  for (const sprache of sprachen) {
    aktuelleSprache = sprache;
    App.init({daten: JSON.parse(JSON.stringify(basis)), datenPfad: "/tmp/magnolie-layout",
      regional: {language: sprache, formatLocale: sprache.replace("_", "-")}, neu: false});
    OrganizerTest.oeffneBuch();
    for (const bereich of bereiche) {
      OrganizerTest.wechsel(bereich);
      await warten();
      for (const eintrag of OrganizerTest.findeTextUeberlaeufe(document)) {
        fehler.push(Object.assign({sprache, zustand: "bereich/" + bereich}, eintrag));
      }
    }
    OrganizerTest.wechsel("gesundheit");
    document.querySelectorAll(".gesundheit-symbolknopf")[1]?.click();
    await warten();
    for (const eintrag of OrganizerTest.findeTextUeberlaeufe(document)) {
      fehler.push(Object.assign({sprache, zustand: "bereich/gesundheit/medikamente"}, eintrag));
    }
    const medikamententabelle = document.querySelector("#inhalt-rechts .medikament-rechts");
    const medikamentenaktionen = document.querySelector(
      "#inhalt-rechts .gesundheit-tabellenaktionen");
    if (window.innerHeight >= 900 && medikamententabelle && medikamentenaktionen &&
        medikamententabelle.getBoundingClientRect().bottom >
          medikamentenaktionen.getBoundingClientRect().top + 1) {
      fehler.push({sprache, zustand: "bereich/gesundheit/medikamente",
        element: "table.medikament-rechts", text: "table overlaps actions",
        box: Math.round(medikamententabelle.getBoundingClientRect().height) + "px",
        inhalt: Math.round(medikamentenaktionen.getBoundingClientRect().top) + "px"});
    }
    for (const gruppe of [["aufgaben", "adressen", "notizen"],
                          ["jahrestage", "planer", "gesundheit"]]) {
      const daten = JSON.parse(JSON.stringify(basis));
      const register = daten.einstellungen.allgemein.registerkarten;
      for (const id of ["aufgaben", "adressen", "notizen", "jahrestage", "planer", "gesundheit"])
        register[id] = gruppe.includes(id);
      App.init({daten, datenPfad: "/tmp/magnolie-layout",
        regional: {language: sprache, formatLocale: sprache.replace("_", "-")}, neu: false});
      OrganizerTest.oeffneBuch();
      await warten();
      for (const eintrag of OrganizerTest.findeTextUeberlaeufe(document)) {
        fehler.push(Object.assign({sprache, zustand: "register/" + gruppe.join("-")}, eintrag));
      }
    }
    App.init({daten: JSON.parse(JSON.stringify(basis)), datenPfad: "/tmp/magnolie-layout",
      regional: {language: sprache, formatLocale: sprache.replace("_", "-")}, neu: false});
    OrganizerTest.oeffneEinstellungen();
    for (const id of Array.from(document.querySelectorAll(".einst-reiter-knopf"), (e) => e.id)) {
      document.getElementById(id)?.click();
      await warten();
      for (const eintrag of OrganizerTest.findeTextUeberlaeufe(document)) {
        fehler.push(Object.assign({sprache, zustand: "einstellungen/" + id}, eintrag));
      }
    }
    OrganizerTest.schliesseEinstellungen();
  }
  window.webkit.messageHandlers[window.__MAGNOLIE_BRUECKE__].postMessage(
    JSON.stringify({cmd: "ui_ueberlauf", fehler}));
 } catch (fehler) {
   window.webkit.messageHandlers[window.__MAGNOLIE_BRUECKE__].postMessage(
     JSON.stringify({cmd: "ui_ueberlauf", fehler: [{sprache: aktuelleSprache,
       zustand: "Ausnahme", element: "JavaScript", text: String(fehler && fehler.stack || fehler)}]}));
 }
})();
""" % json.dumps(sprachen)
        self.sende_js(quelltext)
        return False

    def navigation_pruefen(self):
        if self.ansicht.get_uri() != m.ORGANIZER_URI:
            self.fertig("Eine fremde file:-Navigation wurde nicht gesperrt")
        else:
            self.fertig("")
        return False

    def fertig(self, fehler):
        zustand["fehler"] = fehler
        self.destroy()


fenster = Prueffenster()
fenster.show_all()


def zeit_ist_um():
    if not zustand["bereit"] or not zustand["layout"]:
        fenster.fertig("%s; URI=%r; angefordert=%r" %
                       (zustand["fehler"], fenster.ansicht.get_uri(),
                        sorted(fenster.angefordert)))
    return False


m.GLib.timeout_add_seconds(int(os.environ.get("MAGNOLIE_TEST_TIMEOUT", "300")),
                           zeit_ist_um)
m.Gtk.main()
if zustand["fehler"]:
    sys.stderr.write(zustand["fehler"] + "\n")
    raise SystemExit(1)
print("GTK/WebKit, 20 Sprachen ohne Textüberlauf, Ressourcen, Brücke und Navigationssperre funktionieren")
