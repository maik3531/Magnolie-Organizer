# Passive Magnolie-Darstellung (Refs #432)

Linux und Windows verwenden denselben begrenzten Web-Darstellungsbaustein
`appearance.js`. Er enthält ausschließlich selbst gezeichnete Vektorformen und
reine Datum-/Darstellungsregeln. Das vom Nutzer gezeigte Stockbild wird nicht
kopiert oder als Programmbestandteil übernommen.

## Saison und Wochenansicht

- 6.–29. Dezember: dezente sechsarmige Eiskristalle auf dem grünen Hintergrund.
- 30. Dezember–1. Januar: Sterne; sie haben am überlappenden 30. Dezember Vorrang.
- 28 statische, unterschiedlich große Elemente, jeweils höchstens 35 CSS-Pixel
  und zusätzlich auf 1 cm CSS-Maß begrenzt; keine Animation/zusätzliche Uhr.
- Wochen-Tagesfelder: Stiefel am 6. Dezember, Weihnachtsmann am 24. Dezember,
  Rakete am 31. Dezember, Sektglas am 1. Januar, Eier am gregorianischen Ostersonntag
  und Ostermontag. Die Motive richten sich nach dem dargestellten Tag, nicht nach
  angelegten Feiertags-/Termindatensätzen. Der Osterumfang ist die derzeitige
  Auslegung von „zu Ostern“ und kann bei anderer Nutzerpräferenz angepasst werden.
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
- automatische/keine/einzelne Feiertagsmotive und ein Testdatum;
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

Das ist keine installierte Tray-/GUI-/Paketabnahme. Die neuen zusätzlichen
Vorschaubegriffe sind derzeit deutsch/englisch enthalten; weitere Kataloge und
eine visuelle native Abnahme bleiben offen. Die vollständige Aggregation weiterer
persönlicher-/Zeit-Abgleichsakteure bleibt gesondert offen; die vorhandenen
Medienläufe und der allgemeine GUI-Abgleich sind angebunden.
Tatsächliche Kamera-/Spiegelungsbereitschaft
wird nicht freigeschaltet.
