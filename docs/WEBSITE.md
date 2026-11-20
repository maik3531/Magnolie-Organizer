# Magnolie-Projektwebsite

Die vollständige Website liegt im bestehenden Magnolie-Organizer-Repository.
`index.html` ist der allgemeine Einstieg; `presse/index.html` enthält die Presseschau.
Die Ordner `de/`, `en/` und `intl/` enthalten die festen Sprachseiten, `assets/`
die Gestaltung und Produktbilder und `media/` sämtliche Videos, Untertitel,
Broschüren und das Medienpaket. Die Website benötigt nur einen statischen
Webserver und keine ChatGPT-Dienste, API-Schlüssel oder JavaScript-Pakete.

## Sprachen und zentrale Rechtsseiten

Impressum, Datenschutz und der persönliche Projektcharakter stehen in allen
20 unterstützten Sprachen zur Verfügung. `impressum/index.html` und
`datenschutz/index.html` sind die deutschen Ausgangsfassungen; die weiteren
Rechtsseiten liegen unter `en/` beziehungsweise `intl/<Sprache>/`. Jede
Sprachseite verlinkt ihre eigenen Rechtsseiten. Die Rechtsseiten bieten eine
Sprachwahl mit allen 20 Fassungen und einen Verweis auf die deutsche Quelle.

Die Übersetzungen werden zentral in `assets/legal-locales/<Sprache>.json`
gepflegt. `operator.json` enthält die bestätigten Betreiberangaben einmal,
`languages.json` die Sprachadressen. `tools/render-legal-pages.py` erstellt
daraus die statischen Rechtsseiten, Fußzeilen, Sprachverweise und Sitemap.
Die obersorbische Einleitung verwendet zusätzlich `hsb-home.json` und ihre
HTML-Vorlage in `tools/templates/`. Generierte Rechtsseiten nicht einzeln
nachbearbeiten, da die nächste Erzeugung solche Änderungen ersetzen würde.

Nur die allgemeine Startadresse erkennt mit `navigator.languages` die
bevorzugte unterstützte Browsersprache und öffnet deren feste Adresse. Die
deutsche Fassung ist ausdrücklich unter `de/` erreichbar. Regionale Varianten
wie `de-CH` und `en-GB` werden ihrer verfügbaren Sprache zugeordnet; `no`
verweist auf Bokmål und chinesische Varianten auf die vorhandene vereinfachte
chinesische Fassung. Ohne passende Sprache bleibt Deutsch der Rückfall.
Feste Sprachadressen und Rechtsseiten werden nicht automatisch umgeleitet;
damit bleibt eine bewusste Auswahl auch bei erneutem Laden erhalten.
Die Auswahl benötigt weder Cookies noch Web Storage, einen Standortdienst
oder eine externe Übersetzungs-API. Ohne JavaScript bleibt die deutsche
Startseite samt direkten Sprachlinks nutzbar.

Allgemeine Website-Links, etwa in beiden README-Dateien, verweisen auf die
Startadresse ohne Sprachsuffix. `/en/`, `/de/` und `intl/<Sprache>/` sind für
die ausdrücklich gewählte Sprachfassung vorgesehen.

Das Favicon `assets/favicon-tray.svg` ist eine unveränderte Kopie des normalen
Organizer-/Tray-Symbols aus `magnolie-organizer/symbole/magnolie-organizer.svg`.
Alle Sprach- und Rechtsseiten verwenden diese Datei. Der separate Dateiname
verhindert die Weiterverwendung des alten Browser-Favicons aus dem Cache.
Die bisherige Blüte in `assets/favicon.svg` dient nur noch als Verzierung im
Zeitungskopf der Presseschau. Bei Änderungen am Produktzeichen die Kopie aus
der maßgeblichen Quelle erneuern.

Betreiberangaben ausschließlich aus bestätigten Angaben des Betreibers oder
eindeutig zugehörigen öffentlichen Projektquellen pflegen. Fehlende Angaben
werden nicht abgeleitet oder erfunden; unvollständige Entwürfe sind vor einer
Veröffentlichung zu ergänzen. Änderungen an Hosting, Kontaktwegen oder
eingebundenen Diensten müssen in der Datenschutzerklärung nachvollzogen werden.
Die technische Bereitstellung der Seiten ist kein Nachweis vollständiger
Rechtskonformität.

Quellen, bestätigte Anbieterangaben und Hinweise zur weiteren Pflege sind in
[WEBSITE-RECHT.md](WEBSITE-RECHT.md) dokumentiert.

## Änderungen und Veröffentlichung

Die nicht generierten HTML-, CSS- und JavaScript-Quellen direkt bearbeiten.
`index.html` bleibt die deutsche Hauptvorlage; daraus wird zusätzlich die
feste deutsche Sprachadresse erzeugt. Den Routing-Code in
`tools/templates/language.js` ändern; `assets/language.js` wird daraus erstellt.
Die Presseliste zugleich
in `docs/PRESSE.md` pflegen. In der Navigation aller Sprachseiten ist die
Presseschau verlinkt. Interne Links bleiben relativ, damit die Website sowohl
unter einer eigenen Domain als auch im Projektpfad funktioniert.

```sh
python3 tools/render-legal-pages.py
python3 tools/render-legal-pages.py --check
node tools/test-website-language.cjs
python3 tools/build-pages.py --output _site
```

Das Zielverzeichnis muss leer sein und außerhalb der kopierten Quellordner
liegen. Der Befehl kopiert ausschließlich die oben genannten Website-Dateien
sowie `docs/PRESSE.md`, `robots.txt`, `sitemap.xml`, `.nojekyll` und
`SOURCE-NOTICES.txt`. Er prüft lokale Seiten-, Medien- und Sprungmarkenlinks
und lehnt symbolische Links in den Eingabedateien ab.
Python 3.9 oder neuer genügt; die Pfadprüfung verwendet `Path.is_relative_to`,
das seit Python 3.9 verfügbar ist. Der gezielte Routingtest nutzt Node.js
und dessen Standardbibliothek; zusätzliche Pakete werden nicht benötigt.
Die Erzeugungsprüfung verhindert fehlende Übersetzungen, veränderte Linkziele
und Platzhalter sowie veraltete generierte Dateien. Der statische Build prüft
die lokalen Ziele einschließlich aller Sprach- und Rechtsseiten.

Der Workflow `.github/workflows/pages.yml` prüft Pull Requests und veröffentlicht
Änderungen auf `main` über GitHub Pages. Unter **Settings → Pages → Build and
deployment → Source** muss **GitHub Actions** gewählt sein. Nach erfolgreicher
Veröffentlichung ist die Startseite unter
`https://maik3531.github.io/Magnolie-Organizer/` erreichbar.

Für eine andere statische Hosting-Adresse:

```sh
python3 tools/build-pages.py --output _site --base-url https://example.org/magnolie/
```

Dies passt kanonische URLs, Sprachalternativen, Vorschaumetadaten, Sitemap
und Veröffentlichungstexte im Ausgabeordner an. Broschüren und das darin
enthaltene Medienpaket verweisen auf die zentrale GitHub-Pages-Adresse.
Der Teilen-Knopf teilt immer die aktuell besuchte Website-Adresse.

## GitLab-Links zur zentralen Website

Website und Presseschau werden ausschließlich in diesem GitHub-Repository
gepflegt und über GitHub Pages veröffentlicht. Die README-Dateien im bestehenden
GitLab-Projekt `maik3531/mint-forgs` verweisen direkt auf die zentralen Seiten:

- [Magnolie-Website mit Übersicht und Downloads](https://maik3531.github.io/Magnolie-Organizer/)
- [Magnolie-Presseschau](https://maik3531.github.io/Magnolie-Organizer/presse/)

Änderungen an Website, Medien und Presseliste erfolgen hier im GitHub-Repository.
Auf GitLab entfällt die bisherige separate `PRESSE.md`; dort bleiben die
README-Links als Einstieg erhalten. Ein zusätzliches Website-Archiv und eine
eigene GitLab-Pages-Pipeline werden nicht gepflegt.

Die gewöhnliche GitHub- oder GitLab-Repository-Adresse zeigt weiterhin die
Projekt- und Codeansicht. Sie lässt sich nicht durch Repository-Dateien zur
Website umleiten. Die Pages-Adresse öffnet unmittelbar die Website mit den
Downloadlinks.
