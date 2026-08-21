#!/usr/bin/env python3
"""Startet den *echten* Magnolienbaum-Dienst des Organizers für den Livetest.

Der Organizer wird als Modul geladen; seine GUI bleibt aus. Der Dienst läuft
auf einem frei wählbaren Port und schreibt alles Wissenswerte zeilenweise nach
stdout, damit der Kotlin-Test mitlesen kann.

Aufruf:
    python3 organizer_dienst.py <pfad-zu-bin/magnolie-organizer> <port>

Zeilen nach stdout:
    BEREIT <port>
    PAARUNGSDATEI <json>
    NACHRICHT <kennung> <json>
    PARTNER <kennung> <bestaetigt>
"""
import importlib.machinery
import importlib.util
import json
import sys
import threading
import time


def lade(quelle):
    spec = importlib.util.spec_from_loader(
        "organizer", importlib.machinery.SourceFileLoader("organizer", quelle))
    modul = importlib.util.module_from_spec(spec)
    sys.modules["organizer"] = modul
    try:
        spec.loader.exec_module(modul)
    except SystemExit:
        pass
    return modul


def sag(*teile):
    print(*teile, flush=True)


def main():
    quelle = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8737
    O = lade(quelle)

    zustand = O.baum_schluessel_erzeugen("Schreibtisch")
    zustand["an"] = True
    zustand["port"] = int(sys.argv[3]) if len(sys.argv) > 3 else port
    zustand.setdefault("paarungen", [])
    zustand.setdefault("paarungenVerbraucht", [])
    sperre = threading.RLock()

    def hole():
        return zustand

    def sichere(neuer):
        return True

    def bei_nachricht(partner, inhalt):
        sag("NACHRICHT", partner.get("kennung"),
            json.dumps(inhalt, ensure_ascii=False))

    def bei_paarung(anfrage, antwort):
        sag("PAARUNGSVERSUCH")

    dienst = O.BaumDienst(hole, sichere, bei_nachricht, bei_paarung,
                          port=port, sperre=sperre)
    if not dienst.starten():
        sag("FEHLER Der Dienst ließ sich nicht starten.")
        return 1

    # Eine Paarungsdatei fürs Handy, gültig 15 Minuten.
    dokument, _einladung = O.baum_paarungsdatei_erzeugen(
        zustand, "127.0.0.1", port)
    sag("PAARUNGSDATEI", json.dumps(dokument, ensure_ascii=False))
    sag("KENNUNG", zustand["kennung"])
    sag("OEFFENTLICH", zustand["oeffentlich"])
    sag("BEREIT", port)

    # Befehle von der Testseite lesen.
    for zeile in sys.stdin:
        befehl = zeile.strip().split(" ", 1)
        if not befehl or not befehl[0]:
            continue
        if befehl[0] == "ENDE":
            break
        if befehl[0] == "PARTNER":
            for p in zustand.get("partner", []):
                sag("PARTNER", p.get("kennung"), bool(p.get("bestaetigt")),
                    p.get("protokoll", ""))
            sag("PARTNERENDE")
        if befehl[0] == "PAAREMIT":
            # Kurzer Codeweg zu einer Gegenstelle; danach gilt sie als bestätigt.
            ziel_host, ziel_port = befehl[1].split(" ")
            try:
                antwort = O.baum_anfragen(ziel_host, int(ziel_port), zustand)
                p = O.baum_partner_aufnehmen(
                    zustand, antwort.get("name", ""), antwort["kennung"],
                    antwort["oeffentlich"], ziel_host, int(ziel_port))
                p["bestaetigt"] = True
                p["protokoll"] = "baum-1"
                sag("PAARUNG", antwort["kennung"], antwort.get("code"))
            except Exception as fehler:
                sag("PAARUNGSFEHLER", fehler)
        if befehl[0] == "SENDE":
            # Schickt eine Notiz an den ersten bestätigten Partner.
            ziel = next((p for p in zustand.get("partner", [])
                         if p.get("bestaetigt")), None)
            if not ziel:
                sag("SENDEFEHLER kein bestätigter Partner")
                continue
            inhalt = json.loads(befehl[1]) if len(befehl) > 1 else {}
            transport = O._fs_b64(O.os.urandom(16))
            gut = O.baum_senden(zustand, ziel, inhalt.pop("art", "notiz"),
                                inhalt, transport_id=transport)
            sag("SENDEERGEBNIS", "ja" if gut else "nein")

    dienst.anhalten()
    sag("ENDE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
