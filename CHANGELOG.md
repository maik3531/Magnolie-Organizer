# Changelog / Änderungen

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
