# #820 – Linux-Sprachkataloge nach #813/#814 vollständig halten

## Bestätigter Ausgangsstand

Geprüfte Basis: `63ca6c8f351dd52627dfc550ff0075e703957ab5`.
Die geschlossenen Issues #813 und #814 wurden anhand ihrer aktuellen Quellen
und Prüfungen nachgeprüft; ihr Status wurde nicht als Fehlerfreiheit gewertet.

Der erreichbare Bereich für lokale Medienwiederherstellung verwendet seit
#814 den Schlüssel `Restore media`. Nur Deutsch enthält ihn. In den anderen
18 nichtenglischen Katalogen fällt diese Überschrift auf Englisch zurück.
Der vorhandene deutsche Eintrag fehlt zugleich in der Linux-POT-Vorlage.

Die vollständige kanonische Extraktion findet außerdem vier fehlende Texte
des privaten GTK-Dialogs für eine bestätigte GIF-Auswahl. Zwei weiterhin
benötigte bedingte Vorhersagetexte werden ohne explizite Extraktionsmarker
nicht gefunden. Zwei alte Vorhersagetexte werden dagegen nicht mehr verwendet.
Die Windows-Korrektur aus #813 hatte diese Vorhersagebereinigung bereits für
den dortigen Katalog durchgeführt; der Linux-Katalog war nicht mitkorrigiert.

Vor der Korrektur: vorhandene Linux-Katalogsuite **7 bestanden, 2 fehlgeschlagen**
(PO/POT-Schlüsselmenge und deterministische Quellabdeckung). Die ergänzte
Medienregression scheitert bereits am fehlenden arabischen Wiederherstellungstext.

## Korrektur

- Alle 19 Linux-Sprachkataloge erhalten die vier fehlenden GTK-Quelltexte;
  die 18 fehlenden Wiederherstellungsübersetzungen werden exakt aus den
  vorhandenen Windows-Katalogen übernommen. Das sind **94 neue Übersetzungen**.
- Zwei aktive bedingte Vorhersagetexte erhalten dieselben expliziten
  Extraktionsmarker wie unter Windows. Ihre vorhandenen Übersetzungen bleiben.
- Die beiden nicht mehr verwendeten Vorhersagetexte werden aus Vorlage und
  Katalogen entfernt. Alle übrigen bestehenden Übersetzungen sind unverändert.
- Die Linux-POT wird mit dem vorhandenen Generator neu erzeugt. MO und JS
  werden unverändert mit den vorhandenen Bauwerkzeugen daraus abgeleitet.
- Die Medienregression prüft den tatsächlich aufgebauten Offline-Bereich in
  allen 19 nichtenglischen Sprachen. Die neue Python-Prüfung kontrolliert die
  vier GTK-Übersetzungen und ihre Zahlenplatzhalter im echten MO-Katalog.

## Prüfnachweis

Mit GNU gettext 0.23.1, Python 3.12 und Node.js/jsdom 26.1.0:

```sh
python3 -m pytest -q magnolie-organizer/pruefungen/test_locale_completeness.py
node magnolie-organizer/pruefungen/media-trash-ui.cjs
git diff --check
```

Zuvor müssen die regulären Linux-/Windows-Webkataloge, Linux-MO-Kataloge und
die normativen Zeitzonendaten mit den bestehenden Quellgeneratoren erzeugt sein.
Sie sind abgeleitete Bauausgaben und gehören nicht zum Quellpatch.

- **10 Python-Testgruppen bestanden:** alle 19 Kataloge, technische Kennungen,
  Platzhalter, deterministische vollständige Quellabdeckung und bytegleiche
  PO→MO/JS-Ableitungen.
- **39 Frontend-/Sprachfälle bestanden**, einschließlich der neuen 19 realen
  DOM-Überschriften und der vorhandenen Medien-, Vorschau-, Sperr-, Fehler- und
  Windows-Abgrenzungsfälle. Zusätzlich werden alle 19 Sprachkataloge geprüft.
- Alle unverändert benötigten Übersetzungen gegen die Ausgangsbasis verglichen:
  **keine inhaltliche Änderung**, nur 94 neue und 38 entfernte obsolete Einträge.
- `git diff --check` ohne Fehler.

## Grenzen und Übergabe

Die Frontendprüfung verwendet die tatsächlichen Quellen mit synthetischer
nativer Brücke. Sie ist keine Abnahme installierter Linux-/Windows-Pakete.
Die neue GTK-Prüfung ist eine Katalogprüfung, keine native Dialogbedienung.
Der private GIF-Helfer und seine produktive Einbindung bleiben bei #337;
dieser Patch erteilt keine Datei- oder Gerätefreigaben und ändert keine
Medienoperationen. Mac-/Tablet-Pakete und sprachliche Muttersprachlerabnahmen
werden hier nicht als geprüft behauptet.

Vor Übernahme auf einen späteren Stand die fünf Quelltexte und die beiden
Marker erneut abgleichen, danach die vorhandenen Kataloggeneratoren und die
oben genannten Tests ausführen. Das Issue bleibt bis zur tatsächlichen
Quellübernahme offen.
