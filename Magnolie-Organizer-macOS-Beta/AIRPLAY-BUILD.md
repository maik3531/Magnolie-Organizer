# In Magnolie eingebauter AirPlay-Empfänger – Bau zu #721

Der Empfänger wird aus dem enthaltenen, auf UxPlay 1.73.7 gebundenen Quellcode
gebaut und zusammen mit seinen Laufzeitbibliotheken in die Magnolie-App gelegt.
Auf dem Mac des Anwenders werden weder UxPlay noch Homebrew, CMake oder ein
separater GStreamer installiert. Das iPhone verwendet seine vorhandene
Bildschirmsynchronisierung. Dies beschreibt den implementierten Bauweg; ein
bestandener nativer Magnolie-/iPhone-Test ist damit nicht behauptet.

## Einbindung in den vorhandenen Entwicklungsbau

Der bestehende Ablauf mit `project_ui.py` und `tools/build_dev.py` bleibt der
Einstiegspunkt. Nach dem Einfrieren und Erzeugen der Projektion wird auf einem
Mac derselben Architektur gebaut:

```sh
python3 tools/build_dev.py --airplay-sdk /absoluter/pfad/zum/vorbereiteten-sdk
```

Der SDK-Pfad wird bewusst vom Entwickler angegeben. Der Bau lädt nichts herunter
und startet keinen Paketmanager. Der vorhandene Mac-Bau benötigt Apples
Entwicklungswerkzeuge; für diesen zusätzlichen C/C++-Bauteil müssen CMake und
pkg-config bereits vorhanden sein. Ohne `--airplay-sdk` bleibt ein Entwicklungsbau
ohne Empfänger möglich; die Oberfläche meldet dann die fehlende eingebaute
Komponente. Ein solcher Bau ist kein AirPlay-Paket.

Der Bau verlangt weiterhin macOS 12.7 als Mindestziel und genau `arm64` oder
`x86_64` für die aktuelle Zielarchitektur. Auch alle gebündelten Bibliotheken und
GStreamer-Plugins müssen diese Architektur und ein höchstens so hohes
Mindestsystem tragen. Ein SDK mit ausschließlich neueren Bibliotheken wird
abgelehnt; die Anwendung hebt ihre Systemanforderung dadurch nicht still an.

## Inhalt des vorbereiteten SDK

Die folgenden Verzeichnisse enthalten die bereits gebauten Entwicklungsteile,
inklusive Headern und `.pc`-Dateien. Die drei Wurzelverzeichnisse sind fest:

| Pfad | Inhalt |
| --- | --- |
| `GStreamer.framework/` | Vollständiges offizielles oder selbst gebautes Framework; Core mindestens 1.22, Video/SDP/App/GLib sowie die für H.264/AAC/ALAC und macOS-Ausgabe benötigten Plugins |
| `openssl/` | OpenSSL 3, Header, dynamische Bibliotheken und `lib/pkgconfig` |
| `libplist/` | libplist ab 2.0, Header, dynamische Bibliotheken und `lib/pkgconfig` |
| `sdk.json` | Genaue Versionen, Lizenzen, Quellenarchive und Prüfsummen |
| Weitere deklarierte Komponenten | Nur wenn ein tatsächlich verwendetes SDK weitere nicht bereits im Framework enthaltene Bibliotheken benötigt |

Das Framework muss insbesondere diese Laufzeitpfade enthalten:

```text
GStreamer.framework/Versions/Current/lib/gstreamer-1.0/
GStreamer.framework/Versions/Current/lib/gio/modules/
GStreamer.framework/Versions/Current/libexec/gstreamer-1.0/gst-plugin-scanner
```

`Versions/Current` darf ein relativer Link innerhalb desselben Frameworks sein.
Aus dem SDK herausweisende oder kaputte Links werden abgelehnt. Die Prüfung
schließt alle Mach-O-Laufzeitdateien des Frameworks ein, auch noch nicht während
eines Tests geladene Plugins.

### `sdk.json`

Dies ist eine Vorlage mit ausdrücklich zu ersetzenden Versions- und Hashwerten.
Es ist kein herunterladbares SDK und keine Zusage, dass bestimmte Kombinationen
schon mit einem iPhone geprüft wurden. Die tatsächlichen Versionen müssen exakt
den Ausgaben der mitgelieferten pkg-config-Module entsprechen.

```json
{
  "schemaVersion": 1,
  "components": [
    {
      "name": "gstreamer",
      "version": "EXAKTE-SDK-VERSION",
      "root": "GStreamer.framework",
      "license": "Lizenzen aller enthaltenen GStreamer- und SDK-Komponenten",
      "licenseFiles": [
        {"path": "notices/gstreamer-sdk-notices.txt", "sha256": "ERSETZEN"}
      ],
      "sourceArchives": [
        {"path": "sources/gstreamer-sdk-corresponding-source.tar.xz", "sha256": "ERSETZEN"}
      ]
    },
    {
      "name": "openssl",
      "version": "3.EXAKTE.VERSION",
      "root": "openssl",
      "license": "Apache-2.0",
      "licenseFiles": [
        {"path": "notices/openssl-LICENSE.txt", "sha256": "ERSETZEN"}
      ],
      "sourceArchives": [
        {"path": "sources/openssl-corresponding-source.tar.gz", "sha256": "ERSETZEN"}
      ]
    },
    {
      "name": "libplist",
      "version": "EXAKTE-SDK-VERSION",
      "root": "libplist",
      "license": "LGPL-2.1-or-later",
      "licenseFiles": [
        {"path": "notices/libplist-COPYING.txt", "sha256": "ERSETZEN"}
      ],
      "sourceArchives": [
        {"path": "sources/libplist-corresponding-source.tar.gz", "sha256": "ERSETZEN"}
      ]
    }
  ],
  "loadPrefixMappings": {
    "/Library/Frameworks/GStreamer.framework": "GStreamer.framework"
  }
}
```

Jeder Hash ist der SHA-256 des tatsächlich bereitgestellten Dokuments/Archivs.
Der Paketverantwortliche stellt die vollständigen zugehörigen Quellen,
Änderungen, Lizenztexte und nötigen Bauhinweise für die ausgelieferten
Bibliotheken bereit. Der technische Check prüft deren Vorhandensein und
Prüfsummen; er entscheidet nicht selbst, ob der angegebene Quelleninhalt alle
Lizenzpflichten erfüllt.

Bibliotheken aus einem bereits vorbereiteten Bau können noch ihren früheren
absoluten Installationspfad tragen. Dafür kann `loadPrefixMappings` genau diesen
Präfix auf die entsprechende SDK-Wurzel abbilden. Der Bau liest dadurch keine
Bibliothek aus dem alten Verzeichnis. Das ist eine ausdrückliche Zuordnung auf
die bereitgestellte Kopie. Nicht zugeordnete `/opt/homebrew`, `/usr/local` oder
andere fremde Laufzeitpfade führen zum Abbruch. `.pc`-Präfixe werden nur in
privaten Baukopien umgeschrieben; das Eingabe-SDK bleibt unverändert.

## Paketinhalt und technische Prüfungen

| App-Pfad relativ zu `Contents` | Bedeutung |
| --- | --- |
| `Helpers/magnolie-airplay-receiver` | Der aus der Magnolie-Quelle gebaute interne Helfer |
| `Frameworks/GStreamer.framework` | Mitgelieferter Renderer, Plugins und Plugin-Scanner |
| `Frameworks/AirPlay/…` | Zusätzlich tatsächlich benötigte Bibliotheken aus den deklarierten SDK-Komponenten |
| `Resources/AirPlay/manifest.json` | Kleine, versionierte Laufzeitbeschreibung; wird nur nach vollständig bestandener Paketprüfung geschrieben |
| `Resources/AirPlay/provenance.json` | SDK-Eingangshashes, Binärhashes, Komponenten und Quellen-/Lizenzzuordnung |
| `Resources/AirPlay/Magnolie-AirPlay-Receiver-source.tar.gz` | Exakte integrierte Empfängerquelle einschließlich Magnolie-Änderungen |
| `Resources/AirPlay/Licenses` und `Sources` | Bereitgestellte Bibliothekslizenzen und zugehörige Quellenarchive |

Alle nicht zu Apple gehörenden dynamischen Verweise müssen innerhalb des Bundles
auflösbar sein. Der Bau schreibt sie auf präzise `@loader_path`-Referenzen um,
entfernt bisherige Runpaths und prüft die gesamte Abhängigkeitskette erneut.
Nicht auflösbare, mehrdeutige oder aus dem Bundle herausweisende Verweise brechen
ab. Systembibliotheken sind auf `/usr/lib/` und `/System/Library/` begrenzt.

Signiert wird von innen nach außen: einzelne Mach-O-Dateien, Framework-Bundles,
danach die Magnolie-App. Diese Ad-hoc-Signierung gehört zum bestehenden
Entwicklungsbau; sie ist weder eine Developer-ID-Signierung noch Notarisierung
oder Release-Freigabe. Eine native Paketabnahme und die echte iPhone-Strecke
bleiben gesondert erforderlich. Vor einem Release gehören insbesondere die
Plugin-/Codec-Verfügbarkeit, macOS-Netzwerkberechtigung, Bild, Ton, Rotation,
Sperren/Stop, erneutes Verbinden und längere Sitzungen auf beiden Architekturen
zur Abnahme.

## Portable Prüfung

```sh
python3 tests/test_airplay_bundle.py
```

Diese Tests prüfen mit synthetischen Dateigraphen die transitive
Bibliotheksauflösung, Plugin-Erfassung, Relocation, Quellenidentität sowie
Abbruchfälle für fremde Bibliotheken, Mehrdeutigkeit, Symlink-Ausbruch und
unpassendes Mindest-macOS. Sie führen keine macOS-Binärdatei aus und ersetzen
keine native Build-/Signatur-/Geräteprüfung.
