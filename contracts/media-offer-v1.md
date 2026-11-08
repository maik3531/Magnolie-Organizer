# Medienangebot mit ursprünglicher Telefonreferenz (Refs #429)

`file_transfer.media_offer` ergänzt ausschließlich die Metadaten für ein
Desktop→Telefon-Medienangebot. Der gewöhnliche `file_transfer.offer` bleibt
unverändert und nimmt diesen neuen Nachrichtentyp nicht als gewöhnliche Datei an.
Der sichere, authentifizierte Umschlag bleibt gleich; maximal 262144 kanonische
UTF-8-Bytes und höchstens 60000 ms Gültigkeit, beim Empfang noch nicht abgelaufen.

Der Körper enthält exakt:

- `format: 1`
- `offer`: den vollständigen unveränderten Körper eines gewöhnlichen Angebots
- `settings`: den vollständigen aktuellen Acht-Felder-Mediensnapshot
- `media_type`: `images` oder `video`
- `mime_types`: genau eine passende Bild-/Video-MIME-Angabe pro Manifest-Datei-ID
- `originals`: ursprüngliche Telefonreferenzen, jeweils unter der neuen Datei-ID

Eine Referenz enthält exakt `source_epoch`, `photo_id`, `media_type`,
`manifest_sha256`, `file_id`, `original_size`, `original_sha256`, `receipt_sha256`.
Fremde IDs, doppelte Referenzen, falsche Typen und unvollständige Einstellungen
werden abgewiesen. Im Handybestandsumfang braucht jedes Mitglied eine Referenz;
der gesamte Bestand erlaubt auch neue Mitglieder ohne erfundene Telefonherkunft.
Reiner Import und eine reine Telefon→PC-Richtung erlauben kein solches Angebot.

Die Rekonstruktion des gewöhnlichen Angebots erhält Nachrichten-ID, Zeitgrenzen
und Manifest unverändert. Damit bleiben die vorhandenen Annahme-/Chunk-/Saved-
Bindungen erhalten. Die Metadaten erteilen keine Rechte und beweisen weder
Dateiinhalte noch ursprüngliche Telefonzuordnungen. Der native Empfang muss
den Snapshot gegen den tatsächlich bestätigten aktuellen Absichtsbesitzer
prüfen, dessen Identität bis zur Workeraufnahme erhalten und alle bestehenden
Buch-, Empfangs-, Originalreferenz-, Inhalts- und Veröffentlichungsprüfungen
unverändert durchführen.

Python, C# und Kotlin prüfen denselben kanonischen Testvektor in
`media-offer-v1-vectors.json`. Der explizite Android-Laufzeitanschluss ist mit
wirklich verschlüsselter Eingabe, nativer PNG-Veröffentlichung und Saved geprüft;
fehlende aktuelle Absicht, Inventarreferenz oder native Empfangszustimmung
bewirken keine Provideränderung. Das ist noch keine Freigabe des normalen
Produktionsdispatchers oder der gemeinsamen Betriebsbereitschaft. Die Ableitung
der MIME-Angaben ist beim expliziten Windows-Sender inzwischen an die tatsächlich
authentifizierten verschlüsselten Cachebytes gebunden: höchstens 1 MiB Präfix,
PNG/JPEG beziehungsweise MP4/QuickTime-Containererkennung, nie Dateiendungen.
Unbekanntes wird vor jedem Angebot und vor dem Anlegen des Versandjournals
abgewiesen; Cache, Original und alte Empfangshistorie bleiben erhalten.
Das ist eine Containeridentifikation, keine vollständige Inhalts-/Pixelprüfung:
diese bleibt beim nativen Empfänger vor der Veröffentlichung erforderlich.

Der Windows-Sender sendet den neuen Umschlag mit exakt geschütztem aktuellem
Acht-Felder-Snapshot und Originalreferenzen. Seine vorhandenen Annahme-, Chunk-,
Saved-, Ablauf-, Abbruch- und Journalbindungen verwenden weiterhin dieselbe
Angebots-ID und dasselbe Manifest. Fünf native Windows-Versandgruppen prüfen
diesen Weg, darunter eine echte umbenannte PNG mit zwei verschlüsselten Chunks
und unbekannter Inhalt trotz `.jpg`-Name ohne Ausgabe. Das ist noch kein
Produktionsdispatcher-/Android-Ende-zu-Ende-Nachweis. Android reserviert den
Umschlag inzwischen im normalen authentifizierten Nachrichtenverteiler und
übergibt ihn ausschließlich an die bereits vorhandene identische native
Verbindung. Chunkantworten erreichen direkt den auf sie wartenden nativen
Empfangsworker, ohne hinter dessen Warteoperation eingereiht zu werden. Ein
Angebot kann weder eine Verbindung noch eine aktuelle Medienabsicht oder
Empfangszustimmung herstellen. Der gewöhnliche source-only/Legacy-Zweig bleibt
empfangsgeschlossen. Der gemeinsame Factory-Zweig verbindet ab Android 30 die
bereits vorhandenen nativen Empfangshandler ausschließlich mit einem tatsächlich
aktuellen gemeinsam bestätigten eingehenden Absichtsbesitzer. Seine gespeicherte
Empfangszustimmung bleibt unabhängig und zunächst geschlossen; erst der echte
lokale positive native Dialog kann sie ändern. Native Verbindungsweiterleitung mit echter PNG-
Veröffentlichung/Saved sowie Ablehnung fremder Verbindung, normaler Dateiangebote
und fehlender Empfängerfactory sind geprüft; im echten Werk-Verteiler sind
reservierte Ablehnung ohne Bootstrap und vorhandene Kontrollaktivierung geprüft.
Ein zusätzlicher Test prüft inzwischen auch die tatsächliche Werk-Factory,
gemeinsame Absichtsabstimmung, native Kontrollabstimmung, positiven nativen
Zustimmungsdialog und den normalen Werk-Verteiler bis zur PNG-Veröffentlichung
und verschlüsselten Saved-Ausgabe. Nur dieser Test stellt die ansonsten gesperrte
gemeinsame Capability bereit. Dies ist kein physischer Telefon-/Desktop-
Ende-zu-Ende-Nachweis und keine Produktfreigabe dieser Capability.

## Ausdrückliche lokale Empfangszustimmung in Notes

Die Medien-Einstellungsseite besitzt inzwischen getrennte Foto-/Video-Aktionen
„Galerie-Empfang erlauben…“. Sie verändern weder die gemeinsamen Einstellungen
noch Android-Leserechte und starten keine Synchronisierung. Die Oberfläche
berücksichtigt die gemeinsam bestätigte Bereitschaft, den gewählten Medientyp,
Richtung/Umfang, Android ≥30 und belegte Medienläufe. Im reinen Importumfang und
bei Telefon→PC sind diese Empfangsaktionen gesperrt.

Der produktive Werk-Aufruf nimmt nur die bereits bestehende native Verbindung,
deren aktuellen Peer-Namen und das tatsächlich gespeicherte, entsperrte Buch.
Er erzeugt keine Verbindung und liest keinen Konfigurationsbesitzer aus
Oberflächen- oder Nachrichtendaten. Eine eigene native Aktion bereitet außerhalb
des UI-Threads den bestehenden Empfangs-Konfigurationsticketbesitzer und einen
geschützten Richtliniensnapshot vor. Erst der echte positive lokale Dialog darf
die einmalige Auswahl erzeugen. Anschließend werden die aktuelle gemeinsame
Kontroll-/Einstellungsabstimmung und derselbe typspezifische Absichtsbesitzer
erneut geprüft, bevor die vorhandene native CAS-/Rückleseprüfung speichern darf.
Diese frische Einstellungsprüfung geschieht ebenfalls außerhalb des UI-Threads
und außerhalb geschützter Indexsperren; deren Absichtsprojektionen bleiben
absichtlich sperrfrei.

Abbrechen beziehungsweise Coroutine-Abbruch schließen den Dialog, widerrufen die
Auswahl und geben ausschließlich das eigene Konfigurationsticket frei. Die Aktion
legt keine Galeriezeile an, stellt keine Datei wieder her und erzeugt weder
Archiv- noch Papierkorbrechte. Die vorhandenen Buch-/Foreground-/Configurer-
Prüfungen gelten weiter. Der gemeinsame Produktweg bleibt wegen der noch nicht
abgeschlossenen Gesamtkomposition weiterhin geschlossen; dieser Bedienungsweg
ist insbesondere keine Freischaltung der Capability 23.

Der tatsächliche Werk-Factory-/Verteilertest verwendet nun diesen produktiven
UI-Eintritt statt einer im Test manuell erzeugten Konfiguration. Er prüft
Dialog-Abbruch, Coroutine-Abbruch, verspätete positive Rückrufe alter Dialoge,
Entzug der gemeinsamen Bereitschaft während des Dialogs ohne Richtlinien- oder
Provideränderung und anschließend eine neue echte positive Aktion bis zur PNG-
Veröffentlichung/Saved. Die zusätzliche Entzugsprobe fand zunächst eine echte
Lücke der neuen UI-Aufnahme: eine sperrfrei zwischengespeicherte Absicht alleine
war kein frischer Bereitschaftsnachweis. Der produktive Werk-Eintritt prüft
deshalb die tatsächliche Kontroll-/Einstellungsabstimmung zusätzlich vor der
Speicherung; die erneute Probe besteht. Vorhandene native Zustimmungs-/Buch-/
Lifecycle-Prüfungen und vier Compose-Einstellungsfälle bestehen ebenfalls.
Das neue Aktionslabel ist in allen 20 Notes-Ressourcenkatalogen vorhanden.

## Windows: Publication-Readback-Metadaten

Windows besitzt nun denselben strikten `file_transfer.published.readback`-Codec
wie Python und Notes. Der gemeinsame öffentliche Vektor prüft die drei
domänengetrennten Hashes. Weitere Prüfungen ändern Angebots-/Manifest-/Datei-
Kennungen, Größe, Inhaltshash und Medientyp mit vollständig neu berechneten
Hashes: die Bindung an das ursprüngliche Angebot muss trotzdem scheitern.
Foto- und Video-Metadaten werden getrennt geprüft. Das Ergebnis ist eine
unveränderliche Kopie von Peer-Metadaten, keine lokale Saved-Quittung,
Chunk-Freigabe, tatsächlicher Source-END oder Cache-Löschberechtigung.

Der zusätzliche ausdrückliche Windows-Sendeeintritt
`SendNativeMappedMediaSourceWithReadbackAsync` wartet nach Peer-Saved auf den
Readback desselben Angebots und derselben aktuellen nativen Bindung. Er vergleicht
den Publikationsfingerabdruck mit dem zuvor empfangenen Saved-Mitglied und den
MIME-Typ mit dem aus tatsächlichen Quellbytes erkannten Angebot. Ein gültig neu
gehashtes, aber sachlich falsches Readback ist deshalb weiterhin unzulässig.
Der geschützte Austauschverlauf hält Peer-Saved und Peer-Readback getrennt fest.
Der bisherige Saved-only-Eintritt behält seinen bisherigen Rückgabevertrag.

Fünf native Windows-Proben prüfen den korrekten Ablauf, falsche Publikation,
falschen MIME-Typ, Readback vor Saved und Abbruch während des Wartens. Der
ursprüngliche Quellcache und die Empfangshistorie bleiben dabei erhalten.
Auch nach dem tatsächlichen Ende ausstehender verschlüsselter Schreibarbeit sind
beide Ergebnisse nur Peer-Metadaten: die ursprünglichen lokalen Dateihandles
besitzt weiterhin der Quellbesitzer. Dessen tatsächlicher Source-END und eine
eventuelle spätere Cache-Freigabe sind damit noch nicht nachgewiesen.

Notes bindet zusätzlich eine einmalige native Readback-Fortsetzung direkt an den
eigenen Empfangslauf. Sie übernimmt ausschließlich dessen ursprüngliches Angebot,
Buch, Kanal, typspezifische Absicht und tatsächlich veröffentlichte Datei.
Erst nach erfolgreicher Saved-Ausgabe, geschlossenen Transferressourcen und dem
tatsächlichen Ende des Empfangsarbeiters kann diese Fortsetzung benutzt werden.
Ein Caller kann keine Ersatzpublikation und kein anderes Buch übergeben.
Die ursprüngliche Kontrollbindung wird vor dem Start und erneut im Hintergrund
geprüft; die vorhandene vollständige Original-Rücklese-/Medienprüfung erzeugt
anschließend den Readback. Aus einem gespeicherten Saved-JSON allein lässt sich
diese Fortsetzung nicht erzeugen.

38 Notes-Empfangs-/Transferfälle bestehen, darunter der neue Originalangebot-
Readback, einmalige Nutzung, laufender/abgebrochener/metadatenbasierter Empfang,
entzogenes Originalbuch und widerrufene Kontrollen. Die fünf bestehenden nativen
Windows-Sendegruppen bestehen nach der Änderung ebenfalls. Beide optionalen
Windows-Produktkompositionen (Foto-/Kameramodule ein beziehungsweise aus) bauen.
Dies ist kein gemeinsamer physischer Telefon-/Windows-Ende-zu-Ende-Nachweis.

Der normale Notes-Nachrichtenverteiler startet diese Fortsetzung inzwischen
automatisch nach erfolgreichem eigenem Medienempfang. Er verwendet dafür denselben
Empfangsarbeiter nach dessen tatsächlichem Transfer-/Ressourcenende, keinen
zusätzlichen Wartethread und keinen blockierten Nachrichtenempfänger. Die native
Startoperation darf dafür auf diesem Arbeiter höchstens eine Sekunde beziehungsweise
bis zum Angebotsablauf warten; danach werden alle ursprünglichen Besitzer erneut
geprüft. Der produktive Anschluss prüft die tatsächliche gemeinsame Abstimmung
frisch außerhalb des UI-Threads und geschützter Indexsperren. Schlägt dies fehl,
bleibt die bereits veröffentlichte Datei unverändert erhalten; es wird kein
Readback-Erfolg erfunden.

Abbruch des ursprünglichen Laufs erreicht auch den automatisch gestarteten
Readback. Der bestehende Lese-/Ausgabebesitzer bleibt dabei bis zum tatsächlichen
I/O-Ende gehalten. Die öffentliche native Drain-Wartesperre wird wie bisher erst
nach dem Aufräum-Rückruf freigegeben. 41 betroffene Notes-Fälle bestehen,
einschließlich des produktiven Factory-/Dialog-/Verteilerwegs bis zum automatisch
gesendeten Readback, entzogener Abstimmung nach Saved und Abbruch bei blockierter
verschlüsselter Readback-Ausgabe. Private explizite Runtime-Aufrufe behalten ihre
gesonderte einmalige Fortsetzung.

Die vollständige gemeinsame Ablaufsteuerung beider Desktops und aller
Synchronisierungsrichtungen bleibt offen; Capability 23 bleibt geschlossen.

## Windows: tatsächlicher lokaler Source-END

Der gesonderte native Sendeeintritt
`SendNativeMappedMediaSourceToSourceEndAsync` führt nach demselben korrelierten
Saved-/Readback-Ablauf zusätzlich den lokalen Quellabschluss aus. Erst nachdem
ausstehende verschlüsselte Ausgabe tatsächlich beendet und der Sendeplatz
freigegeben ist, wird der ursprüngliche Quellbesitzer geschlossen. Dabei wird
auf laufende Cache-Leser gewartet; anschließend werden die tatsächlich gehaltenen
Datei-/Album-/Wurzelhandles geschlossen. Ein Fehler beim nativen Schließen darf
keinen erfolgreichen Endzustand setzen.

Der geschützte Austauschverlauf erhält erst danach `source_ended` mit dem
ursprünglichen Cache-Kopf, dessen Nonce und dem exakten Readback-Hash. Dieser
private terminale Schreibweg prüft den tatsächlich beendeten lokalen Besitzer
sowie unveränderte geschützte Quell- und Austauschköpfe. Er verwendet nicht die
bereits entzogene Leseberechtigung des alten Quellbesitzers neu. Spätere
Quell-/Chunk-Leseversuche sind gesperrt; der geschützte Cache und vorhandene
Historien werden trotzdem nicht gelöscht oder ersetzt.

Vier native Windows-Gruppen prüfen erfolgreichen Abschluss, falsche Publikation,
Readback vor Saved und Abbruch. Nur im Erfolgsfall sind die ursprünglichen
Handles tatsächlich unbenutzbar und der terminale Verlauf gespeichert. Vier
weitere native Regressionen prüfen wartende Cache-/Quellleser, abgebrochene
verschlüsselte Ausgabe und den weiterhin nichtterminalen Readback-only-Weg.
Beide optionalen Produktkompositionen bauen. Das ist noch keine automatische
gemeinsame Ablaufsteuerung, Cache-Löschberechtigung oder physische gemeinsame
Telefon-/Windows-Abnahme.

## Windows: nachfolgende Quellversion ohne Verlust des Vorgängers

`FreezeCompletedSuccessor` bereitet mit dem neuen aktuellen nativen Quellbesitzer
eine weitere Version derselben ursprünglichen Telefonzuordnung vor. Der normale
`Freeze`-Weg behält seine bisherige Sperre gegen doppelte Vorbereitung. Der neue
Weg übernimmt keinen alten Cache und erzeugt keine Lese-/Schreibberechtigung aus
dessen Metadaten: gespeichertes Originalbuch, aktuelle gemeinsame Absicht,
positive native SEND-Bindung und tatsächlich gehaltene aktuelle Datei bleiben
für den neuen Besitzer unabhängig erforderlich.

Vor einer neuen Version müssen die zugehörigen Vorgänger als eine eindeutige
geschützte Kette mit tatsächlichem lokalem Source-END vorliegen. Die Prüfung
bindet Cache-Kopf, Nonce, Austauschkopf, korrelierten Readback und jede erhaltene
verschlüsselte Cache-Datei aneinander. Fehlende, unvollständige, beschädigte oder
verzweigte Vorgänger bleiben gesperrt. Vor dem abschließenden Ready-Schreiben
wird der erhaltene Vorgänger einschließlich seiner Cache-Dateien erneut geprüft,
damit eine Änderung während der neuen Kopie nicht verdeckt wird. Die neue Vorbereitung
erhält eine eigene Identität und einen geschützten `previous`-Verweis auf den exakten
letzten Vorgänger; dessen Kopf und sämtliche Cache-Bytes bleiben
unverändert. Die vorhandenen Speicher-/Historiengrenzen gelten weiter.

Identische Bytes gegenüber der letzten abgeschlossenen Version erzeugen keine
neue Vorbereitung. Ein bewusster späterer Wechsel zurück zu älteren Bytes ist
hingegen eine neue Änderung gegenüber dem letzten Stand und wird nicht durch
eine beliebige alte Historie unterdrückt. Dies ist eine Vorbereitungs-/
Versionsentscheidung, keine automatische Cache-Löschung oder Übernahme alter
Dateirechte.

Sieben native Windows-Gruppen prüfen neue Version, unveränderte Bytes,
unvollständigen Vorgänger, beschädigten Vorgängercache, noch gar nicht gesendete
Vorbereitung und die Kette erste Version → zweite Version → ältere Bytes als
dritte Version sowie beschädigte Vorgängerbytes während einer bereits laufenden
neuen Kopie. Im letzten Fall bleibt die neue Vorbereitung als unvollständig
erhalten, statt fälschlich Ready zu werden oder alte Daten zu reparieren/löschen.
Die vier bisherigen Cache-/Korruptions-/Buch-/Drain-Gruppen
bestehen ebenfalls; Capability 23 bleibt geschlossen.

## Windows: Auswahl zugeordneter PC-Änderungen im normalen Lauf

Die lokale Sendezustimmung wird unabhängig von Empfangszustimmung, Medienauswahl
und gemeinsamer Richtung geschützt gespeichert, getrennt für Fotos und Videos.
Ohne eigene ausdrückliche Wahl bleiben beide aus; auch frühere native
Empfangseinstellungen erzeugen keine Sendezustimmung. Der Datensatz ist an beide
Identitäten und die Kopplung gebunden. Veraltete Fenster dürfen ihn nicht ersetzen;
ein Entzug mit erneuter Zustimmung erzeugt eine neue Version.

Der tatsächliche zugeordnete Quellzugriff verlangt diese Zustimmung zusätzlich
zur positiven SEND-Steuerbindung und hält deren genaue Version während eigener
Datei- und Cache-Zugriffe fest. Entzug oder Aus-/Einschalten sperrt den alten
Besitzer, ohne Dateien, Cache oder Historien zu löschen. Die Tests erteilen diese
lokale Zustimmung jetzt ausdrücklich; sie wird nicht aus ihren Steuergrants
abgeleitet. Native Prüfungen belegen Standard-Aus, unabhängige Foto-/Videowahl,
geschützte Persistenz, Kopplungswechsel, beschädigten Chiffretext und Entzug beim
echten Quell-/Cachezugriff. Manueller und WLAN-Export bestehen mit der zusätzlichen
Prüfung weiterhin. Die Oberfläche bietet nun getrennte lokale Foto-/Video-
Sendezustimmungen. Eine positive Erweiterung erfordert den nativen standardmäßig
ablehnenden Bestätigungsdialog; die Browsernachricht kann keine Bestätigung oder
Steuergrants mitgeben. Buch, ursprüngliche Verbindung und genaue Zustimmungsversion
werden nach der nativen Antwort erneut geprüft. Abbruch schreibt nichts; Entzug
erfordert keine positive Bestätigung. Der Dialogweg ist über die native
Entscheidungsfunktion mit Zustimmung, Abbruch, tatsächlicher Buchsperre,
Verbindungswechsel und konkurrierender Änderung sowie die vollständige Browser-
Oberflächenprüfung belegt. Eine tatsächliche installierte GUI-Klickabnahme ist
damit nicht behauptet.

Die produktive `NativeMediaUiAuthority` projiziert diese Zustimmung inzwischen
in derselben vorhandenen Steuersitzung. Sie hält ihren Besitzer stabil und
erhöht bei Änderungen beziehungsweise Entzug die Berechtigungsrevision. Die
laufende Steuersitzung liest dabei weiterhin nicht unter ihrer Sperre aus dem
geschützten Store. Ein normaler ausgehender Lauf verlangt seine genaue lokale
Zustimmung, das gespeicherte Buch, die abgestimmte Richtung und anschließend
die tatsächliche positive Gegenstellenbestätigung; vorher gibt es kein
Medienangebot und keine vorbereitete Quellkopie. SEND funktioniert dabei ohne
RECEIVE. Die lokale Auswahlprojektion berücksichtigt beide unabhängigen Rechte
und die jeweilige tatsächliche Richtung, statt ausgehende Läufe durch eine
fehlende Empfangszustimmung zu deaktivieren. Entzug und Verbindungsschluss
während der Gegenstellenabstimmung beenden den Lauf ohne Daten-/Cacheverlust.
Native Prüfungen führen diesen normalen UI-eigenen Weg ohne vorgegebenen
SEND-Testgrant bis zum Source-END aus und prüfen beide Abbrüche. Vorhandene
manuelle/WLAN-Exporte und Import-/Videoabläufe bestehen ebenfalls; die
Importprobe beantwortet nun auch den nach einer Zustimmungsprojektion erneuerten
tatsächlichen Steuer-ACK. Dies ist keine Freischaltung von Capability 23.

Der gemeinsame manuelle und WLAN-Automatiklauf enthält jetzt einen
Desktop→Telefon-Schritt für bereits zugeordnete Medien. Seine Kandidaten kommen
ausschließlich aus geschützten, abgeschlossenen lokalen Saved-/END-Zuordnungen
des aktuellen Zieles. Er scannt keine beliebigen Dateipfade. Ersetzte Vorgänger
und mehrdeutige Zuordnungen werden nicht als neue Quellrechte übernommen; jeder
tatsächliche Zugriff öffnet die ursprüngliche Datei mit den bestehenden nativen
Buch-/Bindungs-/Identitätsprüfungen neu.

Unveränderte ursprüngliche Dateien ohne ausgehende Versionshistorie benötigen
keinen Quellcache. Bei vorhandener Historie entscheidet dagegen nur der letzte
vollständig abgeschlossene Stand über unveränderte Bytes; spätere Änderungen
erhalten eine neue erhaltene Quellversion. Unbekannte tatsächliche Medienbytes
werden vor einer persistenten Vorbereitung abgewiesen. „Nur Fotos“ verwendet die
vorhandene native Metadatenprüfung und überspringt nicht passende Dateien vor
der Vorbereitung, statt Dateiendung/MIME allein zu vertrauen.

Die unabhängige Richtung wird vor beiden Teilabläufen geprüft. PC→Telefon fällt
nicht in Telefon-Discovery/READ/Import durch; reiner Import erlaubt keine
PC-Ausgabe. Für den Umfang „gesamte Sammlung“ fehlen weiterhin die bisher nicht
zugeordneten reinen PC-Dateien: der Lauf meldet dafür Review statt vollständigen
Erfolg zu behaupten. Fehler oder unvollständige frühere Versionen bleiben Hold,
ohne automatische Wiederaufnahme, Löschung oder Ersetzung geschützter Daten.

Native Windows-Prüfungen umfassen den normalen manuellen Lauf über zwei echte
Quellversionen, einen tatsächlichen WLAN-Automatiklauf, jeweils einen
unveränderten Folgelauf ohne erneute Ausgabe/Vorbereitung, PC-only ohne
Telefon-Import, Import-only und unbekannte Bytes vor Ausgabe sowie den nativen
Foto-Metadatenfilter vor Vorbereitung. Drei betroffene bisherige Import-/Video-
Regressionsgruppen bestehen ebenfalls. Beide optionalen Produktkompositionen
bauen. Linux-Parität, vollständige Sammlungs-/Lösch-/Wiederherstellungswege und
gemeinsame physische Ende-zu-Ende-Abnahme bleiben offen; Capability 23 bleibt
geschlossen.

## Linux: expliziter nativer Medien-Quellsender

Der vorhandene private Linux-Quellsender besitzt zusätzlich zu seinem unveränderten
gewöhnlichen Dateiangebot einen ausdrücklichen `send_media_offer`-Weg. Er liest
ausschließlich den authentifizierten vorbereiteten Cache unter dessen echter
Buch-/I/O-/Zustimmungslease. Der Medien-Snapshot muss zum geschützten ursprünglichen
Absichtshash der Vorbereitung passen. Der MIME-Typ kommt aus höchstens 1 MiB
tatsächlicher Cache-Bytes nach denselben begrenzten PNG-/JPEG-/MP4-/QuickTime-
Containerregeln wie unter Windows, nicht aus dem Dateinamen. Die vollständige
native Medienprüfung auf Notes bleibt davon unabhängig.

Ein eigener geschützter Austauschformatstand hält bei diesem neuen Weg Saved und
den danach korrelierten Publication-Readback getrennt fest. Angebotsidentität,
Manifest, ursprüngliche native Bindung, tatsächliche Chunk-Ausgabe, Saved-
Publikationsfingerabdruck und bytebasiert erkannter MIME-Typ bleiben erforderlich.
Gültig neu gehashte, aber sachlich falsche Rückmeldungen, falscher Kanal, Ablauf,
zu früher Readback und doppelte Rückmeldung werden abgewiesen. Die Beobachtung
bleibt Metadaten ohne native Saved-/Lese-/Archivierungsberechtigung.

18 neue Fälle einschließlich tatsächlicher verschlüsselter Zwei-Chunk-Ausgabe,
Saved-/Readback-Korrelation und begrenzter MIME-Erkennung bestehen. Alle 17
bisherigen Senderfälle, sieben Cache-Leserfälle, fünf gezielte bestehende Retry-/
Archivfälle und 20 optionale Kompositionsfälle bestehen in begrenzten separaten
Läufen. Ein zunächst zu großer Gesamtlauf erreichte sein Zeitlimit; daraus wurde
kein Prüferfolg abgeleitet. Die kleinere MIME-Hilfe wird nur mit der optionalen
Medienkomposition ausgeliefert.

Dieser Weg ist weiterhin eine explizite private Linux-Komposition, noch kein
normaler Desktop-Verteiler oder automatischer Exportlauf. Neue Medienangebote
werden nicht in die bisherigen gewöhnlichen Retry-Nachweise umgedeutet.

## Linux: Medienabschluss an der verlustfreien nativen Archivstrecke

Ein eigener Medien-Abschlussprüfer verbindet den neuen Saved-/Readback-Verlauf
inzwischen mit dem vorhandenen nativen Archivbesitzer. Ein Medien-Saved allein
reicht hierfür nicht: ursprüngliches Medienangebot, tatsächliche vollständige
Chunk-Ausgabe, exakte Annahme/Saved/Publikation/MIME und Readback-Bindung bleiben
erforderlich. Die bisherigen gewöhnlichen Datei-/Retry-Prüfer werden dafür nicht
abgeschwächt.

Zusätzlich muss die unabhängig vorhandene lokale Quellversionssicherung exakt
zum vorbereiteten Cache passen und tatsächlich erneut geprüft werden. Die
vorhandene native Übergabe hält Buch und I/O-Sperre bis zum Ende, schließt die
eigenen Cache-Deskriptoren und verschiebt das vollständige private Cache-Verzeichnis
ohne Ersetzen in sein erhaltenes Archiv. Erst nach tatsächlicher Bewegung,
Synchronisation und erneuter Prüfung darf der geschützte Verlauf `archived`
festhalten. Es werden weder Cache-Bytes noch Vorgänger gelöscht. Der alte
vorbereitete Besitzer wird beendet; eine neue ausdrücklich ausgewählte Version
braucht einen neuen echten Besitzer. Historische Beobachtungen erteilen weiterhin
keine Lese-, Lösch- oder wiederverwendbare Slotberechtigung.

Fünf zusätzliche native Linux-Fälle prüfen erhaltene Dateiidentitäten und Bytes,
Wiederherstellung der gesicherten alten Version, neue ausdrückliche Vorbereitung,
Saved ohne Readback, kopierte Abschlussmetadaten, veraltete Sicherung und eine
noch blockierte echte Leserfreigabe trotz bereits gespeichertem Readback. Sechs
gezielte bisherige Archiv-/Retry-/Abbruchregressionen bestehen ebenfalls.
Normaler Linux-Verteiler, lokale produktive SEND-Zustimmung, automatische
Exportauswahl und vollständige gemeinsame Abnahme bleiben offen; Capability 23
bleibt geschlossen.

Die gemeinsame native Zusammensetzung und vollständigen Abschluss-/
Wiederaufnahmewege bleiben offen; Remote-Saved ist kein lokales Saved/END und
keine Berechtigung, den Ausgangscache zu entfernen.
