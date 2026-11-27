# #759 / #330: Medien-Wartezustand und erster Aufbau der lokalen Wiederherstellung

## Quellstand und Teilpatches

Die vollständige Issue-Bewertung verwendet `3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f`.
Diese zwei engen Teilpatches setzen auf dem danach ausdrücklich festgelegten
`50b1512234a765635f82af4537f277594fbf9878` auf. Das betroffene Windows-UI-Modul und
sein Statuskoordinator waren zwischen diesen beiden Basen bytegleich.

1. `7453838a78895e31f1103b2065692b6fabfae1fb`: ohne gemeinsame Medienwerte den
   Hauptschalter sichtbar und gesperrt halten, alte Optionen ausblenden und
   Änderungen vor sowie nach wartendem Save-ACK verhindern.
2. `d242f95c38d9c2c5ce42159318e3c7831b1aa80c`: anfängliche Historienanfragen und
   automatische Panelregistrierungen während des synchronen UI-Aufbaus erhalten.

Finaler Tree: `fe9242fc30a014fd850ca3b9e8c66b15747783be`.
Die Serie und ihr Gesamtdiff stehen unter `patches/`; `source-commit-binding.json`
bindet die tatsächlich geprüften Eingaben an diese Commits.

## Zwei bestätigte Fehler

**Fehlende gemeinsame Medienwerte:** `NativeMediaUiStatus` kann für eine unterstützte
ältere Verbindung Metadaten ohne `shared_settings` liefern. Das tatsächlich
ausgeführte Windows-Modul blendete dabei den Hauptschalter aus und ließ Foto- sowie
Automatikoptionen zu. Eine Fotoänderung führte sogar zu Save-ACK und einer nativen
`settings`-Nachricht. Der Patch zeigt dafür einen lokalisierten Wartezustand.
Eine spätere Statusänderung stellt die vorhandene gemeinsame Bedienung automatisch
wieder her. Status, das Stoppen eines bereits laufenden Vorgangs und lokale
Wiederherstellung bleiben erreichbar.

**Erste Anzeige vorhandener Sicherungen:** Die Anwendung erzeugt zunächst
`createRecoveryPanel`, dann `createPanel`, und hängt anschließend die Telefonzeile
an das Dokument. Der unmittelbare Statusabruf entfernte zuvor die gerade erzeugten
Historienanfragen, weil deren DOM noch nicht angehängt war. Im echten Aufbauablauf
kamen deshalb von zwei angebotenen Historienzeilen null an. Bei mehreren anfänglichen
Telefonzeilen konnte derselbe vorzeitige Abbau außerdem die automatische
Statusregistrierung der ersten Zeile entfernen. Der zweite Patch erledigt die
Entfernung abgelegter Panels erst nach dem synchronen Aufbau in einer gemeinsamen
Microtask. Peerbindung, Ablaufzeiten und die Prüfung auf ein angehängtes Panel beim
Empfangen bleiben bestehen. Ein endgültig entferntes Panel wird nicht durch eine
spätere alte Antwort wiederbelebt.

Die ursprüngliche rote Aufbauprobe bleibt in `initial-recovery-before.log` erhalten.
`initial-recovery-after-wait-only.log` zeigt denselben Fehler nach dem ersten
Teilpatch; er wurde ausdrücklich als zweiter Fehler korrigiert.

## Automatische Übernahme einer Einstellung

Es kommt kein Bestätigungsdialog und kein zusätzlicher Einrichtungsklick hinzu.
Der verfügbare gemeinsame Pfad liefert durch `NativeMediaSharedSettingsView` auch
vor dem ersten gespeicherten Shared-Datensatz eine editierbare Projektion.
Bearbeitung erfordert die technische Fähigkeit `MediaSharedControlsReady`,
keinen bereits abgeschlossenen ACK-Abgleich.

Die vorhandene Kette bleibt unverändert:

`shared_setting` → `ChangeNativeMediaUiSharedSettingAsync` →
`SendMediaSharedSettingsAsync` → Notes `MediaSyncTransport.receive` beziehungsweise
`NativeMediaSettingsLane.receive` → dauerhafte `storage.merge`-Übernahme →
technischer ACK und Echo. Die UI bekommt über `MagnolieMedia.changed` automatisch
einen neuen Status. Ein neuer Regressionstest editiert bereits bei
`shared_matched: false` und prüft genau eine Änderungsnachricht ohne Dialog.

**Produktgrenze:** Die Standard-Notes-Fähigkeitsliste bewirbt die hierfür benötigte
Discovery-Version derzeit nicht; die neue native Unterstützung ist ein privater
Integrationspfad. Die produktive gemeinsame Anbindung bleibt deshalb ein konkreter
Rest unter #330. Diese UI-Patches bestätigen weder eine fertige Notes-Übernahme im
installierten Produkt noch einen Foto-/Videotransfer. Der Wartezustand ersetzt diese
fehlende technische Integration nicht durch eine weitere manuelle Bestätigung.
Die getrennte Quellenprüfung ist in `review-759-automatic-path.json` dokumentiert.

### Begrenzter Nachtrag auf 24927cf9

Der zusätzliche Quellenvergleich bis zum festgehaltenen
`24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b` bestätigt dieselbe
Standard-Capability-Grenze. Inzwischen enthält `main` aber weitere konkrete
Implementierung: äquivalente WLAN-ACK-Erneuerungen in Linux und Notes,
verifizierte private Gruppen-Standardziele und einen begrenzten manuellen
Linux-Foto-Erstempfang über „Jetzt synchronisieren“. Bei diesem Erstempfang ist
der separate Empfangsschalter nicht erforderlich. Diese Bausteine dürfen nicht
weiter als fehlende Implementierung aufgeführt werden. Video-Erstempfang,
gemischte Läufe, Automatik und reale Paket-Paarabnahme bleiben getrennt.

`media-latest-delta.json` enthält die betroffenen Commits, konkrete Mitglieder
und 14 Quellhashvergleiche. Hierfür wurden keine neuen Laufprüfungen behauptet.
Die Windows-UI-Datei und ihr Statuskoordinator sind zwischen 50b15122 und
24927cf9 unverändert; die zwei vorliegenden Originalpatches bleiben an 50b15122
gebunden. Die gemeinsame aktuelle Restserie wird getrennt auf 24927cf9 angepasst.

## Tatsächlich ausgeführte Prüfungen

| Prüfung | Vorher | Final |
|---|---:|---:|
| Enger ursprünglicher Handlerfall ohne `shared_settings` | FAIL, alte `settings`-Nachricht gesendet | PASS, nur Status, kein Save |
| Neue Wartezustandsfälle | 0/6 | 6/6 |
| Neue initiale Recovery-/Mountfälle | 1/5 | 5/5 |
| Tatsächlicher anfänglicher Readback in der isolierten Aufbauprobe | 0/2 Historienzeilen | 2/2 Historienzeilen |
| Bestehendes vollständiges Medien-UI-Prüfprogramm | keine neue Baselinebehauptung | PASS |
| Bestehende Quellordner-UI-Fälle | keine neue Baselinebehauptung | 29/29 |
| Unabhängige Zustands-/Lifecyclefälle auf den endgültigen Bytes | separat dokumentiert | 4/4 |

Das sind vier direkt betroffene UI-Prüfprogramme. Die Anzahl einzelner Assertions
im älteren Gesamtprogramm wird nicht als zusätzliche Fallzahl ausgegeben.
Die Programme führen das tatsächliche UI-Modul in JSDOM aus. Es wurde kein
installiertes Windows-/Notes-Paket, keine VM und kein nativer Transfer ausgeführt.
Der unabhängige Lifecyclefall prüft unter anderem 128 Wiederaufbauten mit zwei
Telefonzeilen als Iterationen eines Falls, keine zusätzlichen 128 Tests und
keine Monats-/Heap-Abnahme. Die vollständige Freigabe liegt unter
`independent/final/review-759-lifecycle-signoff.json`.
Die bestehenden Tests wurden auf bestätigte gemeinsame Statuswerte umgestellt;
die bisher ausdrücklich erwarteten Legacy-Settings-/Mode-Fallbacks sind durch den
beauftragten Wartezustand ersetzt. Schutzprüfungen für Ziele, Vorschau, Historie,
Stop, einzelne Feldänderungen und fehlgeschlagenen Save bleiben erhalten.

## Erneut gezielt ausführen

Nach Anwendung beider Teilpatches mit den bereits vorhandenen Node-/JSDOM-Werkzeugen:

```sh
python run-focused-tests.py \
  --checkout /pfad/zum/gepatchten/repository \
  --tools /pfad/zu/round3-tools \
  --output /pfad/zu/neuen-nachweisen
```

Der Runner erwartet `js/node_modules/jsdom` unter dem Werkzeugverzeichnis und
erstellt vier Logs sowie ein Manifest mit Quell-/Test-Hashes. Er führt keinen Build
aus und kennzeichnet dies ausdrücklich mit `build_executed_by_runner: false` und
`build_exit_code: null`. Für die vorherigen roten Zustände sind die unveränderten
Quellbytes, Befehle und Rückgabecodes separat gebunden.

`ARBEITSSTAND-fragment.md` enthält den kurzen Abschnitt für die gemeinsame Übergabe.
Produktquellen, Paketbau und GitHub-Issues wurden durch diese Prüfungen nicht
veröffentlicht oder mit `main` zusammengeführt.
