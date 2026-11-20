# Magnolie-Projektwebsite

Die vollständige Website liegt im bestehenden Magnolie-Organizer-Repository.
`index.html` ist die Startseite; `presse/index.html` enthält die Presseschau.
Die Ordner `en/` und `intl/` enthalten die weiteren Sprachseiten, `assets/`
die Gestaltung und Produktbilder und `media/` sämtliche Videos, Untertitel,
Broschüren und das Medienpaket. Die Website benötigt nur einen statischen
Webserver und keine ChatGPT-Dienste, API-Schlüssel oder JavaScript-Pakete.

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

## GitLab-Veröffentlichung

Ziel ist derselbe vollständige Websitebestand direkt im bestehenden
GitLab-Projekt `maik3531/mint-forgs`: `index.html`, `assets/`, `en/`, `intl/`,
`media/`, `presse/`, die begleitenden Website-Dateien und das gleiche Buildskript
`tools/build-pages.py`. Änderungen an der Website und der Presseliste werden
in beiden Repositories gemeinsam nachgeführt. Die Website beginnt an der
Wurzel ihrer Pages-Adresse.

Die vorbereitete `.gitlab-ci.yml` verwendet ausschließlich den jeweiligen
GitLab-Commit. Sie paketiert die eigenen Dateien mit Python aus dessen
Standardbibliothek und der tatsächlichen GitLab-Pages-Adresse:

```sh
python3 tools/build-pages.py --output public --base-url "$CI_PAGES_URL"
```

Der Ordner `public/` ist dabei nur das erzeugte Veröffentlichungsartefakt.
Die Website wird aus den unmittelbar im GitLab-Projekt gepflegten Dateien
bereitgestellt; für ihren Betrieb sind keine Abrufe von GitHub oder ChatGPT
erforderlich. Verweise auf Projektquellen, Downloads und externe Presseartikel
bleiben gewöhnliche ausgehende Links.

Die Pipeline veröffentlicht `public/` über GitLab Pages bei Änderungen der
Website auf dem Standardbranch; sie kann auch über die GitLab-Weboberfläche
gestartet werden. Die Übernahme der Dateien in das bestehende Projekt, die
Runner-Verfügbarkeit und die endgültige Pages-Adresse müssen noch bestätigt
werden. Erst ein erfolgreicher GitLab-Pages-Lauf und der Aufruf der
veröffentlichten Seiten belegen die dortige Veröffentlichung.

Die gewöhnliche GitHub- oder GitLab-Repository-Adresse zeigt weiterhin die
Projekt- und Codeansicht. Sie lässt sich nicht durch Repository-Dateien zur
Website umleiten. Die Pages-Adresse öffnet unmittelbar die Website mit den
Downloadlinks.
