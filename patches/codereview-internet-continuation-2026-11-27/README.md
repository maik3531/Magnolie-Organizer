# Fortsetzung: Internetverbindung, Notes und vollständige Patchübergabe

**Stand: 27. November 2026. Geprüfter aktueller Hauptzweig: `f8ad956ec4c9a71cd4d857c3218177c481407c85`.**

Diese Übergabe setzt die beiden vorherigen Codereview-Chats fort. Die im letzten Chat vorbereitete Neuner-Serie wurde vollständig veröffentlicht und um einen neu reproduzierten Notes-Fernabgleichfehler ergänzt. Die Patches sind für die spätere Einpflege bestimmt. Die Produktdateien von `main` und installierte Programme wurden durch diese Übergabe nicht verändert.

## Wiederhergestellte vorherige Arbeit

Die [vollständige ursprüngliche Lieferung](https://github.com/maik3531/Magnolie-Organizer/blob/6d5e189ee2d70ad3f085b13d96e596fd7ec83241/patches/open-issues-audit-2026-11-27/README.md) enthält die Sichtung von 106 ursprünglich offenen Issues, die nachvollziehbare Zusammenführung bestehender Aufgaben, neun Teilpatches und alle zugehörigen Quell- und Prüfbelege. Alle **871 Dateien, 12.755.282 Bytes**, wurden nach der Veröffentlichung über einen neuen GitHub-Abruf vollständig heruntergeladen und gegen ihre Byteanzahl und SHA-256 geprüft. [Rücklesebeleg](audit-remote-readback-proof.json).

Die drei davor veröffentlichten Reviewrunden bleiben über [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113) erreichbar. Bereits übernommene Korrekturen werden beim aktuellen Patchumfang berücksichtigt.

## Antwort zum Magnolienbaum und zu Magnolie Notes

| Frage | Quellengeprüfter Stand | Noch offen |
| --- | --- | --- |
| Funktioniert der Magnolienbaum über Internet? | Ausdrücklich eingerichtete entfernte TCP-Endpunkte und authentisierte FS1-Verbindungen sind implementiert. Die früheren kontrollierten Protokollnachweise bleiben an ihre Quellen gebunden. | Die gegenseitige Erreichbarkeit muss vorhanden sein. Beliebige Router-, Mobilfunk- und Energiesparbedingungen wurden nicht real abgenommen. |
| Ist die Einrichtung kinderleicht? | Die Oberfläche verlangt Host und Port; ein geeigneter Zugang wird vorausgesetzt. Eine angenommene Kopplung muss nicht bei jedem normalen Wiederverbinden erneut bestätigt werden. | Ein allgemein nutzbarer Vermittler oder ein Assistent, der den Internetzugang selbst herstellt und beide Richtungen prüft, ist in diesem Ablauf nicht vorhanden. Das Bedienurteil beruht auf dem Quellablauf, nicht auf einem Nutzertest. |
| Können Notizen über Internet abgeglichen werden? | Bereits geteilte Notizen nutzen den vorhandenen Versandweg. Beim Speichern wird ihre Fortschreibung eingereiht und die Postfachverarbeitung unmittelbar gestartet. | Eine erreichbare Desktop-Gegenstelle allein garantiert keinen erreichbaren Rückweg zum Telefon. |
| Wartet jede Änderung sechs Stunden? | Nein. Die Sechsstundenregel gehört zum eingeschalteten periodischen Gesamtabgleich über WLAN. Einzelne Änderungen haben den beschriebenen unmittelbaren Versandweg. | Der vollständige automatische Abgleich über alle freigegebenen Transportarten bleibt [#128](https://github.com/maik3531/Magnolie-Organizer/issues/128). |
| Kann Nextcloud diese Lücke bereits automatisch schließen? | Der Desktop hat einen älteren WebDAV-Briefkasten für `baum-1`. | Der reguläre FS1-Weg verwendet ihn nicht als allgemeinen Rückfallweg; Notes hat dafür keinen entsprechenden WebDAV-Client. Das ist von CalDAV und der eigenständigen Nextcloud-Notes-App zu trennen. |

Der [vollständige Internetbericht mit Quellverweisen und Protokolllogs](https://github.com/maik3531/Magnolie-Organizer/blob/6d5e189ee2d70ad3f085b13d96e596fd7ec83241/patches/open-issues-audit-2026-11-27/internet-notes/README.md) bleibt maßgeblich. Die [erneute Quellenbindung](internet-review-recheck.json) bestätigt auf `f8ad956e` 15 unveränderte vollständige Dateien sowie acht unveränderte Linuxdefinitionen. Die einzige geänderte große Desktop-Webdatei enthält die späteren Importkorrekturen. Das ist kein neu ausgeführter Geräte- oder Internetlauf.

## Neuer bestätigter Notes-Fehler: #148

Bei der Prüfung der Fernabgleich-Verfügbarkeit begann Notes in jeder Runde wieder beim ersten gespeicherten Partner. Sechs frühe Zeitüberschreitungen konnten deshalb verhindern, dass ein späterer erreichbarer Rechner überhaupt geprüft wurde. Auch Partner nach der bisherigen Grenze von 32 blieben bei jeder Aktualisierung außen vor. Die Oberfläche konnte den Einzelabgleich einer bereits geteilten Notiz dadurch fälschlich als nicht verfügbar anzeigen. Der normale Postfachversand ist ein gesonderter Ablauf und wird durch diesen Befund nicht pauschal als ausgefallen bezeichnet.

Der [enge Teilpatch](notes-148/notes-148-fair-remote-probes.patch) setzt die nächste Prüfrunde nach dem zuletzt tatsächlich versuchten Partner fort. Zeitbudget, Höchstzahl pro Runde, Authentisierung, Vertrauensprüfung und Ablauf der Nachweise bleiben erhalten. Der Patch gehört zum vorhandenen [#148](https://github.com/maik3531/Magnolie-Organizer/issues/148); es wurde kein Doppelissue angelegt.

**Tatsächlich geprüft:** Der Kotlin-Ablauf mit unverändert übernommener Produktmethode und echtem Nachweis-Gültigkeitstest ergab vorher **10 bestanden / 2 fehlgeschlagen**, danach **12 bestanden / 0 fehlgeschlagen**. Zusätzlich bestehen **8 JUnit-Fälle** direkt gegen den neuen Prüfreihenfolge-Kern. Die beiden roten Fälle sind die wiederholten Auslassungen; die übrigen Fälle sichern unter anderem Widerruf, geänderte Identität, Schlüsselwechsel und abgelaufene Nachweise ab. [Beschreibung, Runner und vollständige Grenzen](notes-148/README.md).

Die faire Fortsetzung beseitigt die dauerhafte Auslassung. Sie garantiert bei vielen oder langsamen Partnern keine ununterbrochene Anzeige sämtlicher Gegenstellen; die kurzlebigen Nachweise werden weiterhin pro Runde neu bestimmt.

## Einpflege auf dem aktuellen geprüften Hauptzweig

Für einen sauberen Stand `f8ad956ec4c9a71cd4d857c3218177c481407c85` ist der [vollständige Gesamtpatch](complete-review-after-f8ad956e.patch) vorbereitet. Er enthält die früheren neun Teile und den neuen #148-Teil. Alternativ können der [aktuelle Gesamtpatch der bisherigen Neuner-Serie](current-main/all-after-f8ad956e.patch) und danach der [#148-Teilpatch](notes-148/notes-148-fair-remote-probes.patch) angewendet werden. Diese Wege sind Alternativen; dieselben Änderungen nicht mehrfach übereinander anwenden.

| Eigenschaft | Wert |
| --- | --- |
| Basiscommit | `f8ad956ec4c9a71cd4d857c3218177c481407c85` |
| Gesamtpatchgröße | 165.983 Bytes |
| Gesamtpatch SHA-256 | `52985a9c4d2e5a1e6b328cb1116503db7c3984f8671ce00f07d24a04483a5e68` |
| Erwarteter Ergebnisbaum | `3b5b94fd3256b01a3a775f39bfdae4d661f9d6b8` |

Gesamtpatch und schrittweise Anwendung ergeben denselben Baum; beide lassen sich exakt auf den Ausgangsbaum zurückführen. Die Notes-Produkt- und Testdateien sind bytegleich mit dem geprüften Notes-Kandidaten. Die einzige gemeinsame Datei der bisherigen Serie und des Notes-Nachtrags ist die Dokumentation `ARBEITSSTAND.md`. [Zusammenführungsbeleg](combined-replay.json).

Die frühere Neuner-Serie wurde zusätzlich gegen alle 4.700 Pfade ihrer vorherigen Integration verglichen: 4.696 sind unverändert; vier enthalten exakt die bewahrte zwischenzeitliche #846-Korrektur. Die betroffenen MCP-, Kalenderfarben- und Serienaliasprüfungen bestehen auf beiden Desktop-Webquellen. [Nachweis und eigenständige Anleitung](current-main/README.md).

Bei einem später fortgeschriebenen Hauptzweig müssen dessen zusätzliche Änderungen berücksichtigt werden. Die Produktdateien des reinen Artefaktzweigs sind keine Einpflegebasis.

## Offene Aufgaben und eindeutige Zustände

- **#844 und #845:** Die übernommenen Grundkorrekturen bleiben erhalten. Die unabhängig reproduzierten Farb-, Jahrestags-, Serienausnahme- und DAV-Reste besitzen Folgepatches und bleiben bis zur tatsächlichen Einpflege offen.
- **#148:** Der neue Verfügbarkeitsfehler besitzt einen geprüften Teilpatch. Weitere Bedienkriterien und die echte Android-Prüfung bleiben offen.
- **#128:** Transportübergreifende automatische Synchronisierung benötigt weiter die tatsächlich ausgehandelte Produktkette. Gemeinsame Einstellungen einmal im Organizer ändern; technische Bestätigungen erzeugen keine weiteren menschlichen Pflichtdialoge. Bestehende Freigaben und Widerrufe bleiben bindend.
- **#113/#121:** Installierte Pakete, reale Geräte, echter Internet-Rückweg und die weiteren ausgewiesenen Abnahmen werden durch diese Hostnachweise nicht ersetzt.

Eine geführte Internet-Einrichtung ist im früheren Bericht als mögliche Bedienverbesserung beschrieben. Sie wurde nicht als zusätzlicher Funktionsauftrag in diese Patchserie aufgenommen. Die aktuelle Arbeit liefert den überprüfbaren Reviewstand, die vollständigen Patches und den konkreten Wiedereinstieg für Codex.
