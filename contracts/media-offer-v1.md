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

Eine bereits aufgenommene Notes-Publikationsprüfung bindet zusätzlich atomar
die ursprüngliche lokale/entfernte Steuersitzung an ihre positive Transferbindung.
Die persistente Wire-/Resume-Bindung bleibt absichtlich unverändert, ist aber
allein kein Erneuerungsrecht für eine laufende Prüfung. Ein neuer Remote-
Sitzungszeuge bei gleicher Berechtigungsepoche hält den alten Prüfbesitzer an.
Ein begrenzter ausschließlich flüchtiger Übergangszähler merkt auch einen
Wechsel zurück zu alten Control-Paketwerten, bevor der IO-Besitzer wieder prüft;
er wird weder auf dem Wire noch in gespeicherte Journale aufgenommen. Gewöhnliche
Sequenz-/Echo-Nachrichten derselben Sitzung ändern diesen Zeugen nicht.
Eine neue ausdrücklich aufgenommene Prüfung kann dagegen ihre eigenen aktuellen
Rechte prüfen. Diese Grenze wird auch vor der tatsächlichen Readback-Ausgabe
kontrolliert; weder Aktions-/Angebotsfristen noch Grant-Bits werden erneuert.
63 gezielte Notes-Hostfälle bestehen einschließlich tatsächlichem Providerpfad,
Sitzungswechsel/-Rückwechsel, unveränderter persistenter Bindung, frischer
expliziter Wiederaufnahme und Überlauf-HOLD. Das ist Robolectric-Abnahme des
App-Codes, kein tatsächlicher Android-Geräte-/OS-Consent-Nachweis.

Der getrennte bereits aufgenommene Notes-Empfangsowner bindet denselben
ursprünglichen Control-Sitzungszeugen vor Aufnahme seiner Galerie-Scope-
Zuordnung. Ein später positiv bestätigter Remote-Sitzungswechsel bei gleicher
persistenter Bindung darf daher weder Reservierung noch Insert, Kopieren,
Publikation oder Saved-Ausgabe des alten Owners erneuern. Der indexinterne
Local-Guard bleibt transport-/sessionsperrenfrei und behält seine ursprünglichen
Buch-/Intent-/Fristprüfungen. 80 passende Notes-Hostfälle bestehen einschließlich
alter und frischer ausdrücklicher Aufnahme, Rückwechsel ohne Zwischenprüfung,
unverändertem Index/Provider vor Ablehnung und bestehendem normalen Runtime-/
Transfer-/Readback-Pfad. Diese Grenze schließt für sich weder die historische
PC-Folgeversionszuordnung noch einen Archiv-/OS-Schreib-/Löschowner ab.

Die normale Runtime hält den ursprünglichen atomaren Control-Operationszeugen
bereits vor Start des Empfangsarbeiters fest und reicht ihn bis in die tatsächliche
Owner-Konstruktion weiter. Ein später positiv bestätigter Sitzungswechsel darf
damit auch in der Lücke vor dem ersten Hintergrund-Capture keine Ersatzrechte
erzeugen. Fehlt die ursprüngliche positive Bindung, bleibt der bestehende
asynchrone Fehler-/Drainweg erhalten; eine nachträgliche Bestätigung darf daraus
keinen erlaubten Owner machen. Der ursprüngliche volle Incoming-Intent bleibt
auch beim gewöhnlichen internen Offer-Eintritt fest gebunden, nicht erst bei der
Media-Offer-Hülle. Automatikmodus und Richtung bleiben trotzdem unabhängig.

Die eigene Saved→Readback-Fortsetzung übernimmt denselben ursprünglichen
Control- und Intentzeugen. Sie vergleicht ihn vor ihrer Aufnahme und erneut
innerhalb des tatsächlichen Hintergrund-Owner-Konstruktors; ein Vorabvergleich
mit anschließend freiem Neu-Capture reicht nicht. Vier neue gezielte Runtimefälle
prüfen neue Remote-Sitzung vor dem ersten Owner, später ersetzten vollen Intent,
Sitzungswechsel nach Saved und die Capture-Race der Fortsetzung. Frische neue
explizite Aufnahme funktioniert weiter. 90 passende Runtime-/Transfer-/Rows-
Hostfälle bestehen, ohne Wire-/Resume-/Journal- oder Friständerung. Die weiteren
expliziten Auswahl-/Archivaktionswege und OS-Mutationsowner sind damit nicht
pauschal abgeschlossen; Geräteabnahme und Feature-/Auslieferungsgates bleiben.

Während einer konkreten Readback-Originalprüfung läuft zusätzlich bei jedem
tatsächlichen Provider-/Datei-IO-Schritt der ursprüngliche Angebotsguard mit.
Nur die spätere Netzwerkausgabe nach Fristende abzulehnen wäre nicht ausreichend:
die alte Aktion darf dann keine neuen Originaldateileser mehr eröffnen.
Eine Host-Gegenprobe hielt eine tatsächliche Providerquery bis nach dem echten
Ablauf eines gültigen kurzlebigen Angebots an; vor der Korrektur öffneten sich
danach noch drei zusätzliche Dateileser. Jetzt bleibt der alte Run vor diesen
Lesern HOLD und gibt keinen Readback aus. Eine unabhängig neu aufgenommene lokale
Inspektion funktioniert weiter; lokale PC-Archivaktionen erben keine fremde alte
Angebotsfrist. 91 passende Notes-Hostfälle bestehen, keine Uhr oder Produktfrist
wurde ersetzt oder verlängert. Buch, ursprünglicher Control-/Intentowner,
Originalbyte-/MIME-/Zeilenprüfung und tatsächliche IO-Drain-Bahn bleiben erhalten.

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

Als getrennte Voraussetzung kann ein ausdrücklicher nativer Notes-Eintritt nun
die tatsächliche bereits veröffentlichte app-eigene PC-Zeile unabhängig
archivieren. Dazu gehören ein exakter lebender PublishedInspection-/Rows-Owner,
die ursprüngliche Control-Sitzung, aktueller voller Empfangsintent und Policy
sowie zwei tatsächliche Permits desselben ursprünglichen gespeicherten lokalen
Buchs. Ein gleich aussehendes anderes Buch, Telefon-READ oder ein erfundener
ausgehender Gallery-Source-Lease sind kein Ersatz. Papierkorb OFF verbietet
neue Archivkopien und löscht bestehende Recovery-Daten nicht.

Die gemeinsame reale Medien-IO-Bahn bleibt während Original-Rücklesen,
nativer Byte-/MIME-/Zeilenprüfung und verschlüsselter Archivkopie gehalten.
Nur ein privater threadlokaler Abschlusspermit des tatsächlichen Rows-Owners
erlaubt dem exakten Archiv den Zugriff auf diese Originalzeile; Metadaten und
beliebige Leser-Callbacks eröffnen keinen Quellzugriff. Zeilenidentität,
Namespace, Generation, Größe und vollständiger Rohhash werden vor und nach
IO geprüft. Abbruch gibt den Platz erst nach tatsächlichem Provider-/Datei-IO-
Drain frei. Zwischenpuffer werden auch bei Fehlern gelöscht.

Separates lokales Archivformat 3 bewahrt die gesamte ursprüngliche PC-Publikation,
ihre opake Herkunft, tatsächlichen Zeilenzeugen, lokalen Buchzeugen und
unveränderte Originalbytes. Es erfindet keine Telefon-Album-/Quellreferenz.
Eine erneute ausdrücklich aufgenommene Prüfung derselben Originalpublikation
verifiziert die vorhandene Kopie, statt Zeit, Version oder Aufbewahrungsursprung
zu erneuern. Alte Archivformate 1/2 und die bestehenden Grenzen bleiben erhalten.
Die neuen Bytes lassen sich nach Schließen von Source-Index und Steuersitzung
sowie Weglegen der Quelldatei unter einem aktuellen lokalen Buchpermit lesen,
auch bei inzwischen ausgeschalteten neuen Archivkopien.

Diese Archivierung verändert keine Galeriezeile, erzeugt keinen Trash-/Saved-
oder Löschabschluss und erlaubt keinen PC-Folgeversionsaustausch. Der alte
OS-Mutations-/Telefon-Restore-Eintritt weist das neue PC-Archivformat mangels
eigenem Mutationsowner ausdrücklich ab. Sechs neue PC-Archivfälle und passende
bestehende Incoming-/Galeriequellen-/Archiv-/Recovery-Fälle bestehen im Notes-
Host-Gate, zusammen 246 Fälle. Dazu gehören Mehrchunk-Originale, neun strikte
Provenienz-Negativfälle, verschiedene echte Bücher, OFF, blockierte Medienbahn,
Byteänderungen und Abbruch während tatsächlich blockierter Provider-IO.
Dies sind interne native Primitiven mit Robolectric-Provider, noch keine
angeschlossene Recovery-Aktion oder Android-Geräte-/OS-Consent-Abnahme.
Der native PC-Schreib-/Ersetzungs-/Archivaktions-/Löschowner bleibt separat
zu komponieren; der bisherige HOLD bleibt.

Der native Verbindungs-/Runtime-Eintritt für eine ausdrücklich ausgewählte
PC-Archivkopie ist jetzt intern angeschlossen. Seine monotone Aktionsfrist
beginnt vor dem Workerstart; ursprünglicher voller Incoming-Intent, positive
Control-Sitzung und beide tatsächlichen Buchpermits bleiben bis zur Prüfung
und Kopie gebunden. Spätere Sitzungs-/Intentwechsel oder ein Abbruch vor dem
Hintergrund-Capture ergeben keinen neuen Besitzer. Eine fehlende aktuelle
Verbindungsvereinbarung wird bereits am nativen Verbindungseintritt abgewiesen.

Der vorhandene Publikations-Lesearbeiter besitzt auch diesen Archivmodus;
es gibt keinen zusätzlichen Hintergrundarbeiter oder Wire-/Browserbefehl.
Er liefert ausschließlich einen lokalen Archivnachweis, keinen Readback oder
Saved-Beleg. App-privater Recovery-Speicher wird erst nach tatsächlicher
Originalbyte-/MIME-/Zeilenprüfung geöffnet und noch innerhalb der gehaltenen
Medien-IO-Bahn geschlossen. Laufabbruch und Runtime-Cleanup warten auf das
tatsächliche Provider-/Speicherende, nicht nur auf ein gesetztes Abbruchflag.

95 passende Notes-Hostfälle bestehen einschließlich vier neuer Runtimefälle:
PC-SEND/Telefon-RECEIVE ohne umgekehrte Freigaben, unabhängige Offline-Lesbarkeit,
verzögertes Capture mit Sitzungs-/Intent-/Buchentzug oder Abbruch, falsche
Auswahl/Originalbytes und tatsächlich blockierte Provider-IO mit verzögertem
Runtime-Cleanup. Keine zusätzliche Quellprüfung des unveränderten alten
Telefonarchivpfads und keine Geräteabnahme werden daraus abgeleitet. Der
Benutzeraktions-/Dialoganschluss fehlt weiterhin; es ist keine benutzbare
Gesamtfunktion, keine Archivaktions-/Retention-Transition und kein PC-Ersetzungs-
oder OS-Schreib-/Löschowner. Der starke PC-Folgeversions-HOLD bleibt bestehen.

Der manuelle Notes-Benutzerweg ist nun in den vorhandenen Medieneinstellungen
angeschlossen: typspezifische Recovery-Kopie → native Auswahl veröffentlichter
PC-Dateien → ausdrückliche positive Bestätigung. Die begrenzte geschützte Liste
enthält nur Namen, Größen und genaue Publikations-/Versionsauswahl des aktuellen
Gerätepaars. Auflisten öffnet weder Providerleser noch Recovery-Speicher und
fordert keine Android-Leseberechtigung an. Leere oder alte Nicht-PC-Zeilen werden
nicht in PC-Ursprünge umgedeutet. Die Auswahlliste ist unveränderlich.

Auswahl und anschließender Arbeiter besitzen dieselbe ursprüngliche Aufnahme,
einschließlich ihrer schon vor Anzeige laufenden monotonen Frist. Bestätigen
nimmt keine neue Sitzung, keinen neuen vollen Intent und keinen Ersatzbuchpermit
auf. Abbrechen oder Activity-Pause entziehen die Auswahl; bei bereits laufender
Kopie wird deren wirklicher CancellationSignal ausgelöst. Die Coroutine wartet
bis zum tatsächlichen IO-Drain. Ein einmaliger Abschlusslistener am vorhandenen
Arbeiter vermeidet einen zusätzlichen Wartethread und signalisiert weder beim
Abbruchflag noch beim bloßen Ergebnis-Setzen einen vorzeitigen Abschluss.

Die Oberfläche erklärt ausdrücklich die unveränderten Originale und fehlende
Ersetzungs-/Löschwirkung; Papierkorbschutz wird nicht stillschweigend aktiviert.
Import-only, fehlende gemeinsame Bereitschaft und belegter manueller Lauf
aktivieren die Schaltflächen nicht. Bestehende lokale Recovery und ihre
standardmäßig ausgeschalteten Vorschaubilder bleiben unverändert. 113 passende
Hostfälle sind durch Union und gezielte Nachprüfung belegt, einschließlich
Compose-Weiterleitung, tatsächlicher synthetischer positiver/negativer Dialoge,
Activity-Pause, Sitzungs-/Intent-/Buchwechsel vor Bestätigung, Coroutine-Abbruch
während blockierter Provider-IO und frühem/spätem Abschlusslistener.

Dies ist ein angeschlossener Benutzerweg im Quellcode mit Robolectric-Abnahme,
keine Installation oder tatsächliche Android-Geräteabnahme. Andere Sprachen
verwenden für die neuen Texte zunächst den englischen Ressourcenfallback;
deutsche Texte sind vorhanden. PC-Folgeversionsaustausch, synchronisierte
Wiederanbindung und OS-Schreib-/Löschowner bleiben offen; ihre HOLDs und die
Feature-/Auslieferungsgates werden durch diesen manuellen Kopierweg nicht gelöst.

Als separater interner Ersetzungsbaustein gibt es einen eigenen PC-spezifischen
OS-Schreibanfrage-Owner. Er bindet vor Originalprüfung und Archivierung die
ursprüngliche PC-Publikation, Control-Sitzung, vollen Incoming-Intent, Empfangs-
Policy, echten Peer und beide ursprünglichen Buchpermits. Die monotone Frist
läuft über Archivierung und OS-Anfrage hinweg; Schließen des geliehenen reinen
Lesebesitzers erzeugt keine neue Aufnahme. Der genaue CancellationSignal bleibt
auch nach Archivierung gebunden.

Nur der echte threadlokale Rows-Archivabschlusspermit darf nach vollständiger
Originalbyte-/MIME-/Zeilenprüfung und verifizierter PC-Archivkopie eine tatsächliche
`MediaStore.createWriteRequest` für genau diese Original-URI erzeugen. Eine bloße
Archiv-/Publikationsreferenz genügt nicht. Der bisherige ausgehende Telefonowner
wird weder nachgebaut noch erweitert. Das neue ActivityResult-Host-Objekt hat
request-spezifische Schlüssel; ein zurückgezogener noch ausstehender OS-Dialog
behält seinen Platz bis zu seinem wirklichen Resultat. Alte Resultate können
keine neuere Anfrage bestätigen. Ein positives Resultat allein genügt nicht:
die aktuelle echte URI-WRITE-Berechtigung muss vorhanden sein und vor Benutzung
unter einer tatsächlich fortgesetzten Activity erneut bestehen. Grants sind
einmalig; spätere Activity-Pause oder ursprünglicher Sitzungs-/Intent-/Buchentzug
erneuern sie nicht. Eine konkurrierende Berechtigungsanfrage kann den Host sperren.

110 gezielte Hostfälle bestehen, darunter fünf neue PC-Anfrage-/Grantfälle und
drei passende bisherige Telefon-OS-Consentfälle. Tatsächliche Anfrageerzeugung,
separate Registry-Resultate und URI-Berechtigungsabfragen laufen gegen synthetische
Robolectric-Provider/Activity-Fixtures, nicht gegen ein tatsächlich zugestimmtes
Android-Gerät. Der neue Owner enthält ausdrücklich keinen Dateiwriter und ist
noch nicht in Runtime-/OS-Dialog-Benutzerführung eingehängt. Ein zukünftiger
Writer braucht zusätzlich ein dauerhaftes Vor-Schreib-Journal sowie neue genaue
Ziel-/Archiv-/Rohbyteprüfungen vor und nach Mutation. Der PC-Nachfolger-HOLD und
alle Geräte-/Feature-/Auslieferungsgates bleiben unverändert.

Vor einem künftigen Ersetzungs-Staging kann der native Index jetzt eine
geschützte Ersetzungsabsicht festhalten. Sie verlangt den tatsächlichen aktuellen
PC-OS-Grant, denselben authentifizierten Kanal und Index, ursprünglichen Vorgänger,
Archivversion und Buchzeugen sowie ein aktuell gültiges neues PC-Angebot unter
dem unveränderten vollen Intent. Die opake PC-Herkunft und der genaue vorherige
Publikationsfingerprint müssen passen; unveränderte Inhalte, anderer Medientyp,
MIME-Typ, sichtbarer Dateiname oder wiederverwendeter Transfer bleiben HOLD.
Ein kompletter portabler Manifestpfad bleibt gespeichert; für den sichtbaren
Zielnamen wird nur sein bereits verwendeter Blattname verglichen. Pfade erteilen
keine Übernahme- oder Ersatzberechtigung.

Das neue ausschließlich vorgeschlagene Journalformat ist getrennte geschützte
Metadatenmitgliedschaft, kein Source-Cache oder Archiv-Deletionsevent. Genau
128 solche Absichten haben ihr eigenes Budget; bestehende Source-Job-, Incoming-
und Historygrenzen werden nicht angehoben. Die Membership-Allowlist erkennt nur
den genauen neuen Präfix mit gültiger ID, keine beliebigen fremden Metadaten.
Bestehende Aufzeichnungen werden weder ersetzt noch entfernt. Eine zweite
Absicht derselben PC-Herkunft wird nicht als Wiederaufnahme angenommen.
Originale Control-/Grantprüfungen erfolgen außerhalb der Indexsperre; dort
werden nur lokale Buchzeugen geprüft. Ein während des Commit entzogener Owner
kann deshalb höchstens eine weiterhin gehaltene Absicht hinterlassen, aber keine
Datei ändern. Der gespeicherte Datensatz verleiht nach Neustart keine alten Rechte.

159 passende Rows-/Runtime-/Transfer-/Index-Hostfälle bestehen einschließlich
echtem archivierten Vorgänger, synthetischem OS-Grant, geschütztem Readback,
Entzug unmittelbar nach Commit, unveränderten Original-/Indexaufzeichnungen,
128er-Grenze samt tatsächlichem Membership-Rollback bei zusätzlichem Eintrag und
passiver Lesbarkeit nach Schließen von Sitzung und Index. Die normale
PC-Nachfolgeraufnahme bleibt nachweislich weiterhin gesperrt. Die vorgeschlagene
Absicht allein erzeugt keine Acceptance, Chunkrechte oder Vor-/Nach-Schreib-
Transition. Gerade ein Netzwerkstrom direkt in die bisherige veröffentlichte
Datei ist nicht freigegeben.

### Notes: separater verschlüsselter PC-Bild-Nachfolger-Zwischenspeicher

Ein interner Stagingeintritt verlangt zusätzlich zur exakt gespeicherten Absicht
weiterhin denselben lebenden ursprünglichen PC-OS-Grant, Kanal, Index, vollen
Intent, Buch und Control-Sitzungsowner. Er ist noch nicht mit dem normalen
Runtime-/UI-Ersetzungsablauf verbunden. Er erzeugt eine eigene tatsächliche
Acceptance und streng gebundene einzelne Chunkanfragen, aber keine neue
Medienzeile, Schreiböffnung des Originals oder Saved-Ausgabe. PC-SEND benötigt
weiterhin weder PC-RECEIVE noch Telefon-READ. Der normale Nachfolger-HOLD bleibt
unverändert; gespeicherte Pläne oder Stagingmetadaten umgehen ihn nicht.

Die eigene geschützte Stagingmitgliedschaft reserviert vor Nutzdaten den neu
erzeugten privaten Root samt nativer Identität. Sie hat getrennt höchstens 128
Datensätze und insgesamt 400 MiB reservierte Manifestbytes; bisherige Source-,
History- und Incominggrenzen bleiben gleich. Unklare oder abgebrochene Einträge
halten ihren Platz und ihre Dateien. Vorhandene Roots werden weder übernommen
noch gelöscht. Header, Chunks und Abschlussmitgliedschaft werden ausschließlich
verschlüsselt mit CREATE_NEW, Force und tatsächlichem Readback geschrieben.
Native Dateiidentitäten, Cipherhashes, private Rechte, Hardlink- und genaue
Verzeichnis-Mitgliedschaftsprüfungen schützen die laufenden Besitzer.

Vor dem Zustand `sealed` werden vollständiger Rohhash sowie native Bildgrenzen
und MIME über einen exakt besessenen entschlüsselnden InputStream geprüft;
Klartextdateien auf Platte gibt es nicht. Der optionale Fotometadatenfilter gilt
weiter. Video-Staging bleibt bis zum eigenen geprüften Parserpfad gesperrt.
`sealed` bescheinigt lediglich diese Zwischenspeicherkopie, weder Saved noch
lokale Schreib-, Wiederaufnahme-, Quell-END- oder Löschrechte. Nach Neustart ist
keine Aufnahme alter Chunkrechte oder Öffnung des Originals aus Metadaten möglich.

Die ursprüngliche OS-Aktionsfrist begrenzt auch Acceptance und Chunkwarten;
weder Archivierung noch OS-Anfrage oder Staging starten sie neu. Die gemeinsame
IO-Bahn bleibt bis zum tatsächlichen Ende aller Empfänger-, Observer- und
Metadaten-IO gehalten. Cancellation allein ist kein Drain. Ein kurzer
Mitgliedschaftsmutex umfasst keine Nutzdaten-IO oder native Parser. Unveränderliche
Vor-/Commit-/Nach-Snapshots erlauben nur den exakt lokal vorbereiteten Übergang
dieser Reservierung zu ihrer geprüften Versiegelung bei parallelen Observern.

177 unterschiedliche passende Hostfälle bestehen: zuletzt 64 Rows-, 48 Runtime-
und neun Transferfälle, ergänzt um unveränderte 51 Index- und fünf bisherige
Descriptor-Medienprüfungen. Neue Nachweise umfassen echte AEAD-Frames, zweichunkige
Bilddaten und native Bildgrenzen, unaligned Reads, Manipulationen, Fristen mit
tatsächlich verstrichener ursprünglicher Aktionszeit, getrennte Rollen,
Kapazitäts-HOLD, fremde Dateien/Roottausch/Hardlinks sowie tatsächlichen
Observer-FD-Drain und paralleles Versiegeln. Die Budgetprobe verwendet nur
synthetische geschützte Reservierungsmetadaten, keine 400-MiB-Nutzdatenkopie.
Dies sind Hostnachweise mit synthetischem Provider/OS-Grant, keine Android-Geräte-
oder Einwilligungsabnahme. Für diesen Stagingstand wird kein R8-Nachweis behauptet.
Der eigentliche Writer mit Schreibbeginn-/Nach-Schreib-Transitionen und
History-CAS sowie Runtime/UI-Anschluss fehlen noch. Die folgende zusätzliche
Vorprüfung ersetzt insbesondere keine Prüfung des künftig schreibenden FDs.
Gerätepause, Feature- und Auslieferungsgates bleiben bestehen.

### Notes: tatsächliche Vor-Schreib-Prüfung ohne Schreiböffnung

Der lebende fertig gestagte Bild-Nachfolger kann unter derselben ursprünglichen
OS-Aktion und IO-Bahn einen separaten `before_write`-Beobachtungseintrag erzeugen.
Dafür werden die genaue weiterhin veröffentlichte PC-Vorgängerzeile und ihre
Eigentümer-/Namespace-/Revisions-/Größenzeugen erneut abgefragt. Ein tatsächlicher
Original-Lese-FD wird ohne Transcodierung und ohne Assetoffset geöffnet, vollständig
gegen den alten Rohhash gelesen und nativ auf Bildtyp geprüft. Regular-File,
Gerät/Inode, Modus, Linkzahl, UID/GID, Größe und Nanosekunden-mtime/ctime werden
vor und nach der Prüfung sowie nach dem Commit verglichen. Der Lese-FD bleibt
während des geschützten Journal-Commit und seines Readback tatsächlich offen.

Das unabhängige bestehende Recovery-Archiv wird erneut inhaltlich geprüft; der
exakte ursprüngliche Eintrag mit Version, Rohhash/-größe, vollständiger
Vorgängerpublikation und ursprünglichem Buchzeugen muss übereinstimmen. Ein
anderer Archivstore oder ein gespeichertes `sealed` allein genügt nicht. Auch
die Stagingbytes werden erneut vollständig geprüft. Alle Schritte bleiben an
den ursprünglichen Kanal/Control/Grant, vollen Intent, Buch und Frist gebunden.
Ein direkter Indexaufruf mit nachgebauten Metadaten ist gesperrt: Nur die Rows-
Instanz mit tatsächlichem threadlokalem Prüf-FD-Besitz darf genau ihren Eintrag
unter derselben Stage-/Grant-/IO-Bahn veröffentlichen. Innerhalb der Indexsperre
werden nur lokale Aktions-/Cancellationzeugen geprüft, keine Transportsperren.

Der genaue neue geschützte Präfix hat ein eigenes 128er-Metadatenlimit; bestehende
Source-, History-, Staging- und Incominglimits werden nicht angehoben. Der Eintrag
bewahrt die vollständige versiegelte Stage und den nativen FD-Zeugen. Er besagt
ausdrücklich weder „Schreiben begonnen“ noch „geschrieben“ oder Saved und besitzt
keine Schreib-/Neustartautorität. Doppelte Aufnahme öffnet keinen weiteren
Original-FD. Entzug unmittelbar nach Commit hinterlässt den gehaltenen Eintrag,
aber keinen fortsetzbaren Writer. Cancellation gibt die IO-Bahn erst nach dem
wirklichen Ende von Original-FD und Archiv-IO frei.

176 betroffene Rows-/Runtime-/Transfer-/Index-Hostfälle bestehen, einschließlich
vier neuer Fälle mit tatsächlichem Original-Lese-FD, unabhängigem Archiv,
geschütztem Readback und passiver Wiederlesbarkeit nach Sitzungsschluss,
Original-/Zeilen-/Archiv-/Grant-/Index-/Cancellation-Negativen, gesperrter
Metadatenfabrikation, Duplikat-HOLD, Entzug nach Commit und blockiertem tatsächlich
offenem Provider-FD bis zu dessen nachgewiesenem Schließen. Originalbytes,
Publikation und Historie bleiben unverändert; keine Schreiböffnung, neue Zeile,
Saved-Ausgabe oder Grant-Verbrauch erfolgt. Mit fünf unveränderten früheren
Descriptor-Medienfällen sind es 181 unterschiedliche Hostfälle. Dies ist weiterhin
kein tatsächlicher Android-OS-/Provider-Abnahmenachweis oder R8-Nachweis.
Die folgende zusätzliche FD-Aufnahme deckt den frisch geöffneten schreibenden
FD ab; Schreibbeginn, vollständiger Postwrite-Readback sowie History-CAS sind
weiterhin nicht implementiert. Der normale PC-Nachfolger-HOLD bleibt bestehen.

### Notes: exklusiver nicht kürzender PC-Schreibziel-FD ohne Mutations-API

Nur derselbe lebende fertig gestagte Transfer mit exaktem Vorprüfeintrag kann
einen zusätzlichen geschlossenen nativen Schreibzielowner halten. Vor der
Öffnung werden Originalzeile, unabhängiges Recovery-Archiv, ursprünglicher
OS-Grant und Staging-Rohbytes erneut geprüft. Das Original wird ausschließlich
mit `rw` geöffnet, ausdrücklich nicht mit kürzendem `w` oder `rwt`. Die
tatsächlichen FD-Zugriffsflags müssen über F_GETFL/O_ACCMODE genau O_RDWR sein;
ein vom Provider trotz Modusanfrage nur lesend gelieferter FD genügt nicht.
Der vollständige native FD-Zeuge muss exakt mit der Vorprüfung übereinstimmen.
Rohhash, native Bildprüfung und anschließende Zeilen-/Archiv-/FD-Kontrolle
erfolgen erneut; gleiche Bytes einer anderen nativen Datei werden nicht als
Zielersatz akzeptiert.

Der Owner exportiert weder FD noch Stream oder write/truncate-Methode und wird
nicht an den Aufrufer herausgegeben. Er wird nur einmal im ursprünglichen
Transfer gehalten, verbraucht den Grant noch nicht und schreibt keine Bytes.
Parent-Cancellation beendet die Autorität sofort, schließt den gehaltenen
Schreibziel-FD aber erst nach dem wirklichen Ende aller noch aktiven
Receiver-/Observer-/Metadaten-IO. Erst danach wird der Drain veröffentlicht und
die IO-Bahn freigegeben. Ein bei der Öffnung noch blockierter Provider bleibt
ebenfalls bis zur tatsächlichen Rückkehr und dem FD-Schließen gezählt.

134 betroffene Rows-/Runtime-/Transfer-/Descriptor-Hostfälle bestehen; mit den
unveränderten 51 Indexfällen sind es 185 unterschiedliche Fälle. Vier neue
Fälle prüfen einen echten nicht kürzenden gehaltenen rw-FD und dessen Schließen,
abgewiesenen Read-only-FD, andere tatsächliche Inode trotz gleicher Rohbytes,
Entzug/Cancellation unmittelbar nach Öffnung, fehlende Vorprüfung sowie
tatsächlichen Drain bei blockierter rw-Öffnung und bei einem bereits gehaltenen
rw-FD mit gleichzeitig noch aktiver Staging-Lese-IO. Die FD-Flagabfragen werden
im Hostfixture explizit modelliert; fstat/lseek verwenden weiterhin die
vorhandenen tatsächlichen Host-Fixtureattribute. Das ist keine Android-OS-
Zugriffsflag-/Providerabnahme. Originalbytes, Publikation und Historie bleiben
unverändert; keine neuen Medienzeilen, Saved-Ausgaben oder Mutationen erfolgen.
Die folgende dauerhafte Vor-erster-Mutation-Transition ergänzt diesen Owner;
der eigentliche Writer mit Postwrite-/History-CAS sowie Runtime/UI-Anschluss
bleibt offen. Kein aktueller
R8-, Geräte-, Installations- oder Veröffentlichungsnachweis wird behauptet.

### Notes: dauerhafter Schreibbeginn-Fence vor jeder Byte-Mutation

Nur der bereits tatsächlich gehaltene ursprüngliche Schreibzielowner kann
einmalig den ursprünglichen OS-Grant verbrauchen und seinen exakten geschützten
Eintrag von `before_write` nach `write_started` überführen. Die gesamte
versiegelte Stage und der vollständige native Vorprüfzeuge bleiben dabei
unverändert erhalten. Die native Zielprüfung und volle ursprüngliche
Aktions-/Grant-/Control-/Intent-/Buch-/Fristprüfung erfolgen vor und nach der
genauen geschützten CAS samt Readback. Innerhalb der Indextransaktion werden
nur die exakten lokalen Owner-, Lane- und Cancellationzeugen geprüft, keine
Transportsperren. Unveränderliche lokal vorbereitete Vor-/Commit-/Nach-Snapshots
erlauben ausschließlich diese eine geplante Transition.

Ein direkter Indexaufruf ohne tatsächliche private Startaufnahme dieses
FD-Owners kann den Zustand nicht herstellen. Ein fremd verbrauchter oder
entzogener Grant und eine zweite Aufnahme bleiben HOLD. Ein sofort nach dem
dauerhaften Commit entzogener Owner hinterlässt `write_started`, aber keinen
fortsetzbaren Writer; der echte FD wird erst nach IO-Drain geschlossen. Neue
Zielaufnahme aus einem gespeicherten `write_started` ist ausdrücklich gesperrt.
Der persistierte Zustand ist eine irreversible Unsicherheitssperre vor der
ersten Byte-Mutation, weder Beleg für geschriebene Bytes noch Saved oder
Schreib-/Wiederaufnahmerechte. Es gibt weiterhin keine write/truncate-API.
Die bestehende geschützte Zeile wird per exakter CAS weitergeführt; kein
zusätzlicher Metadatentyp oder erhöhtes Source-/History-/Stagingbudget entsteht.

183 betroffene Rows-/Runtime-/Transfer-/Index-Hostfälle bestehen, mit den fünf
unveränderten Descriptor-Medienfällen insgesamt 188 unterschiedliche Fälle.
Drei neue Fälle prüfen den tatsächlichen gehaltenen rw-FD, exakt einmaligen
Grant-Verbrauch, vollständigen Zeugenerhalt und geschützten Start-Readback,
gesperrte direkte Journalfabrikation, Duplikate, fehlendes Ziel und
verbrauchte/entzogene Grants sowie sofortigen Entzug nach dauerhaftem Commit.
Offline lässt sich die erhaltene Beobachtung passiv wiederlesen, ohne daraus
Rechte zu gewinnen. Originalbytes, Publikation und Historie bleiben unverändert,
kein Saved oder sonstiger Abschluss wird erzeugt. Vor der künftig ersten
Byte-Mutation sind weiterhin Recovery-Archiv, Staging-Rohbytes und Ziel erneut
unter dem tatsächlichen Owner zu prüfen. Der folgende Kopierkern ergänzt die
rohe Mutation; dauerhafter Postwrite-/Providerabschluss und History-CAS fehlen.
Normaler PC-Nachfolger-HOLD, Runtime/UI-Gate, Android-Gerätepause sowie fehlende
Geräte-/Auslieferungsabnahme bleiben unverändert. Ein zusätzlicher tatsächlicher
Release-R8-Lauf für den Quellstand `3bc3454c` besteht. In seinem tatsächlichen
DEX sind alle 13 geprüften betroffenen nativen Owner-/Stage-/Journal-/Index-Lane-
Klassen nachgewiesen; umbenannte Journalmodelle werden über die tatsächliche
R8-Mappingdatei zugeordnet. Das sind Klassen, keine zusätzlichen Testfälle.
Es wurden keine neuen Keep-Regeln hinzugefügt und keine APK paketiert,
signiert oder installiert. Dieser DEX-Nachweis ersetzt keine native Geräte-
oder OS-Provider-Abnahme.

### Notes: tatsächliche rohe PC-Bild-Ersetzung ohne Abschlussbeleg

Der interne Kopierkern verlangt denselben tatsächlich gehaltenen rw-Zielowner,
seinen dauerhaft gespeicherten `write_started`-Fence und den genau dort
verbrauchten ursprünglichen Grant. Unmittelbar vor den ersten Bytes werden
Original-Rohhash und Native-Target, unabhängiges Recovery-Archiv sowie vollständige
Staging-Rohbytes erneut geprüft. Nur während dieser genau einmal aufgenommenen
eigenen Kopie dürfen erwartete Größe und Zeitstempel fortschreiten; Gerät/Inode,
Modus, Linkzahl und UID/GID bleiben unverändert gebunden. Die allgemeine
unveränderte Originalprüfung wird dadurch nicht abgeschwächt.

Die begrenzte Kopie liest ausschließlich den aktuellen entschlüsselnden
Stagingowner, niemals Netzwerkbytes oder beliebige Leser-Callbacks. Sie prüft
den streaming Rohhash, kürzt einen alten Dateischwanz explizit auf die neue
Größe, erzwingt die Ausgabe und liest das gesamte tatsächliche Ergebnis erneut
auf Rohhash, native Bildgrenzen/MIME und stabile Native-Target-Zeugen zurück.
Archiv und Stage werden nochmals geprüft. Alle duplizierten Schreib-FDs und
der gehaltene ursprüngliche rw-FD werden tatsächlich geschlossen, bevor eine
rohe lokale Bytebeobachtung zurückgegeben wird. Der Parent hält seine IO-Bahn
auch bei Abbruch bis zum wirklichen Ende aller IO und Descriptoren.

Der geschützte Zustand bleibt bewusst `write_started`. Eine rohe Bytebeobachtung
ist weder dauerhafter Postwrite-/History-Abschluss noch Provider-Publikation,
Saved, Quell-END oder Wiederaufnahmerecht. Fehler und Teilkopien behalten
Originalarchiv, Stage, bisherigen Publikationseintrag und Unsicherheits-Fence;
kein automatisches Wiederholen, Zurückschreiben oder Löschen findet statt.
Die folgende tatsächliche Providerprüfung nach asynchronem Close ergänzt den
Kopierkern; History-CAS und der normale Runtime/UI-Anschluss fehlen weiterhin.

136 betroffene Rows-/Runtime-/Transfer-Hostfälle bestehen. Mit unveränderten
51 Index- und fünf Descriptor-Medienfällen sind es 192 unterschiedliche Fälle.
Neue Fälle prüfen längeren und kürzeren Ersatz einschließlich echten
Tail-Truncate, vollständige Zielbytes und unveränderte alte Archivbytes,
Vorab-HOLD bei fehlendem Start/falschem Archiv/manipulierter Stage, zwei wirklich
offene Schreib-FDs während einer tatsächlichen Teilkopie bis zum Drain sowie
Manipulation nach Force ohne automatisches Restore. Der bisherige Robolectric-
Standard `dup(fd)` kopiert in eine andere temporäre Datei und ist dafür kein
Nachweis. Das registrierte Hostfixture öffnet stattdessen dieselbe tatsächliche
Inode mit erhaltenem Zugriffsmodus ohne Kürzung; ausdrücklich nicht modelliert
werden Androids Shared-Offset- und Reliable-Close-Syscallannahmen. Keine dieser
Hostprüfungen ersetzt die weiterhin pausierte Android-Geräteabnahme. Für diesen
neuen Kopierstand wird kein aktueller R8- oder Auslieferungsnachweis behauptet.

### Notes: kanonischer Provider-Readback und dauerhafter Postwrite-Zeuge

Nur der gleiche lebende ursprüngliche Targetowner und exakt seine tatsächlich
nach erfolgreichem rw-FD-Close erzeugte Raw-Ergebnisinstanz können den neuen
Inhalt kanonisch beim Provider zurücklesen. Kopierte oder gespeicherte
Ergebnisdaten, ein anderer Index oder eine neue Sitzung reichen nicht.
Transfer, native Kopie und Postwrite-Prüfung teilen denselben ursprünglichen
Deadlineowner mit unverändertem Monoton-/Wallclock- und Acceptance-Ende; gerade
ein kurzes neues Angebot wird innerhalb jeder nativen IO-Prüfung begrenzt,
nicht nur vor und nach dem gesamten Kopiervorgang. Keine neue Frist entsteht.

Die Prüfung beginnt erst nach tatsächlichem Close sämtlicher Schreib-FDs.
Alte Größen-/Revisionsmetadaten nach asynchronem Provider-Close erlauben nur
begrenztes Warten: höchstens 32 Warteintervalle von jeweils höchstens 100 ms,
zusätzlich immer innerhalb der verbleibenden ursprünglichen Angebots- und
OS-Aktionsfrist. Statische Zeilenidentität, Eigentümer, Namespace, Pfad, Name
und Medientyp müssen weiterhin exakt passen. Die tatsächliche neue Größe und
fortgeschrittene Providerrevision sind Voraussetzung zum Öffnen des kanonischen
Original-Lese-FDs. Dieser muss den tatsächlich geschriebenen vollständigen
Native-Target-Zeugen, Rohhash und native MIME/Bildgrenzen bestätigen; Assetoffset,
Dateitausch oder veränderte neue Bytes bleiben HOLD.

Der tatsächliche kanonische Lese-FD bleibt während der geschützten CAS und ihres
Readback offen. Nur die prüfende Rows-Instanz mit exaktem threadlokalem
Target-/Raw-Ergebnis-/Vorher-/Nachher-/gültigem Lese-FD-Besitz darf denselben
Journal-Datensatz nach `provider_verified` überführen. Innerhalb der Indexsperre
werden nur lokale Deadline-/Aktions-/Lane-/Cancellationzeugen geprüft, keine
Transportsperren. Vollständige alte Stage, Originalpublikation und alter nativer
Vorprüfzeuge bleiben unverändert erhalten; der neue Postwrite-Abschnitt bindet
genaue Providerzeile, neuen nativen FD-Zeugen, Größe und Rohhash. Es entsteht
kein zusätzlicher Metadatentyp oder erhöhtes History-/Stagingbudget.

`provider_verified` ist weder History-CAS, Saved noch Neustartrecht. Entzug
unmittelbar nach Commit erhält diesen Zeugen, verhindert aber den weiteren
Abschluss. Doppelte Aufnahme öffnet keinen weiteren Provider-FD. Passive
Offline-Lesbarkeit erteilt keine frühere Autorität. Abbruch während tatsächlicher
Readback-IO hält die gemeinsame IO-Bahn bis zum wirklichen FD-Ende.

192 betroffene Rows-/Runtime-/Transfer-/Index-Hostfälle bestehen, mit fünf
unveränderten Descriptor-Medienfällen 197 unterschiedliche Fälle. Neue Nachweise
verbinden echte rohe Ersetzung, tatsächlich geschlossenen rw-FD, verzögert
modellierte Providerrevision auch bei gleich großer Bildersetzung, tatsächlichen
kanonischen Native-Readback und geschützten Postwrite-Readback. Negative prüfen
kopierte Ergebnisinstanz, falschen Index, fremde Providerzeile, gleiche Bytes
einer anderen Inode, manipulierte Bytes und Cancellation mit wirklich offenem
Lese-FD. Dazu kommen strikte Postwrite-Dekodierung, fehlender threadlokaler
Prüfbesitz, Entzug nach dauerhaftem Commit, Duplikat-HOLD und passives Offline-
Wiederlesen. Die kurze Originalfrist darf bereits während der Vorprüfung
ablehnen oder nach dem ersten Chunk stoppen, niemals spätere Chunks nach
Fristende fertigstellen. Das ist keine Android-Provider-/Sharedoffset-/OS-
Einwilligungsabnahme. Die folgende History-CAS ergänzt den Postwrite-Zeugen;
endgültiger Saved-Abschluss und Runtime/UI-Ersetzungsanbindung fehlen weiterhin.
Normale Nachfolgersperre, Gerätepause und
Auslieferungsgates bleiben bestehen. Kein aktueller R8-Nachweis für diesen
neuen Postwrite-Code wird behauptet.

### Notes: atomare PC-Publikationshistorie unter demselben kanonischen FD

Nach der Postwrite-CAS bleibt derselbe tatsächliche kanonische Lese-FD bis zum
Historienabschluss offen. Ausschließlich der ursprüngliche lebende Stageowner
liefert Binding, Pairing-Epoche, Scope und Manifest der neuen Publikation; sie
bindet den tatsächlichen neuen Providerzeugen und den exakten alten
Publikationsfingerprint. Die alte Publikation wird niemals umgeschrieben oder
entfernt. Neue Publikation und der genaue `history_committed`-Journalzeuge werden
atomar im selben geschützten SQL-Commit und mit anschließendem Readback
gesichert. Vorhandene neue Publikationen werden auch bei gleichen Daten nicht
als fortsetzbare Aufnahme adoptiert. Direkte Metadatenaufrufe ohne den realen
threadlokalen Rows-/Target-/Raw-Ergebnis-/Lese-FD-Prüfbesitz genügen nicht.

Der Journalzeuge bewahrt vollständige Stage, alten nativen Vorprüfzeugen und
Postwrite-Abschnitt; seine neuen begrenzten Historyreferenzen müssen beim Lesen
exakt zu der separat erhaltenen neuen Publikation passen. Der native
Herkunfts-/Manifest-/Scope-/Rohhash-/Providerzeugen-Zusammenhang wird ebenfalls
geschützt nachgeprüft. Nach beiden Commitpunkten wird vor Rückgabe nochmals der
tatsächliche FD samt Providerzeile geprüft. Ein danach entzogener Owner erhält
alle dauerhaft gesicherten alten und neuen Fakten, aber keine frühere
Abschlussautorität zurück.

Schon vor Grant-Verbrauch und erster Byte-Mutation wird Platz für die neue
Publikation verlangt: unveränderte Gesamt-Incominggrenze und höchstens 128
Publikationsfakten je opaker PC-Quelle, vollständige Vorgängerbezüge, keine
Forks und genau der ausgewählte aktuelle Head. Volle Historie bedeutet HOLD,
niemals Verdrängen oder Anheben der Grenze. Ein reines Bytebudget mit maximalen
zukünftigen Zahlenbreiten prüft außerdem vor Mutation die unveränderte
8192-Byte-Metadatengrenze einschließlich Framing und Verschlüsselung. Diese
Größenberechnung ist ausdrücklich kein erzeugter oder gespeicherter nativer
Dateizeuge. Abgeschlossene Absichten bleiben als Fakten erhalten; nur noch
offene oder unklare Absichten derselben Herkunft verhindern eine neue Absicht.
Die normale neue Aufnahme bleibt weiterhin gesperrt.

194 unterschiedliche betroffene Rows-/Runtime-/Transfer-/Index-Hostfälle sind
nachgewiesen, mit fünf unveränderten Descriptor-Medienfällen 199 Fälle. Der
breite Lauf bestand 193 Fälle; eine zu enge Annahme des Zweisekunden-Fixtures,
dass die native Vorprüfung stets vor Angebotsende fertig sei, wurde korrigiert
und der einzelne geänderte Fall danach bestanden. Kein Produkt-/Angebots-TTL
wurde verlängert: sichere Nullbyte-Ablehnung während der Vorprüfung und Stop
nach einem Chunk sind erlaubt, spätere Chunks nach Fristende nicht. Unveränderte
bestandene Fälle wurden dafür nicht wiederholt. Neue Historiennachweise prüfen
beide tatsächlichen Publikationen, unveränderten alten Inhalt im unabhängigen
Archiv, Headwechsel ohne Fork, passiven Offline-Readback, Entzug nach atomarem
Commit ohne Saved sowie volle 128er-Quellhistorie mit Nullbyte-HOLD vor
Grant-Verbrauch. Der Kapazitätsfall verwendet synthetische geschützte
Historienmetadaten, keine 128 tatsächlichen nativen Ersetzungen.

`history_committed` bleibt historische Evidenz, kein Neustartrecht, tatsächlicher
Quell-END oder automatisch ausgegebener Saved-Beleg. Dessen tatsächliche
ursprünglich gebundene Ausgabe wird im folgenden Abschnitt ergänzt; der
Runtime/UI-Ersetzungsablauf fehlt weiterhin. Android-Gerätepause und alle Feature-/Auslieferungsgates bleiben
unverändert; kein aktueller R8- oder physischer Providerabnahmenachweis für
diesen neuen Code wird behauptet.

### Notes: tatsächliche Saved-Ausgabe nach geschlossenem kanonischem FD

Der ursprüngliche Transfer übernimmt seine Abschlussinstanz ausschließlich
privat nach tatsächlicher Rückkehr der nativen Rows-Prüfung. Zu diesem Zeitpunkt
ist deren kanonischer Lese-FD wirklich geschlossen; beide Publikationen und
der atomare Historienzeuge müssen exakt geschützt zurücklesbar sein. Ein vom
Aufrufer geliefertes Ergebnis-JSON, rohe Kopie oder `history_committed` allein
genügen nicht zur Ausgabe.

Genau ein Ausgabeversuch erzeugt das vorhandene Saved-Wireformat aus dem
ursprünglichen Manifest, Acceptance, Permission-Epoche und Destination-Token;
der Receipt bindet den tatsächlich neuen Publikationsfingerprint. Ursprüngliche
Frist, authentifizierter Kanal, Control-Sitzung, voller Intent und Buch bleiben
vor und nach tatsächlichem `channel.send` sowie Historien-Readback erforderlich.
Erst danach wird das tatsächliche Ausgabeereignis intern festgehalten.
Native URIs/Pfade werden nicht übertragen. Dieses historische Ausgabeereignis
ist kein Peer-ACK, Quell-END, Cleanup-, Wiederaufnahme- oder weiterer Schreibgrant.

Fehlgeschlagene Ausgabe oder nachträglich entzogener Owner behalten neue Bytes,
alte und neue Publikation, Archiv, Stage und Journal. Selbst wenn ein
Ausgabecallback bereits verschlüsselte Bytes beobachtet hat, darf sein später
entzogener Owner keinen internen Abschluss oder neue Autorität daraus gewinnen.
Eine blockierte verschlüsselte Ausgabe hält die IO-Bahn trotz schon geschlossener
Datei-FDs bis zu ihrem tatsächlichen Rücklauf. Cancellation allein ist kein Drain.

147 betroffene Rows-/Runtime-/Transfer-Hostfälle bestehen; mit unveränderten
51 Index- und fünf Descriptor-Medienfällen sind es 203 unterschiedliche Fälle.
Vier neue Fälle verbinden tatsächliche rohe Bildersetzung, native kanonische
Prüfung, beide Historienfakten, echte FD-Closes und anschließend echte AEAD-
Saved-Ausgabe mit dem exakt neuen Receipt. Weitere Nachweise prüfen fehlenden
eigenen Abschluss, Failed Send, Grant-/Buch-/Control-Entzug und Entzug während
eines schon beobachtbaren Ausgabeereignisses, Duplikatverhinderung sowie
blockierten SecureChannel-Send bis zum tatsächlichen IO-Ende. Alle dauerhaften
Fakten bleiben erhalten. Dies ist weiterhin ein intern geprüfter Einzelbildpfad,
kein fertig angebundener Runtime/UI- oder vollständiger Foto-/Videoablauf.
Die tatsächliche Android-Geräteabnahme bleibt pausiert; bestehende Feature-
und Auslieferungsgates bleiben bestehen. Kein aktueller R8-/Installations-
oder Veröffentlichungsnachweis für diesen neuen Ausgabecode wird behauptet.

### Notes: ursprünglicher PC-Ersetzungsablauf im nativen Dispatcher und OS-UI

Authentifizierte PC-Nachfolgerangebote werden jetzt getrennt von der gewöhnlichen
Neuaufnahme klassifiziert. Nur der bestehende Connectionowner darf den vorhandenen
resumierten Activityhost erreichen. Kein Paket erzeugt daraus einen neuen Intent,
Buchpermit, Kanal oder Grant. Die normale Nachfolgersperre der Neuaufnahme bleibt
bestehen. Ein weiteres solches UI-Angebot kann den bereits gehaltenen Auftrag
nicht überschreiben; Chunks gehen ohne die Operation-Gate-Sperre direkt an den
exakten aktiven Worker, der auf diese authentifizierten Bytes wartet.

Vor dem Einreihen der Archivprüfung wird die ursprüngliche native Aufnahme mit
ihrem ursprünglichen Aktionsclock, vollständigen Intent, aktuellen Controlowner,
gespeicherten entsperrten Buch und eingeschaltetem Recovery-Schutz festgehalten.
Die kurze Vorbereitungs-Lane wird vor Start der tatsächlichen nativen Lese-IO
freigegeben; der Pendingowner schließt konkurrierende Aufnahmen weiterhin aus.
Recovery-Speicher öffnet erst im tatsächlichen Original-Prüfabschluss. Erst die
dort erzeugte ursprüngliche OS-Anfrage darf der echte ActivityResult-Host starten.
PC-Schreibdialog und bisherige Foto-/Video-Lese-/Schreibdialoge schließen sich
gegenseitig aus; ein alter ausstehender Callback behält seinen Slot.

Die Pause durch diesen eigenen OS-Dialog ist beabsichtigt und widerruft nicht
seine noch unvollständige Anfrage. Eine positive Antwort allein genügt weiterhin
nicht: Bis zur echten Activity-Resume darf kein Schreib-FD geöffnet werden.
Jeder andere Vordergrundverlust, Abbruch, fremde oder späte Ownerwechsel bleibt
widerrufbar. Ein abgebrochener Dialog kann durch seine spätere positive Antwort
keine Aufnahme oder Mutation nachliefern.

Der typisierte PC-Worker hält die gemeinsame native Lane schon vor Vorschlag
und Staging. Sein Transfer leiht exakt diesen Owner, nicht eine zwischenzeitlich
freigegebene oder neu erworbene Lane. Staging, native Kopie, kanonischer Readback,
Historien-CAS und tatsächliche Saved-Ausgabe folgen unter den unveränderten
Originalzeugen. Auch bei Cancellation bleibt die Lane bis zum tatsächlichen
Ende sämtlicher Receiver-, Observer-, Ausgabe-IO und des wieder geöffneten
Recovery-Archivs gehalten. Runtime-Close und Policyentzug berücksichtigen diesen
Worker und die Pendingvorbereitung; Abbruch ist kein Quell-END.

Nur der ursprüngliche erfolgreich ausgegebene Run darf anschließend genau einmal
den tatsächlichen Published-Readback an derselben Connection, demselben vollen
Intent, Controlowner, Buch und ursprünglichen Angebot beginnen. Der neue Receipt
muss exakt zur geschützten neuen Publikation passen. Historische PC-Versionen
bleiben erhalten; aktuelle Archiv-/Ersetzungsauswahl verwendet ausschließlich
den geschützten eindeutigen Head einer vollständigen nicht verzweigten Herkunft.

211 betroffene Hostfälle bestehen: Rows91, Runtime53, Transfer9, Index51 und
PermissionHost7. Mit fünf unveränderten Descriptor-Medienfällen sind dies 216
unterschiedliche Fälle. Der vollständige UI-Fall wurde zusätzlich zum normalen
authentifizierten Dispatcher und passiven Foregroundhost erweitert und danach
einzeln erneut bestanden; unveränderte Fälle wurden dafür nicht wiederholt.
Nachgewiesen sind der tatsächliche Runtime-/Connection-/ActivityResult-/Worker-
Saved-/Readback-Pfad, PC SEND ohne PC RECEIVE oder Telefon READ, kein Schreiben
zwischen positiver OS-Antwort und echter Resume, Pending-/Abbruch-/Late-Callback-
HOLD, mutualer Berechtigungsslot und blockierte echte verschlüsselte Ausgabe bis
zum Runtime- und Coroutine-Drain. Der dabei entdeckte Plattformverzeichnisfehler
wurde in #485 separat behoben und geprüft: Plattformrechte bleiben unverändert,
alle selbst verwalteten Stagingverzeichnisse bleiben privat und inodegebunden.

Die Oberfläche ist damit nativ angeschlossen, aber nur für ein Bild je
ursprünglichem Angebot hostgeprüft. Mehrdatei- und Videoersetzungsangebote werden
nicht still geteilt oder freigeschaltet. Ganze Sammlung, automatische
Angebotskomposition, native PC-Auswahl und verbleibende Lösch-/Recovery-/Retention-
Abnahmen sind kein Ergebnis dieser Tests. Android-Gerätepause, Capability- und
Auslieferungsgates bestehen weiterhin; daraus folgt keine Installation oder
vollständige Foto-/Video-Abnahme und keine fertige OBS-/Spiegelungsfunktion.

Der angeschlossene Produktstand `26872c6c` besteht außerdem den tatsächlichen
Release-R8-Lauf; 20 erforderliche Klassen einschließlich Dispatcher, Worker,
Activityhost-Anbindung, nativer Kopie und Historienzeugen sind über tatsächliche
DEX-Deskriptoren und R8-Mapping nachgewiesen. Das ist kein zusätzlicher Hostfall,
kein gepacktes APK und keine Geräte-/Installationsabnahme. Der präzise offene
Gesamtrest aus #429 wird in #486 fortgesetzt; bestehende Gates bleiben bestehen.

### Linux: frische PC-Nachfolger aus tatsächlich abgeschlossener Sourcehistorie

Der explizite native Connectionpfad aus #487 kann jetzt die gleiche tatsächliche
PC-Datei nach einem abgeschlossenen Lauf frisch erneut aufnehmen. Die gewöhnliche
erstmalige Aufnahme hält bekannte Herkunft weiterhin. Der neue Pfad verlangt
erneut eigenen nativen Action-, Root-/Member-, Buch-, Intent- und positiven
SEND-Controlbesitz; frühere Jobs, Saved oder Historienflags erteilen keine neuen
Lese- oder Schreibrechte. Android prüft seine ursprünglichen OS-Rechte unabhängig.

Die genaue bestehende geschützte Sourcechronologie bestimmt den Vorgänger,
niemals UUID-, SQLite- oder Katalogreihenfolge. Root-/Dateigeneration und Pfad der
Herkunft müssen exakt erhalten bleiben. Neue Inode am alten Pfad oder dieselbe
Datei unter anderer Herkunft bleiben HOLD. Aus der vollständig abgeglichenen
Saved-/Published-Readback-/Retirementkette wird genau der vorherige
Receiver-Publikationsfingerprint korreliert. Ein begrenzter expliziter
Rückwärtslauf bindet frühere Job-, Ready- und Retirementhashes; rekursive
Vorgängerprüfung trägt denselben begrenzten Zykluszeugen, statt die gesamte
Chronologie aus ihrem eigenen Exchangevalidator erneut aufzurufen.

Vor neuem Cache/Job werden aktuelle vollständig gelesene Native-Rohbytes geprüft.
Gleiche Größe oder ein alter Rohhash allein sind kein Unverändertnachweis. Die
vorherigen tatsächlichen verschlüsselten Sourcearchive und ihr vollständiger
Slotbestand werden ebenfalls unabhängig geprüft. Nur nach vollem frischen
Rohhash darf unveränderter Inhalt ohne neuen Cache, Job oder Angebot halten.
Der ursprüngliche geschützte Katalogstand wird nach dieser IO erneut geprüft;
eine nachträglich fortgeschriebene Historie darf auch keinen alten
Unverändertentscheid nachliefern.

Geänderte Rohbytes erhalten einen neuen tatsächlichen Cache, ein neues Manifest,
Transfer- und Source-ID sowie die unveränderte opake PC-Herkunft mit genauem
vorherigem Publikationsfingerprint. Der ursprüngliche Vorgänger/Katalogstand wird
vor Cacheanlage und erneut innerhalb der Job-Plantransaktion gebunden. Wire-
Erzeugung und Retirementvalidator leiten ihre frühere Publikation aus genau
dieser geschützten Jobchronologie ab, nicht aus einem caller- oder wiregelieferten
Flag. Es entstehen kein neues Recordformat, Quotenlimit oder ersetzter alter
Datensatz; die vorhandene 128er-Sourcegrenze und alle alten Jobs, Exchanges,
Retirements und unabhängigen Backupversionen bleiben bestehen.

56 unterschiedliche betroffene Linux-Hostfälle bestehen in begrenzten seriellen
Gruppen: PC-Connection12, PC-Source14, Chronologie10 und Buildkomposition20.
Der neue tatsächliche AEAD-Connectionfall umfasst erstes SEND/Saved/Readback/
Backup/Quell-END, einen frisch geänderten vollständig abgeschlossenen Nachfolger
und ein drittes echtes Angebot mit genau dem zweiten Publikationsfingerprint.
Dieses dritte Angebot ist ausdrücklich noch kein dritter Abschluss. Native
Dateien und alle früheren Fakten bleiben erhalten, native Pfade/IDs fehlen im
Wire, Telefonreferenzen werden nicht erfunden und PC RECEIVE/Telefon READ sind
keine zusätzlichen SEND-Voraussetzungen. Neue negative prüfen fehlenden oder
ausstehenden Abschluss, neue Inode am alten Pfad, fehlendes tatsächliches
Archiv, Entzug während des frischen vollständigen Native-Hashens sowie
Katalogfortschreibung nach Admission ohne neue Cache-/Jobaufnahme.

Diese Fälle verwenden authentifizierte modellierte Peerantworten, keine neue
Android-Geräteabnahme. Der Windows-Nachfolgerpfad besteht separat; daraus folgt
keine übertragene native Windows-Prüfung. Auswahloberfläche, ganze Sammlung und
automatische Komposition sowie Video-/Mehrdateiersetzung werden unter #486
weiterbearbeitet. Keine Capability- oder Lieferfreigabe wird daraus abgeleitet.

### Linux: ursprüngliche native Auswahl separater PC-Quellordner (#488, Teilstand)

Die Linux-Oberfläche kann ausdrücklich PC-Quellordner für Bilder oder Videos
hinzufügen und die geschützte Auswahl lesen. Diese Ordner sind keine
Empfangsziele. Die Aktion startet weder Inventur noch Dateilesen oder Transfer
und erteilt keine SEND-/RECEIVE-Rechte. Ein Datenfreigabe-ACK der Gegenseite ist
für diese Konfiguration nicht erforderlich; ursprüngliche authentifizierte
Metadaten, passende gesamte-Sammlungsrichtung und gespeichertes entsperrtes Buch
bleiben erforderlich. Hinzufügen verlangt die separate lokale Sendezustimmung.

Der Renderer wartet auf den tatsächlichen Speicher-ACK und übergibt nur
Medientyp, Aktionsart und Versions-/Requestkorrelation, niemals Pfad oder
Bestätigungsflag. Der native Auftrag bindet ursprünglichen vollständigen Intent,
Controlkontext, Buch, Preferences und eine nicht erneuerbare Frist. Nur der echte
GTK-Ordnerdialog liefert den Pfad; sein Besitzer hält den tatsächlichen
Verzeichnis-FD über die private Unix-RPC bis zur serverseitigen Prüfung des
exakten Native-Zeugen. Vor der Ergebnisantwort wird dieser FD geschlossen.
Kontextwechsel, spätes Ergebnis und Abbruch erneuern keine Auswahlbefugnis.
Cancellation widerruft auch neben belegter IO-Gate sofort; ein bereits
committender Owner behält seinen Slot bis zum tatsächlichen IO-Ende.

Registrierung bleibt append-only unter dem bisherigen geschützten Rootkatalog.
Nur tatsächlich fehlender Speicher darf erstmals gebunden werden; unbekannter
ungebundener Bestand wird nicht übernommen. Bestehende Grantfelder bleiben
unverändert. Reines Lesen fehlender Konfiguration erzeugt keinen Katalog oder
Sourceowner. UI-Pfade stehen ausschließlich im Tooltip, nicht im sichtbaren
Text oder editierbaren Pfadfeld. Import-only/Empfangsrichtung bieten keine
Exportauswahl; aktive native Dialoge schließen sich gegenseitig aus.

Hostnachweise dieses Teilstands: neun API-Fälle, 13 native Handler-/private-IPC-
Fälle, zehn gezielte Linux-Frontendfälle sowie 22 bestehende native UI-Fälle
und der vollständige Linux-UI-Regressionslauf bestanden. Der echte GTK-Dialog
wird in den Handlerproben modelliert; eine installierte native Dialogabnahme
wird nicht behauptet. Dieser Linux-Teilnachweis umfasst noch nicht die separate
Windows-Integration in `phone-media.js`/`DeviceFileBridge.cs`; deren anschließender
Implementierungs- und Prüfstand steht im folgenden Abschnitt. Der echte Sammlungslauf,
automatische Exportkomposition, Video-/Mehrdateiersetzung und alle übrigen
Geräte-/Liefergates bleiben offen. #488 und #486 sind nicht abgeschlossen.

### Windows: eigene native PC-Quellordnerauswahl (#488, weiterer Teilstand)

Windows besitzt jetzt seinen eigenen strikten `pick_collection_source`-Pfad in
`phone-media.js` und der tatsächlichen WinForms-Bridge. Erst der echte native
FolderBrowserDialog liefert einen gehaltenen read-only Verzeichnisowner; keine
Rendererpfade, Bestätigungsbits, Native-IDs oder Empfangsziele werden übernommen.
Source-, Empfangs- und Zustimmungsdialoge teilen einen nativen Dialogslot.

Vor dem Dialog werden ursprüngliche Connection, gespeichertes Buch, voller
gemeinsamer Intent, lokale Zustimmungen/Preferences, Rootkatalog und ursprüngliche
Controlposition gebunden. Die Frist läuft vom Eintritt, nicht erst nach einer
späteren Vorbereitung. Der Katalog-CAS prüft innerhalb seiner bestehenden
Transaktion nochmals genau den ursprünglichen Rootbestand. Neue Registrierungen
bleiben append-only; gleiche bestehende Auswahl wird nicht ersetzt. Ausgewählte
Native-Owner schließen vor der Antwort, auch bei Abbruch oder fehlendem Kontext.

Die Controlpositionsprüfung ist absichtlich nur ein lokaler unveränderter
Positionsvergleich, weder Scopecallback noch Datenfreigabe. Unter geschütztem
Store-CAS wird kein Transportmonitor oder callbackfähiger Control-Scope betreten.
Native Metadaten, Connection, Buch, voller Intent und lokale Rechte werden davon
unabhängig frisch geprüft. Sowohl PC RECEIVE als auch Telefon READ/RECEIVE dürfen
für reine Quellkonfiguration geschlossen sein; daraus entsteht kein SEND-Binding.

Der Renderer wartet auf den tatsächlichen Speicherabschluss und prüft danach
denselben Buchowner, dieselbe angeschlossene Panelinstanz und die ursprüngliche
Connection-/Vollintentversion. Ein verspäteter Speicherabschluss kann keinen
anderen Buchstand übernehmen. Import-only, reine Empfangsrichtung, OFF, fehlende
Metadatenechos, lokale Sendeverweigerung oder fehlende Native-Version halten die
Auswahl geschlossen. Statuslesen inventarisiert keine Dateien und startet keine
Übertragung; Pfade erscheinen nur im Tooltip, Vorschaubilder bleiben aus.

Sechs unterschiedliche native Windows-Testgruppen bestehen über den vorhandenen
Windows-Prüfweg: zwei neue Auswahlgruppen (14 Szenarien), zwei Rootpersistenz- und
Tampergruppen, strikte Requestgrammatik und bestehender Zustimmungsdialog. Die
zwei neuen Gruppen wurden nach Erweiterung/ursprünglicher Fristprüfung erneut
gezielt bestanden; kein doppeltes Zählen. Der reine Control-/Positionsfall besteht
zusätzlich im Hosttest. 13 gezielte Windows-Frontendfälle, bestehende Medien-UI,
Telefon-Einstellungen und 53 Windows-State-Regressionen bestehen. Aktuelle Core-
und echte WinForms-Produktquelle kompilieren ohne Warnungen/Fehler. Native
Verzeichnis-/DPAPI-/Katalogbesitzer sind tatsächlich unter Windows geprüft; die
Dialogantwort selbst wird im Test über den nativen Callback modelliert. Keine
installierte interaktive Dialog- oder Gesamtproduktabnahme wird daraus abgeleitet.

Der eigentliche gesamte-Sammlung-Lauf und automatische Angebotskomposition samt
Archiv-/Quell-END zwischen Dateien fehlen weiterhin. #488 bleibt dafür offen;
Video-/Mehrdatei- und Android-/Auslieferungsgates bleiben unverändert.

### Linux: unveränderte native Peerprojektion ohne Verlust frischer IO (#489)

Der erweiterte Linux-Sammlungstest traf zunächst beim geänderten Folgeexport auf
die ursprüngliche Aktionsfrist. Eine gezielte Messung zeigte unter anderem
23.772 vollständige native Peerprojektionen und mehr als 55 Millionen
Funktionsaufrufe bereits in einem rund 30-sekündigen Ausschnitt. Wiederholte
Historienprüfung war zunächst eine Hypothese, nicht der nachgewiesene Fix.

Der gebundene native Authorityowner darf jetzt ausschließlich die deterministische
immutable Projektion exakt gleicher authentifiziert entschlüsselter Peerbytes
wiederverwenden. Jeder Aufruf liest weiterhin den tatsächlichen Peer-FD und den
Originalschlüssel, prüft Ancestor-/Key-/Link-/Mode-/Namenszeugen, entschlüsselt
wirklich und prüft die native Bindung vor und nach dieser IO. Geänderte Bytes
werden neu geparst; Fehler, Revocation und Kanal-/Pairingwechsel verwerfen den
Owner samt Projektion endgültig. Bereits geparste Daten sind kein Ready-, SEND-,
READ-, RECEIVE-, Saved- oder Source-END-Nachweis. Die eigenständigen aktuellen
Grant-, Buch-, Intent-, Native-Datei- und Historienprüfungen bleiben unverändert.

59 betroffene Hostfälle bestehen einschließlich warmer Projektion bei fehlendem,
korruptem, unsicherem oder während tatsächlicher Entschlüsselung ausgetauschtem
Peerbestand, fehlendem/erneuertem Schlüssel und nicht wiederbelebbarer alter
Bindung. Die erweiterte tatsächliche Sammlungskette besteht mit unveränderten
Originalfristen; weder Zeitlimit noch Quote, Recordformat oder Historiengrenze
wurde erhöht. Dies ist ein Linux-Projektions-/Hostnachweis, keine übertragene
Windows-Korrektur oder physische Android-/Lieferabnahme.

### Linux: tatsächlicher begrenzter Lauf expliziter Sammlungsquellen (#488)

Der bisher nur gemappte Sourceworker verbindet im gesamten-Sammlungsmodus jetzt
auch die ausdrücklich geschützten PC-Quellordner. Vor dem gemappten Teil werden
Originalkatalog, echte Root-FDs, aktuelle Native-Member und ihre vollständigen
Native-Statzeugen eingefroren. Ohne ausdrücklich gewählten Root des aktuellen
Medientyps oder bei unvollständiger/unklarer Inventur hält der Lauf vor einem
gemappten Teilerfolg. Inventur bleibt begrenzt: höchstens 4096 Dateien insgesamt,
zusätzlich vorhandene Entry-/Tiefen-/Rootgrenzen. Es gibt keinen beliebigen
PC-Scan oder implizit neu ausgewählte Quellen.

Nur der tatsächlich aktive typisierte Worker und sein exaktes ursprüngliches
Root-/Memberobjekt dürfen eine PC-Aufnahme neben diesem eigenen Workerslot
einreihen. Gleiche kopierte Metadaten oder ein fremder Worker genügen nicht.
Jede Datei wird vor Admission als eigenes echtes Einzeldateiangebot vorbereitet;
aufgenommene Mehrdateiangebote werden nicht nachträglich geteilt. Gewöhnliche
bekannte Herkunft hält weiterhin; nur der explizite abgeschlossene Nachfolgerpfad
aus #487 darf den geschützten Vorgänger und seine genaue Publikation übernehmen.
Unverändert bedeutet vollständiger frischer Native-Rohhash, nicht Dateiendung,
Größe oder alter Flag. Liegt eine tatsächlich im gemappten Teil bereits vollständig
geprüfte Datei auch im ausgewählten Root, wird nur ihre unveränderte tatsächliche
Native-Signatur mit der eingefrorenen Inventur korreliert: kein zweites Angebot,
keine PC-Neuetikettierung und kein doppeltes Zählen. Der zugehörige Beobachter
wird ausschließlich im ursprünglichen Worker nach echtem Vergleich bzw. geändertem
Transfer mit Backup/END notiert; er ist kein READ-/Schreib-/Publikationsgrant.
Unklare oder nur historisch zugeordnete Kandidaten ohne diesen tatsächlichen
Vergleichszeugen halten weiterhin.

Vor dem nächsten Angebot folgen jeweils tatsächlicher Saved-/Published-Readback,
unabhängiges Rohbackup und ursprüngliches natives/socketgebundenes Quell-END.
Backup und Retirement verwenden den tatsächlichen Sender-Sourceowner, auch bei
PC- statt Mappingquellen. Der bisherige begrenzte Cache-Slot darf erst nach echtem
Archivieren/END mit einem neuen Native-Inode verwendet werden; sein gleicher
Pfad ist keine Wiederaufnahme des alten Jobs. Alle ursprünglichen Archive,
Versionen und die 128er-Sourcegrenze bleiben erhalten.

Vor Abschluss werden gesamter Rootkatalog, sämtliche ursprünglichen Member und
ihre vollständigen Native-Signaturen erneut geprüft. Eine gleich große Änderung
nach einem bereits abgeschlossenen Einzelschritt macht den Gesamtpass HOLD;
die tatsächliche Einzelquittierung wird weder geleugnet noch als Gesamtabschluss
ausgegeben. Lokaler Sendeentzug wird schon während der Inventur frisch geprüft.
Nur-Fotos prüft tatsächliche Kamerametadaten in gemapptem und unabhängigem Teil;
absichtlich ausgeschlossene Dateien zählen als gefiltert, niemals als bekannte
Publikation. Abbruch und Cleanupfehler behalten ihren HOLD-Status und geben den
Workerslot erst nach tatsächlichem Root-/Katalog-/IO-Drain frei.

99 unterschiedliche betroffene Python-Hostfälle bestehen: 14 neue Collection-
Fälle, 26 bestehende Worker-/Service-/Wifi-/Stop-/Close-/Buch-/Controlfälle und
59 Authorityfälle aus #489. Der positive Collectionfall beginnt am tatsächlichen
PhoneService-`sync_shared`-Einstieg mit ursprünglichem Desktop-Buchfence. Er
schließt zwei native PC-Originale nacheinander vollständig ab, liest beide in
einem weiteren Lauf unverändert und sendet anschließend eine echte Änderung
derselben Native-Generation mit exakter Vorpublikation bis zu eigenem Backup/END.
Drei echte geschützte Archive und alle älteren Jobfakten bleiben erhalten;
PC RECEIVE und Telefon READ bleiben aus. Die Peerantworten sind authentifizierte
Hostmodelle, keine neue Android-Abnahme.

Das ist ein begrenzter Inhaltspass der expliziten Quellen, kein Lösch-, Retention-
oder globaler Bestandsvollständigkeitsnachweis. Zum Zeitpunkt dieses Linux-
Teilstands hielt Windows den gesamten-Sammlungsrest noch zur Prüfung; der
anschließende Produzentenstand folgt unten. Der offene Rest aus #488 wird gemäß
Teilabschlussregel in #491 weitergeführt; Androidpause, Video-/Mehrdatei- und
Liefergates unter #486 bleiben bestehen.

Automatischer gesamter PC-Export bleibt ausdrücklich vor Inventur und Aufnahme
gesperrt, bis die dafür offene native Abnahme vorliegt. Weder der manuelle
Hostlauf noch aktivierte gemeinsame Wifi-Einstellungen öffnen dieses Gate.
Die zusätzliche optionale Buildkomposition besteht in allen 20 Variantenfällen;
die dabei bestätigten GUI-Imports ohne Fotomodul wurden separat in #490 behoben.

### Windows: begrenzter manueller Sammlungsproduzent (#491, Fortsetzung #488)

Die native Windows-Ordnerauswahl ist jetzt an den gemeinsamen Produzenten
angeschlossen. Der Coordinator übergibt ausdrücklich manuell/automatisch;
automatischer gesamte-Sammlung-Export hält vor jeder Inventur. Ein Aufruf ohne
expliziten manuellen Parameter öffnet dieses Gate nicht. Originales Buch, voller
Intent, Connection/Control-Binding und lokale Sendezustimmung bleiben für den
gesamten manuellen Lauf gebunden. Weder PC RECEIVE noch Telefon READ werden
daraus erzeugt oder vorausgesetzt.

Vor dem gemappten Teil hält ein privater Passowner ausdrücklich ausgewählte
Root-FDs, originale Member/Elternketten und echte Dateisignaturen. Native Identität,
Größe, Creation-, LastWrite-, Change-Zeit und Attribute werden an tatsächlichen
Dateihandles verglichen; Zugriffszeit ist wegen eigener Reads kein Inhaltszeuge.
Fehlender Root, zweifelhafte Inventur, mehrdeutige Identität oder Überschreiten
bestehender Grenzen hält. Keine neue Schema-, Quoten- oder Historienfreigabe.

Jede unabhängige Quelldatei verwendet den tatsächlichen Sourceowner und den
vorhandenen vollständigen Freeze-/Nachfolgerpfad. Erst echter Saved/Readback,
unabhängiges Rohbackup und tatsächliches Source-END erlauben das nächste Angebot.
Der ursprüngliche Katalog wird an Dateiübergängen und abschließend frisch
verglichen; die Source prüft ihren ausgewählten Root und ihre eigenen nativen
Dateizeugen unabhängig bei IO. Ein angehängter Root während einer Datei erteilt
dieser Datei keine neue Autorität und macht den Gesamtpass nicht vollständig.
Zum Schluss werden ganze Inventur, Elterngenerationen und alle Inhaltspositionen
erneut geprüft. Späte gleiche-Größe-Edits und neue Dateien nach echtem Einzel-END
halten den Gesamtpass, ohne die tatsächliche Einzelhistorie zu verwerfen.

Elf unterschiedliche native Windows-Testgruppen bestehen: vier neue
Produzentengruppen (zwei Originale mit echtem END vor nächstem Angebot und frischem
Unverändertlauf; echte geänderte Nachfolge mit genauer Vorpublikation; sieben
Automatik-/Root-/Katalog-/Inhalts-/Buch-/Consent-/Controlguards; zwei späte
Inventuränderungen nach echtem END) sowie sieben betroffene Inventur-, Mapping-
und bestehende Collection-Sourcegruppen. Aktuelle Core- und tatsächliche
WinForms-Produktquelle bauen ohne Warnungen/Fehler. Nur die äußere Verwaltung
der mehrteiligen Testgruppe wurde an ihre Gesamtdauer angepasst; jeder tatsächliche
Sender behält unverändert seine ursprüngliche 60-Sekunden-Frist.

Der Produzentenaufruf ist echt, die authentifizierten Telefonantworten sind
Hostmodelle. Kein neuer interaktiver Installations- oder Android-Abnahmenachweis.
Unklare bzw. bereits gemappte Member unter expliziten Roots werden noch nicht
als neue PC-Quelle umetikettiert: diese Überlappung und gemischte Typen bleiben
konservativ HOLD und benötigen weitere Arbeit. #491/#486 sowie Androidpause,
automatischer Export, Capability23 und Video-/Mehrdatei-/Liefergates bleiben offen.

### Windows: tatsächliche Mappingbeobachtung in ausgewählten Roots (#492)

Der zuvor nativ reproduzierte HOLD `media_collection_existing_mapping_required`
bei bereits im selben Pass vollständig gelesenen gemappten Dateien ist für genau
diesen belegten Fall behoben. Die tatsächliche Mappingquelle hält nach vollständigem
Rohhash einen unveränderlichen nativen Inhaltspositionszeugen. Anfang und Ende
dieser Lesung müssen dieselbe Identität, Größe und native Inhaltsposition besitzen.
Nur der private ursprüngliche Passowner, derselbe Store/Peer/Connectionowner und
die in genau diesem Pass tatsächlich lebend aufgenommene, anschließend vollständig
vorbereitete Source dürfen den Beobachter genau einmal korrelieren. Ein alter
vorbereiteter Sourceowner aus einem vorherigen Pass genügt nicht.

Notiert wird er erst nach echtem Unverändertvergleich, vollständigem aktuellem
Nachfolgerhash oder – bei tatsächlich übertragenen Änderungen – nach dem echten
Backup-/Quell-END. Beim späteren Rootmitglied müssen aktuelle Native-Position und
ursprünglich eingefrorener Inventurzeuge exakt übereinstimmen. Die Beobachtung
erteilt kein READ, SEND, keine Publikation und keine neue PC-Herkunft; sie verhindert
ausschließlich ein zweites Angebot/doppeltes Zählen. Nach END verbleibende
Beobachter sind ausdrücklich historische Metadaten, keine wiederbelebbaren Quellen.

Sechs unterschiedliche native Windows-Testgruppen bestehen: unveränderte gemappte
Dateien im Root ohne Angebote/neue Sourcehistorie; tatsächlich geänderte Mappingdatei
bis zu genau einem Angebot, echtem Backup/END und anschließendem Overlapskip;
fünf negative Beobachterfälle (später Edit, Nur-Fotos ohne tatsächlichen Zeugen,
unvorbereitete Source, fremder Connectionowner, alte beendete Source); drei betroffene bestehende
Mappinggruppen. Aktuelle Core- und echte WinForms-Produktquelle bauen ohne
Warnungen/Fehler. Linux besitzt seinen getrennt gesicherten entsprechenden
Workerzeugen; diese Windows-Prüfung ist kein neuer Linux-/Androidnachweis.

Historische/mehrdeutige oder nur gefilterte Mappings ohne aktuelle Vollbeobachtung
bleiben HOLD. Gemischte Dateitypen und sonstige konservative Inventur-HOLDs sind
damit nicht pauschal gelöst. Keine Installation, Veröffentlichung oder Öffnung
der bestehenden Geräte-/Automatik-/Video-/Mehrdatei-/Liefergates.

### Linux/Windows: positiv bekannte Gegenart ist keine unbekannte Datei (#493)

Beide Plattformen reproduzierten nativ bzw. im tatsächlichen Linux-Worker
`media_source_mime_unknown`, wenn eine ausdrücklich als Bilderquelle gewählte
Sammlung einen erkennbaren MP4-Container enthielt. Der Typname/Dateisuffix war
dabei kein Zeuge: Die Testdatei hieß absichtlich wie ein Bild.

Nur innerhalb bereits unabhängig aufgenommener nativer Collection-Sourceowner
unterscheidet eine neue deny-only Klassifikation jetzt den erwarteten Typ von
einer positiv identifizierten bekannten Gegenart. Ausschließlich wenn die strikte
erwartete Identifikation unbekannt meldet UND die ebenso strikte Gegenart wirklich
erkannt wird, entsteht `media_collection_known_other_type`. Der Worker zählt
dies als gefiltert, niemals als bekannte Publikation. Es gibt weder einen Cachejob
noch ein Angebot, eine Umetikettierung oder eine neue Video-SEND-Zustimmung.
Die bestehende Mapping-/Herkunftsaufnahme bleibt vorher erforderlich; unbekannte
historische oder gefilterte Mappings bekommen hierdurch keinen Ersatzzeugen.

Unbekannte Bytes, defekte oder zu große Dimensionen und Grenzen bleiben HOLD.
Die tatsächliche Sender-/Empfänger-Identifikation bleibt unverändert strikt;
deren `mime_unknown` wird nicht allgemein übersprungen. Auch gegenteilige
Containererkennung ist keine vollständige Pixel-/Videodecoder-Abnahme. Die
Video-Containerproben sind begrenzte Identifikationsfixtures, kein abgenommenes
abspielbares Telefonvideo und keine Freigabe für Videoersetzung.

Elf neue gezielte Linux-Fälle bestehen: tatsächlicher Bilderroot mit erkannter
Gegenart ohne Video-SEND, unbekannte/defekte Bytes und Nur-Fotos-Mischroot sowie
sieben Klassifikations-/strikte-Sender-Vektoren. Der durch diese Änderung betroffene
vollständige dreistufige echte Service-/Backup-/END-Lauf besteht zusätzlich mit
unveränderten Fristen. Vier Windows-Gruppen bestehen: zwei native Rootgruppen,
eine Klassifikationsgruppe und der betroffene vollständige unabhängige
Source-/Nachfolger-/Backup-/END-Fall. Aktuelle Core- und echte WinForms-Produktquelle
bauen ohne Warnungen/Fehler. Frühere unveränderte Proofs werden nicht doppelt gezählt.

Nur die sichere bekannte Gegenart wird ausgeschlossen, nicht beliebiger unbekannter
Dateibestand als vollständig erklärt. Ungeklärte/historische bzw. nur gefilterte
Überlappungen ohne vollständigen aktuellen Zeugen bleiben HOLD; Recovery und
native Bestands-/Provider-/Geräteabnahme bleiben offen. Keine Installation oder
Veröffentlichung, keine Öffnung von Capability23, automatischem gesamtem Export
oder den Video-/Mehrdatei-/Liefergates.

### Zielwechsel-Gegenprobe: Linux-Quelle und Windows-Sicherheitsgrenze (#494)

Die Vermutung, ein tatsächlich gewechseltes Windows-Empfangsziel verliere erst
beim späteren ausgewählten alten Quellroot seinen Mappingowner, ist durch die
native Gegenprobe nicht bestätigt: Der reguläre Windows-Speicherpfad erlaubt
derzeit nach erster Zielregistrierung nur denselben ursprünglichen Root. Eine
neue Auswahl hält schon mit `file_destination_existing_history_required`, bevor
ein neuer Zielrecord oder ein späterer historischer Sourcefall entsteht. Dieser
Guard wird nicht entfernt, und Testdaten werden nicht daran vorbei manipuliert.
Der fehlende ursprüngliche verlustlose Windows-Wechsel-/Migrationspfad wird in
#495 getrennt bearbeitet.

Linux verarbeitet dagegen den tatsächlichen nativen Empfangszielwechsel im
neuen Hostfall bereits korrekt: ursprünglicher Root zusätzlich ausdrücklich
als Quelle gewählt, echte alte aktuelle Mappingdatei frisch gelesen, kein
neues PC-Angebot/Relabel, Originalbytes erhalten, neues Empfangsziel unbeschrieben.
Der entsprechende native Windows-Fall bestätigt die andere Vertragsgrenze:
abgelehnter Wechsel lässt alten Zieltoken, Record, Mappings und Historie exakt
unverändert; der alte echte Mappingquelllauf funktioniert danach weiterhin.

Diese zwei neuen gezielten Fälle bestehen. Kein Produktguard wurde gelockert
und kein Windows-Sourcefix aus dem Linux-Erfolg abgeleitet. Die Corequelle mit
den Schutztests baut fehlerfrei; unveränderte aktuelle Produktbuildnachweise
bleiben erhalten. Es gibt keinen neuen nativen Zielwechsel-, Android-, Recovery-
oder Lieferabnahmenachweis. Historische/unklare Quellen ohne ursprünglichen
aktuellen Owner bleiben HOLD; #495/#486 und die Geräte-/Liefergates bleiben offen.

### Windows: getrennte inaktive Zielentscheidungen vor einem Wechsel (#495)

Der erste Baustein des fehlenden Zielwechselowners ist ausdrücklich nur ein
inaktives Metadatenregister. `native_media_destination_choices` hängt geschützte
native Auswahlrecords an, statt `native_media_destinations`, dessen Ciphertext,
Version oder Zieltoken zu überschreiben. Die vorhandene Auswahl bleibt aktiv;
`SetNativeMediaDestination` hält einen anderen Root weiterhin. Kein GUI-Pfad
aktiviert diese Records, kein Source-/Receive-/Restorepfad darf sie als aktuellen
Zielowner oder historischen Datenbeleg verwenden.

Ein Record bindet tatsächliche Native-Verzeichnisidentität und Creation-Zeugen,
ursprüngliche Zielversion, authentifizierten Peer-/Pairing-/Local-Keyscope und
eine eigene opake Metadatenversion. Jede Anlage verlangt den originalen nativen
Kontextvergleich und den exakten vorgefundenen Katalog; Kontext, nativer Owner,
Generation, Originalrecord und vorhandener tatsächlicher DPAPI-Schlüssel werden
vor Commit erneut geprüft. Keine Schlüssel-/Datenbankrekonstruktion. Der Vergleich
unter Store-CAS ist ein deny-only Metadatenfence, kein callbackfähiger Transport-
Scope oder neuer Datenkonsens. Unbekannte Recordfelder führen zu HOLD unter Erhalt
der ursprünglichen Bytes, nicht zu Normalisierung oder Reparatur.

Das neue ausschließlich inaktive Register ist separat auf 32 Entscheidungen je
Peer/Medientyp und die bestehende 128-KiB-Metadatenrecordgröße begrenzt. Dies erhöht
keine bestehende Source-/Receive-Historienquote; deren 128er-Grenzen bleiben
unverändert. Volles Register hält ohne Eviction. Identische Auswahl bleibt unter
derselben ursprünglichen Version/Generation idempotent, überlappende/mehrdeutige
Roots werden nicht automatisch neu assoziiert. Auflisten ist weder Absenzbeweis
noch Recovery-, Restart-, Schreib- oder Transferfreigabe.

Acht unterschiedliche Windows-Testgruppen bestehen: drei neue inaktive
Registergruppen und fünf betroffene ursprüngliche Zielgruppen. Echte Windows-
Verzeichnisse, Creation-Änderung, DPAPI-Datei, Verschlüsselung und SQL-Transaktion
sind geprüft; Originalrecord und dessen Ciphertext bleiben unverändert. Die
Grenzprobe legt 32 inaktive Entscheidungen an und bestätigt HOLD der 33. ohne
Verlust; fehlender Schlüssel und fehlendes Original erzeugen keine Ersatzowner.
Ein spätes Kontextende nach Insert, aber vor Commit rollt vollständig zurück.
Aktuelle Core- und echte WinForms-Produktquelle bauen ohne Warnungen/Fehler.

Dies ist noch kein benutzbarer Empfangszielwechsel: Originaljob-/Backup-/Trash-/
Preview-/Sourceowner für frühere Generationen, authentifizierte aktive Auswahl
und ursprünglicher nativer Dialoganschluss fehlen weiterhin. Solange sie nicht
vollständig verbunden und geprüft sind, bleibt die aktive Umschaltung HOLD.
Linux-Zielwechselbelege sind kein Windows-Aktivierungsnachweis. Androidpause,
Capability23, automatischer gesamter Export und Video-/Mehrdatei-/Liefergates
bleiben unverändert; keine Installation oder Veröffentlichung.

### Windows: ursprünglicher abgeschlossener Jobowner vor Zielaktivierung (#496)

Backup, Trash-Move/Restore, Trash-Vorschau und endgültige lokale Entfernung
verwenden jetzt einen privaten typisierten Owner des exakten ursprünglichen
abgeschlossenen Receivejobs. Er prüft die tatsächliche bestehende Schlüsseldatei,
aktuellen Peer-/Pairing-/Local-Keyscope und den frisch authentifizierten Job mit
identischer Revision, Version und vollständigem Bodyfingerprint. Gespeicherte
Saved-/Source-END-Bezüge sind dabei historische Korrelation, kein neuer IO-END-,
Cleanup-, Lese- oder Mutationsgrant.

Der vollständige ursprüngliche Rootdescriptor einschließlich Native-Identität,
Pfad, Volume, Zielversion und Token muss zum unveränderlichen Legacy-Zielrecord
passen. Inaktive Zielvormerkungen werden dazu niemals abgefragt oder als neue
admittierte Generation angenommen. Auch gefälschte CLR-Metadaten mit derselben
nominalen Version ersetzen nicht den wirklichen authentifizierten Jobbody. Fehler
verwerfen den Metadatenowner dauerhaft; Wiederherstellung der alten DB-/Keybytes
belebt ihn nicht wieder. Native Dateihandles, volle Bytes/Hashes, aktuelles Buch,
Auswahl, Retention und gegebenenfalls ausdrückliche Löschbestätigung bleiben
unabhängig in den jeweiligen Operationen erforderlich.

Der vorhandene gemappte Sourceowner authentifiziert sein Mapping weiterhin selbst
bei IO. Er und seine Kandidatenplanung lesen nun ausdrücklich den unveränderlichen
ursprünglichen Legacy-Root statt des künftig umschaltbaren öffentlichen aktuellen
Zielgetters. Kein zweiter redundanter Historyscan ersetzt dort den bereits echten
Mappingowner; keine native Prüfung wird aus einem gecachten Ready-Flag abgeleitet.
Der öffentliche aktuelle Getter bleibt bis zum fehlenden Aktivierungspfad beim
Legacy-Ziel; neue zugelassene Zielgenerationen sind noch nicht implementiert.

33 unterschiedliche betroffene native Windows-Gruppen bestehen: drei neue
Owner-/Sourcegruppen, 14 Backup-/Pending-/Recoverygruppen, sieben Trashgruppen,
sechs Purgegruppen und drei vorhandene Mappinggruppen. Die neuen Fälle prüfen
echte Rohsicherung, unabhängige Rohwiederherstellung, Trash-Vorschau und Restore
nach inaktiver Vormerkung, außerdem einen tatsächlichen geänderten Mappingexport
bis zum eigenen Rawbackup/Quell-END bei weiterhin ausgeschaltetem PC RECEIVE und
Telefon READ. Sechs negative Ownerfälle halten, darunter gleicher Token/Version
bei ausgetauschtem Root, verlorener Job/Key, Vormerkung als vorgeblicher Jobbeleg,
anderer Body unter gleicher Version und Saved ohne tatsächlichen Endbeleg.
Vorschau-Rendering ist in diesen neuen Fällen modelliert; authentifizierte native
Datei-IO ist echt, keine neue Decoder-/Androidabnahme wird behauptet.

Core- und tatsächliche WinForms-Produktquelle bauen ohne Warnungen/Fehler. Native
Fristen, Source-/Receive-Historiengrenzen und das 32er-Vormerkungsregister bleiben
unverändert. Weitere zugelassene Generationen, authentifizierte aktuelle Auswahl
und original gebundener nativer Dialog fehlen noch; Zielwechsel und Lieferung
bleiben gesperrt. Eine Vormerkung oder ein alter Jobflag darf diese Lücke nicht
schließen. Linux-/Notes-Nachweise bleiben separat erhalten, #423 bleibt pausiert.

### Windows: getrennte vorbereitete PC-Sicherung und rohe Offline-Recovery

Ein ausdrücklicher interner nativer Eintritt kann die tatsächlichen Bytes eines
lebenden vorbereiteten PC-Quellowners in einen separat gewählten beschreibbaren
Sicherungsordner kopieren. Ein nur lesend ausgewählter Collection-Root ist kein
solcher Schreibowner. Weder Empfangsziel noch Telefon-READ oder PC-RECEIVE werden
daraus abgeleitet; es wird kein eingehender Saved-/Source-END-Job nachgebaut.

Der bestehende geschützte Backupkatalog hat dafür einen eigenständigen
Ausgabeparent-Eintritt. Seine Snapshot-/Anchorprüfung, Grenzen und alten
Empfangsformate bleiben erhalten. Eine geschlossene Auswahl tatsächlicher
nativer Eingabeowner erlaubt entweder die bisherige Staged-Datei oder den
exakten lebenden vorbereiteten Quellcache, keine beliebigen Leser-Callbacks.
Letzterer bleibt an Store, Quelljobversion, Nonce, Manifest und ursprüngliche
Quell-/Buch-/Intent-/Einwilligungsprüfungen gebunden. Die bestehende
Cache-vor-Store-Sperrreihenfolge und der Cache-IO-Besitzer bleiben während der
gesamten lokalen Kopie gehalten; Dispose kann den tatsächlichen Quellabschluss
erst nach dem Drain veröffentlichen. Entzogene Quellen werden nicht durch
weiter erlaubtes Schreiben am Sicherungsziel erneuert.

Separates Backup-Provenienzformat 1 mit `kind: prepared_pc_source` bewahrt
Quellversion, Nonce, vollständiges Manifest, lokalen Ursprung, Scope,
ursprüngliche Buch-/Intent-/Sendezeugen und gegebenenfalls den genauen Vorgänger.
Diese Metadaten sind keine Empfangsquittung. Inhaltliche Deduplizierung erhält
unterschiedliche Quellversionen; Wiederholen derselben Sicherung erneuert weder
Versions-ID noch Aufbewahrungsursprung. Kandidaten-FID und unveränderliche
Versionsabsicht werden weiter vor Nutzdaten geschrieben. Wiederaufnahme prüft
jedes vorhandene Präfixbyte und die tatsächlichen Zielbytes; sie funktioniert
auch ab einem nicht chunkbündigen Offset. Fremde oder beschädigte Präfixe
bleiben unverändert HOLD, ohne Trunkierung. Zwischenpuffer werden auch bei
fehlgeschlagenem Präfixlesen gelöscht.

Die unabhängigen rohen Recovery-Eintritte benötigen nur den ursprünglichen
lokalen Speicherschlüssel, die exakte Backupordner-/Anchoridentität und einen
aktuellen nativen lokalen Ausgabeowner. Sie lesen weder lebenden Peer noch
Quellcache, Mappingstore oder Empfangsziel. Auch vollständig geschriebene,
noch nicht terminal bestätigte Sicherungen können nach unabhängiger Prüfung
ohne Katalogumschreiben gerettet werden. Das Ziel muss eine ausdrücklich neue
native Datei sein. Die bisherige synchronisierte Empfangs-Wiederpublikation
weist PC-Sicherungen mangels eigenem Publikationsowner ausdrücklich ab.

Sechs gezielte tatsächliche Windows-Gruppen prüfen diese PC-Pfade; elf passende
bestehende Gruppen sichern Staged-Bytes, alte Saved-/Backupkataloge, alternativen
Sicherungsort und eingehende native Recovery. Das ist noch kein angeschlossener
nativer Picker, keine automatische Sicherungssteuerung oder benutzbare gesamte
PC-Recovery-Oberfläche. Notes-Folgeversionen und Geräteabnahme bleiben gesperrt;
diese lokalen Nachweise erlauben keine Auslieferung oder Featurefreigabe.

Der native Coordinator kann diese unabhängigen PC-Sicherungen jetzt unter einem
tatsächlich gespeicherten, entsperrten lokalen Buch auflisten und eine ausdrückliche
lokale Recovery-Auswahl vorbereiten. Die Auswahl bindet exakte Backupversion,
ursprünglichen Backupordner, gesondert nativ beschreibbar gewählten Ausgabeordner,
ursprünglichen Buchpermit und eine eigene Operations-ID. Vorbereitung schreibt
noch keine Zieldatei. Bestätigung läuft in der vorhandenen exklusiven nativen
Medienarbeitsbahn, nicht unter Empfangsfreigaben oder einem Browser-Dateipfad.

Für diese lokale neue Datei führt ein getrenntes Restore-Scope mit Journalformat 2
zusätzlich den ursprünglichen Buchzeugen. Das exakte alte eingehende
Journalformat 1 bleibt lesbar und unverändert. Kandidaten-FID und Referenz werden
vor Nutzdaten festgehalten, vorhandene Bytes unabhängig geprüft und die Datei
ohne Ersetzen eines fremden Namens veröffentlicht. Dieselbe bestätigte Operation
liest nach Abschluss ihren tatsächlichen ursprünglichen Ziel-FID/Inhalt zurück,
statt eine zweite Datei anzulegen. Ein fremder besetzter Name bleibt erhalten;
nach ausdrücklichem Freimachen durch den Benutzer kann derselbe Kandidat mit
derselben Operations-ID weiterlaufen. Eine andere Datei am gewählten Ausgabeort
oder ein geändertes gespeichertes Buch erneuern die alte Auswahl nicht.

Das ist ausschließlich lokale neue Datei-Recovery, keine synchronisierte
Wiederanbindung oder Notes-Veröffentlichung. Vor Aufnahme unabhängiger PC-Quellen
werden deshalb auch sämtliche authentifizierten lokalen Recovery-Journale
deny-only geprüft: bekannte wiederhergestellte FIDs dürfen nicht als neue
Erstherkunft umetikettiert werden. Auch ein noch unklarer eigener Kandidat bleibt
HOLD. Die zusätzliche Scope-Prüfung ist begrenzt und verwirft keine Aufzeichnungen.
Zwei gezielte tatsächliche Windows-Gruppen prüfen Offline-Auswahl, Buch-/Worker-
Bindung, idempotente Wiederholung, Ersatz-Ausgabeordner, Namenskollision,
unveränderten Kandidaten-FID und die neue Quellsperre. Vier passende bestehende
Gruppen sichern alte native Restore-/UI-/Source-END-Wege. Native Dialoge und
Weboberfläche sind damit noch nicht angeschlossen; Reboot-Adoption alter
Bestätigungen oder eine automatische Recovery-Publikation werden nicht behauptet.

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
