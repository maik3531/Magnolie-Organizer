# Changelog / Änderungen

## 2.0.20 / Notes 1.0.15 — 2026-09-23

### English

- Improves Windows DAV discovery for separate calendar/address-book services and direct collection addresses, and makes authentication failures visible.
- Keeps the local Windows Contacts folder unselected until explicitly chosen.
- Completes DAV settings translations and makes successful calendar/contact synchronization notifications optional, off by default; errors remain visible.
- Adds the application-managed Windows account helper and account sign-in controls. **The complete sign-in workflow in the managed profile and Microsoft EAS data synchronization remain under development; these are not yet confirmed end-to-end features.**
- Includes the unchanged Magnolie Notes 1.0.15.

### Deutsch

- Verbessert die Windows-DAV-Erkennung für getrennte Kalender-/Adressbuchdienste und direkte Sammlungsadressen und zeigt Anmeldefehler an.
- Wählt den lokalen Windows-Kontaktordner erst nach ausdrücklicher Auswahl als Abgleichsquelle.
- Vervollständigt die Übersetzungen der DAV-Einstellungen. Erfolgsmeldungen beim Kalender-/Kontaktabgleich sind optional und standardmäßig aus; Fehler bleiben sichtbar.
- Ergänzt die von Magnolie verwaltete Windows-Kontenhilfe und Schaltflächen für die Kontoanmeldung. **Der vollständige Anmeldedurchlauf im verwalteten Profil und die Microsoft-EAS-Datenübertragung bleiben in Entwicklung und sind noch nicht durchgängig bestätigt.**
- Enthält die unveränderte Magnolie Notes 1.0.15.

## 2.0.19 / Notes 1.0.15 — 2026-09-19

### English

- Fixes repeated recurrence calculations and redraws in the monthly calendar by sharing a bounded date range between the calendar grid and appointment overview.
- Bundles the handbook and fallback fonts in the AppImage, and fixes opening the handbook from the setup assistant.
- Marks actual appointment durations and overlapping intervals in the daily calendar without blocking new entries in occupied hours.
- Restores SMS notifications while the Organizer is running or in the tray, independently of the separate daemon-only notification setting.
- Restores notification readiness and event delivery after a background-service restart.
- Adds readable call-action labels and the Magnolie chime for incoming-call alerts.
- Corrects caller-number delivery on newer Android versions, including numbers reported after the initial ringing event.
- Tolerates repeated leading plus signs such as `++49` when dialing and matching contacts.
- Removes the redundant own-device checkbox from paired-device settings.

### Deutsch

- Behebt wiederholte Serienberechnungen und Neuzeichnungen in der Monatsansicht durch einen gemeinsamen begrenzten Zeitraum für Kalenderblatt und Terminübersicht.
- Bündelt Handbuch und Ersatzschriften im AppImage und korrigiert den Handbuchstart aus der Ersteinrichtung.
- Markiert tatsächliche Termindauern und Überschneidungen im Tageskalender, ohne neue Einträge in belegten Stunden zu sperren.
- Behebt unterdrückte SMS-Meldungen bei laufendem Organizer und im Tray, unabhängig von der gesonderten Einstellung für Meldungen bei beendetem Organizer.
- Stellt Benachrichtigungsbereitschaft und Ereignisempfang nach einem Neustart des Hintergrunddienstes wieder her.
- Ergänzt lesbare Anrufschaltflächen und das Magnolie-Glockenspiel bei eingehenden Anrufen.
- Korrigiert die Rufnummernübermittlung unter neueren Android-Versionen, auch wenn die Nummer erst nach Beginn des Klingelns gemeldet wird.
- Toleriert mehrfach führende Pluszeichen wie `++49` beim Wählen und beim Kontaktabgleich.
- Entfernt die zusätzliche Bestätigung als eigenes Gerät aus den Einstellungen gekoppelter Geräte.

## 2.0.18 / Notes 1.0.14 — 2026-09-16

### English

- Fixes protected QR-code and portrait delivery in Windows WebView2 by keeping response bytes valid for the complete browser-consumption lifetime and adds native image decoding and dimension checks.
- Completes gettext metadata and removes remaining English, duplicated, or wrong-language fallbacks across all 19 Organizer and handbook translations.
- Includes all Thunderbird schema-23 and recurrence-import corrections, generic Nextcloud/CalDAV/CardDAV synchronization hardening, task hierarchy, setup-assistant, scaling, AppImage, and platform fixes developed after 2.0.17.
- Includes Magnolie Notes 1.0.14.

### Deutsch

- Behebt die Auslieferung geschützter QR- und Porträtbilder in Windows-WebView2, indem die Antwortbytes während der vollständigen Browserverarbeitung gültig bleiben, und ergänzt native Decodierungs- und Dimensionsprüfungen.
- Vervollständigt die Gettext-Metadaten und entfernt verbliebene englische, doppelte oder fremdsprachige Fallbacks in allen 19 Organizer- und Handbuchübersetzungen.
- Enthält alle nach 2.0.17 entwickelten Korrekturen für Thunderbird-Schema 23 und Serienimport, allgemeinen Nextcloud-/CalDAV-/CardDAV-Abgleich, Aufgabenhierarchie, Ersteinrichtung, Skalierung, AppImage und Plattformen.
- Enthält Magnolie Notes 1.0.14.

## 2.0.17 / Notes 1.0.13 — 2026-09-02

### English

- Fixes an address-book synchronization hang that was already present in 2.0.15 and earlier by bounding the final persistence acknowledgement with a timeout and failing without committing an incomplete baseline.
- Adds a native first-run assistant for language, regional defaults, data sources and optional integrations.
- Adds stable task hierarchy and ordering across the desktop editions and Personal Sync format 3, and preserves hierarchy through CalDAV VTODO `RELATED-TO` data where supported.
- Supports standards-compatible CalDAV and CardDAV services generically. Nextcloud remains supported; Baïkal is only one example of a compatible server and does not provide the separate Magnolienbaum WebDAV mailbox.
- Adds optional, explicitly confirmed contact imports over existing authenticated channels. Imports are previewed, bounded, read-only at the source and do not silently enable ongoing contact synchronization.
- Derives incoming-call origin only from a valid phone number and the configured regional context, and distinguishes known, unknown and unavailable origins without guessing.
- Writes total archives with data schema 3 and internal data model 7, while retaining readers for archive schemas 1 and 2. Personal Sync negotiates formats 1 through 3; format 3 adds task identity, parent and order fields.
- Updates the 19 supported translations for the new assistant, DAV, task, contact-import and call-origin text.

### Deutsch

- Behebt einen bereits in 2.0.15 und älteren Fassungen vorhandenen Hänger beim Adressbuchabgleich, indem die abschließende Speicherbestätigung eine feste Zeitgrenze erhält und bei deren Überschreitung keine unvollständige Baseline festgeschrieben wird.
- Ergänzt einen nativen Assistenten für die Ersteinrichtung von Sprache, regionalen Vorgaben, Datenquellen und optionalen Anbindungen.
- Ergänzt stabile Aufgabenhierarchie und -reihenfolge auf den Desktopplattformen und in Personal-Sync-Format 3; CalDAV-VTODO übernimmt die Hierarchie über `RELATED-TO`, soweit die Gegenseite dies unterstützt.
- Unterstützt standardkonforme CalDAV- und CardDAV-Dienste allgemein. Nextcloud bleibt unterstützt; Baïkal ist nur ein Beispiel für einen kompatiblen Server und stellt nicht das getrennte Magnolienbaum-WebDAV-Postfach bereit.
- Ergänzt optionale, ausdrücklich bestätigte Kontaktimporte über bestehende authentifizierte Verbindungen. Sie zeigen eine Vorschau, sind begrenzt und an der Quelle nur lesend und aktivieren keinen dauerhaften Kontaktabgleich.
- Ermittelt die Herkunft eingehender Anrufe nur aus einer gültigen Rufnummer und dem eingestellten Regionalkontext und unterscheidet bekannte, unbekannte und nicht verfügbare Herkunft ohne zu raten.
- Schreibt Gesamtarchive mit Datenschema 3 und internem Datenmodell 7; Archivschemata 1 und 2 bleiben lesbar. Personal Sync handelt die Formate 1 bis 3 aus; Format 3 ergänzt Aufgabenkennung, Elternbezug und Reihenfolge.
- Aktualisiert die 19 unterstützten Übersetzungen für Assistent, DAV, Aufgaben, Kontaktimport und Anrufherkunft.

## 2.0.16 / Notes 1.0.12 — 2026-09-01

### English

- Uses existing GNOME and KDE system accounts without requesting another login, with an optional bounded native Akonadi bridge.
- Hardens EDS and Akonadi synchronization against incomplete snapshots, concurrent status refreshes, read-only sources, and unintended remote deletion.
- Corrects SMS notification ownership, Desktop Entry escaping, AppImage host-helper startup, and recovery-snapshot retention.

### Deutsch

- Verwendet vorhandene GNOME- und KDE-Systemkonten ohne erneute Anmeldung und ergänzt eine optionale begrenzte native Akonadi-Brücke.
- Härtet EDS- und Akonadi-Abgleich gegen unvollständige Stände, parallele Statusabrufe, schreibgeschützte Quellen und unbeabsichtigte Fernlöschungen.
- Korrigiert SMS-Meldungszuständigkeit, Desktop-Entry-Escaping, AppImage-Hosthelfer und die Aufbewahrung von Wiederherstellungsständen.

## 2.0.15 / Notes 1.0.12 — 2026-09-01

### English

- Gives recovery-point and automatic-backup retention fields the full available width, shortens their labels, and saves valid values immediately without redundant confirmation buttons.
- Makes disabled leather buttons clearly readable with a paper background and dark text while preserving their disabled state.

### Deutsch

- Gibt den Feldern für Wiederherstellungspunkte und aufzubewahrende Sicherungen die volle Breite, kürzt ihre Beschriftungen und speichert gültige Werte sofort ohne überflüssige Bestätigungsschaltflächen.
- Stellt deaktivierte Lederknöpfe mit Papierhintergrund und dunkler Schrift klar lesbar dar, ohne ihren deaktivierten Zustand aufzuheben.

## 2.0.15 / Notes 1.0.11 — 2026-09-01

### English

- Keeps both calendar day pages aligned with or without weather, after changing tabs, at smaller window sizes, and while scrolling the hour grids.
- Synchronizes the monthly view with the selected day at month boundaries and gives the anniversary list a narrow, unobtrusive scrollbar.
- Gives automatic cloud backup in Magnolie Notes its own consistent paper section with the established Magnolie typography and controls.

### Deutsch

- Hält beide Seiten der Kalender-Tagesansicht mit und ohne Wetter, nach Registerwechseln, bei kleineren Fenstern und beim Rollen der Stundenraster ausgerichtet.
- Synchronisiert die Monatsansicht an Monatsgrenzen mit dem gewählten Tag und gibt der Jahrestagsliste eine schmale, unaufdringliche Scrollleiste.
- Gestaltet die automatische Cloud-Sicherung in Magnolie Notes als eigenen einheitlichen Papierabschnitt mit der bestehenden Magnolie-Typografie und Bedienung.

## 2.0.14 / Notes 1.0.10 — 2026-08-31

### English

- Keeps plaintext personal QR and portrait files out of Linux and Windows packages by routing their versioned obfuscation containers through native readers.
- Restores the native AppImage graphics path, retains an explicit compatibility fallback, and expands release audits for every package format.
- Adds neutral CLI short options, permanently accepted German and English long options, localized help, and consistent localized manual pages.
- Improves the calendar day layout, connected Magnolie Notes status, Personal Sync selection, and the version-specific About page on Linux and Windows.
- Adds isolated RPM profiles for Fedora, openSUSE, Mageia, OpenMandriva, PCLinuxOS, and ROSA while retaining Fedora 42 as the release gate.
- Hardens Windows VM result reporting, handbook navigation and printing, and corrects incomplete or inverted translations across all 19 catalogs.
- Adds encrypted manual and automatic cloud-folder backups across Linux, Windows and Magnolie Notes, including portable Android archives and guarded retention.

### Deutsch

- Hält persönliche QR- und Porträtdateien im Klartext aus Linux- und Windows-Paketen heraus, indem versionierte Obfuskationscontainer über native Leser ausgeliefert werden.
- Stellt den nativen AppImage-Grafikpfad wieder her, behält einen ausdrücklichen Kompatibilitätsrückfall bei und erweitert die Freigabeprüfungen für alle Paketformate.
- Ergänzt sprachneutrale CLI-Kurzoptionen, dauerhaft akzeptierte deutsche und englische Langoptionen, lokalisierte Hilfe und konsistente lokalisierte Manpages.
- Verbessert Kalender-Tagesansicht, verbundenen Magnolie-Notes-Status, Personal-Sync-Auswahl und die versionsbezogene Über-Seite unter Linux und Windows.
- Ergänzt getrennte RPM-Profile für Fedora, openSUSE, Mageia, OpenMandriva, PCLinuxOS und ROSA; Fedora 42 bleibt das Freigabegate.
- Härtet Windows-VM-Ergebnisübermittlung, Handbuchnavigation und -druck und korrigiert unvollständige oder vertauschte Übersetzungen in allen 19 Katalogen.
- Ergänzt verschlüsselte manuelle und automatische Cloudordnersicherungen unter Linux, Windows und Magnolie Notes, einschließlich portabler Android-Archive und geschützter Aufbewahrung.

## 2.0.13 / Notes 1.0.9 — 2026-08-30

### English

- Aligns notebook lines with the measured font baseline and actual WebKit line spacing for both fonts, all three sizes, text scaling and long wrapped notes.
- Keeps pairing, file, clipboard, SMS and call notifications native whenever the background service is enabled, independently of the Organizer window state.
- Allows pairing, file and clipboard decisions directly from native notification actions and applies received clipboard text without opening Organizer.
- Adds a guided contact-transfer workflow with previews, source-aware choices and a selectable KDE Connect receive target.
- Hardens retention and recovery handling across Linux, Windows and Android, including deterministic journal recovery after interrupted writes.
- Adds signed, checksum-bound Linux and Windows updates with atomic replacement and rollback on failed AppImage restarts.
- Expands release validation for translations, notification fallbacks, update security, package reproducibility and installed Android upgrades.

### Deutsch

- Richtet Notizlinien an der gemessenen Schriftgrundlinie und dem tatsächlichen WebKit-Zeilenabstand aus, für beide Schriften, alle drei Größen, Textskalierung und lange umgebrochene Notizen.
- Zeigt Paarungs-, Datei-, Zwischenablage-, SMS- und Anrufereignisse bei aktivem Hintergrunddienst unabhängig vom Fensterzustand immer nativ an.
- Ermöglicht Paarungs-, Datei- und Zwischenablageentscheidungen direkt über native Meldungsaktionen und übernimmt empfangenen Text ohne Organizerfenster.
- Ergänzt eine geführte Kontaktübernahme mit Vorschau, quellenabhängigen Auswahlmöglichkeiten und wählbarem KDE-Connect-Empfangsziel.
- Härtet Aufbewahrung und Wiederherstellung unter Linux, Windows und Android, einschließlich deterministischer Journalwiederherstellung nach unterbrochenen Schreibvorgängen.
- Ergänzt signierte, prüfsummengebundene Linux- und Windows-Aktualisierungen mit atomarem Ersetzen und Rücknahme nach fehlgeschlagenem AppImage-Neustart.
- Erweitert das Freigabegate für Übersetzungen, Meldungsrückfälle, Updatesicherheit, reproduzierbare Pakete und installierte Android-Aktualisierungen.

## 2.0.12 / Notes 1.0.9 — 2026-08-30

### English

- Fixed notebook paper lines drifting away from text when system font scaling is enabled.
- Improved background-service visibility, reminder handling and native notifications for received files, SMS messages and calls.
- Hardened Nextcloud synchronization, settings handling and connected-phone status updates.
- Corrected Whatsie links and strengthened native notification dependencies in Debian, RPM and AppImage packages.

### Deutsch

- Behebt den Versatz zwischen Notiztext und Papierlinien bei aktivierter Systemschriftvergrößerung.
- Verbessert Sichtbarkeit und Erinnerungsverarbeitung des Hintergrunddienstes sowie native Hinweise auf empfangene Dateien, SMS und Anrufe.
- Härtet Nextcloud-Synchronisierung, Einstellungsverarbeitung und Statusmeldungen verbundener Telefone.
- Korrigiert Whatsie-Verknüpfungen und vervollständigt native Benachrichtigungsabhängigkeiten in Debian-, RPM- und AppImage-Paketen.

## 2.0.11 / Notes 1.0.9 — 2026-08-29

### English

- Made the background-service permissions collapsible, added All/None controls, and moved them to the start of the Security page.
- Completed the German translation of the Nextcloud connection test.
- Fixed startup through the N4 symlink path.
- Added the required Debian `Breaks`/`Replaces` relationship while preserving upgrades from 2.0.10.
- Assigned RPM ownership of the installed directories explicitly.
- Added the N7 full validation and a real 2.0.10-to-2.0.11 upgrade gate in both package orders.
- Made the next reminder calculation efficient without scanning every day of long recurring series.
- Synchronized the current web UI, catalogs, handbook, and Windows version metadata.

### Deutsch

- Macht die Hintergrunddienstrechte einklappbar, ergänzt Alle-/Keine-Schalter und setzt sie an den Anfang der Sicherheitsseite.
- Vervollständigt die deutsche Übersetzung des Nextcloud-Verbindungstests.
- Korrigiert den Start über den N4-Symlinkpfad.
- Ergänzt die notwendigen Debian-Beziehungen `Breaks`/`Replaces` und bewahrt Aktualisierungen von 2.0.10.
- Weist die installierten Verzeichnisse in RPM-Paketen ausdrücklich zu.
- Ergänzt die N7-Vollprüfung und ein reales Upgradegate von 2.0.10 auf 2.0.11 in beiden Paketreihenfolgen.
- Berechnet die nächste Weckzeit effizient, ohne lange Terminserien Tag für Tag zu durchlaufen.
- Synchronisiert aktuelle Weboberfläche, Kataloge, Handbuch und Windows-Versionsmetadaten.

## 2.0.10 / Notes 1.0.9 — 2026-08-29

### English

- Fixes a file conflict between the Organizer and handbook Debian packages.
- Installs the handbook crash reporter in a private package path.
- Safely takes over the old path when upgrading from handbook 2.0.9.
- Prevents future releases containing overlapping Debian package files.

### Deutsch

- Behebt einen Dateikonflikt zwischen den Debian-Paketen von Organizer und Handbuch.
- Installiert den Absturzmelder des Handbuchs in einem privaten Paketpfad.
- Ergänzt eine sichere Übernahme des alten Pfads bei Aktualisierungen von Handbuch 2.0.9.
- Verhindert künftige Veröffentlichungen mit überlappenden Debian-Paketdateien.

## 2.0.9 / Notes 1.0.9 — 2026-08-29

### English

- Added an optional secure Linux background service with native confirmations.
- Added local crash reporting for Linux, the handbook, Windows and Android.
- Corrected calendar and contact handling, including zero-duration appointments and structured EXDATE/RDATE values.
- Improved AppImage font, theme and CPU compatibility.
- Corrected the Android `connectedDevice` foreground-service declaration.
- Completed all manually maintained translations and the handbook.

The Windows artifacts are explicitly approved unsigned Linux cross-builds. Their
source, native, package and installer audits pass, but Authenticode signing and a
Windows VM runtime test were unavailable.

### Deutsch

- Ergänzt einen optionalen sicheren Linux-Hintergrunddienst mit nativen Bestätigungen.
- Ergänzt lokale Absturzberichte für Linux, Handbuch, Windows und Android.
- Korrigiert Kalender- und Kontaktverarbeitung einschließlich Termine ohne Dauer und strukturierter EXDATE-/RDATE-Werte.
- Verbessert Schrift-, Theme- und CPU-Kompatibilität des AppImages.
- Korrigiert die Android-Foreground-Service-Deklaration `connectedDevice`.
- Vervollständigt alle manuell gepflegten Übersetzungen und das Handbuch.

Die Windows-Artefakte sind ausdrücklich freigegebene, unsignierte
Linux-Cross-Builds. Quellen-, native, Paket- und Installerprüfungen bestehen;
Authenticode-Signierung und ein Laufzeittest in einer Windows-VM waren nicht verfügbar.

## 2.0.8 / Notes 1.0.8 — 2026-08-27

### English

- Fixed Thunderbird calendar takeover so one malformed SQLite row no longer hides later appointments, biweekly Monday series retain their interval, and annual anniversaries keep their master identity for duplicate removal.
- Added registry-gated Thunderbird network-calendar caches while excluding deleted, disabled and orphaned cache entries; EXDATE, RDATE and moved occurrences now remain exact.
- Isolated the AppImage OpenSSL providers and GTK theme from the host, restored its complete PyOpenSSL runtime, and prevented optional KDE Connect initialization from blocking startup on Arch-based systems.
- Made a fresh Nextcloud setup enable calendar/contact synchronization by default and prevents silently saving credentials while every Nextcloud function is disabled.
- Stabilized the settings dialog, preserved scroll position only on the same page, and added a selectable KDE Connect receive folder with safe clipboard fallback.
- Added proximity-based screen-off handling during Android calls and hardened listener, wake-lock, outgoing-call cancellation, service shutdown and reconnect lifecycles.

The Windows artifacts are explicitly approved unsigned Linux cross-builds. Their
source, native, package and installer audits pass, but Authenticode signing and a
Windows VM runtime test were unavailable.

### Deutsch

- Korrigiert die Thunderbird-Kalenderübernahme: Eine fehlerhafte SQLite-Zeile blendet nachfolgende Termine nicht mehr aus, vierzehntägige Montagsserien behalten ihr Intervall und jährliche Jahrestage ihre Serienkennung zur Dublettenbereinigung.
- Ergänzt registrierungsgebundene Thunderbird-Netzkalender-Caches und schließt gelöschte, deaktivierte sowie verwaiste Cacheeinträge aus; EXDATE, RDATE und verschobene Instanzen bleiben exakt erhalten.
- Isoliert OpenSSL-Provider und GTK-Theme des AppImages vom Wirt, vervollständigt dessen PyOpenSSL-Laufzeit und verhindert, dass die optionale KDE-Connect-Initialisierung den Start auf Arch-basierten Systemen blockiert.
- Aktiviert bei einer neuen Nextcloud-Einrichtung Kalender und Kontakte voreingestellt und verhindert das stille Speichern von Zugangsdaten, wenn sämtliche Nextcloud-Funktionen ausgeschaltet sind.
- Stabilisiert den Einstellungsdialog, bewahrt die Rollposition nur auf derselben Seite und ergänzt einen wählbaren KDE-Connect-Empfangsordner mit sicherem Zwischenablage-Rückfall.
- Ergänzt das sensorabhängige Abschalten des Android-Bildschirms bei Gesprächen und härtet Lauscher-, Sperrbit-, Wählabbruch-, Dienstende- und Wiederverbindungsabläufe.

Die Windows-Artefakte sind ausdrücklich freigegebene, unsignierte
Linux-Cross-Builds. Quellen-, native, Paket- und Installerprüfungen bestehen;
Authenticode-Signierung und ein Laufzeittest in einer Windows-VM waren nicht verfügbar.

## 2.0.7 / Notes 1.0.7 — 2026-08-27

### English

- Added independently selectable Bluetooth hands-free routing without coupling it to the encrypted RFCOMM data fallback.
- Added secure, opt-in KDE Connect clipboard and file reception with peer pinning, confirmation controls, private staging and safe downloads.
- Extended the exact phone-status protocol with v3 reporting the Magnolie Notes version while preserving v1 and v2.
- Added a guided five-part Magnolie Notes first run and made selected read-only notifications active from app selection plus Android notification access, without a redundant switch.
- Clarified SMS settings and history deletion in the interface and handbook.

The Windows artifacts are explicitly approved unsigned Linux cross-builds. Their
source, native, package and installer audits pass, but Authenticode signing and a
Windows VM runtime test were unavailable.

### Deutsch

- Ergänzt eine unabhängig wählbare Bluetooth-Freisprechverbindung, ohne sie an den verschlüsselten RFCOMM-Datenrückfall zu koppeln.
- Ergänzt den sicheren, optionalen KDE-Connect-Empfang für Zwischenablage und Dateien mit Peer-Bindung, Bestätigungen, privater Zwischenablage und sicheren Downloads.
- Erweitert das exakte Telefonstatusprotokoll um v3 mit der Magnolie-Notes-Version; v1 und v2 bleiben unverändert.
- Ergänzt eine geführte fünfteilige Ersteinrichtung in Magnolie Notes; ausgewählte Nur-Lese-Meldungen werden ohne redundanten Schalter durch Appwahl und Android-Systemzugriff aktiv.
- Verdeutlicht SMS-Einstellungen und das Löschen von Verläufen in Oberfläche und Handbuch.

Die Windows-Artefakte sind ausdrücklich freigegebene, unsignierte
Linux-Cross-Builds. Quellen-, native, Paket- und Installerprüfungen bestehen;
Authenticode-Signierung und ein Laufzeittest in einer Windows-VM waren nicht verfügbar.

## 2.0.6 / Notes 1.0.6 — 2026-08-26

### English

- Birthdays and anniversaries with no known year are now stored without a placeholder year and displayed without an age or year.
- Explicitly marked legacy values are migrated to the yearless form; genuine dates in 1604, 1900, or 2000 remain complete dates.
- Yearless birthdays round-trip directly through vCard; calendar exports preserve them without treating the technical ICS start year as a birth year.
- Google birthday calendar imports remain restored from the 2.0.5 baseline.
- Magnolie Notes remains at version 1.0.6.

The external QEMU `autopkgtest` remains unavailable; the local package, cross-platform, Fedora, and release checks are run separately.

### Deutsch

- Geburtstage und Jahrestage ohne bekanntes Jahr werden jetzt ohne Platzhalterjahr gespeichert und ohne Alter oder Jahr angezeigt.
- Ausdrücklich markierte Altwerte werden in die jahrfreie Form migriert; echte Daten aus 1604, 1900 oder 2000 bleiben vollständige Daten.
- Jahrfreie Geburtstage bleiben beim vCard-Rundlauf direkt erhalten; Kalenderexporte bewahren sie, ohne das technisch nötige ICS-Startjahr als Geburtsjahr zu behandeln.
- Der mit 2.0.5 wiederhergestellte Import von Google-Geburtstagskalendern bleibt erhalten.
- Magnolie Notes bleibt bei Version 1.0.6.

Das externe QEMU-`autopkgtest` bleibt nicht verfügbar; die lokalen Paket-, plattformübergreifenden, Fedora- und Release-Prüfungen laufen getrennt.

## 2.0.5 / Notes 1.0.6 — 2026-08-26

### English

- Added secure, short-lived QR pairing for Magnolienbaum across Linux and Android.
- Hardened phone transports, browser launching, update verification and release metadata handling.
- Preserved complex recurring calendar fields, task due dates and per-entry contact parameters during synchronization and round trips.
- Improved conflict bounds, deletion acknowledgements, encrypted reminder logs and recovery-journal retention.
- Added a constrained Windows shell launcher, oversized-note safeguards and standalone localized handbook variants.
- Added explicit peer confirmation before Android QR pairing and released Magnolie Notes 1.0.6.

### Deutsch

- Sichere, kurzlebige QR-Paarung für den Magnolienbaum unter Linux und Android ergänzt.
- Telefontransporte, Browserstart, Aktualisierungsprüfung und Release-Metadaten gehärtet.
- Komplexe Kalender-Serienfelder, Aufgabenfälligkeiten und eintragsgebundene Kontaktparameter bleiben bei Abgleich und Rundlauf erhalten.
- Konfliktgrenzen, Löschbestätigungen, verschlüsselte Erinnerungsprotokolle und Journal-Aufbewahrung verbessert.
- Begrenzten Windows-Shellstarter, Schutz für übergroße Notizen und eigenständige lokalisierte Handbuchvarianten ergänzt.
- Explizite Gegenstellenbestätigung vor Android-QR-Paarung ergänzt und Magnolie Notes 1.0.6 veröffentlicht.

## 2.0.4 / Notes 1.0.5 — 2026-08-24

### English

- Restored WebKit compositing and page-turn animations while improving startup responsiveness.
- Made the AppImage work on Wayland through XWayland while retaining the GLIBC 2.35 compatibility ceiling.
- Removed the visible Language & region settings tab while retaining automatic locale selection and the Linux command-line override.
- Deduplicated matching EDS and ICS recurring all-day events and made their source labels clearer.
- Optimized Windows startup lease cleanup by avoiding payload hashing.
- Updated the complete handbook, packages, catalogs, tests and platform copies to 2.0.4; Magnolie Notes remains at 1.0.5.

### Deutsch

- WebKit-Compositing und Umblätteranimationen wurden wiederhergestellt und zugleich die Reaktionsfähigkeit beim Start verbessert.
- Das AppImage läuft unter Wayland über XWayland und behält dabei seine GLIBC-2.35-Kompatibilitätsgrenze.
- Die sichtbare Einstellungsseite „Sprache & Region“ wurde entfernt; automatische Gebietsschemawahl und Linux-Kommandozeilenoption bleiben erhalten.
- Übereinstimmende wiederkehrende ganztägige EDS- und ICS-Termine werden nicht mehr doppelt angezeigt und tragen klarere Quellenbezeichnungen.
- Die Windows-Bereinigung von Start-Leases vermeidet nun das Hashen der Nutzlast.
- Vollständiges Handbuch, Pakete, Kataloge, Tests und Plattformkopien wurden auf 2.0.4 angehoben; Magnolie Notes bleibt bei 1.0.5.

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
