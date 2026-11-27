# Veröffentlichungsbelege zur Mac-Issue-Übergabe

**Abgeschlossen am 26. November 2026:** Alle 31 vorgesehenen Issue-Kommentare wurden angelegt und danach einzeln aus GitHub zurückgelesen. Marker, Kommentar-ID und vollständiger Text stimmten mit dem jeweiligen geprüften Entwurf überein. Dies ist eine Quell-/Patchübergabe; native Mac-Abnahme, Main-Merge und Paketveröffentlichung sind damit nicht erfolgt.

- Arbeitszweig: [work/macos-issue-fixes-20261126](https://github.com/maik3531/Magnolie-Organizer/tree/work/macos-issue-fixes-20261126).
- Exakter veröffentlichter Quellcommit A: [`8efc6834`](https://github.com/maik3531/Magnolie-Organizer/commit/8efc6834abd16f18300f3d59a1897c81758b0c34), Tree `d731a6bd56acd68e79aab83fbadb19ab94ad6547`, identisch zum ursprünglichen Übergabecommit `0dfeb1b30a208480eb6901e3d3148a5efeaae5ff`.
- Fester Dokumentations-/Artefaktstand der Kommentare: [`cf7b3f2b`](https://github.com/maik3531/Magnolie-Organizer/commit/cf7b3f2bf4e8afee662a4926f32fc989d7ff7df8), Tree `84946fbf64b1c804072ae539680c221c04690247`. Dieser wurde zusätzlich über Git gefetcht und gegen den lokalen Veröffentlichungsindex identisch verglichen.
- [Maschinenlesbare Einzelbelege](macos-issue-publication-receipts-2026-11-26.json) enthalten für jeden Kommentar URL, ID, Marker, UTF-8-Bytezahl, SHA-256 des vollständig übereinstimmenden Texts und Rücklesezeit.
- [Originale Patchfolge wiederherstellen](macos-issue-publication-2026-11-26/CODEX-RESTORE.md): 24 Patchdateien und das geprüfte Bundle erhalten die Originalfolge.
- [Zusammenfassung und Fortsetzungs-Prompt](macos-next-chat-prompt-2026-11-26.md).

Spätere Änderungen am Arbeitszweig verändern die festen Beleglinks in diesen Kommentaren nicht. Vor einer weiteren Übergabe vorhandene Marker und Inhalte prüfen, damit keine Doppelkommentare entstehen. Der finale Head kann wegen dieses Abschlussbelegs nach dem genannten Dokumentationsstand liegen; die Produktquellen wurden dadurch nicht geändert.

## Direktlinks auf alle 31 Kommentare

| Issue | Gegenstand | Geprüfter Kommentar |
| --- | --- | --- |
| #121 | Nach Gesamtabnahme: macOS- und Android-Organizer auf Funktions- und Darstellungsparität bringen | [Kommentar 7186455888](https://github.com/maik3531/Magnolie-Organizer/issues/121#issuecomment-7186455888) |
| #451 | CSS-Kompatibilität: native Auswahl-/Markerabnahme und Engine-Zielmatrix (Rest aus #446) | [Kommentar 7186470128](https://github.com/maik3531/Magnolie-Organizer/issues/451#issuecomment-7186470128) |
| #452 | Tablet/TZDB: ThreeTenBP liefert falsche Gaza-/Hebron-Zeiten und erfolgreiche falsche ICS-Roundtrips | [Kommentar 7186470845](https://github.com/maik3531/Magnolie-Organizer/issues/452#issuecomment-7186470845) |
| #453 | ICS-Ports: eigene VTIMEZONE-TZIDs kollidieren mit privaten UTC-Stringmarkern | [Kommentar 7186471583](https://github.com/maik3531/Magnolie-Organizer/issues/453#issuecomment-7186471583) |
| #454 | Mac/Tablet: persistierte Sync-Epoche und Löschquarantäne bei Wiederherstellung ergänzen | [Kommentar 7186472352](https://github.com/maik3531/Magnolie-Organizer/issues/454#issuecomment-7186472352) |
| #458 | Zeichenblatt: geringe Rasterabweichung nach Undo/Redo bei identischem Vektormodell untersuchen | [Kommentar 7186473069](https://github.com/maik3531/Magnolie-Organizer/issues/458#issuecomment-7186473069) |
| #464 | Serientermine: verschiedene Ausnahmen am selben Zielzeitpunkt werden zusammengefaltet | [Kommentar 7186473921](https://github.com/maik3531/Magnolie-Organizer/issues/464#issuecomment-7186473921) |
| #465 | ICS-Altbestand: verbleibende Port-Abnahme und exakte Reparatur bereits gespeicherter Ausnahme-Duplikate | [Kommentar 7186474755](https://github.com/maik3531/Magnolie-Organizer/issues/465#issuecomment-7186474755) |
| #468 | Zeichenblatt: Pointerup-Korrektur in Portprojektionen übernehmen und native Eingabe abnehmen | [Kommentar 7186475580](https://github.com/maik3531/Magnolie-Organizer/issues/468#issuecomment-7186475580) |
| #472 | Tablet-Abnahme: leere UI-Epochenplatzhalter vom nativen Speichervertrag unterscheiden | [Kommentar 7186476384](https://github.com/maik3531/Magnolie-Organizer/issues/472#issuecomment-7186476384) |
| #511 | Fortsetzung #455: opaque Unicode-JSON-Schlüssel verlustfrei bis zum nativen Mac-Buch erhalten | [Kommentar 7186477162](https://github.com/maik3531/Magnolie-Organizer/issues/511#issuecomment-7186477162) |
| #680 | Zeitzonen: nativer Linux-Journal-Restore und verbleibende macOS-/Tablet-/Android-Matrix – Rest #661 | [Kommentar 7186477847](https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-7186477847) |
| #682 | Kalenderanhänge: echte HTTPS-/Clipboard-Handler und native Portmatrix – Rest #651 | [Kommentar 7186478629](https://github.com/maik3531/Magnolie-Organizer/issues/682#issuecomment-7186478629) |
| #683 | CalDAV: echter Testserver, Legacy-Baselines und Konfliktmatrix nach installierter Farbformularabnahme – Rest #652 | [Kommentar 7186479357](https://github.com/maik3531/Magnolie-Organizer/issues/683#issuecomment-7186479357) |
| #721 | Mac/iPhone: AirPlay-Bildschirmspiegelung mit UxPlay integrieren und nativ prüfen | [Kommentar 7186480066](https://github.com/maik3531/Magnolie-Organizer/issues/721#issuecomment-7186480066) |
| #749 | Medienabgleich: Originalformate über JPEG/PNG und MP4/MOV hinaus, einschließlich iPhone | [Kommentar 7186480800](https://github.com/maik3531/Magnolie-Organizer/issues/749#issuecomment-7186480800) |
| #770 | Mac/iPhone: ausgewählte Systemkalender-Termine nativ in Magnolie übernehmen | [Kommentar 7186481565](https://github.com/maik3531/Magnolie-Organizer/issues/770#issuecomment-7186481565) |
| #771 | Mac EventKit: Vierjahresgrenze des allgemeinen Quellenlesers darf keinen vollständigen Zeitraum vortäuschen | [Kommentar 7186482270](https://github.com/maik3531/Magnolie-Organizer/issues/771#issuecomment-7186482270) |
| #772 | Mac: ausgewählte Apple-Notizen direkt als lokale Textkopien übernehmen | [Kommentar 7186483138](https://github.com/maik3531/Magnolie-Organizer/issues/772#issuecomment-7186483138) |
| #773 | Mac-Kalenderimport: offener Einstellungsdialog blockiert die native Vorschau | [Kommentar 7186483902](https://github.com/maik3531/Magnolie-Organizer/issues/773#issuecomment-7186483902) |
| #774 | Mac-Notes-Import: ungespeicherte Kontoeingaben beim automatischen Schließen erhalten | [Kommentar 7186484707](https://github.com/maik3531/Magnolie-Organizer/issues/774#issuecomment-7186484707) |
| #775 | Mac/iPhone: ausgewählte Systemkontakte nativ als lokale Kopien übernehmen | [Kommentar 7186485555](https://github.com/maik3531/Magnolie-Organizer/issues/775#issuecomment-7186485555) |
| #776 | Kontaktkopien: reine Kontaktgeburtstage aus dem Mac-Patch beim JSON-Austausch plattformübergreifend prüfen | [Kommentar 7186486387](https://github.com/maik3531/Magnolie-Organizer/issues/776#issuecomment-7186486387) |
| #777 | Mac/iPhone: ausgewählte Apple-Erinnerungen als lokale Aufgaben übernehmen | [Kommentar 7186487191](https://github.com/maik3531/Magnolie-Organizer/issues/777#issuecomment-7186487191) |
| #778 | Mac: Speicherzustand nach Darstellungsfehler bei Kalender-, Notes- und Kontaktkopien prüfen | [Kommentar 7186487948](https://github.com/maik3531/Magnolie-Organizer/issues/778#issuecomment-7186487948) |
| #779 | Aufgabenkopien: Herkunft beim JSON-Austausch mit Linux und Windows prüfen | [Kommentar 7186488763](https://github.com/maik3531/Magnolie-Organizer/issues/779#issuecomment-7186488763) |
| #781 | Mac-Dateinotizen: Import nach Darstellungsfehler im Snapshot-Callback beenden und Speicherzustand erhalten | [Kommentar 7186489586](https://github.com/maik3531/Magnolie-Organizer/issues/781#issuecomment-7186489586) |
| #783 | macOS-Kandidaten bauen trotz aktuellem Checkout weiter die veröffentlichte Desktopbasis v2.0.30 | [Kommentar 7186490335](https://github.com/maik3531/Magnolie-Organizer/issues/783#issuecomment-7186490335) |
| #784 | Mac-Geräteseite: Notes-Voraussetzung und endlose Statusanzeige durch passende Apple-/KDE-Dateiwege ersetzen | [Kommentar 7186491235](https://github.com/maik3531/Magnolie-Organizer/issues/784#issuecomment-7186491235) |
| #785 | Mac-Importparität: aktuelle OR6-/Dateiparser und vollständige native Importwege anbinden | [Kommentar 7186492012](https://github.com/maik3531/Magnolie-Organizer/issues/785#issuecomment-7186492012) |
| #786 | macOS-Systemkonten: echten Apple-Kalender-, Kontakt- und Erinnerungsabgleich anbinden | [Kommentar 7186492778](https://github.com/maik3531/Magnolie-Organizer/issues/786#issuecomment-7186492778) |

## Prüfstatus

Der tatsächliche abschließende Codeprüfstand ist `7c9cf20394aef73d261a77f746ebca7340826d30`: 35/35 Hostgruppen bestanden. Gesonderte Parser-/OR6-/UI-Belege und ihre genauen Quellstände stehen im [Prüfverzeichnis](macos-verification-2026-11-26/README.md). Die 90 OR6- und 107 Sync-UI-Prüfungen überlappen andere Umfänge und werden nicht addiert. Neue Swift-/Apple-Provider-/TCC-/Bundleprüfungen wurden hier nicht ausgeführt.

Der generische Whitespace-Check meldet in eingecheckten `.patch`-Artefakten unter anderem leere Kontextzeilen und die standardmäßige `-- `-Signaturtrennung sowie Leerzeichen in unveränderter `git bundle verify`-Ausgabe. Diese Belegbytes wurden bewusst erhalten und über SHA-256 geprüft. Die übrigen neuen Markdown-/JSON-Unterlagen bestanden den auf sie begrenzten `git diff --check`; Produktcode und Rohbelege wurden dafür nicht verändert.
