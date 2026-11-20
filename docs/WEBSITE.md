# Magnolie-Projektwebsite

Die vollständige Website liegt im bestehenden Magnolie-Organizer-Repository.
`index.html` ist die Startseite; `presse/index.html` enthält die Presseschau.
Die Ordner `en/` und `intl/` enthalten die weiteren Sprachseiten, `assets/`
die Gestaltung und Produktbilder und `media/` sämtliche Videos, Untertitel,
Broschüren und das Medienpaket. Die Website benötigt nur einen statischen
Webserver und keine ChatGPT-Dienste, API-Schlüssel oder JavaScript-Pakete.

## Zentrale Rechtsseiten

`impressum/index.html` und `datenschutz/index.html` enthalten die zentralen
deutschsprachigen Rechtsseiten. Sie sind in den Fußzeilen aller Sprachseiten
und der Presseschau über relative Links erreichbar. Englische Linkzusätze
helfen auf den internationalen Seiten bei der Orientierung.

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

HTML-, CSS- und JavaScript-Dateien direkt bearbeiten. Die Presseliste zugleich
in `docs/PRESSE.md` pflegen. In der Navigation aller Sprachseiten ist die
Presseschau verlinkt. Interne Links bleiben relativ, damit die Website sowohl
unter einer eigenen Domain als auch im Projektpfad funktioniert.

```sh
python3 tools/build-pages.py --output _site
```

Das Zielverzeichnis muss leer sein und außerhalb der kopierten Quellordner
liegen. Der Befehl kopiert ausschließlich die oben genannten Website-Dateien
sowie `docs/PRESSE.md`, `robots.txt`, `sitemap.xml`, `.nojekyll` und
`SOURCE-NOTICES.txt`. Er prüft lokale Seiten-, Medien- und Sprungmarkenlinks
und lehnt symbolische Links in den Eingabedateien ab.
Python 3.9 oder neuer genügt; die Pfadprüfung verwendet `Path.is_relative_to`,
das seit Python 3.9 verfügbar ist. Zusätzliche Pakete werden nicht benötigt.

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
