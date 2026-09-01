#!/usr/bin/env python3
"""Historischer Bluetooth-Prototyp; nicht für den Betrieb verwenden.

Der produktive Organizer enthält inzwischen `BaumBluetoothDienst`, registriert
das Profil über BlueZ und reicht RFCOMM direkt an `BaumDienst.behandeln` weiter.
Diese frühere eigenständige Skizze bleibt nur als Entwicklungsgeschichte liegen;
sie soll nicht parallel zum Organizer gestartet werden.

Der Rahmen ist derselbe, den `BluetoothTransport` in der App schreibt:

    4 Byte Länge (big endian) | JSON {"pfad": "...", "nutzlast": {...}}

und zurück:

    4 Byte Länge (big endian) | JSON (die Antwort des Baumpfads)

Die Dienstkennung ist fest:

    6d61676e-6f6c-6965-6e62-61756d383733     ("magnolienbaum873")

Voraussetzung ist `pybluez` oder ein Kernel mit `AF_BLUETOOTH`-Sockets; unter
Linux geht letzteres ohne Zusatzpaket. Der Rechner muss sichtbar und gekoppelt
sein (`bluetoothctl discoverable on`).

Aufruf zum Ausprobieren:

    python3 organizer_bluetooth.py /pfad/zu/bin/magnolie-organizer
"""
import importlib.machinery
import importlib.util
import json
import socket
import struct
import sys
import threading

DIENST_UUID = "6d61676e-6f6c-6965-6e62-61756d383733"
RFCOMM_KANAL = 11
RAHMEN_MAX = 8 * 1024 * 1024


def lade_organizer(quelle):
    spec = importlib.util.spec_from_loader(
        "organizer", importlib.machinery.SourceFileLoader("organizer", quelle))
    modul = importlib.util.module_from_spec(spec)
    sys.modules["organizer"] = modul
    try:
        spec.loader.exec_module(modul)
    except SystemExit:
        pass
    return modul


class BluetoothHorcher(object):
    """Nimmt Baumnachrichten über RFCOMM entgegen.

    `behandeln(pfad, nachricht, quelle)` muss genau das tun, was der
    HTTP-Behandler des Organizers in `BaumDienst.starten()` tut – am saubersten,
    indem dieser Teil dort in eine eigene Methode gezogen wird. Solange das
    nicht geschehen ist, übergibt man hier eine Funktion, die dieselben Wege
    bedient.
    """

    def __init__(self, behandeln, kanal=RFCOMM_KANAL):
        self.behandeln = behandeln
        self.kanal = kanal
        self._buchse = None
        self._laeuft = False

    def starten(self):
        try:
            buchse = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                   socket.BTPROTO_RFCOMM)
            buchse.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            buchse.bind(("", self.kanal))
            buchse.listen(4)
        except (AttributeError, OSError) as fehler:
            print("Bluetooth steht nicht zur Verfügung:", fehler, file=sys.stderr)
            return False
        self._buchse = buchse
        self._laeuft = True
        threading.Thread(target=self._horchen, daemon=True).start()
        return True

    def anhalten(self):
        self._laeuft = False
        if self._buchse:
            try:
                self._buchse.close()
            except OSError:
                pass
            self._buchse = None

    def _horchen(self):
        while self._laeuft:
            try:
                verbindung, woher = self._buchse.accept()
            except OSError:
                break
            threading.Thread(target=self._bedienen, args=(verbindung, woher),
                             daemon=True).start()

    def _bedienen(self, verbindung, woher):
        try:
            verbindung.settimeout(30)
            umschlag = self._lies_rahmen(verbindung)
            pfad = str(umschlag.get("pfad") or "")
            nutzlast = umschlag.get("nutzlast")
            if not isinstance(nutzlast, dict):
                raise ValueError("unvollständiger Rahmen")
            # Die Geräteadresse bindet die FS-Sitzung, so wie sonst die IP.
            quelle = woher[0] if isinstance(woher, tuple) else str(woher)
            _nummer, antwort = self.behandeln(pfad, nutzlast, quelle)
            self._schreib_rahmen(verbindung, antwort)
        except Exception as fehler:
            try:
                self._schreib_rahmen(verbindung, {"fehler": str(fehler)[:120]})
            except OSError:
                pass
        finally:
            try:
                verbindung.close()
            except OSError:
                pass

    @staticmethod
    def _lies_rahmen(verbindung):
        kopf = BluetoothHorcher._genau(verbindung, 4)
        (laenge,) = struct.unpack(">I", kopf)
        if not 0 < laenge <= RAHMEN_MAX:
            raise ValueError("ungültige Rahmenlänge")
        roh = BluetoothHorcher._genau(verbindung, laenge)
        return json.loads(roh.decode("utf-8"))

    @staticmethod
    def _schreib_rahmen(verbindung, wert):
        roh = json.dumps(wert, ensure_ascii=False).encode("utf-8")
        verbindung.sendall(struct.pack(">I", len(roh)) + roh)

    @staticmethod
    def _genau(verbindung, anzahl):
        teile = []
        offen = anzahl
        while offen > 0:
            stueck = verbindung.recv(min(offen, 64 * 1024))
            if not stueck:
                raise OSError("Verbindung abgebrochen")
            teile.append(stueck)
            offen -= len(stueck)
        return b"".join(teile)


def beispiel(quelle):
    """Zeigt, wie der Horcher an einen laufenden Baumzustand kommt."""
    O = lade_organizer(quelle)
    zustand = O.baum_schluessel_erzeugen("Schreibtisch")
    zustand["an"] = True
    sperre = threading.RLock()

    def behandeln(pfad, nachricht, quelle_adresse):
        """Dieselben Wege wie über HTTP.

        Im eingebauten Zustand ruft man hier den ausgelagerten Behandler des
        `BaumDienst` auf. Der Entwurf bedient nur die Paarung nach Datei und
        die sichere Nachricht, damit sich das Zusammenspiel ausprobieren lässt.
        """
        with sperre:
            try:
                if pfad == "/magnolie/v2/paarung":
                    return 200, O.baum_paarungsanfrage_annehmen(
                        zustand, nachricht, quelle_adresse)
                if pfad == "/magnolie/v1/paarung":
                    return 200, O.baum_antwort_paarung(
                        zustand, nachricht, quelle_adresse)
                if pfad == "/magnolie/v1/nachricht":
                    inhalt = O.baum_nachricht_annehmen(zustand, nachricht)
                    return 200, {"ok": True, "art": inhalt.get("art")}
            except RuntimeError as fehler:
                return 403, {"fehler": str(fehler)}
        return 404, {"fehler": "Unbekannter Weg."}

    horcher = BluetoothHorcher(behandeln)
    if not horcher.starten():
        return 1
    print("Bluetooth-Horcher läuft auf RFCOMM-Kanal", RFCOMM_KANAL)
    print("Dienstkennung:", DIENST_UUID)
    print("Fingerabdruck:", O.fingerabdruck(zustand["oeffentlich"]))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        horcher.anhalten()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(beispiel(sys.argv[1]))
