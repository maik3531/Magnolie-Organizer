# Main-Integrationsnachprüfung für `3f3ec069`

## Ergebnis und genaue Bindung

Die isolierte Git-Trockenberechnung ist **konfliktfrei**. Zum gelesenen Refstand ist `main` ein Vorfahr des Kandidaten; eine Fast-forward-Übernahme wäre möglich. Es wurde keine Übernahme ausgeführt.

| Merkmal | Beobachteter Wert |
|---|---|
| Remote-Abfrage UTC | 26.11.2026, 13:16:51.757434–13:16:58.877993 UTC |
| Remote-Abfrage Europe/Berlin | 26.11.2026, 14:16:51.757434–14:16:58.877993 CET (UTC+01:00) |
| `main` | `d4da48a5eadd0bda22422b924bef4ee3b4324040` |
| Arbeitszweig/Kandidat | `3f3ec069895dec254c53660d14e6851cb23077cd` |
| Gemeinsame Basis | `d4da48a5eadd0bda22422b924bef4ee3b4324040` |
| Nur auf `main` / nur im Kandidaten | 0 / 23 Commits |
| `merge-tree` | Exit 0, keine Konflikte |
| Berechneter und tatsächlicher Kandidatenbaum | `176fa7f362227c92ec4d7c4bf08d09b855951ae7` |

Berechnet im bereits vorhandenen isolierten Objektbestand `parallel-8c860a14.git`, ohne Checkout-, Branch- oder Commitänderung. Die vollständigen Werte stehen in `integration-3f3ec069.json`.

## Änderungen seit `8c860a14`

Drei nachfolgende Commits beheben den Apple-Metadatenparser (#806), die kanonische Testwurzel (#793) und die Archivzeitstempel (#808). Insgesamt sind genau diese fünf Pfade geändert:

- `ARBEITSSTAND.md`
- `Magnolie-Organizer-macOS-Beta/tests/test_airplay_bundle.py`
- `Magnolie-Organizer-macOS-Beta/tests/test_import_python_bundle.py`
- `Magnolie-Organizer-macOS-Beta/tools/airplay_bundle.py`
- `Magnolie-Organizer-macOS-Beta/tools/import_python_bundle.py`

Der gemeinsame Workflow `.github/workflows/ports-2.0.30.yml` ist bytegleich: Git-Blob `67d8915eef9fa357dc0ce5debcf40cd82c03b608` an beiden Commits. Sämtliche 20 Top-Level-Verzeichnisbäume außerhalb des Mac-Unterbaums sind identisch, einschließlich Organizer, Windows, Notes, Handbuch, Verträgen, gemeinsamen Werkzeugen, Port-Adaptern und dem auf diesem Mac-Zweig vorhandenen Tablet-Unterbaum. Das belegt unveränderte Quellbytes; es ist kein erneuter Android-Zweigvergleich.

## Abnahmegrenzen und spätere Übernahme

Der native Lauf #104 (`45827353062`) ist an **`3f3ec069895dec254c53660d14e6851cb23077cd`** gebunden. Sein Ergebnis wird durch diese Git-Prüfung nicht bewertet. Ein späterer Dokumentationscommit bleibt ein eigener Quellstand und darf nicht als durch #104 nativ getestet dargestellt werden.

Der frühere parallele Zweigvergleich `integration-62523306.json` bleibt ein historischer Beleg für seine dort genannten SHAs. Es gab keine neue Android-Refabfrage, keinen erneuten Vergleich und keine Wiederholung der 24-Patch-Wiederherstellung. Sobald sich `main` oder der zu übernehmende Kandidat ändern, muss die konkrete Integration erneut gezielt geprüft werden. Zielrelease und tatsächliche Übernahmemethode werden durch diesen Befund nicht festgelegt.
