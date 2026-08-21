# Changelog / Änderungen

## 2.0.1 / Notes 1.0.5 — 2026-08-21

### English

- Reduced startup work for large data sets from quadratic scans to linear indexes.
- Added privacy-safe startup timing diagnostics for data loading and browser rendering.
- Added search with persistent selections to print, export and bulk-delete options.
- Exposed Calendar and Planner search with visible controls and previous/next match navigation.
- Bundled the same handwriting font on Linux and Windows.
- Removed two redundant full pagination passes before the handbook first opens.
- Updated Linux, Windows and handbook sources, tests and documentation to 2.0.1.

Release artifacts, final checksums and the signed update manifest are generated only
after the remaining package and Windows VM checks have passed.

### Deutsch

- Start großer Datenbestände von quadratischen Suchen auf lineare Indizes umgestellt.
- Datenschutzfreundliche Startzeitmessung für Datenladen und Browserdarstellung ergänzt.
- Suche mit erhaltener Auswahl in Druck-, Export- und Sammellöschoptionen ergänzt.
- Kalender- und Planersuche sichtbar gemacht und um vorherigen/nächsten Treffer erweitert.
- Unter Linux und Windows dieselbe gebündelte Handschrift eingebaut.
- Zwei redundante Vollpaginierungen vor dem ersten Öffnen des Handbuchs entfernt.
- Linux-, Windows- und Handbuchquellen, Tests und Dokumentation auf 2.0.1 angehoben.

Freigabeartefakte, endgültige Prüfsummen und das signierte Aktualisierungsmanifest
entstehen erst nach den verbleibenden Paket- und Windows-VM-Prüfungen.

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
