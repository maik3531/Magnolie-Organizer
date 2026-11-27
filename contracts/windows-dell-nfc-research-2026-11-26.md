# Windows / Dell Precision 7540: NFC, Telefonzugriff und Authentisierung

**Stand: 26. November 2026.** Ergänzender Forschungsauftrag zur Magnolie-Übergabe:
Welche Fähigkeiten bietet der vom Nutzer genannte Precision 7540, wie könnten
Telefon und NFC sinnvoll eingebunden werden, und was wäre für einen
Passwortersatz erforderlich? Dieses Dokument beschreibt Herstellerbelege,
Grenzen und nächste Prüfungen. Es führt keine neue Produktfunktion ein.

**Prüfstatus:** Dokumentation und begrenzte Quelltextsuche wurden ausgewertet.
Der Nutzer-PC, seine Windows-Version, sein Kontotyp, die tatsächlich verbauten
Optionen, Treiber und das Telefon wurden nicht ausgelesen. Kein Gerätetest,
keine Installation, keine Registrierung und kein Entsperrversuch wurden
ausgeführt. Vorgeschlagene Fähigkeiten sind deshalb keine Abnahmezusage.

## 1. Was Dell und Windows tatsächlich dokumentieren

NFC ist kein Mac-exklusives Merkmal. Dell beschreibt für den Precision 7540
einen optionalen **ControlVault 3 Contactless Smartcard Reader with NFC**.
Genannt werden Tag-, Reader-, Writer- und Peer-to-Peer-Modus sowie NFP- und
PC/SC-Schnittstellen. 125-kHz-Proximity-Karten sind ausdrücklich ausgeschlossen.
Die Nutzerangabe eines vorhandenen NFC-Chips passt damit zu den Modellunterlagen;
welche Variante und Treiber auf seinem Rechner vorhanden sind, bleibt ungeprüft.
[S1, S2]

Windows stellt getrennte NFC-Nachrichten-, Tag-, Secure-Element- und
Smartcard-Schnittstellen bereit. Leser, Gegenstelle und Anwendung müssen das
gleiche Protokoll unterstützen. Ein aufgelegtes Telefon wird dadurch nicht
automatisch zu einem freigegebenen Datenträger. [S3]

Der 7540 besitzt laut Modellunterlagen außerdem optionale Fingerabdruck- und
IR-Kamera-Ausstattung; eine normale Webcam belegt keine IR-Kamera. Dell führt
das Modell in seiner Anleitung für ControlVault und Windows Hello auf.
NFC-Leser, Fingerabdrucksensor, ControlVault und TPM bleiben getrennt zu
prüfende Fähigkeiten. [S4]

### NFC ist nicht ARM-PAC

**NFC** bezeichnet Nahfunk. **PAC** bedeutet im zuvor untersuchten
Prozessorzusammenhang *Pointer Authentication Code*: eine AArch64-Funktion zur
Authentifizierung von Speicheradressen. Dells Prozessorliste nennt Intel-Core-
und Intel-Xeon-Modelle; die Modellreihe gehört damit zu Intel/x86-64. Ein
NFC-Chip erfüllt keine ARM64-/PAC-Voraussetzung des untersuchten xnulinux-Wegs.
Das ist keine allgemeine Aussage gegen andere Intel-Virtualisierungswege und
kein ausgelesener Befund über die konkrete CPU des Nutzers. [S2, S5]

## 2. Telefon, Tag und Dateiübertragung unterscheiden

| Wunsch | Belastbarer Umfang |
| --- | --- |
| Tag oder kontaktlose Karte lesen | Dells Spezifikation nennt passende Modi; eine Windows-Anwendung muss das konkrete Daten-/Kartenformat verstehen. [S1, S3] |
| Android per NFC ansprechen | Eine entsprechend entwickelte App kann etwa Host-based Card Emulation anbieten. Sie beantwortet ihr vereinbartes Protokoll; daraus entsteht keine allgemeine Freigabe von Kontakten, Kalendern oder internen Appdateien. [S6] |
| Android Beam verwenden | Google hat Beam mit Android 10 abgekündigt und die aktive Weiterentwicklung beendet. Optionale Herstellerunterstützung ist keine heutige Kompatibilitätszusage. Andere NFC-Funktionen sind davon getrennt. [S6] |
| iPhone per NFC ansprechen | Core NFC bietet geeigneten Apps Tag-Lese-/Schreibfunktionen; für weitere kontaktlose Transaktionen gelten gesonderte Voraussetzungen. Das ist kein allgemeiner Zugriff auf das iPhone-Dateisystem. Ein pauschales Verbot jeder Readerkommunikation wäre ebenfalls zu weitgehend. [S7] |
| Daten nach Magnolie übernehmen | Die zuständige Telefon-App muss Daten bereitstellen oder exportieren. Anschließend werden Dateiübertragung, Importvorschau und tatsächliches Speichern getrennt geprüft. |

### Unmittelbar sinnvoller Dateiweg

**KDE Connect / lokales Netz:** vorhandene passende Clients auf PC und Telefon
öffnen, Geräte im erreichbaren Netz gegenseitig koppeln und eine einzelne
Testdatei übertragen. KDE bietet Windows-, Android-, iOS- und macOS-Ausgaben;
Fähigkeiten unterscheiden sich je Plattform. Insbesondere nennt KDE für iOS
eine Grenze beim dauerhaften Hintergrundbetrieb. Empfangene unterstützte
Dateien können anschließend bewusst in Magnolie importiert werden. Eine
externe KDE-Verbindung ist noch keine direkte Magnolie-Gerätesteuerung. [S8]

**Android / USB:** Telefon entsperren, datenfähiges Kabel verwenden und am
Telefon Dateiübertragung auswählen. Eine zuvor von der jeweiligen App
bereitgestellte Datei auf Windows kopieren. **iPhone / USB:** Apples Windows-App
„Apple Devices“ tauscht Dateien mit Apps aus, die File Sharing unterstützen;
dies ist ausdrücklich appbezogen. [S9]

VCF für Kontakte oder ICS für Kalender sind mögliche Übergabeformate, wenn die
Telefon-App einen solchen Export anbietet. Telefontyp und gewünschter Inhalt
sind daher vor einem konkreten Ablauf festzustellen. Eine eigene
Magnolie-Notes-App für das iPhone wird nicht vorausgesetzt.

## 3. Passwortersatz verlangt einen kryptographischen Nachweis

Microsofts native Win32-WebAuthn-API unterstützt Windows Hello und externe
FIDO2-Authentikatoren; NFC, USB und BLE sind mögliche Transporte. Ein geeigneter
NFC-Sicherheitsschlüssel kann somit eine App authentisieren. Der eingebaute
Leser allein ist kein persönlicher Sicherheitsschlüssel, und ein erfolgreicher
Tagtest beweist noch nicht FIDO2-Kompatibilität. [S10]

| Verfahren | Bedeutung für Magnolie |
| --- | --- |
| Karten-UID oder gleichbleibender Tagtext | Auslesbarer Bezeichner beziehungsweise Inhalt. Für die Auswahl einer Ansicht oder Vorlage denkbar; allein kein ausreichender Entsperrnachweis. Windows dokumentiert UID-Lesen als Metadatenoperation. [S3] |
| Registrierter kryptographischer Schlüssel | Eine neue Challenge wird beantwortet und gegen den registrierten öffentlichen Schlüssel geprüft. Benutzerbestätigung/PIN/Biometrie und die Bindung an den vorgesehenen Vorgang müssen entsprechend dem Verfahren geprüft werden. [S10] |
| Windows Hello | Windows verifiziert PIN oder Biometrie und ermöglicht die Verwendung geschützter Schlüssel. Ob unterstützte Hardware, Einrichtung und Richtlinien vorliegen, muss tatsächlich ermittelt werden. [S11] |

Die Bewertung einer bloßen UID als unzureichend folgt aus dem Protokoll:
Ein offener Bezeichner ist kein frischer, an diesen Entsperrversuch gebundener
Schlüsselbeweis. Es wird nicht behauptet, jede Hardwarekarte lasse ihre feste
Kennung beliebig überschreiben.

### Windows-Anmeldung und verschlüsseltes Magnolie-Buch sind getrennt

Hello/WebAuthn authentisiert; daraus folgt nicht automatisch der Datenkey eines
separat verschlüsselten Magnolie-Buchs. Eine erfolgreiche Signatur oder ein
positives UI-Dialogergebnis ersetzt keinen geprüften Schlüsselverwaltungsweg.
DPAPI schützt Daten üblicherweise für denselben Benutzer auf demselben Rechner;
diese API verlangt dadurch nicht automatisch vor jeder Entschlüsselung erneut
Windows Hello. [S11, S12]

Ein zusätzlicher Magnolie-Entsperrweg muss deshalb bewusst eingerichtet, an
Buch und Profil gebunden und nativ abgesichert werden. Vorhandene
Buchverschlüsselung und Wiederherstellung bleiben erhalten. Rechnerwechsel,
Windows-/TPM-/Hello-Reset und Tokenverlust gehören zur Abnahme. Ein ungeschütztes
JavaScript-Flag darf keine neue Berechtigung zum Datenkey erzeugen. Dies sind
Anforderungen an einen Ausbau, keine Behauptung einer hier implementierten API.

Auch der Windows-Sperrbildschirm ist gesondert zu betrachten: Microsofts
Standard-Smartcard-Anmeldung ist für Domänen-/Entra-Konten beschrieben, nicht
für lokale Konten. Der dokumentierte FIDO2-Windows-Anmeldeweg verlangt passend
eingerichtete Entra-/Hybrid-Geräte. Eine NFC-Karte ersetzt deshalb nicht
automatisch jedes private Windows-Kennwort. [S13]

Ein Telefon kann bei unterstützten Plattformen auch über standardisierte
Passkey-Cross-Device-Authentisierung verwendet werden. Microsoft nennt QR-Code
und Näheprüfung; die Windows-Dokumentation verlangt dabei Bluetooth und
Internet auf beiden Geräten. Dieser Weg ist keine garantierte
Offline-NFC-Funktion. [S14]

## 4. Magnolie-Umfang und nächste Geräteprüfung

Die begrenzte Suche nach `ProximityDevice`, `SCardEstablishContext`,
`SCardListReaders`, `NfcAdapter` und NFC-Reader-Schnittstellen lieferte keinen
Nachweis eines spezifischen Dell-/PCSC-Adapters. Sonstige `NFC`-Treffer betrafen
überwiegend Unicode-Normalisierung. **Daraus folgt nicht**, dass ein vorhandener
WebAuthn-Pfad keinen vom Betriebssystem vermittelten NFC-FIDO2-Transport nutzen
könnte. Die ergänzende Windows-Codeprüfung fand derzeit keinen solchen
Hello-/CNG-/WebAuthn-Entsperrweg. Der vorhandene
[EncryptionService](../magnolie-organizer-windows/EncryptionService.cs)
verwendet das Kennwort/PBKDF2 und eine geschützte DEK-Hülle; ein zusätzlicher
nativer Komfortzugang wäre neue Implementierungsarbeit.

Ein einfacher NFC-Shortcut für eine Projektansicht oder Erfassungsvorlage wäre
ein anderer, kleinerer Funktionsumfang als eine Entsperrung. Für Telefondateien
bleibt der vorhandene LAN-/USB-Weg unmittelbar nützlicher. Allgemeine
Featurepriorisierung und der bestehende Authentisierungs-Code werden in
[Windows: Feature-Möglichkeiten und Umsetzungsgrenzen](windows-feature-opportunities-2026-11-26.md)
behandelt. Die beiden Dokumente unterscheiden belegten Bestand von neuem
Vorschlag; NFC ist keine Voraussetzung für die übrigen Verbesserungen.

Die folgende Abnahme ist **vorbereitet, nicht ausgeführt**. Sie setzt einen
ausdrücklich verfügbaren Testzugang voraus; hier wurden keine Nutzer-PC-Aktionen
ausgeführt.

| Schritt | Konkrete Prüfung | Erwarteter Nachweis |
| --- | --- | --- |
| 1. Fähigkeiten | Windows-Version/Build, Kontotyp, erkannte NFP-/Smartcard-/Biometriegeräte, passende Treiber sowie Hello-/TPM-Zustand erfassen. | Tatsächliche vorhandene Optionen; keine Ableitung allein aus dem Dell-Modellnamen. Geräte-/Kontokennungen nicht in öffentliche Logs aufnehmen. |
| 2. NFC-Lesen | Einen eigens bereitgestellten unkritischen Tag mit bekanntem Format/Inhalt lesen; Tagentfernung, unpassendes Format und Abbruch prüfen. | Exakter Inhalt oder klare Ablehnung; keine Entsperrung allein durch UID. |
| 3. Telefondatei | Je tatsächlich vorhandenem Android-/iPhone-Weg eine Testdatei bewusst freigeben; Transport, Vorschau, Import, Save-ACK und erneutes Öffnen prüfen. | Identischer übertragener Inhalt und dauerhaft bestätigter Bestand; keine automatische Freigabe anderer Appdaten. |
| 4. FIDO2/Hello | Separat eingerichteten Testschlüssel verwenden; Abbruch, fehlende Hardware, falsches Profil/Buch, alte Challenge und fehlende erforderliche Benutzerprüfung behandeln. | Nur ein frischer, korrekt gebundener Nachweis ist erfolgreich; kein UID-/UI-Erfolgsersatz. |
| 5. Datenkey/Recovery | Tatsächliche Buchentschlüsselung getrennt vom Login prüfen; Neustart, gesperrte Sitzung, Tokenverlust und Wiederherstellung auf einem zweiten Testprofil durchgehen. | Wiederherstellbarer Datenbestand ohne stillschweigende Änderung der bisherigen Verschlüsselung oder Gerätebindung. |

Eine allgemeine Dell-Anleitung mit Windows-8.1-„Tap and send“-Schritten ist kein
Beleg für denselben Ablauf unter einer heutigen Windows-/Telefonkombination.
Hardwareerkennung, Protokollerfolg und produktive Magnolie-Funktion bleiben
getrennte Ergebnisse.

## Primärquellen

Die Quellen wurden am 26. November 2026 recherchiert. Plattformvoraussetzungen
bei der späteren Geräteabnahme erneut gegen die tatsächlich verwendeten
Versionen prüfen.

- **S1 – Dell, konkrete NFC-Fähigkeiten:** [Precision 7540: Contactless smart card](https://www.dell.com/support/manuals/de-de/precision-15-7540-laptop/precision_7540_setupspecs/contactless-smart-card?guid=guid-a1eab32e-34db-4acb-84d2-db4e45d2e4fa&lang=en-us).
- **S2 – Dell, CPU und optionale Ausstattung:** [offizielles 7540-Datenblatt](https://i.dell.com/sites/csdocuments/Shared-Content_data-Sheets_Documents/en/us/861_dell_precision_7540_spec_sheet.pdf), [Prozessorliste](https://www.dell.com/support/manuals/de-de/precision-15-7540-laptop/precision_7540_setupspecs/processor?guid=guid-fa035465-9ae5-4548-b649-3489225799bc&lang=en-us).
- **S3 – Microsoft, Windows-NFC und Kartenmetadaten:** [NFC architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/nfc/nfc-architecture), [Smart card design guide](https://learn.microsoft.com/en-us/windows-hardware/drivers/nfc/design-guide-smart-card).
- **S4 – Dell, optionale IR-/Fingerprint-Wege:** [7540-Kamera](https://www.dell.com/support/manuals/en-us/precision-15-7540-laptop/precision_7540_setupspecs/camera?guid=guid-c9367232-3fd0-4d80-bbb5-51f807dc5d2d&lang=en-us), [Handballenauflage](https://www.dell.com/support/manuals/en-sg/precision-15-7540-laptop/precision_7540_setupspecs/palmrest-view?guid=guid-bf056545-b2c0-4c88-aced-2f1c82d5b655&lang=en-us), [Windows Hello und ControlVault](https://www.dell.com/support/kbdoc/en-us/000353977/how-to-determine-if-windows-hello-is-using-controlvault-for-the-fingerprint-reader?lang=en).
- **S5 – Prozessor-PAC:** [Arm Architecture Reference Manual](https://support.arm.com/documentation/ddi0487/maa/-Part-D-The-AArch64-System-Level-Architecture/-Chapter-D8-The-AArch64-Virtual-Memory-System-Architecture/-D8-10-Pointer-authentication?lang=en), [Linux-Kernel: Pointer authentication in AArch64](https://www.kernel.org/doc/html/latest/arch/arm64/pointer-authentication.html).
- **S6 – Android NFC:** [Host-based card emulation](https://developer.android.com/develop/connectivity/nfc/hce), [Android Beam deprecation](https://developer.android.com/about/versions/10/behavior-changes-all#android-beam).
- **S7 – Apple NFC:** [Core NFC](https://developer.apple.com/documentation/corenfc/), [NFC & SE Platform](https://developer.apple.com/support/nfc-se-platform/).
- **S8 – KDE Connect:** [offizielle Plattformdownloads](https://kdeconnect.kde.org/download.html), [Projekthandbuch: Kopplung, Dateiübertragung und Plattformgrenzen](https://userbase.kde.org/KDEConnect).
- **S9 – USB-Dateiwege:** [Google: Android und Computer](https://support.google.com/android/answer/9064445?hl=de-de), [Apple Devices: File Sharing unter Windows](https://support.apple.com/en-az/120402). Die englische Apple-Länderseite wurde verwendet, weil die US-URL beim Abruf HTTP 429 lieferte.
- **S10 – Standardauthentisierung:** [Microsoft: Windows-WebAuthn-APIs](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/webauthn-apis), [Win32-WebAuthn](https://learn.microsoft.com/en-us/windows/win32/webauthn/-webauthn-portal), [Passkey-Challenge und Signaturprüfung](https://support.microsoft.com/en-us/accounts-billing/security/passkeys-frequently-asked-questions-faq), [FIDO-Spezifikationen](https://fidoalliance.org/specifications/download/).
- **S11 – Microsoft, Hello für Apps:** [Schlüsselschutz und Authentisierungsablauf](https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello).
- **S12 – Microsoft, DPAPI:** [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata), [Beispiel mit Bindungs-/Wiederherstellungsgrenzen](https://learn.microsoft.com/en-us/windows/win32/SecCrypto/example-c-program-using-cryptprotectdata).
- **S13 – Windows-Anmeldekonten:** [Smartcard Technical Reference](https://learn.microsoft.com/en-us/windows/security/identity-protection/smart-cards/smart-card-windows-smart-card-technical-reference), [FIDO2-Anmeldung auf Entra-/Hybrid-Geräten](https://learn.microsoft.com/en-us/entra/identity/authentication/howto-authentication-passwordless-security-key-windows).
- **S14 – Microsoft, Telefon-Passkeys:** [Passkey erstellen/speichern](https://support.microsoft.com/en-us/accounts-billing/security/create-save-passkey), [Windows-Unterstützung und Cross-Device-Voraussetzungen](https://learn.microsoft.com/windows/security/identity-protection/passkeys/).
