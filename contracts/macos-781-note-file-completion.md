# #781 — Dateinotizimport nach Darstellungsfehler abschließen

Produktbefund auf `616069f15fed21d8d8d05c8ef795f4ed21bd059c`; Patchbasis
`a26bb1302f3f5b772b83c9530f3098df34262f20` mit den Hinweisen aus #778.

## Ursache und belegte Auswirkung

`macOSBetaImportNoteFiles()` registriert einen asynchronen Callback für den
Wiederherstellungspunkt. Der äußere `try/catch` ist beendet, wenn dieser
Callback später läuft. Wirft `zeichneAlles()` nach dem Anhängen der Notizen,
wird deshalb weder die Save-ACK-Anmeldung erreicht noch das ursprüngliche
Import-Promise abgeschlossen.

Die Fehler-Injektion im öffentlichen `MagnolieAppearance.update`-Hook wurde
an der tatsächlichen generierten Oberfläche mit synthetischer Textdatei
ausgeführt: `appended: true`, `settledRenderer: false`, die Exception trat
beim Snapshot-Callback aus. Ein begrenzter 250-ms-Beobachter meldete Timeout.
Das ist ein reproduzierter JS-Transaktionsfehler, kein behaupteter nativer
Mac-Absturz oder bereits eingetretener Benutzerdateiverlust.

## Änderung

- Der asynchrone Callback besitzt einen eigenen `try/catch`. Alle Fehler
  erreichen das ursprüngliche Import-Promise.
- Nach dem Anhängen wird zuerst das Speichern eingeplant. Ein Rendererfehler
  erhält denselben präzisen Hinweis wie #778: Kopien stehen im Dokument,
  ihre Speicherung ist aber noch nicht bestätigt.
- Ein tatsächlich abgelehntes Save-ACK bleibt ausdrücklich ein ungespeicherter
  Zustand. Keine Rücknahme und kein Speichererfolg werden erfunden.
- Erfolg nach ACK erfordert weiterhin dasselbe Dokument, erlaubten Zustand
  und die tatsächliche Anwesenheit aller hinzugefügten Notizobjekte.
- Der Swift-Host übernimmt den konkreten Promise-Fehler als strukturiertes
  Ergebnis. Sein bestehendes `defer { finished() }` beendet die laufende
  Dateiauswahl-/Importoperation auch beim Fehler; überholte Dokumentgenerationen
  werden weiterhin ignoriert. Die übernommene Fehlermeldung ist auf 2048 Zeichen
  begrenzt.

Der Dateiimport bleibt bewusst additiv. Er erhält keine neue automatische
Quell-Deduplikation; ein erneutes absichtliches Auswählen derselben Datei ist
eine neue Importaktion. Der geprüfte Retry speichert die bereits vorhandene
Kopie, statt die Datei erneut zu importieren.

## Tatsächliche Prüfungen

Node 24.22.3 / JSDOM 26.1.0, Linux-Prüfhost:

```sh
python3 -m unittest discover -s Magnolie-Organizer-macOS-Beta/tests \
  -p test_host.py -k additive_selected_note_files_contract -v
```

**41 Hostprüfungen bestanden**, einschließlich aller bisherigen Importfälle
und neuer Fehlerfälle in Englisch und Deutsch: Promise-Abschluss, präziser
Hinweis, unveränderte Bestandsnotizen, exakter Text der angehängten Kopie,
kanonischer Save-Retry und erneut geladenes Buch mit genau derselben lokalen
Notiz-ID. Eine falsche ACK-ID lässt den Import warten; eine passende ACK nach
Entfernung der importierten Notiz meldet keinen Importerfolg. JavaScript-Syntax und Diff-Whitespace geprüft.

Die nativen Nutzlasten und Speicherquittungen waren synthetisch. Swift,
AppKit-Dateiauswahl, echtes WKWebView und nativer Datenträger wurden hier nicht
ausgeführt. Codex soll den Swift-Bau auf beiden Architekturen prüfen und den
Fehlerpfad im tatsächlichen Dateiauswahldialog abnehmen. Der Patch baut auf den
deutschen/englischen Speicherhinweisen aus #778 auf.

Andere Editionen besitzen andere Dateiimporttransaktionen. Aus diesem
Mac-Nachweis wird kein ausgeführter Linux-/Windows-Produktfix abgeleitet.
