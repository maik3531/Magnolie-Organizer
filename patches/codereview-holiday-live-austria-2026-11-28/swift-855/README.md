# #855 – ausgeführte Swift-Serviceprüfung, 28.11.2026

Der vorher ungeprüfte vollständige `HolidayService.swift` und seine vollständige
reguläre `HolidayServiceTests.swift` wurden unverändert mit **Swift 6.4.3** für
`x86_64-unknown-linux-gnu` kompiliert. **11 XCTest-Methoden bestanden, 1 vorhandener
Live-Mac-Test wurde ausdrücklich übersprungen, 0 Fehler, 0 Warnungen.** Alle fünf
neuen #855-Regressionsmethoden sind unter den bestandenen Fällen. Für diesen Lauf
war keine Änderung am Produkt oder an seinen Testassertionen erforderlich.

## Genaue Bindung

Produktbasis `1749c92eb42801c38eaba31b272d8c0e27be9164` mit dem veröffentlichten
#855-Patch, Ergebnisbaum `f4f94a2c2cf73a064448d3208f31d471e150dbe4`.
Patch-SHA-256 `c1cecd73eda51d3726962039bbb5b9e3bef8d34dede05897a64908acbb2f588c`.
`SOURCE-MANIFEST.json` bindet alle echten Eingaben; die sechs vollständigen
Dateikopien sind bytegleich mit Produkt-/Testquellen. Die drei Transportdatentypen
wurden wörtlich aus `DAV.swift` extrahiert, lediglich mit Foundation-Import ergänzt.

`swift-test-initial.log` enthält den vollständigen Build und XCTest-Lauf.
`RESULT.json` führt jede einzelne Testmethode auf. `TOOLCHAIN.json` bindet Herkunft,
Version und Prüfsummen. `Package.resolved` pinnt Swift ASN.1 auf die aufgelöste
Version; sie ist nur eine transitive Paketabhängigkeit von Swift Crypto.

## Transparente Hostgrenzen

Die unveränderte Testklasse injiziert für jeden ausgeführten Servicefall ihren
bereits vorhandenen kontrollierten Transport. Der native Default-Transport
`URLSessionBoundedTransport` wird **nicht** kompiliert oder geprüft: Ein klar
benanntes Hostmodul wirft dort ausdrücklich einen Fehler, falls dieser außerhalb
des Prüfumfangs liegende Weg versehentlich angesprochen wird. Der vorhandene
Test `testLivePublicHolidayServiceWhenRequested` ist ohne die ausdrückliche
Mac-Live-Umgebungsvariable ein von XCTest ausgewiesener Skip.

Die echten `Contract.swift`, `OpaqueUTF8Identity.swift`, `SystemSourcePolicy.swift`
und `FileImportProtocol.swift` sind eingebunden, damit auch der vorhandene
Bridge-Vertragstest seine tatsächliche Implementierung ausführt. Ihre CryptoKit-
Imports werden allein im Linux-Host über das offizielle Swift-Crypto-Paket 5.2.0
bereitgestellt (`@_exported import Crypto`). Dies ist keine Prüfung von Apples
CryptoKit, CommonCrypto, Security/Keychain oder AppKit.

**Dieser Nachweis schließt die offene Swift-Compiler-/XCTest-Prüfung des
HolidayService und seiner Regressionen im kontrollierten Linux-Host.** Ein
vollständiger macOS-App-Bau, native WebKit-/AppKit-Bedienung, der Apple-
Netzwerktransport, Live-Provider und installierte Pakete bleiben davon getrennt.

## Toolchain und Wiederholung

Die aktuelle offizielle [Debian-13-Toolchain](https://www.swift.org/install/linux/debian/13/)
wurde nach den [offiziellen Tarball-Schritten](https://www.swift.org/install/linux/tarball/)
heruntergeladen. Die getrennte PGP-Prüfung in `gpg-verify.log` endete erfolgreich
mit `VALIDSIG 52BB7E3DE28A71BE22EC05FFEF80A866B47A981F` (Swift 6.x Release Signing
Key). Das öffentliche Schlüsselbündel stammt von `https://swift.org/keys/all-keys.asc`.
Ein erster Schlüsselimport meldete Probleme beim Start des hier nicht benötigten
GPG-Agenten; der öffentliche Schlüsselring wurde dabei vollständig erstellt.
Die anschließende reine Signaturprüfung mit `--no-autostart` hatte Exitcode 0.

Swift Crypto stammt aus dem offiziellen [Release 5.2.0](https://github.com/apple/swift-crypto/releases/tag/5.2.0).
Compilerarchive, Bibliotheksquellen und erzeugte Binaries gehören nicht zum
Prüfbelegpaket. Für die Wiederholung beide Archive anhand `TOOLCHAIN.json` beziehen,
die Swift-PGP-Signatur prüfen und separat entpacken. Dann auf einer isolierten
Kopie der angegebenen Produktbasis den #855-Patch anwenden:

```sh
python prepare-host.py --repo /path/to/Magnolie-Organizer \
  --output /tmp/magnolie-holiday-swift-host \
  --swift-crypto /path/to/swift-crypto-5.2.0
env -u MACOS_BETA_LIVE_HOLIDAYS /path/to/swift-6.4.3/usr/bin/swift test \
  --package-path /tmp/magnolie-holiday-swift-host --jobs 2
```

Das Vorbereitungsskript prüft die vollständigen Eingabedateien gegen das
Manifest, bevor es eine Testkopie erzeugt. Es verändert keine Produktdatei.
