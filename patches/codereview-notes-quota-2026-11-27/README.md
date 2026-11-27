# Fortsetzung: Notes-Postfach darf erlaubte Fernwege nicht blockieren

## Geprüfter neuer Teilpatch

Der Nachtrag zu [#691](https://github.com/maik3531/Magnolie-Organizer/issues/691) behebt einen konkreten Fehler im vorbereiteten Android-LAN-Berechtigungsweg: Mindestens 64 auf LAN-Freigabe wartende Einträge konnten in jedem Postfachlauf das ganze Versuchskontingent verbrauchen. Bereits erlaubte öffentliche Fernziel- oder Bluetooth-Sendungen dahinter wurden dadurch nie erreicht.

Die endgültige Korrektur gibt ausschließlich im LAN-Wartezweig den belegten Versuch zurück. Die bisherige Begrenzung für fehlgeschlagene oder leere Vorbereitung und fehlende Partner bleibt erhalten. Neue Rechte, Einstellungen oder Transportarten werden dadurch nicht eingeschaltet.

**Basis:** 9de81cc10d72ca7b176b5c501ff20689cdd53c31.

**Endgültiger getesteter lokaler Produktcommit:** e9f4a41c87c2ef708e0c357fa76e64b339c5e313.

- [Einzelpatch #691](notes-691/notes-691-outbox-route-quota.patch)
- [Reproduktion, Abgrenzung und Wiederholung](notes-691/README.md)
- [20 erfolgreiche Fälle](notes-691/after/results.log)
- [Quellenbindung und Kombination mit #148](notes-691/commit-binding.json)
- [Unabhängige Gegenprüfung](integration/independent-review.json)

## Tatsächliche Prüfergebnisse

| Quellstand | Bestanden | Fehlgeschlagen |
|---|---:|---:|
| Unveränderte Basis | 15 | 5 |
| Verworfener erster Kandidat | 17 | 3 |
| Endgültiger Patch | 20 | 0 |

Das identische Harness kompiliert die tatsächlichen Postfachmethoden, das Sendungsmodell, die LAN-Wartebedingung und den reinen Java-LAN-Prüfkern. Kontrollierte Speicher-, Plattform-, Parser- und Zustellabhängigkeiten begrenzen die Aussage. Enthalten sind das reguläre Kontingent 64 mit 70 wartenden LAN-Einträgen, erlaubter Fernversand/Bluetooth, Widerruf, Wartebestand, Wiederherstellung, Dienstgeneration, Zeitwächter und Legacy-Reihenfolge.

Der erste Kandidat wurde vor Veröffentlichung verworfen. Die drei zusätzlichen Budgetfälle reproduzieren genau dessen unerwünschte Ausweitung der Vorbereitungsarbeit. Der Ordner superseded-e6c4293 enthält nur den ausdrücklich verworfenen Prüfnachweis; zu übernehmen ist ausschließlich der oben verlinkte endgültige Patch.

Der erfolgreiche Lauf erfolgte vor dem abschließenden Commit. Deshalb nennt after/manifest.json bei head_at_execution noch den damaligen HEAD e6c4293. Alle vier dort dokumentierten Produktquell-Prüfsummen und der exakte Methodenhash sind unabhängig gegen den endgültigen Commit e9f4a41 geprüft und stimmen überein. Das historische Manifest wurde nicht umgeschrieben.

## Einpflege mit der bisherigen Serie

Der bisherige vollständige Zehner-Gesamtpatch ist auch auf der jetzt geprüften Basis 9de81cc1 anwendbar. Der neue Einzelpatch ist danach konfliktfrei anwendbar. Zusätzlich liegt ein gemeinsamer Patch für einen noch unveränderten Stand 9de81cc1 vor:

- [Vollständiger Gesamtpatch einschließlich #691](integration/complete-review-after-9de81cc.patch)
- [Genaue Basis, Ergebnisbaum und SHA-256-Bindung](integration/compatibility.json)

Entweder den Gesamtpatch auf seine unveränderte Basis anwenden oder auf eine bereits übernommene bisherige Serie nur den Einzelpatch anwenden. Beide Varianten wurden vorwärts und rückwärts geprüft; rückwärts entsteht exakt der jeweilige Basisbaum. Nicht beide Varianten doppelt anwenden.

Die Änderungen, die seit der vorigen Übergabe auf main hinzugekommen sind, bleiben erhalten. Der Ergebnisbaum ist auch aus dem vorigen integrierten Baum plus der tatsächlichen neuen Upstream-Differenz plus diesem Notes-Patch identisch herstellbar. Der neue Linux-Videoordner-Teststand ist bytegleich erhalten. Der kombinierte Baum enthält genau die getesteten Postfachmethoden.

Unveränderte Laufzeitprüfungen der früheren zehn Patches wurden nicht erneut gezählt. Deren quellengebundene Belege bleiben in den früheren Übergaben erhalten.

## Geltungsbereich und verbleibende Arbeit

Der konkrete fehlende-LAN-Freigabe-Fall betrifft den ausdrücklich vorbereiteten Target-37-Kandidaten. Der reguläre Notes-Quellbau bleibt bei Target 35. Diese Prüfung belegt keine Regression einer installierten regulären APK.

Die vollständige Feldgleichheit ist für bereits vorbereitete FS1-Testeinträge geprüft. Die vorhandene Legacy-Vorbereitung kann weiterhin vor der LAN-Prüfung Umschlag, Quittungsmetadaten und Partnerzähler reservieren. Der LAN-Wartezweig löscht keinen Eintrag und erzeugt weder Fehlversuch noch Backoff.

Eine echte Android-, Routing-, signierte FS1-, Mobilfunk-/Router- oder Paketprüfung wurde hier nicht durchgeführt. Die native Kandidatenmatrix und die übrige Migration bleiben in #691 offen. Der durchgehend ausgehandelte automatische Abgleich über weitere tatsächlich freigegebene Transportarten bleibt in [#128](https://github.com/maik3531/Magnolie-Organizer/issues/128) offen. Der neue Patch verbessert den vorhandenen zulässigen Versand, ersetzt aber diesen Gesamtauftrag nicht.

Diese Übergabe sichert geprüfte Patches und Belege zur späteren Übernahme. Sie ändert weder den Produkt-Hauptzweig noch installierte Programme oder veröffentlichte Pakete.
