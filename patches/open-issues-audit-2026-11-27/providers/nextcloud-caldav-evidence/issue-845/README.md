> **Historischer Alternativpatch – nicht auf die aktuelle Basis anwenden.**
> Die ursprüngliche Nextcloud-BDAY-Erkennung wurde unabhängig in `7a490dd8` übernommen.
> `8d7263fd` und sein Initialpatch bleiben als geprüfter früherer Vorschlag erhalten.
> Aktuell maßgeblich sind `upstream-adoption.json` und der enge Folgepatch unter `upstream-remainder/`.
> Dessen Restumfang ist Linux-DAV-Scope plus Bedeutungserhalt der Februarregel bei Typ-/Jahresänderung.

# #845: explizite Nextcloud-Geburtstage

**Prüfbarer Folgepatch `8d7263fda398f7ee0cbe6b9f5b7bab3e9d6c5f5a` auf #844-Commit `a64624071e700920907bcab7dd14d62fc93e0b9a`.**
Tree: `8a18f65ab50d4e9125b3ffd086ccab7066fc053f`. Der Patch ist eine getrennte Quelllieferung; keine Main-/Paket-/Serverfreigabe.

## Bestätigter Fehler und Umfang

Beide ursprünglichen Desktopcodecs verstehen Magnolie-Typmarker, erkennen aber Nextclouds ausdrückliches `X-NEXTCLOUD-BC-FIELD-TYPE:BDAY` nicht. Echte Nextcloud-BirthdayService-Daten erscheinen daher als jährlicher Termin. Bei fehlendem Geburtsjahr darf der technische DTSTART-Anker 1970 oder1972 nicht zum tatsächlichen Geburtsjahr werden.

Die maßgebliche [Nextcloud-Primärquelle](https://github.com/nextcloud/server/blob/1ab09ec753f106661beadee1794b390ebec455dd/apps/dav/lib/CalDAV/BirthdayService.php) trennt UNKNOWN-YEAR0/1 und ein bekanntes ursprüngliches BC-YEAR. Der29.Februar wird mit `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1` erzeugt. Das entspricht dem vorhandenen Magnolie-Jahrestag auf dem28.Februar eines Nichtschaltjahrs. Eine gewöhnliche `FREQ=YEARLY`-Februar29-Serie hat eine andere Bedeutung und wird deshalb nicht allein wegen des Datums promoted.

Der Patch ergänzt eine ausdrücklich markierte und konservativ geprüfte BDAY-Erkennung. Datum, ganztägige Ein-Tages-Dauer, Jahresmarker und unbeschränkte passende Jahresregel müssen zusammenpassen. Bekanntes Datum vor1970 bleibt bekannt; vorhandene widersprüchliche BC-YEAR-/UNKNOWN-YEAR-Kombinationen bleiben als roher Termin erhalten. DEATHDATE, ANNIVERSARY, bloße Titel/Kategorien und gewöhnliche jährliche Termine werden nicht in Geburtstage umgedeutet. Eigene ausdrückliche andere Typen behalten Vorrang.

Export und erneuter Import behalten den technischen Nextcloud-Anker, die echte Jahreslosigkeit und die Februar-Monatsende-Regel. Bei Änderung des Datums/Jahres werden die bekannten NC-Marker konsistent aktualisiert. Bei bewusster Änderung des Typs werden genau diese drei alten Birthday-Marker entfernt; es wird kein neuer Nextcloud-Typ geraten. Die ursprüngliche Monatsende-Regel bleibt auch nach einem weiteren Export erhalten. UID, Text, fremde Eigenschaften, verschachtelte Alarmdaten und die vorhandene Farbsemantik bleiben erhalten.

Eine separat gespeicherte RECURRENCE-ID-Komponente gleicher UID verhindert die Vereinfachung des Masters zu einem ausnahmslosen Jahrestag. Die gesamte Serie bleibt im Ereignis-/Ausnahmenpfad, unabhängig von der Reihenfolge der Komponenten. Linux nutzt seine vorhandene Serienklassifikation; C# stimmt die betroffenen typisierten Kandidaten vor der bestehenden Ereignisabstimmung ab.

## Tatsächlich ausgeführte Prüfungen

| Stand und Prüfung | Ergebnis |
|---|---|
| Final identische Python-Testbytes auf sauberer Produktbasis a6462407 |21Fehler,23bestanden; fehlende NC-Typklassifikation und fehlender Schutz für diesen neuen Scope sichtbar |
| Final identische C#-Gruppe auf a6462407 |rot am ersten tatsächlichen Geburtstagstypkriterium; Build erfolgreich |
| Patch: neue Pythonfälle plus bestehender Jahrestags-Scopevertrag |44/44bestanden |
| Patch: C# Nextcloud explicit birthday markers / year / recurrence / roundtrip |1/1Gruppe bestanden |
| Patch: drei vorhandene C#-Farbgruppen |3/3bestanden |
| Unabhängige tatsächliche Python-Payloads in beiden Desktop-DOMs |4/4bestanden nach identischer0/4Basis;2027/2028, Jahr/Alter, Farbe, Speichern/Reload |
| Unabhängige konkrete Reviewgrenzen |2/2bestanden: separate Ausnahme, Typänderung |

Der gemeinsame Korpus enthält21synthetische ICS-Vektoren:7gültige BDAY-Muster und14gewöhnliche, mehrdeutige oder nicht vereinfachbare Gegenfälle. Python ergänzt5Datums-/Jahresänderungen,2Typprioritätsfälle,2Typänderungen und7Linux-DAV-Schutzfälle. Dazu kommen7bestehende Scopefälle. C# prüft dieselben21Vektoren und dieselben9Edit-/Typprioritätsfälle. Eine C#-Gruppe zählt als Gruppe, nicht als30unabhängige native Testläufe.

Die neuen Python-/C#-Codecprüfungen verwenden JSON-Datenpersistenz als gezielten Übergang. Sie sind keine neue native verschlüsselte Buch-/Kontenabnahme. Die unabhängigen vier DOM-Prüfungen verwenden die tatsächlichen Python-Payloads; daraus wird keine zusätzliche C#→DOM-Ausführung abgeleitet. Die beiden echten Codecprüfungen und die Frontendfälle sind getrennt belegt.

## Befehle, Quelldateien und Reproduzierbarkeit

`baseline-final-manifest.json` und `final-manifest.json` enthalten sämtliche genauen argv, cwd, Umgebungsvariablen, Dauer, Exitcodes und Eingangsdateihashes. Beide Enden verwenden identische neue Tests/Fixtures. Die ältere erste Baseline bleibt historisch erhalten; ihre Farbfixture-Annahme wurde vor dem final identischen Vergleich korrigiert. Maßgeblich ist der finale Vergleich.

Python auf dem jeweiligen Checkout:

```sh
PYTHONPATH="$PWD/magnolie-organizer/bin" /workspace/scratch/7203da5bd564/round3-tools/python/bin/python -m pytest -q magnolie-organizer/pruefungen/test_nextcloud_birthday_markers.py magnolie-organizer/pruefungen/test_nextcloud_anniversary_scope.py
```

C# nach vorhandener locked restore/build, Arbeitsverzeichnis `magnolie-organizer-windows`:

```sh
/workspace/scratch/7203da5bd564/round3-tools/dotnet/dotnet run --project tests/CoreTests.csproj --no-build --configuration Debug -- "Nextcloud explicit birthday"
/workspace/scratch/7203da5bd564/round3-tools/dotnet/dotnet run --project tests/CoreTests.csproj --no-build --configuration Debug -- "Category colors"
```

Die exakten DOTNET_CLI_HOME-/NUGET_PACKAGES-Werte stehen im Manifest. Die vorhandene gepinnte Toolchain wurde wiederverwendet. Das unabhängige Review einschließlich seiner Originalbefehle steht in `independent-final-review.json` und den zugehörigen Display-/Grenzdateien.

## Bewusst offene Integration

**#441 bleibt offen:** Linux unterstützt noch keinen vollständigen typisierten Jahrestags-Sync mit Quelle/UID/ETag, Baselines, Konflikten und Löschungen. Der bestehende Vorab-Schutz umfasst jetzt auch die neu korrekt erkannten Nextcloud-BDAY-Ressourcen. Dadurch wird kein Jahrestag still aus dem Termin-Sync ausgelassen und kein falscher vollständiger Erfolg gemeldet. Für diesen ausgewählten Scope ist weiterhin eine explizite Ablehnung möglich. Die vollständige Syncintegration wurde nicht nachgebaut.

**#683 bleibt offen:** Echte Server-/Rechte-/Offline-/Konflikt-/Neustart-/Buch-/Journalabnahme sowie Mac-/Tablet-Portkoordination folgen ihren vorhandenen Kriterien. Keine realen Konten, Server oder Nutzerbücher wurden in diesen Prüfungen benutzt. Vorhandene fehlende gi/GLib- und Named-Pipe-Bedingungen aus dem separaten DAV-Audit werden nicht als bestanden umgedeutet.

Das Formatpatch ist ausschließlich für den angegebenen Parent beziehungsweise für eine geprüfte Integration der davorliegenden #844-Folge vorgesehen. Spätere Upstream-Übernahmen müssen vor erneuter Anwendung berücksichtigt werden.
