# #855-Nachprüfung und #856 – Österreichische Ferien vollständig abrufen

Die offenen Sprach- und Swift-Serviceprüfungen von #855 sind nachgeholt. Die
reale Providerprüfung hat dabei einen weiteren tatsächlichen Fehler gefunden:
Österreichische ISO-Regionen wurden unverändert an eine API gesendet, die andere
Regionskennungen erwartet. Der vollständige Folgepatch für alle vier nativen
Plattformen liegt hier zur Prüfung und späteren Übernahme mit Codex vor.

Fachissues: [#855](https://github.com/maik3531/Magnolie-Organizer/issues/855)
und [#856](https://github.com/maik3531/Magnolie-Organizer/issues/856).
Kein Produkt-main-Merge, keine Paketinstallation und kein Release durch diesen
Review. Die vollständige native Plattformabnahme ist nicht behauptet.

## Genau eine passende Patchvariante anwenden

| Ausgangsstand | Vollständiger Patch |
| --- | --- |
| Unveränderte Produktbasis `1749c92eb42801c38eaba31b272d8c0e27be9164` | [Gemeinsamer Patch #855 + #856](holiday-cache-855-plus-austria-856.patch) |
| Derselbe Stand mit dem vollständigen früheren #855-Patch, Ergebnisbaum `f4f94a2c2cf73a064448d3208f31d471e150dbe4` | [Nur Folgepatch #856](austrian-regions-856-after-855.patch) |

**Die beiden Varianten sind Alternativen. Nicht beide aufeinander anwenden.**
Vor Übernahme frischen main und zwischenzeitliche Änderungen vergleichen.
Die einzelnen Mac-/Windows-Teilpatches in den Belegunterordnern dienen dem
Nachvollziehen der Teilprüfungen; bei Anwendung einer obigen vollständigen
Variante nicht zusätzlich anwenden.

Beide vollständigen Varianten wurden in getrennten Git-Indexen vorwärts
angewandt und wieder zurückgenommen. Sie erzeugen exakt denselben finalen Baum
`e02b1150060a66d9289cfd910356b44029cb270b`; ihre Rücknahme stellt den jeweiligen
Basisbaum exakt wieder her. [Nachweis](PATCH-CHECK.json),
[Quellbindungen aller 19 betroffenen Dateien](SOURCE-MANIFEST.json).

| Variante | Bytes | SHA-256 |
| --- | ---: | --- |
| #856 nach #855, zwölf Quelldateien | 60.165 | `f03e194168a4d412672ac0cc0c128285f9e30f1b82e6c42c35012ca18b00b0c9` |
| #855 + #856 gemeinsam, 19 Quelldateien | 173.824 | `ee7179924bbdb0072259eb9b2f5e1bd14e10df943f458148af2b17ca4e8c5e1e` |

## Live gefunden: erfolgreicher HTTP-Status, fehlende Wiener Ferien

Die tatsächlichen Linux-Produktfunktionen führten echte HTTPS-Abrufe mit ihrer
normalen TLS-, Größen- und Parserprüfung aus. Der Testhost zeichnet Antworten
auf und stellt Gettext-/Laufzeitkontext bereit; er ersetzt weder den HTTP-Client
noch den Feiertagsalgorithmus.

Die bestehende Auswahl Wien verwendet korrekt die interne ISO-Identität `AT-9`.
OpenHolidays verlangt für seinen Parameter `subdivisionCode` jedoch `AT-WI`.
Beide Varianten antworteten am 28.11.2026 mit HTTP 200. Die falsche Anfrage gab
nur sechs landesweite Ferienperioden zurück. Die richtige Anfrage enthielt acht,
zusätzlich Semesterferien **02.–07.02.2026** und Sommerferien
**04.07.–06.09.2026**.

Die offizielle Subdivisionsantwort unterscheidet ausdrücklich `code` und
`isoCode`. Sie enthält neun österreichische Paare, darunter `AT-KÄ`/`AT-2`,
`AT-NÖ`/`AT-3` und `AT-OÖ`/`AT-4`. Auch die Kalenderantworten verwenden die
Providerkennungen. Ein alleiniger Austausch des URL-Parameters würde deshalb
noch keine korrekte Zuordnung der zurückgegebenen Daten herstellen.

Mit den real aufgenommenen Antworten wurde die Auswirkung in beiden
vollständigen Desktopoberflächen nachvollzogen: Die Wiener Perioden fehlten,
und eine ausdrücklich gesetzte, kanonische Altcachefixture mit dem realen
Semesterzeitraum wurde durch die fälschlich bestätigte Abdeckung gelöscht.
Dies ist eine kontrollierte Reproduktion, kein behaupteter Datenverlust auf
einem Nutzergerät. [Rohantworten, genaue Aufrufe und Reproduktion](live/README.md).

## Korrektur für Linux, Windows, Tablet und Mac

Alle vier Provider bilden die neun belegten österreichischen Regionen an der
HTTP-Grenze in beide Richtungen ab. Auswahl, gespeicherte Daten und die neuen
`abrufbereiche` behalten die bisherigen ISO-Identitäten. Bekannte
Unicode-Providerkennungen werden korrekt URL-kodiert beziehungsweise vor der
bestehenden strikten Antwortprüfung auf ISO normalisiert. Bekannte
ISO-Antworten bleiben kompatibel. Die allgemeine Zeichensatzprüfung wird nicht
gelockert; die übrigen Länder behalten ihren bestehenden Pfad.

Unbekannte angefragte österreichische Regionen dürfen keine scheinbar gültige
Teilantwort auslösen. Jeder AT-Antwortscope muss bekannt sein, bevor eine
vollständige Cache-Ersetzung bestätigt wird. Das gilt auch für landesweite
Zeilen, landesweite Abfragen, unbekannte vermeintliche Kindregionen und
gemischte bekannte/unbekannte Codes. Verwertbare positive Daten behalten den
bisherigen plattformspezifischen Lesepfad, ohne dadurch Löschbefugnis zu erhalten.

Die vorhandene Python-Setupprüfung erwartete ausdrücklich die falsche Provider-
URL mit `AT-9`; genau diese Erwartung wurde anhand der offiziellen Antwort auf
`AT-WI` korrigiert. Der Quellhost bindet zusätzlich den neuen echten Helper ein.
Alle übrigen Setup-Assertions bleiben erhalten.

Es gibt keine neue Einrichtungshürde, Standortfreigabe, zusätzliche gespeicherte
Identität oder erfundene Ferientermine. Die konservativen #855-Regeln für
unvollständig abgedeckte nationale und jahresübergreifende Altperioden bleiben
bestehen. Das Paket erweitert keine Länder/Provider und keine Festtagsmotive.

## Nachgeholte Prüfungen von #855

- **Alle 20 Sprachen:** Der vollständige unveränderte Einrichtungsprüfer besteht
  **88/88** Fälle mit beiden Oberflächen. Darin sind 40 sprachabhängige Starts
  und 48 weitere Ablaufprüfungen. Die 38 Webkataloge wurden mit den regulären
  Generatoren und GNU msgfmt einschließlich Formatprüfung erzeugt. Dieselben
  88 Fälle bestanden auch mit dem regulär regenerierten Windows-Nativkatalog;
  dies sind zwei Eingabekonfigurationen, keine 176 unterschiedlichen Fälle.
  [Sprachnachweis](languages/README.md).
- **Swift-Service kompiliert und ausgeführt:** Die vollständigen unveränderten
  #855-Dienst-/XCTest-Quellen bestehen **11 ausführbare Methoden**, einschließlich
  aller fünf neuen #855-Methoden. Ein vorhandener Live-Mac-Test bleibt explizit
  übersprungen. Swift 6.4.3 unter Debian 13, keine Warnungen oder Fehler.
  [Nachweis des unveränderten #855-Stands](swift-855/README.md).
- **Tatsächliche Providerantworten:** DE/Sachsen 2026/2027, CH/Zürich und
  Österreich wurden real abgefragt. HTTP-Erfolg wurde nicht mit fachlicher
  Vollständigkeit gleichgesetzt; daraus entstand der bestätigte Fehler #856.

Eine vorbestehende einzelne portugiesische Nativkatalogabweichung (`No` statt
`Não`) wird vom normalen Generator aus der bereits korrekten PO-Quelle bereinigt.
Beide Katalogfassungen bestehen die 88 Fälle. Daraus wurde kein unbelegter Fehler
regulär gebauter Pakete abgeleitet. Der Sprachlauf ist eine Einrichtungstest-
matrix, keine umfassende sprachwissenschaftliche Prüfung aller Programmtexte.

## Endgültige #856-Vorher-/Nachher-Ergebnisse

| Gleiche endgültige Prüfanforderungen | Nur #855 | Mit #856 |
| --- | ---: | ---: |
| Echte Linux-Python-Produktfunktionen | 27/35 | **35/35** |
| Echte Windows-C#-Methoden/Parser im Host | 30/43 | **43/43** |
| Vollständiger Tablet-Dienst und reguläre JUnit-Klasse | 20/26 | **26/26** |
| Vollständiger Swift-Dienst und reguläre XCTest-Klasse | 12/17 | **17/17** |
| Beide vollständigen Desktopskripte mit aufgezeichneten nativen Liveantworten | 6/12 | **12/12** |

Swift hat zusätzlich in beiden Vergleichen denselben **einen übersprungenen
Live-Mac-Test**. Drei ursprüngliche Python-Setup-Providerfälle bestehen ebenfalls.
Die früheren 80 Desktop- und sechs MCP-Fälle von #855 sind unveränderte vorhandene
Belege; sie werden hier nicht als neu ausgeführte Tests ausgegeben.

Vier neue tatsächliche Requests nach der endgültigen Korrektur bestätigen
**Wien: 13 Feiertage + 8 Ferienperioden** und **Kärnten: 13 + 9**, mit kanonischen
ISO-Feldern und bestätigter Bereichsabdeckung. Die endgültigen Antworten liegen
in [final-capture/live-results.json](live/final-capture/live-results.json).
Der anschließende 12-Fälle-Desktoplauf verarbeitet diese Aufzeichnungen; er
ist ein Replay und keine zusätzliche Live-GUI-Verbindung.

Ein unabhängiger Review fand im ersten Linuxkandidaten eine zu weite Abdeckung
bei unbekannten Codes ohne Länderpräfix. Dieser Kandidat wurde verworfen. Die
endgültige Python-Suite enthält 20 Kombinationen dieses Grenzfalls; die
unabhängige Gegenprobe besteht **32 negative und vier positive Fälle**.
[Review und wiederholbare Gegenprobe](independent-review/README.md).

Teilberichte mit tatsächlichen Befehlen, Quellenhashes und Wiederholung:
[Linux/Live](live/README.md), [Windows](windows/README.md),
[Tablet](kotlin/README.md), [Swift-Folgepatch](swift-856/README.md),
[maschinenlesbare Zusammenfassung](TEST-SUMMARY.json).

Einzelbelege entstanden vor dem Zusammensetzen des finalen Git-Baums. Das
`candidate_tree`-Feld im Desktop-Replay bezeichnet seine unveränderten
#855-Frontendquellen; die separaten Native-Quellenhashes bezeichnen #856.
Maßgeblich für den gesamten zusammengesetzten Stand sind die oben gebundenen
Patchbäume und `SOURCE-MANIFEST.json`. Die ursprünglichen Laufbelege werden
nicht nachträglich als andere Testläufe umgeschrieben.

## Genaue Grenzen und native Linux-Umgebung

Die C#-Prüfungen laufen auf Linux mit SDK 8.0.428/Runtime 8.0.34 und kontrollierten
HTTP-/Callback-Kontexten. Kotlin 2.4.21 erzeugt JVM-Bytecodeziel 17; die tatsächliche
Laufzeit ist OpenJDK 21.0.13.1. Die vorhandene DAV-Warnung bleibt sichtbar.
Das ersetzt keine native Windows- oder Android-Geräteprüfung.

Swift kompiliert die vollständigen Feiertagsdienst-/Testquellen und echte
Contract-Hilfsquellen. Der unbenutzte Default-Transport ist im Linux-Host
ausdrücklich fail-closed abgegrenzt; AppKit, Keychain und die vollständige
Mac-Anwendung wurden nicht gebaut. Der Nachweis darf daher nicht als native
macOS-App- oder native Mac-HTTP-Abnahme bezeichnet werden.

Die echte Linux-WebKit-Prüfung wurde vorbereitet: offizielle signatur-/hash-
geprüfte Debian-Abhängigkeiten, Xvfb und private Mountanordnung. Die Umgebung
verweigert jedoch bereits `socket(AF_UNIX, SOCK_STREAM)` mit **EPERM**, direkt
und innerhalb der Testnamespace. D-Bus kann deshalb den lokalen Bus nicht
starten. **Null native WebKit-Produkttestfälle wurden ausgeführt.** Keine Sandbox
wurde dafür abgeschaltet, keine Zugriffssperre umgangen und keine Hostinstallation
vorgenommen. [Startversuche, genaue Socketprobe und Grenzen](webkit/README.md).
Für diese verbleibende Abnahme wird eine reguläre Linux-GUI-Umgebung mit
erlaubten lokalen IPC-Sockets und funktionierender WebKit-Sandbox benötigt.

Installierte Pakete, vollständige native Oberflächen und vollständige Mac-HTTP-
Pfade bleiben offen. Liveinhalte sind zeitgebundene Beobachtungen. Der Legacy-
GUI-Weg erhält durch diese Änderungen keine individuelle Antwortkennung;
die bereits dokumentierte Grenze verspäteter Antworten bleibt bestehen.

## Datenquellen, Lizenz und Fortsetzung

Die Rohantworten und abgeleiteten Kalenderansichten werden mit OpenHolidays-
Attribution und der tatsächlich gelesenen ODbL-Datenlizenz bereitgestellt:
[Attribution](live/ATTRIBUTION.md), [Lizenzvolltext](live/OPENHOLIDAYS-DATA-LICENSE.txt),
[offizielle FAQ](https://www.openholidaysapi.org/en/faq/). Das gilt auch für die
bytegleiche Subdivisionskopie im unabhängigen Review. Aus der Softwarelizenz
wird keine abweichende Datenlizenz abgeleitet.

Frischen main, #855/#856 und aktuelle Arbeitsmarkierungen vor Übernahme lesen.
#853 hat inzwischen einen getrennt veröffentlichten ersten nationalen
Wasserzeichen-Teilpatch nach #850; diese Arbeit wurde beim Fortschreiben des
Reviewzweigs erhalten. #854 bleibt der separate Auftrag für FR/BE/NL-Gruppen
und weitere Quellen-/Regionsabdeckung. Die separat bearbeitete #128-Automatik
nicht parallel neu implementieren. Kein alter Gesamtpatch darf zwischenzeitliche
Produktänderungen zurückdrehen.
