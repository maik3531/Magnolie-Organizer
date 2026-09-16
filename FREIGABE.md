# Desktop-Freigabe

Diese Checkliste hält den auf diesem Rechner verwendeten Ablauf fest. Private
Schlüssel, Zertifikate und der konkrete Contributor-Hash gehören nicht in das
Repository.

## Voraussetzungen

- GitHub-Zugang: `gh auth status`
- Update-Schlüssel, ausschliesslich fuer die spaetere Promotion:
  `~/.local/share/magnolie-release/update-ed25519.pem`. Normale Quell-, Paket-
  und Kandidatenbauten benoetigen diesen privaten Schluessel nicht.
- Contributor-Hash: aus der `build-config.json` des letzten geprüften
  Organizer-DEBs übernehmen oder über die geschützte CI-Variable bereitstellen
- JavaScript: `/home/maik3531/.bun/bin/bun`
- Lokales .NET SDK: `/tmp/opencode/dotnet-8.0.408`
- Lokales PowerShell: `/tmp/opencode/powershell-7.4.13/pwsh`
- Lokales NSIS: `/tmp/opencode/nsis-root/usr/bin/makensis`
- NSIS-Daten: `/tmp/opencode/nsis-root/usr/share/nsis`

Fehlende lokale Werkzeuge werden nur unter `/tmp/opencode` installiert. Keine
Systeminstallation und keine Änderung der Benutzerkonfiguration ist nötig.

## Verbindliche Quell- und Fehlerregel

- Die einzige bearbeitbare Magnolie-Quelle ist der aktuelle Arbeitsbaum unter
  `/home/maik3531/Downloads/Magnolie-GPT/magnolie-organizer-veroeffentlicht`.
  Unter `/tmp`, in einer `/tmp/magnolie-source-*`-Projektionen, entpackten
  Quellarchiven, Build-Staging-Verzeichnissen und auf Testmaschinen wird niemals
  Quellcode korrigiert oder als neuer Ausgangsstand übernommen.
- Temporäre Quellprojektionen dürfen ausschließlich durch die kanonischen
  Buildskripte aus dem aktuellen Arbeitsbaum erzeugt und nur für
  Reproduzierbarkeits-/Archivprüfungen gelesen werden. Jeder Befund wird danach
  im kanonischen Arbeitsbaum behoben und der gesamte betroffene Build neu
  gestartet.
- Vor jedem Build werden Version, Arbeitsbaum und Werkzeugpfade erneut geprüft.
  `NSISDIR` zeigt immer auf `/tmp/opencode/nsis-root/usr/share/nsis`, während
  `/tmp/opencode/nsis-root/usr/bin` ausschließlich im `PATH` steht.
- Fehler, Assertions, Warnungen und übersprungene Prüfungen werden nicht anhand
  einer späteren Erfolgsmeldung übergangen. Jeder Befund wird klassifiziert,
  behoben oder mit einem nachprüfbaren Grund als Blocker dokumentiert. Ein
  Testlauf gilt nur bei Exitstatus 0 und ohne unerklärte Warnung als bestanden.
- Nach jeder Änderung an PO-Dateien werden PO, MO, Web- und native Kataloge neu
  erzeugt. Leere, unscharfe, angehängte englische und fremdsprachige Fallbacks
  sind Releaseblocker.
- Ein Windows-Cross-Build ist nur ein Transportkandidat. QR-Code, Porträt,
  Ersteinrichtung, Skalierung und WebView2 werden mit genau diesem Kandidaten auf
  der Windows-Testmaschine geprüft. Statische Datei- oder Hashprüfungen ersetzen
  keine Darstellungskontrolle.
- Ein weiterer Claude-Lauf ist fuer diesen Auftrag vom Nutzer wegen des
  Abonnements erlassen. Das ist kein Verzicht auf technische Tests oder die
  unabhaengige Pruefung vorhandener Befunde. Kuenftig gesondert beauftragte
  Reviews bleiben moeglich; es wird kein nicht ausgefuehrter Review behauptet.

Ein KDE-DEB enthaelt drei interne Backends mit paketverwalteten Abhaengigkeiten:
Ubuntu 24.04 / Mint 22 (Qt5/KF5), Debian 13 (Qt6/KF6, Akonadi 24.12) und
Ubuntu / Kubuntu 26.04 (Qt6/KF6, Akonadi 25.12).

```sh
python3 magnolie-organizer-2.0.0/werkzeuge/kde_deb_bauen.py /tmp/opencode/kde-component
```

`MAGNOLIE_AKONADI_BUILD_ROOTFS` zeigt auf das Noble-Rootfs;
`MAGNOLIE_AKONADI_DEBIAN13_ROOTFS` auf das Trixie-Rootfs und
`MAGNOLIE_AKONADI_UBUNTU2604_ROOTFS` auf das Resolute-Rootfs. Der kanonische Builder
prueft `dpkg-checkbuilddeps`, baut jedes Backend zweimal und erzeugt echte
`dpkg-shlibdeps`-Abhaengigkeiten. Keine lokalen Shlibs-Overrides, Namensattrappen,
uebersprungenen Build-Abhaengigkeiten oder Host-Fallbacks sind erlaubt.
Die isolierten Bauten und Serialisierungstests greifen nicht auf Hostkontakte zu.
Ein gemeinsames DSC/Quellarchiv enthaelt das vollstaendige Multi-Rootfs-Rezept.
Das einzige DEB heisst `magnolie-organizer-kde_2.0.18_amd64.deb`; die drei
nativen Gates muessen denselben DEB-Hash plus ihr internes Profil nachweisen.
KDE-PIM bleibt Suggests; echte dormant-Backend-Anforderungen bleiben als
maschinenlesbare Audits erhalten und werden vor jeder Ausfuehrung geprueft.
Kein Uebergangs-DEB wird angeboten. Suffixierte 2.0.18-Testkandidaten sortieren
hoeher und erfordern beim Ersatz eine ausdrueckliche Downgrade-Entscheidung.
Installierter Paketname und Helferprotokoll bleiben unveraendert. Details stehen
in `native/akonadi-helper/DEB-TARGETS.md` im Organizer-Quellbaum.

## Reihenfolge

Der zusaetzliche dauerhafte Notes-Download ist in [NOTES-DOWNLOAD.md](NOTES-DOWNLOAD.md)
beschrieben. Vor dem Einfrieren `python3 tools/sync_mobile_downloads.py --check`
und die dortigen QR-Tests ausfuehren. Hostingaktivierung erfordert einen passenden
Veroeffentlichungsauftrag, der auch vorab bedingt delegiert sein kann. Alias erst
nach Abnahme und Remote-Hashcheck gemeinsam mit seiner Pruefsumme umschalten.
Der aktuelle Auftrag verlangt die Entfernung aller alten Downloadpakete nach
erfolgreicher Ersetzung und Remotepruefung, auch 2.0.17 und alter Notes-Versionen.
Keine dauerhafte Aufbewahrung alter Downloadpakete oder alter Versions-URLs
zusagen. Bis dahin bleiben benoetigte Upgrade-Eingaenge und Rollbackdateien
verfuegbar; Quellen, private Evidenz und Git-Historie werden nicht geloescht.
Diese Schemaaenderung fuehrt selbst weder Veroeffentlichung noch Loeschung aus.

1. Desktop-Versionen in Organizer, Handbuch und Windows angleichen. Die
   unabhaengige Notes-Version wird aus den aktuellen Android-Baumetadaten gelesen.
   Alle Quellen, Kataloge und die vorgesehenen Releasehinweise vor dem
   Kandidatenbau fertigstellen. Danach den Quellstand fuer die Abnahme einfrieren.
2. Parser-, Python-, DOM-, Handbuch-, Paket- und Shellpruefungen ausfuehren.
   Oeffentliche Pakettests verwenden ausschliesslich temporaere Testschluessel.
3. Windows als ausdruecklich unsignierten Linux-Cross-Build erzeugen:

   ```sh
   export DOTNET_ROOT=/tmp/opencode/dotnet-8.0.408
   export PATH="$DOTNET_ROOT:/home/maik3531/.bun/bin:/tmp/opencode/nsis-root/usr/bin:$PATH"
   export NSISDIR=/tmp/opencode/nsis-root/usr/share/nsis
   export MAGNOLIE_CONTRIBUTOR_HASH='<64-hex>'
   /tmp/opencode/powershell-7.4.13/pwsh -NoProfile \
       -File Magnolie-Organizer-Windows-2.0.0/build/Build.ps1 -CrossCompile
   ```

   Alle Windows-Kandidatendateien liegen danach nebeneinander im Windows-Projekt,
   einschliesslich Source-ZIP, Buildrecord und `-provenance.json`. Die Provenienz
   bindet Source-ZIP, portables ZIP und Installer aneinander. Vor und nach dem
   Bau wird der Quellarchivinhalt mit dem aktuellen Arbeitsbaum verglichen.
   Das ist noch keine native oder persoenliche Freigabe.
   Die Windows-Kompilierung und Installererzeugung verwenden eine unveraenderte
   Projektion genau dieses geprueften ZIPs. Linux-Projektionen werden vor dem Bau
   gegen den aufgezeichneten Quellbestand geprueft. In diesen Projektionen werden
   keine Quellkorrekturen vorgenommen; generierte Kataloge/Buildausgaben bleiben
   normale Ergebnisse des kanonischen Buildsystems.
   Windows-Kandidatenpruefsummen dienen nur der Transportintegritaet. Sie sind
   keine finalen Release-Pruefsummen. Auch die Authenticode-Signatur eines separat
   beauftragten offiziellen CI-Kandidaten ersetzt weder die native Abnahme noch
   die Nutzerentscheidung und berechtigt nicht zur Update-Manifest-Promotion.

4. Den vollstaendigen Desktop-Kandidatenbau einschliesslich `autopkgtest` starten.
   Nur wenn die benötigte QEMU-Umgebung im konkreten Lauf nachweislich fehlt,
   darf der eingeschränkte Lauf verwendet werden; Grund und ausgelassene
   Prüfung sind in `HINWEIS.txt` festzuhalten. Fedora-Bau und
   Fedora-Installationstest bleiben dabei aktiv:

   ```sh
   export MAGNOLIE_CONTRIBUTOR_HASH='<64-hex>'
    export MAGNOLIE_AKONADI_BUILD_ROOTFS=/tmp/opencode/ubuntu-noble-akonadi-rootfs
    export MAGNOLIE_AKONADI_DEBIAN13_ROOTFS=/tmp/opencode/debian-trixie-akonadi-rootfs
   magnolie-organizer-2.0.0/werkzeuge/release_bauen.sh
   ```

   Ohne `--promote` wird niemals signiert oder ein Live-Manifest ersetzt.
   Der Bau liefert ein neues privates Verzeichnis unter
   `/tmp/opencode/magnolie-desktop-candidate.*` mit flachem Artefaktlayout und
   `candidate.json`. Ein Lauf ohne Fedora erzeugt keinen freigabefaehigen Kandidaten.
   `candidate.json` ist ein technischer Baunachweis, keine Abnahme. Die Quellarchive
   behalten das letzte veroeffentlichte Bootstrap-Manifest; nach Abnahme werden
   diese Archive nicht fuer einen neuen Manifestinhalt erneut gebaut.
5. Exakte Kandidatenidentitaet ohne Signierung ermitteln:

   ```sh
   python3 magnolie-organizer-2.0.0/werkzeuge/release_gate.py inspect \
       --root "$PWD" --candidate /tmp/opencode/magnolie-desktop-candidate.XXXXXX
   ```

   Der Befehl prueft Quellen, vollstaendige Artefakte und Windows-Provenienz und
   gibt SHA-256 von `candidate.json` aus. Jede Quellaenderung, jedes neue relevante
   Quellfile und jede Aenderung der Kandidatenbytes macht die Abnahme ungueltig.
6. Genau diesen Kandidaten auf Linux und Windows installieren und nativ testen.
   Windows-Testmedium: `vm/Create-Installer-TestMedia.sh KANDIDATENVERZEICHNIS AUSGABE.iso`
   im Windows-Projekt. Das Medium enthaelt `candidate.json`; der VM-Test leitet
   daraus Version und Installername ab und prueft den Installerhash vor jedem Start.
   `windows-installer.json` auf dem Ergebnisdatentraeger bindet den tatsaechlichen
   Test an Kandidat, Quellen und Installer. Dieser Teilbericht ersetzt weder die
   restlichen Windows-Pruefungen noch die native Sichtpruefung. Android-AVD
   und Interoperabilitaet muessen fuer die enthaltene Notes-APK ebenfalls belegt sein.
7. Einen der zwei ausdruecklichen Autorisierungspfade verwenden: v1 bleibt die
   persoenliche Abnahme nach eigenen Linux-/Windows-Tests des Nutzers. v2 erlaubt
   einen vorab bedingt delegierten Veroeffentlichungsauftrag, dessen echte
   Originalinstruktion privat erhalten bleibt. Erst nach allen erfolgreichen
   Tests bindet der verantwortliche Operator die erfuellten Bedingungen an den
   exakten Kandidaten und dessen Belege. Bei gueltiger Delegation ist kein
   weiterer persoenlicher Zwischenstopp noetig. Niemals persoenliche Nutzertests
   behaupten, die nur ein Operator oder VM-Agent ausgefuehrt hat. Ein Build allein
   erzeugt weder Zustimmung noch einen Operatorrecord.
8. Die unten beschriebenen echten Belege privat ablegen und zuerst nur pruefen:

   ```sh
   python3 magnolie-organizer-2.0.0/werkzeuge/release_gate.py verify \
       --root "$PWD" --candidate KANDIDATENVERZEICHNIS \
       --approval PRIVATER_BELEGORDNER/approval.json \
       --accept-candidate TATSAECHLICHE_KANDIDATEN_SHA256
   ```

   `verify` schreibt nichts und liest keinen privaten Signierschluessel.
   Beide `update.xml` bleiben bis zur explizit beauftragten Promotion bei 2.0.17.
9. Nur nach allen Belegen und einem ausdruecklichen Veroeffentlichungsauftrag
   (persoenlich oder durch die gepruefte bedingte Delegation):
    Zuerst den versionierten Notes-Upload und die private Alias-Vorbereitung aus
    `NOTES-DOWNLOAD.md` erledigen, solange der eingefrorene Bootstrap noch gilt.
    `release_bauen.sh --promote KANDIDATENVERZEICHNIS APPROVAL_JSON KANDIDATEN_SHA256`.
   Erst dieser getrennte Pfad prueft den produktiven privaten Schluessel. Er baut
   keine Produkte neu, sondern signiert das Manifest zu genau den angenommenen
   Artefakten, erzeugt die finalen flachen Pruefsummenlisten und ersetzt die
   Release-Dateien mit Rollback. Quellen, Kandidat und Belege werden unmittelbar
   vor der Ersetzung nochmals geprueft. Fehlender Schluessel ist ein Blocker;
   ein neuer Ersatzschluessel ist keine zulaessige Umgehung des eingebetteten Pins.
10. Im Umfang des Veroeffentlichungsauftrags nur vorgesehene Quell-/Releaseaenderungen committen,
    pushen, taggen und GitHub Release mit allen geprueften Artefakten erstellen.
    Alte `.buildinfo`-/`.changes`-Dateien und private Belege nie aufnehmen.
11. Dieselben vom Update-Manifest referenzierten Artefakte in
   `https://gitlab.com/maik3531/mint-forgs` unter `Magnolie-Organitzer/`
   ersetzen und den GitLab-Commit pushen.
12. GitHub-Downloads, GitLab-Raw-URLs, Prüfsummen und den signierten Updatepfad
     nach der Veröffentlichung erneut abrufen und verifizieren.
13. Danach gemaess aktuellem Auftrag alle alten Downloadpakete an den lokalen
    und oeffentlichen Releaseorten entfernen und Downloadlisten korrigieren,
    nicht durch neue Bytes unter alten Versionsnamen ersetzen. Die verifizierten
    neuen versionierten Pakete, Aliasdateien und Pruefsummen bleiben erhalten.

## Pflichtartefakte

- Organizer: DEB, DSC, Quellarchiv, AppImage, Flatpak, RPM und SRPM
- Optionaler KDE-Helfer: ein `magnolie-organizer-kde_VERSION_amd64.deb` mit drei
  internen Backends, ein KDE-DSC, Quellarchiv und `kde-VERSION-provenance.json`;
  ausserdem ein eigenstaendiges Fedora-RPM und SRPM, kein Uebergangs-DEB
- Handbuch: DEB, DSC, Quellarchiv, RPM und SRPM
- Windows: Quell-ZIP, portables ZIP, Installer, Buildrecord, `-provenance.json`
  und Pruefsummen, alle im selben Verzeichnis
- Unveränderte aktuelle Notes-Artefakte, falls die gemeinsame Release-Seite sie
  weiterhin als Bestandteil ausweist
- `Magnolie-Organizer-PRUEFSUMMEN.sha256`, `PRUEFSUMMEN.sha256`, `update.xml`
  und `HINWEIS.txt`

## Privates Abnahmeschema

Diese Beschreibung ist keine Abnahmedatei. Die Werkzeuge erzeugen keine
`approval.json`. Die verantwortliche Person erfasst ausschliesslich echte
Ergebnisse und die tatsaechliche Nutzerentscheidung. Hashbindungen beweisen
Dateiidentitaet, nicht, wer einen lokalen Beleg verfasst hat; der private
Belegordner und die Freigabekonsole sind eine vertrauenswuerdige Operatorgrenze.
CI darf weder Nutzerzustimmung noch eine Delegation/Operatorentscheidung setzen
oder aus Build-Erfolg diesen Promotionpfad automatisch starten. Der aktuelle
Implementierungsauftrag erstellt noch keinen Produktions-Abnahmerecord.

### Technische Identitaetsbindung

Neue Kandidaten verwenden `magnolie-desktop-candidate-v2`. Jede Quellidentitaet
enthaelt `sha256` und `mode` (ganzzahliger POSIX-Modus einschliesslich aller
Execute- und Sonderbits), nicht mehr das verlustbehaftete Boolean `executable`.
Alte unveroeffentlichte Kandidaten werden verworfen und neu gebaut; es gibt
keine Migration bestehender Abnahmen. Das persoenliche Abnahmeschema v1 und das
native Belegschema bleiben unveraendert. Das neue Abnahmeschema v2 ergaenzt nur
den getrennten delegierten Autorisierungspfad, nicht schwaechere technische Gates.

JSON wird aus genau den Bytes geprueft, deren Hash gebunden wird. Quellen und
Artefakte werden nach der externen Windows-Pruefung erneut verglichen; native
JSON-Belege, Nutzerentscheidung, Originalinstruktion und Operatorrecord werden
gegen den Hash ihres eingelesenen Inhalts geprueft. Die Promotion bindet alle
Abnahme-/Instruktions-/Operator-/Logdateien vor
und nach ihrem geschuetzten Dateitausch. Sie publiziert ausschliesslich die
geprueften privaten Staging-Bytes und kontrolliert Quellen und Ergebnis nochmals
vor dem Commit. Der kooperative Release-Lock kann beliebige Schreibzugriffe
desselben Benutzers nicht verhindern; sichtbare Abweichungen fuehren zum Abbruch
bzw. Rollback. Unklare Rename-/Rollback-Zustaende behalten ihr Recovery-Verzeichnis.
Ein Windows-Cleanupfehler nach dem Commit wird als Fehler gemeldet, darf aber
keinen destruktiven Rollback bereits bestaetigter Ausgaben mehr ausloesen.

Vor dem Einfrieren und bei der Kandidatenpruefung werden beide Bootstrap-Kopien
gegen die festgeschriebene veroeffentlichte `2.0.17`-Datei und deren Ed25519-Pin
geprueft. Read-only-Preflight:

```sh
python3 magnolie-organizer-2.0.0/werkzeuge/release_gate.py bootstrap --root "$PWD"
```

Der eigenstaendige Handbuch-RPM-Bau verwendet die lokal mitgelieferte
`werkzeuge/source_selection.py`. Linux und Handbuch fuehren bytegleiche Kopien
dieses gemeinsamen, eigenstaendig nutzbaren Selektors; die Pakettests pruefen
diese Gleichheit im Gesamtbaum und testen sichere Archive ohne Geschwisterprojekt.

### v1: Persoenliche Abnahme

`approval.json` hat genau die Felder `schema` (`magnolie-desktop-approval-v1`),
`candidateSha256`, `nativeEvidence`, `userAcceptance` und `qemuException`.
`nativeEvidence` enthaelt genau `linux`, `windows` und `android`. Jeder Wert ist
eine Referenz `{"file":"linux-native.json","sha256":"<echte Dateisumme>"}`.
Dateipfade sind relativ zum jeweiligen Beleg, ohne `..`, absolute Pfade oder
Symlinks. Referenzierte Dateien muessen existieren, nicht leer und bytegleich sein.

Ein nativer Beleg hat genau diese Felder:

```json
{
  "schema": "magnolie-native-evidence-v1",
  "platform": "linux",
  "candidateSha256": "<Identitaet von candidate.json>",
  "sourceSha256": "<sourceSha256 aus candidate.json>",
  "artifacts": {"<tatsaechlich getesteter Binaerdateiname>": "<SHA-256>"},
  "checks": {"installation": {"exitCode": -1, "log": {"file": "installation.log", "sha256": "<SHA-256>"}}}
}
```

Der Platzhalter oben ist absichtlich nicht erfolgreich. Fuer jeden realen Check
ist Exitcode 0 samt echtem Protokoll erforderlich, ohne unerklärte Warnungen.
`artifacts` muss alle jeweiligen Binaerartefakte aus `candidate.json` enthalten:
Linux alle DEBs, binaeren RPMs, AppImage und Flatpak; Windows Installer und
portables ZIP; Android die APK. Quellen, SRPMs und Metadaten sind bereits durch
die Kandidatenidentitaet gebunden. Erforderliche Checks:

- Linux: `installation`, `upgrade`, `ui`, `protectedImages`, `firstRun`, `scaling`, `updater`, `kdeUbuntu2404Mint22`, `kdeDebian13`, `kdeUbuntu2604`.
- Windows: `installation`, `upgrade`, `uninstall`, `ui`, `protectedImages`, `firstRun`, `scaling`, `updater`.
- Android: `installation`, `upgrade`, `interoperability`.

Die drei KDE-Checks haben zusaetzlich genau `artifact`, `sha256`, `profile`:
`artifact` ist jeweils `magnolie-organizer-kde_VERSION_amd64.deb`, `sha256` dessen
identischer Hash aus dem Kandidaten. `profile` ist passend zum Check
`ubuntu24.04`, `debian13` oder `ubuntu26.04`. Drei unterschiedlich gebaute DEBs
oder reine Komponenten-Bauprotokolle erfuellen diese nativen Gates nicht.
Installations-, Upgrade- und konfigurierte KDE-Datentests bleiben erforderlich;
ein nichtaktivierender `--check` ist keine Live-Datenabnahme.

`userAcceptance` hat genau `accepted` (nur nach echter Zustimmung `true`),
`candidateSha256`, `statement` und `evidence` (Referenz auf die gespeicherte echte
Nutzerentscheidung, nicht auf eine automatisierte Erfolgsmeldung). Die technische
Erklaerung in `statement` lautet exakt:

`I explicitly approve publication of this exact candidate after testing it on Linux and Windows.`

Auch die referenzierte UTF-8-Nutzerentscheidung muss die exakte Kandidaten-SHA256
und diese Erklaerung enthalten. Ein beliebiges Testprotokoll oder eine alte
Abnahmedatei wird nicht als persoenliche Entscheidung akzeptiert.

### v2: Bedingt Delegierte Autorisierung

`magnolie-desktop-approval-v2` hat genau `schema`, `candidateSha256`,
`nativeEvidence`, `authorization`, `qemuException`. Identitaet, native Belege,
alle Checks, Logs und QEMU-Regeln sind dieselben wie bei v1. `userAcceptance`
ist hier unzulaessig; v1 akzeptiert umgekehrt kein `authorization`-Objekt.
Unbekannte Schemas, Felder, Arten oder unvollstaendige Records werden abgewiesen.

`authorization` hat genau diese Form (Platzhalter sind nicht freigabefaehig):

```json
{
  "kind": "delegated-conditional",
  "instructions": {"file": "instructions.json", "sha256": "<SHA-256>"},
  "operatorRecord": {"file": "operator.json", "sha256": "<SHA-256>"}
}
```

Die referenzierte `instructions.json` hat genau `schema`
(`magnolie-delegated-instructions-v1`), `delegated` (explizites Boolean),
`version`, `notesVersion` (exakte Releaseversionen aus `candidate.json`) und
`quote` (Datei-/SHA-256-Referenz). Nur die vertrauenswuerdige verantwortliche
Person darf nach Pruefung der echten Nutzeranweisung `delegated` auf `true`
setzen. Das bezeugt eine Veroeffentlichung nach erfolgreich erfuellten Bedingungen
fuer diese Versionen, nicht beliebige kuenftige Releases. Keine Textsuche nach
"ja", "veroeffentlichen" oder aehnlichen Schluesselwoertern entscheidet darueber.

Nicht freigabefaehiges Instruktionsbeispiel:

```json
{
  "schema": "magnolie-delegated-instructions-v1",
  "delegated": false,
  "version": "<Desktopversion>",
  "notesVersion": "<Notesversion>",
  "quote": {"file": "original-user-text.txt", "sha256": "<SHA-256 der Originaldatei>"}
}
```

`quote` verweist relativ zur Instruktionsdatei auf eine **separate private Datei**
mit den unveraenderten tatsaechlichen UTF-8-Nutzertextbytes, nicht auf eine
Uebersetzung, Zusammenfassung, nachformulierte Zustimmung oder einen Testlog.
Originale Zeilenenden und Schreibweise erhalten; kein Kandidatenhash und keine
persoenliche Testerfahrung in den Nutzertext hineinschreiben. Die Originaldatei
muss vorhanden, nicht leer und hashgleich sein. Die Software authentifiziert
weder den lokalen Verfasser noch die Bedeutung des Texts; diese Pruefung bleibt
ausdruecklich an der vertrauenswuerdigen Operatorgrenze. Auch Einschraenkungen,
Widerrufe und der Unterschied zwischen Implementierungs- und Publikationsauftrag
sind dort zu pruefen. Hashes allein schaffen keine Autoritaet.

Erst **nach Abschluss und Pruefung aller erforderlichen Tests** erstellt der
Operator separat `operator.json` mit genau:

```json
{
  "schema": "magnolie-delegated-operator-v1",
  "statement": "Operator verified delegated conditions",
  "afterTests": false,
  "finalResult": "pending",
  "candidateSha256": "<SHA-256 von candidate.json>",
  "sourceSha256": "<sourceSha256 aus candidate.json>",
  "artifacts": {"<jedes Artefakt>": {"sha256": "<SHA-256>", "bytes": 0}},
  "instructions": {"file": "instructions.json", "sha256": "<SHA-256>"},
  "nativeEvidence": {"<jede Plattform>": {"file": "<Belegdatei>", "sha256": "<SHA-256>"}},
  "qemuException": null
}
```

Dieses Beispiel ist absichtlich nicht erfolgreich. Nur nach echter Pruefung sind
`afterTests: true` und `finalResult: "passed"` zulaessig. Das ist ein attestierter
Nachtest-Zeitpunkt, keine aus Dateizeitstempeln abgeleitete Chronologie. Artefakte
muessen dem **vollstaendigen** Kandidateninventar inklusive Quellen, Metadaten,
Groessen und Hashes entsprechen. `instructions`, `nativeEvidence` und
`qemuException` muessen exakt dieselben Werte wie im Abnahmerecord haben;
die Referenzen werden im Kontext dieses Records geprueft, nicht umgedeutet.
Geaenderte Instruktionsbytes, Testbelege oder Kandidaten erfordern einen erneut
geprueften Operatorrecord. Es gibt keinen Generator fuer erfolgreiche Records.

Der normale `verify`-Befehl oben akzeptiert beide Schemas. Weder ein Aufruf von
`seal`/`inspect` noch ein erfolgreicher Bau waehlt v2 oder erteilt eine Freigabe.
`--accept-candidate` bleibt eine explizite Operatorbindung an den exakten Hash,
keine Behauptung persoenlicher Nutzertests. Beide Pfade erzwingen unveraendert
Quellinventur, Dateimodi, Pins, Provenienz, Archivprojektionen und die erneuten
Dateibindungspruefungen bis vor/nach dem Promotion-Dateitausch.

Reine Python-Regression ohne Produktbau, GPU, VM oder Signierung:

```sh
python3 -B -m pytest -q magnolie-organizer-2.0.0/pruefungen/test_release_authorization.py
```

Die neuen synthetischen Fixtures pruefen beide Recordpfade und Dateibindungen
ohne Monkeypatches. Sie ersetzen keine produktive Kandidaten-/SDK-/VM-Pruefung;
die vorhandenen v1-Paket-/Provenienzregressionen bleiben ebenfalls erforderlich.

### Gemeinsame Grenzen

`qemuException` ist normalerweise `null`. Nur fuer einen als `unavailable`
aufgezeichneten QEMU-Lauf ist ein konkreter Grund von mindestens 20 Zeichen
zulaessig, der wortgleich in den bereits angenommenen `HINWEIS.txt` steht.
Fehlgeschlagene Tests sind keine nicht vorhandene QEMU-Umgebung.

Synthetische Vertraege/SQL-Fixtures gehoeren in Quellarchive, niemals in
Produkt-Payloads. Persoenliche Profile, private Testverzeichnisse, Schluessel,
Token und `an-claude.md` sind keine Quellartefakte. Neue KDE-Quelldateien werden
rekursiv erfasst und invalidieren wie jede andere Quellaenderung den Kandidaten.

## Recurrence-Paketgate

`bin/magnolie_recurrence.py` ist eine zwingende Laufzeitdatei des Launchers.
DEB/RPM installieren sie nach `/usr/bin/magnolie_recurrence.py`, Flatpak nach
`/app/bin/magnolie_recurrence.py`, AppImage nach
`AppDir/usr/bin/magnolie_recurrence.py`. `werkzeuge/runtime_pruefen.py` prueft
Syntax und Aufloesung der lokalen Modulimporte am tatsaechlichen Installationsort,
ohne die Anwendung zu starten. Ein fehlendes Modul darf nicht aus dem Quellbaum
oder einer anderen Installation nachgeladen werden.

Die verpflichtenden Pakettests sind `test_recurrence.py`,
`test_recurrence_oracle.py`, `test_recurrence_integration.py`,
`test_recurrence_timezones.py` und `test_runtime_packaging.py` unter `pruefungen/`.
Sie benoetigen pytest, die normalen Build-Abhaengigkeiten und IANA-Zeitzonendaten,
aber weder dateutil noch einen Windows-Geschwisterbaum/.NET. Die Linux-Tests lesen
die gemeinsamen Verträge auch aus der internen `contracts/`-Kopie eines
eigenstaendigen Quellpakets. AppImage buendelt seine eigenen Zeitzonendaten;
DEB deklariert `tzdata`, RPM den von seinem Distributionsprofil bereitgestellten
Zoneinfo-Dateipfad. Das Flatpak-Gate prueft die Daten des GNOME-Runtimes.

Die 448 Regel-/Anker-/Ende-Faelle in
`pruefungen/fixtures/recurrence-rfc-oracle.json` enthalten festgeschriebene,
unabhaengig mit `python-dateutil==2.9.0.post0` ermittelte Referenzdigests. Pro Regel
wird die geordnete Folge aller 16 Eingaben und Ergebnislisten geprueft. Normale
Bauten regenerieren diese Referenzen niemals. Windows-Quellarchive enthalten
dieselbe Datei unter `tests/fixtures/recurrence-rfc-oracle.json`; der obligatorische
`tests/recurrence-golden.js`-Lauf prueft alle 448 Faelle ohne Python/dateutil.
`tests/recurrence-worker.js` prueft immer die enthaltene Windows-Oberflaeche und
zusaetzlich die Linux-Oberflaeche, wenn deren Quelle im vollstaendigen Repository
vorliegt. Ein explizit gesetzter, aber ungueltiger Linux-Pfad ist ein Fehler.
Keine dieser Fixture-Dateien wird in Binaerpakete installiert.

Die zusaetzlichen, ausdruecklich angeforderten Entwicklerpruefungen bleiben
erhalten. Zusaetzlich zu den normalen Testabhaengigkeiten gelten
`pruefungen/requirements-recurrence-oracle.txt`, fuer vier Engines ausserdem das
vorhandene .NET-SDK mit restauriertem `CoreTests.csproj` und Node/Bun mit jsdom.
Beispiele aus der Organizer-Quellwurzel, keine Release-/Signierbefehle:

```sh
python3 -m pytest -q pruefungen/recurrence_dateutil_oracle.py
python3 -m pytest -q pruefungen/recurrence_cross_platform.py
```

Fehlt eine Abhaengigkeit bei einer solchen expliziten Pruefung, ist das ein
Fehler, kein stiller Skip. Die erste Datei enthaelt weiterhin die lebenden
dateutil-, Selektor-, Wochenjahr- und DST-Differentialtests. Die zweite ruft die
drei vollstaendigen Vier-Engine-Integrationspruefungen auf. Referenzpflege ist
separat und manuell zu begutachten:
`python3 pruefungen/recurrence_dateutil_oracle.py --golden-digests` druckt nur
Testreferenzen und schreibt keine Dateien.

## Notes-Referenzeingang

Die ausschliesslich privaten Vorbereitungsbefehle, der rein lesende lokale
Werkzeug-Preflight und die getrennten Public-/Cross-Testabhaengigkeiten stehen in
`BUILD-PREREQUISITES.md`. Ganze Produktbauten beginnen erst nach Hauptreview und
Quell-Freeze. `Build.ps1 -Destination` und `MAGNOLIE_WINDOWS_ARTIFACTS` trennen
Windows-Quellwurzel und privaten Artefakteingang; historische Dateien bleiben
unveraendert. `notes_candidate.py` prueft APK-Metadaten ohne private Schluessel.
Ein neuer privater Notes-Eingang erfordert jetzt den ausgefuehrten Baunachweis;
der explizite Modus `--build-production` baut und signiert erst nach gesonderter
Autorisierung aus den kanonischen Quellen. Ablauf: `BUILD-PREREQUISITES.md`.

Neue Notes-Artefakte werden privat vorbereitet. `MAGNOLIE_NOTES_ARTIFACTS` kann
auf ein privates, flaches Eingangsverzeichnis mit APK, Quellarchiv,
`Magnolie-Notes-VERSION-provenance.json` und
`Magnolie-Notes-PRUEFSUMMEN.sha256` zeigen. Ohne die Variable wird die Releasewurzel
verwendet. Die erwartete Version kommt aus den Android-Quellmetadaten, nicht aus
dem historischen Verzeichnisnamen. Somit erfordert die Quelle 1.0.14 genau
`Magnolie-Notes-1.0.14.apk` und `magnolie-notes_1.0.14.tar.xz`; eine auf 1.0.13
verweisende Liste wird nicht akzeptiert. Die Liste muss APK, Quellarchiv und
Baunachweis vollstaendig abdecken; die Kandidateninventur bindet alle Dateien.
Fehlende, leere, doppelte, alte oder nicht bytegleiche Eingaben
werden bereits vor dem Desktopbau abgewiesen.

Reine Eingangspruefung ohne Bau, Signierung, Kandidatenerzeugung oder Promotion:

```sh
python3 magnolie-organizer-2.0.0/werkzeuge/release_gate.py notes-inputs \
    --root "$PWD" --candidate /pfad/zum/privaten/notes-eingang
```

Diese Pruefung sowie Seal/Inspect erzwingen den Notes-Baunachweis, die exakte
Quellarchivprojektion inklusive Modi sowie APK-Version, Produktionszertifikat und
Debug/Test-Flags. `MAGNOLIE_RELEASE_CERT_SHA256` muss die unabhaengig bekannte
oeffentliche Produktionsidentitaet angeben; `ANDROID_SDK_ROOT` stellt aapt und
apksigner fuer die reine Verifikation bereit. Ein nachtraeglich gehashtes APK ohne
ausgefuehrten Baunachweis reicht nicht. Der Nachweis misst kanonische Quellen und
Vertraege vor/nach einem sauberen Releasebau mit ausgefuehrten Unit-Tests und bindet
dessen konkrete APK-Ausgabe. Er ist ein lokaler Nachweis auf einem vertrauenswuerdigen
Baurechner, keine unabhaengige Reproduzierbarkeit und keine Freigabeentscheidung.
AVD/Upgrade, Cross-Tests und native Interoperabilitaet bleiben eigene Android-Gates;
persoenliche oder bedingt delegierte Autorisierung bleibt separat erforderlich. Aktuelle
oeffentliche 1.0.13-Links und -Pruefsummen werden zum Vorbereiten des privaten
1.0.14-Eingangs nicht veraendert.
