# Nachprüfung #823: stabile Kontaktidentität bei ergänzender Wiederherstellung

## Bestätigter Fehler und Korrektur

Auf der Basis `0cdd6f992e094cd724203713da3bf145c36958fc` behalten die tatsächlichen
Linux- und Windows-Frontends beim gewöhnlichen Kontaktimport korrekt eine Karte:
Eine bisher leere externe UID wird ergänzt, während `id=contact-local` gleich
bleibt. Wird anschließend der vorherige Snapshot ergänzend im Kontaktbereich
wiederhergestellt, erzeugen beide nativen Auswahlfunktionen zwei Karten mit
derselben lokalen ID. Die bisherigen 37 Vektoren des abgeschlossenen Issues
erfassen diese Kontakttransition nicht.

Der Patch erweitert den bestehenden Vorrang einer eindeutigen lokalen ID auf
Kontakte. Die aktuelle Karte und UID bleiben erhalten. Bei geänderter UID werden
ausschließlich bekannte fehlende Kontaktinhalte ergänzt. Aktive Bindungen,
archivierte Transportdaten und unbekannte Providerfelder werden dabei nicht
zurückgeholt. Mehrdeutige lokale IDs führen vor der primären Dateimutation zu
einem Konflikt, soweit sie sich nicht über eine exakte unveränderte Identität
auflösen lassen. Bereits vorhandene exakte Mehrdeutigkeiten bleiben unverändert.

Die bisherigen Kalender-, Notiz- und Jahrestagsregeln sowie der ausdrückliche
Ersetzungsmodus bleiben erhalten. Es werden keine Kontakte nach Name, E-Mail oder
Telefon im Restore zusammengeführt; der normale Import vor dem Restore ist ein
separater, tatsächlich ausgeführter Schritt der Reproduktion.

## Quellbindung und Lieferung

- Basis: `0cdd6f992e094cd724203713da3bf145c36958fc`
- Geprüfter Quellcommit: `71c5cb2276beaa3bbb9a7748bd0e2a9f86dd4f8a`
- Ergebnisbaum: `0294bedd87c37c9baf91b9fc72944ef0f1fbceea`
- Patch: `823-contact-identity.patch`
- Patch-SHA-256: `f272ac7f366522f5db1fbab925fddc15b8ede61d9423ab2c3f1e041cf7e02ce8`

Der Quellcommit ändert vier Dateien: beide Auswahlfunktionen, die gemeinsamen
Vektoren und zwei Linux-Tests am tatsächlichen Restore-/Save-Eingang.
`ARBEITSSTAND-fragment.md` ist zur gemeinsamen Übergabe vorgesehen und gehört
nicht zum Produktpatch. Die Veröffentlichung erfolgt über das bestehende Issue;
dieser Review führt keinen Merge nach `main` und keine Paketfreigabe durch.

## Prüfergebnisse

| Prüfung | Unveränderte Basis | Korrigierter Quellstand |
|---|---|---|
| Gemeinsame Auswahl-/Ersetzungsvorgaben, Python | 89 bestanden, 9 fehlgeschlagen | 98 bestanden |
| Gemeinsame C#-Auswahlgruppe | Fehler am ersten neuen Kontaktvektor | Alle 49 Vektoren einschließlich Wiederholung und Ersetzung bestanden |
| Vollständige Frontends → echte Python-/C#-Auswahl | Beide Frontends: eine Karte vor Restore, zwei danach | Jeweils eine Karte; Python-Wiederholung bleibt bei einer Karte |
| Fokussierte Python-Gesamtprüfung | Neue Vektoren separat rot nachgewiesen | 136 bestanden |
| Bestehende C#-Journalgruppe | Kein neuer Ausgangsfehler behauptet | Bestanden |
| Bestehendes CoreTests-Projekt | Unveränderter Build für Vergleich verwendet | Build mit gesperrten Abhängigkeitsversionen, 0 Warnungen, 0 Fehler |

Die 136 Python-Fälle bestehen aus `test_restore_identity.py`,
`test_save_restore_boundary.py`, `test_restore_commit_result.py` und
`test_backup_profile_validation.py`. Die neuen tatsächlichen Restore-Fälle
prüfen die geschriebenen Bytes, Schutzsnapshot und Originalsnapshot,
unbeteiligte Notizinhalte, zwei Wiederherstellungen, neue Instanzen nach
Neustart und die Ablehnung eines veralteten Saves. Ein mehrdeutiger Kontaktfall
bestätigt unveränderte primäre Bytes bei `committed=false`.

Die 12 neuen gemeinsamen Vektoren decken UID-Zuweisung, fehlende alte UID,
UID-Wechsel und -Entfernung, Erhalt aktueller Bindungen, einen konkurrierenden
Datensatz mit der alten UID, den bisherigen UID-Fallback sowie verschiedene
Mehrdeutigkeiten ab. Leere alte Inhaltsfelder und unbekannte Metadaten werden
bei einem UID-Wechsel nicht erfunden oder zurückgeholt.

Die ursprünglichen geschlossenen Korrekturen #818/#823/#601 wurden zuvor mit
98 fokussierten Python-Fällen auf der unveränderten Basis nachgeprüft; alle
bestanden. Der neue Befund betrifft einen zusätzlichen Kontaktablauf.

## Wiederholung mit den vorhandenen Werkzeugen

Verwendet wurden Python 3.12.14 mit pytest 8.3.5, Node 24.22.3 mit JSDOM 26.1.0 und das
vorhandene .NET-CoreTests-Projekt mit SDK 8.0.408. `BASE` und `FIXED` bezeichnen
getrennte Checkouts der obigen Quellstände; die neuen Vektoren liegen in `FIXED`.
`DOTNET` und `PYTHON` bezeichnen die vorhandenen Werkzeuge. Die aufgeführten
Prüfungen verwenden ausschließlich synthetische Kontakte und isolierte Dateien.

```bash
# Rote Python-Basis gegen dieselben neuen Sollvektoren:
"$PYTHON" run-python-vectors.py "$FIXED" "$BASE"

# Grüne fokussierte Python-Prüfung, im korrigierten Checkout:
mkdir -p /tmp/opencode
cd "$FIXED"
"$PYTHON" -m pytest -q \
  magnolie-organizer/pruefungen/test_restore_identity.py \
  magnolie-organizer/pruefungen/test_save_restore_boundary.py \
  magnolie-organizer/pruefungen/test_restore_commit_result.py \
  magnolie-organizer/pruefungen/test_backup_profile_validation.py

# Vorhandener C#-Host, keine neue Produkt-Testumgebung:
"$DOTNET" build magnolie-organizer-windows/tests/CoreTests.csproj \
  -p:RestoreLockedMode=true -v minimal
cd "$FIXED/magnolie-organizer-windows"
MAGNOLIE_TEST_SOURCE_ROOT="$FIXED" "$DOTNET" \
  tests/bin/Debug/net8.0/CoreTests.dll 'Additive restore'
MAGNOLIE_TEST_SOURCE_ROOT="$FIXED" "$DOTNET" \
  tests/bin/Debug/net8.0/CoreTests.dll 'Wiederherstellungsjournal'
```

Die rote C#-Prüfung verwendet die auf der Basis gebaute `CoreTests.dll`, mit
`MAGNOLIE_TEST_SOURCE_ROOT` auf den korrigierten Checkout für die neuen Vektoren.
Sie scheitert erwartungsgemäß an
`contact-import-assigned-uid-keeps-stable-local-id`. Die Logdateien halten den
tatsächlich ausgeführten Vergleich fest.

`frontend-repro.cjs CHECKOUT OUTPUT_DIRECTORY` lädt beide vollständigen
Produktfrontends und erzeugt die synthetischen Bücher. Es verwendet die bereits
vorhandene Zeitzonenprojektion im Speicher, ohne eine Produktquelle umzuschreiben.
JSDOM wird über die übliche Node-Modulauflösung bereitgestellt.
`Probe.cs` und `Probe.csproj` dienen ausschließlich der Diagnose: Sie rufen per
Reflection die tatsächlich kompilierte interne Auswahlfunktion aus einer
übergebenen `CoreTests.dll` auf; sie enthalten keine nachgebildete Auswahlfunktion.
Die Hauptregression bleibt Teil der bestehenden gemeinsamen Tests.

## Grenzen und Einordnung

JSDOM belegt den DOM-/Quellablauf auf dem Host. Der C#-Lauf führt die wirkliche
Produktfunktion in CoreTests unter Linux aus. Das ist keine installierte
Windows-/Linux-GUI-, DPAPI-, Paket- oder Geräteabnahme. Reale isolierte
Dateispeicherung und Wiederherstellung wurden im Python-Host ausgeführt.

Die frische Testumgebung benötigte den von vorhandenen Tests erwarteten Ordner
`/tmp/opencode` und für die C#-Journalgruppe das dokumentierte Arbeitsverzeichnis
`magnolie-organizer-windows`. Ein neuer Test las zunächst nach der normalen
Journalmigration noch den alten Profilpfad; sein abschließender Readback verwendet
nun denselben kanonischen Journalpfad wie der native Restore. Diese
Prüfvorbereitungen waren keine zusätzlichen Produktfehler.
