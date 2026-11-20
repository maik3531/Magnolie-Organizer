# Notes #691: gekoppelter API-37-Migrationskandidat

Stand: 19. November 2026. Basis: `6ebaaaed896288662b26aa3c0acbf2541828591b`
aus `maik3531/Magnolie-Organizer/main`.

## Ergebnis und Geltungsbereich

Die gemeinsame Notesquelle enthält einen ausdrücklichen API-37-Prüfmodus und
zusätzliche LAN-Laufzeitsicherungen. Der normale Produktbau bleibt bis zur
nativen Abnahme auf Ziel 35. Dies ist ein Quellkandidat, keine geprüfte oder
ausgelieferte APK und kein Abschluss der nativen Kriterien aus
[Issue #691](https://github.com/maik3531/Magnolie-Organizer/issues/691).

Der vorbereitete Compilerstand aus #672 bleibt erhalten: SDK 37.2,
AGP 9.5.1, Gradle 9.6.0, Kotlin/Compilerplugins 2.4.21, JDK 21 und
Java-/Kotlin-Bytecodeziel 17. Die Mindestversion bleibt API 26.
Abhängigkeiten, STRICT-Locks und Artefaktverifikation werden nicht geändert.
Die im Issue dokumentierten früheren Build-/Unit-/Lint-/Cross-Ergebnisse sind
Nachweise des Vorgängerstands, keine erneute Prüfung dieser Änderung.

| Eigenschaft | Normaler Produktbau | Ausdrücklicher Prüfmodus |
| --- | --- | --- |
| Gradle-Eigenschaft | fehlt oder `false` | `magnolieTarget37Validation=true` |
| Ziel-SDK | 35 | 37 |
| Mindest-SDK | 26 | 26 |
| LAN-Berechtigung im Manifest | keine | `ACCESS_LOCAL_NETWORK` |
| Buildmodus | bisherige Varianten | nur bestehende Release-App-Variante |
| Signierung | bisheriges Verfahren | `magnolieFdroid=true`, unsigniert |
| Netz für Gradle | bisheriges Verfahren | `--offline` erforderlich |
| Kennzeichnung | bisherige Version | Suffix `-api37-validation`, `testOnly=true` |
| Instrumentierungs-APK | bisheriges Verfahren | Device-Test-Komponenten deaktiviert |

`finalizeDsl` setzt Ziel-/Manifestvertrag und kontrolliert minSdk, Ziel-SDK,
unsigned Konfiguration und Kandidatensuffix. Nur öffentliche AGP-DSL-APIs
werden benutzt. Es entstehen keine zusätzlichen Flavor-/Dependencyvarianten.
Der Prüfmodus erteilt keine Signier-, Installations- oder Storefreigabe.

## Laufzeitverhalten

### Sichtbare Einrichtung

`MainActivity` besitzt den Launcher unter einem stabilen ActivityResult-Schlüssel.
`LanAnfrage` erlaubt einen neuen Request nur nach einem bewussten Aufruf auf dem
Hauptthread einer sichtbaren, nicht beendeten Activity im Zustand `RESUMED`.
Das Systemergebnis wird nicht als Grant übernommen: Der Callback liest die
tatsächliche `ACCESS_LOCAL_NETWORK`-Freigabe erneut.

Die Zustandsklasse speichert keinen Peer, Auftrag, Grant, Konto-/Buchbezug und
keine Fortsetzungsfunktion. Sie kann nach einem Callback lediglich einen
sichtbaren Wartehinweis auslösen. Ein `onStop` oder neuer Intent entwertet die
Zuordnung des ausstehenden Requests, hält aber dessen OS-Ergebnisslot bis zur
Rückmeldung besetzt. Eine fehlgeschlagene Launcher-Ausführung gibt nur das
betroffene Ticket frei. Nach Destroy/Recreate wird keine alte Aktion wiederholt.
Boot, Worker und Monitore bleiben ohne Berechtigungsdialog.

Bereits bewusst eingeschaltete Dienste dürfen wartend bestehen und über ihre
vorhandenen Kontrollschleifen wieder nutzbar werden. Abgelehnte Such- oder
Kopplungsaktionen werden nicht aus einem späteren Grant rekonstruiert.
Bluetoothrechte ersetzen den tatsächlichen LAN-Grant nicht.
Auch der Einladungsempfang prüft nach blockierenden Lese-/Schreibschritten
seine Laufzeit erneut, bevor er eine Einladung zeigt oder deren Peeraktion auslöst.

### Ziele, Netzwechsel und laufende Verbindungen

Der Android-Adapter ergänzt die bisherigen IP-/Namensregeln um das tatsächliche
`Network` und dessen `LinkProperties`. Eine öffentliche Adresse ist keine
pauschale Fernausnahme. Auf WLAN-/Ethernetnetzen benötigen direkt angeschlossene
und spezifisch geroutete Ziele die LAN-Freigabe; ein bekannter Internetpfad über
ein Standardgateway kann ohne LAN-Grant weiterarbeiten. Fehlende oder unklare
Routeninformationen werden konservativ behandelt.

Der API-37-Transport bindet den Socket an genau das ausgewählte `Network` und
überwacht anschließend dieses Netz. Ein Wechsel des Standardnetzes auf Mobilfunk
oder VPN kann eine noch bestehende WLAN-Verbindung deshalb nicht nachträglich
als ungeschützten Fernzugriff einstufen. Der Hostname wird einmal aufgelöst;
verbunden wird die konkrete geprüfte Adresse. `.local`-Namen werden bereits
vor der Auflösung geprüft.

Eine `LanZielWache` begleitet auch zunächst öffentliche Fernverbindungen.
Sie prüft vor Connect, vor dem Senden und vor Annahme der Antwort erneut und
wird zusätzlich vom bestehenden Monitor beobachtet. Ein entzogenes Recht oder
eine neu lokale Route stoppt den betroffenen Lauf; Wiederfreigabe macht einen
alten Lauf nicht wieder gültig. Das Betriebssystem bleibt die abschließende
Berechtigungsinstanz; die App-Prüfung ist kein atomarer OS-Grant-Lock.

Öffentliche Ziele über Mobilfunk/VPN sind ausgenommen. Private, Loopback-,
Link-local- und Multicastziele behalten vorsorglich die bestehende strenge
Adressprüfung, auch wenn eine VPN-Route vorliegt. Spezifische öffentliche
Fernrouten können konservativ als LAN gelten. Diese Grenzen müssen in der
nativen Routingmatrix bewertet werden; sie sind keine vollständige Nachbildung
der Android-Routingentscheidung.

### Empfang und native Schreibzugriffe

LAN-Empfang ist an den tatsächlichen Listenerlauf und die Freigabegeneration
gebunden. Die Gültigkeit wird bis in den vorhandenen FS-Empfangsbeleg und die
Schreibgrenze weitergereicht. Ein bereits eingelesener Auftrag darf nach Entzug
oder nach Ersetzen des Listenerlaufs keine neue Mutation beginnen. Ein alter
Listener darf keinen neu gestarteten Lauf beenden. Gemeinsam mit Bluetooth
genutzte Sitzungstabellen und gespeicherte Pairings werden dabei nicht geleert.

Der Telefonkanal bindet entschlüsselte Aufträge an den ursprünglichen Socket
und die Sitzungs-/Pairinggeneration. TCP-Streams prüfen vor und nach I/O;
native Quellen- und Schreibgrenzen prüfen die Verbindung erneut. Wartezeiten
auf Werk-/Buchsperren dürfen einen bereits entwerteten Empfang nicht wieder
berechtigen. Bluetooth verwendet seine eigene Verbindungslebensdauer.

Die Berechtigung autorisiert ausschließlich den Netzwerktransport. Sie erfindet
keine Kontakte-, Galerie-, SEND-, Konto-, Buch- oder Synchronisationsfreigabe.
Bestehende Identitäts-, History-, Revisions-, CAS- und Widerrufsprüfungen bleiben
zusätzliche Bedingungen.

## Wiederholbare Prüfungen

Im Repository sind gezielte lokale Prüfhelfer enthalten:

```bash
python3 magnolie-notes/werkzeuge/test_target37_build.py -v
python3 magnolie-notes/werkzeuge/test_lan_request.py -v
python3 magnolie-notes/werkzeuge/test_lan_routes.py -v
python3 magnolie-notes/werkzeuge/test_lan_guards.py -v
git diff --check
```

Der Manifestprüfer testet sowohl erlaubte Ausgaben als auch falsche SDKs,
falsche Paketidentität, fehlende/doppelte LAN-Deklarationen und durchgesickerte
Kandidatenmerkmale. Seine Standardtests verwenden ausdrücklich synthetische XMLs.
Die Anforderungs- und Routenfälle führen tatsächliche Produktions-Javaklassen
mit synthetischen OS-/Netzzuständen aus. Gegenproben mit absichtlich wieder
eingebautem Public-IP-Bypass, ignorierter Route und wiederbelebtem altem Lauf
müssen scheitern. Ein JUnit-Anschluss verwendet dieselben Fälle.

In der Prüfumgebung des gelieferten Patches war Java 21 mit dem Compiler-Modul vorhanden, aber
kein vollständiges Android-SDK, keine gecachte Gradledistribution, kein Kotlin-
Compiler und keine `javac`-/`ct.sym`-Installation. Die Java-Hostprüfungen verwenden
deshalb das vorhandene `jdk.compiler` mit Source-/Bytecodeziel 17. Das ist keine
vollständige Java-17-API-Oberflächenprüfung mittels `--release 17`.
Es wurden keine SDKs oder Abhängigkeiten installiert.

### Mit dem Patch überlieferter Prüfstand vom 19. November 2026

| Prüfung | Ergebnis | Reichweite |
| --- | --- | --- |
| `test_target37_build.py` | 9 Tests bestanden | Quellverträge und Manifestprüfer; 2 positive/22 negative synthetische XML-Ausgaben |
| `test_lan_request.py` | 2 Tests bestanden; 110 Java-Assertions | Tatsächliche Request-Zustandsklasse plus Activity-Quellvertrag |
| `test_lan_routes.py` | 5 Tests bestanden; 51 Java-Assertions | Tatsächliche Routen-/Verbindungskerne, 3 erkannte Fehlermutationen und Netzbindungs-Quellvertrag |
| `test_lan_guards.py` | 15 Tests bestanden | Integration, Hintergrund-/Callbackgrenzen und 20 Sprachressourcen |
| Bestehende `LanGuardProbe` | 178 Java-Assertions bestanden | Geänderter Adresskern und vorhandenes Generationstor |
| Python-Syntax, `git diff --check`, Toolchain-/Lockvergleich | bestanden | Keine Änderung an SDK-/Wrapperkatalog, Locks oder Artefaktpins |
| 12 ergänzte Kotlin-Empfangstests | implementiert, nicht ausgeführt | 7 Baum-FS-Fälle und 5 Telefon-/Timer-/TimeSync-Fälle |
| JUnit-/Android-/Gradle-/Ownership-Gate | nicht ausgeführt | Vorhandene Kotlin-/Android-Werkzeuge fehlen hier |
| Native Geräte, Paketinstallation, Upgrade, Signierung | nicht ausgeführt | Bestehende Freigabegrenzen und fehlende Geräteabnahme |

### Lokaler Übernahmeprüfstand vom 20. November 2026

Der vorhandene Bauhost hat ein vollständiges JDK 21, die vorbereitete
Android-Plattform 37.2 und den festgelegten Gradle-Wrapper. Die obige
Werkzeugbeschränkung beschreibt die ursprüngliche Patchumgebung, nicht diesen
Bauhost. Versionskatalog, Wrapper, Locks und Artefaktprüfsummen bleiben unverändert.

Lokal bestanden sind die 9 Kandidaten-/Manifestprüfertests, 15
LAN-Integrationsverträge, 2 Request- und 5 Routenfälle einschließlich der
Routen-Fehlermutationen. Die tatsächlichen Kotlin-Akquisitionskörper und ihre
drei Cleanup-/Reihenfolge-Gegenproben wurden mit vorhandenen, hashgeprüften
Werkzeugen ausgeführt; die Java-Kerne verwenden hier `javac --release 17`.
Das bleibt ein synthetischer Hostnachweis, keine Android-Geräteabnahme.

Beide tatsächlich zusammengeführten Release-Manifeste wurden strikt offline
erzeugt und mit dem Manifestprüfer geprüft: Ziel 37 mit LAN-Deklaration,
testOnly und Kandidatenmarkierung; normales Ziel 35 ohne diese Merkmale.
Fehlende Cacheeinträge für festgelegte Build-/Testabhängigkeiten wurden separat
in der normalen Ziel35-Konfiguration mit strikter Abhängigkeitsprüfung ergänzt,
ohne Lock- oder Prüfmetadaten neu zu schreiben. App- und Testquellen kompilierten
anschließend erfolgreich. Dieser Cache-/Kompilierlauf ist kein bestandener
Unit-Testlauf und kein Ziel37-Onlinebau.

Der vollständige Offline-Kandidatenlauf führte 2.407 Tests ohne übersprungene
Fälle aus. 2.406 bestanden; allein der bisherige Versionstest erwartete die
Produktversion ohne Kandidatensuffix. Der Test wurde gezielt an die von Gradle
explizit übergebene Validierungseigenschaft gebunden: Er prüft weiterhin den
exakten Versionsnamen und Versionscode, beim Kandidaten zusätzlich den
Release-Bautyp. Dieser geänderte Test bestand anschließend separat sowohl für
Ziel37 als auch für die normale Ziel35-Konfiguration. Die unveränderten 2.406
Erfolge wurden beibehalten, nicht als neuer vollständig wiederholter grüner
Gesamtlauf ausgegeben. Die separat geführten Crossplattformklassen sind in
diesen Zahlen nicht enthalten.

`lintRelease` des Kandidaten bestand strikt offline mit 0 Fehlern und 175
Warnungen. Anschließend bestand `assembleRelease` ebenfalls strikt offline.
Die tatsächlich erzeugte APK wurde auf ZIP-CRC, aus der APK ausgelesenes
Manifest und fehlende Signatur geprüft: Paketidentität und Versionskennzeichnung
stimmen, minSdk26, targetSdk37, LAN-Deklaration und testOnly sind vorhanden,
Debugging ist aus. Das unsignierte Artefakt bleibt ein privater Testkandidat,
kein installierbares Update und keine Veröffentlichungsfreigabe.

Die separat ausgeschlossenen Crossplattformklassen wurden anschließend im
vorhandenen isolierten Testnetz ausgeführt: **57/57 Tests bestanden, keine
Skips**. Die kanonischen Python-/C#-Gegenstellen waren an den aktuellen
Quell-/Binärstand gebunden; Hostnetz und ursprünglicher Listener blieben
unverändert. Das prüft die synthetischen Transportwege auch unter den neuen
Empfangs-/Sitzungsgrenzen, nicht die physische Android-Berechtigungsdialog- oder
Windows-GUI-Abnahme.

Die positiven synthetischen Telefonfixtures binden ihre Originalpipe jetzt
explizit über einen ausschließlich testseitigen Helper. Fachliche Assertions
werden dadurch nicht gelockert. Eine bewusst angepasste Erwartung betrifft
`BackgroundLifecycleTest` an der Grenze `received-control`: Eine bereits
invalidierte Sitzung verwirft den Frame vor Dispatch still, anstatt erst im
nachgelagerten Handler eine Exception auszulösen. Die vorhandenen Queue-,
No-Effect- und Re-pair-Prüfungen sowie alle anderen Fehlererwartungen bleiben.

### Nächster Build auf dem vorhandenen vollständig bestückten Bauhost

Nur bereits vorhandene, checksumgebundene Wrapper-/SDK-/Dependencybestände
benutzen. Gradles `--offline` verhindert nicht das erstmalige Herunterladen
einer fehlenden Wrapperdistribution; deshalb den vorhandenen Cache vorher
prüfen. Ein fehlender Bestand ist ein Halt, kein Installationsauftrag.

```bash
cd magnolie-notes
./gradlew --offline --dependency-verification strict \
  -PmagnolieFdroid=true -PmagnolieTarget37Validation=true \
  :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
python3 werkzeuge/test_target37_build.py --manifest PFAD_ZUM_GEMERGTEN_MANIFEST --target 37
```

Zusätzlich den normalen Ziel35-Bau und sein tatsächliches Manifest mit
`--target 35` prüfen. Das vorhandene komplette `release-gate.sh` fordert auch
Debug-/Fixture-/AndroidTest-Varianten an und kann nicht unverändert als
Target37-Kandidatenlauf verwendet werden. Die bestehenden Robolectric-Tests
verwenden SDK 35; ihr Erfolg würde keine Android-17-Systemprüfung belegen.

Ein tatsächliches Paket benötigt weiterhin CRC-/Paket-/Manifest-/Unsignedaudit.
Signierte native Prüfpakete und die vorhandene `.validation`-Instrumentierung
sind eine spätere eigene Stufe des bestehenden Freigabeverfahrens.

## Offene native Abnahmematrix

**Alle folgenden Zeilen sind offen.** Nur getrennte synthetische Bestände
verwenden. Keine tatsächlichen Benutzerschlüssel oder Originalbücher. Pro Fall
Quellcommit, Paket-SHA256, Signieridentität des Testpakets, Geräte-/OS-Version,
Ist-Target, Ausgangsrechte, Schritte und beobachtetes Ergebnis privat festhalten.

| Bereich | Konkrete Fälle | Erwartung |
| --- | --- | --- |
| Zielgrenze | Gerät 26/35/36 mit Target37; Gerät37 mit Target35 und Target37 | Kein neuer Dialog bei Geräte-API <37 oder targetSdk <37; Ziel35 ohne LAN-Deklaration; min26 erhalten |
| Neue Einrichtung | Grant, Denial, Cancel, erneuter bewusster Versuch | Nur sichtbare Einrichtung fragt; ausschließlich tatsächlicher Grant ermöglicht LAN |
| Gruppe/Upgrade | Ziel35→37 mit/ohne Bluetoothgrant und nach Gruppenverweigerung | Android entscheidet Dialog/Grant; App leitet keine Autorität aus Bluetooth ab |
| Entzug | Während Connect, accept, Read, Antwort und vor nativem Commit; Wiedererteilung | Betroffener Lauf stoppt; alter Beleg bleibt ungültig; neuer autorisierter Lauf kann starten |
| Lifecycle | Rotation, Home, Stop/Destroy, Prozessneustart, später Callback, neuer Intent/Peer | Keine wiederholte alte Peer-/Buchaktion und kein Hintergrunddialog |
| Automatik | Dienst aktiv/inaktiv vor Boot/Update; Verbindung weg/zurück | Gespeicherte Einrichtung bleibt; ausgeschaltet bleibt ausgeschaltet; kontrollierte Wiederaufnahme |
| TCP | Connect und accept, vollständiger und teilweiser Frame | Kein geschützter Zugriff ohne Recht; Trennung verursacht keine spätere Mutation |
| UDP | Send/Receive, Broadcast/Multicast | Beide Richtungen geschützt; Ressourcen nach Entzug geschlossen |
| NSD | Beide Notespfade, Discovery/Registration/Resolve und verspätete Callbacks | Ergebnis/Lauf/Grantgeneration passen; abgebrochene Suche bleibt beendet |
| Adressen | Private IPv4, ULA/link-local/global IPv6, öffentlich nummeriertes LAN, spezifische Route | Lokale Route benötigt Grant; eindeutig ferner Pfad bleibt unabhängig |
| Netzwechsel | WLAN↔Ethernet/Mobilfunk/VPN bei offener Verbindung, Network-Verlust, Route geändert | Prüfung bleibt am gebundenen Netz; alte Transfers werden nicht durch einen Defaultwechsel freigestellt |
| Bluetooth | LAN verweigert bei aktivem Bluetooth und umgekehrt; paralleler Betrieb; RFCOMM-EOF | Bluetooth bleibt unabhängig; WLAN-first nur bei nutzbarem LAN; keine EOF-Endlosschleife |
| Datenkontinuität | Upgrade/Neustart/Entzug mit Identität, Pairing, Konten, Büchern, Consent, SEND, History/Revision/CAS | Identitäten und Inhalte erhalten; echte Widerrufe weiterhin wirksam |
| UI/Plattform | Edge-to-edge, Back, Größenwechsel, Kontakte, Erinnerungen/FGS, ggf. WebView-LAN | Aktuelle Plattformpfade korrekt; keine pauschale Altgeräteimplementierung |
| Paket/Freigabe | Tatsächlich signiertes installierbares Prüf-/Releasepaket im bestehenden Verfahren | Start, Bedienung und Upgrade nativ belegt, bevor Produktziel/Storefreigabe geändert werden |

Die positive Samsung-/Android-17-Rückmeldung zur bisherigen Ziel35-APK bleibt
unberührt. Desktopgegenstellen erhalten durch diese Migration keine Android-
Berechtigung. iPhone-Anbindung bleibt bei vorhandenen Apps; keine eigene
iOS-Notes-App wird eingeführt.

## Primärquellen

- https://developer.android.com/privacy-and-security/local-network-permission
- https://developer.android.com/reference/android/Manifest.permission
- https://developer.android.com/reference/android/net/Network
- https://developer.android.com/reference/android/net/ConnectivityManager
- https://developer.android.com/training/basics/intents/result
- https://developer.android.com/about/versions/16/behavior-changes-16
- https://developer.android.com/about/versions/17/behavior-changes-17
- https://developer.android.com/build/extend-agp

Diese Quellen definieren die Plattformanforderungen; die Hosttests beweisen
ausschließlich die jeweils ausgeführten synthetischen Quellfälle.
