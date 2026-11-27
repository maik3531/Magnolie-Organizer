# Issue #828 — Portugiesisches „No“ berichtigen

In beiden Desktop-Katalogen steht für den aktuellen gettext-Schlüssel `No`
noch `msgstr "No"`. Die portugiesische Verneinung lautet `Não`. Der Patch ändert
diese beiden Übersetzungswerte und den daraus erzeugten, bereits versionierten
Windows-JS-Katalog. Sonstige Nachrichten bleiben unverändert.

Der Fehler wurde in beiden tatsächlichen Weboberflächen mit der vorhandenen
Desktop-Regressionsfixture reproduziert: Sprache `pt`, initialisierte
Anwendung, Gerätestatusdialog über `OrganizerTest.oeffneGeraeteDialog`,
synthetischer Status mit `online: true`, `network_validated: false` und
`network_metered: false`. Vor der Änderung zeigen beide Statusfelder `No` an;
nach kanonischer Katalogerzeugung zeigen beide Oberflächen in beiden Feldern
`Não`. Der gleiche gettext-Schlüssel wird auch bei der Linienauswahl in
Seitenvorlagen verwendet.

Die allgemeine Abbrechen-Schaltfläche verwendet den getrennten Schlüssel
`Cancel`; ihre korrekte Übersetzung `Cancelar` wird nicht geändert.

Geprüft mit den jeweiligen `werkzeuge/po_zu_js.py`, deren
`msgfmt --check --check-format`-Prüfung und tatsächlichem jsdom-Gerätedialog.
Beide Desktop-Durchläufe sind erfolgreich; `git diff --check` ist sauber.
Der ignorierte Linux-JS-Katalog wurde ebenfalls frisch erzeugt. Native
GTK-/WebView2-Pixel wurden nicht geprüft.
