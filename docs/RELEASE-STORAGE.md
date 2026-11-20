# Schutz der GitLab-Releaseablage

Quellarbeit zu [Issue #698](https://github.com/maik3531/Magnolie-Organizer/issues/698)
und [Anschlussarbeit #707](https://github.com/maik3531/Magnolie-Organizer/issues/707).
Die bereinigten Git-/LFS-Historien dürfen durch neue Veröffentlichungen oder
alte Arbeitsklone nicht erneut anwachsen. Pro verwaltetem Programm bleibt nach
einem erfolgreich abgeschlossenen Wechsel genau eine veröffentlichte Version.

## Was diese Änderung absichert

`tools/release_git_guard.py` prüft jeden neu erreichbaren Git-Commit zwischen
einer vertrauenswürdigen Basis und dem zu veröffentlichenden Stand. Auch eine
Paketdatei, die nur in einem Zwischencommit existiert, wird erkannt. Neue
Paket-/Archivdateien, neue LFS-Pointer und neue Blobs über 5 MiB sind unzulässig.
Bereits vorhandene Einträge bleiben nur bei identischem Pfad, Modus und
Git-Objekt unverändert zulässig. Eine unvollständige Historie oder eine fremde
Basis beendet die Prüfung mit Fehler.

Der GitHub-Workflow `release-storage.yml` führt diese Prüfung und die gezielten
Speichertests aus. Er veröffentlicht keine Pakete, benötigt keine Zugangsdaten
und prüft auch Pull Requests. Ein CI-Ergebnis nach einem Push ersetzt keinen
Schutz vor einem GitLab-Push: Der vorhandene externe Publisher muss denselben
Guard vor seinem Push ausführen. Die Vertrauensbasis muss aus dem tatsächlich
bereinigten Zielrepository stammen. `HEAD` als selbst gewählte Basis würde
keinen neu eingebrachten Commit prüfen.

`tools/gitlab_release_storage.py` enthält den getrennten Registry-Ablauf.
Er erstellt zunächst ausschließlich lesend einen konkreten Plan. Der Plan
bindet Projekt, Branchstand, Paketname und Version, Dateigrößen und SHA-256,
die bisherigen Metadaten, die bisherigen Paket- und Datei-IDs und den
Speicherstand. Die Ausführung akzeptiert nur die exakte SHA-256 dieses Plans.
Diese Inhaltsbindung ist keine zusätzliche Produktfreigabe: Die vorhandene
Kandidaten-, Signatur- und native Abnahmeprüfung bleibt erforderlich.

## Reihenfolge und Fehlerverhalten

| Phase | Verhalten | Bei Abbruch |
|---|---|---|
| Plan | Vollständigen Bestand und Statistiken lesen, lokale Dateien prüfen, Reserven berechnen | Keine entfernte Änderung |
| Upload | Einen gebundenen Veröffentlichungszustand reservieren, fehlende Dateien in die Generic Registry laden | Bisherige Download-Metadaten und aktuelle Pakete bleiben erhalten |
| Prüfung | Dateimenge, eindeutige Namen, Status, Größe und SHA-256 prüfen; neue Dateien anonym vollständig herunterladen | Keine Aktivierung oder Altpaketlöschung |
| Aktivierung | Alle im Plan aufgeführten Metadaten und den Releasezustand in einem GitLab-Commit ändern und zurücklesen | Unklare Commitantwort wird anhand des tatsächlichen Zustands aufgelöst |
| Bereinigung | Ausschließlich die vorher erfassten alten Paket-IDs nach erneutem Zustands- und Inhaltsvergleich löschen | Neue Version bleibt aktiv; derselbe Plan kann fortgesetzt werden |
| Abschluss | Genau eine verwaltete Version nachweisen, Statistik erneut lesen, Zustand freigeben | Angeforderte Löschungen und gemeldete Speicherwerte bleiben getrennt |

Die kleine öffentliche Zustandsdatei `release-storage/state.json` besitzt je
Paketname einen eigenen aktuellen Stand. Ihr letzter Änderungscommit wird bei
jedem Schreibschritt über GitLabs `last_commit_id` verglichen. Alle
Aktivierungsmetadaten werden zusammen mit dieser Zustandsdatei geschrieben;
`force` wird nicht verwendet. Auch der aktuelle Branchstand wird geprüft.

Eine private Ausführungskennung unterscheidet zwei Aufrufe desselben Plans.
Ein anderer Lauf darf eine laufende Veröffentlichung nicht übernehmen. Der
öffentliche Zustand enthält nur den SHA-256-Abdruck dieser Kennung. Der
lokale Abschlussbericht hält die Kennung für einen Wiederanlauf fest; eine
Dateisperre verhindert gleichzeitige lokale Aufrufe mit demselben Bericht.
Ein anderer Rechner darf diese private Kennung nicht gleichzeitig verwenden.
Es gibt kein automatisches Ablaufen oder gewaltsames Übernehmen einer Sperre.
Alle beteiligten Publisher müssen diesen Ablauf verwenden. GitLabs Paket-API
stellt keine atomare Transaktion über Git-Commits und Paketlöschungen bereit;
beliebige parallele manuelle Administratoränderungen lassen sich dadurch
nicht vollständig ausschließen.

Ein unbekannter Altbestand unter demselben Paketnamen wird nicht automatisch
übernommen oder gelöscht. Bereits verwaltete Metadatendateien dürfen beim
Folgerelease nicht aus dem Plan verschwinden. Metadaten eines anderen Kanals
werden nicht verändert. Der Paketname `magnolie-desktop` ist von
`magnolie-notes-fdroid-reference` getrennt. Aktive externe Referenzen sind vor
einer Übernahme eines weiteren Kanals konkret zu prüfen.

## Grenzen und Speicherberechnung

Die Aufbewahrungsregel gilt je verwaltetem Paketnamen. Damit bleiben etwa
separate Programmvarianten und Notes-Referenzpakete unabhängig von einer
Desktopversion erhalten. Ein erfolgreicher Folgerelease entfernt seinen
unmittelbaren verwalteten Vorgänger; es wird keine pauschale zusätzliche
Vorgängerversion behalten. Unvollständige Uploads bleiben bei einem Abbruch
für den gebundenen Wiederanlauf liegen, ohne zu aktuellen Downloads zu werden.

Die voreingestellten Betriebsgrenzen sind 10 GiB für Git plus LFS mit
512 MiB Reserve, ein separates Registry-Budget von 10 GiB mit 512 MiB Reserve
und höchstens 2 GiB pro Veröffentlichung. Das Registry-Budget ist eine eigene
Betriebsentscheidung, **keine behauptete GitLab.com-Registry-Quota**.
Neue Registry-Binärdateien werden nicht als Git-Zuwachs gezählt; neue kleine
Metadaten und Zustandscommits werden dagegen berücksichtigt. Fehlende oder
ungültige Statistikwerte werden niemals durch null ersetzt.

Der Bericht trennt geplante Paket-IDs, bestätigte Löschanforderungen, bestätigte
Abwesenheit, Objektbytes und anschließend von GitLab gemeldete Statistik.
`physical_freed_bytes` bleibt ausdrücklich unbekannt. GitLab aktualisiert
Speicherstatistiken verzögert; ein HTTP-204-Löschresultat ist kein Messwert für
physisch freigegebene Serverbytes.

## Anschluss an die bestehende Produktfreigabe

`release_gate.py prepare-storage` verwendet dieselbe Kandidatenprüfung,
native Freigabe, Signaturprüfung und Prüfsummenerzeugung wie der vorhandene
lokale Promotion-Schritt. Es exportiert ein vollständig gebundenes
Registry-Kandidatenverzeichnis außerhalb der Produktquelle. Der veröffentlichte
Bootstrap und die Dateien im Quellverzeichnis werden dabei nicht geändert.
Ein `storage_candidate_check` prüft den Export erneut gegen den genehmigten
Kandidaten, seine abgeleiteten Dateien und die exakt signierten Registry-URLs.

Der CLI-Adapter des Speicherwerkzeugs verwendet diese echte Magnolie-Prüfung.
Er bindet das signierte `update.xml` an den tatsächlichen Pfad
`Magnolie-Organitzer/update.xml`; Prüfsummen oder andere Dateien können nicht
als Update-Manifest eingesetzt werden. Weitere Dateien behalten ihren
verifizierten Namen innerhalb dieses Verzeichnisses.
Die Kernfunktionen können auch die übrigen sechs in #698 erfassten Projekte
verarbeiten; sie verlangen dafür ausdrücklich deren eigenen Freigabe-Callback.
Der Magnolie-CLI-Adapter gibt keine fremden Programme frei. Private
Freigabeprotokolle, Zugangsdaten und konkrete Betriebsbefehle bleiben außerhalb
des öffentlichen Repositorys.

**Ein vorbereiteter Registry-Kandidat ist keine aktivierte Migration.** Der
bisherige private GitLab-Publisher und das in `AGENTS.md` referenzierte private
Betriebsprotokoll waren in dieser Arbeitsumgebung nicht vorhanden. Ihre
Aufrufstellen müssen den neuen Ablauf übernehmen; der Quellpatch allein
installiert keinen serverseitigen GitLab-Hook.

## Vorbereiteter Übergang der Updateprogramme

Die Windows- und Linux-Quellen akzeptieren zusätzlich zu den bisherigen
Raw-Paketadressen ausschließlich diesen Generic-Registry-Kanal:

`https://gitlab.com/api/v4/projects/78301901/packages/generic/magnolie-desktop/<Releaseversion>/<Dateiname>`

Projekt-ID, Paketname, Version und vollständiger Dateiname müssen exakt passen.
Eine andere Projekt-ID, ein anderer Kanal, eine andere Versionsablage,
zusätzliche Pfadbestandteile, URL-Kodierungen, Query, Fragment, Zugangsdaten
oder ein abweichender Port werden nicht als gleichwertiges Ziel behandelt.
Es gibt keine allgemeine Freigabe von GitLab-URLs. Für Linux-Handbücher mit
eigener Handbuchversion bleibt der Dateiname an diese signierte Version
gebunden; der Registry-Ordner gehört zur signierten Desktop-Releaseversion.

| Bezug | Bindung |
|---|---|
| Update-Manifest | Unverändert `https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/update.xml` |
| Organizer-DEB | `magnolie-organizer_<Version>_all.deb` |
| AppImage | `Magnolie-Organizer-<Version>-x86_64.AppImage`, Architektur `x86_64` |
| Windows-Installer | `Magnolie-Organizer-Windows-<Version>-Setup-x64.exe` |
| Linux-Handbuch | `magnolie-handbuch_<Handbuchversion>_all.deb` |

Die Paketadressen bleiben Teil der Ed25519-signierten Nachricht. Das bloße
Umschreiben eines gültigen Raw-Manifests auf Registry-Adressen macht seine
Signatur ungültig. Beim Download bleiben SHA-256, Größenbegrenzung und die
Bindung an die exakt zuvor geprüfte Adresse maßgeblich. Auch eine Weiterleitung
von einer erlaubten Raw-Adresse zu einer erlaubten Registry-Adresse ist kein
zulässiger Ersatz für die signierte Adresse.

Diese Quelländerung ist eine Vorbereitung für neu gebaute Clients. Bereits
installierte ältere Clients akzeptieren weiterhin nur ihre bisherigen
Raw-Paketadressen. Ein späteres Umschalten des gemeinsam verwendeten Manifests
auf Registry-Adressen würde deren automatische Aktualisierung blockieren,
auch wenn zwischenzeitlich eine kompatible Clientversion angeboten wurde.
Lange ausgeschaltete Geräte können diese Zwischenversion verpasst haben.

Vor einer Aktivierung muss deshalb ein konkreter Übergang einschließlich
solcher Altclients abgenommen sein. Die Quelländerung entscheidet weder über
ein Supportende alter Clients noch über dauerhaft zusätzlich aufzubewahrende
Brückenpakete. Sie ändert keine veröffentlichte Manifestdatei, erzeugt keine
neue Versionsnummer und ersetzt keine native Installations- oder Updateprüfung.
Der vorhandene Windows-Manifestvorbereitungsschritt bleibt beim bisherigen
Raw-Kandidaten; erst `prepare-storage` erzeugt und signiert den gesonderten
Registry-Export nach der bestehenden Freigabeprüfung.

## Noch erforderlicher Produktivanschluss

Vor der ersten Live-Aktivierung müssen die tatsächlich verwendeten
Download-Metadaten vollständig in den Plan aufgenommen und ihre Bedeutung
gegen den freigegebenen Satz geprüft werden. Insbesondere:

- Den oben beschriebenen Übergang mit bereits installierten Windows- und
  Linux-Clients einschließlich ausgelassener Zwischenversionen nachweisen.
- Die stabilen Notes- und QR-Bezugswege sowie die F-Droid-Referenz sind
  eigenständige Abhängigkeiten. Ein Desktopmanifest löst diese nicht ab.
- APT-Pool, `Packages`, `Release`, `InRelease`, Signaturen und By-hash-Verweise
  benötigen einen zusammenhängend geprüften Übergang. Die private
  APT-Erzeugung gehört nicht zum hier vorhandenen öffentlichen Bauablauf.
- Der Transport verweigert Redirects und verlangt echte anonyme Downloads.
  Falls GitLab für ein Ziel eine Object-Storage-Weiterleitung benötigt,
  stoppt die Veröffentlichung. Das ist vor einer Freigabe konkret zu prüfen;
  beliebige weitere Hosts werden nicht automatisch zugelassen.

Es wird deshalb keine fertige Produktions-Metadatenzuordnung aus Namen oder
alten Links geraten. Der neue Quellstand baut keine Produktpakete, erzeugt
keine nativen Prüfnachweise und veröffentlicht keine neue App-Version.

## Gezielt überprüfbare Eigenschaften

Die Tests verwenden temporäre echte Git-Repositories beziehungsweise eine
synthetische GitLab-Gegenstelle mit Commitbedingungen und Dateiinventaren.
Sie prüfen Veröffentlichung und Wiederanlauf, Teiluploads, falsche Hashes,
Duplikate, fremde Projekte, veränderte Pläne und Metadaten, neue Ausführungen
während einer laufenden Veröffentlichung, Pagination, fehlende Statistiken,
Reserveüberschreitungen und Fehler während der Bereinigung. Diese Prüfungen
belegen die Quelllogik; sie ersetzen weder einen Live-GitLab-Durchlauf noch
native Update- und Paketabnahmen.

Zusätzlich prüfen die Update-Tests die engen Raw-/Registry-Adressgrenzen,
Signaturbindung, unveränderten Manifestbezug und abgewiesene Umleitungen.
Ein Integrationstest übergibt einen mit einem flüchtigen Testschlüssel
signierten echten `prepare-storage`-Export an den Linux-Manifestvalidator.
Der Windows-Job verwendet die vorhandenen portablen `CoreTests` mit der
Update-Testgruppe. Ein erfolgreicher Lauf unter Linux belegt keine native
Windows-Installation, Authenticode-Abnahme oder Bedienprüfung.

## API-Grundlagen

- [GitLab Generic Packages](https://docs.gitlab.com/user/packages/generic_packages/)
- [Packages API](https://docs.gitlab.com/api/packages/)
- [Repository Files API](https://docs.gitlab.com/api/repository_files/)
- [Commits API](https://docs.gitlab.com/api/commits/)
- [Projects API und Statistiken](https://docs.gitlab.com/api/projects/)
- [GitLab.com-Speichergrenzen](https://docs.gitlab.com/user/storage_usage_quotas/)

GitLabs eingebaute Generic-Package-Cleanup-Regeln ersetzen diese
Versionsaufbewahrung nicht: Sie behandeln doppelte Dateien, nicht pauschal alle
vorherigen Versionen eines Programms.
