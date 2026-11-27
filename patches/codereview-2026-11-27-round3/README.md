# Magnolie-Codereview: dritte Patchübergabe vom 27. November 2026

## Letzter Issue-Abgleich während der Veröffentlichung

#839 wurde inzwischen unabhängig mit
[`852c8cf9`](https://github.com/maik3531/Magnolie-Organizer/commit/852c8cf958e780063138801d5f3e7982b50ab62b)
übernommen und [geschlossen](https://github.com/maik3531/Magnolie-Organizer/issues/839#issuecomment-7223553749).
Diese übernommene Portfassung einschließlich ihres gesonderten nativen Nachweises
bleibt erhalten. **Für die beobachtete Basis `852c8cf9` den
[verbleibenden Gesamtpatch](after-852c8cf9/remaining-review.patch) verwenden:**
Er enthält ausschließlich den #823-Notfallkontakt-Nachtrag und die zusätzlichen
#841/#842-Regressionen. Er verändert weder Portquellen noch den bereits
fortgeschriebenen Arbeitsstand.

Die drei entsprechenden Teilpatches aus der unten stehenden Serie sind eine
Alternative zu diesem verbleibenden Gesamtpatch. Beide Wege sind konfliktfrei
vorwärts und rückwärts geprüft. Die acht betroffenen Quell-/Testdateien sind
bytegleich zur tatsächlich geprüften letzten Reviewintegration; der unabhängige
Portcommit ändert keine Eingaben der fokussierten Python-/C#-Prüfung. Es gab
keinen erneuten Lauf gegen die Portfassung aus `852c8cf9`.
[Anwendbarkeit und Abgrenzung](upstream-852c8cf9.json) ·
[Exakter Patchnachweis](after-852c8cf9/replay.json).

## Vollständiger Reviewstand auf der vorausgehenden Basis

**Vollständige geprüfte Reviewbasis: `42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe`.**
Die [darauf abgestimmte vollständige Nachtragsserie](after-42af5bb0/magnolie-round3-after-42af5bb0.patch)
erhält die inzwischen unabhängig übernommenen Produktkorrekturen aus #823,
#841 und #842. Sie ergänzt den noch bestätigten Notfallkontakt-Rest aus #823,
die Portkorrektur aus #839, die zusätzlichen Regressionen und den Arbeitsstand.

Dieser Artefaktzweig stellt vollständige Patches, reproduzierbare synthetische
Fälle und die zugehörigen Prüfnachweise zur späteren Codex-Einpflege bereit.
Sein Produktquellstand ist die unveränderte oben genannte Basis; die geprüften
Änderungen liegen in den Patchdateien. Es wurde kein Produktmerge nach `main`
und keine Paketveröffentlichung durchgeführt.

## Die vier zugeordneten Issues

| Issue | Bestätigter Umfang und inzwischen übernommener Stand | Inhalt der empfohlenen Serie |
|---|---|---|
| [#823](https://github.com/maik3531/Magnolie-Organizer/issues/823) | Der ursprüngliche Kontaktfall nach UID-Zuweisung ist seit [42af5bb0](https://github.com/maik3531/Magnolie-Organizer/commit/42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe) korrigiert. Beim weiteren Abgleich verliert dessen Inhaltsauswahl jedoch das unterstützte Feld `kontaktpersonen`: Nach UID-Wechsel wird aus zwei gesicherten Notfallkontakten nur der über alte Einzelfelder rekonstruierte erste Kontakt. | Kleiner Produktnachtrag: `kontaktpersonen` in beide bestehenden Inhaltslisten aufnehmen. Alle 40 übernommenen Vektoren erhalten; zwölf weitere Reviewfälle und der neue Notfallkontaktfall ergänzen insgesamt 53 gemeinsame Vektoren. Hinzu kommen Tests an den tatsächlichen Linux-Restore-/Save-Dateigrenzen. |
| [#839](https://github.com/maik3531/Magnolie-Organizer/issues/839) | Absolute und gewöhnliche Alarme desselben Eintrags zum selben Zeitpunkt erzeugen doppelte Meldungen. Alte Tablet-Pläne und bereits vorhandene Meldebelege brauchen denselben Abgleich. Unter macOS kann das Entfernen eines absoluten Aufgabenalarms eine bereits verbrauchte Fälligkeits-/Vorlaufmeldung erneut aktivieren. | Vollständiger Nachtrag für beide Portwege, alte verschlüsselte Tablet-Pläne und gemeinsame native Meldebelege; zusätzliche bestehend angebundene DOM-/JVM-Prüfungen. |
| [#841](https://github.com/maik3531/Magnolie-Organizer/issues/841) | Arabische regionale Sprachcodes stellten beim tatsächlichen Systemsprachenstart auf LTR. Die Produktkorrektur wurde unabhängig mit [ecad9a05](https://github.com/maik3531/Magnolie-Organizer/commit/ecad9a054b1acca3c204c733466eb7b5a23cd0ec) übernommen; das Issue ist geschlossen. | Ausschließlich zusätzliche vollständige DOM-Startregression und Registrierung im bestehenden Webtestlauf. Die übernommenen `i18n.js`-Dateien bleiben erhalten. |
| [#842](https://github.com/maik3531/Magnolie-Organizer/issues/842) | Ungültiges UTF-16LE/BE mit BOM wurde unter Windows mit Ersatzzeichen importiert. Die unabhängige strenge Decoderkorrektur ist seit [dd997f01](https://github.com/maik3531/Magnolie-Organizer/commit/dd997f01ea5a16d4c37c4ac938e068ee1a8e361a) übernommen; das Issue ist geschlossen. | Ausschließlich zusätzliche 148 Datei-/ZIP-/Müllkalenderfälle im vorhandenen C#-Testprojekt. Übernommener Decoder und vorhandene Vertragsprüfungen bleiben erhalten. |

Bei #823 bezeichnet der ursprüngliche Ausgangsfall eine vorhandene gültige
ältere Karte ohne externe UID. Eine leere UID aus dem heutigen Neuanlage-Dialog
wird nicht behauptet. Die Beschränkung auf bekannte Inhaltsfelder gilt beim
UID-Wechsel; sie ist keine allgemeine Bereinigung beliebiger Kontaktmetadaten.
Bei #839 bleiben unterschiedliche Einträge, Sektionen, Quellen und Zeitpunkte
getrennt; mehrdeutige alte lokale Identitäten werden nicht geraten.

## Vollständige Patchreihenfolge für die Basis 42af5bb0

| Schritt | Vollständiger Patch | Beschreibung und Nachweise |
|---|---|---|
| 1 | [01 – #823](after-42af5bb0/series/01-823-contact-persons-regression.patch) | [Aktueller Feldrest und Integration](evidence/after-42af5bb0/README.md), [ursprüngliche Kontaktanalyse](evidence/823/README.md) |
| 2 | [02 – #841](after-42af5bb0/series/02-841-startup-regression.patch) | [DOM-Start, Sprachenkataloge und Grenzen](evidence/841/README-841.md) |
| 3 | [03 – #842](after-42af5bb0/series/03-842-unicode-regression.patch) | [Decoder-, Datei- und ZIP-Nachweise](evidence/842/README.md) |
| 4 | [04 – #839](after-42af5bb0/series/04-839-alarm-receipts.patch) | [Meldeidentitäten, alte Pläne und native Prüfgrenze](evidence/839/README.md) |
| 5 | [05 – Arbeitsstand](after-42af5bb0/series/05-review-handoff.patch) | Ergänzt ausschließlich `ARBEITSSTAND.md`; vorhandener Inhalt bleibt erhalten. |

Der [Gesamtpatch](after-42af5bb0/magnolie-round3-after-42af5bb0.patch) und die fünf
geordneten Teilpatches ergeben denselben geprüften Baum. **Einen der beiden Wege
anwenden.** Der Gesamtpatch wird mit `git apply`, die mbox-Teilpatches können mit
`git am` übernommen werden. Die Quellcommit-IDs in den Nachweisen stammen aus den
lokalen Reviewzweigen; maßgeblich für die Rekonstruktion sind Basis, Patchbytes
und Ergebnisbaum im [Anwendungsnachweis](after-42af5bb0/replay.json).

Beispiel zur Rekonstruktion des vollständigen 42af-Reviewstands aus einem Checkout dieses Artefaktzweigs:

```bash
PATCH_DIR="$PWD/patches/codereview-2026-11-27-round3"
git worktree add --detach ../magnolie-round3-review 42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe
git -C ../magnolie-round3-review apply --check "$PATCH_DIR/after-42af5bb0/magnolie-round3-after-42af5bb0.patch"
git -C ../magnolie-round3-review apply "$PATCH_DIR/after-42af5bb0/magnolie-round3-after-42af5bb0.patch"
```

Bei einem später veränderten `main` nur die dort noch fehlenden Änderungen
übernehmen und betroffene geänderte Eingaben gezielt nachprüfen. Diese Übergabe
ist bewusst an einen überprüften Commit gebunden.

## Prüfergebnisse und ihre Aussagekraft

| Prüfung | Ergebnis und gebundener Stand |
|---|---|
| Neuer Notfallkontaktfall gegen unveränderte `42af5bb0`-Produktquellen | Python: 143 bestanden, 1 fehlgeschlagen; C#-Identitätsgruppe scheitert ausschließlich am neuen gemeinsamen Fall. Der tatsächliche vCard-Schreib-/Leserundlauf bestätigt zwei unterstützte Notfallkontakte. |
| Fokussierte Python-Prüfung nach dem kleinen Feldnachtrag | **144 bestanden**, einschließlich 53 gemeinsamer Fälle jeweils additiv/ersetzend und tatsächlicher Restore-/Save-Dateigrenzen. |
| Aktuelle C#-Integration | **Build mit gesperrten Abhängigkeiten: 0 Warnungen, 0 Fehler; sechs Gruppen bestanden.** Darunter 53 gemeinsame Restore-Vektoren, Journalprüfung, 148 Unicode-Importfälle und drei bestehende Import-/Exportgruppen. |
| Vollständige DOM-Sprachstarts | **16 bestanden** über beide Desktopquellen; vorher acht Fehler. Zusätzlich bestehende regionale Zeiteingabe über 20 Sprachen je Desktop und Lokalisierungsvollständigkeit bestanden. |
| macOS-Oberfläche und Controller | **398 Prüfungen bestanden**; tatsächliche generierte Produktprojektion, DOM und Brückenaufrufe. |
| Tablet-Oberfläche | **30 Fälle bestanden** einschließlich gewöhnlichem Speichern und daraus erzeugten Alarmplänen. |
| Tatsächliche Tablet-Speicherklassen unter JVM | **23 JUnit-Prüfungen bestanden**, einschließlich Verschlüsselung, gespeicherten Altplänen, Belegen und erneutem Öffnen. |
| Unabhängige zusätzliche Gegenprüfungen | Sechs Kontaktidentitätsfälle und 28 Decoder-Randfälle bestanden auf den dokumentierten ursprünglichen Reviewquellen. |

Die aktuelle Python-/C#-Prüfung wurde erneut auf der an `42af5bb0` angepassten
Serie ausgeführt. Die übrigen oben genannten DOM-/Portergebnisse stammen aus
der gemeinsamen historischen Integration und gelten für bytegleiche relevante
Eingaben. Der [Gleichheitsnachweis](evidence/after-42af5bb0/source-equality-manifest.json)
bindet diese Zuordnung; unveränderte Suiten wurden nicht zusätzlich wiederholt.
Die historischen 136 Python-Fälle und 49 Restore-Vektoren sind damit keine
abweichenden Zählungen desselben neuesten Laufes, sondern ausdrücklich ältere
Quellstände vor den drei unabhängig übernommenen Vektoren und dem zusätzlichen
Notfallkontaktfall.

Host-DOM-, .NET- und JVM-Läufe belegen keine installierte Windows-/Linux-GUI,
DPAPI, echte macOS-Mitteilungszustellung oder Android-NotificationManager.
`ReminderReceiver` und eine installierte Android-Anwendung wurden in dieser
Runde nicht ausgeführt. macOS behält den bisherigen Umfang der geöffneten,
entsperrten Sitzung und bekommt keinen neuen dauerhaften Meldebelegspeicher.
Paket-/Geräteabnahmen bleiben in [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113)
und [#121](https://github.com/maik3531/Magnolie-Organizer/issues/121) sowie den
jeweiligen Plattformissues getrennt. Der gesonderte CSV-Kontaktrest aus
[#566](https://github.com/maik3531/Magnolie-Organizer/issues/566) wird hier nicht
als abgeschlossen ausgewiesen.

## Alternative historische Basen

| Basis | Vollständiger Gesamtpatch | Verwendung |
|---|---|---|
| `852c8cf9…` | [Verbleibender Gesamtpatch nach unabhängiger Portübernahme](after-852c8cf9/remaining-review.patch) | Für diese zuletzt beobachtete Hauptzweigbasis: nur #823-Feldnachtrag und #841/#842-Tests, bestehende Portkorrektur erhalten. |
| `42af5bb0…` | [Vollständige vorausgehende Reviewserie](after-42af5bb0/magnolie-round3-after-42af5bb0.patch) | Enthält nur die gegenüber dieser geprüften Basis fehlenden Produktnachträge und Tests. |
| `dd997f01…` | [Zwischenstand nach Sprach-/Decoderübernahme](after-dd997f01/magnolie-round3-after-dd997f01.patch) | Historische vollständige Kontaktkorrektur plus #839 und zusätzliche Regressionen; enthält den Notfallkontakt-Feldnamen bereits. Nicht zusätzlich auf die empfohlene Serie anwenden. |
| `0cdd6f99…` | [Ursprüngliche vollständige Reviewserie](historical/magnolie-codereview-round3.patch) | Dokumentiert alle vier ursprünglichen Produktkorrekturen und Nachweise vor den unabhängigen Übernahmen. Nicht zusätzlich auf eine neuere Route anwenden. |

Für jede Route sind Gesamtpatch und Teilserie getrennt vorwärts auf den exakten
Ergebnisbaum und rückwärts auf den exakten Basisbaum geprüft. Die Dateien in
`evidence/823`, `evidence/839`, `evidence/841` und `evidence/842` beschreiben die
ursprünglichen isolierten Reviewstände; `evidence/integration-historical` bindet
deren gemeinsame Integration. `evidence/current` dokumentiert ausdrücklich den
Zwischenstand auf `dd997f01`, `evidence/after-42af5bb0` die empfohlene letzte Serie.

## Integrität und Wiederholung

[manifest.json](manifest.json) enthält SHA-256, Git-Blob-ID und Byteanzahl aller
ausgelieferten Dateien außer sich selbst. [normalization.json](normalization.json)
weist die für die Veröffentlichung ersetzten flüchtigen Hostpfade und die
dadurch aktualisierten Metadatenprüfsummen aus. Produktpatches bleiben bytegleich;
ursprüngliche Hashwerte der betroffenen Logs/Metadaten sind zusätzlich erhalten.
Die enthaltenen Runner nutzen die vorhandenen Repository-Testwege und explizite
Checkout-/Werkzeug-/Ausgabepfade. Für die aktuellen vollständigen Prüfungen ist
der Runner unter `evidence/after-42af5bb0` maßgeblich.

```bash
python3 "$PATCH_DIR/verify_delivery.py"
python3 "$PATCH_DIR/verify_delivery.py" --repository ../magnolie-round3-review
```

Der zweite Befehl rekonstruiert die Patches ausschließlich in temporären
Git-Indizes. Er verändert weder den normalen Index noch die Arbeitsdateien.

## Exakte Bindung der vollständigen 42af-Serie

| Bestandteil | Wert |
|---|---|
| Basiscommit | `42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe` |
| Basisbaum | `ebce761a5dc8774e968dc1fdbe7a11f815d04dc9` |
| Geprüfter Quellcommit vor Dokumentation | `1a1423730f9b179b45bf281211f4c3f3afec8583` |
| Finaler Quellcommit einschließlich Dokumentation | `5839a53bdaabdb455f3f1fd298506c38c69d78db` |
| Exakter Ergebnisbaum | `ceb603576b01a9ea8952f9aefa74f963fe587bdf` |
| Gesamtpatch SHA-256 | `a0979fbe478e87983b8e1f7b56fe63fa936cc7a8cb7fab1937db23f77b9f2072` |
| Gesamtpatch Bytes | `64338` |
