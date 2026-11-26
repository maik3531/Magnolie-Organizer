# Android-Tablet: Prüfnachweise der Fortsetzung

Stand: 26. November 2026. Refs #795, #790, #791, #792, #798, #799, #800, #801 und #463.
Die Fortsetzung baut auf `29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14` auf.

## Abschließender tatsächlicher Prüfstand

[Actions #101](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
auf Head `7a7d90b04796cf338b98f0fdbb87e8da1c967043` besteht den vollständigen
APK-Gate und die echte API34-Providerstufe: **303 JUnit-Tests ohne Fehler/Skips**,
**zehn fachliche Providergruppen plus Cleanup**. Serienausnahme vorher/nachher
jeweils zwei Instanzen, 19 Produkt-/Readbackprüfungen ohne WRITE, beide vorab
abgebrochenen Abfragen und vollständige Bereinigung sind konkret bestätigt.
Originalbelege, 42 vollständige XML-Reports, APK-/Quellprüfsummen und der
tatsächlich ausgeführte Artefaktprüfer stehen in [ci-run-45822320243](ci-run-45822320243/README.md).
Die früheren Fehlläufe bleiben separat erhalten; [CI99](ci-run-45817099578/README.md)
enthält sowohl den externen HTTP429 als auch den ersten nativen Fixturebefund #807.

Der abschließende reine Dokumentations-/Nachweisnachtrag erhält alle 83
Laufzeitdateien bytegenau. [completion](completion/README.md) dokumentiert den
ausgeführten Vergleich und den abschließenden Delta-Abgleich aller 33
maßgeblichen Issues. Der gebaute und nativ geprüfte Head bleibt ausdrücklich
der oben genannte; vollständige UI-/Berechtigungsdialog-/Geräteabnahme folgt
daraus nicht. Die folgenden Abschnitte halten die früheren Hostnachweise fest.

## Historischer Vorbereitungsstand der ersten Folgepatches

**Geprüfte gemeinsame Webprojektion:**
`7a0c31a550761badd32e07f4bdaee6b016fd158a769a64017c7525332bb70416`.

Der lokale geprüfte Quell-/Dokumentationscommit
`dbe791faab785741ff9c6519ea443d69405ee00b` und der über GitHub angelegte Commit
`430f8ee41ac9ff938cf00362138651e1f7c5b743` haben exakt denselben Git-Baum
`4f5b27a2357b1eeb5cd01f6552d6ebd3aed4d12c`. Unterschiede ihrer Commitkennungen
betreffen die Commitmetadaten. `source-commit-mapping.json` bindet jeden der sechs
Quell-/Dokumentationscommits. Der anschließende Belegcommit ändert ausschließlich
diesen Ordner, keine Projektions- oder Buildquellen.

## Ergebnisse und Aussagegrenzen

| Prüfung | Tatsächliches Ergebnis | Rohbeleg |
| --- | --- | --- |
| Kontakt-/Terminkennung vor Fix | 2 erwartete Reproduktionsfehler am alten Produktionsmapper, JUnit Exit 1 | `native/before-junit.log`, `native/ProviderIdentityBeforeTest.kt`, `native/before-source-hashes.json` |
| Importfokus vor Fix | 69/108 bestanden, 39 Fehler | `browser/focus-before.json` |
| Importfokus nach isoliertem Fix | 108/108 bestanden | `browser/focus-after-108.json` |
| Sprach-/Fokuszwischenstand vor #801 | 119/119 bestanden | `browser/i18n-after-119.json` |
| Status vor #801 | In zwei Fenstern vom Dialog verdeckt; Text vorhanden, Hitprobe negativ | `browser/status-before.json` |
| Finales Importformular | 167/167 bestanden, drei Fenstergrößen | `browser/system-167.json`, `browser/system-167.log` |
| Finales allgemeines Tablet-Layout | 150/150 bestanden, zehn Fenster-/Schrift-/RTL-Fälle | `browser/layout-150.json`, `browser/layout-150.log` |
| Erzeugte gemeinsame Oberfläche | 194 bestanden | `web/web-194.log` |
| Tatsächliche Import-/Anhangsintegration | 46 bestanden | `web/import-46.log` |
| Native Import-/Quellen-/Anhangsrichtlinien | 46 JVM-Tests bestanden | `native/full-compile/run-xgr0rcb2/junit.log` |
| Kotlinprodukt und Ressourcen | 38 Kotlin-Dateien gegen echte Android-37.2-/AndroidX-Artefakte; aapt2 36, Link und echtes R.java erfolgreich | `native/full-compile/receipt.json` und zugehörige Logs |
| #463 Diagnosepolicy | 9 JVM-Tests bestanden, darunter 432 Kombinationen mit unverändertem Besitzprädikat | `ownership/junit.log`, `ownership/receipt.json` |
| #463 Reproduktion des mitgelieferten Skripts | Alle drei Compile-/JUnit-Befehle erfolgreich; erneut 9 Tests, reales Android-API-Kompilieren erfolgreich | `ownership/reproduced-commands.json`, `ownership/reproduced-receipt.json` und Logs |
| Provenienz-/Workflowvertrag | 22 Tests bestanden | `build/provenance-22.log` |
| Aktuelle Quelle/Projektion | 459 eingecheckte Eingaben gebunden, 19 PO-Kataloge reproduziert, 83 generierte Ausgaben geprüft | `build/source-binding.json` |
| Vollständiges lokales APK-Gate | Readiness mit Exit 2 abgelehnt: konfiguriertes JAVA_HOME enthält kein ausführbares javac | `build/readiness.log` |

Chromium war Version 156.0.8078.108. Die Browser-/jsdom-Prüfungen verwenden die
erzeugte echte Organizeroberfläche, aber synthetische Provider und Speicherung.
Die native Policyprüfung verwendet die Produktionsfunktionen mit synthetischen
Abfragen auf der Host-JVM. Reales Android-API-Kompilieren belegt keine ausgeführte
ContentResolver-Abfrage, keine D8-/APK-Paketierung und keine Geräteabnahme.

## Sichtbarkeit, Fokus und Datenerhalt

Der finale Browserlauf erzeugt einen tatsächlichen Kontakt-Identitätskonflikt
über den echten Importhelper. Live-Buch und gespeichertes Buch bleiben exakt
unverändert, der Fokus bleibt am Importknopf. Die deutsche Meldung befindet sich
in einer persistenten Live-Region innerhalb des Einstellungsdialogs. Nach Scrollen
passt ihr vollständiges Rechteck in den Dialoginhalt und die Hitprobe trifft sie:

| Fenster | Meldungsrechteck | Vollständig sichtbar / unverdeckt |
| --- | --- | --- |
| 600 × 960 | x43, y264, 498 × 65,25 CSS-Pixel | ja / ja |
| 800 × 480 | x39, y265, 706 × 43,5 CSS-Pixel | ja / ja |
| 600 × 360 | x35, y194, 514 × 65,25 CSS-Pixel | ja / ja |

Die Meldung muss in kurzen Fenstern gegebenenfalls durch Scrollen erreicht
werden. Es wird keine gleichzeitige Sichtbarkeit sämtlicher Formularfelder
behauptet. Alle 20 Systemimportkataloge enthalten neun nicht leere Texte;
die vorhandenen 100 Texte wurden durch den I18n-Fix nicht geändert. Das ist
keine Muttersprachlerprüfung aller Übersetzungen.

## Reproduktion

Zuerst die geprüfte Patchserie anwenden und die normalen Projektabhängigkeiten
bereitstellen. Die vorhandene Build-/Ressourcenkoordination bleibt für komplette
APK- und native Läufe verbindlich. Für die gezielten Hostprüfungen im Tabletordner:

```sh
node tools/project-web.cjs
node tests/web.test.cjs
node tests/system-import.test.cjs
MAGNOLIE_CHROMIUM=/path/to/chromium node tests/system-import-browser.cjs
MAGNOLIE_CHROMIUM=/path/to/chromium node tests/tablet-layout-browser.cjs
python3 -B tests/test_source_proof.py
node tools/project-web.cjs --check
```

jsdom und Playwright müssen auflösbar sein; bei externer Installation dafür
NODE_PATH bzw. MAGNOLIE_PLAYWRIGHT setzen. MAGNOLIE_TABLET_SYSTEM_OUTPUT und
MAGNOLIE_TABLET_LAYOUT_OUTPUT aktivieren die JSON-/Screenshot-Ausgabe. Der
archivierte einmalige Vorher-Statusprobe-Code enthält die ursprünglichen
absoluten Hostpfade; der finale Regressionstest ist der konfigurierte Repotest.

Die native Quellprüfung ist mit dem tatsächlich ausgeführten
`native/verify-native-followup.py` reproduzierbar. `ownership/reproduce.py`
reproduziert #463 und wurde ebenfalls tatsächlich ausgeführt:

```sh
python3 -B native/verify-native-followup.py --repository /path/to/repo \
  --dependencies /path/to/tablet-build-dependencies --output /path/to/new-native-proof
python3 -B ownership/reproduce.py --repo /path/to/repo \
  --dependencies /path/to/tablet-build-dependencies --output /path/to/new-ownership-proof
```

Beide verlangen die manifestegebundenen vorhandenen Abhängigkeiten. Deren
Hashes stehen in den Receipts; Downloadmanifeste sind im ersten Belegordner
`../android-tablet-2026-11-26/` gesichert. Die Skripte starten keinen Emulator
und ersetzen den vollständigen Gradle-Gate nicht.

Die Capturefunktion `snapshot` aus `tools/source-proof.py` wurde auf dem oben
angegebenen Quellcommit ausgeführt. Anschließend wurde dessen `bind`-Funktion
mit Kandidat `None` verwendet: ausdrücklich nur Quellen-/Projektionsbindung. Der vollständige
temporäre Bindungsbeleg ist durch `proofSha256` im kompakten Receipt gebunden;
die Funktion prüft diese Eingaben erneut. Bei Verwendung des bytegleichen
GitHub-Commits ändern sich die gebundenen Commitkennungen, nicht Quell- und
Projektionshashes.
Ein CLI-Bind mit APK-Kandidat wurde nicht ausgeführt oder simuliert.

## Vollständiger APK-Bau und offene Abnahme

Das manuelle Workflowziel `tablet-build-only` verwendet den bestehenden
vollständigen APK-Bau und dessen Quellbindung. Build-only wird in Job,
Artefaktnamen und Metadaten ausdrücklich ausgewiesen. Das Ziel überspringt die
Emulator-/Runtimeabnahme; alle vorhandenen nativen Ziele behalten ihre Gates.
Ein erfolgreicher Actions-Lauf muss separat mit Run-ID, exaktem Head und
APK-Hashes nachgewiesen werden. Dieser Ordner behauptet diesen Erfolg nicht.

Android-Provider, Berechtigungswechsel, Rotation/Prozessneustart, TalkBack/IME,
native Pixel-, SAF-, Restore- und Speichermatrix bleiben offen. #463 verbessert
die Diagnose; es löst die fehlende Accessibility-Fensterbindung nicht. Bekannte
Grenzen der lokalen Provideridentitäten stehen im Folgeaudit. Die Prüfungen
erteilen keine Releasefreigabe und ändern keine vorhandenen Nutzerdaten.

`checksums.json` bindet die hier gesicherten Belege. `patch-apply-source-series.json`
belegt die ersten sechs Folgepatches ab der angegebenen Basis; die vollständige
Serie einschließlich Belegpatch wird beim Bereitstellen erneut angewandt und im
Issue-Index mit ihrem Ergebnisbaum quittiert.
