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

## Linux: begrenzte Kandidatenliste aus geschützten Zuordnungen

Die lokale Exportauswahl kann nun ausschließlich die neuesten geschützten
Zuordnungen seitenweise lesen. Der genaue Eigentümer-Snapshot bleibt über die
Seiten gebunden. Sämtliche ursprünglichen Datensätze, Versionsköpfe und
Vorgängerketten werden vor der Auswahl authentifiziert; nicht zugeordnete oder
beschädigte Metadatensätze dürfen nicht durch einen Foto-/Videofilter verschwinden.
Es werden keine Mediendateien geöffnet, geprüft, gesucht oder neu erzeugt.

Die Liste ist nur historische Kandidatenmetadaten, keine Lese-, Schreib-,
Lösch- oder Neustartberechtigung. Eine inzwischen fehlende Datei bleibt fehlend;
der spätere tatsächliche Quellbesitzer muss sie mit Buch, Zustimmung und
ursprünglicher Identität unabhängig öffnen. Zehn native Fälle prüfen begrenzte
Seiten, Snapshot-Wechsel, Versionsköpfe, alle bestehenden Schutzdomänen,
verwaiste Metadaten auch im jeweils anderen Medienfilter und fehlende Ziele
ohne Wiederherstellung. Die normale Exportplanung und sichere Entscheidung
gegenüber der letzten abgeschlossenen Quellversion bleiben noch offen.

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

Der eigenständige Senderaufruf bleibt eine explizite private Linux-Komposition;
die zusätzliche normale Factory-Anbindung ist unten beschrieben. Neue Medienangebote
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
Lokale produktive Linux-SEND-Zustimmung, automatische Exportauswahl und
vollständige gemeinsame Abnahme bleiben offen; Capability 23
bleibt geschlossen.

## Linux: native Quell-Factory und gemeinsame Steuersitzung

### Geschützte Reihenfolge neuer Quellversionen

Neue native Cache-Aufträge binden zusätzlich den exakten abgeschlossenen
Vorgänger: dessen geschützte Ready-Version und dessen Archivabschluss. Die
vollständige Vorgängerkette wird vor einem weiteren Auftrag authentifiziert.
Fehlende oder veränderte Vorgänger, mehrere Wurzeln, Verzweigungen und nicht
erreichbare Einträge sperren die Fortsetzung. Ein noch laufender Auftrag kann
nicht als abgeschlossener Vorgänger verwendet werden. Die bestehende Prüfung
der tatsächlichen Archivdateien vor Nutzung des freien Quellplatzes bleibt
zusätzlich erforderlich.

Bestehende Aufträge ohne diese Reihenfolge bleiben unverändert als vollständig
authentifizierter, aber ungeordneter Altbestand erhalten. Neue Ketten binden
diesen Bestand über einen gemeinsamen Digest; sie erfinden keinen neuesten
Alteintrag. UUIDs, SQLite-Zeilenfolge und sortierte Katalogmitgliedschaften
begründen keine zeitliche Reihenfolge. Die Projektion sind ausschließlich
historische Metadaten, keine Lese-, Wiederaufnahme- oder Löschrechte. Die
automatische Exportplanung wird durch die Reihenfolge allein noch nicht
eingeschaltet.

### Native Vergleichsentscheidung für zugeordnete PC-Dateien

Der Quellbesitzer und die bestehende native Verbindung können nun eine einzelne
geschützte Zuordnung prüfen, ohne einen Cache oder Transfer anzulegen. Dabei
bleiben die tatsächliche Sendezustimmung, die gemeinsame Richtungsvereinbarung,
das gespeicherte Buch, die aktuelle Zuordnung, die originalen Dateideskriptoren
und die exklusive Medien-I/O-Lane während des gesamten Vergleichs gebunden.
Vor der Entscheidung werden sämtliche vorhandenen Quellabschlüsse und die
tatsächlichen Archivbelege unabhängig geprüft. Laufende oder beschädigte
Quellaufträge sperren den Vergleich; fehlende Mediendateien bleiben fehlend.

Verglichen wird ausschließlich mit der letzten passenden abgeschlossenen
Medienversion in der geschützten Reihenfolge. Ohne frühere Quellversion gilt die
ursprünglich empfangene Zuordnung als Ausgangsstand. Ein Treffer in irgendeiner
älteren Version oder in der ursprünglichen Empfangsversion darf einen Rückwechsel
zu älteren Bytes nicht als unverändert verbergen. Ungeordnete Altversionen sowie
generische Datei-Saved-Abschlüsse ohne normale Medien-Readback-Semantik dürfen
keine Unverändert-Entscheidung begründen. Die Entscheidung ist weiterhin nur
Metadaten: kein Lese-, Cache-, Wiederaufnahme- oder Löschrecht. Seitenweise
Auswahl und automatische Ausgangsplanung sind noch nicht angeschlossen.

Die native Verbindung besitzt zusätzlich eine ausdrückliche bedingte
Vorbereitung: Erst nach der tatsächlichen SEND-/RECEIVE-Steuervereinbarung wird
geprüft; bei unveränderten Bytes entsteht kein Auftrag. Für geänderte Bytes wird
die Quelle mit einer frischen nativen Aktion und allen aktuellen Zustimmungen
erneut geöffnet. Ursprüngliche Dateisignatur, Zuordnung und Katalogversion müssen
vor der Cache-Anlage genau dem Prüfstand entsprechen; die kopierten Bytes müssen
vor Ready nochmals denselben Hash ergeben. Eine dazwischen veränderte Datei
oder Quellhistorie sperrt die Vorbereitung. Eine unpassende Hashvorgabe wird
nicht zu Ready befördert; bereits geschriebene Teilstände bleiben erhalten.

Ein so vorbereiteter Auftrag nutzt denselben tatsächlichen Quellbesitzer und
dieselbe Steuersitzung wie die bestehende native Verbindung. Saved, Readback,
unabhängige Sicherung und Archivierung bleiben eigenständige Nachweise. Nach
ihrem Abschluss kann dieselbe unveränderte Quelle ohne neuen Cache übersprungen
werden, ohne SEND oder den Steuereigentümer durch Arbeiteraktivität umzuschalten.
Das ist weiterhin eine einzelne native Auswahl, noch kein automatisch
seitenweise laufender Sammlungsscheduler.

Ein nativer Arbeiter kann die bedingte Vorbereitung zusätzlich an seine eigene
aktuelle Operation binden. Diese Prüfung ist ausschließlich eine weitere Sperre:
Sie ersetzt weder Sendezustimmung noch Buch-, Richtungs-, Zuordnungs- oder
Dateirechte. Sie wird auch während des tatsächlichen Lesens und Kopierens sowie
bei späterem Zugriff auf die lebende Vorbereitung geprüft. Ein beendeter oder
fehlgeschlagener Operationsnachweis schließt genau diese Vorbereitung dauerhaft;
ein später wieder positiver Rückgabewert darf sie nicht erneut freigeben.
Abbruch schließt keine Deskriptoren aus einem fremden laufenden I/O heraus.
Bereits geschriebene Teilstände bleiben erhalten, werden aber nicht als Ready
oder wiederaufgenommene Leseautorität ausgegeben.

Für die folgende begrenzte Kandidatenauswahl kann die native Quelle außerdem
den genauen Zuordnungs-Snapshot und den aktuellen Versionskopf verlangen. Beide
werden innerhalb derselben geschützten Zuordnungslease vor dem Dateiöffnen
geprüft, bei der frischen Kopie erneut. Eine inzwischen historische Version
darf auch mit einem aktuellen Snapshot nicht zur automatischen Auswahl werden.
Die bisherige ausdrückliche historische Backup-/Restore-Auswahl bleibt ohne
diese zusätzlichen, ausschließlich einschränkenden Bedingungen unverändert.

### Begrenzter nativer Ausgangslauf über vorhandene Zuordnungen

Die normale Linux-Verbindung besitzt einen nativen Arbeiter für seitenweise
ausgewählte Zuordnungen. Er hält denselben Zuordnungs-Snapshot über alle Seiten,
prüft jede Datei mit der bedingten Vorbereitung und überspringt unveränderte
Bytes ohne Cache. Für geänderte Dateien benutzt er den bestehenden gemeinsamen
Steuersender. Erst tatsächliches Saved plus authentifiziertes Readback, eine
unabhängige lokale Sicherung und native Archivierung erlauben die nächste Datei.
Eine Readback-Projektion allein genügt nicht: Vor dem Backup muss die echte
Socket-/Cache-I/O-Lane frei sein. Stop und Verbindungsende entziehen Rechte,
melden aber keine Freigabe, während die tatsächliche I/O noch läuft.

Der manuelle native Sitzungseinstieg `sync_shared` verwendet die aktuelle
gemeinsame Richtungsvereinbarung. Ein reiner PC-Ausgangslauf fordert weder
Telefon-READ noch dessen Empfangszustimmung an. Import-only kann diesen Arbeiter
nicht zum Export veranlassen. Nicht implementierte gesamte PC-Sammlungen erhalten
eine ausdrückliche Review-Sperre statt eines Erfolgsergebnisses für eine Teilmenge.
Dies ersetzt keine native/physische Gesamtabnahme. Die vollständige gemeinsame
UI-Anbindung bleibt offen.

Der native WLAN-Einstieg wird nur aus tatsächlich abgeglichenen gemeinsamen
Einstellungen und unabhängiger nativer Sendezustimmung geplant. Die bestehende
Sitzung plant dabei auch PC-only, ohne Telefon-READ oder RECEIVE einzuschalten.
Der tatsächliche Dienst bindet die zusätzliche WLAN-Prüfung an genau seinen
aktuellen Kanal und dessen Transportart; eine Behauptung aus einem Protokoll-
oder UI-Feld reicht nicht. Automatische Quelloperationen prüfen diese Bindung
und den aktuellen gemeinsamen WLAN-Modus auch während späterer Socket-/Cache-I/O.
Manueller gemeinsamer Modus, fehlende Zustimmung und Transportwechsel sperren
den automatischen Export. Ein bestätigtes Readback ersetzt weiterhin keinen
tatsächlichen I/O-Abschluss, auch nicht beim automatischen Lauf.

Bei vorhandener gemeinsamer Vereinbarung bearbeitet die native Modusauswahl
deren eigenen geschützten Modusregister und wartet wieder auf den genauen
ACK-/Peer-Echo-Abgleich. Sie erfordert keine Aktivierung des Empfangs. Stop
pausiert auch einen gerade untätigen Automatiklauf; doppelte unveränderte
Einstellungs-Echos dürfen weder diese Pause noch eine manuelle Moduswahl aufheben.

Die Linux-Oberfläche kann für einen tatsächlich angebundenen, abgeglichenen
Ausgangsbereich Modus und Handlauf auch bei ausgeschaltetem Empfang anzeigen.
Ohne Telefonalbumauswahl sendet sie ausschließlich `sync_shared`, keine
erfundenen Album-IDs oder Empfangsfreigaben. Telefon-READ-/Entdeckungsaktionen
bleiben bei ausgeschaltetem Empfang verborgen. Die passive Anzeige verwendet
nur Metadaten aus dem lebenden nativen Besitzer und öffnet keine Mediendateien
oder geschützten Einstellungsstores. Dieser Anzeigehinweis verleiht keine Rechte:
Der echte Dienst prüft weiterhin Kanal, aktuelle native Metadaten-ACKs,
Fingerabdruck und sämtliche individuellen Quellbedingungen beim Start.

Nach einem neuen Kanalaufbau kann eine bestehende geschützte reine
Sendezustimmung denselben Quell-/Steuerbesitzer wieder zusammensetzen, ohne
RECEIVE einzuschalten. Voraussetzung sind die tatsächlich auf diesem Kanal
bestätigten Fähigkeiten, Grants und gegenseitigen Own-Device-Metadaten sowie
der vorhandene aktuelle Paarungsbezug. Vorhandene native Einstellungen bleiben
dabei unverändert; fehlende Schlüssel, Historien oder Verzeichnisse werden
nicht aus der Wiederanbindung erfunden. Die neue Verbindung sendet ihre eigenen
Steuer-/gemeinsamen Einstellungen und wartet auf frischen ACK-/Peer-Echo- und
Dateisteuerabgleich. Gespeicherte Übereinstimmung ist keine neue Leseautorität.

Ein zusätzlicher monitorfreier nativer Metadatennachweis begrenzt den Arbeiter
auch während Quell- und Socket-I/O. Fehlende oder inzwischen unbestätigte
Kanalmetadaten stoppen ihn; spätere gültige ACKs beleben diesen beendeten
Arbeiter nicht wieder. Eine gespeicherte gemeinsame Richtung darf bei der
Wiederanbindung nicht durch den älteren Empfangs-Autostart ersetzt werden.
Noch nicht wieder angebundene gemeinsame automatische Empfangspfade erhalten
eine ausdrückliche Review-Sperre statt unangeforderter Telefon-READ-Aktionen.

Auch ein nach seinem Angebot auf weitere Telefonanfragen wartender Ausgangslauf
prüft die aktuelle lokale Zustimmung und seine genaue Dateisteuerbindung. Diese
Prüfung läuft ausschließlich außerhalb einer Quell-/Cache-Lease und auf der
serialisierten Verbindungsspur. Während tatsächlicher Socket-I/O wird sie
nicht blockierend aufgeschoben, nicht als Zustimmungsfehler gewertet. Ein
beobachteter Entzug von lokalem SEND oder entferntem RECEIVE beendet den Lauf
auch ohne weitere Chunk-/Saved-/Readback-Nachricht. Original und bestehender
Cache bleiben erhalten; ein später erneut positiver Grant belebt den beendeten
Lauf nicht wieder und ersetzt weder Saved noch Sicherung oder Archivierung.

Auch die Metadatenabfrage des Zeitplaners belegt diese Verbindungsspur nur
nicht blockierend. Eine belegte Spur bedeutet vorerst keinen planbaren Lauf,
nicht neue Zustimmung oder eine Berechtigung, laufende Quell-I/O zu untersuchen.

### Erstmalige native Sendeeinrichtung ohne Empfangsaktivierung

Bei tatsächlich bestätigten aktuellen Quellmetadaten kann die Linux-Anzeige
eine getrennte Sendeeinrichtung anbieten, auch wenn noch kein Dateibesitzer
existiert. Ihr Versionshinweis ist ausschließlich eine speicherinterne
Einrichtungs-CAS, keine gespeicherte Zustimmung und kein Leserecht. Die Anzeige
erzeugt weder Paarungsmetadaten noch Standardordner oder Einstellungen.

Der private native Vorbereitungsaufruf bindet ein einmaliges, höchstens
60 Sekunden gültiges Ticket an den genauen Kanal/Paarungszustand, die bisherigen
geschützten Einstellungen, den tatsächlich gespeicherten Buchstand und die
getrennten Foto-/Videowünsche. Vorbereitung und Abbruch ändern diesen Bestand
nicht. Positive Erweiterungen durchlaufen weiterhin den nativen Dialog mit
Nein als Standardantwort; weder Browserfelder noch der Einrichtungs-Hinweis
ersetzen diese Entscheidung. Ein abgewiesener Commit kann nach einer späteren
Metadatenreparatur nicht wieder aufgenommen werden.

Erst der bestätigte Commit darf die bestehende enge native Initialisierung der
Dateipaarungsmetadaten benutzen und eine getrennte SEND-Zustimmung speichern.
Er aktiviert weder RECEIVE noch Telefon-READ und erzeugt keine Medienziele,
Zuordnungshistorien, Aufträge oder Quellcaches. Vorhandene abgewählte Zustimmung
bleibt bis dahin unverändert. Vorhandene Einstellungsreste ohne passenden
Paarungsbezug erhalten einen Review-Halt; fehlende Schlüssel werden nicht
erzeugt. Die gespeicherte Sendezustimmung allein startet keinen Abgleich:
gemeinsamer Bereich/Richtung/Modus und ihr tatsächlicher neuer ACK-/Echo-Abgleich
sowie Dateisteuerbindung bleiben getrennte Voraussetzungen.

Der native Einstellungsanschluss `shared_setting` bearbeitet genau ein
typgeprüftes gemeinsames Feld mit CAS gegen den vollständigen aktuellen
Registerstand. Er bestätigt keinen Empfang und keine Sendezustimmung. Ungültige
Felder/Werte und veraltete Versionen werden vor einer Registeränderung oder
Invalidierung bestehender Übereinstimmung abgewiesen. Nach einer gültigen
Änderung bleiben tatsächlicher gesicherter Ausgang, ACK und Peer-Echo nötig;
ein lokaler Anzeigehinweis allein ist kein gemeinsamer Vertrag.

Die passive native Projektion dieser Einstellungen stammt nur aus dem
speicherinternen Transportbeobachter. Sie unterscheidet gespeicherte unabhängige
Auswahl und effektive Übertragungsrichtung: Import-only zeigt die zuvor gewählte
Richtung weiterhin an, kann sie aber nicht zum Export benutzen. Änderungen
behalten native Foto-/Video-Sendebits, RECEIVE, Steuersitzung und deren
Berechtigungsrevision bei. Der Buchnachweis hält dabei keinen SQLite-
Wartungsschreiblock über die separate Registertransaktion in derselben
`phone.db`, sondern prüft den tatsächlichen ursprünglichen Buchstand erneut.

Die Linux-Oberfläche bearbeitet diese Felder erst nach tatsächlicher dauerhafter
Buch-Speicherbestätigung und mit der aktuellen gemeinsamen Registerversion.
Bereich, konfigurierte Richtung und Modus bleiben getrennte Auswahlen; ein
ausstehender Auftrag zeigt weder optimistische Zustimmung noch vorweggenommene
Übereinstimmung an. Native Antworten sind mit begrenzten Anfrage-IDs korreliert;
alte Antworten dürfen keine neue Kopplung oder einen neueren Auftrag verändern.
Empfang und native Senderechte bleiben eigene Bedienelemente. Ein noch nicht
angelegter gemeinsamer Registerstand ist ausdrücklich als unkonfiguriert
ausgewiesen, nicht als Widerruf einer bestehenden Legacy-Empfangskonfiguration.

Sobald gemeinsame Register vorhanden sind, darf auch der ältere Albumstart
eine ausgeschaltete oder noch unbestätigte gemeinsame Vereinbarung nicht über
weiterhin positive native Empfangsrechte umgehen. Der native Sitzungsstart
verlangt vor neuem Batch-/Dateiablauf die tatsächlich aktuelle passende
Übereinstimmung. Nicht implementierte gesamte PC-Sammlung und Löschweitergabe
bleiben in der UI gesperrt; gespeicherte Werte werden deshalb nicht verworfen.
Stop bleibt während tatsächlicher Arbeit auch dann erreichbar, wenn eine
Übereinstimmungsänderung den bisherigen Ausgangs-Anzeigehinweis zurückzieht.

Ein gemeinsamer nativer Abgleich bindet beide Richtungen an dieselbe ursprüngliche
Übereinstimmungsidentität, die angeforderten Medienarten, den gespeicherten
Buchstand und dessen begrenzte Laufzeit. Aktuelle Kanal-Metadaten und bei einem
automatischen Lauf die tatsächliche WLAN-Verbindung bleiben erforderlich. Dieser
Kontext wird als ausschließlich einschränkende Prüfung durch Quellbefehle,
Quellläufe und den tatsächlichen Empfänger bis zu Chunk-Schreiben und
Veröffentlichung mitgeführt. Ein fehlgeschlagener oder beendeter Kontext wird
durch spätere positive Antworten oder eine neue Übereinstimmung nicht erneuert.
Alle unabhängigen nativen Datei-/Medienrechte bleiben zusätzlich erforderlich.

Ein Kontextwiderruf ersetzt weder den tatsächlichen Drain noch Source-END.
Nur der exakt zugeordnete Stop-Checkpoint darf nach bekanntem Request-Drain bzw.
korrelierter Cancel-Barriere auf demselben Thread den zurückgezogenen
Laufkontext übergehen; neue Chunks oder Veröffentlichung dürfen das nicht.
Verifizierte Teilstücke, ursprüngliche Dateien, Jobhistorie und Quota bleiben
erhalten. Unbekannter Quellabschluss bleibt ausdrücklich HOLD.

Gemeinsamer WLAN-Empfang ist unabhängig von nativer SEND-Zustimmung planbar,
verlangt aber bereits bestehende native Empfangszustimmung und aktuelle
Dateisteuerbestätigungen. Nach einem Verbindungswechsel werden gespeicherte
Empfangseinstellungen nur lesend übernommen; gemeinsame Metadaten und
Dateisteuerung müssen auf dem neuen Kanal tatsächlich neu bestätigt sein.
Der folgende Lauf holt zuerst den aktuellen Telefonstatus und danach den
Katalog. Er benutzt nicht den älteren Aktivierungsweg: weder Telefon-SEND noch
Videos oder Android-READ werden dabei automatisch eingeschaltet. Ein OFF- oder
Reparaturstatus des Telefons bleibt Review/HOLD statt einer Konfiguration.

Die bloße Existenz gespeicherter gemeinsamer Einstellungen ist eine zusätzliche
Wiederverbindungsgrenze, keine Übereinstimmung und kein Dateirecht. Auch bei
entzogener Medienfähigkeit darf sie nicht durch einen älteren automatischen
Empfangs-Bootstrap ersetzt werden. Ohne solche gemeinsamen Einstellungen bleibt
der bestehende ausdrücklich konfigurierte Legacy-Empfangsweg erhalten.

Belegt ein anderer nativer Vorgang die Verbindungs-I/O-Spur unmittelbar vor
der Erzeugung eines Sende- oder Empfangsworkers, darf ausschließlich der dort
vor der Erzeugung auftretende `file_desktop_connection_busy` begrenzt erneut
versucht werden. Jeder Versuch verbraucht einen neuen nativen Aktionstoken;
ursprünglicher Laufkontext, Buchstand und Fristen bleiben unverändert. Stop,
Widerruf, jeder andere Fehler sowie bereits erzeugte oder gehaltene Worker
werden damit nicht wieder gestartet.

Ein einzelner gemeinsamer Medienlauf mit aktuell vollständig gelesenem, leerem
Telefonkatalog kann ohne Batch-/Dateianfrage abschließen. Ein leerer Katalog mit
nur ausgewähltem oder fehlendem Lesezugriff ist kein vollständiger Scan. Auch ein
vollständig leerer Katalog beweist keine Löschung und darf keine vorhandenen
PC-Dateien, Zuordnungen oder Wiederherstellungskopien verändern.

Die Sitzungsanzeige summiert gespeicherte/als bekannt geprüfte Dateien und
Konflikte über die tatsächlichen Teilworker desselben Laufs. Nur nach dessen
wirklichem END wird ein Worker genau einmal in die Sitzungssumme übernommen;
sein noch laufender Fortschritt wird zusätzlich angezeigt. Der nächste Abgleich
beginnt bei null. Das sind Vorgangs-/Übertragungszähler, keine deduplizierte
Sammlungsgröße, keine Saved-/END-Autorität und kein Vollständigkeitsnachweis.

Die Linux-/Windows-Medienordner werden durch explizite Ordner- und
Standardaktionen bedient. Vorhandene Pfade stehen nur im Tooltip des jeweils
eindeutig als Foto- oder Videoziel bezeichneten Ordnerbuttons, nicht als
sichtbares Pfadfeld; die native Ordnerwahl erhält weiterhin keinen Webpfad.
Die gemeinsamen Auswahlen folgen Umfang, Automatik und unabhängiger Richtung.

Auch die Windows-Oberfläche bearbeitet `photos_only` als eigenes versioniertes
gemeinsames Feld hinter der Videos-Auswahl. Erst der dauerhafte Buch-Save geht
der nativen Einzelfeld-Anfrage voraus; Fehler setzen die Anzeige auf den
bestätigten Stand zurück. Fehlt die native Feldversion, wird keine bearbeitbare
Filterfunktion angeboten. Der Regler erteilt keine SEND-/RECEIVE-Rechte und
startet keinen Transfer. Die vorhandene native Metadatenprüfung, nicht eine
Dateiendungsprüfung, entscheidet weiterhin über die ausgewählten Aufnahmen.

Auch die native Windows-Einstellungsansicht zeigt konfigurierte Richtung und
Modus getrennt vom wirksamen Transferfilter. Bei Import-only bleibt eine
gespeicherte PC→Telefon-/Zwei-Wege-Richtung sichtbar und unabhängig editierbar;
`Effective`/`TransferRequestedFor` verbieten weiterhin jeden Export in diesem
Umfang. Weder die nur lesende Ansicht noch ein Umfangswechsel schreiben die
Richtungsregister, Dateirechte oder Historien um.

Notes verwendet dieselbe Trennung in seiner gespeicherten Einstellungsansicht
und im nativen Compose-Richtungsmenü. Die Galerie-Empfangsaktion bleibt bei
Import-only gesperrt, auch wenn die konfigurierte Richtung PC→Telefon oder
Zwei-Wege ist. Die tatsächlichen Transport-Intents verwenden weiterhin nur
die wirksame Richtung; ein Menüklick übergibt ausschließlich den gewählten
Richtungswert und seine aktuelle native Feldversion.

Notes bietet `photos_only` ebenfalls als eigene Auswahl nach Videos an. Der
Haken folgt ausschließlich dem bestätigten nativen Zustand; der Klick übergibt
nur das Feld, den Wert und dessen Version. Fehlende Feldversion oder deaktivierter
Abgleich sperren die Auswahl. Die vorhandene Prüfung der Aufnahmemetadaten in
Galeriequelle und nativem Empfänger bleibt unverändert, ohne neue Android-Rechte.

Der lokale Notes-Wiederherstellungsbereich startet separat eingeklappt, auch
ohne Telefonkopplung. Archivladen beginnt erst beim ausdrücklichen Öffnen;
Vorschauoption, Einträge und Aktionen bleiben vorher verborgen. Zuklappen
entfernt Vorschauen und offene Bestätigungen, schaltet automatische Miniaturen
wieder aus und beendet einen noch aktiven Restore-Kontext, ohne dessen native
I/O-Handles vor tatsächlichem END zu schließen. Späte Vorschaubilder werden im
geschlossenen Bereich verworfen statt erneut angezeigt. Dies ersetzt weder
Aufbewahrungs-/Leeren-Funktion noch native Geräteabnahme.

Der Windows-Handstart eines gemeinsamen Abgleichs verwendet `sync_shared`
mit einer ausschließlich nativ erzeugten, an aktuelle Verbindung und vollständige
Einstellungsregister gebundenen Version. Er benötigt kein ausgewähltes
Telefonalbum, wenn nur PC→Telefon angefordert ist. Die strikte Browsergrammatik
akzeptiert dabei weder Pfade, Kataloge, Einstellungen noch Berechtigungsflags.
Native Kanal-ACK/Übereinstimmung, unabhängige SEND-/RECEIVE-Zustimmung und das
aktuell gespeicherte Buch werden vor dem bestehenden gemeinsamen Lauf erneut
geprüft. Ein Anzeigehinweis erteilt keine Datei- oder Android-Leserechte.
Stop bleibt während des Laufs erreichbar; bei fehlgeschlagener Startantwort
wird der native Lauf abgebrochen und sein tatsächliches Ende abgewartet.

Auch der gemeinsame Windows-Eingang verwendet beim manuellen und WLAN-Lauf
keine Telefon-Aktivierung: Erst eine tatsächlich korrelierte frische
Statusantwort bestätigt einen bereits eingeschalteten, zugeordneten Quellstand
ohne Reparaturbedarf. Telefon-SEND oder Video-OFF bleibt Review, ohne
`configure`, `configure_videos` oder `request_read`. Video übernimmt seine
Quellversion nur innerhalb desselben aktuellen nativen Auswahl-/Kontrollkontexts
nach unabhängiger tatsächlicher Datenbestätigung; ein neuer Versuch entfernt
vorherige Videoaktivierung. Der ausdrücklich gewählte Legacy-Einrichtungsweg
bleibt davon getrennt und unverändert.

Der automatische gemeinsame Windows-Gesamtlauf bindet sich wie der manuelle
Lauf an die ursprünglichen vollständigen Einstellungsregister und dieselbe
native Verbindung. Auch eine später tatsächlich bestätigte neue Übereinstimmung
ersetzt diesen Kontext nicht, wenn die daraus projizierten lokalen Präferenzen
zufällig gleich bleiben. Alle Teilrichtungen/Medienarten benutzen den gepinnten
Stand; ein neuer Stand verlangt einen neuen Lauf statt zusätzlicher Rechte für
den bereits zugelassenen Vorgang.

Windows besitzt einen begrenzten nativen Videovorschaurenderer für lokale
MP4-Daten. Er erhält ausschließlich die bereits hash-/versionsgeprüften Bytes
der ausgewählten erhaltenen Datei, nie Originalpfad, Dateiendung oder URL.
ISO-BMFF-Referenzen auf externe Dateien/URLs/QuickTime-Referenzfilme werden vor
dem Decoder abgewiesen. Media Foundation liest einen nur lesbaren Speicherstream;
die Anwendung erzeugt dafür keine temporäre Klartextdatei und benutzt keinen
Shell-Vorschaudienst. Andere Container und fehlende Plattformcodecs bleiben HOLD.

Grenzen: höchstens 16 MiB Eingang, vor Decodierung geprüfte Abmessungen bis
32768 je Achse und 24 Millionen Pixel, höchstens 128 Sample-Leseversuche für
das erste Bild. Native Bildpuffer werden nur innerhalb ihrer tatsächlichen
Lebenszeit benutzt; eigene Klartext-/Pixelarrays werden danach gelöscht.
Die native Anzeige-Drehung wird vor dem bestehenden JPEG-Rasterpfad angewendet.
Ausgegeben werden weiterhin nur begrenzte 192-/1024-Seiten-Vorschaubilder nach
erneuter Eigentümer-/Dateiprüfung. Miniaturen bleiben standardmäßig OFF;
Vorschau erteilt weder Wiederherstellungs-, Lösch-, Saved- noch END-Rechte.

Tatsächlich nativ geprüft sind H.264-Baseline-MP4, Farbanordnung/Zeilenrichtung,
eine 90-Grad-Displaymatrix, der reale Produkt-JPEG-Renderer sowie Vorschau nach
echtem Empfang/Saved/Source-END und expliziter lokaler Papierkorboperation.
Das ist keine vollständige Codec-/Geräte-/installierte GUI-Abnahme.

Für bisher nicht zugeordnete Windows-PC-Dateien gibt es zunächst eine getrennte
native Quellgrundlage: verschlüsselt gespeicherte, unabhängig identifizierte,
nur lesbare Quellwurzeln sowie begrenzte handle-relative Bestandsaufnahme und
Wiederöffnung anhand tatsächlicher Verzeichnis-/Datei-IDs. Auswahl und Inventar
erteilen keine SEND-/RECEIVE-Rechte, erzeugen keine Telefonreferenz und sind
kein vollständiger Snapshot, Löschbeleg oder abgeschlossener Transfer.
Backup- und private `.magnolie-`-Unterbäume sind ausgeschlossen; Reparse-Ziele
werden nicht verfolgt, mehrfach verknüpfte Dateien abgewiesen und Grenzen nicht
als vollständiger Bestand ausgegeben. Fehlende ursprüngliche Schlüssel,
geänderte Paarung, beschädigte Quellaufzeichnung und ersetzte Wurzeln bleiben
HOLD unter Erhalt der gespeicherten Daten. Native Benutzerauswahl, automatische
Einbindung und durchgängige Gegenstellen-Versionszuordnung für diesen bislang
nicht zugeordneten PC-Bestand sind damit noch **nicht** als benutzbar abgenommen.

Quellinventar und Wiederöffnung binden zusätzlich die tatsächlich nativ gelesene
Erstellungszeit der Datei und ihrer Verzeichnisvorfahren. Dieser zusätzliche
Generationszeuge ist keine eigenständige globale Identität oder Berechtigung.
Änderungen führen zu HOLD; verworfene Leseowner werden durch Zurücksetzen des
Zeugen nicht wieder verwendbar. Neue Quellroot-Aufzeichnungen verwenden dafür
Format 2. Alte Format-1-Aufzeichnungen ohne Zeugen bleiben unverändert lesbar,
erlauben aber weder Wiederöffnung noch automatische Aufwertung anhand des
heutigen Dateisystems. Bestehende Telefonmapping-/Quellcacheformate bleiben
unverändert.

Der interne Windows-PC-Quellowner kann unabhängig von PC-RECEIVE und
Telefon-READ denselben authentifizierten Sender mit verifiziertem Cache,
angeforderten Chunks, Peer-Saved, korreliertem Readback, tatsächlichem
Writer-Drain und eigenem Source-END benutzen. Sein Originalbuch, voller
gemeinsamer Intent, lokale medientypspezifische SEND-Einwilligung,
Verbindung/Paarung und tatsächliche native Quelle bleiben auf jedem Zugriff
gebunden. Nachweislich bereits gemappte native Dateien dürfen nicht als neue
unabhängige PC-Herkunft umetikettiert werden.

Lokale Quellcacheformate 3/4 tragen getrennte PC-Herkunft einschließlich
Quellroot-/Dateiidentität und zusätzlicher Generationszeugen. Sie erlauben
leere Telefonreferenzen ausschließlich für `entire_collection`; die strengen
alten Cacheformate 1/2 verlangen weiterhin ihre echte Telefonreferenz.
Versionen hängen an der jüngsten tatsächlich abgeschlossenen Quellversion;
unveränderte Inhalte, unvollständige Vorgänger oder unsichere Generationen
erteilen keine neue Sendeberechtigung. Alle alten Aufzeichnungen bleiben
erhalten, einschließlich bei gemischter Telefon-/PC-Quellhistorie.
Eine bekannte native Dateiidentität mit geänderter Quellwurzel oder Generation
bleibt ebenfalls HOLD. Auch das tatsächliche Verschieben derselben Datei in
eine zweite ausgewählte Wurzel darf keine neue unabhängige Herkunft erzeugen;
eine ausdrückliche sichere Neuzuordnung ist damit nicht implementiert.
Windows speichert den vollständigen nativen relativen Pfad im getrennten lokalen
Ursprungsformat 2. Eine tatsächliche neue Datei-ID am bereits bekannten Pfad
bleibt ebenfalls HOLD, ohne Übernahme nach Name oder Bytes. Gleichnamige Dateien
in verschiedenen Unterverzeichnissen bleiben unterscheidbar. Das ältere lokale
Ursprungsformat 1 bleibt unverändert lesbar; ohne vollständigen Pfadzeugen darf
es keine neue Zuordnung innerhalb derselben Quellwurzel erlauben. Weder der
heutige Dateibaum noch der bloße Wire-Dateiname darf diesen fehlenden Zeugen
nachträglich ergänzen. Cacheformate 3/4 und das opake Wire-Format bleiben davon
getrennt; native Pfade und IDs werden weiterhin nicht übertragen.

Media-Offer-Format 2 ergänzt `pc_origins`: pro zugehöriger Datei ausschließlich
`format: 1`, `origin_sha256` und `previous_publication_sha256` (anfangs `null`).
Es überträgt keine lokalen Root-/Datei-IDs oder Pfade. PC-Herkunft und echte
Telefonreferenzen dürfen sich nicht überlappen und müssen gemeinsam exakt die
angebotenen Dateien abdecken. PC-Herkunft ist nur für `entire_collection`
zulässig; Format 1 behält sein bisheriges exaktes Schema.

Der Sender bestimmt den Vorgängerfingerabdruck erst nach erneuter Prüfung der
geschützten abgeschlossenen Quelllinie einschließlich eigenem Source-END.
Historische lokale Vorläufer ohne PC-Wire-Herkunft bleiben erhalten auf HOLD,
statt nachträglich eine Notes-Zuordnung zu erfinden. Gemeinsame kanonische
Vektoren prüfen diese Metadaten in Windows, Linux und Notes.

Notes bindet PC-Herkunft an den geschützten Publikationsdatensatz (Format 3)
und seinen Scope-Fingerabdruck. Vor Reservierung/Acceptance/Provider-Insert
verhindert die bestehende bounded Journalprüfung, dass neue Transfer-/Quell-IDs
denselben bereits reservierten oder publizierten PC-Ursprung in eine zweite
Galerienzeile aufspalten. Auch der genaue Vorgängerfingerabdruck allein erlaubt
keinen Austausch und keine Löschung; ein unbekannter Vorgänger bleibt HOLD.
Die alten Publikationsformate 1/2 bleiben unverändert erhalten.

Erstimport und diese Haltegrenzen sind im tatsächlichen Notes-Runtime-/SQLite-
Pfad mit Robolectric und simuliertem MediaStore-Provider geprüft, nicht auf
einem Android-Gerät. Der native Ersatz-/Archivierungs-/Löschowner für eine
Folgeversion steht noch aus. Ein Windows-Sendernachweis mit synthetischen
Peerantworten beweist keinen durchgängigen Android-Versionsaustausch. Deshalb
bleiben automatische neue PC-Gesamtbestands-Exporte, vollständige Benutzerauswahl,
Capability 23 und gemeinsame Geräteabnahme weiterhin gesperrt.

Die unabhängige Linux-Quellgrundlage arbeitet ebenfalls ausschließlich lesend
über gehaltene Deskriptoren. Sie verlangt echte fd-relative `statx`-Geburtszeit
und Mount-ID ohne `ctime`-Ersatz. Begrenzte Inventuren verwenden jeweils einen
frischen Verzeichniscursor; Mitgliedsmetadaten sind an die ursprüngliche Wurzel
gebunden. Links, private Backup-/Stagingpfade und Mount-Abstiege werden nicht
als Medienquelle übernommen. Geänderte oder verworfene Leser leben nicht wieder
auf; Schließen eines Mitglieds wartet auf laufende Lesezugriffe und verwirft
deren unveröffentlichten Puffer. Das Schließen allein der Wurzel ist kein
Source-END und ist keine vollständige Linux-Synchronisationsfunktion.

Der getrennte geschützte Linux-Quellwurzelkatalog verwendet die vorhandene
AEAD-/SQLite-Deskriptorinfrastruktur, ohne Telefonpräferenzschemas zu ändern.
Passive Abwesenheit erzeugt nichts; nur eine verbrauchbare native Aktion und
eine gehaltene Quellwurzel erlauben eine neue Auswahl. Die maximal 32 Auswahlen
bleiben append-only erhalten. CAS und geschützte Mitgliedschaft sowie ein an
seinen tatsächlichen Inode gebundener Anchor verhindern stilles Ersetzen
einzelner Katalogteile durch Kopien. Fehlende oder ausgetauschte Teile bleiben
HOLD. Ein Paarungswechsel erhält alte Metadaten, verleiht aber keine neue
Wiederöffnungs- oder Neuzuordnungsbefugnis. Änderungen am gespeicherten Pfad,
nativer Identität, Geburtszeugnis oder Mount-ID werden nicht automatisch
übernommen. Auch eine neue Mount-ID nach einem Systemneustart ist kein Anlass
für eine automatische Reparatur.

Wiederöffnung verlangt erneut die tatsächliche native Quelle und einen
aktuellen Guard; die Auswahl selbst verleiht kein SEND. Die private
Speicherwurzel des Katalogowners und ihre Vorfahren sind keine zulässigen
Medienquellen. Das ist noch keine vollständige Linux-Synchronisationsfunktion.
Ein separater unveränderlicher
Ursprungszeuge bindet Scope, Katalogwurzel, Datenbank, Lock und Anchoridentität.
Die vorhandenen geschützten nativen Einstellungen können ihn durch eine
ausdrückliche native Aktion im optionalen Feld `collection_roots` festhalten.
Die Bindung verlangt eine bereits vorhandene Policy, aktiviert keine
Einwilligung und erhält die tatsächliche Berechtigungsrevision und -epoche.
Alte Policies ohne das Feld behalten ihre exakte Form; bestehende
Einstellungsänderungen erhalten den gebundenen Zeugen. Eine bereits gebundene
Originalidentität darf nicht durch einen anderen Katalog ersetzt werden.

Die interne Einstellungsfactory öffnet den Katalog ausschließlich mit diesem
gespeicherten Zeugen. Auch nach erneutem Öffnen der Einstellungen bleiben ein
gemeinsam fehlender Katalog samt Anchor oder ein separat neu angelegter
Ersatzkatalog HOLD, ohne Bootstrap oder Neuzuordnung. Die Produkt-UI verwendet
diese Auswahl-APIs noch nicht. Das ist
kein Nachweis gegen einen gemeinsamen Reset aller unabhängigen Zeugen samt
Einstellungen oder einen vollständigen historischen Datenbank-Rollback auf
unveränderten Inodes. Keine automatische Wiederherstellung oder Neuauswahl wird
daraus freigegeben.

### Linux: unabhängiger PC-Quellowner am Cache-/Sendeweg

Der ausdrückliche native Collection-Owner liest tatsächlich ausgewählte Dateien
unter der vorhandenen gespeicherten Buch-/Intent-/Einwilligungs-IO-Lease. Er
benötigt weder PC-RECEIVE noch Telefon-READ. Ein echtes Telefonmapping wird nicht
nachgebaut: Vor Aufnahme werden sämtliche authentifizierten Mappinggenerationen
auf die native Dateiidentität geprüft; danach bleibt ihr vollständiger
geschützter Änderungszeuge gebunden. Jede spätere Mappingänderung hält den Lauf
an. Originalquelle, Quellwurzelkatalog, Policy, Paarung und voller Intent werden
weiter geprüft. Ein tatsächlicher Medien-MIME-Nachweis erfolgt vor Cacheanlage;
unzulässige Wire-Dateinamen werden abgewiesen, nicht normalisiert.

Der gemeinsame Cache-/Job-/Readerweg akzeptiert nur die zwei ausdrücklich
benannten exakten lebenden Klassen, keine beliebigen Unterklassen oder
Duck-Typen. Alte Mappingcache- und Jobformate bleiben unverändert. Separates
PC-Format 3 trägt lokale Herkunft, Katalogzeugen und Medienart bei leeren
Telefonreferenzen. Der begrenzte geschützte Jobkatalog hält die Herkunft über
alle ausgewählten Wurzeln hinweg fest. Bekannte native Dateiidentitäten und
ein neuer Inode am bereits bekannten vollständigen relativen Quellpfad bleiben
HOLD. Der Pfad ist nur eine Sperrgrenze für unsichere Neuzuordnung, keine
Identitäts- oder Übernahmeberechtigung nach Namen. Auch ein exakt bekannter
PC-Ursprung wird vorerst nicht als neue Folgeversion vorbereitet.

Eine echte katalogeigene Auswahl-IO-Lease hält authentifizierte Mitgliedschaft
während begrenzter IO fest. Die native Sperre schließt andere Katalogschreiber
aus; tatsächliche Datenbank-Signaturänderungen durch Umgehen dieser Sperre werden
trotzdem abgewiesen. Der Zeuge darf nicht nach Lease-Ende oder in einem anderen
Thread weiterverwendet werden. Dies vermeidet wiederholtes Entschlüsseln
unveränderter Mitgliedschaft, ohne Aktions-/Wirefristen zu verlängern.

Der private Sender bietet die anfängliche opake PC-Herkunft im Media-Offer-
Format 2 an und verwendet tatsächlichen verschlüsselten Offer-/Chunk-Verkehr.
Eine gewöhnliche Offer ohne PC-Herkunft sowie Retry-/Reprepare-Abkürzungen sind
für diesen Owner gesperrt. Peer-Saved und korrelierter Publikations-Readback
sind weiterhin keine lokalen END-/Löschberechtigungen.

Separates lokales Quellbackupformat 2 bewahrt PC-Herkunft ohne Telefonmapping.
Nach unabhängig geprüftem Backup und korreliertem Publikations-Readback kann
der tatsächliche native Abschluss zuerst Cache- sowie Quell-/Vorfahrenhandles
synchron schließen und danach den bisherigen no-replace Cache-Archivabschluss
schreiben. Nur der exakte schon drainende Besitzer darf auf derselben IO-Lease
noch den terminalen Status und den abschließenden Buchcheckpoint prüfen; keine
neuen Chunks oder Dateileser werden dadurch erlaubt. Abbruch hält reale IO und
Buchplatz bis zum tatsächlichen Ende ausstehender Ausgabe und bewahrt unklare
Ausgabe als Pending, nicht als Abschluss.

Die lokale Sicherung lässt sich ohne Quelldatei, verfügbaren Transfercache,
aktiven Kanal oder lebenden Peer-Owner in eine ausdrücklich neue Zieldatei
wiederherstellen. Eine daraus abgeleitete native PC-Wiederpublikation oder
Notes-Folgeversion hat noch keinen eigenen Besitzer und bleibt HOLD.

Die normale native Verbindung besitzt zusätzlich einen exakten PC-Quellowner
und einen ausdrücklichen internen Vorbereitungseintritt. Vor dem Kopieren bindet
er die bereits positiv bestätigte SEND-Richtung, ursprüngliche eigene und
entfernte Steuersitzung, native Aktion samt Frist und Verbindung. Eine spätere
entfernte Sitzung darf die vorbereitete Quelle auch bei gleicher persistenter
Berechtigungsepoche nicht erneuern. Der normale Nachrichtenverteiler und Sender
benutzen dieselbe bestehende Steuersitzung; es gibt keine zweite Sitzung und
keinen Wechsel von Grant-Bits abhängig von aktiven Arbeiten.

Nur genau ein vorbereiteter Mapping- oder PC-Owner darf zum Sender gehören.
Eine ausstehende PC-Vorbereitung sperrt andere Mapping-Kopier-/Planungs-/Worker-
Eintritte vor Quell-IO. Nach tatsächlich abgeschlossenem PC-END darf eine andere
Datei mit frischem Quellowner unter derselben Steuersitzung vorbereitet werden;
der alte Besitzer wird nicht wiederbelebt. Schließen der normalen Verbindung
signalisiert Abbruch sofort, gibt Quellhandles und Authority aber erst nach
dem tatsächlichen Ende ausstehender verschlüsselter Ausgabe frei. Unklare
bereits ausgegebene Bytes bleiben Pending, nicht END.

Diese Nachweise betreffen den tatsächlichen Linux-Host-/AEAD-/SQLite-/Socketweg
und normalen Factory-/Verteiler-Code mit privater Test-Funktionsfreigabe und
simulierten Peerantworten. Auch ein frischer Ausgangszustand ohne vorherige
Empfangseinstellung, Empfangsziel oder Mappingstore besteht mit PC-RECEIVE und
Telefon-READ aus. Der native Picker und die automatische Gesamtbestandssteuerung
sind noch nicht angeschlossen. Notes-Versionsaustausch und Geräteabnahme bleiben
offen. Daraus folgen weder Capability-23-Aktivierung noch benutzbare
Gesamtsynchronisation, Großbestands-/Video-Leistungsabnahme oder Auslieferung.

Die normale native Dateiverbindung komponiert für einen geeigneten bereits
authentifizierten Medienpeer ihre Einstellungsabstimmung und die Quell-Factory
für bereits telefonzugeordnete Dateien.
Sie startet dadurch keinen Arbeiter, Scan oder Transfer. Ohne eigene gespeicherte
Sendezustimmung bleibt SEND aus. Die Handlerzusammensetzung bleibt über die ganze
Verbindung stabil; aktive beziehungsweise beendete Arbeiter schalten keine
Berechtigungsbits um. Die bisherigen eigenständigen Präferenzprojektionen
bleiben standardmäßig SEND=false.

Eine ausdrücklich vorbereitete Quelle verwendet genau die bestehende
Steuersitzung und deren ursprüngliche Besitzer. Der normale reservierte
Nachrichtenverteiler führt Annahme, Chunk-Anfragen, Saved und Readback an diesen
Besitzer zurück. Medien-Einstellungs-ACKs werden nur anhand tatsächlich eigener
ausstehender Nachrichten übernommen; fremde normale ACKs warten nicht hinter
einer blockierten Dateiausgabe. Jeder tatsächliche Quellzugriff behält zusätzlich
seine ursprüngliche Buch-/Zustimmungs-/Absichts-/Cachelease.

Ausgabe und Archivierung halten den bestehenden Verbindungslauf bis zum
tatsächlichen I/O-Ende. Schließen signalisiert Abbruch, gibt aber weder
geschützte Verzeichnisse noch die native Aktivitätssperre vorzeitig frei. Erst
nach vollständig geprüfter verlustfreier Archivierung wird der alte Sender
abgelöst; die gemeinsame Steuersitzung und ihre Rechte bleiben stabil.
Vier neue native Factory-/Verteilerfälle prüfen vollständige verschlüsselte
Übertragung mit Saved/Readback/Archiv, Entzug ohne Besitzerwechsel sowie Schließen
während blockierter echter Ausgabe und Archivbewegung. Bestehende private
Kompositionen und die optional geschlossene Auslieferung bleiben getrennt.

Die normale Linux-Exportauswahl/-planung ist damit noch nicht angeschlossen.
Vollständige Sammlungs-, Lösch-, Galerieaufbewahrungs-
und gemeinsame physische Abnahme bleiben ebenfalls offen; Capability 23 bleibt
geschlossen.

## Linux: lokale Sendezustimmung über nativen Dialog und privaten IPC

Die Oberfläche bietet bei tatsächlich komponierter nativer Quelle eigene
Foto-/Video-Senderechte unabhängig vom Empfangsschalter. Sie wartet vor der
Anfrage auf die vorhandene dauerhafte Speicherbestätigung und zeigt vor einer
nativen Zusage kein positives Recht an. Verspätete Antworten gehören zur genauen
Anfrage, Kopplung und geöffneten Dateninstanz; sie ersetzen keinen neueren Zustand.
Die Statusprojektion verwendet nur bereits nativ gelesene Speicherwerte und
führt unter dem Dienstmonitor keine neue geschützte Datei-I/O aus.

Der tatsächliche GTK-Bestätigungsdialog ist standardmäßig ablehnend. Nur eine
Erweiterung der Rechte fragt positiv nach; Entzug benötigt keine Zustimmung.
Seine Vorbereitung erzeugt ein kurzlebiges einmaliges Verbindungsticket für die
genauen Foto-/Videowahlen, die angezeigte Präferenzversion und das tatsächlich
gespeicherte Buch. Ein geänderter oder bereits verbrauchter Kontext darf keine
Wahl übernehmen. Falsche alte Tickets verwerfen auch keine neuere gültige Wahl.
Der Browser darf weder ein solches Ticket noch einen Bestätigungs-, Grant- oder
Dateipfad mitgeben. Bestätigen und Abbrechen laufen über den bestehenden privaten
Unix-IPC und außerhalb des UI-Threads. Abbruch, Buchsperre, Schlüsselwechsel,
veraltete Version und Fehler behalten die bisherigen Rechte und Dateien.

Eine erhaltene Sendezustimmung einer älteren Kopplung wird weder als aktuelles
Recht angezeigt noch als bereits bestätigt behandelt, selbst wenn die unabhängige
Empfangszuordnung inzwischen erneuert wurde.

Siebzehn gezielte native Fälle einschließlich des tatsächlichen GTK-Callbacks und
privaten IPC sowie die vollständige Browseroberflächenprüfung bestehen. Dazu
kommen 94 betroffene bestehende Authority-/Verteiler-/Präferenz-/Kompositionsfälle
und drei IPC-Regressionen. Dies ist keine installierte Dialog-Klickabnahme und
keine vollständige automatische Sammlungssynchronisation; Capability 23 bleibt
geschlossen.

Die gemeinsame native Zusammensetzung und vollständigen Abschluss-/
Wiederaufnahmewege bleiben offen; Remote-Saved ist kein lokales Saved/END und
keine Berechtigung, den Ausgangscache zu entfernen.
