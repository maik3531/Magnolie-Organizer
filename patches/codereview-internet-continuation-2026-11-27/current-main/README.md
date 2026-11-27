# Gezielte Übernahmeprüfung auf f8ad956e

**Ergebnis: bestanden.** Die bereits geprüfte Neuner-Serie lässt sich vollständig
auf `f8ad956ec4c9a71cd4d857c3218177c481407c85` anwenden. Die während der
früheren Prüfung parallel übernommene Korrektur zu #846 bleibt erhalten.

## Anwendung

Der hier bereitgestellte `all-after-f8ad956e.patch` ist derselbe vollständige
Änderungsumfang mit aktualisierten Git-Blobverweisen für diese Basis. Er ist
eine Alternative zu `all-after-7a490dd8.patch` oder der geordneten Neuner-Serie;
die Varianten werden nicht zusätzlich übereinander angewendet.

```sh
git switch --detach f8ad956ec4c9a71cd4d857c3218177c481407c85
git apply --check /path/to/all-after-f8ad956e.patch
git apply --index /path/to/all-after-f8ad956e.patch
git write-tree
```

Erwarteter Ergebnisbaum: `90f8ed38ad1de3134a6056fe109bdef86e77b8da`.
Die Anwendung ist in einer sauberen Arbeitskopie auszuführen. Für einen späteren
Hauptzweig sind dessen zusätzliche Änderungen erneut zu berücksichtigen.

## Nachweise

- Gesamtpatch und alle neun Teilpatches ergeben auf `f8ad956e` denselben Baum.
  Beide Wege ergeben rückwärts exakt den Ausgangsbaum
  `7c2601341c0436e99ac7d0bb3426138fab3476f4`.
- Vergleich aller **4.700 Git-Pfade einschließlich Dateimodi** mit der früher
  geprüften Integration `f3ea06e275ce6cd7547106096cfd96d27cf57e15`:
  **4.696 unverändert**, exakt vier Unterschiede. Der Vergleich verwendet
  Git-Bäume und hängt nicht vom Umfang einer Sparse-Arbeitskopie ab.
- Die vier Unterschiede sind `ARBEITSSTAND.md`, beide `anwendung.js` und
  `mcp-import-review.js`. Jedes geänderte Textsegment entspricht exakt der
  parallelen Übernahme `7a490dd8 → f8ad956e`.
- Der fehlende Kalenderfarbwert wird weiterhin schon bei der Normalisierung
  weggelassen. Der ältere zusätzliche Schutz im Aliaszweig bleibt als
  defensive Prüfung bestehen. Er ersetzt oder entfernt die neuere Korrektur
  nicht; die übrigen Farbkorrekturen der Serie bleiben erforderlich.

## Tatsächlich ausgeführte gezielte Prüfungen

Node **24.22.3**, JSDOM **26.1.0**:

| Prüfung | Ergebnis |
|---|---|
| Aktueller MCP-Importreview mit zusätzlicher Farbbehauptung aus #846 | Beide Desktop-Webquellen bestanden |
| Kalenderfarben mit Speichern und erneutem Laden | Je 12/12 Fälle auf beiden Webquellen |
| Historische Android-Serienaliase mit wirklichem Python-Codec | Beide Webquellen bestanden: Reimport, Save-ACK, erneutes Laden, vollständige Serienidentität, Mehrdeutigkeiten und gleichzeitige Buchänderung |

Der erste Alias-Aufruf erreichte die Produktprüfung nicht, weil dieser spezielle
Test entgegen den beiden anderen Programmen `MAGNOLIE_WEB` nicht verwendet und
eine generierte Zeitzonendatei im Arbeitsbaum erwartet. Die ersten Fehlerlogs
bleiben unter `initial-setup/` erhalten. Nach bytegleicher Bereitstellung genau
dieser vorhandenen generierten Datei bestand der vollständige Alias-Aufruf;
danach wurde die temporäre Datei wieder entfernt. Die bereits erfolgreichen
MCP-/Farbläufe wurden bei unveränderten Eingabehashes nicht erneut ausgeführt.

Die vollständigen Befehle, Quellhashes, Logs und Baumvergleiche stehen in
`replay-and-tests.json`; `only-preserved-upstream.diff` zeigt die vier erhaltenen
Unterschiede. `recheck.py` wiederholt den Nachweis mit angegebenen Arbeitskopien,
Patchordner, Node und vorhandenem JSDOM. Der frühere Ergebnisbaum kann durch
Anwendung der veröffentlichten Serie auf `7a490dd8` rekonstruiert werden;
identische Commit-Metadaten werden dafür nicht verlangt.

## Prüfgrenze

Dies ist eine gezielte Quellen-, Anwendbarkeits- und Hostprüfung. Ein neuer
C#-Bau, vollständiger Python-Suitenlauf, Bun-Lauf, Pakettest, physischer
Telefonlauf oder reale Internetverbindung wird daraus nicht abgeleitet.
Die unveränderten übrigen Quelldateien bleiben an die früheren ausdrücklich
ausgewiesenen Nachweise gebunden. Es wurden weder Hauptzweig noch Geräte
verändert und keine Pakete veröffentlicht.
