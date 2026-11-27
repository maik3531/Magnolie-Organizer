# #845: enger Rest nach Upstream 7a

**Dieser Nachtrag baut auf `7a490dd87e94eec08d7f09cb95a04b34bf4621c2` auf. Er ersetzt nicht die inzwischen übernommene BDAY-Erkennung.** Die beiden aktuellen Folgecommits `559c5c1f` und `573905f5`, ihre Parent-/Tree-Bindung und die zwei nacheinander anzuwendenden Formatpatches stehen in `delivery.json`. Der frühere Initialpatch `8d7263fd` ist historisch und darf auf dieser Basis nicht zusätzlich angewendet werden.

## Bestätigte Reste und gezielter Zusatz

1. **Linux-DAV lässt erkannten Geburtstag aus.** Die vorhandene Dateiklassifikation liest Nextcloud-BDAY korrekt als Jahrestag. Der gewöhnliche Linux-Terminabgleich verarbeitet diesen Ergebnisteil jedoch nicht. Ein tatsächlicher synthetischer Lauf auf 7a meldet Erfolg und liefert für diese Ressource weder Termin noch Jahrestag zurück. Der schon vorhandene Vorab-Schutz für noch nicht vollständig unterstützte typisierte Jahrestage erfasst nur Magnolie-Marker. Der Nachtrag erweitert genau diesen Schutz auf die tatsächlich erkannte Nextcloud-BDAY-Ressource, vor Kalenderwrites, Bereinigung oder bestätigtem Syncabschluss. Vollständiger Jahrestags-Sync #441 bleibt weiterhin offen.
2. **Typ-/Jahresänderung am29.Februar verliert die Monatsende-Regel.** Bei Änderung zu einem anderen Jahrestagstyp oder Änderung von Jahr/Jahrlosigkeit fällt der Upstream-Export auf `FREQ=YEARLY` zurück. Die ursprüngliche Nextcloud-Regel `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1` enthält auch den28.Februar in Nichtschaltjahren; eine gewöhnliche jährliche Februar-29-Regel enthält diese Tage nicht. Der Nachtrag erhält die vorhandene Regel, solange das kanonische Datum weiter den29.Februar bezeichnet. Eine Änderung auf einen anderen Monat/Tag verwendet weiterhin die passende normale Jahresregel.

3. **Normaler exportierter Geburtstag mit späterer Ausnahme.** Eine ergänzende tatsächliche C#-Probe auf dem ersten Folgecommit 559c bestätigte einen schon in7a vorhandenen Grenzfall: Nach dem normalen NC-BDAY-Import und tatsächlichen Export enthält der Master zusätzlich den eigenen Magnolie-Typmarker. Eine danach ergänzte RECURRENCE-ID wurde zwar erkannt, aber der normale eigene Jahreszweig konnte die bereits ermittelte Ausnahme übergehen. Zusatzcommit `573905f5` setzt genau den vorhandenen `allowProviderBirthday`-Guard vor die gesamte betroffene Jahrestagsentscheidung. Seine neue Regression durchläuft den tatsächlichen Import→Export→Reimport: ohne Ausnahme bleibt ein Geburtstag erhalten; mit Ausnahme bleiben Master und Ausnahme im Ereignispfad. Keine weitere Regel oder zusätzliche Suche wurde eingeführt.

Damit auch ein zweiter Export nach Reimport korrekt bleibt, verstehen ausdrücklich markierte Magnolie-Jahrestage diese genau begrenzte unendliche Monatsende-Regel. Gewöhnliche unmarkierte Ereignisse werden nicht durch den neuen Regelhelper zu Geburtstagen. Separate Serienausnahmen bleiben über den bestehenden Detached-Mechanismus im vollständigen Ereignispfad; die Vorprüfung wird auch für diese erhaltene Monatsende-Regel genutzt. Alte Nextcloud-BC-Marker werden bei bewusster Typ-/Datumsänderung weiterhin wie upstream entfernt. Fremde Metadaten bleiben erhalten.

## Vorher-/Nachherbeleg

| Prüfung mit denselben Testbytes | Unveränderte7a-Produktquelle | Folgepatch |
|---|---|---|
| Python: vorhandene Nextcloud-BDAY- und Jahrestags-Scopefälle plus6 neue Fälle |6 Fehler,19 bestanden |25/25 bestanden |
| C#: bestehende Gruppe `Nextcloud ICS birthdays` mit4 neuen Editfällen |Fehler am ersten falschen RRULE-Export; bestehende Fälle bis dahin bestanden |1/1 Gruppe bestanden |
| C#: vorhandene Gruppe `Nextcloud CalDAV` |bereits separat auf ursprünglichem Auditstand geprüft |1/1 Gruppe bestanden |
| C#-Build |erfolgreich |0 Warnungen,0 Fehler |

Die vier Editfälle trennen bekanntes und unbekanntes Jahr sowie Typwechsel und Jahreswechsel. Jeder prüft zwei Export-/Reimport-Runden, korrekten kanonischen Typ/Datum, Entfernung veralteter BC-Marker, fremde Metadaten und eine anschließend ergänzte separate Serienausnahme. Zwei weitere Pythonfälle rufen den tatsächlichen Linux-Sync mit normalem beziehungsweise Schalttag-BDAY auf und verlangen den vorhandenen ausdrücklichen Scopefehler, ohne Writes/Deletes oder Veränderung der übergebenen Daten.

Der erste Folgecommit wird durch `baseline-manifest.json` und `final-manifest.json` gebunden. Der zusätzliche Guard ist getrennt in `normal-detached-baseline-manifest.json` und `normal-detached-final-manifest.json` dokumentiert: identischer neuer Test auf 559c rot, nach dem Zusatz grün; die normale Kontrolle ohne Ausnahme bleibt bestehen. Beide Python-Eingaben sind seit 559c bytegleich und wurden dafür nicht erneut ausgeführt. Die Manifeste binden exakte argv, Arbeitsverzeichnis, Umgebung, Laufzeit, Exitcode und vier Eingangsdateien. Die erste C#-Filterauswahl ohne passende Gruppe ist separat als Setupversuch dokumentiert; sie zählt nicht als Regression. Ebenso bleibt eine während der Implementierung korrigierte lokale C#-Variablenkollision als erster Buildversuch erhalten und wird nicht als finales Testergebnis ausgegeben.

## Reproduzieren

Im Checkoutroot mit der vorhandenen Pythonumgebung:

```sh
PYTHONPATH="$PWD/magnolie-organizer/bin" /workspace/scratch/7203da5bd564/round3-tools/python/bin/python -m pytest -q magnolie-organizer/pruefungen/test_nextcloud_ics_birthdays.py magnolie-organizer/pruefungen/test_nextcloud_anniversary_scope.py
```

Nach locked restore/build des vorhandenen `CoreTests.csproj`, Arbeitsverzeichnis `magnolie-organizer-windows`:

```sh
/workspace/scratch/7203da5bd564/round3-tools/dotnet/dotnet run --project tests/CoreTests.csproj --no-build --configuration Debug -- "Nextcloud ICS birthdays"
/workspace/scratch/7203da5bd564/round3-tools/dotnet/dotnet run --project tests/CoreTests.csproj --no-build --configuration Debug -- "Nextcloud CalDAV"
```

Die verwendeten DOTNET_CLI_HOME-/NUGET_PACKAGES-Werte stehen im Manifest. Keine neue Toolchain und kein neuer Testserver.

## Grenzen und Integration

Dies sind tatsächliche Codec-/Orchestrierungsaufrufe mit synthetischen Daten und kontrollierten Transporten. Kein echter Nextcloudserver, kein Benutzerkonto, keine native GUI oder Geräteabnahme wurde verwendet. Kein Monatslaufzeittest und keine Paketfreigabe. Der gezielte Linux-Hold macht den fehlenden vollständigen Jahrestags-Sync #441 sichtbar; er implementiert ihn nicht. Die echte DAV-Konflikt-/Rechte-/Offline-/Neustart-/Journalmatrix #683 bleibt offen. Der separate #844-Farbrest wird eigenständig auf derselben7a-Basis integriert; die hier geänderten Bedingungen enthalten keine neue Farbeimplementierung.

Der bestehende vorgeschaltete Upstreamgrundfix und dieser enge Rest müssen als getrennte Stände bewertet werden. Die ursprüngliche große Alternative ist vollständig als historischer Beleg erhalten, aber nicht Bestandteil des aktuellen Anwendungsvorschlags.

## Aktuelle Anwendung

Nur die beiden Formatpatches `0008-Refs-845-followup-on-7a490dd8.patch` und `0009-Refs-845-exported-birthday-detached-guard.patch` in dieser Reihenfolge auf die angegebene 7a-Basis beziehungsweise entsprechend auf eine geprüfte Restserie anwenden. Der Initialpatch im übergeordneten Ordner ist ausdrücklich historisch.
