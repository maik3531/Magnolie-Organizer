# Magnolie Organizer – Handbuch (Quellpaket)

Das Benutzerhandbuch zum Magnolie Organizer, gestaltet wie das Programm
selbst: ein aufgeschlagenes Buch im Querformat. Diese Fassung ist das
Handbuch 2.0.4 für Magnolie Organizer 2.0.4.

## Aufbau

    bin/         Anzeigeprogramm (Python, GTK 3, WebKit2GTK)
    web/         Das Buch: index.html, stil.css, handbuch.js
                 und inhalt.js – darin steht der englische Ausgangstext
    po/          Gettext-Vorlage und vollständiger deutscher Katalog
    werkzeuge/   Katalogprüfung sowie Erzeugung von POT und Web-Katalog
    symbole/     Programmsymbol als SVG und in vier PNG-Größen
    pruefungen/  Selbsttest des Buches
    debian/      Paketbeschreibung für den Bau des .deb

## Den Text ändern

Der vollständige Handbuchtext liegt in `web/inhalt.js`. Jede Seite ist
ein Eintrag mit `kapitel`, `titel` und `inhalt`. Aus dem englischen Titel wird
ein stabiler `id`-Slug gebildet; für dauerhaft verlinkte Seiten wird `id`
ausdrücklich gesetzt. Interne Verweise verwenden `data-page`, nie Seitenzahlen.
Wer eine Seite ergänzt,
setzt `imInhalt: true`, damit sie im Inhaltsverzeichnis erscheint; mit
`imInhalt: "haupt"` wird der Eintrag hervorgehoben.

Nach Textänderungen erzeugt `python3 werkzeuge/pot_erzeugen.py` die Vorlage und
die Extraktionsmarken neu. `web/i18n/de.js` und die MO-Datei entstehen erst beim
Paketbau und gehören nicht in das Quellarchiv.

Die Seitenzahl ist nicht fest vorgegeben. Ausführlichkeit und Vollständigkeit
gehen vor einer bestimmten Blattzahl. Die Druckprüfung achtet darauf, dass kein
Text abgeschnitten wird und keine leeren PDF-Seiten entstehen.

## Paket bauen

    sudo apt install build-essential debhelper gettext nodejs node-jsdom \
      python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 poppler-utils
    dpkg-buildpackage -us -uc -b
    sudo apt install ../magnolie-handbuch_2.0.4_all.deb

## Prüfen

    python3 werkzeuge/pot_erzeugen.py
    while read sprache; do python3 werkzeuge/katalog_pruefen.py \
      po/magnolie-handbuch.pot po/$sprache.po; done < po/LINGUAS
    NODE_PATH=/pfad/zum/vorhandenen/node_modules bun pruefungen/handbuch_test.js
    python3 pruefungen/druck_test.py
    node pruefungen/paket_inhalt_test.js ../magnolie-handbuch_2.0.4_all.deb

`npm install` ist weder ein Quell- noch ein Prüfschritt. Unter Debian liefert
`node-jsdom` die Testabhängigkeit. Ist sie bereits in einem anderen Projekt
vorhanden, zeigt `NODE_PATH` auf dessen `node_modules`, ohne dieses Handbuch zu
verändern.

Die zweite Prüfung erzeugt die Druckfassung mit demselben GTK/WebKit wie das
Handbuchprogramm und benötigt zusätzlich `pdfinfo` und `pdftotext`.
Die Paketprüfung läuft erst nach dem Paketbau. Sie entpackt das gebaute DEB in
ein temporäres Verzeichnis und vergleicht SHA-256, Seitenzahl und Slug-Liste von
`web/inhalt.js` mit dem sauberen Quellbaum; eingecheckte Debian-Stagingdateien
werden dabei weder verwendet noch akzeptiert.

## Ohne Installation ausprobieren

    MAGNOLIE_HANDBUCH_WEB=$(pwd)/web python3 bin/magnolie-handbuch
