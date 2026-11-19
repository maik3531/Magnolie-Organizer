# #648 – vorbereitete LAN-Guards, keine API-37-Freigabe

Basis der LAN-Änderung: `6b89a37bf0a8ba4447da28ac69776a33cfeb1a69`. Der bereitgestellte
Notes-648-LAN-Guards-Kandidat wurde geprüft und in der lokalen Arbeitsquelle
weiterbearbeitet. Dieser Stand ist keine freigegebene APK.

## Umfang

- Die Prüfung hängt sowohl von Geräte- als auch Ziel-API ab. Bei API/Target unter
  37 bleibt der bestehende INTERNET-Pfad erhalten. Bluetooth ist kein LAN-Grant.
- Der Application-Start initialisiert die Prüfung vor dem gespeicherten
  Dienstwiederanlauf. Hintergrundläufe fordern keine Berechtigungsdialoge an.
- Nur bewusste sichtbare Dienst-/Suchaktionen können die Freigabe anfragen.
  Der Callback liest den tatsächlichen Systemstatus, wiederholt aber keine
  gespeicherte Peer-, Buch-, Kontakt- oder Kopplungsaktion. Bewusste Suche kann
  anschließend erneut ausgelöst werden; eingeschaltete Dienste setzen über ihren
  normalen Takt fort. Ein zwischenzeitliches Ausschalten bleibt wirksam.
- TCP, UDP und beide NSD-Pfade erhalten LAN-Guards. Entzug stoppt nur LAN;
  gemeinsam mit Bluetooth verwendete Sitzungstabellen und gespeicherte Pairings
  bleiben bestehen. Ein lebender Bluetooth-Transport wird nicht wegen fehlender
  LAN-Freigabe als offline markiert. WLAN-first bleibt bei nutzbarem LAN erhalten.
- Suchcallbacks sind an Lauf und Freigabegeneration gebunden; späte Ergebnisse
  werden verworfen. Der Guard ist kein atomarer Betriebssystem-Grant-Lock.
- Öffentliche Fernziele werden einmal aufgelöst und an genau diese IP gebunden.
  Lokale Namen einschließlich `.local.` und IDN-Punktschreibweisen werden vor dem
  Resolver geprüft; lokale Adressen anschließend erneut. Öffentlich adressierte
  lokale Netze und ungewöhnliche Routen bleiben Teil der nativen Abnahme.
- Fehlende Freigabe verbraucht keine LAN-Postfachversuche und erfindet keine
  Buch-, Konto-, SEND- oder Geräteberechtigungen. Wartetext ist in allen
  vorhandenen 20 Sprachressourcen enthalten.

## Korrekturen gegenüber dem Kandidaten

Der WLAN-Transport besitzt alle falliblen Registrierungsschritte nach der
Socket-Feldbelegung innerhalb seines Cleanup-finally. Entzug oder unerwarteter
Registrierungsfehler lässt kein geschlossenes Socket als belegt zurück.

Der Einladungskonstruktor prüft den Token vor dem Listener-Erwerb und schließt
den Listener explizit bei Registrierungsfehlern. Dasselbe gilt für die
TCP-Rohrregistrierung; Fehler beim Abmelden verhindern nicht das Socket-Close.

## Belegte Teilprüfungen

- Produktions-Java-Kern und Adressregeln: **178 Assertions** auf dem vorhandenen
  Java-17-Compiler, einschließlich der ursprünglich mitgelieferten 151 Fälle.
  Resolver werden bei verweigerter lokaler Namensfreigabe nachweislich nicht
  aufgerufen; die Tests verwenden ausschließlich synthetische Adressen.
- Die tatsächliche Kotlin-JUnit-Klasse `LanTorTest` ist mit dem bereits
  vorhandenen Kotlin-2.0.21-Compiler auf dem JVM-Host ausgeführt worden.
- Dieselben 178 Assertions, sieben JUnit-Tests und Erwerbs-Gegenproben bestehen
  zusätzlich auf der vorhandenen Java-21-Laufzeit. Der Java-Kern wurde dabei
  weiterhin mit dem vorhandenen Java-17-Compiler und `--release 17` gebaut,
  entsprechend dem Quell-/Bytecodeziel des Projekts. Dieser begrenzte Nachweis
  wird von der nachfolgenden vollständigen Gradle-Kompilierung unterschieden.
- `werkzeuge/test_lan_ownership.py` kompiliert den unveränderten tatsächlichen
  WLAN-Klassenkörper, die tatsächlichen Einladungserwerbsfelder und die
  tatsächliche TCP-Rohrklasse in einem begrenzten JVM-Testkontext. Sockets und
  Plattformstatus sind ausdrücklich Testdoubles. Registrierungsausfall,
  Entzug/Wiederfreigabe/Wiederverwendung und Erwerbsfehler werden ausgeführt.
  Gezielt wieder eingebaute Fehler für WLAN, Einladung und TCP werden erkannt.
  Dies ist kein Test echter Android-Sockets oder NSD-Komponenten.
- `werkzeuge/test_lan_guards.py` prüft zusätzlich die Quellverträge und XML-
  Sprachressourcen. Quellprüfungen ersetzen keine Android-Ausführung.
- Vollständige Release-Kotlin-/Java-Kompilierung einschließlich Ressourcen mit
  vollständigem JDK 21 und vorhandener Android-Plattform 35: bestanden, offline
  und im unsignierten F-Droid-Modus. Deprecation-/Nullability-Warnungen bestehen.
- Vollständiges bestehendes Release-Unitgate: **2.386/2.386 Tests**, keine Skips,
  nach den separat geprüften Korrekturen #666, #667 und #668 auf `e1c824bb` plus
  diesem lokalen LAN-Stand.
- Release-Lint besteht ohne Fehler; **100 Warnungen und sieben Hinweise** bleiben.
  Die API-Grenzen der Galerie-Helfer wurden separat in #668 geprüft.
- Vollständiges Cross-Gate: **57/57 Tests**, keine Skips, nach den getrennten
  Fixturekorrekturen #669/#670/#673. Die tatsächlichen Python-/C#-Transporthosts
  laufen mit Notes im isolierten Netzwerk (#671), bei unverändertem protokollfestem
  Port 8741. Hostnetz und bestehender Benutzerdienst bleiben unverändert; der
  Einladungsvertrag wurde nicht auf beliebige Ports gelockert. Dies ist keine
  native Windows-GUI- oder physische Android-Geräteabnahme.
- Der unsignierte Release-APK-Bau ist bestanden. ZIP-Integrität, Paketkennung,
  Version 1.0.21 / Code 21, minSdk 26 / targetSdk 35 und das Fehlen der neuen
  LAN-Manifestberechtigung sind am tatsächlichen Paket geprüft. Die APK ist
  erwartungsgemäß nicht signiert; keine Installation oder Veröffentlichung.
  Native Paketabnahmen bleiben offen.

## Unveränderte Freigabegrenzen

compileSdk 35 / targetSdk 35 / minSdk 26 bleiben bestehen. Keine neue
Manifestberechtigung. Eine Gradle-Prüfung blockiert targetSdk ab 37, bis die
  zusammengehörige Werkzeug-/Manifestmigration aus #558/#672 geprüft wird; keine
Eigenschaft umgeht diesen Halt.

Kompilierung, vollständiges Unit- und Cross-Gate, Lint und unsignierter APK-Bau
sind nachgewiesen, native Paketabnahmen noch nicht. Hostprüfungen belegen keine echte Bedienung
von Compose, Foreground Services, NSD, Berechtigungsgruppen oder nativen
Socket-/Lifecycle-Rennen.

Vor einer Integration/Freigabe bleibt der vollständige vorhandene Bau-/Testweg
innerhalb der gültigen Buildfreigaben nötig. Vor API-37-Anhebung zusätzlich
gemeinsame SDK-/AGP-/Gradle-/Kotlin-/Manifestprüfung und native Abnahme von
Erstfreigabe, Ablehnung, Entzug/Wiederfreigabe, Prozessneustart, Activity-Wechsel,
Peerwechsel, parallelem Bluetooth und älteren Geräten ab API 26. Nur synthetische
Bestände verwenden; gespeicherte Rechte und Daten erhalten.

Diese Prüfergebnisse sind keine native Paket- oder Veröffentlichungsabnahme.
Bestehende tatsächliche Geräte-/Signier-/Store-Pausen bleiben wirksam; daraus
folgt kein pauschales Verbot einer geprüften Quellstandsicherung. Der offene
Migrations- und native Abnahmeumfang aus #648 wird in #672 fortgeführt. Die
isolierte WLAN-Cross-Abnahme aus #671/#673 ist abgeschlossen. Die positive Samsung- /
Android-17-Rückmeldung zur bestehenden Notes-APK wird nicht in Frage gestellt.

Offizielle Grundlage: https://developer.android.com/privacy-and-security/local-network-permission
