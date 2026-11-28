# #856 – österreichische Providerregionen, Swift-Prüfnachweis

Der enge Mac-Teilpatch korrigiert ausschließlich die Grenze zwischen den internen
ISO-Regionen `AT-1` bis `AT-9` und den neun offiziell gelieferten OpenHolidays-
Providercodes. Er baut auf dem unveränderten #855-Kandidaten
`f4f94a2c2cf73a064448d3208f31d471e150dbe4` auf. `mac-at-856.patch` ist der
entsprechende Delta-Patch der beiden Mac-Dateien, kein zweiter Gesamtpatch.

## Änderung

Die vom Nutzer gewählte Region bleibt ein ISO-Code. Ausschließlich im HTTP-
Queryparameter wird dieser auf `AT-BL`, `AT-KÄ`, `AT-NÖ`, `AT-OÖ`, `AT-SB`,
`AT-SM`, `AT-TI`, `AT-VA` oder `AT-WI` übersetzt. URLComponents übernimmt die
UTF-8-Prozentkodierung. Antwortcodes werden vor der vorhandenen ASCII-Prüfung
auf die bekannten ISO-Codes zurückgeführt. Cachefelder, zusammengefasste
Regionen und die #855-Abdeckungsbestätigungen bleiben somit konsistent.

Unbekannte AT-Auswahlen werden durch den vorhandenen Query-Fehlervertrag vor
HTTP zurückgewiesen. Unbekannte sichere ASCII- und fremde Antwortcodes bleiben
wie bislang toleriert lesbar, bestätigen aber niemals die vollständige AT-
Abdeckung. Unbekannte Unicode-/malformierte Werte bleiben unter der bisherigen
strikten Parserreaktion. Die Zeichenprüfung wird nicht allgemein gelockert.

## Tatsächlich ausgeführt

Die identischen sechs neuen Testmethoden wurden zunächst mit der unveränderten
#855-Servicequelle und anschließend mit dem Korrekturkandidaten im selben
Swift-Host ausgeführt:

| Stand | Bestanden | Fehlgeschlagen | Expliziter Live-Skip |
| --- | ---: | ---: | ---: |
| #855 mit neuen #856-Assertions | 12 | 5 | 1 |
| #855 + #856 | **17** | **0** | **1** |

Die sechs neuen Methoden prüfen alle neun Paare und beide Endpoints,
Umlautcodes mit tatsächlichen UTF-8-URL-Queryparametern, Mehrregionsantworten
einschließlich Alias/ISO-Deduplizierung, ungültige Auswahlen, unbekannte/fremde
Antworten, bestehende Unicode-Ablehnung sowie unverändertes DE-/CH-Verhalten.
Auch alle elf zuvor ausgeführten #855-Methoden bleiben grün. Die 63 einzelnen
fehlgeschlagenen Assertions auf der Vorfassung sind keine 63 unabhängigen Bugs.

Beide Builds waren erfolgreich und warnten nicht. `before.log` und `after.log`
enthalten die vollständigen Ausgaben, `RESULT.json` alle Methodenergebnisse.
Die Eingabehashes belegen identische Testbytes vor/nach der Korrektur und binden
die endgültigen Produktquellen. `git diff --check` bestand für beide Mac-Dateien.

## Wiederholung und Grenzen

Compiler: Swift 6.4.3 für Debian 13/x86_64; die PGP-geprüfte Toolchain und die
Swift-Crypto-5.2.0-Kompatibilität sind im separaten #855-Swift-Nachweis vollständig
beschrieben. `TOOLCHAIN.json` ist dessen unveränderliche Herkunftsquittung und
beschreibt dort den ursprünglichen #855-Lauf; die zusätzlichen #856-Quellhashes
stehen in diesem Ordner.

Das gleiche `prepare-host.py` prüft hier gegen das aktualisierte Manifest.
Nach Anwendung des vollständigen #855-Patches und dieses #856-Deltas:

```sh
python prepare-host.py --repo /path/to/Magnolie-Organizer \
  --output /tmp/magnolie-at-swift-host --swift-crypto /path/to/swift-crypto-5.2.0
env -u MACOS_BETA_LIVE_HOLIDAYS /path/to/swift-6.4.3/usr/bin/swift test \
  --package-path /tmp/magnolie-at-swift-host --jobs 2
```

Die vollständigen echten Service- und XCTest-Dateien sowie Contract-/JSON-
Hilfsdateien sind unverändert in den Host kopiert. Alle ausgeführten Abrufe
verwenden den vorhandenen XCTest-Transport. Der unbenutzte native Default-
Transport wirft im Host ausdrücklich einen Fehler. **Kein nativer Mac-App-
Bau, keine AppKit-/WebKit-/Keychain-Abnahme und kein Live-Mac-HTTP-Nachweis.**
Die separate Live-Reproduktion des tatsächlichen Providers gehört zum
übergreifenden #856-Beleg. Keine Produktübernahme oder Paketfreigabe.
