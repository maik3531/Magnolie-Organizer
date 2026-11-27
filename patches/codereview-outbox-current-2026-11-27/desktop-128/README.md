# #128 – Desktop-Postfach: Fortschritt hinter nicht zugelassenen Actor-Nachrichten

Dieser getrennte Review-Patch verbessert den gewöhnlichen Telefon-Sender in Linux und Windows. Ein volles Fenster aus reservierten Actor-Nachrichten ohne gegenwärtigen Versandweg verdeckt späteren gewöhnlichen Verkehr nicht mehr allein aufgrund der 32er-Vorauswahl. Die Actor-Umschläge bleiben geschützt und erhalten.

| Quellbindung | Wert |
|---|---|
| Basis | `9de81cc10d72ca7b176b5c501ff20689cdd53c31` |
| Basisbaum | `f442d855aa6f00ff26eeffc3fe30380a507c470f` |
| Ergebnisbaum | `c98bb01ca6081dc8b80c1739aee3d1ae12f154da` |
| Patch | `desktop-128-actor-queue-fairness.patch` |
| Patch SHA-256 | `a13ffa0a5d96e92cf17292ae2e63a0bf403493b1b03c0ccf827b535fbb0ca28e` |
| Zuordnung | [vorhandenes Issue #128](https://github.com/maik3531/Magnolie-Organizer/issues/128) |

## Reproduzierter Fehler und geprüfte Wirkung

Die Probe legt 65 gültig markierte Actor-Batch-Umschläge mit einem noch gültigen privaten Run ab und reiht danach einen gewöhnlichen Gerätestatusauftrag ein. Die Testverbindung besitzt für die gespeicherten Actors keine aktuelle Admission. Deren Versand muss deshalb warten. Drei aufeinanderfolgende Senderdurchläufe zeigen:

| Tatsächlich ausgeführter Quellhost | Basis | Patch |
|---|---|---|
| Linux, neu geöffnetes Store-/Service-Testobjekt | 0 / 0 / 0 Sendungen; Fortschrittsassertion rot | 0 / 0 / 1 Sendungen; Fortschrittsassertion grün |
| C#, gleicher bestehender `PumpOutboxNowAsync`-Einstieg | 0 / 0 / 0 geschriebene Bytes; Fortschrittsassertion rot | 0 / 0 / 430 geschriebene Bytes; Fortschrittsassertion grün |
| Actor-Versuche | 0 | 0 |
| Zurückgehaltene Actor-Umschläge | alle erhalten | alle erhalten |

Die identische C#-Probe `WindowsProgressProbe.cs` wird gegen Basis und Patch gebaut. Beide benutzen den bestehenden produktiven Einstieg; die negative Basisprüfung beruht nicht auf einer dort fehlenden neuen Test-API. Der unveränderte zusätzliche `Due`-Lesezugriff der Probe sieht weiterhin den bisherigen Kopf. Er ist absichtlich nicht der Zustandsgeber der neuen Pumpe.

Bei Linux ruft die Basisprobe den ursprünglichen `pending`-/`_send_message`-Ablauf auf. Der Patchlauf ruft den tatsächlichen neuen `_pump_pending`-Helfer des Receiver-Timeoutpfads auf. Diese beiden Einstiege sind in den JSON-Belegen ausdrücklich bezeichnet. Der Store wird wirklich wieder geöffnet; ein vollständiger GUI-/Prozessneustart oder eine physische Telefonverbindung wird dadurch nicht behauptet. Linux verwendet einen Testkanal, C# einen Speicherstream mit dem produktiven verschlüsselten Writer.

Eine solche geschützte Warteposition ist laut Quellprüfung möglich: Actor-Wire-Umschläge werden unabhängig vom flüchtigen Owner gespeichert; neue Service-/Connection-Objekte besitzen zunächst keine entsprechende Admission. Linux prüft den exakten ursprünglichen Kanal vor dem Actor-Versand. Windows beendet seinen getrennten Actor-Pump bei fehlender Admission, bevor dieser gegebenenfalls die Registry bereinigt. Ein späteres explizites Cancel/Reap, Nachrichten-/Run-Ablauf, Unpair oder Restore kann die Warteposition auflösen. Die Probe belegt drei unveränderte Wartungsrunden, keine zeitlich unbegrenzte Existenz abgelaufener Nachrichten.

## Begrenzter Eingriff

Die neue gewöhnliche Pump-Auswahl liest höchstens 32 Rohzeilen pro Aufruf. Der Schlüssel aus `created_ms` und SQLite-`rowid` bleibt außerhalb der Wire-Nachricht. Er gehört zur aktuellen Verbindung und wird weder in Einstellungen gespeichert noch von allgemeinen Queue-/ACK-Lesezugriffen verschoben. Bestehende priorisierte Steuerarten werden auch bei gesetztem Daten-Cursor zuerst berücksichtigt. Gleiche Zeitstempel sind durch `rowid` eindeutig geordnet.

Unter Linux wird nur ohne passende Peer-/Kanal-Admission weitergeblättert. Auch ein vorhandener, vorübergehend wartender Actor-Owner behält die bisherige Kopf-Auswahl. Neue Admissions setzen die Auswahl vor dem Lesen zurück. Aus einer bereits vorgerückten gewöhnlichen Seite wird grundsätzlich kein Actor gesendet; damit kann auch ein Admissionswechsel zwischen Seitenlesen und Versand keine spätere Actor-Nachricht vor den früheren Nachrichten senden. Es werden weder native Writer-Callbacks vorab ausprobiert noch zwei Seiten in einem Pump-Aufruf gescannt.

Unter Windows sendet der gewöhnliche Pump reservierte Actors weiterhin überhaupt nicht. Der getrennte autorisierte Actor-Pump verwendet seine bestehende `Due`-Auswahl. Der neue begrenzte Read-Zweig teilt die vorhandene Entschlüsselungs-, Run- und Bereinigungsprüfung. Er bewahrt den Rohseiten-Fortschritt auch dann, wenn wartende Produzenten vor `result.Add` zurückgestellt oder ungültige Zeilen gelöscht werden. Allgemeine `Due`-Aufrufer behalten ihre bisherige Semantik einschließlich der bestehenden Bereinigung; es gibt keinen globalen Store-Cursor.

Der Patch ändert keine Grant-, Identitäts-, Revision-, Session-, Nachrichtenlebenszeit-, ACK-, Restore- oder Transportpolicy. `wifi_only` bleibt vor der Auswahl wirksam. Gewöhnliche Time-/Shared-Wartezustände werden durch diesen Actor-Teilfix nicht überholt. Fairness für vorhandene, momentan wartende Actor-Owners und weitere Queue-Arten bleibt außerhalb dieses Teilpatches.

## Prüfungen

- **12 neue Python-Fälle:** 65/96 zurückgehaltene Actor-Umschläge, WLAN/Bluetooth, gleiche Zeitstempel, spätere Steuerpakete, unveränderte allgemeine Pending-Lesezugriffe, neue Sitzung/Transport, gelöschte Seiten und Rücklauf, `wifi_only`, gewöhnliche Time-/Shared-Wartezustände, tatsächlich erlaubter Actor-Versand sowie Admissionswechsel vor/nach dem Seitenlesen und vorhandener wartender Owner.
- **10 bestehende gezielte Python-Fälle:** verschlüsselte Actor-Queue und Wiederöffnen, markierte/unmarkierte Trennung, fehlende Actor-Route, keine generische Actor-Empfangsübernahme, Queue-Retry/ACK, WLAN-Wechsel, frische Time-Policy und manuelles Bluetooth, Shared-Echo und alter Snapshot.
- **Eine neue .NET-Gruppe mit 11 Szenarien:** entsprechende Queue-/Control-/FIFO-/Transportprüfungen, 32 synthetisch wartende Produzenten, gültige private Runs, entfernte ungültige Zeilen und Cursor-Rücklauf. Die Produzentenfixture setzt gezielt synthetische Store-Metadaten ein; ihr Context-Payload ist kein geschützter nativer Owner. Sie prüft den echten bestehenden Auswahlzweig, keinen vollständigen Produzenten-Lebenszyklus.
- **Fünf bestehende .NET-Gruppen:** Actor-Outbox, native Actor-Quell-/Book-/Frischeguards, Telefonprotokoll/Queue, Shared-Transport und dauerhafte Time-Receipts. Der größere native Actor-Quellhost ist gezielt wegen der geteilten `Due`-Prüfung enthalten; es wurde keine Gesamtsuite ausgeführt.
- Alle C#-Bauten: **0 Warnungen, 0 Fehler**. Laufzeit: .NET SDK **8.0.408**, .NET **8.0.15** auf Linux; Python **3.12.14**.

Der erste Telefonprotokoll-Gruppenlauf scheiterte ausschließlich am fehlenden Host-Zeitzonenpfad `US/Eastern`. Mit dem bereits vorhandenen vollständigen Python-`tzdata`-Bestand als `TZDIR` bestand dieselbe Gruppe. Der ursprüngliche Fehler und der erfolgreiche Wiederholungslauf sind beide enthalten. Die neue Fixture bereinigt nur den eigenen SQLite-Pool.

### Im Review verworfener Zwischenstand

Der erste Linux-Cursor-Kandidat setzte erst nach einem erfolgreichen Actor-Send zurück. Drei zusätzliche Negativfälle bestätigten, dass damit bei inzwischen verfügbarer Admission ein späteres Paket vor den früheren Paketen gewählt werden konnte. `linux-admission-candidate-negative.log` enthält die drei tatsächlichen Fehlschläge. Der finale Lauf enthält alle zwölf erfolgreichen Fälle. `rejected-linux-cursor-candidate.patch` ist ausschließlich der verworfene Diagnosezustand und darf nicht übernommen werden. Der auszuliefernde Patch ist ausschließlich die oben genannte Datei `desktop-128-actor-queue-fairness.patch`.

## Wiederholung und Patchprüfung

`verify_replay.py --repo /pfad/zum/repository` prüft alle beigefügten SHA-256-Werte, wendet den Patch in einem getrennten temporären Git-Index auf die gebundene Basis an, vergleicht den vollständigen Ergebnisbaum und führt dieselbe Prüfung rückwärts durch. Dabei werden weder der Arbeitsbaum noch der Index des angegebenen Repositorys verändert. Die Basis muss als Git-Objekt vorhanden sein.

Für die Python-Fälle im isolierten Patch-Worktree:

```sh
python -m pytest -q magnolie-organizer/pruefungen/test_telefon_outbox_actor_fairness.py
python /pfad/zum/beleg/linux_progress_probe.py /pfad/zum/patch-worktree
```

Die Fortschrittsprobe wird gegen den Basis-Worktree mit derselben letzten Zeile ausgeführt und muss dort Exitcode 1 liefern. Der Patchlauf liefert Exitcode 0.

Für den vorhandenen .NET-Quellhost:

```sh
dotnet restore magnolie-organizer-windows/tests/CoreTests.csproj --locked-mode
dotnet run --project magnolie-organizer-windows/tests/CoreTests.csproj --no-restore -- 'Phone outbox actor fairness'
```

`build_progress_probe.py BASIS_WORKTREE PATCH_WORKTREE --dotnet /pfad/zu/dotnet` erzeugt eine portable temporäre MSBuild-Einstiegsdatei, baut dieselbe Fortschrittsprobe gegen beide Quellstände und verlangt Basis rot / Patch grün. Es verwendet den vorhandenen Projektaufbau und vorhandene NuGet-Restores. Die protokollierten Bauten verwendeten ausschließlich bereits vorhandene Pakete und den bestehenden SDK; es wurde kein Paket installiert oder veröffentlicht.

## Grenzen und nächster Schritt

Dies ist ein Patch zur späteren Codex-Integration in #128. Er aktiviert weder `auto_connection` noch einen neuen Internettransport. Der Magnolienbaum mit expliziten FS1-Fernendpunkten ist ein anderer Sendepfad als dieses Telefon-PersonalSync-Postfach. Der Patch verändert Notes/Android nicht. Dort ist eine ähnliche Vorauswahl quellenbelegt; regulär gestoppte Actors sind bereits aus `due` ausgeschlossen. Ein Notes-Laufzeitnachweis für andere noch fällige Actor-Frames wurde hier nicht ausgeführt.

Native Windows-, Android-Geräte-, reale Internet-/Router- und Paketabnahmen sind offen. Neuere `main`-Änderungen müssen beim Integrations-Replay erhalten bleiben. #128 bleibt als übergeordnete Aufgabe offen.
