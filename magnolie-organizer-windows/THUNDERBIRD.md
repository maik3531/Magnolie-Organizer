# Verwaltete Internetkonten unter Windows

## Bedienungsziel

Die Kontoeinrichtung erfolgt direkt in Magnolie unter **Einstellungen →
Synchronisation → Internetkonten**: E-Mail-Adresse eingeben, Google,
Outlook.com/Hotmail oder Microsoft 365 wählen und die normale Anbieteranmeldung
durchführen. Eine zusätzliche Thunderbird-/Add-on-Installation durch den Nutzer
ist nicht vorgesehen. Magnolie benötigt keine eigene Anbieterregistrierung.

## Hintergrundbaustein

Der Windows-Paketbau führt eine festgelegte Thunderbird-Laufzeit und angepasste
TbSync-/EAS-Komponenten mit. Die OAuth-Implementierungen und die tatsächlich beim
Anbieter verwendeten Anwendungsidentitäten dieser Komponenten bleiben erhalten.
Der Nutzer sieht im Berechtigungsdialog den tatsächlichen Anmeldeanbieter.

Magnolie bereitet ein eigenes Profil unter
`%LOCALAPPDATA%\Magnolie Internet Accounts\profile` vor. Private Thunderbird-
Profile werden nicht umkonfiguriert. Die Kontenablage liegt außerhalb des
Organizer-Datenverzeichnisses und gehört nicht in dessen Datenarchive.

Die lokale Native-Messaging-Verbindung ist auf den aktuellen Windows-Benutzer
und die Magnolie-Erweiterung begrenzt. Kontenstatusmeldungen enthalten keine
Kennwörter oder OAuth-Tokens. Persönliche und verwaltete Thunderbird-Quellen
verwenden getrennte Verbindungen und Quellenkennungen.

## Implementierungsstand

- Die Google- und Microsoft-Anmeldung unter Windows wurde vom Nutzer erfolgreich
  durchgeführt und bestätigt.
- Automatische Profil-/Erweiterungsvorbereitung und Kontoeinrichtungs-Schaltflächen
  sind im Entwicklungsstand vorhanden; die Texte sind in allen 20 Sprachen
  verfügbar.
- Google verwendet die in der Hintergrundlaufzeit vorhandene DAV-Erkennung und
  Anbieteranmeldung. Der echte Google-Abgleich bleibt bis zur Bestätigung in
  Issue #17 offen.
- Der Microsoft-Einrichtungsadapter delegiert die Anmeldung an den EAS-Anbieter
  und verbindet das angelegte Konto. **Die EAS-Datenübergabe zwischen Microsoft
  und Magnolie ist noch nicht fertig.** Anmeldung und Ordnererkennung sind kein
  bestätigter Zweiwege-Abgleich; Issue #29 bleibt offen.
- Version 2.0.20 enthält diese Grundlagen; die vollständige Kontenanbindung bleibt in Entwicklung.

## Paketbau und Quellen

`werkzeuge/account_runtime.py` verwendet festgelegte Downloadadressen und
SHA-256-Prüfsummen und bereitet die Laufzeit direkt im Windows-Ausgabeverzeichnis
vor. Der bestehende `build/Build.ps1`-Ablauf ruft dieses Werkzeug auf.
7-Zip wird nur auf dem Baurechner benötigt (`MAGNOLIE_7Z`), nicht beim Nutzer.
Heruntergeladene Originalpakete werden wiederverwendet.

Mozilla Thunderbird wird unverändert übernommen. Die Anpassungen an den
TbSync-/EAS-Komponenten sind unter `app/account-bridge` einsehbar, als Varianten
gekennzeichnet und unter MPL-2.0 verfügbar. Sie ergänzen die eingeschränkte
Kontrollschnittstelle und den direkten Anmeldeeinstieg; die Originaldatei
`oauth.mjs` wird nicht verändert. Herkunft und Lizenzhinweise liegen der Laufzeit
und den Erweiterungen bei.

Die Tests prüfen Profiltrennung, Nachrichtenrahmen, Quellenbindung, bedingte
Schreibzugriffe, anbieterabhängige Kontaktkennungen und die Beschränkung der
öffentlichen Statusdaten. Native Tests verwenden eigene Prüfprofile.
