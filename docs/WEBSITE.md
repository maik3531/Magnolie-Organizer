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

Im bestehenden GitLab-Projekt `maik3531/mint-forgs` wird der vollständige
Websitebestand als `Magnolie-Webseite.zip` gepflegt. Die Archivwurzel beginnt
unmittelbar mit `index.html`, `assets/`, `en/`, `intl/`, `media/` und `presse/`;
auch das Buildskript und die zugehörigen Website-Dokumente sind enthalten.
Auf GitHub bleiben dieselben Website-Dateien einzeln an der Repository-Wurzel
bearbeitbar. Änderungen an der Website, den Medien und der Presseliste werden
bei der Aktualisierung des GitLab-Archivs gemeinsam übernommen.

Die für das bestehende GitLab-Projekt bestimmte Pipeline ist unter
[`tools/gitlab-pages.yml`](../tools/gitlab-pages.yml) dokumentiert und wird
dort als `.gitlab-ci.yml` verwendet. Sie entpackt ausschließlich das Archiv
aus dem jeweiligen GitLab-Commit und baut es mit der eigenen Pages-Adresse:

```sh
python3 -m zipfile -e Magnolie-Webseite.zip .website-source
python3 .website-source/tools/build-pages.py --output public --base-url "$CI_PAGES_URL"
```

`.website-source/` und `public/` sind temporäre Arbeits- beziehungsweise
Ausgabeordner der Pipeline. Die ausgelieferte Startseite liegt direkt an der
Wurzel der GitLab-Pages-Adresse. Alle Website-Dateien und Medien werden von
GitLab ausgeliefert; für den Websitebetrieb sind keine Abrufe von GitHub oder
ChatGPT erforderlich. Verweise auf Projektquellen, Downloads und externe
Presseartikel bleiben gewöhnliche ausgehende Links.

Die `.gitlab-ci.yml` in der GitHub-Quelle beschreibt zusätzlich den direkten
Bau aus einzelnen Quelldateien. Für die Archivablage im bestehenden GitLab-
Projekt ist dagegen `tools/gitlab-pages.yml` maßgeblich. Beide Varianten
verwenden dasselbe Buildskript und prüfen lokale Links vor der Veröffentlichung.

Die Pipeline veröffentlicht `public/` bei Änderungen von Archiv oder
CI-Konfiguration auf dem Standardbranch und kann dort auch über die GitLab-
Weboberfläche gestartet werden. Runner-Verfügbarkeit, endgültige Pages-Adresse
und erfolgreiche Veröffentlichung müssen noch am GitLab-Projekt bestätigt
werden. Erst ein erfolgreicher Pages-Lauf und der Aufruf der veröffentlichten
Seiten belegen den Live-Stand.

Die gewöhnliche GitHub- oder GitLab-Repository-Adresse zeigt weiterhin die
Projekt- und Codeansicht. Sie lässt sich nicht durch Repository-Dateien zur
Website umleiten. Die Pages-Adresse öffnet unmittelbar die Website mit den
Downloadlinks.
