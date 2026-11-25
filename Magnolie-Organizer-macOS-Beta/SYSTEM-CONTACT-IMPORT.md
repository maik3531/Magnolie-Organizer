# Ausgewählte Mac-Kontakte als lokale Kopien übernehmen

Quellpatch zu [#775](https://github.com/maik3531/Magnolie-Organizer/issues/775),
Fortsetzung von #721, #770 und #772. Stand: 25. November 2026.

Der Anschluss nutzt das öffentliche Apple-Framework **Contacts** direkt im
Mac-Host. Er installiert kein zusätzliches Programm und benötigt keine eigene
Magnolie-App auf dem iPhone. Die gewünschten iPhone-Kontakte müssen bereits im
gewählten Mac-Adressbuch verfügbar sein, beispielsweise über das vom Nutzer
eingerichtete iCloud- oder CardDAV-Konto. AirPlay bleibt der Bild-/Tonkanal;
Kontaktfelder werden über diesen getrennten Systemzugriff gelesen.

**Dies ist ein prüfbarer Quellpatch, keine native Funktionsfreigabe.** In dieser
Umgebung stehen weder macOS noch eine Swift-Toolchain bereit. Contacts,
AppKit-Auswahl, Berechtigungsdialog und echte Konten-/Geräteinteraktion müssen
nach dem nativen Bau geprüft werden. Die unten beschriebenen Projektionsprüfungen
verwenden erfundene Daten und ersetzen diese Abnahme nicht.

## Bedienung nach dem nativen Bau

1. Das Magnolie-Buch entsperren. **Mac-Kontakte übernehmen …** im App-Menü oder
   bei den Systemquellen wählen. Bestehende Editor- und Speicher-Guards bleiben
   wirksam. Noch offene Kontoeingaben einschließlich einer alleinigen
   Kennworteingabe werden nicht automatisch gespeichert oder verworfen.
2. Den Kontaktezugriff freigeben, falls macOS danach fragt. Die Importaktion
   fordert ihn ausdrücklich an; der App-Start sammelt keine Kontaktdaten.
3. Ein tatsächlich gefundenes Mac-Adressbuch wählen. Gleiche Anzeigenamen
   bleiben durch getrennte native Kennungen unterscheidbar.
4. Bis zu **100 Kontakte** auswählen. Zunächst werden nur Kennungen und
   Namensangaben aufgelistet; weitere Felder und Bilder werden ausschließlich
   für die gewählten Kontakte gelesen.
5. Die Vorschau nennt neue, bereits übernommene, an der Quelle geänderte und
   ausgeschlossene Kontakte. Angezeigte Feldwerte, Fotos und Hinweise prüfen.
   Ziel ist der vorhandene Kontaktbereich des aktuellen Magnolie-Buchs.
   Die Provider-Auswahl unter den Synchronisationseinstellungen ist kein
   zusätzliches lokales Zieladressbuch.
6. **Angezeigte Kontakte übernehmen** bestätigen. Der Host liest dieselben
   nativen Kennungen erneut und vergleicht Quelle und gelesene Inhalte mit der
   Vorschau. Änderungen erfordern einen neuen Vorschlag.
7. Magnolie legt über den bestehenden Speicherweg einen Wiederherstellungspunkt
   an und übernimmt die neuen lokalen Kontakte. Erfolg erscheint erst nach
   der bestätigten dauerhaften Speicherung. Bei einem abschließenden
   Speicherfehler bleiben die sichtbaren Kopien ausdrücklich ungespeichert;
   diese Änderungen zuerst speichern.

Ein Abbruch verwirft das Leseergebnis. Ein bereits laufender Contacts-Aufruf
kann noch zurückkehren; die Reader-Queue bleibt bis dahin belegt. Die
Koordination prüft Abbruch und Dokumentgeneration nach jedem asynchronen
Schritt. Nach Beginn der lokalen Speichertransaktion wird kein Abbruchknopf
angeboten, der eine bereits erfolgte Mutation rückgängig zu machen verspricht.

## Feldumfang und bewusste Grenzen

Der neue Weg liest explizit ausgewählte öffentliche `CNContact`-Schlüssel.
Er benutzt weder eine private Kontakte-Datenbank noch einen vCard-Parser als
verdeckten Import aller fremden Eigenschaften. Die bestehende allgemeine
Snapshot-API mit ihrer noch nicht implementierten Kontaktprojektion wird
dadurch nicht in einen vollständigen Synchronisationsvertrag umgedeutet.

| Feld oder Zustand | Behandlung |
| --- | --- |
| Name und Firma | Darstellung im vorhandenen Kontaktmodell; unterstützte strukturierte Namens-/Organisationsangaben zusätzlich in kontrollierten Roundtrip-Feldern |
| Mehrere Telefon-, E-Mail- und Postadressen | Werte und unterstützte Labels im vorhandenen Modell; Zusammenführungen, Kürzungen oder andere unerwartete Normalisierungen führen zum sichtbaren Ausschluss |
| Schreibweise von E-Mail-Adressen | Das vorhandene Modell verwendet Kleinschreibung. Diese einzige zugelassene Schreibweisenänderung erhält einen eigenen Vorschauhinweis; die Originalschreibweise bleibt im Quelldatensatz |
| Unterstützte öffentliche Webadressen | Kontrollierte HTTP-/HTTPS-URLs ohne Zugangsdaten; keine Übernahme von Quell-UID, Revision oder fremden Synchronisationsregeln als aktive vCard-Eigenschaften |
| Kontaktfoto | Unterstützte Originaldaten aus `imageData`; kein unbemerkter Ersatz durch das abgeleitete Vorschaubild. Die native Vorschau verkleinert nur die Darstellung |
| Gregorianischer Geburtstag mit oder ohne Jahr | Eigenständiges Kontaktdatum; kein erfundenes Jahr und keine automatische Jahrestagsanlage. Ein ausdrücklich geliefertes Jahr 1604 bleibt für diese Kopien erhalten |
| Nichtgregorianische oder nicht eindeutig abbildbare Datumsangaben sowie zusätzliche Datumsfelder | Sichtbarer Ausschluss; keine automatische Umdeutung in einen Gregorianischen Geburtstag oder Jahrestag |
| Weitere öffentliche Namens-, Organisations-, Adress- oder Profildetails | Soweit nicht aktiv im Kontaktmodell nutzbar, ausdrücklich als zusätzliche Quelldaten gekennzeichnet. Die Vorschau nennt diese Einschränkung |
| Notiz innerhalb einer Kontaktkarte | Nicht angefordert und nicht übernommen. Apple verlangt für dieses Feld ab macOS 13 ein besonderes, von Apple genehmigtes Entitlement |
| Unbekannte Providerfelder, vollständige Gruppen-/Verknüpfungssemantik | Kein Vollständigkeitsversprechen und keine neue aktive Abbildung |

Die tatsächliche kanonische Normalisierung wird auf den vorbereiteten neuen
Kontakten ausgeführt und mit den erwarteten Feldern verglichen. Bestehende
Kontakte werden dabei nicht normalisiert oder ersetzt. Ungeeignete Einträge
werden mit einem Grund ausgelassen; ein fehlender Wert wird nicht durch ein
erfundenes Standarddatum, Bild oder Feld ergänzt.

`nativeContactRecord` bewahrt die tatsächlich gelesenen öffentlichen
Ursprungsfelder. Dieser Nachweis ist **kein vollständiges Archiv** einer
Apple-Kontaktkarte oder des zugrunde liegenden Kontodienstes. Die Quelle ist
auch nach der lokalen Kopie weiterhin in Apple Kontakte vorhanden.

## Geburtstage ohne zusätzliche Jahrestage

Kopien dieses Anschlusses tragen den begrenzten Herkunftsvertrag
`nativeContactImport.version = 1` und `birthdayPolicy = "contact-only"`.
Das Geburtsdatum bleibt am Kontakt sichtbar und bearbeitbar. Der Mac-Port
erzeugt daraus keine Kalender-/Jahrestagseinträge und ordnet auch keinen
namensgleichen vorhandenen Jahrestag zu. Die Regel gilt beim Import, beim
erneuten Laden und beim normalen Bearbeiten dieser Kontakte.

Der bestehende Datumseditor unterstützt auch einen fehlenden Jahreswert. Eine
nichtleere ungültige Eingabe wie `31.02.2000` oder ein unvollständiges `12.`
blockiert das Speichern und behält das bisherige Kontaktdatum. Bewusstes Leeren
bleibt möglich. Die alte 1604-Sentinelregel wird ausschließlich für diese
gekennzeichneten Kopien umgangen, damit ein ausdrücklich vorhandenes Jahr 1604
beim Laden und Bearbeiten erhalten bleibt.

Gewöhnliche Magnolie-Kontakte behalten ihr bisheriges Verhalten. Bereits
vorhandene beziehungsweise ausdrücklich angelegte Jahrestage bleiben eigene
Daten. Das ist eine eng auf den Mac-Port begrenzte Projektion; daraus folgt
keine bereits geprüfte gleiche Behandlung durch andere Editionen oder ältere
Bauten. Ein Export beziehungsweise Restore in solchen Bauten benötigt eine
gesonderte Prüfung dieser Herkunfts- und Geburtstagssemantik. Der konkrete
gemeinsame Quellenbefund und die noch offene Linux-/Windows-Prüfung stehen in
[#776](https://github.com/maik3531/Magnolie-Organizer/issues/776); ein nativer
Datenverlust oder ausgelöster Alarm wird daraus nicht behauptet.

## Identität, Wiederimport und Speicherung

Die native Herkunft bindet die tatsächliche Containerkennung und die
unveränderte native Kontaktkennung. UTF-8-basierte Identitätsrahmen verhindern,
dass verschiedene Kennungen durch Unicode-Normalisierung zusammenfallen.
Neue Kopien erhalten frische lokale IDs und eine unabhängige lokale UID.
Die native Kennung wird nicht als Provider- oder Synchronisations-UID verwendet.

- Bereits übernommene Identität: keine zweite lokale Kopie.
- An der Quelle geänderte Identität: Vorschauhinweis; die vorhandene lokale
  Kopie und ihre Bearbeitungen bleiben erhalten.
- Lokale Kopie im Papierkorb: nicht erneut anlegen; bei Bedarf dort
  wiederherstellen.
- Gleicher Name, gleiche E-Mail-Adresse oder Telefonnummer ohne diese Herkunft:
  keine automatische Zusammenführung.
- Mehrdeutige oder widersprüchliche Herkunft: Übernahme stoppen.

Apple garantiert die Kontaktkennung nur auf dem jeweiligen Gerät. Nach
Kontowechseln, Neuaufbau der Kontakte-Datenbank oder auf einem anderen Mac kann
eine neue native Kennung entstehen. Der Anschluss behauptet deshalb keinen
geräteübergreifenden Dublettenschutz und löst solche Fälle nicht durch
Namens-/E-Mail-Heuristiken auf.

Die Vorschau ist an das echte aktuelle Dokument und dessen Inhalt gebunden.
Zusätzliche Entwürfe, Wiederherstellung, Dokumentwechsel, überholte Vorschläge,
abgelaufene Tokens und fehlende Speicherquittungen verhindern die Übernahme.
Der Quellvergleich bindet die gelesenen Felder einschließlich ausgeschlossener
Einträge; er ist kein atomarer Compare-and-Swap- oder Server-Revisionsbeleg.
Es gibt keine Contacts-Schreib-/Löschoperation und keinen automatischen oder
bidirektionalen Abgleich.

## Grenzen und native Abnahme

Ein Lauf umfasst höchstens 100 ausgewählte Kontakte und 16 MiB transportierte
Daten einschließlich mehrfach enthaltener Vorschaufelder. Metadatenlisten,
einzelne Felder, Bilder und Strukturgrößen sind zusätzlich begrenzt. Eine
überschrittene Gesamtgrenze bricht den Vorschlag ab; sie erzeugt keinen als
vollständig ausgegebenen gekürzten Bestand. Native Lesevorgänge verwenden die
vorhandene serielle Store-Queue, kooperative Abbruchprüfungen und die
20-Sekunden-Lesefrist.

Ein Originalfoto darf höchstens 2.600.000 Bytes umfassen. Der Reader prüft
Signatur, tatsächliches ImageIO-Decoding und höchstens 64 Frames mit zusammen
16.777.216 Pixeln sowie höchstens 8192 Pixeln je Kante. Ungeeignete Formate werden
ausgeschlossen; eine überschrittene native Lese-/Größengrenze stoppt den Lauf
mit einem Fehler, ohne die Auswahl teilweise zu speichern.

Vor einer Freigabe sind insbesondere zu prüfen:

- Swift-Bau und Core-Tests mit unterstütztem macOS-SDK; tatsächliche
  Mindestversion 12.7 sowie aktuelle Intel-/Apple-Silicon-Zielsysteme.
- Erlaubter, verweigerter, widerrufener und noch nicht angefragter
  Kontaktezugriff; keine unzulässige Anfrage des Kontakt-Notizschlüssels.
- Lokale, iCloud- und tatsächlich verfügbare CardDAV-Container, gleiche
  Anzeigenamen, verknüpfte Kontakte und nicht vereinheitlichte Kennungen.
- Exakte Auswahl und Containerzugehörigkeit vor/nach dem Lesen, geänderte,
  verschobene oder entfernte Kontakte zwischen Vorschau und Bestätigung.
- Mehrfachwerte und benutzerdefinierte Labels, strukturierte Namen und
  Adressen, Originalbilder, Geburtstage ohne Jahr und seltene Datumsfälle.
- Tatsächlicher AppKit-Fokus, lange Vorschauen, Fotoanzeige, Abbruch,
  Einstellungen/Editorentwürfe, Speicherung und erneutes Öffnen des Buchs.
- Bereits vorhandene Kopien, lokale Änderungen und Papierkorb; keine
  unbeabsichtigte Änderung der Apple-Quelle oder vorhandener Jahrestage.

## Tatsächlicher Prüfstand dieses Quellpatches

Der gemeinsame Abschlusslauf bestand sechs Testgruppen: Kontaktkopien
(**230 Prüfungen** und Driftprüfung von 14 Geburtstagsankern), Notes-Kopien
(**179**), Kalenderkopien (**307**), allgemeiner UI-Host (**109 Assertions**),
Bridgeinventar und Freeze-/Manipulationserkennung. Verwendet wurden Node
24.22.3 und CI-JSDOM 26.1.0. Der eigenständige Kontakt-Runner bestätigte die
230 Prüfungen zusätzlich mit unveränderter Eingabeinventur.

Die Kontaktprüfung führt die tatsächliche projizierte Organizer-Oberfläche
mit einem gemeinsamen vollständigen Core-Fixture aus: Auswahl-/Settingspfade,
Mehrfachfelder und Fotos, Wiederimport, Papierkorb, lokale Änderungen,
Jahr-/Datumsfälle, echte Editoreingaben, kanonische MCP-Aktionen, ODS-Fallback,
Entwurfs-/Restore-/Token-/Checkpoint-/Speicherfehler und Grenzen. Native
Nutzlasten und Transportantworten sind dabei synthetisch; Contacts.framework
und AppKit laufen hier nicht.

25 neue Swift-Core-/Bridge-Testmethoden sind für die native Ausführung
vorbereitet. Sie wurden mangels Swift und macOS **nicht kompiliert oder
abgespielt**. JSON-/Plist-Format, Fixture-Identitätsreferenz, PNG-Struktur samt
CRC/Scanlines und Diff-Whitespace wurden tatsächlich geprüft. Eine vollständige
Sprachkatalogprüfung oder Paketfreigabe wird daraus nicht abgeleitet.

## Maßgebliche öffentliche Schnittstellen

- [CNContactStore](https://developer.apple.com/documentation/contacts/cncontactstore.md):
  gezieltes Lesen, zunächst Kennungen und danach Details; I/O außerhalb des UI-Threads.
- [CNContactFetchRequest.predicate](https://developer.apple.com/documentation/contacts/cncontactfetchrequest/predicate.md):
  keine Compound-Predicates. Containerzugehörigkeit und gezielter ID-Abruf
  werden getrennt geprüft.
- [CNContact.identifier](https://developer.apple.com/documentation/contacts/cncontact/identifier.md):
  nur auf dem aktuellen Gerät eindeutig.
- [CNContact.note](https://developer.apple.com/documentation/contacts/cncontact/note.md):
  besonderes Apple-Entitlement ab macOS 13.
- [CNContact.birthday](https://developer.apple.com/documentation/contacts/cncontact/birthday.md):
  Gregorianischer Geburtstag mit erforderlichem Tag/Monat und optionalem Jahr.

Quellzweig und tatsächlicher Prüfstand werden in `ARBEITSSTAND.md` und im
Issue hinterlegt. Die Patches sind für die spätere Übernahme mit Codex bestimmt;
sie veröffentlichen kein installierbares Paket.
