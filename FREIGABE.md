# Desktop-Freigabe

Diese Checkliste hält den auf diesem Rechner verwendeten Ablauf fest. Private
Schlüssel, Zertifikate und der konkrete Contributor-Hash gehören nicht in das
Repository.

## Voraussetzungen

- GitHub-Zugang: `gh auth status`
- Update-Schlüssel: `~/.local/share/magnolie-release/update-ed25519.pem`
- Contributor-Hash: aus der `build-config.json` des letzten geprüften
  Organizer-DEBs übernehmen oder über die geschützte CI-Variable bereitstellen
- JavaScript: `/home/maik3531/.bun/bin/bun`
- Lokales .NET SDK: `/tmp/opencode/dotnet-8.0.408`
- Lokales PowerShell: `/tmp/opencode/powershell-7.4.13/pwsh`
- Lokales NSIS: `/tmp/opencode/nsis-root/usr/bin/makensis`
- NSIS-Daten: `/tmp/opencode/nsis-root/usr/share/nsis`

Fehlende lokale Werkzeuge werden nur unter `/tmp/opencode` installiert. Keine
Systeminstallation und keine Änderung der Benutzerkonfiguration ist nötig.

Nur für einen isolierten lokalen Akonadi-Helfer-Bau, dessen Abhängigkeiten noch
nicht paketverwaltet installiert sind, darf eine lokale Shlibs-Datei übergeben
werden:

```sh
(cd native/akonadi-helper && \
    MAGNOLIE_SHLIBS_LOCAL=/pfad/zu/lokalen.shlibs dpkg-buildpackage -us -uc -b)
```

`MAGNOLIE_SHLIBS_LOCAL` darf nicht für normale Paketbauten gesetzt sein; ohne
die Variable verwendet `dh_shlibdeps` unverändert die paketverwalteten
Bibliotheksinformationen.

## Reihenfolge

1. Desktop-Versionen in Organizer, Handbuch und Windows angleichen. Die
   Android-Version bleibt unabhängig und wird nur für eine ausdrücklich
   beschlossene Notes-Veröffentlichung erhöht.
2. Parser-, Python-, DOM-, Handbuch-, Paket- und Shellprüfungen ausführen.
3. Windows als ausdrücklich unsignierten Linux-Cross-Build erzeugen:

   ```sh
   export DOTNET_ROOT=/tmp/opencode/dotnet-8.0.408
   export PATH="$DOTNET_ROOT:/home/maik3531/.bun/bin:/tmp/opencode/nsis-root/usr/bin:$PATH"
   export NSISDIR=/tmp/opencode/nsis-root/usr/share/nsis
   export MAGNOLIE_CONTRIBUTOR_HASH='<64-hex>'
   /tmp/opencode/powershell-7.4.13/pwsh -NoProfile \
       -File Magnolie-Organizer-Windows-2.0.0/build/Build.ps1 -CrossCompile
   ```

4. Den vollständigen Desktop-Releasebau einschließlich `autopkgtest` starten.
   Nur wenn die benötigte QEMU-Umgebung im konkreten Lauf nachweislich fehlt,
   darf der eingeschränkte Lauf verwendet werden; Grund und ausgelassene
   Prüfung sind in `HINWEIS.txt` festzuhalten. Fedora-Bau und
   Fedora-Installationstest bleiben dabei aktiv:

   ```sh
   export MAGNOLIE_CONTRIBUTOR_HASH='<64-hex>'
   magnolie-organizer-2.0.0/werkzeuge/release_bauen.sh
   ```

5. Prüfen, dass `update.xml` echte Artefaktsummen und eine gültige Signatur
   enthält. Danach die globale `PRUEFSUMMEN.sha256` aus genau den hochzuladenden
   Dateien neu erzeugen und mit `sha256sum -c` prüfen.
   Keine frühere Testaussage als Ergebnis des aktuellen Releases übernehmen;
   Windows-VM, Android-AVD, QEMU und Paketprüfungen nur als bestanden nennen,
   wenn ein Ergebnis des aktuellen Releasekandidaten vorliegt.
6. Ausschließlich Quell-, Metadaten- und vorgesehene Releaseänderungen committen.
   Alte `.buildinfo`-/`.changes`-Dateien und private Schlüssel nie aufnehmen.
7. Commit nach `main` pushen, Tag `vVERSION` setzen und pushen.
8. GitHub Release mit `HINWEIS.txt` als Beschreibung und allen geprüften
   Artefakten erstellen.
9. Dieselben vom Update-Manifest referenzierten Artefakte in
   `https://gitlab.com/maik3531/mint-forgs` unter `Magnolie-Organitzer/`
   ersetzen und den GitLab-Commit pushen.
10. GitHub-Downloads, GitLab-Raw-URLs, Prüfsummen und den signierten Updatepfad
    nach der Veröffentlichung erneut abrufen und verifizieren.

## Pflichtartefakte

- Organizer: DEB, DSC, Quellarchiv, AppImage, Flatpak, RPM und SRPM
- Optionaler Akonadi-Helfer: DEB, DSC, Quellarchiv, RPM und SRPM
- Handbuch: DEB, DSC, Quellarchiv, RPM und SRPM
- Windows: Quell-ZIP, portables ZIP, Installer, Buildrecord und Prüfsummen
- Unveränderte aktuelle Notes-Artefakte, falls die gemeinsame Release-Seite sie
  weiterhin als Bestandteil ausweist
- `Magnolie-Organizer-PRUEFSUMMEN.sha256`, `PRUEFSUMMEN.sha256`, `update.xml`
  und `HINWEIS.txt`
