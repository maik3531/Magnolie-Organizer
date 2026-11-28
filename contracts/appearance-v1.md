# Passive Magnolie-Darstellung (Refs #432)

Linux und Windows verwenden denselben begrenzten Web-Darstellungsbaustein
`appearance.js`. Er enthält ausschließlich selbst gezeichnete Vektorformen und
reine Datum-/Darstellungsregeln. Das vom Nutzer gezeigte Stockbild wird nicht
kopiert oder als Programmbestandteil übernommen.

## Saison und Wochenansicht

- 6.–29. Dezember: dezente sechsarmige Eiskristalle auf dem grünen Hintergrund
  nur bei explizit ausgewähltem Land DE, AT, CH, LI, LU, BE, NL, PL oder CZ.
  Ohne Auswahl und bei klimatisch gemischten Ländern ohne regionale Auswahl
  (FR, IT, ES) sowie anderen Ländern keine Eiskristalle. Diese konservative
  Dekorationsregel ist keine Wettervorhersage; weder Sprache noch Standortdienste
  bestimmen sie. Die bestehende explizite Entwicklervorschau bleibt möglich.
- 30. Dezember–1. Januar: Sterne; sie haben am überlappenden 30. Dezember Vorrang.
- 28 statische, unterschiedlich große Elemente, jeweils höchstens 35 CSS-Pixel
  und zusätzlich auf 1 cm CSS-Maß begrenzt; keine Animation/zusätzliche Uhr.
- Wochen-Tagesfelder verwenden das ausdrücklich gewählte Feiertagsland und
  das Datum des dargestellten Tages. Ohne bekanntes Land erscheint kein
  automatisches Festtagsmotiv. Für die zwölf derzeit auswählbaren Länder
  bleiben die bisherigen westlichen Motive vorläufig erhalten; ihre genaue
  regionale und kulturelle Zuordnung bleibt offen (#853).
- Neue verifizierte nationale Festidentitäten: Schweiz (1. August, Laterne,
  landesweit seit 1994); Frankreich (14. Juli seit 1880, Kokarde); Niederlande
  (Koningsdag, Krone, seit 2014 am 27. April bzw. am Samstag 26. April bei
  Sonntag); Deutschland (3. Oktober ab 1990, Brandenburger Tor) und Österreich
  (26. Oktober ab 1965, Parlamentsmotiv), Belgien (21. Juli ab 1890,
  dreigeteiltes Festbanner), Luxemburg (23. Juni, Konzert-/Feuerwerksmotiv,
  konservativ ab 1964 wegen abweichender Angaben zum ersten Sommertermin),
  Italien (Republikfest, Wahlurne), Polen (11. November 1937/38 und ab
  1989, zweigeteiltes Festbanner), Liechtenstein (15. August ab 1940,
  Höhenfeuer mit stilisierter Feuerkrone), Tschechien (28. Oktober ab 1993,
  Proklamation und Flagge) und Spanien (12. Oktober ab 1982, Festbanner).
  Tschechiens Motiv gilt für die heutige Republik und erinnert an die
  Staatsgründung von 1918. Spaniens Motiv folgt dem Festdatum auch dann,
  wenn ein arbeitsfreier Ersatztermin anders liegt.
  Das italienische Motiv folgt dem 2. Juni ab den belegten Feiern 1947/48,
  1977–2000 dem ersten Junisonntag mit der gesetzlichen Ausnahme am
  2. Juni 1986 und seit 2001 wieder dem 2. Juni.
  Die Regeln sind unabhängig von
  Programmsprache und funktionieren offline. Sie erzeugen keine Kalenderdaten, ändern keine Schalter und
  leiten keine Zugehörigkeit aus Namen, Sprache oder Religion ab.
- Am 6. Januar erscheinen bei ausdrücklich gewähltem Feiertagsland zwei
  kulturelle Motive: Spanien zeigt zum Día de Reyes drei Kronen, Stern und
  Geschenke (ab 1984); Italien zeigt zur Befana Strumpf und Besen (ab 1986).
  Die Jahresgrenzen sind konservative Anzeigegrenzen für den belegten
  modernen Zeitraum. Die Motive treffen keine Aussage über Arbeitsfreiheit.
  Quellen: [spanisches Tourismusportal](https://socialnewsroom.spain.info/three-kings-day-in-spain-2024/),
  [BOE, Real Decreto 2001/1983, Art. 45](https://www.boe.es/eli/es/rd/1983/07/28/2001),
  [italienisches Tourismusportal](https://www.italia.it/it/italia/cosa-fare/storia-ed-eventi-per-la-befana)
  und [italienischer Präsidialerlass 792/1985](https://presidenza.governo.it/USRI/confessioni/norme/85DPR792prn.html).
- Quellen Italien: [Dekret 387/1947](https://www.gazzettaufficiale.it/eli/id/1947/05/31/047U0387/sg),
  [Festgeschichte des Verteidigungsministeriums](https://www.difesa.it/primopiano/verso-il-2-giugno-la-storia-dello-sfilamento-su-via-dei-fori-imperiali/34716.html),
  [Gesetz 260/1949 mit Verweis auf 54/1977 und 336/2000](https://presidenza.governo.it/ufficio_cerimoniale/normativa/legge_19490527_260.pdf),
  [Gesetz 200/1986](https://www.gazzettaufficiale.it/eli/id/1986/05/23/086U0200/sg).
  Polen: [Gesetz von 1937](https://eli.gov.pl/eli/DU/1937/255/ogl),
  [Wiederherstellung 1989](https://eli.gov.pl/eli/DU/1989/34/ogl).
  Liechtenstein: [Regierungsbeschluss 1940](https://e-archiv.li/textDetail.aspx?backurl=auto&eID=1&etID=41401),
  [Gesetz von 1990](https://www.gesetze.li/chrono/pdf/1990034000) und
  [offizielles Festprogramm mit der Krone auf Tuass](https://staatsfeiertag.li/).
  Tschechien: [Fortführung des Feiertags nach der Staatsteilung](https://www.mo.gov.cz/en/ministry-of-defence/newsroom/news/five-hundred-new-soldiers-take-oath-on-the-national-holiday--61702/).
  Spanien: [Königliches Dekret 3217/1981](https://www.boe.es/eli/es/rd/1981/11/27/3217/con)
  und [Gesetz 18/1987](https://www.boe.es/eli/es/l/1987/10/07/18/con).
- Quellen: https://www.aboutswitzerland.eda.admin.ch/en/national-holiday-and-national-anthem ,
  https://www.info.gouv.fr/actualite/pourquoi-le-14-juillet-est-il-notre-fete-nationale ,
  https://www.royal-house.nl/topics/monarchy/king%E2%80%99s-day ,
  https://www.royal-house.nl/latest/news/2013/1/28/kings-day-on-27-april-from-2014 ,
  https://www.bundesregierung.de/breg-de/schwerpunkte/deutsche-einheit/fotoreihe-wiedervereinigung-442686 und
  https://www.parlament.gv.at/en/experience/events/1285635 ,
  https://www.monarchie.be/en/monarchy/events-linked-monarchy ,
  https://www.belgium.be/fr/la_belgique/connaitre_le_pays/la_belgique_en_bref/symboles/drapeaux ,
  https://luxembourg.public.lu/en/society-and-culture/political-system/symbols-dynasty.html und
  https://luxembourg.public.lu/en/vivre/quality-of-life/jours-feries-legaux.html .
  Automatische Vorschau mit gewähltem Land und Testdatum; bisherige explizite
  Übersteuerungen bleiben erhalten. Weitere Festidentitäten und Provider
  sind Folgearbeit (#853/#854).
- Die Motive sind sehr schwache Magnolie-farbene Schatten, nicht interaktiv und
  für assistive Technik ausgeblendet. Sie werden nicht mitgedruckt. Die bestehende
  Datumswechselprüfung aktualisiert den Saisonhintergrund auch dann, wenn ein
  ungespeicherter Editor den normalen Seitenneubau verhindert.

## Entwicklermodus

Eine mit `TEST` und einem ausdrücklichen Simulationshinweis gekennzeichnete
visuelle Vorschau bietet:

- keine/Notes/KDE Connect/beide Verbindungstypen im Vorschau-Symbol;
- Blüte/Kamera/Smartphone und unabhängig Synchronisierungspfeile;
- automatische/keine/Eiskristall-/Sterndekoration;
- automatische/keine/einzelne Feiertagsmotive, einschließlich aller zwölf
  Nationalmotive und der beiden Motive für den 6. Januar, sowie ein Testdatum;
- Zurücksetzen. Sperren, neuer Buchkontext und Abschalten des Entwicklermodus
  verwerfen die Übersteuerung ebenfalls; verspätete alte Bedienelemente greifen
  nicht mehr ein.

Die gewöhnlichen Vorschauauswahlen besitzen keine Verbindungs-/Berechtigungs-API,
keine Speicherung und keine eigene Uhr. Sie ändern weder Notizen noch echte
Synchronisierungszustände und starten keine Kamera oder Spiegelung.

Zusätzlich gibt es in beiden Desktop-Oberflächen einen ausdrücklichen Knopf
`TEST · OS-Tray-Symbol (60 s)`. Nur dieser sendet einen schmalen visuellen
Testauftrag an den nativen Host. Der Host prüft den tatsächlich gespeicherten
Entwicklermodus und den entsperrten Buchkontext selbst; ein vom Browser behaupteter
Entwicklermodus oder ein Bereitschafts-/Berechtigungsfeld reicht nicht aus.
Akzeptiert werden ausschließlich vier Verbindungsfarben, drei Symbolformen und
ein echter boolescher Pfeilzustand. Es gibt keine Transport-/Berechtigungssetter.

Die native Test-Lease endet nach 60 Sekunden anhand monotoner Zeit, bei Sperre,
Abschalten des Entwicklermodus, anderem gespeicherten Buchkontext oder explizitem
Zurücksetzen. Auch eine zwischenzeitlich neu gespeicherte Buchfassung beendet
den Test vorsorglich. Der native zeitliche Wächter läuft ausschließlich während
eines Tests und wird danach entfernt/gestoppt; eine ausgebliebene Browsermeldung
kann ihn nicht verlängern. Das native Tray wird als `TEST` bezeichnet; vorhandene
Benachrichtigungszähler bleiben erhalten. Die echten Verbindungs-/Arbeitsbesitzer
werden nicht verändert und bestimmen nach Testende wieder das Icon.

## Native Linux-Verbindungsanzeige

Der Linux-Tray liest inzwischen die tatsächlichen nativen Notes-Transportzustände
und eine eigene schmale KDE-Verbindungsprojektion. Bloße Kopplung, Discovery,
fremde Zertifikate oder beendete Worker zählen nicht als Verbindung. Der normale
KDE-Statusaufruf wird hierfür ausdrücklich nicht verwendet, da er den direkten
Transport starten könnte. Die neue Projektion startet keinen Dienst und erzeugt
keine Identität: direkt prüft sie aktuelle bestätigte TLS-Besitzer samt Zertifikat,
beim Systemdienst fragt sie mit `NO_AUTO_START` nur gekoppelte erreichbare Geräte
ab und prüft den unveränderten Dienstbesitzer. Der lokale IPC-Aufruf akzeptiert
keine vom Browser vorgegebenen Verbindungswerte.

Die Blüte wird bei Notes weiß, bei KDE gelb und bei beiden orange. Goldrahmen und
das tatsächliche Buch bleiben erhalten; ohne Verbindung/Aktivität wird exakt der
bisherige ursprüngliche Icon-Name verwendet. Synchronisierungspfeile bleiben
unabhängig von der Farbe. Zusätzlich zum vorhandenen echten Medienworkerstatus
ist der tatsächlich laufende allgemeine Syncworker berücksichtigt; dessen Ende
versteckt keinen anderen weiterhin laufenden Medienworker.

KDE-Verbindungs-/Dienstbesitzerereignisse sowie Notes-Ereignisse veranlassen eine
frische native Abfrage, statt veraltete Ereignisnutzlasten als Zustand zu nehmen.
Native D-Bus-Abonnements werden beim Beenden entfernt. Die Vektordarstellung kann
eine Kamera anstelle der Blüte oder ein Smartphone anstelle des ganzen Buchs
zeichnen; derzeit fehlen weiterhin echte Kamera-/Spiegelungsproducer. Dafür wird
kein aktiver Zustand oder funktionierender Backendbetrieb erfunden.

## Native Windows-Verbindungsanzeige

Auch Windows projiziert jetzt tatsächliche Notes-Onlinebesitzer und aktuelle,
nicht geschlossene KDE-TLS-Verbindungen mit bestätigtem aktuellem Zertifikat.
Dabei werden weder die Lazy-Fassade noch deren Backend durch die Anzeige erzeugt.
Eine KDE-Verbindung muss dafür ausdrücklich kein SMS-Plugin anbieten.
Ereignisse planen eine zusammengefasste frische Abfrage auf dem UI-Thread;
Ereignisnutzlasten dienen nicht als Verbindungsnachweis.

Der bestehende allgemeine Syncbesitzer und eigene kurzlebige Aktivitäts-Leases
der tatsächlich zugelassenen manuellen/automatischen Medienläufe steuern die
Pfeile unabhängig. Der gemeinsame Medienworker allein gilt nicht als Abgleich,
weil ihn auch lokale Vorschau-/Wiederherstellungsoperationen verwenden.
Die Anzeige hält ohne Verbindung/Aktivität das ursprüngliche Icon-Objekt.
Erzeugte Icons gehören der Anzeige, ersetzte werden freigegeben; der Renderer
klont native HICONs und gibt deren ursprüngliche Handles ausdrücklich frei.
Blütenfarbe, Kameraersatz und Smartphoneersatz sind nativ zeichnungsfähig;
Kamera-/Spiegelungsbetrieb wird weiterhin nicht erfunden.

Die produktive Drawing-Assembly wurde auf dem bestehenden isolierten nativen
Windows-Prüfpfad ohne Installation geprüft: 24 Varianten, tatsächliche
Blütenfarbpixel, erhaltene Rahmen-/Bindungs-/Buchpixel außerhalb der Blüte und
80 wiederholte Erzeugungen ohne anwachsende GDI-/USER-HICON-Ressourcen.
Eine separate echte TLS-Probe prüft Kopplung ohne Verbindung, Nicht-SMS-Verbindung,
aktuelles/fremdes Zertifikat, entzogene Bestätigung und Entfernen. Die passive
Lazy-Fassade und überlappende/doppelt beendete Aktivitäts-Leases sind ebenfalls
geprüft. Eine installierte visuelle Taskleistenabnahme ersetzt das nicht.

## Persönliche Daten und Zeiterfassung

Zusätzlich zu Medien und allgemeinem GUI-Abgleich werden die tatsächlich
schreibenden persönlichen-/Zeit-/Akteur-Nachrichten erfasst. Beide Plattformen
verwenden dieselbe ausdrückliche Liste von 17 vorhandenen Datennachrichten;
Einstellungen, bloße Modi, Heartbeats, Diagnoseabfragen, unbekannte Nachrichten
und Timer-Fernsteuerung zählen nicht. Die Sende-Lease beginnt erst nach Aufnahme
in den tatsächlichen verschlüsselten Schreiber, nicht schon beim Einreihen oder
Warten auf seine Sperre. Sie bleibt bis zum abgeschlossenen oder fehlgeschlagenen
Schreiben bestehen. Zugelassene Empfangsverarbeitung und native Zeit-Commitarbeit
werden ebenfalls erfasst. Ein wartender dauerhaft gespeicherter Auftrag ist
ausdrücklich kein laufender nativer Arbeiter.

Linux verwendet eine eigene schmale native Aktivitätsprojektion samt ausschließlich
lesendem IPC-Aufruf. Sie nimmt nicht den allgemeinen Telefonservice-Monitor, den
ein älterer Sender während Netzwerk-I/O halten kann: das neue Start-/Endereignis
darf deshalb keinen vollständigen Telefonbericht auf dem GUI-Thread anfordern.
Die Oberfläche fragt den aktuellen unabhängigen Zähler neu ab und vereinigt ihn
erst beim Zeichnen mit den weiterhin laufenden Medien-/GUI-Besitzern. Es werden
keine neuen Transportdienste, Statusabonnements oder Pollingtimer erzeugt.

Prüfungen blockieren den tatsächlichen verschlüsselten Schreiber, erzeugen
Schreibfehler und prüfen überlappende Besitzer, doppelte Endmeldungen,
beeinträchtigte Darstellungsbeobachter und die lesbare native IPC-Projektion bei
gesperrtem Servicemonitor. Native Zeit-Empfangs-/Commit- und Akteur-Empfangsfälle
prüfen die tatsächlichen Verarbeitungsbesitzer; vorhandene Protokoll-, Zustimmungs-
und Empfangsregressionen bleiben erhalten. Dies ändert weder Empfangszustimmung
noch die weiterhin geschlossene gemeinsame Medien-Runtime.

## Nachweise und offene Abnahme

Reine Regeln prüfen alle vier Farbkombinationen, strenge echte Booleans statt
Kopplungs-/Wahrheitswerten, die Datumsgrenzen, Ostern in März/April und 24
Symbolvarianten. Der echte Oberflächenharness prüft Linux/Windows jeweils en/de:
Wochenmotiv, Entwicklervorschau, Größenbegrenzung, unveränderte Daten/keine nativen
Befehle beim bloßen Umschalten und Zurücksetzen beim Sperren/Deaktivieren. Der
ausdrückliche OS-Knopf prüft exakt den visuellen Auftrag, Ablehnung ohne
gespeicherten Entwicklermodus, Ablaufmeldung und Zurücksetzen beim Sperren;
verspätete Bestätigung reaktiviert die gesperrte Vorschau nicht. Native Tests
prüfen die gespeicherten Gates, alle 24 Typkombinationen, exakte Fristgrenzen,
entzogenen Modus, neuen Buchbesitzer und abgewiesene Fremdfelder. Linux prüft
zusätzlich die tatsächliche GTK-Methodenverknüpfung bis zum erzeugten Test-Icon
und Wiederherstellen des echten aktuellen Icons samt Zähler. Die bestehenden vollständigen
Linux-JS-Prüfungen und Desktop-Zustandsregressionen bestehen ebenfalls.

Zusätzliche Linux-Prüfungen lesen native Projektions-/IPCpfade und dekodieren die
wirklichen erzeugten SVGs als 32-Pixel-Raster. Sie prüfen die Farbkombinationen,
unveränderten Rahmen, Ereignisfrische, Workerende und Beibehalten des ursprünglichen
Icons. Bestehende KDE-Pairing-/Verbindungsregressionen bestehen ebenfalls.

Die 16 zusätzlichen Vorschau-/Saisonbegriffe einschließlich des nativen Testknopfs
und seiner Ablehnung sind in allen 19 vorhandenen Sprachkatalogen beider Desktops
enthalten. Vorhandene Übersetzungen bleiben unverändert; die bestehenden
PO-Compiler prüfen und erzeugen die Laufzeitkataloge. Ein eigener Vergleich prüft
die neuen Begriffe in beiden Desktops, der tatsächliche UI-Harness alle 20 Sprachen
einschließlich Englisch, insgesamt 40 Kombinationen. Das ersetzt keine
muttersprachliche redaktionelle Abnahme.

Das ist keine installierte Tray-/GUI-/Paketabnahme; eine visuelle native Abnahme
bleibt offen. Die Anzeige erfasst aktuelle native Arbeit, nicht eine zeitlich
künstlich verlängerte Erfolgsmeldung nach bereits beendeten kurzen Vorgängen.
Tatsächliche Kamera-/Spiegelungsbereitschaft
wird nicht freigeschaltet.
