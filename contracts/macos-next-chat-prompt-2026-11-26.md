# Mac-Übergabe: Zusammenfassung und Fortsetzungs-Prompt

**Stand der Vorlage: 26. November 2026.** Diese Datei hält den Arbeitsauftrag
auch über Chatgrenzen hinweg fest. Der kopierfertige Prompt unten ist ebenso
nach Abschluss der Veröffentlichung verwendbar: Er verlangt zuerst eine
Bestandsprüfung und setzt bereits erledigte Schritte nicht erneut in Gang.

## Bekannte Ausgangspunkte

| Bedeutung | Gesicherter Anker |
| --- | --- |
| Repository | [maik3531/Magnolie-Organizer](https://github.com/maik3531/Magnolie-Organizer) |
| Veröffentlichter Arbeits-/Übergabezweig | `work/macos-issue-fixes-20261126`; tatsächlichen Remote-Stand vor Fortsetzung lesen |
| Erfolgreich geprüfter Quellstand der erweiterten Nachprüfung | `3f3ec069895dec254c53660d14e6851cb23077cd`; [Lauf #104](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062), Gesamtworkflow und beide Mac-Jobs `completed/success` |
| Zuletzt lesend bestätigte gemeinsame Basis | `main` auf `d4da48a5eadd0bda22422b924bef4ee3b4324040`, 26. November 2026 um 14:52:15 Uhr Europe/Berlin (13:52:15 UTC); vor späterer Integration erneut lesen |
| Vollständiger ursprünglicher Übergabecommit einschließlich Bericht | `0dfeb1b30a208480eb6901e3d3148a5efeaae5ff` |
| Geprüfter Codecommit der ursprünglichen Linux-Übergabe | `7c9cf20394aef73d261a77f746ebca7340826d30` |
| Über die API angelegter Quellcommit A | `8efc6834abd16f18300f3d59a1897c81758b0c34` |
| Identischer Quellbaum von Originalübergabe und Commit A | `d731a6bd56acd68e79aab83fbadb19ab94ad6547` |
| Weitere Folgeinhalte | Publikationsbelege, wiederherstellbare Git-Artefakte und ergänzende Windows-Forschung; den finalen Head aus dem Repository feststellen |

Ein identischer Git-Tree beweist identische getrackte Inhalte an diesen beiden
Ankern, nicht eine identische Commit-Historie. Für originale Einzelcommits und
Patchreihenfolge die Wiederherstellungsanleitung verwenden. Einen späteren
Dokumentations-Head nicht als neuen vollständig getesteten Codecommit ausgeben.

**Verifizierter Abschluss der ursprünglichen Übergabe am 26. November 2026:** Der Arbeitszweig ist veröffentlicht. Alle **31 Issue-Kommentare** wurden angelegt und mit identischem vollständigem Text zurückgelesen. Ihre Dokument- und Patchlinks sind an `cf7b3f2bf4e8afee662a4926f32fc989d7ff7df8` gebunden. [Die vollständigen Kommentar-URLs und Rücklesebelege](macos-issue-publication-receipts-2026-11-26.md) dokumentieren den Abschluss. Vollständige native UI-/Monterey-/Konto-/Geräteabnahme und die ausdrücklich genannten Restarbeiten bleiben offen; den späteren erfolgreichen CI-Umfang von #97 gesondert beachten. Ein neuer Chat prüft den heutigen Stand und veröffentlicht diese Übergabe nicht erneut.

**Native Fortsetzung:** Die späteren echten GitHub-Mac-Läufe #91 bis #95
sind im Fortsetzungsbericht unten dokumentiert. #92 hat die Swift-Korrekturen
und Zeitzonenreferenzphasen auf ARM64 und Intel bestätigt und anschließend den
Runtime-Baurest #789 konkret gezeigt. #93 hat den korrigierten Runtimebau
einschließlich isoliertem Modulabschluss auf beiden Architekturen bestanden
und danach den Tempwurzelrest der Prüftreiber #793 sichtbar gemacht.
#94 bestätigt den Tempwurzelfix mit 17 ImportHelper-/Pfadtests und 90 OR6→UI-
Prüfungen auf beiden Architekturen. Die folgenden Host-/Swift-Fälle sind in
#796/#797 getrennt mit ihren tatsächlichen Ursachen dokumentiert.
#95 auf `3c0b4bb410a5ab514e3deae7fb665a692eb436c2` bestätigt beide
gesamten Hostläufe mit 35 Tests, 0 Fehlern und 1 Skip sowie je vier
Swift-Durchläufe mit jeweils 501 Tests ohne Fehler (4/5/5/6 Skips).
Erst die äußere Appsignatur zeigt den neuen Bundlelayoutrest #802;
App-Smoke und Entwicklungspaketierung wurden in diesem Lauf nicht erreicht.
Der veröffentlichte Layoutfix liegt auf
`215d89029df02df2dce78f35412785ec9f9b36d8`.
[Lauf #97 / 45807249788](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
hat genau diesen Stand auf ARM64 und Intel vollständig im definierten
CI-Umfang bestanden: Runtimebau, 21 Runtimebuilder-/17 ImportHelpertests,
35 Hosttests ohne Fehler mit einem Skip, vier Swift-Kontexte mit jeweils
501 Fällen ohne Fehler (4/5/5/6 Skips), äußere Appsignatur, echter
Start-/Speicher-/Beenden-/Wiederöffnungsablauf und Entwicklungspaketierung.
Der Gesamtworkflow ist `completed/success`. Beide CI-Entwicklungsartefakte
haben 14 Tage Aufbewahrung; die vollständige UI-/Monterey-/Konto-/Geräteabnahme
ist davon getrennt und bleibt offen.
Der
Windows-Archivfix #787 besteht nativ; der separate Windows-Cleanuprest #794
ist ein Folgeauftrag und kein erledigter Produktfix.
Der ursprüngliche Hostnachweis bleibt
historisch; er darf weder diese neuen Befunde ersetzen noch als vollständige
native Abnahme gelesen werden. Den aktuellen Head und neuere Läufe nachlesen.

**Erweiterter nativer Abschluss:** [#104 / 45827353062](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
bestand auf `3f3ec069895dec254c53660d14e6851cb23077cd` mit Tree
`176fa7f362227c92ec4d7c4bf08d09b855951ae7` am 26. November 2026 von
**14:15:18 bis 14:49:42 Uhr Europe/Berlin**. Gesamtworkflow und beide
Mac-Jobs sind `completed/success`. Je Architektur bestanden 26 Runtime-,
27 AirPlay- und 17 ImportHelperfälle sowie 34 Hostfälle mit einem ausdrücklich
Linux vorbehaltenen Skip. Vier Debug- und ein Release-Swift-Kontext prüfen
dieselben 501 Namen; Debug hat 4/5/5/6 Skips, Release 495 bestandene Fälle,
sechs Skips und keine Fehler. Diese Kontexte werden nicht als unabhängige
eindeutige Tests addiert.

Der echte Swift→private-Python-Prozess mit originaler OR6-Fixture besteht
9/9 Kriterien; der tatsächliche App-Lebenszyklus besteht 7/7. Die nachgelagerte
unabhängige Byteprüfung besteht je Paket 65/65 Kriterien und ist keine erneute
native Ausführung oder Signaturvertrauensprüfung. Beide Quellmanifeste binden
dieselben 3921 Dateien an `3f3ec069`. Der
[dauerhafte #104-Beleg](../Magnolie-Organizer-macOS-Beta/verification/native-run-104.json)
erhält Details, Skips und Hashes. Das Paket bleibt Debug/ad-hoc; tatsächlicher
Picker/Editor, dauerhaft gespeicherte Importdaten, Monterey, TCC, Konten,
Geräte und Produktionsauslieferung bleiben gesonderte offene Gates.

## Maßgebliche Dokumente

- [Aktuelle Stabilitätsprüfung mit gemeinsamen Regressionen und neuen nativen Laufbelegen](../Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md)
- [Dauerhafter nativer Abschlussbeleg #104](../Magnolie-Organizer-macOS-Beta/verification/native-run-104.json)
- [Stabile Übernahme: Quellanker, Folgepatches, künftige Änderungen und Freigabematrix](macos-stable-integration-2026-11-26.md)
- [Fortsetzung: tatsächliche native Mac-Läufe und Folgefixes #787/#788/#789/#793/#796/#797/#802](../Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md)
- [Einzelbefunde, Patchreihenfolge und offene Teile](macos-issue-handoff-2026-11-26.md)
- [Vollständiges Issue-Inventar](macos-issue-inventory-2026-11-26.json)
- [Prüflogs und Quellbindungen](macos-verification-2026-11-26/README.md)
- [Publikation und Wiederherstellung der Originalhistorie](macos-issue-publication-2026-11-26/CODEX-RESTORE.md)
- [Tatsächliche Umgebung und künftige macOS-/VM-Abnahme](../Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md)
- [Dell/NFC/Telefon/Auth: recherchierte Fähigkeiten und Prüfplan](windows-dell-nfc-research-2026-11-26.md)
- [Windows: ergänzende Feature-Möglichkeiten](windows-feature-opportunities-2026-11-26.md)

## Prüfstatus und wesentliche Grenzen

Der ursprüngliche Linux-Hostlauf auf
`7c9cf20394aef73d261a77f746ebca7340826d30` bestand **35/35 Gruppen**.
Zusätzlich ausgewiesen sind **90 OR6→Helper→UI-Prüfungen** und **107
Sync-UI-Prüfungen**. Dies ist der historische Übergabenachweis, kein aktueller
nativer Mac-Vollpass. Die Umfänge überlappen und werden nicht addiert.
Rohbelege und genaue Quellstände stehen im Prüfverzeichnis. Die ursprünglichen
Testtreiberfehler und ihre Korrekturen dürfen nicht aus dem Nachweis entfernt
werden.

Die ursprüngliche lokale Arbeitsumgebung „Magnolie-Organizer einrichten“
war Linux x86_64. Dort liefen keine native Swift-Kompilierung, Apple-SDK-
Abnahme oder macOS-VM. Die späteren tatsächlichen GitHub-Mac-Läufe sind
gesonderte Ausführungen auf entfernten Mac-Hosts. Vorbereitete Provider-/
TCC-Prüfungen und historische grüne Läufe auf älteren Quellen beweisen
keine darüber hinausgehende aktuelle Abnahme.

Die 31 berücksichtigten Issues sind:
`121, 451, 452, 453, 454, 458, 464, 465, 468, 472, 511, 680, 682, 683, 721,
749, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 781, 783, 784, 785, 786`.
Das Inventar dokumentiert daneben Ausschlüsse und historische Fälle. Nicht
jedes berücksichtigte Issue benötigt einen neuen Produktpatch: bestätigte
Bestandsfixes, Regressionen und offene native Abnahmen bleiben unterscheidbar.

Die wichtigen offenen Teile umfassen die vollständige native UI-/Systemkonto-/
Monterey-/Geräteabnahme, ausgewiesene
Restfälle der Kalenderalias-/verlustfreien Übernahme, weitere Importgrenzen
sowie den noch begrenzten Systemabgleich. #786 bietet einen manuellen
Dreiwege-Feldabgleich bewusst gebundener bestehender Kalender-/Kontakt-/
Erinnerungsdatensätze. Neuanlagenexport, Löschungen, weitere Felder/Serien,
Automatik, geführte Ungewissheits-Recovery und vollständiger Apple-Notes-
Rückabgleich sind damit nicht als fertig belegt. Einzelheiten und konkrete
Abnahmeschritte stehen in den Issue-Verträgen.

## Kopierfertiger Prompt für den nächsten Chat

Den folgenden Block vollständig kopieren. Falls beim Abschluss neuere
verifizierte Beleg-URLs oder ein finaler Branch-Head vorliegen, können sie
zusätzlich darunter eingefügt werden; die Bestandsprüfung bleibt erforderlich.

```text
Setze den bestehenden Auftrag für maik3531/Magnolie-Organizer fort. Lies zuerst
den tatsächlichen Stand und führe nur noch fehlende, bereits beauftragte Arbeit
aus. Starte weder Audit noch Veröffentlichung pauschal von vorn.

URSPRÜNGLICHER AUFTRAG
Alle macOS-bezogenen Issues prüfen, konkrete reviewbare Fixpatches samt Belegen,
Beschreibung, Abhängigkeiten und Codex-Anweisungen vorbereiten und den jeweiligen
Issues zuordnen. Codex soll die Änderungen später prüfen und anwenden können.
Teilfixe, bereits behobene Fälle, Tests und offene Arbeit transparent ausweisen.
Die Übernahme nach main, Issue-Schließungen und öffentliche Release- oder
Vertriebspaketveröffentlichungen sind durch diesen Fortsetzungs-Prompt nicht
beauftragt. Native CI-Prüfungen auf dem bestehenden Arbeitszweig und deren
zeitlich begrenzte CI-Entwicklungsartefakte gehören zur autorisierten
Fortsetzung. Diese Artefakte sind keine Produktionsfreigabe.

FOLGEAUFTRAG ZUR STABILEN ÜBERNAHME
Der Nutzer verlangt zusätzlich eine dauerhafte Dokumentation, damit kommende
Änderungen später übernommen werden können, und eine gründliche erneute
Prüfung vor der nächsten stabilen Veröffentlichung. Wiederherstellung,
gemeinsame Regressionen und Integration sind dokumentiert; den aktuellen
Abschluss der erweiterten nativen Prüfungen zuerst aus dem Stabilitätsbericht
lesen. Eine CI-Freigabe ersetzt keine fehlende Produktfunktion oder reale
UI-/Monterey-/Provider-/Geräte-/Distributionsabnahme.

ZUERST BESTAND PRÜFEN
1. Repository https://github.com/maik3531/Magnolie-Organizer und den Zweig
   work/macos-issue-fixes-20261126 lesen. In vorhandenen Checkouts zuerst
   git status, AGENTS.md und ARBEITSSTAND.md prüfen; Benutzeränderungen erhalten.
2. Diese Dateien lesen:
   - Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md
   - Magnolie-Organizer-macOS-Beta/verification/native-run-104.json
   - contracts/macos-stable-integration-2026-11-26.md
   - Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md
   - contracts/macos-issue-handoff-2026-11-26.md
   - contracts/macos-issue-inventory-2026-11-26.json
   - contracts/macos-issue-publication-receipts-2026-11-26.md
   - contracts/macos-issue-publication-receipts-2026-11-26.json
   - contracts/macos-verification-2026-11-26/README.md
   - contracts/macos-issue-publication-2026-11-26/CODEX-RESTORE.md
   - Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md
3. Tatsächlichen Remote-Head, vorhandene Wiederherstellungsartefakte und deren
   Prüfsummen feststellen. Eine lokale Datei oder ein vorbereiteter Upload ist
   noch kein Beweis einer erfolgten GitHub-Veröffentlichung. Falls ursprüngliche
   Einzelcommits fehlen, nach CODEX-RESTORE.md vorgehen; keine Historie erfinden.
4. Für alle unten genannten Issues die vorhandenen Kommentare einschließlich
   Folgeseiten lesen. Nach macos-issue-audit-2026-11-26:N suchen, wobei N die
   Issue-Nummer ist, zum Beispiel macos-issue-audit-2026-11-26:771. Marker,
   Kommentar-ID/URL, Inhalt und darin genannten Quellstand zusammen prüfen.
   Bereits passende Kommentare nicht erneut posten. Einen fehlenden oder
   nachweislich veralteten Teil gezielt ergänzen und den Abschluss belegen.
   Keine pauschale Aussage „alle Kommentare veröffentlicht“ ohne Einzelabgleich.

BEREITS ABGESCHLOSSENE ÜBERGABE
Der Zweig und alle 31 Kommentare sind veröffentlicht und zurückgelesen.
Die Kommentarlinks verwenden den festen Dokumentations-/Artefaktcommit
cf7b3f2bf4e8afee662a4926f32fc989d7ff7df8. Die Publikationsbelege enthalten
alle Kommentar-IDs, URLs und Text-Hashes. Diese Schritte nicht neu ausführen.
Vollständige native UI-/Monterey-/Konto-/Geräteabnahme und die dokumentierten
technischen Reste bleiben offen; die genauen späteren nativen CI-Umfänge beachten.

QUELLANKER
- Erfolgreich geprüfter erweiterter nativer Quellstand nach #806/#793/#808:
  3f3ec069895dec254c53660d14e6851cb23077cd
  Tree 176fa7f362227c92ec4d7c4bf08d09b855951ae7
  https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062
  Lauf #104, Attempt 1, 26.11.2026 14:15:18–14:49:42 Europe/Berlin
  (13:15:18–13:49:42 UTC). Gesamtworkflow und beide Mac-Jobs completed/success.
  Den vollständigen Abschlussbeleg verification/native-run-104.json im
  Mac-Verzeichnis lesen. Die Zwischenfehler #100/#102/#103 bleiben erhalten.
  Ein späterer Dokumentationshead ist nicht der native Prüfcommit.
- Gemeinsame Basis zum letzten gelesenen Refstand:
  main auf d4da48a5eadd0bda22422b924bef4ee3b4324040,
  erneut lesend bestätigt am 26.11.2026 um 14:52:15 Uhr Europe/Berlin (13:52:15 UTC).
  Die konfliktfreie 0/23-Integrationsprobe vom selben Tag 13:16:51–58 UTC
  bezieht sich exakt auf 3f3ec069, nicht auf spätere Dokumentationscommits.
  Vor tatsächlicher Übernahme beide Refs neu lesen; ein neuer Integrationscommit
  benötigt seine eigenen passenden Quell-, Test- und Paketnachweise.
- Historischer vollständiger Vorgängerlauf #97 auf Helper-Bundle-Fixcommit:
  215d89029df02df2dce78f35412785ec9f9b36d8
  https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788
  Gesamtworkflow und beide Mac-Jobs erfolgreich. Host-/Swift-Tests,
  vollständige Appsignatur, sieben tatsächliche Lifecycle-Kriterien und
  Entwicklungspaketierung bestanden. Die genauen Belege und Grenzen im
  Fortsetzungsbericht lesen; keine Voll-UI-/Monterey-/Kontenabnahme daraus ableiten.
- Nativer Folgelauf #95 auf tatsächlichem Quellcommit:
  3c0b4bb410a5ab514e3deae7fb665a692eb436c2
  https://github.com/maik3531/Magnolie-Organizer/actions/runs/45799895334
  Host-/Swift-Tests auf ARM64 und Intel erfolgreich; danach äußerer
  App-Signaturrest #802. Neuere Layoutfixes und deren genaue Abnahme im
  Fortsetzungsbericht und im tatsächlichen Repository-Head lesen.
- Vollständiger ursprünglicher Übergabecommit:
  0dfeb1b30a208480eb6901e3d3148a5efeaae5ff
- Geprüfter Codecommit der ursprünglichen Linux-Übergabe:
  7c9cf20394aef73d261a77f746ebca7340826d30
- API-Quellcommit A:
  8efc6834abd16f18300f3d59a1897c81758b0c34
- Originalübergabe und API-Commit A besitzen den identischen Tree:
  d731a6bd56acd68e79aab83fbadb19ab94ad6547
Dokumentation, Git-Artefakte und Windows-Forschung können danach hinzugekommen
sein. Den aktuellen Head nachlesen. Gleicher Tree bedeutet nicht gleiche
Historie; die originalen Patchabhängigkeiten bleiben maßgeblich.

ISSUES
121, 451, 452, 453, 454, 458, 464, 465, 468, 472, 511, 680, 682, 683, 721,
749, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 781, 783, 784, 785, 786.
Das Inventar enthält auch die begründeten Ausschlüsse und historischen Fälle.
Den Umfang anhand des aktuellen Inventars prüfen, nicht aus Suchbegriffen neu
und unbemerkt erweitern. Kein neuer Patch allein deshalb, weil ein Issue offen ist.

VERBINDLICHE NUTZERVORGABEN
- Aktuelle Linux-/Windows-Quellen sind der Vergleichsstand für den Mac. Ältere
  veröffentlichte Desktopquellen nicht wieder in den aktuellen Mac-Bau kopieren.
- Alle vorgesehenen Dateiimporte einschließlich des aktuellen OR6 prüfen.
  Parserparität, tatsächliche UI-Vorschau, Konflikte, Save-ACK und dauerhafte
  Speicherung auseinanderhalten. #785 und IMPORT-RUNTIME.md beachten.
- Keine eigene Magnolie-Notes-Begleitapp für Mac/iPhone voraussetzen oder neu
  entwickeln. Notizfunktionen im Organizer bleiben im Prüfumfang.
- Vorhandenes KDE Connect darf auf Mac/Windows/iPhone genutzt werden. Externen
  Dateitransport und direkte Magnolie-Gerätesteuerung getrennt behandeln;
  Fähigkeiten der tatsächlichen Gegenstelle prüfen. Kein pauschales KDE-Verbot.
- Echter Abgleich mit Apple-Programmen ist gewünscht. Vorhandene Kopierimporte
  sind keine Freigabe für Rückschreiben. Den implementierten schmalen #786-
  Feldabgleich von noch fehlendem Create/Delete, weiteren Feldern, Serien,
  Automatik, Ungewissheits-Recovery und Apple-Notes-Rückabgleich unterscheiden.
  Keine vollständige Linux-Parität oder atomare Apple-Server-CAS behaupten.
- Der Nutzer hat keinen persönlichen Mac als Testvoraussetzung. Die hier
  benannte Umgebung „Magnolie-Organizer einrichten“ ist Linux x86_64; keine
  vorhandene lokale Mac-VM behaupten. Der dokumentierte künftige Prüfweg nutzt
  tatsächlich verfügbare passende macOS-/Cloud-VMs, sofern eingerichtet.
- Was mangels Umgebung oder Gegenstelle nicht ausführbar ist, konkret mit
  Voraussetzungen, Codex-Schritten, Testfällen und erwarteten Ergebnissen
  vorbereiten. Fehlende native Abnahme ausdrücklich offen lassen.
- Die Windows-/Dell-/NFC-Forschung beschreibt neue Vorschläge. Sie belegt keine
  bereits implementierten Funktionen. contracts/windows-dell-nfc-research-2026-11-26.md und
  contracts/windows-feature-opportunities-2026-11-26.md sind Forschungs-/
  Planungsergebnisse. Nutzer-PC, NFC-Leser und Telefon wurden nicht geprüft.

BELEGTER PRÜFSTAND
Lauf #104 auf 3f3ec069 besteht auf ARM64 und Intel die vollständige definierte
erweiterte CI-Kette. Je Architektur: 26 Runtime-, 27 AirPlay-, 17 Helperfälle;
34 Hostfälle bestanden und ein negativer Linux-only Baufall übersprungen.
Vier Debugkontexte und ein Releasekontext wiederholen dieselben 501 Testnamen:
Debug mit 4/5/5/6 Skips, Release 495 bestanden, sechs Skips, keine Fehler.
Der echte Swift→private-Python-Prozess besteht 9/9 Kriterien; der tatsächliche
App-Lebenszyklus 7/7. Unabhängige Byteaudits bestehen je Paket 65/65 Kriterien;
deren Linux-Auswertung ist keine erneute native Ausführung oder codesign-Prüfung.
Der Prozessnachweis ist keine Picker-/Editor-/Import-Save-/Kontenabnahme;
das paketierte Artefakt bleibt Debug/ad-hoc und wurde auf macOS 15 geprüft.

Die gemeinsame erneute Hostregression ist auf c8a7690d / Produktcode 215d890
gebunden: 444 Pythonfälle und 14 Untertests, die vollständige Linux-Parserprobe,
Linux-/Windows-Webprüfungen und Zeitzonenfälle. Genaue Einzelzahlen/Grenzen
stehen im Stabilitätsbericht; keine überlappenden Umfänge zusammenzählen.
Der reine Git-Nachvergleich bestätigt identische gemeinsame Produktquellen
bis 3f3ec069; das ist keine nochmalige Testausführung. Die 24 Originalpatches
wurden tatsächlich wiederhergestellt, jeder Zwischenbaum wurde exakt geprüft.
#806 belegt nun die eindeutige echte macOS-Zielplattform; #808 erhält
Archivzeitstempel und ist mit echtem Make sowie gepinntem XZ nachgeprüft.
Die vollständigen Vorher-/Nachherbelege sowie native-run-100/102/103.json
erhalten die tatsächlichen Fehler. Der erfolgreiche #104-Abschluss ergänzt
diese Historie mit eigenem Endbeleg. Spätere Quelländerungen nach der
Änderungsmatrix erneut prüfen; weder den Hosttestanker noch #104 nachträglich
auf einen späteren Dokumentations- oder Integrationscommit umbenennen.
Der zusätzliche Windows-Lauf Nr. 552 / 45820275770 auf 8c860a14 ist mit
551/552 Core-Testgruppen fehlgeschlagen und bestätigt den getrennten
Cleanuprest #794 erneut. Die betroffenen C#-Quellen wurden hier nicht
geändert; keinen Windows-Pass oder Windows-Fix aus Mac-Ergebnissen ableiten.

Im ursprünglichen Linux-Nachweis bestanden 35/35 Hostgruppen; gesondert ausgewiesen sind 90 OR6→Helper→UI-
Prüfungen und 107 Sync-UI-Prüfungen. Diese Umfänge überlappen und werden nicht
addiert. Logs und Quellbindungen verwenden. Die ursprünglichen nativen
GitHub-Läufe bis einschließlich #97 stehen in
Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md.
Die erweiterte Nachprüfung ab #100 steht in
Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md.
Beim jeweiligen Lauf zuerst den erreichten Schritt, genauen Quellcommit
und Ausgang prüfen.
Swift-/Zeitzonenerfolg, Runtimebau, XCTest, Bundle-/App-Start sowie echte
TCC-/Provider-/Gerätetests bleiben getrennte Nachweise. Vorbereitete Tests und
historische CI-Erfolge auf älteren Quellen nicht als aktuelle native Erfolge
ausgeben. Die Folgeissues #787/#788/#789/#793/#796/#797/#802/#806/#808 und den separaten
Windowsrest #794 gezielt mitlesen. Ein nativer Runtime-/Testteilerfolg ist
kein vollständiger App-Smoke- oder echter Konten-/Gerätenachweis.

ARBEITSWEISE UND ABSCHLUSS
Für neue Konten-/Geräteprüfungen synthetische Daten und ausdrücklich
eingerichtete Testquellen verwenden; dieser Übergabeauftrag enthält keinen
Zugang zu persönlichen Apple-Konten oder zum Windows-PC des Nutzers.
Nach der Bestandsprüfung fehlende Patch-/Issue-Zuordnungen und Belege gezielt
fertigstellen. Bestehende Autorisierung zur konkreten Issue-Übergabe nutzen;
keinen zweiten gleichlautenden Kommentar erzeugen. Sind alle Übergabeschritte
bereits erledigt, dies mit Branch-/Kommentar-/Artefaktbelegen bestätigen und
den nächsten ausgewiesenen Abnahme- oder Restpunkt benennen. Keine unnötige
Wiederholung unveränderter Tests und keine unbegrenzte Funktionsausweitung.

Wenn ein Wechsel des Chats absehbar sinnvoll wird, rechtzeitig eine aktuelle
Zusammenfassung und einen vollständig kopierfertigen Fortsetzungs-Prompt geben:
Ziel, Nutzervorgaben, aktuelle Quellstände, tatsächliche Ergebnisse, offene Teile,
erfolgte externe Aktionen mit URLs und der konkrete nächste Schritt. Dabei
keinen exakten verbleibenden Chat-/Tokenraum oder erfolgten Veröffentlichungs-
status erfinden. Relevanten Stand auch in der Repository-Übergabe festhalten.
```

## Bei einer späteren Aktualisierung

Neue Abschlussangaben nur nach Prüfung ergänzen: tatsächlicher Branch-Head,
verifizierte Artefakt-/Kommentar-URLs, noch offene Issues oder Abnahmen sowie
der konkrete nächste Schritt. Die historischen Quell- und Testanker oben
bleiben erhalten. Nachträgliche Dokumentation allein verändert keinen
vorangegangenen Testnachweis.
