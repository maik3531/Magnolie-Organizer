# Mac-Geräteseite mit vorhandenen Importwegen — #784

## Bestätigter Ausgangsbefund

Die tatsächliche Mac-Projektion des aktuellen gemeinsamen Quellstands
`c9c3ebebd621e3562c601a2fa6d49909ca42fadd` zeigte im Einstellungsreiter
„Magnolia tree“ die drei Karten „Magnolie Notes phone connection“, „KDE Connect“
und „Magnolienbaum“ jeweils mit dauerhaftem „One moment…“. Zusätzlich war
„Restore media / Refresh“ bedienbar. Die dazugehörigen Telefon-, Notes-, KDE-
und Medienbefehle haben noch keinen Mac-Handler. Die bestehende Bridge wies sie
ab; die allgemeinen Desktop-Karten warteten trotzdem auf Statusantworten.

Der Befund wurde mit dem vorhandenen JSDOM-Host auf der vollständig erzeugten
Oberfläche reproduziert. Eine separate Magnolie-Notes-Begleitapp wird für die
Mac-Importwege nicht vorausgesetzt. Ein vorhandener externer KDE-Connect-Client
und die direkte Steuerung dieses Clients aus Magnolie sind getrennte Funktionen.

## Änderung

Zwei genaue Anker in `tools/project_ui.py` ersetzen nur die Darstellung dieses
Mac-Einstellungsreiters und seine Beschriftung. `Projection/device-import-page.js`
baut „Geräte und Importe“ mit den vorhandenen Formular- und Buttonbausteinen.
Die gemeinsamen Linux-/Windows-Quelldateien, die native Befehlsliste und sämtliche
nativen Importhandler bleiben unverändert.

Die Seite bietet genau sechs bestehende Einstiege:

| Aktion | Bestehender Anschluss |
| --- | --- |
| Notizdateien auswählen | `macOSBetaStartNoteImport` → `notiz_dateien_importieren` |
| Kalenderdatei auswählen | `starteImport("ics")` → `import` mit `art: "ics"` |
| Termine aus Mac-Kalendern kopieren | `macOSBetaStartCalendarImport` |
| Mac-Kontakte kopieren | `macOSBetaStartContactImport` |
| Mac-Erinnerungen kopieren | `macOSBetaStartReminderImport` |
| Textkopien aus Apple Notizen | `macOSBetaStartAppleNotesImport` |

Dateien werden zuerst über die eigene KDE-Connect-App oder AirDrop auf dem Mac
gespeichert und anschließend bewusst ausgewählt. Der vorhandene Dateiimport
unterstützt TXT und Markdown als Textnotizen, PDF und JPEG/PNG/GIF/WebP als
Anhänge sowie ICS-Kalenderdateien. Die Seite verspricht keine automatische
Ordnerüberwachung, Konvertierung anderer Formate oder direkte Telefonsteuerung.

Die Apple-Einstiege verwenden ihre vorhandene Auswahl, Vorschau, Prüfung und
Speicherung lokaler Kopien. Die Seite erklärt ausdrücklich, dass lokale
Änderungen nicht zurücksynchronisiert werden. Für direkte Telefonsteuerung,
Kopplung, Synchronisierung und Magnolienbaum-Freigabe zeigt sie eine klare
Nichtverfügbarkeitsmeldung. Sie startet keine Abfragen an fehlende Dienste und
enthält keine wirkungslosen Pairing-, Aktualisierungs- oder Medienknöpfe.
Dies ist keine grundsätzliche Sperre von KDE Connect; eine spätere direkte
Magnolie-Anbindung benötigt einen eigenen tatsächlichen Mac-Handler.

## Bestehende Speicher- und Entwurfsgrenzen

Alle sechs Aktionen teilen eine Wartesperre, solange ein Einstieg auf eine
Entwurfsentscheidung oder Speicherquittung wartet. Wiederholte und konkurrierende
Klicks, auch nach einem Neuaufbau der Seite, reihen keinen zweiten Pickerstart
ein. Save-NACK, Entwurfsabbruch und abgewiesene Starts geben die Knöpfe wieder
frei. Die Sperre bleibt an genau den laufenden Start gebunden.

Der vorhandene Navigationsguard wird vollständig abgeschlossen, bevor die
dauerhafte Speicherquittung und ein vorhandener Importstarter verwendet werden.
Dadurch kann auch ein ausdrücklich verworfener Entwurf den verschachtelten
Guard eines bisherigen Starters nicht versehentlich blockieren. Die vier Apple-
Aktionen verwenden unverändert diese bisherigen Starter. Die zwei Dateieinstiege
schließen die Einstellungen nach der Speicherquittung vor der Dateiauswahl. Die Bereitschafts-/Restoreprüfung und der Kontenentwurfsguard
werden vor und nach der Speicherquittung geprüft. Ein weiteres offenes Modal
verhindert den Dateistart. Der Callback bleibt an dasselbe Buch gebunden.
Erst danach schließt der kanonische Settings-Abschluss die Einstellungsseite.

Ein Save-NACK lässt Seite, Buch und ausstehende Änderungen bestehen. Ein
abgebrochener Entwurfsdialog lässt den Editor mit seinem Inhalt bestehen.
Das Öffnen eines Pickers importiert noch nichts und meldet keinen
Import-Erfolg. Vorschau, Recovery-Checkpoint und tatsächlicher Import-Save-ACK
bleiben Aufgaben der vorhandenen Importpfade.

## Ausgeführte Prüfungen

Umgebung: Linux, Node 24.22.3, JSDOM 26.1.0. Die vorhandenen 19 generierten
Kataloge wurden mit `po_zu_js.py` und GNU gettext 0.21 vorbereitet.
Native Antworten in den Hosttests sind synthetisch.

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| Neue Geräteeinstiege | 118 Prüfungen an der tatsächlichen projizierten UI in EN/DE; 2 absichtlich zerstörte Projektionsanker abgewiesen |
| Notizdateiimport | 41 bestehende Hostprüfungen bestanden |
| Mac-Kalenderkopien | 327 bestehende UI-Prüfungen bestanden |
| Apple-Notes-Textkopien | 195 bestehende UI-Prüfungen bestanden |
| Mac-Kontaktkopien | 246 bestehende UI-Prüfungen bestanden |
| Mac-Erinnerungskopien | 369 bestehende UI-Prüfungen bestanden |
| Allgemeiner tatsächlicher UI-Host | 109 bestehende Assertions bestanden |
| Vollständige/reproduzierbare Projektion | Bestanden |
| Freeze-/Manipulationserkennung | Bestanden |

Der abschließende gemeinsame Lauf aller neun Gruppen bestand in 40,367 Sekunden
mit Exitcode 0. Der neue Test prüft die sechs
tatsächlichen Buttons und ihre Nachrichten, keine Dienste beim Seitenaufbau,
die genaue EN-/DE-Beschriftung, fehlende Begleitapp-/APK-Voraussetzungen,
Save-ACK, Save-NACK mit erneutem Speichern, Entwurfsabbruch, erhaltenen
Kontenentwurf, Restore-Sperre und sichtbare native Ablehnung ohne Buchänderung.
Die unabhängige Prüfung fand und reproduzierte zunächst doppelt aufgereihte
Pickerstarts vor einem Save-ACK. Die Korrektur wird nun für alle sechs Aktionen
mit doppelten und konkurrierenden Klicks sowie Seitenneuaufbau geprüft.
Die Regression umfasst außerdem einen erst während des Speicherns geöffneten
Editor und den bewussten Discard-Retry. Der unabhängige Prüfer wiederholte die
118 Prüfungen erfolgreich und führte zusätzlich den Entwurf-verwerfen-Pfad
für alle sechs Aktionen aus: jeweils genau eine erwartete Nachricht.

```sh
python3 tests/test_host.py ProjectionTests.test_device_page_existing_import_capabilities
python3 tests/test_host.py \
  ProjectionTests.test_additive_selected_note_files_contract \
  ProjectionTests.test_additive_system_calendar_import_contract \
  ProjectionTests.test_additive_apple_notes_copy_contract \
  ProjectionTests.test_additive_system_contact_copy_contract \
  ProjectionTests.test_additive_system_reminder_copy_contract \
  ProjectionTests.test_actual_generated_ui_host_contract \
  ProjectionTests.test_projection_is_reproducible_and_full_ui \
  ProjectionTests.test_freeze_and_generated_tamper_detection
```

Arbeitsverzeichnis: `Magnolie-Organizer-macOS-Beta`; `MACOS_BETA_JSDOM` kann auf
die vorhandene `jsdom/lib/api.js` zeigen. Der neue Test ist in den normalen
Hostlauf eingebunden. Elf deutsche Ergänzungen verwenden das vorhandene
`native-extra-i18n.json`; Englisch ist der bestehende MsgID-Fallback.
Bestehende Übersetzungen und andere Sprachkataloge wurden nicht geändert.

## Grenzen

Hier wurden weder Swift noch AppKit/WKWebView ausgeführt. Reale Dateiauswahl,
KDE-Connect-/AirDrop-Übertragung, Systemberechtigungen und Datenträgerdauerhaftigkeit
bleiben native Abnahme. Es wurde keine KDE-Connect-Installation verändert,
keine Telefonkopplung vorgenommen und kein neuer Syncdienst implementiert.
Die Prüfung in zwei Sprachen ist keine sprachliche Abnahme aller 19 Kataloge.
Andere Desktop-Einstellungsseiten werden durch diesen engen Seitenpatch nicht
als vollständig an den Mac angepasst ausgewiesen.
