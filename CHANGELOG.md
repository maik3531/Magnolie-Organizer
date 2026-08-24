# Changelog / Änderungen

## 2.0.3 / Notes 1.0.5 — 2026-08-24

### English

- Prevented optional desktop integration from replacing PulseAudio with PipeWire or vice versa during DEB installation.
- Added verified audio fallback across available PulseAudio, PipeWire and ALSA clients.
- Disabled affected WebKitGTK DMA-BUF and compositing paths before initialization to avoid blank Wayland AppImage windows and Mesa/Gallium shutdown crashes.
- Added a sandboxed GNOME 49 Flatpak bundle with no direct host-filesystem or GPU-device access.
- Carried the complete 154-page handbook and all 19 translation catalogs forward to 2.0.3.

### Deutsch

- Optionale Desktopintegration kann bei der DEB-Installation weder PulseAudio durch PipeWire noch PipeWire durch PulseAudio ersetzen.
- Der Audiofallback wechselt geprüft zwischen vorhandenen PulseAudio-, PipeWire- und ALSA-Werkzeugen.
- Betroffene DMA-BUF- und Compositing-Pfade werden vor der WebKitGTK-Initialisierung abgeschaltet; dadurch werden leere Wayland-AppImage-Fenster und Mesa-/Gallium-Abstürze beim Beenden vermieden.
- Ein sandboxiertes Flatpak auf Basis von GNOME 49 kommt ohne direkten Zugriff auf das Wirtsdateisystem oder Grafikgerät hinzu.
- Das vollständige 154-Seiten-Handbuch und alle 19 Übersetzungskataloge wurden auf 2.0.3 übernommen.

## 2.0.2 / Notes 1.0.5 — 2026-08-22

### English

- Made handbook resizing responsive by showing the scaled pages before repagination completes.
- Reduced organizer startup work by loading only the active language catalog.
- Built the AppImage from a pinned Ubuntu 22.04 runtime and verified its GLIBC 2.35 ceiling on Arch Linux.
- Added separately installable native Fedora 42 RPMs for the organizer and handbook.

The Fedora packages were built, installed and verified in a pinned rootless Fedora 42 environment.
The Windows VM and external `autopkgtest` QEMU runs remain unavailable.

### Deutsch

- Handbuchseiten werden beim Ändern der Fenstergröße sofort skaliert angezeigt und danach neu paginiert.
- Der Organizer lädt beim Start nur noch den aktiven Sprachkatalog.
- Das AppImage entsteht aus einer gepinnten Ubuntu-22.04-Laufzeit und hält beim Arch-Test die GLIBC-2.35-Grenze ein.
- Organizer und Handbuch stehen als getrennt installierbare native Fedora-42-RPMs bereit.

Die Fedora-Pakete wurden in einer gepinnten rootlosen Fedora-42-Umgebung gebaut,
installiert und geprüft. Windows-VM und externer `autopkgtest`-QEMU-Lauf bleiben
weiterhin nicht verfügbar.

## 2.0.1 / Notes 1.0.5 — 2026-08-21

### English

- Reduced startup work for large data sets from quadratic scans to linear indexes.
- Added privacy-safe startup timing diagnostics for data loading and browser rendering.
- Added search with persistent selections to print, export and bulk-delete options.
- Exposed Calendar and Planner search with visible controls and previous/next match navigation.
- Bundled the same handwriting font on Linux and Windows.
- Removed two redundant full pagination passes before the handbook first opens.
- Updated Linux, Windows and handbook sources, tests and documentation to 2.0.1.

Local release artifacts, final checksums and a signed update manifest were generated.
The Windows artifacts are unsigned Linux cross-builds; their source, package and
30,000-item core tests pass, but a current Windows VM run was unavailable. External
Linux `autopkgtest` QEMU and Fedora `mock` tests were unavailable as well.

### Deutsch

- Start großer Datenbestände von quadratischen Suchen auf lineare Indizes umgestellt.
- Datenschutzfreundliche Startzeitmessung für Datenladen und Browserdarstellung ergänzt.
- Suche mit erhaltener Auswahl in Druck-, Export- und Sammellöschoptionen ergänzt.
- Kalender- und Planersuche sichtbar gemacht und um vorherigen/nächsten Treffer erweitert.
- Unter Linux und Windows dieselbe gebündelte Handschrift eingebaut.
- Zwei redundante Vollpaginierungen vor dem ersten Öffnen des Handbuchs entfernt.
- Linux-, Windows- und Handbuchquellen, Tests und Dokumentation auf 2.0.1 angehoben.

Lokale Freigabeartefakte, endgültige Prüfsummen und ein signiertes
Aktualisierungsmanifest wurden erzeugt. Die Windows-Artefakte sind unsignierte
Linux-Cross-Builds; Quellen-, Paket- und 30.000er-Coretests bestehen, ein aktueller
Windows-VM-Lauf war jedoch nicht verfügbar. Auch die externen Linux-Tests mit
`autopkgtest` QEMU und Fedora `mock` waren nicht verfügbar.

## 2.0.0 / Notes 1.0.5 — 2026-08-21

### English

- Published Magnolie Organizer 2.0.0 for Linux and Windows.
- Published Magnolie Notes 1.0.5 for Android.
- Added the matching bilingual Magnolie Handbook 2.0.0.
- Verified Android signing, installation, startup, instrumentation and upgrade.
- Verified Linux tests, 30,000-item load tests and reproducible DEB/AppImage builds.
- Audited Windows source, portable ZIP and installer contents.
- Successfully tested the application runtime on Windows.
- Added SHA-256 checksums and a signed update manifest.

The Windows artifacts are unsigned Linux cross-builds. External Linux
`autopkgtest` QEMU and Fedora `mock` tests were not run because the required
images and tools were unavailable.

### Deutsch

- Magnolie Organizer 2.0.0 für Linux und Windows veröffentlicht.
- Magnolie Notes 1.0.5 für Android veröffentlicht.
- Passendes zweisprachiges Magnolie-Handbuch 2.0.0 ergänzt.
- Android-Signatur, Installation, Start, Instrumentation und Upgrade geprüft.
- Linux-Tests, 30.000er-Lasttests und reproduzierbare DEB-/AppImage-Bauten geprüft.
- Windows-Quellen, portable ZIP und Installer inhaltlich auditiert.
- Laufzeit der Anwendung unter Windows erfolgreich geprüft.
- SHA-256-Prüfsummen und signiertes Update-Manifest bereitgestellt.

Die Windows-Artefakte sind unsignierte Linux-Cross-Builds. Externe
Linux-`autopkgtest`-QEMU- und Fedora-`mock`-Tests konnten mangels Testabbildern
und Werkzeugen nicht laufen.
