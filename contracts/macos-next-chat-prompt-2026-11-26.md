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
| Vollständiger ursprünglicher Übergabecommit einschließlich Bericht | `0dfeb1b30a208480eb6901e3d3148a5efeaae5ff` |
| Zuletzt vollständig geprüfter Codecommit dieser Übergabe | `7c9cf20394aef73d261a77f746ebca7340826d30` |
| Über die API angelegter Quellcommit A | `8efc6834abd16f18300f3d59a1897c81758b0c34` |
| Identischer Quellbaum von Originalübergabe und Commit A | `d731a6bd56acd68e79aab83fbadb19ab94ad6547` |
| Weitere Folgeinhalte | Publikationsbelege, wiederherstellbare Git-Artefakte und ergänzende Windows-Forschung; den finalen Head aus dem Repository feststellen |

Ein identischer Git-Tree beweist identische getrackte Inhalte an diesen beiden
Ankern, nicht eine identische Commit-Historie. Für originale Einzelcommits und
Patchreihenfolge die Wiederherstellungsanleitung verwenden. Einen späteren
Dokumentations-Head nicht als neuen vollständig getesteten Codecommit ausgeben.

**Verifizierter Abschluss am 26. November 2026:** Der Arbeitszweig ist veröffentlicht. Alle **31 Issue-Kommentare** wurden angelegt und mit identischem vollständigem Text zurückgelesen. Ihre Dokument- und Patchlinks sind an `cf7b3f2bf4e8afee662a4926f32fc989d7ff7df8` gebunden. [Die vollständigen Kommentar-URLs und Rücklesebelege](macos-issue-publication-receipts-2026-11-26.md) dokumentieren den Abschluss. Die native Mac-Abnahme und die ausdrücklich genannten Restarbeiten bleiben offen. Ein neuer Chat prüft den heutigen Stand und veröffentlicht diese Übergabe nicht erneut.

**Native Fortsetzung:** Die späteren echten GitHub-Mac-Läufe #91 und #92
sind im Fortsetzungsbericht unten dokumentiert. #92 hat die Swift-Korrekturen
und Zeitzonenreferenzphasen auf ARM64 und Intel bestätigt und anschließend den
Runtime-Baurest #789 konkret gezeigt. Der ursprüngliche Hostnachweis bleibt
historisch; er darf weder diese neuen Befunde ersetzen noch als vollständige
native Abnahme gelesen werden. Den aktuellen Head und neuere Läufe nachlesen.

## Maßgebliche Dokumente

- [Fortsetzung: tatsächliche native Mac-Läufe und Folgefixes #787/#788/#789](../Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md)
- [Einzelbefunde, Patchreihenfolge und offene Teile](macos-issue-handoff-2026-11-26.md)
- [Vollständiges Issue-Inventar](macos-issue-inventory-2026-11-26.json)
- [Prüflogs und Quellbindungen](macos-verification-2026-11-26/README.md)
- [Publikation und Wiederherstellung der Originalhistorie](macos-issue-publication-2026-11-26/CODEX-RESTORE.md)
- [Tatsächliche Umgebung und künftige macOS-/VM-Abnahme](../Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md)
- [Dell/NFC/Telefon/Auth: recherchierte Fähigkeiten und Prüfplan](windows-dell-nfc-research-2026-11-26.md)
- [Windows: ergänzende Feature-Möglichkeiten](windows-feature-opportunities-2026-11-26.md)

## Prüfstatus und wesentliche Grenzen

Der vollständige Hostlauf bestand **35/35 Gruppen**. Zusätzlich ausgewiesen
sind **90 OR6→Helper→UI-Prüfungen** und **107 Sync-UI-Prüfungen**. Die Umfänge
überlappen; sie werden nicht zu einer Gesamtzahl addiert. Rohbelege und genaue
Quellstände stehen im Prüfverzeichnis. Die ursprünglichen Testtreiberfehler und
ihre Korrekturen dürfen nicht aus dem Nachweis entfernt werden.

Die Arbeitsumgebung „Magnolie-Organizer einrichten“ war Linux x86_64. Hier
liefen keine neue native Swift-Kompilierung, Apple-SDK-Abnahme oder macOS-VM.
Vorbereitete Swift-/Provider-/TCC-/Bundle-Prüfungen sind keine bestandenen
nativen Tests. Historische grüne CI-Läufe auf älteren Quellen beweisen die
aktuellen Patches ebenfalls nicht.

Die 31 berücksichtigten Issues sind:
`121, 451, 452, 453, 454, 458, 464, 465, 468, 472, 511, 680, 682, 683, 721,
749, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 781, 783, 784, 785, 786`.
Das Inventar dokumentiert daneben Ausschlüsse und historische Fälle. Nicht
jedes berücksichtigte Issue benötigt einen neuen Produktpatch: bestätigte
Bestandsfixes, Regressionen und offene native Abnahmen bleiben unterscheidbar.

Die wichtigen offenen Teile umfassen die echte native Abnahme, ausgewiesene
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
Die Übernahme nach main, Issue-Schließungen und Paket-/Releaseveröffentlichungen
sind durch diesen Fortsetzungs-Prompt nicht beauftragt.

ZUERST BESTAND PRÜFEN
1. Repository https://github.com/maik3531/Magnolie-Organizer und den Zweig
   work/macos-issue-fixes-20261126 lesen. In vorhandenen Checkouts zuerst
   git status, AGENTS.md und ARBEITSSTAND.md prüfen; Benutzeränderungen erhalten.
2. Diese Dateien lesen:
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
Native Abnahme und die dokumentierten technischen Reste bleiben offen.

QUELLANKER
- Vollständiger ursprünglicher Übergabecommit:
  0dfeb1b30a208480eb6901e3d3148a5efeaae5ff
- Zuletzt vollständig geprüfter Codecommit:
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
Im ursprünglichen Linux-Nachweis bestanden 35/35 Hostgruppen; gesondert ausgewiesen sind 90 OR6→Helper→UI-
Prüfungen und 107 Sync-UI-Prüfungen. Diese Umfänge überlappen und werden nicht
addiert. Logs und Quellbindungen verwenden. Spätere echte native GitHub-Läufe
stehen in Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md;
dort zuerst den erreichten Schritt, genauen Quellcommit und Ausgang prüfen.
Swift-/Zeitzonenerfolg, Runtimebau, XCTest, Bundle-/App-Start sowie echte
TCC-/Provider-/Gerätetests bleiben getrennte Nachweise. Vorbereitete Tests und
historische CI-Erfolge auf älteren Quellen nicht als aktuelle native Erfolge
ausgeben. Die Folgeissues #787/#788/#789 gezielt mitlesen.

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
