# Windows-PAD für Magnolie Organizer – Refs #562

Stand: 13. November 2026. **Öffentliche Bereitstellung vom Nutzer am 13. November 2026 freigegeben; noch bei keinem Portal eingereicht.**

## Konkrete Änderungen

- `pad/magnolie-organizer-windows.xml`: selbst gehosteter Windows-Datensatz mit PAD-4.0-Feldstruktur, fünf vollständigen Beschreibungsblöcken und offiziellen Downloadinformationen.
- `pad/release.json`: unveränderte öffentliche GitHub-Release-Metadaten als reproduzierbare Eingabe.
- `tools/pad/maintain.py`: Offline-Prüfung und lokale Aktualisierung aus einem neuen offiziellen Release-Datensatz; veröffentlicht nichts.
- `tools/pad/pad-4.0-spec.xml`: archivierte Felddefinitionen zur nachvollziehbaren lokalen Musterprüfung.
- Diese Dokumentation. Keine Anwendung, Installer, Versionsdatei oder bestehende CI wird geändert.

## Dauerhafte Adresse

Kanonische Feedadresse:

https://raw.githubusercontent.com/maik3531/Magnolie-Organizer/main/pad/magnolie-organizer-windows.xml

Diese Adresse benötigt weder eine neue Domain noch GitHub Pages. Die geprüften Dateien werden mit ausdrücklicher Freigabe in `main` übernommen. Der Raw-Endpunkt liefert die XML-Datei öffentlich über HTTPS. Versionsnummern bleiben im Inhalt und in der Installeradresse, nicht in der Feedadresse. Die Adresse funktioniert nur solange Repository, Standardpfad und öffentlicher Zugriff erhalten bleiben. Vor einer Umbenennung muss ein dauerhafter Ersatz samt Weiterleitung geplant werden.

Alternative bei später gewünschter eigener Webpräsenz: GitHub Pages unter `https://maik3531.github.io/Magnolie-Organizer/pad/magnolie-organizer-windows.xml`. Pages ist hier nicht eingerichtet oder überprüft; diese Alternative ist **nicht** im Feed eingetragen. Vor der ersten Einreichung genau eine kanonische Adresse wählen.

## Belegte Produktdaten

| Feld | Wert / Herkunft |
|---|---|
| Produkt | Magnolie Organizer for Windows; Android Notes ausgeschlossen |
| Version | 2.0.30, GitHub-Release `v2.0.30` |
| Veröffentlichungsdatum | 31.10.2026, `published_at=2026-10-31T22:04:17Z` |
| Installer | Magnolie-Organizer-Windows-2.0.30-Setup-x64.exe |
| Größe | 174431464 Bytes; PAD K=170343.23 und MB=166.35, jeweils Basis 1024 |
| Plattform | Windows 10/11 x64 laut offizieller README; keine Win7-/Win8-Kompatibilität behauptet |
| PAD-Betriebssystem | `WinOther`: die archivierte 4.0-Werteliste enthält keine Windows-10/11-Tokens; genaue Voraussetzung im Freitext |
| Autor / Kontakt | Maik Walter, maik3531@gmail.com, öffentlich in `magnolie-organizer/debian/control`; keine private Adresse ergänzt |
| Preis / Typ | 0.00 EUR/USD, PAD-Katalogkategorie `Freeware`; keine Behauptung einer proprietären Lizenz |
| Lizenz | Programm-/Handbuchquellen GPL-3.0-or-later; gesonderte Rechte für Schriften, Metadaten und geschützte QR-/Porträtdateien beachtet |
| Bild | Offizielle Wochenansicht aus dem Handbuch, keine neu erstellte Windows-Aufnahme |
| Icon | Offizielles 48×48-PNG aus der Windows-Quelle; direkte Bildadresse über GitHub Raw-Weiterleitung |

Maßgebliche Quellen:

- https://api.github.com/repos/maik3531/Magnolie-Organizer/releases/latest
- https://github.com/maik3531/Magnolie-Organizer/releases/tag/v2.0.30
- https://github.com/maik3531/Magnolie-Organizer/blob/main/README.md
- https://github.com/maik3531/Magnolie-Organizer/blob/main/LICENSING.md
- https://github.com/maik3531/Magnolie-Organizer/blob/main/magnolie-organizer/debian/control
- https://github.com/maik3531/Magnolie-Organizer/blob/main/magnolie-organizer-windows/installer/MagnolieOrganizer.nsi
- https://github.com/maik3531/Magnolie-Organizer/blob/v2.0.30/magnolie-organizer-windows/app/web/i18n.js
- https://github.com/maik3531/Magnolie-Organizer/tree/v2.0.30/magnolie-organizer-windows/app/web/i18n

Beschreibungen: Deutsch, Englisch, Spanisch, Französisch und Russisch, jeweils Keywords und Texte für 45/80/250/450/2000 Zeichen. Die Zahlen sind Höchstlängen, keine vorgeschriebene Textlänge. Die Texte sind neue redaktionelle Beschreibungen aus den belegten Produktfunktionen.

Oberfläche: Englisch als Rückfallsprache sowie Arabisch, Belarussisch, Chinesisch (vereinfacht), Tschechisch, Dänisch, Deutsch, Spanisch, Französisch, Hindi, Obersorbisch, Italienisch, Japanisch, Norwegisch (Bokmål), Niederländisch, Polnisch, Portugiesisch, Russisch, Türkisch und Ukrainisch. Die 19 Katalogdateien sind im Release-Tag vorhanden. PAD verwendet `Byelorussian`, `ChineseSimplified` und `Norwegian`; Obersorbisch hat dort keinen eigenen Token und wird als `Other` erfasst. Beschreibungssprachen sind keine unabhängige Aussage über die Oberfläche. Der NSIS-Installationsassistent selbst verwendet Deutsch; die Sprachliste betrifft das Programm.

## Spezifikation und ehrlicher Prüfumfang

PAD 4.0 ist die zuletzt in den geprüften offiziellen Unterlagen belegte veröffentlichte Version. Die ASP-Unterlage von 2018 beschreibt 4.1 als geplante Arbeitsgruppe, nicht als veröffentlichte Spezifikation:
https://asp-software.org/documents/ASPects_2018-04_EXTRA.pdf

Die bisherigen offiziellen Spezifikationsadressen `pad.asp-software.org`, `padspec.org` und `asp-software.org/pad/` waren bei dieser Prüfung nicht abrufbar. AppVisor leitete auf eine Domainverkaufsseite weiter. Deshalb keine Behauptung einer aktuellen offiziellen Online-Validierung.

Die lokale Referenz ist eine archivierte Kopie der PAD-4.0-Felddefinitionen aus:
https://github.com/tandemcommander/tandemcommander-web/blob/main/vendor/pad-4.0-spec.xml
Diese Kopie stammt von einem Drittprojekt, nicht von einem noch erreichbaren offiziellen Spezifikationsserver. Ihr Inhalt ist im Paket festgehalten; Änderungen daran müssen separat geprüft werden. Die Originaldefinitionen werden nicht stillschweigend erweitert, etwa um erfundene Windows-Tokens oder längere URLs.

Geprüft werden XML-Wohlgeformtheit, doppelte Elemente, bekannte Feldpfade, reguläre Ausdrücke aller vorhandenen Blattfelder, Beschreibungslängen, ein ausdrücklich definiertes Pflichtfeldprofil für den selbst gehosteten Feed und die Übereinstimmung mit Release-Metadaten. Die Spezifikationskopie enthält keine allgemeine Optionalitätskennzeichnung. Deshalb ist das lokale Pflichtfeldprofil **keine Behauptung vollständiger historischer AppVisor-Pflichtfeldkonformität**.

Nicht ergänzt: Stadt/Land/Postanschrift, Telefon, dedizierte Vertriebs-/Supportkontakte, AppVisor-PublisherID/AppID, Zertifikat-IDs, ASP-Mitgliedschaft, Virenscanergebnisse oder Authenticode-Nachweise. Dafür fehlen verifizierte Angaben oder es handelt sich um nicht verfügbare Dienstkennungen. `CERTIFIED=N` kennzeichnet den hier neu erstellten, nicht zertifizierten Feed. Ein strenger historischer Validator kann fehlende Identitäts-/Adressfelder beanstanden. Solche Rückmeldungen müssen anhand tatsächlicher Anforderungen geklärt werden, niemals mit erfundenen Werten. Die Aufnahme durch ein konkretes Portal ist erst nach dessen Prüfung belegt.

## Suche nach vorhandenem Feed

Vollständiger `main`-Baum bei Commit `ae3e13b565d7505d4363b7654b460a1a6f148406`: `truncated=false`, kein PAD-benannter Pfad. Aktuelle README ohne PAD-Adresse. GitHub-PR-Suche `repo:maik3531/Magnolie-Organizer PAD is:pr`: 0 Treffer, `incomplete_results=false`. Öffentliche Websuche ohne verifizierten Feed. Das schließt einen anders benannten oder extern gehosteten Feed nicht aus. Ein künftig nachgewiesener bestehender Feed sollte vor Einführung einer zweiten Adresse geprüft werden.

## Aktualisierung bei Releases

1. Erst das neue stabile Organizer-Release mit endgültigem Windows-Installer veröffentlichen. Notes- oder Beta-Releases sind keine Ersatzquelle.
2. Die vollständige JSON-Antwort von `https://api.github.com/repos/maik3531/Magnolie-Organizer/releases/tags/vX.Y.Z` lokal als `new-release.json` speichern. Die explizite Tag-Adresse vermeidet die versehentliche Auswahl eines Notes-Release über `latest`.
3. Aus der Repositorywurzel ausführen:

   `python3 tools/pad/maintain.py --update-release new-release.json --change-info "Reviewed Windows release summary"`

4. Das Skript übernimmt Version, UTC-Veröffentlichungsdatum, endgültigen Installerdateinamen, direkte Asset-URL und Bytegröße; K/MB werden neu berechnet. Es verweigert Entwürfe, Vorabversionen, fremde Repositorys und fehlende/nicht hochgeladene Installer. Die feste Feedadresse bleibt unverändert.
5. Sprachumfang, Systemvoraussetzungen, Produktbeschreibungen, Lizenz und Bildlinks bei inhaltlichen Änderungen separat prüfen. Die kurze Release-Zusammenfassung ist bewusst redaktionell, nicht automatisch aus Markdown abgeschnitten.
6. `python3 tools/pad/maintain.py` ausführen und Diff prüfen. Downloadadresse samt Weiterleitung mit HEAD/GET auf HTTP 200 prüfen; Content-Length mit `File_Size_Bytes` vergleichen. Bildadressen müssen echte Bilder liefern. Öffentlichen Feed nach Bereitstellung abrufen, XML parsen und mit dem freigegebenen lokalen Inhalt vergleichen.
7. Nach ausdrücklicher Freigabe geprüften Quellstand übernehmen. Keine automatische Push-/Deploy-Aktion ist enthalten. Keine erneute Download3K-Einreichung für reine Versionsupdates.

## Aufnahmewege

| Portal | Offizieller Weg | Konsequenz |
|---|---|---|
| Download3K | https://www.download3k.com/submit.php | Öffentliche stabile PAD-URL; selbst hosten empfohlen; nach Erstaufnahme dieselbe Datei aktualisieren, tägliche Abfrage laut Anbieter |
| Download3K-Sprachen | https://www.download3k.com/languages-guide.php | Lokalisierte Beschreibungen in de/fr/es/ru im selben Feed; keine Mehrfacheinreichung pro Sprachseite |
| Free Downloads Center | https://freedownloadscenter.com/author.htm | Lokale PAD-Datei oder PAD-URL |
| UpdateStar | https://client.updatestar.com/pad/ | Gehostete PAD-URL an den dort genannten Supportkontakt, keine XML als Anhang; noch keine Nachricht verfasst/gesendet |
| FDMlib | https://en.freedownloadmanager.org/submit/ | Lokale Datei oder URL; Sprachfassungen als ein Verzeichnis behandeln |

Diese Seiten nennen keinen vollständigen öffentlich prüfbaren Satz portalinterner Pflichtfelder. Daher keine garantierte Annahme. Download3K verlangt schadsoftwarefreie Downloads; die hier erfolgte Metadatenprüfung ersetzt keinen solchen Nachweis.

## Freigabe und verbleibende Prüfung

Die öffentliche Bereitstellung dieses Patches wurde am 13. November 2026 ausdrücklich freigegeben. Nach der Übernahme wird die öffentliche XML-Adresse auf HTTP 200, gültiges XML und Übereinstimmung mit dem lokalen Inhalt geprüft. Es wurde kein Portal angeschrieben; Issue #562 bleibt für den noch offenen Einreichungsumfang bestehen. Eine Einreichung erfolgt nur im ausdrücklich freigegebenen Umfang. Empfangsbestätigung und öffentlich sichtbarer Katalogeintrag bleiben getrennte Ergebnisse.
