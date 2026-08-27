# Magnolie Notes – Notizen für Android

Ein Notizbuch fürs Handy im Stil des Magnolie Organizers: Leder und Gold außen,
Papier mit Linienspiegel innen. Jede Notiz trägt Tag und Uhrzeit und ein
Sinnbild, und über den **Magnolienbaum** geht sie unmittelbar zum Organizer am
Rechner – ohne Cloud, ohne Vermittler.

Magnolie Organizer ist als vollständige Desktop-Anwendung für Linux und Windows
erhältlich. Beide Ausgaben tauschen freigegebene Inhalte über WLAN, das lokale
Netz, VPN oder einen eingerichteten Fernendpunkt aus. Die Linux-Ausgabe enthält
zusätzlich den passenden BlueZ-RFCOMM-Empfänger. Die Windows-Ausgabe kann
RFCOMM verwenden, wenn Windows den Bluetooth-Zugriff erlaubt, ein aktiver
Adapter vorhanden und das Telefon in Windows gekoppelt ist. WLAN und Bluetooth
führen in denselben verschlüsselten Magnolienbaum-Handler. Beim Versand gilt die
feste Reihenfolge: eindeutiger örtlicher WLAN-Endpunkt, optional eingerichteter
entfernter Endpunkt, danach Bluetooth.

Die Oberfläche folgt der Geräte- oder App-Sprache und unterstützt denselben
Umfang wie der Organizer: Deutsch, Englisch, Französisch, Spanisch, Italienisch,
Niederländisch, Portugiesisch, Russisch, Tschechisch, Polnisch, Obersorbisch,
Dänisch, Norwegisch Bokmål, Hindi, vereinfachtes Chinesisch, Japanisch,
Arabisch, Ukrainisch, Belarussisch und Türkisch. Ab Android 13 stehen alle
zwanzig Sprachen auch in der systemweiten Sprachauswahl für diese App bereit.

---

## 1. Notizen aus fremden Programmen übernehmen

Zuerst das Unangenehme, offen gesagt: **Samsung Notes, Google Keep, ColorNote
und die übrigen lassen sich nicht direkt auslesen.** Ihre Datenbanken liegen
unter `/data/data/<paket>/` in der App-Sandbox. Android verwehrt jeder fremden
App den Zugriff darauf, und eine öffentliche Schnittstelle zum Mitlesen gibt es
bei keinem dieser Programme. Ohne Root ist das keine Frage des Aufwands,
sondern schlicht verschlossen. Wer etwas anderes verspricht, verschweigt
entweder Root oder meint in Wahrheit einen der beiden folgenden Wege.

Diese beiden Wege gehen dafür immer und sind vollständig eingebaut:

### Der bequeme Weg: teilen

Notiz in Samsung Notes, Keep, ColorNote, Evernote, im Browser oder sonstwo
öffnen → **Teilen** → **Magnolie Notes**. Fertig. Mehrere Notizen dürfen auch
zusammen kommen (`SEND_MULTIPLE`), markierter Text ebenso (`PROCESS_TEXT`).
Bilder und PDF landen als Anhang. Woher die Notiz kam, merkt sich die App und
schreibt es in die Herkunftszeile.

### Der gründliche Weg: Exportdatei einlesen

Blatt **Übernehmen** → *Datei wählen* oder *Ordner wählen*. Erkannt werden von
selbst:

| Programm | Was einlesen |
|---|---|
| Google Keep | Google Takeout `.zip`, einzelne `.json` oder `.html` |
| Samsung Notes | als Text/HTML gespeicherte Notizen, `.sdocx`-Archive, ganze Ordner |
| Evernote | `.enex` (ein ganzes Notizbuch je Datei) |
| Simplenote | `notes.json` |
| Standard Notes | Sicherungs-`.json` oder `.txt` |
| Joplin | `.md`-Ordner (die `id:`-Fußzeilen fallen weg) |
| beliebig | Markdown- und Textordner, rekursiv bis sechs Ebenen |

So kommst du an die Exportdatei:

* **Google Keep** – `takeout.google.com` am Handy öffnen, nur „Keep“ auswählen,
  Export anfordern, die `.zip` hier einlesen.
* **Samsung Notes** – Liste öffnen, Notiz lange antippen, *Mehr → Als Datei
  speichern → Text oder PDF*. Ein ganzes Notizbuch lässt sich auf einmal
  auswählen; danach den Zielordner hier einlesen.
* **Evernote** – *Notizbuch → Notizen exportieren → .enex*.

Datum und Uhrzeit der Quelle bleiben erhalten, wo der Export sie mitliefert
(Keep rechnet in Mikrosekunden, Evernote in UTC – beides wird umgerechnet).
Derselbe Wortlaut kommt kein zweites Mal herein: über Titel und Text wird ein
SHA-256-Fingerabdruck gebildet, der doppelte Übernahmen erkennt.

---

## 2. Tag, Uhrzeit und Sinnbild

Jede Notiz führt zwei Zeitstempel in Millisekunden: `angelegt` und `geaendert`.
Die Liste gruppiert nach Tagen (*Heute*, *Gestern*, dann Wochentag und Datum)
und zeigt je Notiz die Uhrzeit.

Das Sinnbild wird beim Anlegen und Übernehmen aus dem Wortlaut geraten und
lässt sich im Schreibblatt jederzeit ändern. Es gibt zwölf, alle mit demselben
Federstrich gezeichnet wie die Symbole im Organizer:

Notiz · Einkauf · Aufgabe · Termin · Einfall · Reise · Rezept · Geld · Arbeit ·
Person · Gesundheit · Zitat

---

## 3. Aufgaben

Das Blatt **Aufgaben** führt, was ansteht – nach Fälligkeit sortiert:
*Überfällig* (in Signalrot), *Heute*, *Morgen*, *Diese Woche*, *Später*,
*Ohne Datum*, *Erledigt*. Abgehakt wird mit einem Tipp aufs Kästchen.

Eine Aufgabe hat Titel, Notiz, Fälligkeitsdatum, Dringlichkeit (dringend /
normal / kann warten) und eine Erinnerung. Das sind genau die Felder, die auch
der Organizer beim Delegieren überträgt.

### Erinnerungen

Ist der Haken *Erinnere mich* gesetzt und ein Datum eingetragen, stellt die App
einen Wecker: am Fälligkeitstag zur eingestellten Stunde, wahlweise um bis zu
14 Tage vorgezogen. Die Meldung nennt den Titel und **den Grund aus der
Notiz** – „Blumen kaufen“ allein sagt weniger als „weil Max Mustermann morgen
Geburtstag hat“. Aus der Meldung heraus lässt sich die Aufgabe direkt abhaken.

Die Wecker überstehen den Prozesstod; nach einem Neustart des Geräts stellt sie
ein `BOOT_COMPLETED`-Empfänger neu, ebenso beim Öffnen der App. Wo Android
genaue Wecker verweigert (ab Android 12 ohne die Erlaubnis
`SCHEDULE_EXACT_ALARM`), weckt die App ungenau statt gar nicht – die Meldung
kann dann einige Minuten später kommen.

### Aufgaben über den Magnolienbaum

* **Vom Rechner aufs Handy.** Im Organizer die Aufgabe an den Handy-Zweig
  delegieren. Sie erscheint hier mit Herkunftszeile *von …*, der Wecker wird
  gestellt, und eine Meldung sagt Bescheid.
* **Vom Handy weiter.** Im Schreibblatt *An einen Zweig geben*. Der Ursprung
  behält die Aufgabe; der andere bekommt eine gekennzeichnete Kopie.
* **Zurück fließt nur das Häkchen.** Wird eine fremde Aufgabe abgehakt oder
  wieder geöffnet, geht eine `stand`-Nachricht an ihre Herkunft. Titel,
  Fälligkeit und Notiz gehören dem Ursprung – das ist im Organizer genauso.

---

## 4. Magnolienbaum: Synchronisation mit dem Organizer

Die App ist ein vollwertiger Zweig. Sie spricht dieselben fünf Wege wie der
Organizer (`/magnolie/v1/paarung`, `/magnolie/v1/nachricht`,
`/magnolie/v2/paarung`, `/magnolie/v2/sitzung`, `/magnolie/v2/nachricht`),
beherrscht `baum-fs1` mit Forward Secrecy ebenso wie das ältere `baum-1`,
kündigt sich per DNS-SD als `_magnolie._tcp` an und beantwortet den
UDP-Ruf `MAGNOLIENBAUM?` auf Port 8737.

### Paaren – drei Wege

1. **Paarungsdatei aus dem Organizer** (empfohlen). Im Organizer
   *Einstellungen → Magnolienbaum → Paarungsdatei erzeugen*, die Datei aufs
   Handy bringen und im Blatt **Magnolienbaum** öffnen. Gültig 15 Minuten.
    Danach sind beide Seiten bestätigt, ausdrücklich vertraut und benutzen
    `baum-fs1`. Ist das LAN-Ziel nicht erreichbar, probiert die App mit
    vorhandener Berechtigung die gekoppelten Bluetooth-Geräte und merkt sich
    die MAC-Adresse des erfolgreichen Geräts.
2. **Paarungsdatei vom Handy.** Umgekehrt geht es auch: *Eigene Paarungsdatei
   erzeugen*, an den Rechner schicken, dort einlesen.
3. **Kurzer Codeweg.** *Im lokalen Netz suchen* → *Verbinden*. Beide Seiten
   zeigen dieselbe sechsstellige Zahl; wer sie vergleicht und bestätigt, ist
   verbunden. Dieser Weg benutzt `baum-1` und hat keine Forward Secrecy.

### Einmal gepaart, danach ohne Rückfrage

Ein Zweig, mit dem die Paarung geglückt ist, bleibt vertraut: sein öffentlicher
Schlüssel ist angeheftet, und jede weitere Synchronisation läuft ohne Nachfrage
durch. Ändert sich der Schlüssel einer bekannten Kennung, wird er **nicht**
stillschweigend ersetzt – dann muss der alte Zweig entfernt und neu gepaart
werden.

Wer es enger haben will, schaltet je Zweig *Inhalte ohne Rückfrage übernehmen*
ab. Dann landen dessen Notizen und Aufgaben zuerst im **Eingang** und warten
auf *Annehmen* oder *Ablehnen*. Der Erledigt-Stand einer Aufgabe wird immer
sofort verarbeitet; er ändert nur ein Häkchen an etwas, das man selbst vergeben
hat.

Am Organizer bleibt es bei dessen eigenem Verhalten: dort landet jedes neue
Angebot einmal im Eingang, bis man „Übernehmen und merken“ wählt.

### Notizen weitergeben

Im Schreibblatt auf **Weitergeben** und den Zweig wählen. Beim ersten Mal geht
die Notiz als Angebot (`notiz`) hinüber und muss im Organizer im Eingang
angenommen werden. Danach fließen Änderungen von selbst in beide Richtungen
(`notiz_sync`): höhere Fassung gewinnt, bei gleicher die lexikografisch größere
Quelle – genau wie im Organizer.

Bei jedem bestätigten, vertrauten Zweig gibt es **Alles synchronisieren**. Das
sendet jede örtliche Notiz mit stabiler Freigabekennung und jede eigene Aufgabe;
fremde Aufgaben werden nicht zurückgespiegelt. Anschließend fordert eine
verschlüsselte `sync_anfrage` den vollständigen Gegenbestand an. Die Antwort
enthält keine weitere Anfrage und bildet daher keine Schleife. Unvertraute
Zweige lösen keine automatische Antwort aus.

Der Schalter **Automatisch im lokalen WLAN synchronisieren** führt denselben
Vollabgleich höchstens alle sechs Stunden aus, solange der sichtbare
Empfangsdienst läuft und Android für das aktive Netz tatsächlich WLAN meldet.
SSID- oder Standortberechtigungen sind dafür nicht nötig; Mobilfunk löst den
Abgleich nicht aus. Schalter und letzter Lauf bleiben gespeichert.

Jede Sendung wird **vor** dem ersten Netzversuch ins Postfach geschrieben. Nach
Fehlern wird im Abstand von 1, 2, 5, 10, 30 und 60 Minuten erneut versucht,
danach stündlich; nach sieben Tagen gilt eine Sendung als aufgegeben.

### Empfangen

Der Schalter **Notizen empfangen** startet einen Vordergrunddienst mit
sichtbarem Hinweis in der Leiste. Nur so kann der Organizer das Handy
erreichen, während die App nicht offen ist. Der Dienst stößt alle 30 Sekunden
das Postfach an – derselbe Takt wie die Outboxwartung des Organizers.

### Bluetooth

Der Schalter **Bluetooth annehmen** öffnet einen RFCOMM-Dienst unter der
Kennung `6d61676e-6f6c-6965-6e62-61756d383733`. Darüber laufen **dieselben**
verschlüsselten Nachrichten; statt HTTP trägt sie ein Rahmen aus vier
Längenbytes und einem JSON-Umschlag `{"pfad":…,"nutzlast":…}`.

Der Organizer registriert dieselbe Kennung über BlueZ, sobald sein
Magnolienbaum eingeschaltet ist. Zuerst Handy und Rechner in den
Android-/Linux-Bluetooth-Einstellungen koppeln und den Magnolienbaum einmal über
WLAN paaren. Danach in der App Bluetooth einschalten, die Berechtigung erlauben
und beim Organizer-Zweig den gekoppelten Rechner wählen. Beim Versand wird
zuerst der örtliche WLAN-Endpunkt versucht. Danach folgen ein optional
eingetragener direkter Internet-/VPN-/Rückwärtstunnel-/Eigener-Server-Endpunkt
und schließlich Bluetooth. Magnolie betreibt dafür keinen zentralen Vermittler.
Beobachtete Quelladressen überschreiben diesen entfernten Endpunkt nicht.
BlueZ verlangt die Systemkopplung; zusätzlich bleiben Fingerabdruck,
angehefteter Partnerschlüssel und `baum-fs1` wirksam.

Der Rückweg vom Organizer zum Handy verwendet in dieser Fassung weiterhin
WLAN. Bluetooth deckt den Versand der App zum Organizer und den Empfang durch
den Organizer ab.

### Zwei zusätzliche Felder

Die Notiznutzlast trägt über das Protokoll hinaus `symbol` und `angelegt`. Der
Organizer liest ausschließlich die ihm bekannten Schlüssel und übergeht diese
beiden stillschweigend – sie stehen bereit, sobald er sie auswerten soll.
Die Bluetooth-Ergänzung ändert diese Nutzlastbehandlung nicht.

---

## 5. Was geprüft ist

46 Tests, davon 45 ausgeführt und grün. Sie prüfen nicht eine Nachbildung,
sondern den echten
Organizer:

* **`DrahtprobeTest` (16 Tests).** `werkzeuge/vektoren.py` lädt
  `bin/magnolie-organizer` als Python-Modul und lässt dessen eigene Funktionen
  rechnen. Verglichen werden: die kanonische JSON-Schreibweise zeichengenau
  (einschließlich Umlauten, Steuerzeichen und Zeichen außerhalb der BMP),
  Fingerabdruck, sechsstelliger Paarungscode, Partner- und Auth-Schlüssel,
  Paarungsdatei Fassung 2 samt Ablehnung einer veränderten Datei, die
  `baum-fs1`-Schlüsselableitung Byte für Byte, das Öffnen eines echten
  Notizumschlags, die Quittung und der alte `baum-1`-Umschlag samt
  Wiederholungsschutz.
* **`LiveprobeTest` (1 Test).** Startet den **wirklich laufenden**
  `BaumDienst` des Organizers über `werkzeuge/organizer_dienst.py` und führt
  über echtes HTTP durch: Paarung mit Datei, Notiz vom Handy zum Organizer,
  Notiz vom Organizer zum Handy, **eine delegierte Aufgabe vom Organizer zum
  Handy und der Erledigt-Stand zurück**. Fehlt Python oder
  `python3-cryptography`, wird der Test übersprungen statt fehlzuschlagen.
* **`NutzlastTest` (15 Tests).** Feldsatz der Notiznutzlast, Anhangsfilter und
  HTML-Filter samt Abwehr von `javascript:`-Zielen und `<script>`; dazu der
  Feldsatz von `aufgabe` und `stand`, das Glätten krummer Datums- und
  Dringlichkeitsangaben und die saubere Trennung der Nachrichtenarten.
* **`EinfuhrTest` (12 Tests).** Echte Ausschnitte aus Keep, Evernote,
  Simplenote, Standard Notes, Joplin, Takeout-ZIP und Samsung-HTML.
* **`TransportwahlTest`.** Prüft örtliches WLAN, entfernten Direktweg,
  Deduplizierung, Bluetooth-Rückfall und LAN-vor-Bluetooth bei Dateipaarung.
* **`SynchronisationTest`, `AutoSyncTest`, `ModellTest`.** Prüfen stabile
  Freigabekennungen und Fassungen, Aufgabenfilter, anfragefreie Vollsync-Antwort,
  Sechs-Stunden-/WLAN-Entscheidung sowie sichere Migrationsvorgaben.

Dazu ein Durchgang mit der **Release-APK auf einem Android-14-Gerät**
(Emulator, R8-verkleinert und signiert):

1. Eine Notiz aus einer fremden App hereingeteilt – sie erscheint unter
   *Heute* mit Uhrzeit und automatisch erkanntem Einkaufs-Sinnbild.
2. Empfangsdienst eingeschaltet – der Vordergrunddienst läuft, der Listener
   horcht auf TCP 8737.
3. Der echte Organizer hat über HTTP gepaart; beide Seiten zeigten denselben
   sechsstelligen Code (833 260) und denselben Fingerabdruck.
4. Der Organizer hat eine verschlüsselte Notiz geschickt – sie steht in der
   Liste, gekennzeichnet als *Magnolienbaum*.
5. Eine Notiz vom Handy weitergegeben – sie kam beim Organizer vollständig an,
   samt `symbol` und `angelegt`.

Neue Prüfvektoren erzeugt man mit:

    python3 werkzeuge/vektoren.py app/src/test/resources/vektoren.json

---

## 6. Bauen

Voraussetzungen: Android SDK (Platform 35, Build-Tools 35), JDK 17, Gradle 8.13.

    ./gradlew :app:assembleDebug     # entwickeln
    ./gradlew :app:testDebugUnitTest # prüfen
    ./gradlew :app:assembleRelease   # ausliefern

Die Release-APK wird ausschließlich mit dem eingerichteten Produktionsschlüssel
signiert; ohne ihn wird der Release-Bau abgewiesen. Eine frühere, mit dem
Android-Debugzertifikat signierte APK kann wegen Androids Signaturprüfung nicht
direkt aktualisiert werden. Sie muss separat deinstalliert werden; dabei löscht
Android deren lokale App-Daten. Deshalb gibt es für diesen Signaturwechsel kein
Datenverlustversprechen.

Das Releasegate verlangt `MAGNOLIE_RELEASE_CERT_SHA256` und vergleicht den
Produktionsfingerabdruck. Zu jeder mit `MAGNOLIE_PREDECESSOR_APK` angegebenen
Vorgänger-APK muss ihr erwarteter Fingerabdruck zusätzlich und zwingend als
`MAGNOLIE_PREDECESSOR_CERT_SHA256` angegeben sein; beide Produktionssignaturen
müssen identisch sein. Die erste so signierte Produktionsfassung ist nicht als
In-place-Upgrade der älteren Debugbuilds zu verstehen: Debug- und
Produktionszertifikat sind absichtlich verschieden, daher verlangt Android dort
eine Deinstallation mit Löschung der alten App-Daten. Installierte Starts laufen ausschließlich über
`MAGNOLIE_ANDROID_TEST_SERIAL` zusammen mit
`MAGNOLIE_ANDROID_TEST_DEVICE_CONFIRMED=1` oder über ein dediziertes lokales
`MAGNOLIE_ANDROID_TEST_AVD`. Ohne Testgerät schließt das Gate; das offizielle
`werkzeuge/release-gate.sh` bietet keine Überspringmöglichkeit. Ein externes
oder physisches Gerät wird nur mit `MAGNOLIE_ANDROID_TEST_DEVICE_CONFIRMED=1`
verändert; ein ausdrücklich benanntes dediziertes AVD darf das Gate verwalten.

* `minSdk` 26 (Android 8.0), `targetSdk` 35
* Kotlin 2.0, Jetpack Compose, kotlinx.serialization
* BouncyCastle nur für X25519 und HKDF; AES-GCM und HMAC kommen aus der
  Plattform

---

## 7. Aufbau

    app/src/main/java/io/gitlab/maik3531/magnolienotes/
      MagnolieApp.kt          Anwendung, legt die Baumidentität an
      MainActivity.kt         Die drei Blätter: Notizen, Übernehmen, Baum
      FreigabeActivity.kt     Ziel von „Teilen“
      daten/
        Modell.kt             Notiz, Anhang, Partner, Sendung, Sinnbilder
        Ablage.kt             JSON-Ablage, atomar geschrieben
      aufgaben/
        Erinnerung.kt         Wecker, Meldungen, Neustartfestigkeit
      einfuhr/
        Einfuhr.kt            Erkennung und Aufnahme
        Leser.kt              Die Leser der einzelnen Formate
        Rohnotiz.kt           Zwischenform
      baum/
        Kanonisch.kt          Pythons json.dumps, zeichengenau
        Krypto.kt             X25519, HKDF, HMAC, AES-256-GCM
        Paarung.kt            Paarungsdatei Fassung 2, beide Rollen
        Sitzung.kt            baum-fs1, beide Rollen
        Baum1.kt              der ältere Umschlag
        Nutzlast.kt           Notiznutzlast und HTML-Filter
        Transport.kt          WLAN (HTTP) und Bluetooth (RFCOMM)
        Server.kt             Empfangsdienst und UDP-Ruf
        Entdeckung.kt         DNS-SD über NsdManager
        Versand.kt            Zustellung, Paarungsabläufe
        Baumwerk.kt           Die Schaltstelle
        BaumDienst.kt         Vordergrunddienst
        BluetoothHorcher.kt   RFCOMM-Gegenstelle
      ui/                     Thema, Bausteine, Blätter, Sinnbilder
                              (NotizBlatt, AufgabenBlatt, EinfuhrBlatt, BaumBlatt)

---

## 8. Darstellung auf dem Gerät

Ab Android 15 zeichnen Apps grundsätzlich bis unter Status- und
Navigationsleiste. Der Ledereinband reicht bewusst dorthin – Titel und Register
werden aber um die Systemränder herum eingerückt, damit sie weder von der Uhr
noch von den Navigationsknöpfen überdeckt werden. Geprüft mit Gesten- **und**
Drei-Knopf-Navigation. Die Schreibblätter weichen zusätzlich der Tastatur aus,
sodass *Sichern*, *Weitergeben* und *Löschen* immer erreichbar bleiben.

## 9. Grenzen, offen benannt

* Fremde Notiz-Datenbanken bleiben ohne Root verschlossen (siehe Abschnitt 1).
* `.sdocx` von Samsung ist ein undokumentiertes Archivformat. Die App holt
  heraus, was an lesbarem Text darin steckt; verlässlich ist der Export als
  Text/HTML.
* ColorNote sichert verschlüsselt; nur der Export als Text lässt sich lesen.
* Bluetooth sendet in dieser Fassung von der App zum Organizer; für den Rückweg
  vom Organizer zum Handy bleibt WLAN erforderlich.
* Der Transport ist HTTP, nicht HTTPS – wie im Organizer. Die Nutzlast ist
  innerhalb des Protokolls verschlüsselt und beglaubigt; Adressen, Ports,
  Größen und Zeitpunkte sind es nicht.
* `baum-1` hat keine Forward Secrecy und keinen kryptografischen Zustellbeleg.
  Wo es geht, `baum-fs1` über die Paarungsdatei benutzen.
* Der Empfangsdienst läuft nur, solange der Vordergrunddienst läuft. Android
  kann ihn bei sehr knappem Speicher dennoch beenden; er startet dann beim
  nächsten Öffnen der App wieder.
* Es gibt kein CRDT: bei gleichzeitiger Änderung auf beiden Seiten gewinnt die
  höhere Fassung, die andere geht verloren. Das ist dasselbe Verhalten wie im
  Organizer.
