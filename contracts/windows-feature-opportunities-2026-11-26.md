# Windows: konkrete Erweiterungen für Entsperren, Wiederherstellung und Geräte

Stand: 2026-11-26. **Vertragsentwurf, keine implementierte Hello-, Passkey- oder NFC-Funktion.** Gelesener Produktstand: `0dfeb1b30a208480eb6901e3d3148a5efeaae5ff`. Die Recherche umfasst Windows-Quellen und offizielle API-Dokumentation. Hier wurden weder Windows, ein TPM, ein NFC-Leser noch ein Sicherheitsschlüssel ausgeführt. Alle nachstehenden Abnahmen sind Arbeitsaufträge, keine bestandenen Tests.

Die Hardware- und Telefonseite wird ergänzend in [windows-dell-nfc-research-2026-11-26.md](windows-dell-nfc-research-2026-11-26.md) behandelt. Die vorhandene Dell-NFC-Ausstattung allein belegt keine Kompatibilität mit einem bestimmten FIDO2-Schlüssel. Für iPhone-Verbindungen bleibt die Vorgabe bestehen: vorhandene Apps und deren tatsächlich unterstützte Wege nutzen; keine eigene Notes-App voraussetzen.

## 1. Bereits vorhandene Grundlage

Alle folgenden Pfade beziehen sich auf `magnolie-organizer-windows/` am genannten Commit.

| Befund | Konkreter Quellbeleg | Bedeutung für Erweiterungen |
|---|---|---|
| Version 2 verschlüsselt Inhalte mit einem zufälligen 32-Byte-Datenschlüssel (DEK); eine getrennte Passwortableitung schützt diesen Schlüssel. | `EncryptionService.cs`, `DataAlgorithm`, `Enable`, `Wrap`, `EncryptData`; insbesondere Zeilen 11–13, 39–74, 116–143 und 202 ff. | Zusätzliche Entsperrwege können denselben DEK umhüllen. Das portable Passwortformat muss dafür zunächst nicht ersetzt werden. |
| Die 16-Byte-`dekKennung` wird geprüft und in authentifizierten Zusatzdaten verwendet. Ein Passwortwechsel umhüllt denselben DEK erneut. | `EncryptionService.cs`, `ChangePasswordWithSession`, `RewrapEnvelope`, `DecryptDataWithSession`. | Gerätefreigaben müssen an dieses konkrete Buch und diesen DEK gebunden werden. Ein Passwortwechsel widerruft bestehende alternative Schlüsselhüllen nicht automatisch. |
| Entsperren prüft die tatsächliche Entschlüsselung; Passwortänderungen verwenden einen Kandidaten und schreiben vor dem Sessionwechsel. | `BridgeDispatcher.cs`, `UnlockAsync` ab Zeile 1121, `SetPasswordAsync` ab 1192, `RemovePasswordAsync` ab 1231. | Den vorhandenen Persistenz- und Mutationsschutz erweitern; keine Freigabe nur durch ein UI-Boolean. |
| DPAPI ist für andere lokale Geheimnisse bereits vorhanden. | `TelefonStore.cs`, `KdeConnectIdentityStore.cs`, `GraphContactService.cs`, `CloudBackupService.cs`; `DataProtectionScope.CurrentUser`. | Ein lokaler Schutzadapter ist technisch anschlussfähig, aber kein bestehender Hello-Entsperrweg. |
| Archive werden passwortgeschützt erzeugt und wieder gelesen; Integrationsgeheimnisse sind ausgeschlossen. | `GesamtarchivService.cs`, `Create`, `Read`, `RejectIntegrationSecrets`; `BridgeDispatcher.cs`, `BackupAsync` ab 1269. | Echte unabhängige Wiederherstellungsproben können das vorhandene Format nutzen. `Read` akzeptiert derzeit die Plattformen `linux` und `windows`; daraus keine allgemeine Mac-Archivfreigabe ableiten. |
| KDE-Empfang hat native Angebote, gekoppelte Verbindungen, Buchbindung und Ablaufzeiten. | `KdeConnectDirectBackend.Clipboard.cs`, `CurrentClipboardReceiveProposal`, `TakeClipboardReceive`; `BridgeDispatcher.Receive.cs`, `ReceiveOwnerCurrent`; `app/web/anwendung.js`, `kdeEmpfangGeprueft`. | Text kann kontrolliert in eine neue Notiz übernommen werden, ohne ein neues Netzwerkprotokoll einzuführen. |
| Notizversand und PDF-Erzeugung sind vorhanden. | `BridgeDispatcher.NoteSend.cs:27`, `NoteSendJobs.cs`, `MainForm.cs`, `CreateNotePdfAsync` ab 632. | Windows-Teilen kann diese vorhandenen Ausgabepfade verwenden. |

Die begrenzte Suche in den Windows-Produktdateien nach `UserConsentVerifier`, `KeyCredentialManager`, `WebAuthN`, `NCrypt`, `CngKey`, `NFC`, `SmartCard` und `DataTransferManager` ergab keinen vorhandenen entsprechenden Adapter. Ebenso wurde keine `WTS_SESSION_LOCK`-/`SessionSwitch`-Anbindung gefunden. Das ist ein Quellbefund, keine Aussage darüber, was die Windows-Installation oder ein generischer künftiger WebAuthn-Pfad unterstützen könnte.

## 2. Prioritäten

| Reihenfolge | Erweiterung | Kleinster sinnvoller Umfang | Status |
|---|---|---|---|
| P1 | Lokale schnelle Entsperrung | Zusätzliche lokale Schlüsselhülle, Passwort bleibt verfügbar | DPAPI anschlussfähig; kryptografisch an Hello gebundener Pfad benötigt eigenen Nachweis |
| P1 | Sperren beim Verlassen des Geräts | Manuelle Sperre plus Windows-Sitzungssperre, konsistenter Umgang mit Entwürfen | Anschluss klar; Lebenszyklustests erforderlich |
| P1 | Wiederherstellung prüfen | Vor Einrichtung der Schnellentsperrung ein unabhängig lesbares Archiv prüfen | Vorhandenes Archivformat wiederverwenden |
| P2 | FIDO2-Schlüssel per USB/NFC | Ein Credential mit tatsächlich verfügbarer PRF-/HMAC-Funktion schützt die DEK-Hülle | API-, Token- und Transportprobe erforderlich |
| P2 | Empfangenen KDE-Text als Notiz übernehmen | Zusätzliche bewusste Aktion am vorhandenen Empfangsangebot | Ohne neue Gerätefreigabe anschlussfähig |
| P3 | Notiz über Windows teilen | Ausgewählten Text oder vorhandenen PDF-Export an Windows-Teilen übergeben | WinForms-Interop und Dateilebensdauer nativ prüfen |

Die erste Implementierung sollte Sperr- und Wiederherstellungsvertrag gemeinsam mit der lokalen Entsperrung abdecken. Eine automatische Entsperrung beim Programmstart ist eine eigene Einstellung und darf nicht unbeabsichtigt die neue Sperrfunktion aufheben.

## 3. Lokale Windows-Entsperrung mit zusätzlicher Schlüsselhülle

**Nutzen:** Das lange Organizer-Passwort muss im täglichen Betrieb seltener eingegeben werden. Windows-Anmeldung, Freigabe einer App und Entschlüsselung des Organizer-Buchs bleiben getrennte Vorgänge.

**Kleinste Umsetzung:** Einen nativen Schutzadapter für lokale Entsperrmethoden ergänzen. Nach tatsächlicher Passwortentsperrung wird eine zusätzliche Hülle des bestehenden DEK erzeugt, mit Formatversion, Buchbindung und `dekKennung`. Ein lokaler DPAPI-Adapter unter `CurrentUser` ist ein kleiner Einstieg. Die Hülle bleibt außerhalb des portablen Buchs und wird nicht in Exporte übernommen. Ein neuer nativer Entsperrpfad muss zunächst die DEK-Kennung und die authentifizierte Inhaltsentschlüsselung prüfen und darf erst danach die bestehende Session aktivieren. DEK und Passwort gelangen nicht in WebView-Nachrichten, MCP-Antworten oder Protokolle.

**Wesentliche Produktentscheidung:** DPAPI schützt normalerweise im Windows-Benutzer-/Rechnerkontext. Eine vorgeschaltete `UserConsentVerifier`-Bestätigung liefert eine Bestätigung, aber nicht automatisch einen kryptografisch daran gebundenen Datenschlüssel. Ein anderer Prozess desselben bereits angemeldeten Benutzers kann deshalb nicht allein durch diesen Dialog als ausgeschlossen gelten. Diese Variante ehrlich als lokale Komfortentsperrung bezeichnen. [M1, M4]

Ein stärkerer Pfad braucht einen gesonderten Prototyp: nicht exportierbarer TPM-/CNG-Schlüssel mit tatsächlich erzwungener Schutzrichtlinie bei der Schlüsselverwendung, oder ein Plattform-Authenticator mit nachgewiesener PRF-Unterstützung. Der Name `Microsoft Platform Crypto Provider` allein beweist keine Hello-Abfrage bei jeder Entschlüsselung. Provider, Algorithmus, Schlüsselrichtlinie und Verhalten unter Abbruch/Sperre müssen zusammen geprüft werden; nicht still auf einen Softwareschlüssel ausweichen. Die CNG-Dokumentation beschreibt unterschiedliche Provider und eine eigene UI-Schutzrichtlinie. [M2, M3]

**Akzeptanz und Regressionen:**

- Native Tests für richtige/falsche DEK-Kennung, manipulierte Hülle, falsches Buch und unpassenden Windows-Benutzer: nur der richtige Schlüssel entsperrt; jeder Fehler lässt die verschlüsselte Datei unverändert.
- Nach Beginn einer Hello-/Windows-Abfrage Buchwechsel, Restore und Sperre auslösen: das verspätete Ergebnis darf keine neue Session freigeben. `PasswordSource.cs` und vorhandene Revisionsprüfungen als Muster nutzen.
- Fehlender Provider, TPM-/Profilverlust, Abbruch und neu eingerichtetes Hello führen zum klar angebotenen Passwortweg, nicht zur Datenlöschung oder stillen Herabstufung.
- Registrierung und Entfernung von Methoden, Passwortänderung und Abschalten der Verschlüsselung erhalten eine ausdrückliche native Reauthentifizierungsregel. Die vorhandenen Methoden `ChangePasswordWithSession`/`RemovePasswordAsync` dürfen nicht versehentlich jede schwächere neue Session als ausreichende Freigabe behandeln.
- Passwortwechsel mit stabilem DEK und tatsächliche DEK-Rotation getrennt testen. Entfernen einer lokalen Hülle widerruft keine bereits kopierten alten Backups oder einen kompromittierten DEK.

Microsoft kündigt die alte interaktive DPAPI-Prompt-Struktur zur Entfernung im April 2027 ab. Für neue Implementierungen nicht darauf aufbauen. [M1]

## 4. Manuelle und automatische Sperre

**Nutzen:** Ein entsperrter Organizer bleibt nach dem Sperren oder Verlassen von Windows nicht versehentlich sichtbar und für neue Hintergrundmutationen verfügbar.

**Kleinste Umsetzung:** Ein nativer Sperrbefehl und ein Sitzungsereignis-Adapter; Windows liefert dafür `WM_WTSSESSION_CHANGE` mit `WTS_SESSION_LOCK` nach Registrierung. Ergänzend kontrolliertes Verhalten bei Standby und optional ein konfigurierbarer Leerlauftimer. [M7] Bestehende Zustände wie `currentPlainTextAvailable`, Mutationsgates und `EncryptionService.Clear` verwenden, aber das Löschen des DEK allein nicht als vollständige Sperre ausgeben.

Beim Sperren zuerst neue Aktionen schließen und die WebView verdecken. Laufende verschlüsselte Speicherung bzw. Entwurfsrettung kontrolliert abschließen, ausstehende Rückrufe entwerten und Frontend-/Editorzustand freigeben. Danach nur durch neue Entsperrung zurückkehren. Ein Speicherfehler muss erkennbar bleiben; ungespeicherte Arbeit darf nicht still verloren gehen. Vorhandene Erinnerungsdaten, Benachrichtigungen, Zwischenablage-, Telefon- und Versanddienste brauchen eine ausdrückliche Regel für den gesperrten Zustand. `RefreshReminderData` erzeugt eigene Hintergrunddaten; deren Sichtbarkeit gesondert prüfen.

**Akzeptanz:** Sperre während Editorentwurf, Save-Fehler, Import, Hintergrundabgleich und eingereihtem KDE-Angebot testen. Nach Rückkehr dürfen alte Rückrufe keinen Klartext einblenden oder speichern. RDP-/Benutzerwechsel und Standby/Resume nativ prüfen. Bei unverschlüsselten Büchern ist eine Bildschirmsperre nur Sichtschutz. Keine vollständige RAM-Löschung versprechen: .NET- und JavaScript-Zeichenketten können Kopien hinterlassen.

## 5. Wiederherstellungs- und Gerätewechselprüfung

**Nutzen:** Komfortentsperrung verursacht bei defektem Rechner, verlorenem Token oder neu eingerichtetem Windows keinen unbemerkten Verlust des einzigen Zugangspfads.

**Kleinste Umsetzung:** Den vorhandenen `.magnolie`-Export mit unabhängiger Leseprüfung in einen Einrichtungsassistenten aufnehmen. Ein frisches passwortgeschütztes Archiv erzeugen, mit einem neuen `EncryptionService` lesen und Inhalt/Schema/Hash prüfen. Die Oberfläche benennt enthaltene Daten und ausgeschlossene Integrationsgeheimnisse. Lokale DPAPI-/TPM-Hüllen und Kopplungsidentitäten werden nicht als portable Wiederherstellung ausgegeben.

**Akzeptanz:** Archiv in einem getrennten Profil ohne ursprüngliches DPAPI, Hello oder TPM öffnen; falsches Passwort, manipuliertes Archiv, älteres Backup und Passwortwechsel prüfen. Ergebnis enthält nachweisbar die erwarteten Buchdaten und erzeugt keine neue Gerätefreigabe. Eine vorhandene Datei oder ein erfolgreicher Schreibaufruf allein ist kein Wiederherstellungsbeweis. Mac-Gesamtarchivübernahme bleibt offen, solange der tatsächliche Parser-/Schemaweg nicht separat belegt ist. Wenn sämtliche Schlüssel und das Passwort verloren sind, keine Wiederherstellung versprechen.

## 6. FIDO2-Sicherheitsschlüssel über USB oder NFC

**Nutzen:** Ein physischer Sicherheitsschlüssel kann den täglichen Zugriff auf das verschlüsselte Buch freigeben. Derselbe Schlüssel kann je nach geprüfter Transportunterstützung über USB oder NFC genutzt werden.

**Kleinste Umsetzung:** Native Windows-WebAuthn-Anbindung statt einer frei navigierbaren Webseite im WebView. Für ein an die Anwendung gebundenes Credential einen öffentlichen Zufallssalt und eine authentifiziert verschlüsselte DEK-Hülle speichern. Das tatsächliche PRF-/HMAC-Ergebnis liefert das Geheimnis für die Hülle; eine gewöhnliche erfolgreiche Signatur oder Credential-ID allein ist dafür kein Ersatz. Die RP-Bindung, angeforderte Benutzerverifikation, Resultatprüfung und Salt-Abbildung gehören in den nativen Adapter. Windows hat native WebAuthn-APIs; die benötigten Erweiterungen müssen per API-Version und tatsächlicher Antwort geprüft werden. [M5, M6]

PRF und CTAP `hmac-secret` sind die relevanten standardisierten Bausteine. Ihre Verfügbarkeit ist optional; ein FIDO2-Aufdruck beweist sie nicht. PRF-Salt-Abbildung anhand der offiziellen Testvektoren prüfen, damit ein bereits umgewandelter Salt nicht versehentlich erneut gehasht wird. [F1, F2]

**Akzeptanz:**

- Auf dem konkreten Windows zuerst denselben Schlüssel über USB prüfen, dann NFC: verfügbare Erweiterung, echte Ausgabe, richtige Benutzerverifikation und erneutes Öffnen nach Neustart belegen.
- Falscher Schlüssel, gleiche Karte ohne passendes Credential, fehlende PRF-Ausgabe, Abbruch und während der Abfrage entfernter Leser dürfen keine Entsperrung auslösen.
- Zwei unabhängig registrierte Schlüssel und Passwortwiederherstellung testen. Tokenreset oder Verlust bleibt ein klarer Wiederherstellungsfall.
- Wiederholte Antworten sowie verspätete Resultate gegen Buch-/DEK-Wechsel prüfen. Keine Klartextschlüssel in Logs oder JS.
- NFC-UID, statischer NDEF-Inhalt oder ein aus solchen Werten berechneter Hash werden niemals als Schlüsselgeheimnis akzeptiert. Ein gewöhnlicher Tag darf allenfalls eine erlaubte Aktion anstoßen, die anschließend die normale Autorisierung benötigt.

**Grenze:** Ein Telefon mit NFC ist nicht automatisch dieser Authenticator. Android-HCE beschreibt eine eigene APDU-/Kartenemulationsfunktion; iOS-Hintergrundlesen von Tags beschreibt wiederum einen nutzerbestätigten Link-/App-Einstieg. Daraus folgt keine allgemeine FIDO2-, Karten- oder Passwortersatzfunktion. [A1, A2] Hardwaredetails bleiben im verknüpften separaten Bericht.

## 7. KDE-Empfang direkt als Notiz übernehmen

**Nutzen:** Einen am Handy kopierten Text mit einer bewussten Aktion als Organizer-Notiz aufnehmen. Die bestehende KDE-Verbindung genügt.

**Kleinste Umsetzung:** Beim vorhandenen Angebot zusätzlich „Als Notiz übernehmen“ anbieten. Der native Host prüft das noch gültige Angebot und liefert dessen tatsächlichen Text; weder Inhalt noch Rechte aus einer vom Frontend erfundenen Angebots-ID übernehmen. Danach den normalen Notizeditor und Speicherabschluss nutzen. Der bisherige Zwischenablageweg bleibt eine getrennte Auswahl. Keine automatische Übernahme aller künftigen Texte und keine zusätzliche Netzwerkfreigabe aus dieser Aktion ableiten.

**Akzeptanz:** Aktuelle Verbindung, gewähltes Gerät, Buchbindung und die vorhandene fünfminütige Gültigkeit bleiben wirksam. Abgelaufene/verbrauchte Angebote, Trennung und Buchwechsel werden abgewiesen. HTML bleibt Text. Doppelter Rückruf oder Wiederholung nach Save-Fehler erzeugt keine zweite Notiz. Bestehende Entwürfe behalten den Änderungsdialog; Erfolg erscheint erst nach bestätigtem Speichern. Die Systemzwischenablage bleibt beim Notizweg unverändert. Empfangene Dateien später in einen vorhandenen Importdialog zu übergeben ist eine getrennte Erweiterung, kein automatischer Bestandteil dieses Minimums.

## 8. Windows-Teilen für eine ausgewählte Notiz

**Nutzen:** Eine einzelne Notiz als Text oder PDF an eine bereits installierte Ziel-App übergeben, ohne für jeden Anbieter einen neuen Organizer-Transport einzubauen.

**Kleinste Umsetzung:** Ein expliziter „Teilen…“-Befehl mit `IDataTransferManagerInterop` am MainForm-Fenster. Nur die ausgewählte Notiz als Text oder über `CreateNotePdfAsync` als Datei bereitstellen. Microsoft beschreibt diesen Ausgangsweg auch für WinForms und nicht paketierte Desktop-Apps. [M8] Die vorhandenen Versandjobs liefern ein Muster für Status, Abbruch und temporäre Dateien; sie sind noch keine vorhandene Windows-Share-Anbindung.

**Akzeptanz:** Kein Ziel, Nutzerabbruch, gesperrtes Buch, während der Vorbereitung geänderte Notiz und PDF-Fehler geben einen passenden Zustand zurück. Keine andere Notiz wird mitgegeben. Temporäre Dateien bleiben lange genug für den Empfänger verfügbar und werden anschließend kontrolliert bereinigt. Der UI-Status lautet nach Übergabe sinngemäß „An Windows-Teilen übergeben“; eine bestätigte Zustellung darf ohne entsprechenden Beleg nicht behauptet werden.

Ein Windows-Eingang als ShareTarget ist ein zusätzlicher Packaging-/Aktivierungsvertrag und gehört nicht still in diesen kleinen Ausgangspatch. KDE Connect bleibt ein zulässiger paralleler Übertragungsweg.

## 9. Konkreter Auftrag an Codex

Je Erweiterung zuerst vorhandene Issues auf Dopplungen prüfen und einen eng begrenzten Auftrag mit obigen Abschlusskriterien anlegen. Keine Produktänderung dieses Dokuments als bereits umgesetzt markieren. Für P1 zuerst den Schutzadapter und die Quelle-/Sessionzustände mit deterministischen Tests vorbereiten; danach auf dem tatsächlichen Windows die verwendeten APIs prüfen. Für FIDO2 vor UI-Entwicklung einen kurzen Capability-Prototyp mit realem Token erstellen. Eine fehlende Erweiterung muss die angebotene Funktion gezielt deaktivieren, nicht eine schwächere Entsperrung aktivieren.

Native Testprotokolle sollen Windows-Build, Provider/API-Version, Geräte-/Treiberbezeichnung, verwendeten Transport, Quellcommit, konkrete Schritte und Ergebnisse enthalten; keine PINs, Schlüssel oder personenbezogenen Inhalte. Reine Mock-/WebView-Tests belegen weder TPM-Schutz noch Hello-Zwang oder die tatsächliche NFC-Kommunikation. Laufende Mac-Arbeit und ihre Freigabegates bleiben hiervon unabhängig.

## Offizielle Quellen

Abruf am 2026-11-26; URLs sind Belege für API-Verträge, keine Bestätigung der Gerätefähigkeiten des Nutzers.

- **M1:** Microsoft, [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata): Benutzer-/Rechnerkontext, Flags und aktueller Hinweis zur PromptStruct-Abkündigung.
- **M2:** Microsoft, [CNG Key Storage Providers](https://learn.microsoft.com/en-us/windows/win32/seccertenroll/cng-key-storage-providers): Provider und unterstützte Schlüsseloperationen.
- **M3:** Microsoft, [NCRYPT_UI_POLICY](https://learn.microsoft.com/en-us/windows/win32/api/ncrypt/ns-ncrypt-ncrypt_ui_policy): getrennte UI-Schutzrichtlinie.
- **M4:** Microsoft, [UserConsentVerifier Desktop-Interop](https://learn.microsoft.com/en-us/windows/win32/api/userconsentverifierinterop/nf-userconsentverifierinterop-iuserconsentverifierinterop-requestverificationforwindowasync): Bestätigung an ein Desktopfenster binden.
- **M5:** Microsoft, [Web Authentication API](https://learn.microsoft.com/en-us/windows/win32/webauthn/-webauthn-portal) und [WebAuthn APIs](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/webauthn-apis): native Windows-Anbindung und Authenticator-Wege.
- **M6:** Microsoft, [Assertion options](https://learn.microsoft.com/en-us/windows/win32/api/webauthn/ns-webauthn-webauthn_authenticator_get_assertion_options) und [HMAC secret salt](https://learn.microsoft.com/en-us/windows/win32/api/webauthn/ns-webauthn-webauthn_hmac_secret_salt): Versionierung, Benutzerverifikation und PRF-/HMAC-Saltwerte.
- **M7:** Microsoft, [WM_WTSSESSION_CHANGE](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change): Sitzungssperre und erforderliche Registrierung.
- **M8:** Microsoft, [Integrate with the Windows share sheet — send](https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/integrate-sharesheet-send): WinForms-/Desktop-Interop für das Teilen.
- **F1:** FIDO Alliance, [CTAP 2.3, Proposed Standard vom 2026-02-26](https://fidoalliance.org/specs/fido-v2.3-ps-20260226/fido-client-to-authenticator-protocol-v2.3-ps-20260226.html), Abschnitt 12.7: `hmac-secret`. Die zitierte aktuelle Spezifikationsfassung wird nicht pauschal als Mindestversion vorausgesetzt.
- **F2:** W3C, [WebAuthn Level 3, PRF extension](https://www.w3.org/TR/webauthn-3/#prf-extension): optionale PRF-Ergebnisse, symmetrische Schlüsselverwendung und Testvektoren.
- **A1:** Android Developers, [Host-based card emulation](https://developer.android.com/develop/connectivity/nfc/hce): eigener HCE-/APDU-Vertrag.
- **A2:** Apple, [Adding support for background tag reading](https://developer.apple.com/documentation/CoreNFC/adding-support-for-background-tag-reading): Taglesen, Nutzerinteraktion und App-/Linkweitergabe.
