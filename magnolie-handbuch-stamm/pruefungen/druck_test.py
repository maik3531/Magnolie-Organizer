#!/usr/bin/env python3
"""Prüft die tatsächliche WebKit-PDF-Fassung auf leere Zwischenblätter."""

import os
import re
import subprocess
import sys
import tempfile
import importlib.machinery
import importlib.util
import io


WURZEL = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def modul_laden(name, pfad):
    lader = importlib.machinery.SourceFileLoader(name, pfad)
    spec = importlib.util.spec_from_loader(name, lader)
    modul = importlib.util.module_from_spec(spec)
    lader.exec_module(modul)
    return modul


def cli_aufruf(modul, argumente, fehler=False):
    argv_alt = modul.sys.argv
    ziel_alt = modul.sys.stderr if fehler else modul.sys.stdout
    uebersetzung_alt, gettext_alt = modul.UEBERSETZUNG, modul._
    titel_alt, override_alt = modul.FENSTER_TITEL, modul.SPRACH_OVERRIDE
    ziel = io.StringIO()
    modul.sys.argv = ["magnolie-handbuch"] + argumente
    if fehler:
        modul.sys.stderr = ziel
    else:
        modul.sys.stdout = ziel
    try:
        modul.haupt()
    except SystemExit as ende:
        code = ende.code
    else:
        code = None
    finally:
        modul.sys.argv = argv_alt
        if fehler:
            modul.sys.stderr = ziel_alt
        else:
            modul.sys.stdout = ziel_alt
        modul.UEBERSETZUNG, modul._ = uebersetzung_alt, gettext_alt
        modul.FENSTER_TITEL = titel_alt
        modul.SPRACH_OVERRIDE = override_alt
    return code, ziel.getvalue()


def cli_pruefen():
    handbuch = modul_laden("magnolie_handbuch_test",
                           os.path.join(WURZEL, "bin", "magnolie-handbuch"))
    englisch = cli_aufruf(handbuch, ["--sprache", "en", "--hilfe"])
    deutsch = cli_aufruf(handbuch, ["--language", "de", "--help"])
    assert englisch[0] == 0 and "Usage:" in englisch[1]
    assert "Use de, en, or system" in englisch[1]
    assert deutsch[0] == 0 and "Aufruf:" in deutsch[1]
    assert "Für diesen Aufruf de, en oder system verwenden" in deutsch[1]

    fehlt = cli_aufruf(handbuch, ["--sprache"], fehler=True)
    franzoesisch = cli_aufruf(handbuch, ["--language", "fr", "--help"])
    falsch = cli_aufruf(handbuch, ["--language", "xx"], fehler=True)
    assert fehlt[0] == 2 and "benötigt eine Sprache" in fehlt[1]
    assert franzoesisch[0] == 0
    assert falsch[0] == 2 and "Ungültige Sprache: xx" in falsch[1]

    quell_pot = os.path.join(WURZEL, "po", "magnolie-handbuch.pot")
    with open(quell_pot, "rb") as datei:
        pot_vorher = datei.read()
    with tempfile.TemporaryDirectory(prefix="magnolie-handbuch-cli-") as ordner:
        cwd_alt = os.getcwd()
        try:
            os.chdir(ordner)
            standard = cli_aufruf(handbuch, ["--sprache", "de", "--pot"])
            eigen = os.path.join(ordner, "ausgabe", "handbuch.pot")
            alias = cli_aufruf(
                handbuch, ["--language", "en", "--pot-template", eigen])
        finally:
            os.chdir(cwd_alt)
        assert standard[0] == 0
        assert os.path.isfile(os.path.join(ordner, "magnolie-handbuch.pot"))
        assert "POT-Vorlage geschrieben nach:" in standard[1]
        assert alias[0] == 0 and os.path.isfile(eigen)
        assert "POT template written to:" in alias[1]

        installiert = os.path.join(ordner, "share", "magnolie-handbuch")
        web = os.path.join(installiert, "web")
        os.makedirs(web)
        for name in ("i18n-markers.js", "handbuch.js"):
            with open(os.path.join(web, name), "w", encoding="utf-8") as datei:
                datei.write("gettext('test');\n")
        start = os.path.join(ordner, "magnolie-handbuch")
        with open(start, "w", encoding="utf-8") as datei:
            datei.write("#!/usr/bin/env python3\n")
        generator = modul_laden("magnolie_handbuch_pot_test", os.path.join(
            WURZEL, "werkzeuge", "pot_erzeugen.py"))
        quellen = generator.quellen_finden(installiert, start)
        assert quellen[:3] == (os.path.join(web, "i18n-markers.js"),
                               os.path.join(web, "handbuch.js"), start)
        assert quellen[3] is False
        pot_erzeugen_alt = handbuch.pot_erzeugen
        def pot_fehler(_ziel):
            raise FileNotFoundError("xgettext")
        handbuch.pot_erzeugen = pot_fehler
        fehler = cli_aufruf(
            handbuch, ["--sprache", "de", "--pot"], fehler=True)
        handbuch.pot_erzeugen = pot_erzeugen_alt
        assert fehler[0] == 1
        assert "POT-Vorlage konnte nicht erzeugt werden: xgettext" in fehler[1]
    with open(quell_pot, "rb") as datei:
        assert datei.read() == pot_vorher


def flach(wert):
    """Leerraum vereinheitlichen, damit Zeilenumbrueche nicht stoeren."""
    return re.sub("[ " + chr(9) + chr(10) + chr(13) + "]+", " ", wert).strip()


def haupt():
    cli_pruefen()
    if "--cli-only" in sys.argv[1:]:
        print("CLI-PRÜFUNGEN BESTANDEN")
        return 0
    hier = os.path.dirname(os.path.realpath(__file__))
    with tempfile.TemporaryDirectory(prefix="magnolie-handbuch-test-") as ordner:
        pdf = os.path.join(ordner, "handbuch.pdf")
        subprocess.run(
            [sys.executable, os.path.join(hier, "druck_pdf.py"), pdf],
            check=True,
        )
        info = subprocess.check_output(["pdfinfo", pdf], text=True)
        treffer = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
        if not treffer:
            raise AssertionError("PDF-Seitenzahl konnte nicht gelesen werden")
        anzahl = int(treffer.group(1))
        if anzahl < 59:
            raise AssertionError("PDF wurde unerwartet gekürzt")

        text = subprocess.check_output(
            ["pdftotext", "-layout", pdf, "-"], text=True)
        seiten = text.split("\f")
        if seiten and not seiten[-1].strip():
            seiten.pop()
        if len(seiten) != anzahl or any(not seite.strip() for seite in seiten):
            raise AssertionError("PDF enthält leere Seiten")

        # Ein Bogen traegt zwei Seiten. pdftotext legt beide Fusszeilen auf
        # dieselbe Zeile: links die Zahl vor der Marke, rechts dahinter.
        fussnummern = [int(links or rechts) for links, rechts in re.findall(
            r"(\d+)\s+Magnolie Organizer · Handbuch"
            r"|Magnolie Organizer · Handbuch\s+(\d+)", text)]
        if fussnummern != list(range(1, len(fussnummern) + 1)):
            raise AssertionError("Handbuchseiten fehlen oder sind falsch geordnet")
        if len(fussnummern) < 59:
            raise AssertionError("Nicht alle Handbuchseiten wurden gedruckt")

        for textstelle in (
            "240.000 Runden",
            "alle Startarten",
            "aufgeschlagene Doppelseite",
            "Mehrtägige Termine",
            "Fassung und Aktualisierungen",
            "Freie Bezeichnungen bleiben erhalten",
            "Gesundheit einschalten und sich zurechtfinden",
            "sichtbaren Drehpfeile",
            "allgemeine Referenzhilfen für Erwachsene",
            "Dosieren Sie Insulin niemals allein nach",
            "allen vier Seiten einen geschlossenen Rahmen",
            "alle sechs Diagramme, davon drei links und drei",
            "A4-Querformat",
            "magnolie-phone/1",
            "KDE Connect",
            "Personal Sync",
            "restore_unavailable",
            "Plattform- und Sicherheitsmatrix",
            "magnolie-organizer-2.0.13-",
            "Die Locale beeinflusst den Diagnosetext",
            "Technische Datei- und Mengengrenzen",
            "keine Speicherobergrenze",
            "Terminserien und ICS-Rundwege",
            "525.600 Minuten",
            "Schreibweise des Manifests",
            "AppImage-Erkennung verhindert",
            "keine entsprechende Begrenzung der Antwortgröße",
            "Glossar: A–M",
            "Eine authentifizierte Verschlüsselung",
            "Glossar: N–Z",
            "kurzfristige, integritätsgeprüfte Kopie",
        ):
            # Der Doppelseitensatz bricht Zeilen anders um als frueher der
            # einspaltige Druck. Verglichen wird deshalb ohne Leerraum.
            if flach(textstelle) not in flach(text):
                raise AssertionError("Druckinhalt abgeschnitten: " + textstelle)

    print("PDF-DRUCKPRÜFUNG BESTANDEN (%d PDF-Seiten, keine Leerblätter)" % anzahl)
    return 0


if __name__ == "__main__":
    sys.exit(haupt())
