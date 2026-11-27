# Aktuelle Übergabe: zwei neue Postfachkorrekturen

**Geprüfte Integrationsbasis:** 7c9f9395ac7fcac03b0ce229f9707643be4b06fa.

Die früheren zehn Reviewpatches sind inzwischen auf main übernommen. Diese Übergabe enthält deshalb ausschließlich die zwei neuen Nachträge zu #691 und #128. Sie sind für die spätere Übernahme mit Codex vorbereitet; der Review selbst hat den Produkt-Hauptzweig nicht verändert.

## Dateien zur Übernahme

- [Gemeinsamer Restpatch auf der angegebenen Basis](remaining-review-after-7c9f9395.patch)
- [Einzelpatch #691 – Notes-LAN-Warten](series/01-691-outbox-route-quota.patch)
- [Einzelpatch #128 – Desktop-Actor-Postfach](series/02-128-actor-queue-fairness.patch)
- [Maschineller Quellen- und Integrationsbeleg](integration-proof.json)
- [Dauerhafter Wiederaufsetzpunkt für folgende Läufe](CONTINUE.md)

**Gesamtpatch:** 45.797 Bytes, SHA-256 7baaf9ede4c21fbaff3688e44ef3a82b689c53b93713abff316f91410a809945.

**Ergebnisbaum:** f4f9817658165bd84d434d34c7ddcce3f32486f4.

Einzelserie und Gesamtpatch sind vorwärts und rückwärts geprüft. Entweder den Gesamtpatch auf seine unveränderte Basis oder nur die noch fehlenden Einzelpatches verwenden; nicht beide Varianten doppelt anwenden. Bei einem neueren main zuerst aktuelle Übernahmen prüfen.

## Was bereits übernommen wurde

| Thema | Upstream-Commit | Folgerung |
|---|---|---|
| #566 – Lotus-CSV-Kontakte | 4660ba7 | Alter Patch entfällt. |
| #790 – Mac-/Tablet-Quellprüfung | da81f59 | Alter Patch entfällt; zusätzliche Tablet-Prüfung bleibt. |
| #844 – Farben und Roundtrip | 2bdb026 und vorhandener #846-Fix | Alter Patch entfällt; lokalisierter ICS-Fehlertest bleibt. |
| #845 – bearbeiteter 29. Februar und Serienausnahmen | 2f2f9f1 | Beide alten Patches entfallen; getrennte C#-Testgruppen bleiben. |
| #395 – Organisatorvorschläge | 37314cc | Alter Patch entfällt; neue Fokusprüfung bleibt. |
| #330 – Medien-Warten und Erstwiederherstellung | 0ffd44b | Beide alten Patches entfallen. |
| #192 – MCP-Dokumentation | a7853a2 | Alter Patch entfällt; vollständige Toolnamen bleiben. |
| #148 – faire Fernzielprüfung | 7c9f939 | Alter Patch entfällt. |

Die [erste Übernahmeprüfung](upstream-adoption-review.md) und der [abschließende Vergleich](upstream-adoption-current.md) prüfen tatsächliche Produkt- und Testdateien. Die vollständigen Themen und ihre nativen Restkriterien sind dadurch nicht pauschal abgeschlossen; beispielsweise bleibt die weitere DAV-Arbeit in #441.

## Neuer Notes-Nachtrag zu #691

Wartende LAN-Sendungen belegten bisher das gesamte Kontingent des Postfachlaufs. Im tatsächlichen Methodenablauf verhindern 70 auf LAN-Freigabe wartende Einträge bei Standardkontingent 64 die Bearbeitung einer späteren erlaubten Fernziel-Sendung. Der endgültige Fix gibt ausschließlich im LAN-Wartezweig den dort belegten Versuch zurück. Leere/fehlgeschlagene Vorbereitung und fehlende Partner behalten ihre bisherigen Grenzen.

**Prüfung:** unveränderte Basis 15 bestanden / 5 fehlgeschlagen, endgültiger Patch 20 bestanden / 0 fehlgeschlagen. Öffentlicher Fernversand, Bluetooth, Widerruf, Wiederherstellung, Dienstgeneration, Arbeitsgrenzen und Legacy-Fencing sind mit kontrollierten Abhängigkeiten geprüft. Ein zunächst breiterer Kandidat wurde im unabhängigen Review verworfen.

[Ausführliche bereits veröffentlichte Belege](https://github.com/maik3531/Magnolie-Organizer/blob/00bda7cb9451e6d167f0be6a9654b68f881b91e9/patches/codereview-notes-quota-2026-11-27/README.md) und [Issuekommentar](https://github.com/maik3531/Magnolie-Organizer/issues/691#issuecomment-7228161134).

Der konkrete Berechtigungsfall betrifft den vorbereiteten Target-37-Kandidaten. Der reguläre Notes-Quellbau bleibt Target 35; keine installierte APK-Regression wird daraus abgeleitet. Die vollständige Feldgleichheit gilt für vorbereitete FS1-Fixtures. Die bestehende Legacy-Vorbereitung bleibt unverändert.

## Neuer Desktop-Nachtrag zu #128

[Ausführlicher Bericht, endgültiger Patch und Reproprogramme](desktop-128/README.md).

65 fällige, geschützte Actor-Datenumschläge ohne aktuellen Sendeowner verdecken durch die bisherige 32er-Vorauswahl einen späteren gewöhnlichen Statusauftrag. In den produktiven Quellhostproben passiert vor dem Fix in drei Wartungsrunden nichts; danach wird der Statusauftrag in der dritten Runde verarbeitet. Alle Actor-Umschläge bleiben erhalten, mit null Versandversuchen.

Der Fix verwendet ein begrenztes, sitzungsgebundenes Pumpfenster. Kontrollen behalten Vorrang. Unter Linux erzwingt eine aktuelle Peer-/Kanal-Admission vor der Auswahl den bisherigen Kopf; von einer fortgesetzten Seite wird niemals ein Actor gesendet. Ein Ownerwechsel nach dem Lesen kann dadurch keine früheren Frames überholen. Unter Windows bleibt der autorisierte Actor-Sender getrennt und verwendet seine bisherige Auswahl.

**Prüfungen:**

- 12 neue und 10 bestehende gezielte Python-Fälle bestanden.
- Neue .NET-Gruppe mit 11 Szenarien und fünf bestehende .NET-Gruppen bestanden.
- Gleicher bestehender C#-Pump-Einstieg: unveränderte Basis rot, endgültiger Patch grün.
- Drei negative FIFO-Fälle verwarfen den ersten Linux-Cursor-Kandidaten; final bestehen alle.
- Alle zugehörigen C#-Bauten: null Warnungen und null Fehler.

Die .NET-Ausführung erfolgte auf Linux. Der zunächst fehlende Host-Zeitzoneneintrag wurde aus dem bereits vorhandenen vollständigen tzdata-Bestand bereitgestellt; ursprünglicher Fehler und erfolgreicher Wiederholungslauf sind dokumentiert. Die Windows-Fixture bereinigt ausschließlich ihren eigenen SQLite-Pool.

Vorhandene, aktuell wartende Linux-Admissions und gewöhnliche Time-/Shared-Wartefälle behalten ihre bisherige Reihenfolge. Der Teilpatch schaltet weder auto_connection noch einen Internettransport frei und verändert Notes/Android nicht.

## Integration und Nachweisgrenzen

Der aktuelle Ergebnisbaum unterscheidet sich vom vorher ausgeführten vollständigen Integrationsstand nur durch erhaltene neue ARBEITSSTAND-Einträge, präzisere MCP-Dokumentation und den neuen Fokus im Web-Smoke-Test. Alle maßgeblichen Produktquellen stimmen bytegleich mit den ausgeführten Tests überein.

Die [gezielte Oberflächenprüfung](ui-integration/README.md) besteht: 10/10 Organisatorfälle, 24/24 Farbvektoren über beide Desktop-Webquellen und beide Legacy-Importprogramme mit dem tatsächlichen Python-Codec. 197 gebundene Eingabedateien blieben unverändert. Keine frühere unveränderte Gesamtsuite wurde als neuer Lauf gezählt.

Das sind kontrollierte JVM-, Python-, .NET- und JSDOM-Quelltests. Es wurde keine neue physische Android-, native Windows-, echte Internet-/Router- oder installierte Paketabnahme ausgeführt. #691 und #128 behalten ihre übrigen offenen Kriterien. Die Magnolienbaum-Fernendpunkte und das Telefon-PersonalSync-Postfach sind unterschiedliche Pfade; dieser Teilfortschritt belegt noch keine fehlerfreie oder vollständig vereinfachte Internet-Einrichtung.

## Fortsetzung unabhängig vom Chatverlauf

Die Datei patches/CODEREVIEW-WEITER.md auf dem Reviewzweig enthält den aktuellen Wiederaufsetzpunkt. Folgeläufe lesen zuerst diese Datei, den frischen Hauptzweig und die aktuellen Issues. Sie prüfen schon erfolgte Übernahmen, führen ein konkretes Arbeitspaket zu Ende und sichern danach Quelle, Tests, offene Grenzen und nächsten Schritt. Der Auftrag sieht geprüfte Patches zur späteren Codex-Übernahme vor, keine automatische Produktveröffentlichung.
