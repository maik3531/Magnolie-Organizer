# Aktueller Arbeitsstand

## Mac #777: Apple-Erinnerungen als eigenständige lokale Aufgaben – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/777-macos-reminder-copy`, Basis
`a706c57132d3646139464d7d432abe3f860514d6` aus #775.** Der Zweig enthält weiter
AirPlay #721, Kalender #770, Apple-Notes-Textkopien #772, die Einstellungs-
Korrekturen #773/#774 und Kontakte #775. Die entfernte Standardbasis wurde als
`00776ce70e155c7a607ed55a4502d6fcee5a860c` bestätigt. Gemäß Nutzerauftrag
werden überprüfbare Quellpatches im Issue und auf dem Arbeitszweig für die
spätere Codex-Übernahme bereitgestellt; kein Merge nach `main`, kein Paket
und keine Veröffentlichung.

Der parameterlose Befehl `macos_erinnerungen_importieren` ist im nativen Menü
und unter den System-Internetkonten angebunden. Der neue direkte
EventKit-Reader nutzt die bestehende serielle Store-Queue und ausdrückliche
Systemfreigabe. Auswahl von Liste/Konto und offenen oder erledigten Einträgen,
vollständige Vorschau, erneuter ausgewählter Quellenabruf und dauerhafte
Speicherquittung sind verbunden. Die älteren allgemeinen Reader/Snapshots
behalten ihre getrennten Verträge und Einschränkungen.

Bis zu 100 Einträge und 16 MiB werden als eigenständige lokale Aufgaben
vorbereitet. Titel, Klartextnotiz, Erledigtstatus, unterstützte Daten und eine
sichtbar erklärte Gruppierung in drei Prioritäten werden übernommen.
Originalwerte und tatsächlich gelesene öffentliche Felder bleiben passiver
Quellenbeleg. Unteraufgabenbeziehungen, Tags, Markierungen, Anhänge,
Zuweisungen, Rich Text und Provider-Sonderfelder werden als nicht verfügbar
gekennzeichnet; ihre Abwesenheit wird nicht erfunden. Serien und Alarme
werden sichtbar ausgeschlossen. Es gibt keine Quelländerung, keinen
Rückabgleich, keine neue Benachrichtigung und keine zusätzliche iPhone-App.

DATE und floating werden direkt als unveränderte Gregorianische
Kalenderwerte abgebildet. Eine fehlende eigene DateComponents-Zeitzone wird
weder durch Kalender-, Objekt- noch Systemzeitzone ersetzt. Die Prüfung
deckte eine zusätzliche Verankerung durch den bisherigen Kalenderdecoder
auf; der neue Civil-Pfad erhält auch floating Uhrzeiten in Sommerzeitlücken
und -überlappungen. Nur ausdrücklich gebundene Zeiten verwenden die
gepinnten Zeitzonendaten; mehrdeutige Zeiten, Subminuten und nicht
bearbeitbare Kombinationen werden sichtbar ausgeschlossen.

Quellidentitäten werden bytegenau verglichen, alle neun Listen-/Kontofelder
und ausgewählten Rohdatensätze einschließlich Ausschlüssen neu geprüft.
Das ist eine Revision gelesener Felder, kein atomarer Serverstand. EventKit
liefert für die Eintragsauswahl bereits vollständige EKReminder-Objekte;
die Metadatengrenze von 10.000 greift nach dem Callback und ist keine
Zusicherung über dessen interne Allokation. Abbruch/20-Sekunden-Frist
beenden die eigene Fortsetzung genau einmal; verspätete Ergebnisse werden
verworfen, ohne sofortigen Abbruch synchroner Systemzugriffe zu behaupten.

Die tatsächliche kanonische UI erzeugt neue lokale IDs und Zeitstempel.
Sie prüft den gesamten Aufgabenbaum auf Klonen und hängt neue Wurzelaufgaben
erst nach bestätigtem Erhalt aller Bestandsaufgaben an. Lokale Änderungen,
bekannte Kopien und Papierkorbeinträge bleiben erhalten. Vorschautoken,
fünfminütige Frist, konkretes Buch samt vollständigem Inhalt, Zeitzone,
Entwürfe, Wiederherstellungspunkt und Save-ACK sind gebunden.

Die unabhängige Prüfung reproduzierte einen Folgefehler nach dem Anhängen:
Eine Ausnahme im öffentlichen Renderer-Hook ließ die neue Kopie im Buch und
einen Speichertimer aktiv, meldete aber nur den Darstellungsfehler. Der
neue Anschluss unterscheidet jetzt bestätigtes Save-NACK von noch nicht
bestätigter Speicherung. Eine echte UI-Regression prüft Erhalt, Save-Retry
und Wiedererkennung ohne Duplikat. Der gleiche Quellpfad älterer
Kalender-/Notes-/Kontaktkopien wird getrennt in **#778** geprüft.

Der von Root ausgeführte gemeinsame Lauf bestand **7/7 Testgruppen** in
29,029 Sekunden, Node 24.22.3 / CI-JSDOM 26.1.0:

| Prüfung | Tatsächlich bestanden |
| --- | --- |
| Erinnerungskopien mit vollständigem gemeinsamem Core-Fixture und echter projizierter UI | 369 Prüfungen |
| Kontaktkopien einschließlich Geburtstag/Editor und 14 Anker-Driftprüfungen | 230 Prüfungen |
| Apple-Notes-Textkopien einschließlich Kontoentwürfen | 179 Prüfungen |
| Systemkalenderkopien einschließlich Settings-Einstieg | 307 Prüfungen |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions |
| Bridgeinventar | Bestanden |
| Freeze-/Manipulationserkennung | Bestanden |

Danach wurde ausschließlich der deutsche native Berechtigungsfehlertext
ergänzt. Der abschließende getrennte Erinnerungs-Runner bestand auf diesen
finalen Eingaben erneut **369 Prüfungen mit unveränderter Eingabeinventur**.
Vier deutsche UI-/Vorschauprüfungen sind enthalten. Native Nutzlasten und
Transportantworten sind synthetisch. 31 neue Swift-Core-/Bridge-Testmethoden
sind vorbereitet, **hier weder kompiliert noch ausgeführt**. Tatsächlich
geprüft sind außerdem JSON-/Plist-Format, Übereinstimmung der 20 Rohfelder,
unabhängiger Identitätshash, vollständige ergänzte deutsche Meldungen und
sauberes Diff-Whitespace. Die finale Produktinventur enthält **432 Dateien**,
SHA-256 der sortierten Inventur
`39622893d7205e8485d8f47cdea8ebdefe378cb566c75a223a071a8ed2a75754`.
Kein SourceFreeze und kein dauerhaft erzeugter Bundle-Stand.

Native Swift-/EventKit-/AppKit-/TCC-/Konten- und Geräteabnahme bleibt gemäß
[SYSTEM-REMINDER-IMPORT.md](Magnolie-Organizer-macOS-Beta/SYSTEM-REMINDER-IMPORT.md)
offen. Der gemeinsame Aufgaben-Normalizer anderer Editionen übernimmt die
neuen Herkunftsfelder nicht wie der Mac-Erhaltungsvertrag. Diese konkrete
Quellenabweichung und die gesonderte Linux-/Windows-JSON-Austauschprüfung
stehen in **#779**; kein dortiger nativer Datenverlust wird behauptet.
**#776** bleibt der separate Kontaktgeburtstagsfall. Nächster Schritt ist
die Codex-Übernahme und native Abnahme des gesicherten Gesamtzweigs sowie
die getrennte Bearbeitung der benannten Folgeprüfungen.

## Mac #775: ausgewählte Systemkontakte als lokale Kopien – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/775-macos-contact-copy`, Basis
`f32f4daa71acea7f76fb9f58ff0f8d4794f728ab` aus #774.** Er enthält weiterhin
AirPlay #721, Kalender #770, direkte Apple-Notes-Textkopien #772 und die
Einstellungs-Guards #773/#774. Die entfernte Standardbasis wurde als
`00776ce70e155c7a607ed55a4502d6fcee5a860c` bestätigt. Gemäß Nutzerauftrag wird
der prüfbare Quellpatch im Issue und auf dem Arbeitszweig für die spätere
Codex-Übernahme bereitgestellt; kein Merge nach `main` und kein Paket/Release.

Der neue parameterlose Befehl `macos_kontakte_importieren` öffnet die native
Adressbuch-/Kontaktauswahl. Der direkte Contacts-Reader nutzt die vorhandene
serielle Store-Queue und ausdrückliche Systemfreigabe. Zunächst liest er
Kennungen/Namen, danach nur die ausgewählten nicht vereinheitlichten Kontakte.
Containerzugehörigkeit, Quellmetadaten und Berechtigung werden vor/nach dem
Detailabruf und nach der Vorschau erneut geprüft. Kein Note-Key, kein breiter
vCard-Descriptor, keine private Datenbank und keine Quellschreiboperation.

Bis zu 100 Kontakte und 16 MiB werden als bewusste lokale Kopien vorbereitet.
Standardfelder, Mehrfachwerte, Labels, Originalfotos und unterstützte Geburtstage
laufen durch die tatsächliche kanonische Normalisierung. Nur ausdrücklich
angezeigte E-Mail-Kleinschreibung ist zugelassen; andere verlustbehaftete Fälle
werden sichtbar ausgeschlossen. Zusätzliche gelesene öffentliche Felder bleiben
als gekennzeichnete Ursprungsdaten erhalten, ohne vollständige Provider-Sicherung
zu behaupten. Das entitlementgeschützte Kontakt-Notizfeld wird nicht angefordert.

Native Herkunft und unabhängige lokale IDs bleiben getrennt. Gleiche Namen,
E-Mail-Adressen oder Telefonnummern führen zu keiner Zusammenführung. Bekannte,
veränderte und im Papierkorb liegende Kopien werden nicht überschrieben oder
neu angelegt. Der Vorschlag bindet das tatsächliche Buch und dessen Inhalt,
läuft nach fünf Minuten ab, prüft Entwürfe/Restore erneut und verwendet
Wiederherstellungspunkt plus dauerhafte Speicherquittung. Fehler nach dem
Anhängen lassen die Kopien ausdrücklich ungespeichert sichtbar.

Für `birthdayPolicy: "contact-only"` bleibt das Datum direkt am Kontakt; 14 enge
Mac-Projektionsanker verhindern automatische Jahrestage/namensgleiche Zuordnung
und bewahren die Semantik im Editor, beim Laden, im Druck-/ODS-Fallback und bei
MCP-`birth_date`. Jahrfreier 29.02. und ein ausdrücklich vorhandenes Jahr 1604
bleiben erhalten. Die unabhängige Durchsicht fand eine Lücke bei ungültigen
Texteingaben im neuen Geburtstagsfeld; sie wurde innerhalb dieses neuen
Anschlusses korrigiert. `31.02.2000` und `12.` behalten nun den gesamten Kontakt,
die Eingabe und den Editorfokus; bewusstes Leeren bleibt möglich. Gewöhnliche
Kontakte und ausdrücklich angeforderte Jahrestagsmutationen bleiben unverändert.

Der abschließende von Root ausgeführte gemeinsame Lauf bestand **6/6
Testgruppen** in 20,627 Sekunden, Node 24.22.3 / CI-JSDOM 26.1.0:

| Prüfung | Tatsächlich bestanden |
| --- | --- |
| Kontaktkopien mit gemeinsamem vollständigem Core-Fixture, echtem Editor, Settings, MCP und ODS | 230 Prüfungen sowie Driftprüfung der 14 Geburtstagsanker |
| Apple-Notes-Textkopien einschließlich Kontoentwürfen | 179 Prüfungen |
| Systemkalenderkopien einschließlich Settings-Einstieg | 307 Prüfungen |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions |
| Bridgeinventar mit neuer expliziter Fähigkeit | Bestanden |
| Freeze-/Manipulationserkennung | Bestanden |

Native Nutzlasten und Transportantworten sind synthetisch. Der getrennte
Kontakt-Runner bestand ebenfalls 230 Prüfungen mit unveränderter
Eingabeinventur. 25 neue Swift-Core-/Bridge-Testmethoden sind vorbereitet,
**hier weder kompiliert noch ausgeführt**. Zusätzlich tatsächlich geprüft:
JSON-/Plist-Format, Fixture-Identität, PNG-Struktur/CRC/Scanlines und sauberes
Diff-Whitespace. Finale Produktinventur: **428 Eingangsdateien**, SHA-256 der
sortierten Inventur `791b8f37633ef06cb44171bc6c42f758777f36e4a0c10eb4c0b73c652bb33968`;
kein SourceFreeze und kein dauerhaft erzeugter Bundle-Stand.

Native Swift-/Contacts-/ImageIO-/AppKit-/Konten- und Geräteabnahme bleibt gemäß
[SYSTEM-CONTACT-IMPORT.md](Magnolie-Organizer-macOS-Beta/SYSTEM-CONTACT-IMPORT.md)
offen. Vollständige Sprachkatalog-/Paketprüfung wird nicht aus den ergänzten
und tatsächlich geprüften deutschen Mac-UI-Texten abgeleitet. Der gemeinsame
Normalizer anderer Editionen kennt die neue Geburtstagsregel noch nicht;
die konkrete Quellenabweichung und gesonderte Linux-/Windows-Austauschprüfung
stehen in **#776**. Kein dortiger nativer Datenverlust oder Alarm behauptet.
Nächster Schritt ist die Codex-Übernahme und native Abnahme des gesicherten
Gesamtzweigs; Erinnerungen behalten ihren getrennten offenen Abbildungsumfang.

## Mac #774: Kontoentwürfe beim Notes-Import erhalten – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/774-notes-account-draft`, Basis
`fbb50c2c9146091a778fdb45608b315a67d64899` aus #773.** Dieser Zweig enthält
die direkte Apple-Notes-Textkopie #772 sowie die getrennten Korrekturen #773 und
#774, aufbauend auf Kalender #770 und AirPlay #721. Die Patches bleiben für die
spätere Codex-Übernahme bereitgestellt; `main` und Pakete sind unverändert.

Die mit erfundenen Testdaten tatsächlich reproduzierte Lücke im neuen Notes-
Start ist geschlossen: Separate Server-/Benutzerentwürfe und eine alleinige
Kennworteingabe in sichtbaren Einstellungen blockieren den Import vor der
Navigation und erneut nach dem Save-ACK. Dialog, Werte und Buchdaten bleiben
erhalten; weder native Notes-Auswahl noch DAV-Speicherung werden gestartet.
Verborgene alte Felder nach bewusstem Schließen blockieren spätere Menüstarts
nicht. Die vorherige Reproduktion betraf nur ungespeicherte Formulareingaben,
keine bereits gespeicherten Zugangsdaten oder tatsächlichen Nutzerkonten.

Der gezielte Notes-Runner bestand mit **179 Prüfungen** und stabiler
Eingangsdatei-Inventur. Der anschließend von Root gemeinsam ausgeführte Lauf
gegen den vollständigen aktuellen Stand bestand **3/3 Testgruppen**:

| Abschließende Prüfung | Ergebnis |
| --- | --- |
| Apple-Notes-Textkopien, tatsächlicher Settings-Knopf und Kontoentwürfe | 179 Prüfungen bestanden |
| Systemkalenderkopien einschließlich Settings-Einstieg und Kontoentwürfen | 307 Prüfungen bestanden |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions bestanden |

Node 24.22.3 / CI-JSDOM 26.1.0; native Quellnutzlasten und Transportantworten sind
synthetisch. Der zuvor abgeschlossene #772-Lauf bestand zusätzlich die
Notizdateiübernahme (23 Prüfungen), das Bridgeinventar und die Freeze-/
Manipulationserkennung. Die neue Korrektur verändert nur den Notes-Startpfad,
seine Regressionstests und Dokumentation. Finales Quellaudit: 424 Eingangsdateien,
kein Freeze oder dauerhaft erzeugter Bundle-Stand; Diff-Whitespace sauber.

18 neue Swift-Core-/Bridge-Tests aus #772 bleiben mangels Swift/Mac unkompiliert
und unausgeführt. Native Notes-Dictionary, Automation-Berechtigung, stabile
Objektreferenzen und die echten Mac-/iPhone-Daten müssen nach
`APPLE-NOTES-IMPORT.md` geprüft werden. Vollständige Sprachkatalog-/Native-Bau-
und Geräteabnahme werden durch diese Projektionsprüfungen nicht behauptet.
Nächster Schritt ist die native Übernahme-/Abnahme dieses gesamten Zweigs;
Kontakte und Erinnerungen behalten ihre getrennten offenen Abbildungsaufgaben.

## Mac #773: Kalenderimport aus den Einstellungen – 25. November 2026

**Quellpatch auf `work/773-calendar-settings-entry`, Basis
`6ffe768f382fbbca3e8f531c93f9ee197eba59a7` aus #772.** Der reproduzierte Fehler
im bestehenden Kalender-Startpfad #770 ist korrigiert: Nach Navigations-Guard
und dauerhafter Speicherquittung schließt ausschließlich der eigene
Einstellungsdialog über dessen kanonischen Pfad. Zusätzliche Modale, abgebrochene
Editorentwürfe und fehlgeschlagene Speicherung verhindern weiterhin den Start.
Der native Befehl bleibt parameterlos; die Vorschaugrenzen bleiben unverändert.

Separate DAV-/Nextcloud-Entwürfe liegen nicht im gewöhnlichen Buch-Save oder im
aktiven Organizer-Editor. Deshalb prüft der Start sichtbare Einstellungen vor
Navigation/Speicherung und erneut nach dem Save-ACK auf geänderte Kontofelder
oder eine nichtleere Kennworteingabe. Die Felder bleiben erhalten; es gibt weder
automatisches Speichern noch Verwerfen. Versteckte alte Kennwortfelder nach
einem bewussten Schließen blockieren spätere Menüstarts nicht.

Der vorhandene gezielte Kalenderprüfer bestand mit **307 Assertions**, Node
24.22.3 / CI-JSDOM 26.1.0 und stabiler Eingangsdatei-Inventur. Er führt den echten
Settings-Knopf mit korrelierter Quellenantwort und vollständigem synthetischem
Kalender-DTO bis zur Vorschau, zum Recovery-Checkpoint und zur dauerhaften
Speicherquittung aus. Zusätzliche Modale, tatsächliche Editorentwürfe,
Speicherfehler sowie URL- und alleinige Kennworteingaben vor/während des
Start-Speicherns sind geprüft. Diff-Whitespace sauber.

Keine Swift-/EventKit-/native Mac-Prüfung aus diesem JS-Nachweis abgeleitet;
keine gemeinsame Linux-/Windows-Quelldatei geändert. Kein Merge oder Paket.
Bei derselben Prüfung ist die gesonderte Kontoentwurfslücke im neuen
Notes-Start #772 konkret reproduziert worden; sie wird anschließend als
eigenständiger Patch zu #774 behoben. Die Reproduktion verwendet ausschließlich
erfundene Werte und zeigt Verlust ungespeicherter Eingaben, keine Veränderung
gespeicherter Zugangsdaten.

## Mac #772: direkte Apple-Notizen als lokale Textkopien – 25. November 2026

**Quellpatch auf `work/772-apple-notes-copy`, Basis Kalenderpatch
`2b3a7cea5093b80de1dd14bdf5afaf84231d66ad` aus #770.** Die abgerufene
Standardbasis ist `00776ce70e155c7a607ed55a4502d6fcee5a860c`. Weiterhin gilt der
Nutzerauftrag, konkrete Patches im Issue zur späteren Codex-Prüfung und Übernahme
bereitzustellen. Kein Merge nach `main`, kein installierbares Paket und kein Release.

Der neue parameterlose Befehl `macos_apple_notizen_importieren` startet die
ausdrückliche Konto-/Ordner-/Notizauswahl. Der eingebaute Reader verwendet feste
NSAppleScript-Handler, typisierte Apple-Event-Argumente und Antworten sowie eine
prozessweit serielle Hintergrundqueue. Die reguläre Automation-Zweckbeschreibung
ist ergänzt. Keine zusätzliche Anwendung, kein `osascript`, keine private
Notes-Datenbank und keine Apple-Notes-Schreib- oder Löschbefehle. Notizen vom
iPhone müssen im gewählten vorhandenen Mac-Notizkonto verfügbar sein.

Bis zu 32 ausgewählte Notizen werden als bewusste Textkopien vorbereitet;
Schutzstatus, Anhänge, Titel, Plaintext, HTML-Repräsentation, Änderungsinformation
und tatsächliche Konto-/Ordner-/Notizkennungen werden geprüft. Geschützte und
anhangshaltige Notizen liefern keine Bodies und erscheinen als Ausschlüsse.
Je Text-/HTML-Feld gelten 1 MiB; Nachweis und finale Nutzlast sind unabhängig auf
8 MiB begrenzt. Dies sind Antwort-/Verarbeitungsgrenzen, keine zugesicherte
Vorab-Allokationsgrenze innerhalb der Apple-App.

Die Vorschau zeigt die vollständigen Texte und das tatsächliche Zielnotizbuch.
Die Kopieridentität bindet bytegenau Konto und Notiz, der Ordner gehört zur
Revision. Wiederimport, geänderte Quelle und Ordnerwechsel überschreiben keine
lokale Bearbeitung; Papierkorbeinträge werden nicht neu angelegt. Nach Freigabe
wird dieselbe Auswahl erneut gelesen. Der private UI-Vorschlag bindet Buch,
Zielnotizbuch, Entwürfe einschließlich ausstehender Notizeditor-Snapshots und eine
begrenzte Gültigkeit. Nur neue kanonische Notizen werden normalisiert. Erfolg
folgt erst nach Recovery-Checkpoint und dauerhafter Speicherquittung.

Quell-HTML bleibt inaktive Herkunft und wird nicht gerendert. Leere Inhalte,
LF, Tabs, Emoji und kombinierende Zeichen bleiben in der geprüften Projektion
erhalten; CR/CRLF und sonst durch den vorhandenen Editor veränderte Texte werden
sichtbar ausgeschlossen. Formatierung, Checklisten, Tabellen, Zeichnungen und
andere Notes-Funktionen werden nicht als entsprechende Funktionen konvertiert.
Die Textkopie ist kein vollständiges Notes-Archiv oder laufender Abgleich.

| Tatsächlich geprüfter Umfang | Ergebnis |
| --- | --- |
| Neue Notes-Übernahme mit tatsächlicher kanonischer UI und synthetischen nativen Daten/Antworten | 155 Prüfungen bestanden; Node 24.22.3, CI-JSDOM 26.1.0 |
| Bestehende Notizdateiübernahme | 23 Prüfungen bestanden |
| Bestehende Kalenderübernahme | 258 Prüfungen bestanden |
| Allgemeiner UI-Host | 109 Assertions bestanden |
| Gemeinsamer abschließender Python-Lauf | 6/6 Tests bestanden, einschließlich Bridgeinventar und Freeze-/Manipulationserkennung |
| Quellaudit, JSON/Plist, Python-Syntax und Diff-Whitespace | 424 Eingangsdateien; neuer Befehl und Automation-Zweckbeschreibung vorhanden; kein Freeze oder dauerhaft erzeugter Bundle-Stand |
| Neue Swift-Kern-/Bridgeverträge | 18 XCTest-Methoden vorbereitet, nicht ausgeführt; `swift`/`swiftc` hier nicht vorhanden |
| Native Swift-/AppKit-/Notes-Dictionary-/Automation-Ausführung und echte Mac-/iPhone-Konten | Nicht durchgeführt |

Native Restmatrix und Quellen: `Magnolie-Organizer-macOS-Beta/APPLE-NOTES-IMPORT.md`.
Die genaue Dictionary und Rückgabetypen, stabile zurückgelieferte Objektreferenzen,
Zugriff/Entzug, gesperrte/komplexe Notizen, Laufzeit und Abbruch sowie dauerhafte
Wiederöffnung müssen auf macOS 12.7 und einem aktuellen unterstützten macOS für
Intel/Apple Silicon geprüft werden. Ein Apple-Event-Timeout oder Task-Abbruch
behauptet keine harte Beendigung der Zielanwendung. Native Ergebnisse nach
Abbruch/Dokumentwechsel werden verworfen; blockierte Aufrufe erzeugen keine Queue
weiterer Importe. Die vollständige Sprachkatalogprüfung bleibt mangels `msgfmt`
offen. JavaScript-Prüfungen sind keine native Freigabe.

Separater bestätigter Befund #773: Der ältere Kalender-Importknopf in den
Einstellungen lässt den Einstellungsmodal offen und blockiert damit die spätere
Vorschau. Reproduziert über den echten projizierten Knopf mit synthetischem
Transport. Der neue Notes-Einstieg schließt ausschließlich diesen eigenen
Einstellungsdialog nach dem bestehenden Speicher-Guard; andere Modale bleiben
geschützt. Die entsprechende Kalenderkorrektur wird getrennt bearbeitet.
Keine gemeinsame Linux-/Windows-Quelldatei geändert oder dortige Behebung behauptet.

## Mac #770: Systemkalender als lokale Termin-Kopien – 25. November 2026

**Quellpatch auf `work/770-macos-calendar-import`, aufbauend auf dem gesicherten
AirPlay-Commit `25c5a849a89d8846b211ff98922a708dcc7e127d` aus #721.** Die erneut
abgerufene Standardbasis bleibt `00776ce70e155c7a607ed55a4502d6fcee5a860c`.
Nutzerauftrag: ohne eigene iPhone-App weiterentwickeln; Patches im Issue zur
späteren Codex-Übernahme bereitstellen. Kein Merge nach `main`, kein Paketbau
oder Release aus diesem Schritt.

Der neue parameterlose Mac-Befehl `macos_kalender_importieren` öffnet einen
nativen EventKit-Kalender-/Datumsdialog. Nach ausdrücklich angeforderter
Systemfreigabe werden höchstens 366 Tage, 10.000 Datensätze und 16 MiB gelesen
und geprüft. Einfache Einzeltermine werden über den bestehenden kanonischen
ICS-Codec vorbereitet. Präzise UTC-Zeiten einschließlich Sekunden und Folds
sowie DATE-/Ganztagsgrenzen bleiben erhalten. Serien, Alarme, Teilnehmer,
Geburtstagsquellen und sonst nicht unverändert abbildbare Termine erscheinen
mit Gründen als Ausschlüsse.

Die Vorschau unterscheidet neue, bereits übernommene, an der Quelle geänderte
und ausgeschlossene Termine. Herkunft bindet tatsächlichen Kalender,
Ereigniskennung und Elternkonto; gleiche Titel sind keine Dublettenidentität.
Vorhandene Kopien und lokale Bearbeitungen werden nicht überschrieben,
Papierkorbeinträge nicht neu angelegt. Nach Bestätigung wird die Quelle erneut
gelesen. Der private UI-Vorschlag prüft Buchinhalt, Generation/Zeitzone,
Sperre/Restore und auch zwischenzeitlich geöffnete Editorentwürfe vor und nach
dem bestehenden Recovery-Checkpoint. Erfolg erst nach dauerhafter Speicherquittung;
gescheiterte Abschlussspeicherung bleibt ausdrücklich ungespeichert sichtbar.

Gezielte Mac-Projektion in Normalisierung, Termin-Editor und Erinnerungsprüfung
verhindert erfundene Standardalarme bei den neuen Kopien. Bewusst im Editor
gesetzte Standardalarme oder einzelne lokale VALARMs bleiben nutzbar. Der
native bestätigte/vorläufige Status folgt dem vorhandenen editierbaren
`vorlaeufig`-Vertrag; sein ursprünglicher EventKit-Wert bleibt in der Herkunft.
Keine widersprüchliche zusätzliche rohe STATUS-Zeile.

| Tatsächlich geprüfter Umfang | Ergebnis |
| --- | --- |
| Neue Übernahme mit echter projizierter UI, vollständigen synthetischen DTOs, echtem Editor/Kalender/Erinnerungsplan und synthetischem nativen Speichertransport | 258 Assertions bestanden; Node 24.22.3, CI-JSDOM 26.1.0 |
| Bestehender allgemeiner UI-Host-Vertrag | 109 Assertions bestanden; gleiche CI-JSDOM-Version |
| Zusammengehöriger abschließender Python-Lauf | 5/5 Tests bestanden: neuer Import, vorhandener UI-Host, Bridgeinventar, Alarmadapter-/Ankerabweichung, Freeze-/Manipulationserkennung |
| Eingangsdateien im gezielten Importprüfer | Unverändert im abschließenden Lauf; zwischenzeitliche Änderungen werden ausdrücklich zurückgewiesen |
| Statisches Quellaudit | 420 Eingangsdateien; neuer Befehl inventarisiert; kein Freeze und kein dauerhaft erzeugter Bundle-Stand |
| Swift-Kern/SDK-Verträge | 16 XCTest-Fälle angelegt; nicht ausgeführt, `swift`/`swiftc` hier nicht vorhanden |
| Python-Syntax, JSON-Ressource und Diff-Whitespace | Geprüft |
| Native AppKit-/EventKit-/WKWebView-Ausführung, echte Mac-/iPhone-Konten und Geräte | Nicht durchgeführt |

Ein erster zusätzlicher allgemeiner UI-Lauf mit JSDOM 31.0.1 vermisste den
Capability-Block. Der unveränderte Test bestand anschließend sowohl gegen den
Vorgängerstand als auch gegen den aktuellen Stand mit 31.0.1 und mit der
CI-Vorgabe 26.1.0. Kein reproduzierter Produktfehler oder belegter genereller
JSDOM-31-Fehler; keine Testbedingung abgeschwächt. Die vollständige frühere
Sprachkatalogprüfung bleibt mangels `msgfmt`/erzeugter Kataloge unbestätigt und
wird nicht aus den gezielten englischen UI-Prüfungen abgeleitet.

Details, Bedienung, Grenzen, wiederholbarer Prüfbefehl und native Restmatrix:
`Magnolie-Organizer-macOS-Beta/SYSTEM-CALENDAR-IMPORT.md`.
`systemAccountSyncImplemented` bleibt false. Keine automatische Aktualisierung,
Rückschreibung oder Löschung in Apple-Konten. JSON-Sicherungen erhalten die
Herkunftserweiterungen; der strenge ICS-Export solcher Kopien bleibt bis zu einer
vollständigen Herkunftsabbildung gesperrt. Erinnerungen, Kontakte und Apple
Notes sind weiterhin eigene offene Anschlussaufgaben ohne neue iPhone-App.

Separater statischer Befund #771: Der ältere allgemeine EventKit-Leseguard
erlaubt 1464 Tage, während Apple Fenster über vier Jahre verkürzt. Die neue
Übernahme bleibt bereits vor dem nativen Read unter dieser Grenze (366 Tage).
Keine native Reproduktion oder Datenverlustbehauptung; kein nachgewiesener
Linux-/Windows-Fehler. Gemeinsame kanonische Produktdateien wurden hier nicht
verändert. Als Nächstes native Kompilierung und tatsächliche Kalender-/Rechte-/
Abbruch-/Speicher-/Wiederöffnungsfälle auf beiden Mac-Architekturen abnehmen;
danach den getrennten Aufgaben-/Kontakt-/Notizenanschluss fortsetzen.

## Mac #721: eingebauter iPhone-AirPlay-Empfänger – 25. November 2026

**Prüfbarer Quellpatch auf `work/721-macos-airplay`, Basis
`00776ce70e155c7a607ed55a4502d6fcee5a860c`; Übernahme und native Abnahme offen.**
Der Nutzer möchte Patches im Issue zur späteren Prüfung/Übernahme mit Codex.
Dieser Anschluss wird deshalb als benannter Arbeitszweig bereitgestellt.

UxPlay 1.73.7 ist mit Versions-/Quellenhashes und erhaltenen Lizenzen direkt
unter `Magnolie-Organizer-macOS-Beta/Receiver` enthalten. Der native Mac-Host
bietet Start/Stop/PIN, verarbeitet ausschließlich feste lokale Statusereignisse
und besitzt seinen eigenen Empfängerprozess. Das iPhone benötigt nur seine
vorhandene Bildschirmsynchronisierung. Der zusätzliche Bundlebau nimmt ein
ausdrücklich vorbereitetes SDK, baut den Helfer und liefert GStreamer/OpenSSL 3/
libplist samt Bibliothekskette, Quellen und Lizenzhinweisen innerhalb der App.
Eine Installation zusätzlicher Empfängerprogramme beim Anwender entfällt in
einem erfolgreich so gebauten Paket. Noch kein solches natives Paket erstellt.

| Prüfung dieses Patches | Ergebnis |
| --- | --- |
| Echter portabler C++-IPC-/Registrierungscode, `-Wall -Wextra -Werror` | 11 Tests bestanden |
| Synthetische Paket-/Bibliotheks-/Relocation-/Quellenfälle | 25 Tests bestanden |
| Versionierter Upstream-Abgleich | 76 vendorte Dateien geprüft; lokaler Delta-Patch gegen sauberen v1.73.7-Stand anwendbar |
| Bestehende Host-Prüfungen für Identität, Freeze-/Manipulationserkennung und Ablehnung falscher Linux-Bauzusage | 3 Tests bestanden |
| Bestehender vollständiger UI-Projektionstest | Fehlgeschlagen an fehlender Bauvoraussetzung: 0 statt 19 erzeugte Sprachkataloge; `msgfmt` in dieser Umgebung nicht vorhanden |
| Neuer portabler Swift-Vertrag, Decoder, Bundlepfade und private Ablage | 27 XCTest-Fälle vorbereitet; nicht ausgeführt, keine vorhandene Swift-Toolchain |
| Native Swift/AppKit-/GStreamer-Kompilierung, Codesign, echter Mac/iPhone-Lauf | Nicht ausgeführt |

Die Katalogvorbereitung bleibt der bestehende `po_zu_js.py`-/`msgfmt`-Weg.
Es wurden weder Tests abgeschwächt noch Ersatzkataloge erzeugt, um die fehlende
Voraussetzung zu verdecken. Die oben genannten gezielten AirPlay-Prüfungen
belegen keinen vollständigen Mac-Build. Der UI-Audit liest die neuen Quellen;
Produkt- und Gerätefreigabe bleiben getrennt.

Der ergänzende Nutzerauftrag zu Notizen, Terminen und weiteren iPhone-Funktionen
ist in `IPHONE-INTEROPERABILITY.md` gegen Apple-Primärquellen und vorhandenen
Magnolie-Code geprüft: Kalender/Erinnerungen über EventKit, Kontakte über
Contacts und gemeinsame Konten, Notizen über bestehenden Dateiimport oder einen
noch zu entwickelnden AppleScript-Connector am Mac. Eine eigene iPhone-App ist
dafür keine Voraussetzung. AirPlay liefert keinen Datensatzabgleich; der
bestehende Status `systemAccountSyncImplemented: false` bleibt zutreffend.

Nächster Schritt: Patch mit Codex übernehmen, die vorhandene Katalogvorbereitung
ausführen und native Swift-/Bundle-/iPhone-Abnahme für Intel und Apple Silicon
nach `AIRPLAY.md` durchführen. Keine Release-Veröffentlichung erfolgt.

`main` ist die Standardquelle. Dieser Eintrag trennt den verifizierten
Quellstand von der installierten Produktversion. Die nachfolgenden
Integrationsstände sind noch nicht Teil von `main`. Ihre Git-Zweige beim
Wechsel des Werkzeugs im autorisierten privaten Projekt-Git prüfen
(in der bestehenden Arbeitskopie: Remote `work-private`; in einer neuen
Arbeitskopie den vorhandenen autorisierten Remote einrichten). Ein
Arbeitsverzeichnis eines Assistenten ist keine Wiederherstellungsquelle.

Vor Änderungen `git status` lesen und fremde Änderungen im bestehenden
Arbeitsbaum stehen lassen. Die Zweige lassen sich nach
`git fetch work-private` mit
`git log -1 work-private/work/330-linux-settings` (entsprechend für Notes
oder Windows) prüfen. Erst den Pin vergleichen, dann bei Bedarf einen
eigenen Git-Arbeitsbaum auf dieser Revision anlegen.

| Aufgabe | Integrationszweig | Quellstand |
| --- | --- | --- |
| [#330](https://github.com/maik3531/Magnolie-Organizer/issues/330), Linux | `work/330-linux-settings` | `c418ddfaf5c9de1e422b03fdecb8bb9f92e72747` |
| #330, Linux – manuelle Bild-Gesamtsammlung | `work/330-linux-manual-images` | `6fcaa6cd1d058f29d6b89e5efb940b509f639a5e` |
| #330, Android Notes | `work/330-notes-settings` | `3fb976ecd45fbb6c4ad7a6f059990aa1eaa40d9e` |
| #330, Windows (nur Quelle) | `work/330-windows-media` | `7c83bdee58f2d56235032735b02952a2fc162caf` |
| [#245](https://github.com/maik3531/Magnolie-Organizer/issues/245), Linux – Spiegelung | `work/245-logind-owner` | `e1810778903a4fe534120742b93703684c1e86e6` |
| #245, Linux – privates Testpaket auf installierter Basis | `work/245-user-deb` | `47c84874c069c4700a42d79bc38795005e14320d` |
| #245/#763, Notes – Quellprüfung bestanden | `work/245-notes-user-draft` | `5993dbb3d289f20e2852a21cd20d28053a6ba72c` |

**Geprüft:** Linux-Oberfläche und beide Seiten des Einstellungsabgleichs in
Quell-/Loopback-Tests. Der Abgleich startet keinen Medienvorgang. Linux
gleicht gespeicherte WLAN-Einstellungen auch dann wieder ab, wenn der
Dateivorgang aufgrund eines fehlenden Zielordners oder einer nicht
unterstützten Richtung sicher gesperrt bleibt. Windows: String-/UI- und
portable Prüfungen sowie Windows-Zielkompilierung, kein nativer Medienlauf.

Die kombinierte Wiederholungsprobe ist auf den verlinkten Linux-/Notes-Pins
bestanden: Nach erneutem Verbinden blieb die Übereinkunft auf demselben
verschlüsselten Testkanal trotz unveränderter höherer Fähigkeitsrevision und
verspäteter älterer Meldung auf beiden Seiten erhalten. Kein Dateivorgang.
Das ist kein installierter WLAN- oder Gerätenachweis.

Die manuelle Bild-Gesamtsammlung kann auf dem separaten Linux-Zweig starten,
wenn das lokale Senderecht, eine ausdrücklich gewählte Bildquelle und der
kompatible, empfangsbereite Gegenpart vorliegen. Der Organizer lässt den
Start sichtbar, aber deaktiviert, solange die Voraussetzungen fehlen.
Eine passive Statusabfrage startet nichts. Oberfläche und drei
verschlüsselte Quelltests bestanden:
Abschluss mit zwei Originalen und Archiv, echter Widerruf, sowie sicheres
Anhalten vor dem Versand einer geänderten zugeordneten Handydatei. Der
Rückweg für „Nur Handybestand“ ist dadurch nicht freigegeben.

**Vorrangig [#763](https://github.com/maik3531/Magnolie-Organizer/issues/763):**
Eine zuvor aktive Telefonverbindung muss nach einem Notes-Update ohne Öffnen
der App oder manuelles Umschalten wiederkommen. AUS muss AUS bleiben. Der
Notes-Fix ist als Quellstand `fcfe26935e931df60945bb708a44223ec07f7856`
in `main` enthalten. Die drei gezielten Tests bestanden auf der Standardbasis
und separat auf `work/763-notes-integration`
(`381d2a5724c54e79bd4d8925fa4ae3bbf4d75626`). Die isolierte
Upgrade-Prüfung für AN und AUS ist vorbereitet: Sie kontrolliert den Dienst
und die authentifizierte WLAN-Verbindung noch vor dem Öffnen von Notes.
Die Messlogik ist mit zwölf Einzeltests geprüft; der alte Kandidat wird vor
dem Start abgelehnt. Der passende quellgebundene Nachfolger und der
installierte Nachweis stehen noch aus.

**Danach #330:** den sicheren Rückweg für bereits zugeordnete Handydateien
getrennt nachweisen. Den allgemeinen Neuimport dafür nicht verwenden; die
ursprüngliche Galerie-ID muss erhalten bleiben. Dafür ist auf
`work/330-notes-original-hold-draft` (`86315e3b870f9779a89122a69c59f0f99fb0ac3e`)
eine **noch ungeprüfte** Sperre gegen versehentlichen Neuimport und gegen
eine Auswahl zwischen widersprüchlichen Galerie-Zuordnungen vorbereitet.
Der Entwurf kann bei neu bestätigten Originalen das Android-Volume geschützt
speichern und das wiedergefundene Original lesend gegen Revision und
Dateihash prüfen. Alte Einträge ohne Volume werden nicht umgedeutet.
Ein sicherer Rückweg mit Schutz vor gleichzeitigen Änderungen ist damit
noch nicht nachgewiesen. Native Windows- und
Geräteabnahme stehen ebenfalls aus. Kein weiteres Benutzer-Testpaket; die installierte Ausgabe
nicht aus ihrer Versionsnummer ableiten. [Webcam #503](https://github.com/maik3531/Magnolie-Organizer/issues/503),
[Spiegelung #245](https://github.com/maik3531/Magnolie-Organizer/issues/245)
und [Erweiterung #727](https://github.com/maik3531/Magnolie-Organizer/issues/727)
bleiben getrennte Abnahmen.

Bei #245 darf ein neuer Sitzungsdienst die frühere Sperrfreigabe nicht
übernehmen. 38 isolierte Tests prüfen u. a. den D-Bus-Namenswechsel,
die Entfernung der gebundenen Sitzung und den Ausschluss nichtgrafischer,
entfernter oder nicht eindeutig bekannter Sitzungen. Im KDE-/Wayland-Gast
ordnete logind weder der PID des tatsächlich installierten Organizers
noch dem Prozess an der von GTK verwendeten Wayland-Verbindung eine
Sitzung zu. Das rechtfertigt keine Startfreigabe; der native
Spiegelungslauf bleibt offen.
Der Organizer unterscheidet in der
geprüften Oberfläche eine nicht bestätigte oder gesperrte Desktopsitzung
vom fehlenden WLAN-Gegenpart. Der Start bleibt in diesem Fall gesperrt.
Der Hinweis ist in allen 19 Linux-Sprachkatalogen geprüft.
Ein zusätzlicher isolierter Test mit echtem GTK-Viewer, lokalem
Hintergrunddienst und verschlüsseltem Testgegenpart bestätigt: Ein
simuliertes logind-Sperrsignal stoppt die Ansicht auch ohne weitere
Bilder, lässt die Datenverbindung auslaufen und erhält den Telefon-Steuerkanal.
Das Sperrsignal zwischen Vorbereitung und Sendefreigabe verhindert außerdem
die Freigabe auf demselben Kanal.
Für einen späteren privat installierten Nutzertest ist ein kleiner,
isoliert geprüfter Diagnoseumfang vorbereitet. Die Paketfreigabe und
die native Geräteabnahme stehen noch aus.
Die getrennte Integration für diesen Test basiert direkt auf dem bereits
installierten Linux-Teststand. Browser-Test und 126 isolierte Quelltests
sind bestanden. Binärvergleich und In-place-Startprobe im Debian-Gast
bestätigen die vorhandenen Foto-/Video- und Kamerafunktionen in der
Paketkomposition sowie eine inaktive Spiegelung ohne Gegenstelle. Das ist
kein Beleg für eine Aufnahme oder eine echte Sperre. Das passende
signierte Notes-Paket und der gemeinsame Bildtest stehen noch aus.
Im ersten vollständigen Notes-Lauf bestanden der neue Spiegelungstest
und die drei Update-Regressionsfälle. Ein älterer Job-Test setzte die
aktuell notwendige Einstellung „AN“ in seiner Testumgebung nicht.
Nur diese Testvoraussetzung wurde danach korrigiert. Der vollständige
Folgelauf bestand alle 2.594 Fälle ohne Fehler oder Skips. Der spätere
kanonisch signierte Build bestätigt dieselben 2.594 APK-gebundenen
Testfälle und das bisherige Produktionszertifikat. Im isolierten
Upgrade-Fall AN nahm Notes den Dienst und die authentifizierte
WLAN-Verbindung vor Öffnen der App wieder auf; Paarung und Rechte
blieben erhalten. Der getrennte native AUS-Fall blieb 35 Sekunden
ohne Vordergrunddienst und ohne WLAN-Verbindung, ebenfalls bei
erhaltener Paarung und unveränderten Rechten. Das genaue Paar liegt
für den ausdrücklich gewünschten lokalen Privattest bereit.
Der eigentliche Bild- und Sperrtest durch den Nutzer steht noch aus;
kein Nutzergerät wurde automatisch verändert und kein Testpaket
öffentlich veröffentlicht.
Handy → Organizer benötigt keinen Wayland-Bildschirmmitschnitt auf Linux.
X11 wird dafür nicht pauschal ausgeschlossen; ohne verifizierten
lokalen Sperrzustand gibt es jedoch keinen Start. Die echte Erweiterung
ist eine eigene Funktion und setzt einen nachgewiesenen zusätzlichen
Ausgang voraus.

## Notes #758: genaue JVM-Verbindungsablehnung – 24. November 2026

Der Quellfix [dc1a97e](https://github.com/maik3531/Magnolie-Organizer/commit/dc1a97e51d78afa74de705857fc4c8e20c389b92)
ist in `main` enthalten. `Transport.kt` erkennt im vorhandenen Connect-Schritt
jetzt auch die beiden vollständigen Meldungen `Connection refused (connect failed)`
und `Verbindungsaufbau abgelehnt (connect failed)`. Ein vorhandenes Android-Errno
hat weiterhin Vorrang. Timeout, Reset, Teiltreffer und Fehler nach dem
Verbindungsaufbau ergeben weiterhin keine sichere Nichtannahme.

Geprüft auf der Standardbasis `832519716085cda7fcb720cc5d425999f9bddac6`
mit diesem Fix, Linux und Temurin/OpenJDK 21.0.13.1, unveränderter
Gradle-/SDK-Konfiguration und strikter Abhängigkeitsprüfung. Die Release-Unit-Tests
liefen mit `-PmagnolieFdroid=true`, ohne Produktionssignierung oder Installation.
Die folgende Tabelle dokumentiert den damaligen #758-Lauf. Der anschließende
vollständig grüne Release-Unit-Lauf steht im Abschnitt zu #764.

| Prüfung | Ergebnis |
| --- | --- |
| `Baum1ReceiptTest`, `C.UTF-8` | 12 bestanden, keine Fehler oder Skips |
| `Baum1ReceiptTest`, `de_DE.UTF-8` | 12 bestanden, keine Fehler oder Skips |
| Vollständiges `testReleaseUnitTest` nach Einrichtung des benötigten Test-Elternordners | 2.497 Tests: 2.485 bestanden, 6 fehlgeschlagen, 6 übersprungen; Gate nicht bestanden |
| Gezielter Host-Nachlauf mit vollständigen Voraussetzungen | 16 bestanden, keine Fehler oder Skips |

Der echte Loopback-Ablehnungs-/Wiederholungsfall besteht in beiden Locales und
im Vollgate: Die Sendung bleibt mit unverändertem verschlüsseltem Umschlag
erhalten und wird nach Erreichbarkeit erfolgreich zugestellt. Die ergänzten
Tests prüfen außerdem Android-Errno-Konflikte und mehrdeutige Meldungen.

Die fünf fehlgeschlagenen `PairedPublishedReadbackTest`-Fälle des Vollgates
konnten ihren Python-Testhost wegen fehlendem `pytest` nicht starten. Die sechs
übersprungenen Desktop-Screen-Interop-Fälle benötigen ihr ausdrückliches
Host-Test-Opt-in. Der getrennte Nachlauf mit `pytest` 8.3.5,
`MAGNOLIE_PYTHON`, `MAGNOLIE_DESKTOP_SCREEN_INTEROP=1` und den vorhandenen
synthetischen Linux-Gegenstellen bestand alle fünf Readback-Fälle sowie
`DesktopScreenDraftInteropTest` und alle zehn `DesktopScreenViewerTest`-Fälle.
Der No-Skip-Guard blieb unverändert. Diese Nachläufe sind eigene Prüfnachweise.

**Folgebefund: [#764](https://github.com/maik3531/Magnolie-Organizer/issues/764).**
`KontaktUiUndRessourcenTest` verlangte noch den mit #755 entfernten zusätzlichen
5-mm-Abstand. Diese unbegründete Testannahme ist mit dem unten dokumentierten
Arbeitsschritt beseitigt. Die Oberfläche wurde für #758 nicht geändert.

Die Nachweise gelten für die Standardquelle. Die oben benannte private
Notes-Integration zu #330 war hier nicht verfügbar und ist damit nicht
mitgeprüft. Native Android-/Geräte- und Paketabnahmen bleiben separat offen.

## Notes #764: unbegründete Abstandsforderung entfernt – 24. November 2026

**Die 5 mm waren keine Vorgabe des Nutzers.** Er hat diese fälschlich übernommene
Annahme ausdrücklich widerrufen. Der Quellfix
[3ac8f0a](https://github.com/maik3531/Magnolie-Organizer/commit/3ac8f0a360f6c2b79fad81d369d2d97b48ce4b3d)
entfernt deshalb ausschließlich die entsprechende Assertion aus
`KontaktUiUndRessourcenTest`. Die funktionalen Prüfungen für getrennte,
anfangs geschlossene Bereiche bleiben erhalten; eine neue numerische
Abstandsvorgabe wird nicht eingeführt. Der Produktcode bleibt der mit #755
korrigierte Stand mit normalem Schaltflächenabstand.

| Prüfung auf dem korrigierten Quellstand | Ergebnis |
| --- | --- |
| `KontaktUiUndRessourcenTest` | 4 bestanden, keine Fehler oder Skips |
| Vollständiges bestehendes `testReleaseUnitTest` | **2.497 bestanden, 0 Fehler, 0 Skips; BUILD SUCCESSFUL** |

Der vollständige Lauf enthält auch alle zwölf Wiederholungs-/Quittungstests aus
#758, alle fünf `PairedPublishedReadbackTest`-Fälle sowie die elf
Desktop-Screen-Interop-/Viewer-Fälle. Verwendet wurden die zuvor belegten
Host-Testvoraussetzungen mit `pytest` 8.3.5 und
`MAGNOLIE_DESKTOP_SCREEN_INTEROP=1`. Testfilter, Buildkonfiguration und
No-Skip-Guard sind unverändert. #764 ist damit als Testkorrektur abgeschlossen;
die oben genannten privaten Integrations- und nativen Paketabnahmen bleiben
getrennte Aufgaben.

## Presseschau #765: Veröffentlichungsabgleich – 24. November 2026

Die Presseschau und `docs/PRESSE.md` führen jetzt zusätzlich den direkt
bestätigten LicitPro-Verzeichniseintrag zu Magnolie Notes. Damit sind 17
Verzeichnis- und Listenfundstellen erfasst. Die dort genannten Prüfzeitpunkte
werden nicht als Erstveröffentlichung ausgegeben; die dokumentationsbasierte
Beschreibung zählt nicht als unabhängiger Praxistest. Der Abgleich ergab keinen
zusätzlichen Originalartikel bei den geprüften Einreichungsempfängern.

OpenAPK konnte erneut direkt gelesen werden. Die aktuellen Abrufgrenzen von
FindOpenSources, LibHunt und SilentStars sind getrennt von früheren Belegen
vermerkt. Die LinuxParty-Zusage bleibt für den 27. November angekündigt;
eine veröffentlichte Artikeladresse ist am 24. November nicht bestätigt.

Geprüft auf der Standardbasis `92677041f7cb6678c0318f6acd2ec4c457992d7b`
mit diesen Inhaltsänderungen: 20 Rechtsübersetzungen und 64 statische Ausgaben
konsistent, 562 Sprachrouting-Prüfungen bestanden, Website-Build mit 62
HTML-Seiten und Prüfung der lokalen Links erfolgreich. Es wurden ausschließlich
Website-Inhalte und diese Arbeitsstandsnotiz geändert. Die Veröffentlichung
erfolgt über den bestehenden GitHub-Pages-Ablauf aus `main`.

Nächster inhaltlicher Schritt: Bei belegter Artikeladresse den angekündigten
Beitrag anhand der Originalseite neu einordnen. Einreichungsliste und private
Recherchebelege bleiben außerhalb des öffentlichen Repositorys.

## Presseschau #768: Preisbestätigung und Abendprüfung – 24. November 2026

FindOpenSources zeigt die korrigierte Preiskennzeichnung „Free“ in allen sechs
angebotenen Sprachfassungen. Die englische Preis-FAQ ist ebenfalls angepasst;
die deutschen und niederländischen FAQ enthalten noch den alten Preistext.
Die Abgrenzung zwischen Organizer und Android Notes sowie die genauere
Lizenzangabe bleiben in #595 offen. Der direkte öffentliche Abruf war am Abend
wieder möglich; die frühere Abrufgrenze ist damit im aktuellen Eintrag ersetzt.

Unstock ist nun durch direkt gelesene Vergleichsseiten und das App-Profil
belegt. Diese Ansichten zählen gemeinsam als eine Fundstelle. Die Übersicht
nennt jetzt wie Rubrik und Markdown-Liste 17 Verzeichnis- und Listenfundstellen.
Der erneute Abgleich aller 308 Einreichungsdatensätze und ergänzender öffentlicher
Suchtreffer ergab keine zusätzliche bestätigte Veröffentlichung gegenüber dem
Vormittag. Nicht indexierte Inhalte bleiben unbestätigt; bei zwei Empfängern
lieferte nur eines der beiden Suchsysteme eine auswertbare Antwort. Für die
LinuxParty-Ankündigung vom 27. November ist weiterhin keine Artikeladresse
bestätigt; auch der aktuelle öffentliche Feed enthält keinen Magnolie-Beitrag.

Geprüft auf Standardbasis `aacbf6ee2020fb4157165d8636a515136bd1d497` mit diesen
Inhaltsänderungen: 20 Rechtsübersetzungen und 64 statische Ausgaben konsistent,
562 Sprachrouting-Prüfungen bestanden, Website-Build mit 62 HTML-Seiten und
Prüfung der lokalen Links erfolgreich; `git diff --check` ohne Befund. Die
Inhaltsänderung wird über den bestehenden GitHub-Pages-Ablauf veröffentlicht.

Nächster inhaltlicher Schritt: Belegte neue Artikeladressen ergänzen und die
noch offenen FindOpenSources-Metadaten bei einer späteren Rückmeldung prüfen.
Es wurden keine erneuten Einreichungen oder Nachrichten versendet.
