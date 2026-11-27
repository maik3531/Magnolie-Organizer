# Letzter Hauptzweigabgleich: 1a578534

**Die vollständige Reviewserie einschließlich des Notes-Nachtrags zu #148 bleibt
auf `1a578534d4136cbee07ff2040324a5528a5cebd5` anwendbar.** Die beiden seit
`f8ad956e` übernommenen Änderungen zu #330 und #846 bleiben vollständig erhalten.
Es war keine inhaltliche Anpassung des vorbereiteten Produktpatchs nötig.

Der [vollständige Fortsetzungsbericht mit Internetbefunden und Notes-Patch](https://github.com/maik3531/Magnolie-Organizer/blob/ba4fe00f582e52a84e0f81f17625d100801e3c85/patches/codereview-internet-continuation-2026-11-27/README.md) erklärt den Funktionsumfang und die einzelnen Issues. Dieser Nachtrag aktualisiert ausschließlich die Einpflegebasis und den inzwischen belegten #846-Abschluss.

## Aktueller Gesamtpatch

`complete-review-after-1a578534.patch` enthält die vollständige Neuner-Serie und
den Notes-Patch. Er ersetzt als Anwendungsweg den vorherigen Gesamtpatch oder
die zehn einzelnen Schritte; die Varianten werden nicht zusätzlich kombiniert.

- Basis: `1a578534d4136cbee07ff2040324a5528a5cebd5`
- Basisbaum: `da04ad84e7b6654d579a90859ac870bbec5ce3f3`
- Ergebnisbaum: `a8d1ca32b26bc1fed4861ef11bb7fca63e1d8fce`
- Größe: **165.983 Bytes**
- SHA-256: `e90566fa131fc087a993d6739bce9b623f0046a53767e44054de410d98adfae8`

In einer sauberen Arbeitskopie:

```sh
git switch --detach 1a578534d4136cbee07ff2040324a5528a5cebd5
git apply --check /path/to/complete-review-after-1a578534.patch
git apply --index /path/to/complete-review-after-1a578534.patch
git write-tree
```

Für einen nochmals fortgeschriebenen Hauptzweig sind die dann neuen Änderungen
gesondert zu berücksichtigen.

## Genau geprüft

Der vorherige Gesamtpatch und die geordnete Folge aus neun Teilpatches plus
Notes-Patch ergeben auf der aktuellen Basis denselben Ergebnisbaum. Beide Wege
ergeben rückwärts exakt den aktuellen Basisbaum. Auch der neu ausgegebene
Gesamtpatch wurde vorwärts und rückwärts geprüft; der Whitespacecheck besteht.

Der vollständige Vergleich aller **4.702 Git-Pfade samt Dateimodi** mit dem zuvor
geprüften Gesamtbaum `3b5b94fd3256b01a3a775f39bfdae4d661f9d6b8` zeigt
**4.694 unveränderte Pfade und genau acht Unterschiede**. Die geänderten
Textsegmente sind exakt dieselben wie im zwischenzeitlichen Hauptzweigdelta
`f8ad956e → 1a578534`. Dazu gehören die neue passive Auswahl des Linux-Videoziels,
die zugehörigen Python-Helfer und Prüfungen sowie die neue Abschlussnotiz zu #846.
Die Zehner-Serie setzt keine dieser Änderungen zurück.

Die neue Linux-Videozielanzeige liegt in derselben großen Oberflächendatei wie
mehrere Reviewkorrekturen, aber in einem anderen Abschnitt. Deshalb wurde genau
der aktualisierte vorhandene Medien-UI-Test ausgeführt: **14/14 Fälle bestanden**
mit Node 24.22.3 und JSDOM 26.1.0. Die vorhandene generierte Zeitzonendatei wurde
für diesen Test bytegleich bereitgestellt und anschließend wieder entfernt.
Unveränderte Windows-, Notes-, Farb-, MCP- und native Prüfungen wurden nicht
erneut ausgeführt.

`compatibility.json` enthält die Befehle, Quellhashes, Baumvergleiche, Patchdaten
und Laufzeiten. `preserved-upstream.diff` zeigt sämtliche acht erhaltenen Deltas.
`verify.py` reproduziert die Prüfung mit den benannten Arbeitskopien,
vorherigen Patchdateien und vorhandenen Laufzeitabhängigkeiten.

## Neuer nachgewiesener Upstreamstand zu #846

Das zuvor noch offene vollständige Windows-Standalone-Quellarchiv-Gate ist
inzwischen **upstream bestanden und #846 geschlossen**:

- [Abschlussnachweis im Issue](https://github.com/maik3531/Magnolie-Organizer/issues/846#issuecomment-7227651086)
- [Windows-CI-Lauf 46058642735](https://github.com/maik3531/Magnolie-Organizer/actions/runs/46058642735)

Dieser native Nachweis stammt aus dem Hauptzweigworkflow und wurde hier nicht
nochmals ausgeführt. Die ältere Aussage, das Gate sei noch offen, ist damit für
diesen begrenzten Prüfpunkt überholt. Andere Paket- und Geräteabnahmen werden
dadurch nicht pauschal abgeschlossen.

## Grenze

Dieser Nachtrag ist ein enger Integrationsnachweis mit einem gezielten
Linux-DOM-Lauf. Er behauptet keinen neuen vollständigen Testlauf, keine native
Installation, keinen realen Telefon-/Internetversuch und keine Paketveröffentlichung.
Hauptzweig und Geräte wurden durch diese Prüfung nicht verändert.
