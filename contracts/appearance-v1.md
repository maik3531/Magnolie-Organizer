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

Der Baustein besitzt keine native Brücke, keine Verbindungs-/Berechtigungs-API,
keine Speicherung und keine eigene Uhr. Vorschauauswahlen ändern weder Notizen
noch Synchronisierungszustände und starten keine Kamera oder Spiegelung.
Die Symbol-Testvorschau bleibt derzeit innerhalb der Entwickleransicht; eine
abgesicherte Testübersteuerung des echten OS-Trays ist noch nicht angeschlossen.

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

**Die entsprechende native Windows-Trayanbindung bleibt offen.**

## Nachweise und offene Abnahme

Reine Regeln prüfen alle vier Farbkombinationen, strenge echte Booleans statt
Kopplungs-/Wahrheitswerten, die Datumsgrenzen, Ostern in März/April und 24
Symbolvarianten. Der echte Oberflächenharness prüft Linux/Windows jeweils en/de:
Wochenmotiv, Entwicklervorschau, Größenbegrenzung, unveränderte Daten/keine nativen
Befehle und Zurücksetzen beim Sperren/Deaktivieren. Die bestehenden vollständigen
Linux-JS-Prüfungen und Desktop-Zustandsregressionen bestehen ebenfalls.

Zusätzliche Linux-Prüfungen lesen native Projektions-/IPCpfade und dekodieren die
wirklichen erzeugten SVGs als 32-Pixel-Raster. Sie prüfen die Farbkombinationen,
unveränderten Rahmen, Ereignisfrische, Workerende und Beibehalten des ursprünglichen
Icons. Bestehende KDE-Pairing-/Verbindungsregressionen bestehen ebenfalls.

Das ist keine installierte Tray-/GUI-/Paketabnahme. Die neuen zusätzlichen
Vorschaubegriffe sind derzeit deutsch/englisch enthalten; weitere Kataloge und
eine visuelle native Abnahme bleiben offen, ebenso die Windows-Trayanbindung
und native OS-Testübersteuerung. Tatsächliche Kamera-/Spiegelungsbereitschaft
wird nicht freigeschaltet.
