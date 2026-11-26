# Mac: gesicherter Stand und spätere Übernahme in den stabilen Entwicklungszweig

Stand: **26. November 2026**. Zugeordnet zu
[#121](https://github.com/maik3531/Magnolie-Organizer/issues/121),
[#783](https://github.com/maik3531/Magnolie-Organizer/issues/783) und den unten
genannten Einzelbefunden. Auftrag: den Stand über Chatgrenzen hinweg sichern,
spätere gemeinsame Änderungen nachvollziehbar übernehmen und vor einer stabilen
Veröffentlichung gründlich prüfen.

## Entscheidung und Quellanker

Der Arbeitszweig ist reviewbar und wiederherstellbar. Der Vorgängerlauf #97
hat die damalige native CI-Kette auf beiden Mac-Architekturen bestanden.
Die erweiterte Nachprüfung #104 hat am hier gebundenen neuen Quellstand auf
ARM64 und Intel mit **`completed/success`** abgeschlossen. Der Lauf dauerte am
26. November 2026 von **14:15:18 bis 14:49:42 Uhr Europe/Berlin**
(13:15:18–13:49:42 UTC). Eine vollständige stabile
Mac-Ausgabe ist damit noch nicht freigegeben: offene Produktfunktionen und
native Abnahmen stehen in der Freigabematrix unten. Quellübernahme und
Veröffentlichung eines installierbaren Pakets bleiben getrennte Entscheidungen.

| Bedeutung | Nachprüfbarer Stand |
| --- | --- |
| Review-/Arbeitszweig | `work/macos-issue-fixes-20261126`; vor jeder Fortsetzung den aktuellen Remote-Head lesen |
| Heutige entfernte Integrationsbasis | `main` auf `d4da48a5eadd0bda22422b924bef4ee3b4324040`, zuletzt am 26. November um 14:52:15 Uhr Europe/Berlin (13:52:15 UTC) lesend bestätigt |
| Erfolgreich geprüfter nativer Quellstand | `3f3ec069895dec254c53660d14e6851cb23077cd`, Tree `176fa7f362227c92ec4d7c4bf08d09b855951ae7` |
| Erweiterte native Ausführung | [Lauf #104](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062), Attempt 1; Gesamtworkflow und beide Mac-Jobs `completed/success` |
| Dauerhafter aktueller nativer Beleg | [Strukturierter #104-Nachweis](../Magnolie-Organizer-macOS-Beta/verification/native-run-104.json), einschließlich beider Quellbindungen, Testkontexte, Skips, Paket-/Loghashes und unabhängiger Byteprüfungen |
| Aktueller Prüf- und Übergabebericht | [Erneute Stabilitätsprüfung](../Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md), einschließlich gemeinsamer Regressionen und erhaltener Zwischenfehler |
| Vollständig erfolgreicher historischer Vorgänger | `215d89029df02df2dce78f35412785ec9f9b36d8`, [Lauf #97](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788) auf beiden Architekturen |
| Historischer Berichts- und Hostregressionsstand | `c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b`; fünf Dokumentations-/Belegdateien nach #97 geändert |
| Dauerhafte historische native Belege | [Bericht bis #97](../Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md), [strukturierter #97-Nachweis](../Magnolie-Organizer-macOS-Beta/verification/native-run-97.json) |
| Ursprüngliche Einzelpatches und Originalhistorie | [Manifest und Wiederherstellung](macos-issue-publication-2026-11-26/CODEX-RESTORE.md), [Issue-/Patchzuordnung](macos-issue-handoff-2026-11-26.md) |
| Fortsetzung nach einem Chatwechsel | [Verbindlicher Fortsetzungs-Prompt](macos-next-chat-prompt-2026-11-26.md) und [ARBEITSSTAND.md](../ARBEITSSTAND.md) |

Ein eigener neuer Stable-/Release-Zweig oder die nächste Versionsnummer wurde
für diese Übergabe noch nicht festgelegt. Alte `release-2.0.*`-Zweige sind kein
automatisch gewähltes Ziel. Die lesend geprüfte aktuelle gemeinsame Basis ist
`main`. Eine spätere Integration muss ihren tatsächlichen Zielzweig und dessen
Commit ausdrücklich festhalten. Der vorliegende Auftrag führt keinen Merge
nach `main`, keine Issue-Schließung und keine Release-Veröffentlichung aus.

## Bereits nachgewiesene Übernehmbarkeit

Die gemeinsame Historie wurde tatsächlich nachgeladen und geprüft. Die zur
Integrationsprobe gehörende Remote-Abfrage am **26. November,
14:16:51–14:16:58 Uhr Europe/Berlin**
bestätigt `main` auf `d4da48a5` und den Kandidaten auf `3f3ec069`. `main` ist
exakt die Merge-Base und ein Vorfahr. Der Vergleich ergibt **0 nur auf main /
23 nur im Kandidaten vorhandene Commits**. Die isolierte Git-Mergeberechnung
ist konfliktfrei und liefert exakt den Kandidaten-Tree
`176fa7f362227c92ec4d7c4bf08d09b855951ae7`. Eine Gesamtübernahme wäre an diesen
Refs technisch als Fast-forward möglich. [Lesefassung](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/integration-3f3ec069.md)
und [strukturierter Nachweis](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/integration-3f3ec069.json)
halten Abfragezeit, Befehle, Ergebnisse und Grenzen fest.

Eine spätere lesende Refabfrage am **26. November um 14:52:15 Uhr Europe/Berlin**
(13:52:15 UTC) bestätigt `main` unverändert auf `d4da48a5`.
Die **0/23** beziehen sich weiterhin auf den Kandidaten `3f3ec069`, nicht auf
spätere Dokumentationscommits. Deren zusätzliche Berichtsdateien verändern
weder rückwirkend den nativen Prüfcommit noch dessen Quellmanifest.

Die früheren Berechnungen bleiben historische Anker: `c8a7690d` ergab 0/18
Commits und Tree `05d0cda6c720c53d61ea699b79f168613f11c9ef`, `8c860a14`
ergab 0/20, `62523306` 0/21. Der getrennte damalige Androidvergleich mit
`7a7d90b0` zeigte zwei gemeinsame Dateipfade und einen konfliktfreien
kombinierten Tree; Mac- und Tablet-Workflowteile blieben jeweils erhalten.
Er ist ausschließlich an diese dort genannten SHAs gebunden, ohne gemeinsamen
Build. [Nachprüfung und Parallelzweigbeleg](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/integration-followup-2026-11-26.md).

Es wurde kein Zweig zusammengeführt. Ein späterer Dokumentationscommit ist
nicht automatisch der nativ geprüfte Kandidat. Ändert sich ein beteiligter
Zweig, muss die konkrete Integration erneut gezielt geprüft werden.

[Dauerhafter Integrations- und Restorebeleg](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/integration-summary.json):
Alle 30 Publikationsdateien und 29 Prüfsummeneinträge stimmen. Alle 24
Originalpatches wurden funktional angewendet; jeder resultierende Tree stimmt
exakt mit dem Original. Das Bundle stellt sämtliche 32 Originalcommits und
688 benötigten Nicht-Main-Objekte bereit. Die historische Folge beginnt auf
`616069f15fed21d8d8d05c8ef795f4ed21bd059c`: Patches 1–9, Merge
`ff5798765f9943411200df4302edfc7779fa74b7`, danach Patches 10–24. Sie endet
auf dem Originaltree `d731a6bd56acd68e79aab83fbadb19ab94ad6547`.
Auch der historische Merge ist konfliktfrei exakt rekonstruierbar.

Die ursprüngliche Übergabe hat 24 Einzelpatches, ein Manifest mit Reihenfolge
und Abhängigkeiten sowie ein Git-Bundle mit Originalobjekten einschließlich
Merge. API-Commit und Originalcommit können denselben Tree, aber verschiedene
Commit-IDs besitzen. Für eine Gesamtübernahme den vollständigen veröffentlichten
Zweig verwenden. Für einzelne ausgewählte Fixes die dokumentierte ursprüngliche
Abhängigkeit und die zusätzlich folgenden Fixes beachten; nicht wahllos alle
Originalpatches noch einmal auf den bereits vollständigen Zweig anwenden.

Für die Original-Bundle-Wiederherstellung einen vollständigen Clone mit allen
im Bundle genannten Voraussetzungen verwenden. Ein `--depth`- oder
`--filter=blob:none`-Checkout kann die Commits kennen, aber historische
Basisobjekte für Thin-Pack-Deltas noch nicht besitzen. Solche fehlenden
Objekte erst vollständig beschaffen und den Restore erneut prüfen; ein
fehlgeschlagener Import in einem unvollständigen Checkout ist weder ein
bestandener Restore noch automatisch ein beschädigtes Übergabebundle.
Die tatsächliche Probe benötigte 198 nachgeladene Main-Basisobjekte; danach
bestand die gesamte Wiederherstellung. Das eingefrorene Bundle endet bei
`0dfeb1b3` und enthält die späteren nativen Folgefixes nicht. Diese liegen
zusätzlich im veröffentlichten Arbeitszweig.

## Native Folgefixes nach der ursprünglichen Übergabe

| Reihenfolge | Issue / Commit | Inhalt und Abhängigkeit |
| --- | --- | --- |
| 1 | #788 · `bdd1345d3bec68144dbcf627a3ca7bd03073c64b` | Swift-Kompilierkorrekturen der Import-/Syncguards auf der kombinierten Mac-Basis |
| 2 | #787 · `689266570cda17f463132a182c02d78ea732dfbd` | Eng begrenzte Ausschlüsse veröffentlichter Mac-Prüfartefakte im Windows-Quellarchiv |
| 3 | #789 · `cc9dc29a606658b7937eb7261409564c96f93775` | Validierte CPython-Buildlinks und privat statisch eingebundenes, fest gepinntes liblzma |
| 4 | #793 · `8c01f75b2ae6a9e753b9c23b0e3c65a7d7826c66` | Nur selbst erzeugte Tempwurzeln kanonisieren; strikte Quellpfadgrenzen erhalten |
| 5 | #796 · `d790d7fc40ddc9f9a0c6869a3378ef53b69f7daa` | Echten Zeitzonenbootstrap in den Kommunikationsprüfer laden |
| 6 | #797 · `3c0b4bb410a5ab514e3deae7fb665a692eb436c2` | Reminder-Text verlustfrei kopieren; präzise Byte-/Notes-Testprüfungen |
| 7 | #802 · `215d89029df02df2dce78f35412785ec9f9b36d8` | Signiertes privates CPython-Helper-Bundle mit isoliertem Launcher; baut auf #789 auf |
| 8 | #121/#802 · `c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b` | Berichts-/Belegcommit, keine weitere Produktcodeänderung |
| 9 | #806 · `6599dcb2a7d337f4b248b8b172e5e18c537a2dfa` | Native Zielplattform und eindeutige Deploymentmetadaten prüfen; Runtime, äußere App und optionaler AirPlay-Bau |
| 10 | #121/#785/#806 · `8c860a14f7e10904c1b3a159ae84619c2c24ba82` | Erweiterter nativer Prozess-/Release-Prüfumfang und gesicherte Integrations-/Restorebelege |
| 11 | #806 · `625233067cd49e204786deb5706e6bc08ef85c4e` | Moderne `vtool`-Werkzeugversionsfelder von der Deploymentversion unterscheiden; Befund aus #100 |
| 12 | #793 · `f7957801ba99c0e65e7eaeb70f69824efcd55fd0` | Neu erzeugte AirPlay-Testwurzel kanonisieren; Befund aus #102, Produktpfadgrenzen unverändert |
| 13 | #808 · `3f3ec069895dec254c53660d14e6851cb23077cd` | Archivzeitstempel validierter regulärer Quellen erhalten; echte Make-Regression und gepinnter XZ-Nachbau zu #103 |

Diese Folgefixes liegen im veröffentlichten Arbeitszweig. #102 und #103
bestätigen die neue echte Darwin-Plattformprüfung auf beiden Architekturen;
#103 bestätigt zusätzlich die vollständige AirPlay-Boundarysuite. Der
Gesamtlauf #104 hat anschließend den korrigierten XZ-/CPython-Bau und die
erweiterte Prüfkette auf beiden Architekturen bestanden.
Ein alter #97-Pass wird nicht auf nachträgliche Quelländerungen übertragen.
Der #787-Nachweis ist keine vollständige Windows-Freigabe: Der getrennte
Windows-Cleanupbefund [#794](https://github.com/maik3531/Magnolie-Organizer/issues/794)
bleibt offen. Der neuere [Windows-Lauf Nr. 552](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45820275770)
auf `8c860a14` bestätigt ihn erneut: 551/552 Core-Testgruppen bestanden,
ein Fehler beim Aufräumen der noch geöffneten `phone.db`; Quellarchiv-Gate
fehlgeschlagen, keine nachfolgenden ZIP-/Installer-/Uploadbelege. Das ist
ein eigener Windows-Nachweis mit unveränderten betroffenen C#-Quellen.

## Künftige Änderungen sicher nachziehen

Gemeinsame UI-, Datenmodell-, Übersetzungs- und Parseränderungen werden in ihren
kanonischen Linux-/Windows-Verzeichnissen weiterentwickelt. Mac projiziert die
aktuellen geprüften gemeinsamen Quellen. #783 verhindert das frühere unbemerkte
Zurücksetzen auf die alte Version `v2.0.30`. Neue native Funktionen benötigen
weiterhin einen tatsächlichen Mac-Anschluss; gemeinsames HTML allein aktiviert
keinen fehlenden Sync-, Telefon- oder Geräteadapter.

1. Aktuelle entfernte Ziel- und Arbeitszweig-Refs, sauberen Arbeitsbaum und
   `ARBEITSSTAND.md` lesen. Den Zielcommit und Kandidatencommit festhalten.
2. Änderungen seit dem letzten geprüften Stand mit Issues und betroffenen
   gemeinsamen/Mac-Dateien abgleichen. Parallelzweige, insbesondere Android,
   nach ihren tatsächlichen Diffs berücksichtigen; keine gemeinsame Workflow-
   Datei durch eine ältere vollständige Kopie ersetzen.
3. Die Gesamtübernahme zunächst in einem getrennten Prüfzweig oder Worktree
   zusammenführen. Konflikte in der maßgeblichen Quelle lösen; keine erzeugten
   `Generated`-Dateien als Ersatzquelle übernehmen. Der Integrationscommit ist
   der neue Prüfkandidat.
4. Vor den Bauvorbereitungen `candidate_sources.py record` auf genau diesen
   Commit ausführen. Kataloge und Abhängigkeiten mit dem vorhandenen Workflow
   vorbereiten, anschließend in diesem isolierten Baucheckout einfrieren und
   projizieren. Nach Tests/Bau `candidate_sources.py verify` ausführen.
5. Nach der folgenden Änderungsmatrix prüfen. Jede Wiederholung nennt ihren
   tatsächlichen Quellstand und ihre Grenzen. Ergebnisse alter Commits nur bei
   nachgewiesen gleichen relevanten Eingaben übernehmen; Paketmanifest und
   tatsächlicher Integrationscommit müssen dennoch zum neuen Paket passen.
6. Issue, Commit, Testkommando, Umgebung, Ergebnis, Skips und Paketprüfsumme
   im Arbeitsstand und im dauerhaften Prüfbeleg aktualisieren. Erst danach die
   konkret reviewbare Quellübernahme beziehungsweise Veröffentlichung freigeben.

| Geänderte Eingaben | Erforderliche passende Prüfungen |
| --- | --- |
| Gemeinsame UI/Modelle, Übersetzungen, Parser oder Verträge | Kanonische Regressionen, aktuelle Mac-Projektion, `check_current_sources.py`, betroffene Import-/Editor-/Kommunikationsfälle, beide native Mac-Jobs; Auswirkungen auf Linux/Windows getrennt prüfen |
| Swift-/AppKit-/Speicher-/Bridgecode | Betroffene negative Fälle und vollständige Swift-Kontexte, beide Architekturen, reale App-Lebensdauer und passende tatsächliche Bedien-/Speicherfälle |
| Runtimepins, Launcher, Bundlelayout oder Signatur | Runtimebuilder-/ImportHelpertests, echte native Builds beider Architekturen, Relokation aus fremdem Arbeitsverzeichnis, Modulabschluss, Architektur/Mindestversion/Systemlinks, verschachtelte und äußere Signatur, paketierte Inventare |
| Zeitzonendaten oder Kalendercodec | Unabhängige Zeitzonenreferenzen sowie native Kalender-/UTC-/Berlin-Kontexte; exakte Version/Hashes und Randfälle erhalten |
| Verpackung, Quellmanifest oder mitgelieferte Dokumente | Quellbindung und Projektionsreproduktion, Paketbau, Inventare/Hashes/Signaturen und passende Startprüfung des tatsächlichen neuen Pakets |
| Ausschließlich externe Berichts-/Belegtexte | Inhalts-, Quellanker-, Link- und Git-Diffprüfung; ohne Codeänderung keinen neuen nativen Produktfix behaupten |

## Was vor einer stabilen Mac-Veröffentlichung noch fehlt

| Gate | Status und konkreter Abschluss |
| --- | --- |
| Erweiterte ARM64-/Intel-CI | #104 auf `3f3ec069` bestanden; ein künftiger Integrations-/Paketstand braucht seine eigene passende Quellbindung und Prüfung |
| Getrennte Windows-CI / #794 | Neuerer Lauf Nr. 552 auf `8c860a14` erneut fehlgeschlagen: 551/552 Core-Gruppen, offener Cleanuprest `phone.db`; kein Windows-Fix oder Gesamtfreigabenachweis aus dieser Mac-Arbeit |
| Vollständige Dateiimporte / #785 | Klassische Parser/OR6, private Runtime und der echte Swift→Python-Prozessweg mit 9/9 Kriterien in #104 geprüft; echter Picker, importierte Daten nach Save/Beenden/Wiederöffnen, vollständiges `.magnolie`-Archiv und lokale Profilerkennung noch nicht vollständig abgenommen beziehungsweise implementiert |
| Vollständiger Apple-Abgleich / #786 | Begrenzter manueller Feldabgleich vorhanden; Neuanlagen/Löschungen, weitere Felder/Serien, Automatik, Notes-Rückabgleich und Recovery-/Provider-/Kontenprüfung offen |
| Verlustfreie Speicherung / #511 | Reminder-Textfix #797 ist eng begrenzt; vollständiger nativer Lade-/Speicher-/Exportpfad für opaque Unicode-JSON-Schlüssel und Erweiterungen bleibt offen |
| Reparatur vorhandener Kalenderduplikate / #465 | Explizite exakte Reparatur mit Referenzerhalt und tatsächlichem Save/Wiederöffnen bleibt offen |
| Mindestversion | Wirklicher Test auf macOS 12.7 erforderlich; Mach-O-Minimum 12.7 ersetzt keine Ausführung auf Monterey |
| Bedienung und Betrieb | Vollständige Editor-/Picker-/Dialog-/Tastatur-/VoiceOver-Abnahme, Berechtigungsverweigerung/-widerruf, Upgrade, Schreib-/Abbruchfehler und Wiederanlauf fehlen über die ausgewiesenen CI-Fälle hinaus |
| Echte Konten und Geräte | Tatsächlicher Apple-Provider-/Server-/iPhone-Rundlauf, KDE-Connect-Transport und AirPlay-Gegenstelle entsprechend den implementierten Fähigkeiten; kein eigener Mac oder eigene Notes-Begleitapp beim Nutzer vorausgesetzt |
| Auslieferung | Tatsächlich vorgesehenes Release-Paket bauen, Produktionssignatur/Notarisierung/Gatekeeper, Installation/Upgrade und veröffentlichte Prüfsummen passend zum Paket abnehmen |

Die [vollständige Funktionsmatrix](../Magnolie-Organizer-macOS-Beta/FEATURE-MATRIX.md)
führt weitere ausdrücklich noch fehlende Funktionen auf. Ein neuer grüner
Build erledigt diese Produktlücken nicht. Der
[Mac-/VM-Abnahmeplan](../Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md)
legt die praktischen Schritte für die noch offenen nativen Prüfungen fest.

## Angeforderte erneute Stabilitätsprüfung

Die erneute Prüfung nach dem erfolgreichen #97-Abschluss hat die tatsächliche
Git-Übernehmbarkeit, funktionale Wiederherstellung der Originalpatches und die
gemeinsamen Hostregressionen abgeschlossen. Unter anderem bestehen 444 Pythonfälle
mit 14 Untertests, die vollständige Linux-Parserprobe mit 1137 ausgegebenen
Prüfungen, Linux-/Windows-Webprüfungen und die Zeitzonenverträge. Die Umfänge
überlappen und sind im [Stabilitätsbericht](../Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md)
mit ihren genauen Quellständen und Grenzen aufgeschlüsselt. Die ursprünglichen
44 Befehlslogs und zwei Abhängigkeitslogs sind vollständig dauerhaft eingebettet.
Die Nachprüfung der Baugrenzen bestätigte #806 und später #808; beide besitzen
eigene reproduzierte Negativfälle und eng begrenzte Fixes. Der vollständige
ARM64-/Intel-Lauf #104 hat die erweiterte CI-Kette auf `3f3ec069` bestanden.

Der [#104-Abschlussbeleg](../Magnolie-Organizer-macOS-Beta/verification/native-run-104.json)
weist für **jede** Architektur folgende getrennte Umfänge aus:

| Prüfung | Tatsächliches Ergebnis je Architektur |
| --- | --- |
| Runtime-/AirPlay-/ImportHelpertests | 26 / 27 / 17 bestanden, keine Fehler oder Skips |
| Hostfälle | 34 bestanden, ein ausdrücklich Linux vorbehaltener negativer Baufall übersprungen; keine Fehler |
| Vier Debug-Swift-Kontexte | Je 501 gleich benannte Fälle; 497/496/496/495 bestanden und 4/5/5/6 Skips, keine Fehler |
| Separater Release-Swift-Kontext | Dieselben 501 Namen; 495 bestanden, sechs Skips, keine Fehler |
| Tatsächlicher Swift→privater Python-Prozess | 9/9 Kriterien mit originaler OR6-Fixture und begrenzten Ablehnungsfällen bestanden |
| Tatsächlicher App-Lebenszyklus | 7/7 Kriterien für Start, frisches Profil, Speichern, normales Beenden und Wiederöffnen bestanden |
| Unabhängige nachgelagerte Byteprüfung | 65/65 Kriterien je Entwicklungspaket bestanden; keine erneute native Ausführung oder Signaturvertrauensprüfung durch den Linux-Audit |

Die fünf Swift-Kontexte wiederholen dieselben 501 Testnamen und werden nicht
zu unabhängigen eindeutigen Tests addiert. Beide nativen Quellmanifeste binden
dieselben **3921 Dateien** an `3f3ec069`. Private Runtime, Relokation,
verschachtelte und äußere Signatur sowie die Entwicklungspaketierung bestanden
in den tatsächlichen Mac-Jobs. Spätere Dokumentationsstände und neue
Integrationscommits erhalten weiterhin eigene Quellnachweise.

Der neue native Lauf ergänzt außerdem eine getrennte optimierte Swift-Prüfung
(`swift test -c release --jobs 2`). Das tatsächlich paketierte Artefakt bleibt
ausdrücklich das ad-hoc signierte Debug-Entwicklungsbundle. Ein bestandener
optimierter Test ist keine Produktionssignatur oder fertige stabile Ausgabe.

Die gezielte Gegenprüfung bestätigte einen zusätzlichen Metadatenvalidatorbefund
[#806](https://github.com/maik3531/Magnolie-Organizer/issues/806): Der bisherige
Runtime-/App-Prüfer wertete Architektur und Mindestversion, aber nicht ausdrücklich
die Apple-Zielplattform aus. Die echten #97-Pakete besitzen macOS-Metadaten und
bleiben gültige Belege. Der enge Folgefix lehnt fremde oder mehrdeutige Plattformen
ab; beide nativen Baupfade haben anschließend in #104 bestanden. Die isoliert
veränderten Negativfixtures sind kein Nachweis, dass die vollständigen Signatur-
und Relokationsgates falsche Plattformen akzeptiert hätten.

Der ursprüngliche separate #806-Quellfix `6599dcb2` führte vor #100 lokal 24 Runtimebuilderfälle aus:
23 bestanden, ein ausdrücklich Darwin vorbehaltener Fall übersprungen.
26 AirPlay-Boundarytests bestanden. Die neue Darwin-Regressionsprüfung baut
eine winzige echte Mach-O-Datei und prüft mit den realen Apple-Werkzeugen die
gezielt veränderten iOS-/Catalyst-/Simulator-Plattformfelder. Sie führt keinen
veränderten Code aus. Nach der dokumentierten `vtool`-Korrektur hat sie auf
beiden Macs in #102 und #103 tatsächlich bestanden.
[Vorher-/Nachherbelege samt Prüflogs und Quellenhashes](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/runtime-review.json)
halten die lokalen Ergebnisse dauerhaft fest. Für AirPlay wurde außerdem eine
übertragbare Mehrdeutigkeitslücke bestätigt: Eine spätere zweite Metadatenangabe
konnte zuvor eine falsche Plattform oder zu neue Mindestversion verdecken.
Auch diese Mehrfachangaben werden nun abgelehnt; der optionale AirPlay-Receiver
ist dadurch noch nicht gebaut oder mit einem Gerät abgenommen.

Der neue Prozessgrenzentest verwendet unveränderte Produktionsquellen von
`FileImportProcess.swift`, die bereits gebauten echten BetaCore-Objekte und das
tatsächliche signierte App-Bundle. Eine originale OR6-Datei läuft durch
Swift-Dateilesen, Protokoll, Prozessstart und privaten Python-Parser; ausgewählte
Datensatzinhalte sowie Ablehnung fehlerhafter Eingaben werden geprüft.
Das prüft keinen Dateiauswahldialog, keinen Editor und kein gespeichertes Buch.
[Zehn lokale Treiberprüfungen](../Magnolie-Organizer-macOS-Beta/verification/stability-2026-11-26/native-process-driver-local.json)
bestanden vor dem nativen Start: echte Fixturevorbereitung, Prozessabschluss,
Ausgabegrenze, Deadline, Fehlerpfade und ausdrückliche Linux-Ablehnung.
Diese damaligen lokalen Tests belegen allein die Prüfinfrastruktur. Der
anschließende #104-Lauf hat zusätzlich den tatsächlichen Swift-Link und alle
neun Prozesskriterien auf beiden Macs bestanden. Die nicht mitgelieferten
BetaCore-Objekte und das kompilierte Prüfprogramm sind durch native Receipts
und Logs gebunden; ihre Bytes wurden im späteren Linux-Audit nicht erneut
gehasht. Picker-, Editor-, Import-Save-/Wiederöffnungs-, TCC-, Konto- und
Geräteabnahme bleiben die oben ausgewiesenen offenen Gates.
