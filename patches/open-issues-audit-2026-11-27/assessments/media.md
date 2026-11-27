# Einzelbewertungen: media

Die Aussagen unterscheiden Quellbefund, vorbereiteten Patch und noch offene installierte Abnahme.

## [#128](https://github.com/maik3531/Magnolie-Organizer/issues/128) — Notes: automatischen Abgleich auf freigegebene aktive Transporte erweitern

**Bewertung:** Funktion oder Integration noch offen

Die transportübergreifende Automatik ist weiterhin ein echter Funktionsrest. Ein vorbereiteter auto_connection-Vertrag ist noch keine angebundene Notes-Laufzeit.

**Bereits umgesetzt / belegt:** PersonalAutoSync enthält Version-8-Aushandlung, auto_connection und einen kompatiblen auto_wifi-Rückfall. Die bestehende WLAN-Automatik prüft eigene Geräte, beidseitige Modulfreigabe, aktive Läufe und Änderungs-/Zeitkriterien.

**Noch offen:** Den ausgehandelten aktiven Transport einschließlich tatsächlich freigegebenem Bluetooth durch Scheduler, Queue und Empfänger führen; vorhandene Einwilligungen und Altgeräteverhalten erhalten. Notes verwendet aktuell weiter WIFI/auto_wifi. Keine pauschale Freigabe unbekannter Transporte.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen; eigenständiger transportübergreifender Implementierungsauftrag. Nicht allein wegen vorhandener Parser-/Statusunterstützung schließen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PersonalAutoSync.kt](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PersonalAutoSync.kt): Vorbereitete Aushandlung/Trigger; eigener Helfer allein aktiviert keinen Lauf.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L115](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L115): shouldStartPersonalSyncOnSecureWifi verweigert jeden Transport außer WIFI.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L2010](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L2010): enqueuePersonalSync weist automatische persönliche Synchronisation ohne WLAN ab.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/notes-device-status-ui.md#L30](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/notes-device-status-ui.md#L30): auto_connection in Statusmetadaten erweitert ausdrücklich nicht die bisherige Transportpolitik.

## [#148](https://github.com/maik3531/Magnolie-Organizer/issues/148) — Notes-Kopfzeile: echte Sync-Verfügbarkeit und Rechnerverbindung vervollständigen

**Bewertung:** Funktion oder Integration noch offen

Kopfzeile und Rechnerwechsel existieren; die verlangte wirkliche Sync-Verfügbarkeit und vollständige Verbindungsbedienung sind noch nicht umgesetzt.

**Bereits umgesetzt / belegt:** TelefonKopf blendet manuellen Sync bei Automatik aus, listet gekoppelte Rechner und markiert den gewählten. selectComputer beendet alte Transport-/Pairingkontexte und setzt den ausgewählten Rechner neu.

**Noch offen:** Die Kopfzeile muss aktuelle Verbindung und tatsächlich zulässige Module/Grants berücksichtigen. Ihr Sync-Knopf hängt derzeit nur an manual, own_device und remote_own_device; eine eigene Trennaktion fehlt dort. Mehrere gespeicherte Rechner sind nicht mehrere gleichzeitige Sitzungen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen; Kopfzeilenlogik mit vorhandener nativer Berechtigungssicht verbinden und Wechsel/Trennung gezielt prüfen. Keine gleichzeitigen Sitzungen aus einer bloßen Rechnerliste ableiten.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/TelefonKopf.kt#L27](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/TelefonKopf.kt#L27): Sync-Bedingung und enabled verwenden nur Modus/Eigengerät; Dropdown bietet Auswahl und Hinzufügen, keine gesonderte Trennaktion.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L2694](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L2694): selectComputer schließt den bisherigen Transport, wechselt den gespeicherten Peer und reconnectet.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonModelle.kt#L119](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonModelle.kt#L119): Verbindung, modulbezogene Freigaben und Shared-Readiness sind bereits getrennte Zustandsfelder.

## [#149](https://github.com/maik3531/Magnolie-Organizer/issues/149) — KDE Connect: Maus- und Tastaturfernsteuerung anbinden

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die ursprüngliche Ferneingabe und der später gemeldete Linux-Startpfadfehler sind im aktuellen Code umgesetzt bzw. korrigiert. Verblieben ist die konsolidierbare Nachprüfung/Bedienungsabnahme.

**Bereits umgesetzt / belegt:** Linux und Windows besitzen native Eingabeziele und Besitz-/Widerrufslogik. Der IPCServer-Setter bindet GUI-Bereitschaft auch bei später Backend-Zuweisung; ein echter Socket-/Lease-Regressionsfall liegt vor. Die Oberfläche bietet ausschließlich eingehende Handy→Rechner-Steuerung und verbirgt nicht verfügbare Empfänger.

**Noch offen:** Die jüngste Mint-Nutzerprobe war vor der dokumentierten Setter-Korrektur negativ. Eine nachfolgende konkrete Paket-/Nutzerprobe dieses korrigierten Startpfads sowie die gemeinsame Handbuch-/Plattformabnahme sind in der Diskussion nicht belegt; keine erneute Implementierung des bereits korrigierten Fehlers nötig.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Mit #153 konsolidieren: dort die korrigierte Ferneingabe als implementiert und die noch fehlende native Nachprüfung/Handbuchabnahme als eigenen Rest übernehmen; anschließend #149 als zusammengeführt schließen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_hintergrund.py#L1315](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_hintergrund.py#L1315): Späte Backend-Zuweisung bindet permitted=self.gui_input_ready.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/pruefungen/test_hintergrunddienst.py#L284](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/pruefungen/test_hintergrunddienst.py#L284): test_late_input_backend_allows_unlocked_tray_but_stops_on_lock_close_and_expiry prüft den tatsächlichen Startpfad über IPC.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L31160](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L31160): baueKdeEingabe enthält nur eingehende Steuerung, Capability-Ausblendung und System-KDE-Rechte.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeInputState.cs](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeInputState.cs): Native Zielbindung gibt gehaltene Eingaben bei Disarm/Widerruf frei.
- [https://github.com/maik3531/Magnolie-Organizer/issues/149#issuecomment-6138777208](https://github.com/maik3531/Magnolie-Organizer/issues/149#issuecomment-6138777208): Jüngste Meldung benennt bestätigte Ursache, Korrektur und präzisierte Richtung; keine spätere positive Mint-Abnahme im Issue.

## [#153](https://github.com/maik3531/Magnolie-Organizer/issues/153) — KDE Connect: Präsentationsmodus und konfigurierte Befehle integrieren

**Bewertung:** Funktion oder Integration noch offen

Präsentationsmodus und konfigurierte KDE-Befehle sind weiterhin nicht als vollständige Produktfunktion angeschlossen.

**Bereits umgesetzt / belegt:** Linux presenter_body und Windows KdeInputProtocol.Pointer validieren begrenzte Zeigerpakete. Maus/Tastatur ist als eigener empfangender Pfad umgesetzt.

**Noch offen:** Presenter-Pakete werden im untersuchten Direktbackend weder als produktive Fähigkeit angekündigt noch im aktiven Paketdispatch verarbeitet. Eine Anbindung zum Laden/Anzeigen/Auslösen konfigurierter KDE-Runcommand-IDs ist im geprüften Linux-/Windows-Produktbestand nicht vorhanden. Es fehlen Oberfläche, native Berechtigungs-/Lebenszyklusintegration und Abnahme.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leitissue für KDE-Bedienintegration behalten und den kleinen Rest aus #149 aufnehmen. Parserpräsenz nicht als fertige Funktion werten.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kde_input.py#L53](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kde_input.py#L53): Presenter-Konstante/Parser sind Vorbereitung, kein angeschlossener Presenter.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3851](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3851): identity_packet kündigt Eingabe/Digitizer/Medien, aber keinen Presenter-/Runcommand-Pfad an.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeConnectDirectBackend.cs#L1221](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeConnectDirectBackend.cs#L1221): Aktiver Dispatch behandelt Request/KeyboardState, nicht Presenter.
- [https://github.com/maik3531/Magnolie-Organizer/issues/153](https://github.com/maik3531/Magnolie-Organizer/issues/153): Verbindliche Befehls-ID-Anbindung statt einer neu erfundenen Shell-Schnittstelle; native Linux-/Windows-Prüfung gefordert.

## [#168](https://github.com/maik3531/Magnolie-Organizer/issues/168) — KDE-Kopplung: Zeichenblatt bei erster und erneuter Kopplung automatisch bereitstellen

**Bewertung:** Gemeldeter Fehler noch nicht bestätigt

Der jüngste Windows-versus-Linux-Vergleich ist noch nicht aufgeklärt. Der Code belegt angebotene Digitizer-Fähigkeiten, aber nicht das automatische Anzeigen des Android-Zeichenblatts.

**Bereits umgesetzt / belegt:** Beide Direktbackends kündigen Digitizer-Sitzungs-/Ereignisempfang an und binden eine aktuelle bestätigte Gegenstelle. Linux prüft deren ausgehende Fähigkeiten; die UI bindet eine verfügbare Quelle an die aktive Zeichenfläche.

**Noch offen:** Erste und erneute Kopplung auf denselben tatsächlichen KDE-Connect-Versionen vergleichen: Original-Identity, Capability-Reihenfolge, Plugin-/Gerätezustand und Zeitpunkt. Der ältere Hinweis auf Androids Tablet-Voreinstellung erklärt den späteren konkreten Plattformunterschied nicht abschließend.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als eng umrissenen Plattformvergleich führen. Ohne native Vergleichsspur keinen neuen Capability- oder Pairingpatch erfinden; vorhandene Paarungen nicht für die Diagnose zurücksetzen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3215](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3215): Digitizer-Auswahl verlangt bestätigte aktive Gegenstelle und beide ausgehenden Pakettypen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3851](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kdeconnect.py#L3851): Digitizer-Session/Event werden in der eigenen Identity angekündigt.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeConnectProtocol.cs#L169](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeConnectProtocol.cs#L169): Auch Windows kündigt die entsprechenden Digitizer-Empfangspakete an.
- [https://github.com/maik3531/Magnolie-Organizer/issues/168#issuecomment-6461548726](https://github.com/maik3531/Magnolie-Organizer/issues/168#issuecomment-6461548726): Jüngster Nutzervergleich: Windows bietet das Zeichenblatt automatisch, Linux erst nach manueller Aktivierung; nicht durch ältere Android-Erklärung erledigt.

## [#245](https://github.com/maik3531/Magnolie-Organizer/issues/245) — Bildschirm: Spiegelung und echten Zweitmonitor auf Telefon oder Tablet ergänzen

**Bewertung:** Funktion oder Integration noch offen

Handy→PC-Spiegelung, PC→Handy-Ansicht und echter zusätzlicher Monitor sind verschiedene Fortschrittsstände. Das Gesamtissue ist weiterhin relevant.

**Bereits umgesetzt / belegt:** Eigene Linux-/Windows-Viewer, Notes-MediaProjection und separate Screen-Steuer-/Datenkanäle sind vorhanden. Die jüngste private Paketkomposition und erhaltene Notes-Paarung wurden isoliert geprüft. Für PC→Handy gibt es einen privaten Portal/PipeWire-/JPEG-Pfad; KWin-Ausgangsbeobachtung ist vorbereitet.

**Noch offen:** Realer selbst bedienter Bild-/Sperrtest des exakten Paketpaars; Linux-desktop_session-Befund nachvollziehbar klären. Produktive Desktop→Handy-Anbindung und bei Erweiterung eindeutiger zusätzlicher Ausgang, Fensterbewegung sowie beobachtetes Entfernen. Die tatsächliche Portalroute/Beobachterintegration ist noch nicht freigegeben. Private Zweig-/Paketnachweise sind kein Nachweis, dass jede Folgeänderung im aktuellen Hauptquellstand aktiviert ist.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leitissue behalten; #727 vollständig als konkreten KDE-Zweitmonitor-Unterabschnitt übernehmen und danach #727 als zusammengeführt schließen. AirPlay #721 wegen eigener Mac-/iPhone-Implementierung und Abnahme separat lassen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_screen_window.py#L224](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_screen_window.py#L224): Eigener Viewer samt begrenzter Bildprüfung und Sitzungslaufzeit ist implementiert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/desktop-screen-send-v1.md#L132](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/desktop-screen-send-v1.md#L132): Produkt prüft die KDE-Route noch nicht und startet den Ausgangsbeobachter nicht; reale Zusatzmonitor-Abnahme bleibt erforderlich.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1077](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1077): Private Integrationszweige und aktuelle Grenzen von Paket-, Update- und tatsächlichem Bildtest getrennt dokumentiert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/245#issuecomment-7216893749](https://github.com/maik3531/Magnolie-Organizer/issues/245#issuecomment-7216893749): Installierter Diagnose-Folge-DEB und wiederhergestellte signierte Notes-APK belegen noch keine physische Bildfreigabe oder Ursache des Sitzungsbefunds.

## [#269](https://github.com/maik3531/Magnolie-Organizer/issues/269) — Telefondateisystem als benanntes Netzlaufwerk mit korrekten Speicherwerten darstellen

**Bewertung:** Funktion oder Integration noch offen

Ein nutzbarer SFTP-Mount ist vorhanden; das geforderte benannte Netzlaufwerk mit belastbarer Telefonkapazität ist damit noch nicht geliefert.

**Bereits umgesetzt / belegt:** Linux verwendet eigenen sshfs-Mount mit Zertifikatsbindung; Windows nutzt einen WinFsp-Verzeichnismount und kontrolliert dessen eigenen Volumennamen. Die bestehende Bereitstellung und sichere Aufräumlogik sind echte Funktionalität.

**Noch offen:** Native Laufwerks-/Dateimanagerdarstellung mit Telefon-/Modellname sowie echte belegte Speicherwerte auf beiden Plattformen. Windows setzt derzeit einen zufälligen Magnolie-Volumennamen; Linux öffnet den Mountordner. Die gemeldeten 1000-GiB-SFTP-Platzhalter dürfen nicht als Telefonkapazität umbenannt werden.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen. Laufwerksintegration und tatsächliche Kapazitätsquelle gemeinsam planen; keine kosmetische Zahl-/Labeländerung als vollständige Lösung ausgeben.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kde_filesystem.py#L126](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_kde_filesystem.py#L126): sshfs wird unter einem eigenen files-Verzeichnis gemountet und dieses im Dateimanager geöffnet.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeFilesystem.cs#L194](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/KdeFilesystem.cs#L194): Verzeichnismount mit zufälligem Magnolie-Label; anschließend show(point).
- [https://github.com/maik3531/Magnolie-Organizer/issues/269#issuecomment-6570825986](https://github.com/maik3531/Magnolie-Organizer/issues/269#issuecomment-6570825986): Jüngster Nutzerbefund fordert weiterhin echtes Laufwerk statt bloßem Ordner sowie native Namen/Kapazitäten.

## [#302](https://github.com/maik3531/Magnolie-Organizer/issues/302) — Notes/Organizer: geschützter Restore ohne Papierkorb, historische Zielrechte und physische Gesamtabnahme – Rest #300

**Bewertung:** Funktion oder Integration noch offen

Viele Restore-Bausteine sind bereits implementiert, aber der produktive historische Wiederherstellungspfad und die physische Gesamtprüfung fehlen weiterhin.

**Bereits umgesetzt / belegt:** Geschützte ursprüngliche Batches, historische Zielprüfung, Auswahl-/Kandidatenbelege, native Writer-Primitive und interner Notes-Restore existieren. Linux besitzt inzwischen einen beschränkten historischen Prepare-IPC-Pfad; Linux/Windows haben private GUI-Writer-Einstiege mit Buch-/Speicherautorität.

**Noch offen:** Historische PreWrite-/ActualSave-/Confirm-Übergabe über den echten Daemon/GUI-Besitzer vollständig verbinden, Original-Save-ACK und terminale Bestätigung nachweisen und historische/public mixed Readiness erst danach freigeben. Notes↔Organizer und Restore ohne Papierkorb nativ insgesamt abnehmen; einzelne bestandene Teilgruppen ersetzen den dokumentierten fehlgeschlagenen/ausstehenden Gesamtlauf nicht.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen und Restbeschreibung auf den tatsächlichen Writer-/IPC-Anschluss und die Gesamtprüfung verengen. Nicht erneut bereits vorhandene Restore-/Journalprimitive implementieren.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_hintergrund.py#L2095](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_hintergrund.py#L2095): Historischer IPC besitzt review und prepare; Prepare liefert noch keine tatsächliche Speicherung oder Confirm.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L26757](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L26757): Privater historischer GUI-Writer ausdrücklich nicht an öffentliches Tool/IPC angeschlossen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/BridgeDispatcher.cs#L1097](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/BridgeDispatcher.cs#L1097): Privater PreparePersonalActorHistoricalSaveAsync mit originalem Save-Nachweis.
- [https://github.com/maik3531/Magnolie-Organizer/issues/302#issuecomment-6569846243](https://github.com/maik3531/Magnolie-Organizer/issues/302#issuecomment-6569846243): Letzter Stand 351f216b: Prepare umgesetzt; IPC PreWrite/ActualSave/Confirm, produktiver GUI-Writer und physische E2E-Abnahme bleiben offen.

## [#306](https://github.com/maik3531/Magnolie-Organizer/issues/306) — Notes-Zeitübersicht: native GUI- und physische Sync-Abnahme nach #304

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Kein neuer Quellfehler bestätigt; das Issue beschreibt ausdrücklich noch fehlende native Zeitübersicht- und physische Sync-Abnahme.

**Bereits umgesetzt / belegt:** Minutentakt aktualisiert die Anzeige ohne Speicherauftrag; horizontale Eintragsaktionen und Arbeitsart-Vorgaben sind vorhanden. Bestehende UI-/Datenregressionsquellen decken die vorbereiteten Fälle ab.

**Noch offen:** Echte Notes-Oberfläche bei schmaler Breite/großer Schrift, aktiven/pausierten Zeiten, Rollen-/Herkunftskennzeichnung, roter Löschaktion und Arbeitsart-Auswahl prüfen; tatsächlicher Notes↔Organizer-Sync darf durch reine Anzeigeaktualisierung keine zusätzlichen Datensatzänderungen erzeugen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als native Restabnahme offen lassen. Eine gemeinsame Notes-Abnahmesitzung mit #322/#375 ist sinnvoll; Zeit-/Sync-Kriterien bleiben dabei einzeln nachweisbar.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeiterfassungBlatt.kt#L76](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeiterfassungBlatt.kt#L76): LaunchedEffect aktualisiert now im Minutentakt; die Zeitübersicht verwendet diesen Anzeigestand.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeiteintragAktionen.kt#L18](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeiteintragAktionen.kt#L18): Horizontale, scrollbar angelegte Aktionszeile.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/daten/ZeitStartUebersichtTest.kt](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/daten/ZeitStartUebersichtTest.kt): Vorhandene Datenregression für Start-/Übersichtsverhalten; in diesem Audit nicht erneut ausgeführt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/306#issuecomment-6565123252](https://github.com/maik3531/Magnolie-Organizer/issues/306#issuecomment-6565123252): Letzter Nachtrag ergänzt Arbeitsart-Vorgaben und unterscheidet lokale UI-/Speichertests von physischem Geräteabgleich.

## [#322](https://github.com/maik3531/Magnolie-Organizer/issues/322) — Notes-Monatsdruck: physische WLAN-Drucker- und Handyabnahme nach #320

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Monatsdruck ist in der Quelle vorhanden; reale Drucker-/Handyabnahme ist ein gültiges eigenständiges Restkriterium.

**Bereits umgesetzt / belegt:** Vordergrundgebundene IPP/IPPS-Suche, getrennte automatische Sichtbarkeitswahl, ausgewählter Monatsbericht und Android-PrintManager/PDF-Anbindung existieren. Die aktuelle Monatsansicht liefert ihre Druckauswahl und entfernt sie beim Verlassen.

**Noch offen:** Physisch erreichbaren WLAN-Drucker einschließlich Verlust der Erreichbarkeit prüfen; richtigen Monat, leere Tabelle, schmale/große Darstellung, Papierkorb AUS und Einstellung Immer anzeigen einschließlich PDF auf echtem Android bestätigen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als Abnahmeissue belassen; keine neue Druckimplementierung ohne konkreten Befund. Mit Notes-Abnahmen koordinieren, Druckerfall nicht stillschweigend streichen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/DruckerSuche.kt#L24](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/DruckerSuche.kt#L24): IPP/IPPS-Suche und ausdrückliche Trennung von Ankündigung und Erreichbarkeit.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeitDrucken.kt#L16](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeitDrucken.kt#L16): Systemdruckdialog wird über PrintManager geöffnet; PDF-/Druckerauswahl liegt beim Android-Druckdienst.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeitMonate.kt#L58](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/ZeitMonate.kt#L58): Monatsgebundene Auswahl mit SideEffect und Dispose-Rücknahme.
- [https://github.com/maik3531/Magnolie-Organizer/issues/322](https://github.com/maik3531/Magnolie-Organizer/issues/322): Explizit verlangte physische WLAN-Drucker- und Handyabnahme nach #320 ist durch Hosttests nicht ersetzt.

## [#330](https://github.com/maik3531/Magnolie-Organizer/issues/330) — Datei-/Fotosynchronisation: native Integration, sichere Zielbelege und Gesamtabnahme

**Bewertung:** Funktion oder Integration noch offen

Das Gesamtziel ist trotz vieler implementierter und teilweise nativ geprüfter Teilpfade nicht abgeschlossen. Aktuelle Produktfreigaben bleiben von privaten Integrationszweigen getrennt.

**Bereits umgesetzt / belegt:** Geschützte Datei-/Medienjobs, getrennte Rechte und Ziele, Hash-/Saved-Nachweise, Mapping, Backup/Restore, gemeinsame Einstellungen und manuelle/WLAN-Teilpfade sind vorhanden. Historische Nachweise auf dem exakten privaten Linux/Notes-Paketpaar belegen Erstimport, Wiederholung ohne neue Frames, WLAN-Wiederanlauf und getrennten Neudatei-Export. Windows hat native kontrollierte Gruppen, jedoch keine vollständige installierte Gegenstellenabnahme. Der begrenzte Nachtrag bb967f45 bis Head 50b15122 ergänzt inzwischen auch den Notes-Laufzeit-Hold für bestätigtes two_way; der vorher offene Notes-Hold wird nicht länger als Rest geführt.

**Noch offen:** Private Support-/Runtime-Kompositionen nachvollziehbar in die freizugebende Quelle integrieren und die vollständige Linux/Windows/Notes-Kette abnehmen. Sichere Rückgabe geänderter vorhandener Android-Originale, typisierte dauerhafte Löschbelege, konsistente Wiederherstellung und vollständige native Paket-/Geräteabnahme bleiben offen. Automatik, Hauptschalter AUS, Rechte, Neu-/Altbestand und Originalformate müssen jeweils ihrer tatsächlichen Freigabe folgen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leitissue behalten und #335 mit seinen Video-spezifischen Kriterien aufnehmen. #338 als eigenständigen Rückweg-/Löschblock verlinkt lassen; #336/#337/#749 nicht als erledigte Unterpunkte vereinnahmen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_telefon.py#L2911](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_telefon.py#L2911): Stock-Gate _native_media_support_checked bleibt ausdrücklich False; private Integrationsfreigabe ist separat.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileConnectionMetadata.cs#L15](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileConnectionMetadata.cs#L15): NativeMediaSupportChecked ist ein privates Prüfgate, keine Produkteinstellung/Ankündigung.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L687](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L687): nativeMediaSupportChecked ist weiterhin private acceptance only.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1): Ursprünglicher Stand 3f4b69ca mit Linux-/Windows-Holds; der hier noch offene Notes-Hold wird durch den gesondert verifizierten Nachtrag bb967f45 überholt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222229215](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222229215): Exaktes privates Paketpaar: manueller JPEG-/MP4-Erstempfang und Wiederholungsprüfung; kein Beweis für alle Richtungen/Plattformen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222370384](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222370384): Gleiches privates Paketpaar: tatsächlicher WLAN-Wiederanlauf, ausdrücklich getrennt vom atomaren Android-Originalrückweg.
- [https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7223719641](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7223719641): Neueste gemeinsame UI-Sperren behalten alte Werte und blockieren neue two_way-Auswahl; keine Freigabe des Gesamtpfads.
- [https://github.com/maik3531/Magnolie-Organizer/commit/bb967f45a3833c2bd58da617c3300b7e24b9a67a](https://github.com/maik3531/Magnolie-Organizer/commit/bb967f45a3833c2bd58da617c3300b7e24b9a67a): Notes-Hold inzwischen integriert; Source-/Receive-/Manual-Freigabe bei two_way gesperrt, kein Originalersetzungs-/Löschbeleg daraus.
- [desktop/media-latest-delta.json](../desktop/media-latest-delta.json): Begrenzter Nachtrag: Linux-/Notes-ACK-Erhalt, private Standardziele und manueller Linux-Foto-Erstempfang bereits in24927cf9; produktive Fähigkeit und vollständige Paketkette bleiben offen.

## [#335](https://github.com/maik3531/Magnolie-Organizer/issues/335) — Optionale Videosynchronisation mit eigenem nativen Zielordner und standardmäßig ausgeschaltetem Schalter

**Bewertung:** Funktion oder Integration noch offen

Die separate Videooption ist längst in der Quelle vorhanden. Der verbleibende Auftrag überschneidet sich vollständig mit der noch offenen nativen Medienintegration #330 und eignet sich zur Zusammenführung.

**Bereits umgesetzt / belegt:** VideoPreferences ist standardmäßig ausgeschaltet und besitzt eigenes natives Ziel und Zieltoken. Foto-/Videoauswahl und native Typrechte sind getrennt; gemeinsame Medienfelder enthalten videos_enabled=false. Die spätere Bedienvorgabe verwendet einen gemeinsamen Löschungen-auslassen-Schalter.

**Noch offen:** Videozweig in der freizugebenden Laufzeit und auf den vorgesehenen Gegenstellen vollständig nachweisen: eigener nativer Videoordner, getrennte OS-/SEND-/READ-/RECV-Rechte, keine Aktivierung durch Fotooption, Erhalt bei AUS/Widerruf/Neuverbinden. Private JPEG/MP4-Proben sind noch keine allgemeine native Produktfreigabe.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Kriterien in #330 übernehmen und #335 als zusammengeführt schließen. Im Leitissue Videooption als implementiert kennzeichnen; noch ausstehende native Integration/Abnahme ausdrücklich erhalten.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L32](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L32): VideoPreferences.enabled=False; eigenes Ziel und getrenntes Token.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncSettings.kt#L88](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncSettings.kt#L88): Gemeinsame Defaults: Hauptmodul AUS, Fotos gewählt, Videos AUS und Handy→PC.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/MedienSyncEinstellungen.kt#L93](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/MedienSyncEinstellungen.kt#L93): Separate Foto-/Videooptionen und typbezogene Empfangsaktionen; Löschwahl bleibt bis zur sicheren Implementierung schreibgeschützt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/335#issuecomment-6639810240](https://github.com/maik3531/Magnolie-Organizer/issues/335#issuecomment-6639810240): Spätere Nutzerentscheidung verlangt einen gemeinsamen Auslass-Schalter statt zwei separater Löschschalter.

## [#336](https://github.com/maik3531/Magnolie-Organizer/issues/336) — Animationen im Fotobereich belassen und optionalen Unterordner Animationen unterstützen

**Bewertung:** Funktion oder Integration noch offen

Animationen bleiben im Bildbereich und ein optionales Layout ist vorbereitet. Sichere nachträgliche Umsortierung ist jedoch weiterhin gesperrt und hat einen dokumentierten echten Kontinuitätsrest.

**Bereits umgesetzt / belegt:** Geschützte Animationswahl, tatsächliche GIF-Containerprüfung, zukünftige Zielplanung sowie umfangreiche private Linux-Auswahl-/Rename-/Journal-/Mappingbelege existieren. Unveränderte historische Originale werden anhand ihrer ursprünglichen Zuordnung behandelt.

**Noch offen:** Eine nach abgeschlossener Verschiebung erfolgte normale Buchspeicherung darf nicht dauerhaft die beweisbare Originalzuordnung verlieren; die aktuellen Schutzprüfungen melden photo_relocation_original_book_changed. Windows-/weitere Formatpfade und native sichere Ja/Nein-Umsortierung fehlen weiterhin. Schutz nicht abschalten und keinen Copy/Delete-Neudownload als Move ausgeben.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen. Den belegten Kontinuitätsrest und produktive native Umsortierung präzise führen; mit #337 gemeinsame Move-Bausteine nutzen, aber Animations- und Motivklassifikation getrennt halten.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_relocation_owner.py#L435](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_relocation_owner.py#L435): Original-Buchwechsel führt weiterhin zu photo_relocation_original_book_changed.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L587](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L587): separate_animations und geschützter Layoutwechsel sind vorhanden.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/media-special-folder-relocation-draft.md#L1](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/media-special-folder-relocation-draft.md#L1): Produktiver move_existing-Pfad bleibt gesperrt; identische neu gespeicherte Buchwerte erneuern den alten Auftrag nicht.
- [https://github.com/maik3531/Magnolie-Organizer/issues/336#issuecomment-7077382378](https://github.com/maik3531/Magnolie-Organizer/issues/336#issuecomment-7077382378): Letzter Nachweis f29090d4 bestätigt den bestehenden Hold selbst bei identischen neu gespeicherten Buchbytes, keine Lösung oder Produktfreigabe.

## [#337](https://github.com/maik3531/Magnolie-Organizer/issues/337) — Reale Foto- und Videoaufnahmen optional von Memes und Grafiken trennen

**Bewertung:** Funktion oder Integration noch offen

Die aktuell verlangte Trennung realer Foto-/Videoaufnahmen von Memes/Grafiken ist nicht durch den vorhandenen Eigene-Aufnahmen-Schalter oder EXIF-Filter erfüllt.

**Bereits umgesetzt / belegt:** Geschützte getrennte Layoutoption, historische Mappingregeln und gemeinsame Relocation-Vorbereitung existieren. CameraPhotoMetadata ist ausdrücklich nur ein begrenztes Metadatenkriterium und kein Nachweis der Kamera-/Motivherkunft.

**Noch offen:** Lokale brauchbare Erkennung realer Aufnahmen einschließlich Aufnahmen fremder Geräte; keine heimliche Cloudverarbeitung und keine Gleichsetzung mit Dateiname/DCIM/EXIF. Beim Ein-/Ausschalten native Ja/Nein-Auswahl und sichere echte Verschiebung vorhandener Dateien, ohne Überschreibung, Verlust oder erneuten Download; ungeklärte Versionen erhalten. Kurze Labels/Tooltips und native Darstellung bleiben gefordert.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Eigenständig offen lassen; Erkennung und sichere historische Umsortierung sind echte neue Kriterien. Gemeinsame Relocation-Abhängigkeit zu #336 dokumentieren, nicht als Duplikat schließen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/CameraPhotoMetadata.kt#L11](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/CameraPhotoMetadata.kt#L11): Kommentar und Implementierung unterscheiden Metadatenfilter ausdrücklich von Provenienzbeweis.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L83](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_photo_preferences.py#L83): separate_own_recordings ist geschützte Auswahl, kein Klassifikator.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/media-special-folder-relocation-draft.md#L104](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/media-special-folder-relocation-draft.md#L104): Dateiname/Kameraalbum/Modell allein reichen nicht; produktive sichere Verschiebung noch offen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/337](https://github.com/maik3531/Magnolie-Organizer/issues/337): Aktualisierter Body verlangt reale Aufnahmen versus Memes/Grafiken unabhängig vom Ursprungsgerät.
- [https://github.com/maik3531/Magnolie-Organizer/issues/337#issuecomment-6595458795](https://github.com/maik3531/Magnolie-Organizer/issues/337#issuecomment-6595458795): Expliziter Ja/Nein-Pfad ohne Zweitkopien und mit dauerhaften Zuordnungen beim Zusammenführen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/337#issuecomment-6595500230](https://github.com/maik3531/Magnolie-Organizer/issues/337#issuecomment-6595500230): Spiegelbildliche Anforderung auch beim Einschalten; keine Löschung oder erneuter Download durch Checkboxwechsel.

## [#338](https://github.com/maik3531/Magnolie-Organizer/issues/338) — Medien-Abgleichrichtung wie Notes wählen: Handy zu PC als Vorgabe, beidseitig nur mit sicherem Rückweg

**Bewertung:** Funktion oder Integration noch offen

Richtungswahl und Laufzeit-Holds sind inzwischen auch in Notes umgesetzt. Der während der Inventur erschienene Commit bb967f45 beseitigt den auf 3f4b69ca noch fehlenden Notes-Hold; sicherer Originalrückweg und Löschbelege bleiben offen.

**Bereits umgesetzt / belegt:** Auf der ursprünglichen Auditbasis 3f4b69ca waren Linux-/Windows-Holds und die Notes-UI-Sperre vorhanden. Der separat gelesene Nachtrag bb967f45 (enthalten im verifizierten Head 50b15122) sperrt two_way jetzt sowohl in MediaSyncSettings als auch in MediaSyncTransport.IntentToken. Gespeicherte bestätigte Werte bleiben erhalten; explizites Import-only und getrenntes PC→Telefon bleiben eigenständig. Der neue echte Storage-/Outbox-/ACK+Echo-Test prüft fehlende Source-/Receive-/Manual-Freigabe. Die Diskussion dokumentiert 94 gezielte JVM-Fälle; diese wurden hier nicht erneut ausgeführt.

**Noch offen:** Sichere bedingte Ersetzung exakt des vorhandenen Android-Galerieoriginals mit geprüftem vorherigem Archiv, gleicher Galerie-ID und Erhalt konkurrierender Bytes bleibt unbewiesen. Schreibzustimmung plus getrennte Vorher/Nachher-Abfragen ist kein atomarer Provider-Vergleich. Neue Galerieimporte ersetzen dieses Kriterium nicht. Löschweitergabe benötigt dauerhafte typisierte Belege statt fehlender/ausgefilterter Inventare; die echte Paket-Paarabnahme bleibt offen. Der Notes-Hold ist ausdrücklich kein offener Rest mehr.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Eigenständig offen lassen und mit #330 verknüpfen. Rest auf sicheren atomaren Android-Originalrückweg, Löschbelege und tatsächliche Paket-Paarprüfung verengen. Keinen zweiten Notes-Hold-Patch erstellen: bb967f45 hat ihn bereits integriert.

**Prüfgrenzen:** Vollständige Inventur auf 3f4b69ca; begrenzter verifizierter Nachtrag bis 50b15122 durch vollständigen bb967f45-Produkt-/Testdiff, Folgecommit und GitHub-Compare. Kein vollständiger neuer Audit auf 50b15122, keine neue JVM-/Geräteprüfung dieses Nachtrags durch diesen Agenten. Alle 24 Kommentare von #338 vollständig abgerufen/indexiert, letzter Kommentar inhaltlich gelesen. Keine Produktänderung oder Paketaktion.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/MediaSyncSettings.cs#L153](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/MediaSyncSettings.cs#L153): Auditbasis: Windows hält two_way und erhält gespeicherte Wahl/Import-only.
- [https://github.com/maik3531/Magnolie-Organizer/commit/bb967f45a3833c2bd58da617c3300b7e24b9a67a](https://github.com/maik3531/Magnolie-Organizer/commit/bb967f45a3833c2bd58da617c3300b7e24b9a67a): Produktdiff unabhängig gelesen: gemeinsames requested-Prädikat verweigert two_way, beide Intent-Richtungen werden exakt geprüft; gezielter Storage-/ACK+Echo-Fall ergänzt.
- [https://github.com/maik3531/Magnolie-Organizer/blob/50b1512234a765635f82af4537f277594fbf9878/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncTransport.kt#L23](https://github.com/maik3531/Magnolie-Organizer/blob/50b1512234a765635f82af4537f277594fbf9878/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncTransport.kt#L23): Verifizierter Nachtrag: IntentToken benutzt das gesperrte gemeinsame Prädikat und lässt nur die jeweils exakte Einwegrichtung zu.
- [https://github.com/maik3531/Magnolie-Organizer/blob/50b1512234a765635f82af4537f277594fbf9878/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncStorageTest.kt#L140](https://github.com/maik3531/Magnolie-Organizer/blob/50b1512234a765635f82af4537f277594fbf9878/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/telefon/MediaSyncStorageTest.kt#L140): Neuer Fall matchedTwoWayStaysStoredWithoutSourceReceiverOrManualRequest; Import-only bleibt nach erneutem Match aktiv, gespeicherte Wahl unverändert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/338#issuecomment-7224505518](https://github.com/maik3531/Magnolie-Organizer/issues/338#issuecomment-7224505518): Neuester Kommentar belegt den inzwischen integrierten Notes-Hold samt 94 historischen gezielten JVM-Prüfungen; sicherer atomarer Originalrückweg bleibt ausdrücklich offen.
- [https://github.com/maik3531/Magnolie-Organizer/compare/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f...50b1512234a765635f82af4537f277594fbf9878](https://github.com/maik3531/Magnolie-Organizer/compare/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f...50b1512234a765635f82af4537f277594fbf9878): GitHub-Vergleich unabhängig geprüft: genau zwei Folgecommits, merge-base=3f4b69ca; Kontakt-Restore-Nachtrag 50b15122 ändert diese Notes-Korrektur nicht.
- [desktop/media-latest-delta.json](../desktop/media-latest-delta.json): Begrenzter Nachtrag: Linux-/Notes-ACK-Erhalt, private Standardziele und manueller Linux-Foto-Erstempfang bereits in24927cf9; produktive Fähigkeit und vollständige Paketkette bleiben offen.

## [#375](https://github.com/maik3531/Magnolie-Organizer/issues/375) — Native Abnahme der Notes-Telefonoberfläche und bestätigten Sync-Anzeige

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die Telefon-/Sync-Oberflächen sind umgesetzt; aktuelle native Abnahme ist weiterhin nötig. Eine ältere Sichtbarkeitsforderung wurde später ausdrücklich präzisiert.

**Bereits umgesetzt / belegt:** Persönliche Sync-Bedienung liegt bei der Notes-Verbindung; letzte bestätigte erfolgreiche Synchronisation ist vom Verbindungszeitpunkt getrennt. Notes hat getrennte aufklappbare Bereiche. Erweitert darf laut späterer Entscheidung bei aktiver Notes-WLAN-Verbindung auch mit altem Peer sichtbar sein; ohne gemeinsame Medienunterstützung bleiben Aktionen gesperrt.

**Noch offen:** Installierte Linux-/Windows-Ansichten und tatsächliches Notes-Gerät prüfen: lokalisiertes Datum/Trigger, Offline/Unknown, keine falsche Erfolgsmeldung nach Fehler/Abbruch, Peerwechsel und native Darstellung. Sichtbarer Erweitert-Hinweis bei altem Peer ist nach neuerer Entscheidung kein Fehler. Positive Medienaushandlung bleibt Teil #330.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als native Restabnahme offen lassen; #306/#322 können organisatorisch in derselben Abnahmerunde geprüft werden, ihre speziellen Kriterien nicht als erledigt erklären.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/notes-device-status-ui.md#L17](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/notes-device-status-ui.md#L17): Bestätigte Erfolgsmetadaten und ausdrückliche Trennung von Host-DOM- und physischer Abnahme.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt#L456](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt#L456): Aktueller Erweitert-Bereich besitzt eigene Sichtbarkeit und eigenen Faltzustand.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/MedienSyncEinstellungen.kt#L25](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/MedienSyncEinstellungen.kt#L25): Erweitert-Sichtbarkeit ist von unterstützten Medienaktionen getrennt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/375#issuecomment-7058013529](https://github.com/maik3531/Magnolie-Organizer/issues/375#issuecomment-7058013529): Neueste Entscheidung 3706e84d erlaubt Erweitert auch für alte Gegenstellen, ohne Medienrechte/Aktionen vorzutäuschen.

## [#389](https://github.com/maik3531/Magnolie-Organizer/issues/389) — Android: dauerhaften Medienpapierkorb mit OS-Zustimmung und Wiederherstellung anschließen

**Bewertung:** Ursprünglicher Umfang erledigt oder entfallen

Schließkandidat: Die ursprüngliche Pflicht zu einem eigenen dauerhaften Android-Medienpapierkorb wurde auf ausdrücklichen Nutzerwunsch aufgehoben.

**Bereits umgesetzt / belegt:** Zusätzliche geschützte Android-Archiv-/Restore-Bausteine sind inzwischen vorhanden, werden durch die geänderte Anforderung aber nicht mehr als Voraussetzung benötigt. Bestehende Archive, Schlüssel und Historien bleiben erhalten.

**Noch offen:** Kein eigenständiger Implementierungsrest für den ursprünglichen eigenen Android-Papierkorb. Die spätere Frage, ob Löschen am Telefon die PC-Sicherung erhält oder einer gemeinsamen Löschwahl folgt, muss im Medien-Richtungs-/Löschauftrag #330/#338 erhalten bleiben; PC-Aufbewahrung einschließlich 0/Nie gehört zu #392. Eine allgemeine 30-Tage-Zusage für alle Galerieanbieter ist nicht zulässig.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als durch geänderte Anforderung obsolet schließen. Die offene Löschsemantik explizit nach #330/#338 und PC-Aufbewahrung nach #392 übertragen; keine Produktlöschung/Deaktivierung als Teil der Bereinigung.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/issues/389#issuecomment-6656075424](https://github.com/maik3531/Magnolie-Organizer/issues/389#issuecomment-6656075424): Verbindliche jüngste Nutzervereinfachung: PC-Sicherung genügt, vorhandenen Galerie-/Systempapierkorb nutzen; eigener Android-Archiv-/Purge-Auftrag entfällt.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/NativeGalleryTrashArchive.kt](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/NativeGalleryTrashArchive.kt): Vorhandenen geschützten Bestand nicht als Folge der Issue-Schließung löschen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/NativeGalleryMediaRestore.kt](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/NativeGalleryMediaRestore.kt): Bestehende Restore-Implementierung bleibt unabhängig von entfallener Auslieferungspflicht erhalten.

## [#392](https://github.com/maik3531/Magnolie-Organizer/issues/392) — PC-Mediensicherungen: inhaltsbasierte Versionierung und geprüfte Leerlauf-Komprimierung

**Bewertung:** Funktion oder Integration noch offen

PC-Backups und Linux-Leerlaufkomprimierung sind weit fortgeschritten; Windows-Wartungsanbindung und automatische Bestandsbereinigung sind weiterhin eigenständige Reste.

**Bereits umgesetzt / belegt:** Inhaltsgebundene Versionen und geschützte Kataloge erhalten Originale; Linux komprimiert erst nach mehr als 30 Tagen und mindestens 10 Prozent tatsächlicher Gesamtersparnis mit Rückleseprüfung. Native Linux-Leerlaufarbeiter und Wiederherstellung einschließlich vollständig vorhandener unterbrochener Sicherungen existieren. Windows hat Katalog/Restore, Ressourcenbeobachtung und Wartungspolitik.

**Noch offen:** Windows-Ressourcenbeobachtung tatsächlich an den produktiven Wartungs-/Kompressionslauf anschließen; derzeit findet sich der Probe-Aufruf außerhalb seiner Klasse nur in Tests. Automatische Versionsverfalls-/Objektbereinigung mit offenen Referenzen sicher umsetzen und nativ prüfen. Originalzuordnungen, 0/Nie und Wiederherstellung nach Entpaarung unverändert erhalten; keine Löschrechte aus bloßer Leerlaufbeobachtung ableiten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen, Beschreibung auf Windows-Wartung/Kompression, sichere GC und native Abnahme verengen. Entfallenen Android-Archivauftrag #389 hier nicht als neue Pflicht aufnehmen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_backups.py#L1400](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_backups.py#L1400): compress_one schützt pending-Referenzen, Retention und bestätigten Repräsentationswechsel.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_backup_codec.py#L26](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_backup_codec.py#L26): Alter, 0/Nie, 10-Prozent-Ersparnis und begrenzte Kompression explizit.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L27457](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L27457): Produktive Linux-Wartungsarbeiter-Komposition ist vorhanden.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileBackupMaintenance.cs#L7](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileBackupMaintenance.cs#L7): Windows-Idle/CPU/RAM-Beobachtung und Policy erteilen ausdrücklich keine Mutation-/Ablaufrechte.
- [https://github.com/maik3531/Magnolie-Organizer/issues/392#issuecomment-6687745249](https://github.com/maik3531/Magnolie-Organizer/issues/392#issuecomment-6687745249): Späteste Windows-Erweiterung belegt Wiederherstellung vollständiger unterbrochener Backupbytes; keine vollständige Wartungs-/GC-Freigabe.

## [#503](https://github.com/maik3531/Magnolie-Organizer/issues/503) — Fortsetzung #244: produktive Webcamsteuerung, native Anbieter und echte OBS-Abnahme

**Bewertung:** Funktion oder Integration noch offen

Webcam-Transport und native Adapter sind erheblich weiter als die ursprüngliche Fehlerbeschreibung. Die produktive Gesamtfreigabe und reale AV-/OBS-Abnahme fehlen weiterhin.

**Bereits umgesetzt / belegt:** Notes-Capture, authentifizierte getrennte AV-Kanäle, Linux-Ausgabe-/Pacingpfade, Windows-Parent/Session/native Output-Komposition und native Bestätigungsoberfläche existieren. Webcam-Bedienung liegt inzwischen unter Notes→Erweitert, nicht mehr unter KDE. Aktuelle Guard- und Cleanup-Korrekturen besitzen gezielte historische Nachweise.

**Noch offen:** Produktive Provider-/Setup-Freigabe und tatsächlicher Kamera-/Mikrofonlauf einschließlich synchronem Bild/Ton in OBS, Stop/Trennung/Sperre/Widerruf. Windows bleibt im echten UI-Gate standardmäßig gesperrt; kombinierter Source-/Mikrofonsetup-Aufrufer und normale FrameServer-Adoption sind nicht als fertige Leistung belegt. Bestehende Geräte-/Audio-/VM-Pausen bleiben verbindlich.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leitissue behalten und #517 sowie #597 als klar getrennte Linux-/Windows-Abschnitte samt ihren vollständigen Restkriterien und Pausen aufnehmen; danach die beiden engeren Issues als zusammengeführt schließen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraDesktopMainForm.cs#L9](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraDesktopMainForm.cs#L9): NativeWebcamChecked bleibt false; implementierter Bestätigungsdialog wird nicht als freigegebene native Funktion exponiert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/BridgeDispatcher.DesktopWebcam.cs#L15](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/BridgeDispatcher.DesktopWebcam.cs#L15): Native Bestätigung ist angeschlossen, aber vom ursprünglichen Buchprofil und dem nativen Gate abhängig.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraNativeOutputs.cs#L19](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraNativeOutputs.cs#L19): Echte Output-Komposition verlangt geschützte installierte Source vor Audio-/Video-Prepare.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-webcam-v1.md#L3](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-webcam-v1.md#L3): Aktueller kombinierter Setupvertrag hat noch keinen aktiven UI/CLI/elevierten Aufrufer; reale AV-/OBS-Abnahme bleibt getrennt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/503#issuecomment-7073925831](https://github.com/maik3531/Magnolie-Organizer/issues/503#issuecomment-7073925831): Letzte Linux-Sitzungsprüfung behält originale WLAN-Bindung; kontrollierte Medienprobe ist kein echter Geräte-/OBS-Nachweis.

## [#517](https://github.com/maik3531/Magnolie-Organizer/issues/517) — Linux-Webcam: native Systemfreigabe und Boot-Autoload der Treibereinrichtung abnehmen

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Linux-Treibereinrichtung und kombinierter Installationsweg sind in der Quelle vorhanden; echte Systemfreigabe und Boot-Autoload sind weiterhin nur nativ abnehmbar.

**Bereits umgesetzt / belegt:** Bestehenden v4l2loopback-Treiber erkennen, vorhandene Systemrechte nutzen, begrenzten eigenen Setup-/Autoload-Kontext erstellen. Der kombinierte PackageKit-Install-/Setup-Weg nutzt genau einen normalen pkexec/polkit-Aufruf mit fester Gesamtfrist und beobachtetem Abbruch.

**Noch offen:** Reale vertrauenswürdige Paketinstallation und eine einzige tatsächliche Systemzustimmung prüfen, inklusive Ablehnung/Abbruch, Paket-/Setup-Fehler, Kontextwechsel, Udev und passendem Autoload beim folgenden Boot. Bereits gemessene virtuelle AV-Ausgabe ersetzt diesen Installations-/Boot-Nachweis nicht.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** In #503 als Linux-Setup-/Boot-Abnahmeabschnitt aufnehmen und #517 anschließend als zusammengeführt schließen. Keine Setup-/Boot-Aktion im Audit ausführen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_camera_install.py#L58](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_camera_install.py#L58): Ein ursprünglicher pkexec-Aufruf startet Install+Setup mit einer 710-Sekunden-Gesamtfrist.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_camera_setup.py#L68](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_phone_camera_setup.py#L68): Eigene modules-load.d-Konfiguration und begrenzte privilegierte Einrichtung.
- [https://github.com/maik3531/Magnolie-Organizer/issues/517](https://github.com/maik3531/Magnolie-Organizer/issues/517): Der Issuebody trennt kontrollierte Prüfungen ausdrücklich von echter Polkit-/PackageKit-/Boot-Abnahme.

## [#597](https://github.com/maik3531/Magnolie-Organizer/issues/597) — Windows-Webcam: Manager/Broker, echte Medienausgabe und kombinierte Setup-Abnahme – Rest #588

**Bewertung:** Funktion oder Integration noch offen

Manager/Broker und echte Windows-Output-Komposition existieren inzwischen. Der kombinierte Installer und native Normalprozess-/FrameServer-/AV-Erfolg sind weiterhin nicht fertig.

**Bereits umgesetzt / belegt:** PhoneCameraVideoParentRuntime, native IPhoneCameraOutputs, Original-OutputAuthority, Audio-/Videotakt und installierte Source-Rückleseprüfung sind vorhanden. UI-Bestätigung wurde nach den frühen Kommentaren angeschlossen. Source-Deployment, Journal und begrenzte kombinierte Setup-Wire sind als interne Bausteine implementiert.

**Noch offen:** Ein ursprünglicher kombinierter Setup-Aufrufer muss Source und Mikrofon in einem genehmigten Systemlauf tatsächlich integrieren; aktueller Vertrag sagt ausdrücklich noch kein aktiver Aufrufer. Anschließend normale nicht erhöhte FrameServer-/Source-Adoption, geschützte installierte Source, reale Kamera/Mikrofon-/OBS-Ausgabe und gesamter UI-Start/Stop nativ belegen. Audio-only-Reboot oder synthetische COM-Adoption ist kein kombinierter Erfolg.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** In #503 als Windows-Abschnitt integrieren: fehlenden kombinierten Caller, nicht erhöhte FrameServer-Adoption, reale Source-/AV-/OBS-Abnahme und Pausen unverändert übernehmen; danach #597 als zusammengeführt schließen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraVideoParentRuntime.cs#L99](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraVideoParentRuntime.cs#L99): Produktiver Parent mit CreateCurrent und PrepareAsync ist bereits implementiert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraNativeOutputs.cs#L19](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/PhoneCameraNativeOutputs.cs#L19): Originale installierte Source und beide nativen Adapter werden unter derselben Autorität komponiert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-webcam-v1.md#L3](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-webcam-v1.md#L3): Kombinierter Setup-Wire/Source-Deployment/Journal besitzen noch keinen aktiven kombinierten Installer-Aufrufer.
- [https://github.com/maik3531/Magnolie-Organizer/issues/597#issuecomment-7044619098](https://github.com/maik3531/Magnolie-Organizer/issues/597#issuecomment-7044619098): Letzte Cleanup-Korrektur und kontrollierte Windows-Gruppen sind kein tatsächlicher Geräte-/Outputnachweis.

## [#641](https://github.com/maik3531/Magnolie-Organizer/issues/641) — Notes: belegtes Gegenstellenprofil, Bedienaktion und bedingter Neustart – Rest #640

**Bewertung:** Funktion oder Integration noch offen

Dieser Auftrag ist nicht nur eine ausstehende Geräteprüfung: Der produktive Notes-Originalrückweg ist weiterhin ausdrücklich unverbunden.

**Bereits umgesetzt / belegt:** Kontakt-Originalprotokoll und interne Test-/Setup-Bausteine sind vorhanden. Notes hält den besonderen Empfänger getrennt vom normalen Baumempfang.

**Noch offen:** Belegtes Gegenstellenprofil, native Provider-/Rechte-/Keystore-Integration, echte Bedienaktion und bedingter Neustart verbinden. originalEmpfang ist im normalen Baumwerk null und wird nur im internen Testkonstruktor gesetzt; entsprechende sichere Nachrichten werden daher produktiv mit contact_original_return_not_enabled abgewiesen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen. Keinen Testkonstruktor oder booleschen Schalter zur vermeintlichen Produktfreigabe umdeuten; den produktiven Besitzerpfad implementieren und danach nativ abnehmen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt#L1214](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt#L1214): Produktiver Empfänger startet null; spezielle sichere Nachricht wird ohne ihn verweigert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt#L1573](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt#L1573): Nur fuerOriginalRueckwegTest setzt originalEmpfang.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/contact-original-return.md](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/contact-original-return.md): Originalprofil, lokale Schreibautorität und ursprünglicher Transport müssen getrennt nachgewiesen werden.
- [https://github.com/maik3531/Magnolie-Organizer/issues/641](https://github.com/maik3531/Magnolie-Organizer/issues/641): Expliziter Rest: echtes Gegenstellenprofil, Bedienaktion und bedingter Neustart nach #640.

## [#691](https://github.com/maik3531/Magnolie-Organizer/issues/691) — Notes: target37-/LAN-Manifestmigration und native Upgrade-/Gerätematrix – Rest #672

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die target37-Testkonfiguration ist implementiert; eine geeignete neu gebaute Kandidaten-APK und native Upgrade-/LAN-Matrix bleiben offen. Das Produktionsziel 35 ist absichtlich unverändert.

**Bereits umgesetzt / belegt:** Separater expliziter Offline-/testOnly-Validierungsbau mit targetSdk 37, eigener LAN-Manifestvariante und Build-/Manifestprüfung ist vorhanden. Das normale Ziel bleibt 35 bei minSdk 26. Die aktuelle Proguard-Datei schützt inzwischen den von #736 betroffenen reflektiven WorkDatabase_Impl-Konstruktor.

**Noch offen:** Den Ziel-37-Kandidaten aus dem aktuellen korrigierten Stand neu bauen und den tatsächlichen DEX einschließlich Room-Konstruktor prüfen, bevor seine native LAN-/Upgrade-Matrix beginnt. Der alte APK-Kandidat ist laut jüngstem Kommentar ungeeignet. Noch keine Produktions-Zielanhebung ohne Geräte-/Upgrade-Nachweise.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als Kandidaten-/native Abnahme führen; spätere Neuherstellung nur im dann autorisierten Buildablauf. Keine unverlangte Paket- oder SDK-Zielumstellung.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/build.gradle.kts#L25](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/build.gradle.kts#L25): Separater Validierungsschalter und Produktionsziel 35 versus Kandidat 37.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/target37/AndroidManifest.xml](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/target37/AndroidManifest.xml): Eigener testOnly-/LAN-Kandidatenoverlay.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/proguard-rules.pro#L6](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/proguard-rules.pro#L6): Aktuelle Keep-Regel erhält WorkDatabase_Impl mit öffentlichem No-Arg-Konstruktor.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/werkzeuge/test_target37_build.py](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/werkzeuge/test_target37_build.py): Vorhandene Manifest-/Konfigurationsprüfung; in diesem Audit nicht erneut ausgeführt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/691#issuecomment-7057311658](https://github.com/maik3531/Magnolie-Organizer/issues/691#issuecomment-7057311658): Letzter Befund verwirft die alte Ziel-37-APK wegen fehlendem Room-Konstruktor; Ziel-35-Fix ist keine Ziel-37-Geräteabnahme.

## [#721](https://github.com/maik3531/Magnolie-Organizer/issues/721) — Mac/iPhone: AirPlay-Bildschirmspiegelung mit UxPlay integrieren und nativ prüfen

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die früher separat übergebene AirPlay-Quellintegration ist im aktuellen gepinnten Bestand vorhanden. Offener Rest ist native Mac-/iPhone-Bau- und Funktionsabnahme.

**Bereits umgesetzt / belegt:** Interner UxPlay-Empfänger mit gebundener Herkunft, Swift-Zustands-/Bundle-/JSONL-Code, native AppKit-Bedienung, eigener Prozess-/PIN-Lebenszyklus sowie Bundle-Bauwerkzeuge liegen im aktuellen Baum. Es wird keine eigene iPhone-App benötigt.

**Noch offen:** Native Swift/AppKit-Kompilierung, geschlossenes signiertes arm64-/x86_64-Bundle auf unterstütztem macOS, Bonjour/LAN-Rechte und echtes iPhone mit PIN, Wiederverbindung, Bild/Ton/Rotation, Stop/Sperre/Benutzerwechsel/Ruhezustand/Absturz und längerer Sitzung. ready/video/audio-Meldungen belegen keine gerenderten Frames oder hörbaren Ton.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als native Abnahme behalten, Beschreibung auf bereits integrierte Quelle aktualisieren. Nicht erneut einen AirPlay-Implementierungsauftrag aus dem alten Patchstatus ableiten und nicht mit dem Android-Zweitmonitorpfad #245 vermischen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/AirPlayHost.swift#L9](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/AirPlayHost.swift#L9): Native Bedienung und besitzgebundener Empfängerprozess sind in der jetzigen Quelle vorhanden.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/AirPlayBundle.swift](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/AirPlayBundle.swift): Interne Bundlepfade und private Kopplungsablage statt externer UxPlay-Suche.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/AIRPLAY.md#L87](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/AIRPLAY.md#L87): Konkrete fünfteilige native Abnahmematrix; Host-/Swift-Ausführungsgrenzen ausdrücklich dokumentiert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/721#issuecomment-7186480066](https://github.com/maik3531/Magnolie-Organizer/issues/721#issuecomment-7186480066): Frühere separate Patch-/Hostnachweise sind keine native Mac-/iPhone-Paketabnahme.

## [#727](https://github.com/maik3531/Magnolie-Organizer/issues/727) — Linux-Zweitmonitor: KDE-Ausgang eindeutig der Sitzung zuordnen und Entfernung beobachten

**Bewertung:** Funktion oder Integration noch offen

Die private KWin-Ausgangsbeobachtung ist implementiert, ihre echte Produktroute und Zusatzmonitor-Abnahme fehlen. Der vollständige Rest passt als Unterabschnitt zu #245.

**Bereits umgesetzt / belegt:** Exakte mapping_id-/Registry-Instanzbindung, begrenzter eigener libwayland-Beobachter, geordnete Pre-Start-Barriere nach SelectSources sowie getrennte Entfernung/Transport-Drain-Beobachtung sind vorhanden und historisch im Labor geprüft.

**Noch offen:** Die tatsächliche KDE-Portalroute unabhängig bestätigen und produktiv den ursprünglichen Beobachter starten. Neuen Ausgang anhand exakter Sitzung/Instanz belegen, Fenster dorthin bewegen und beim Stop ausschließlich diesen Ausgang verschwinden sehen. Geometrie, Desktopname oder zufällig passender Ausgang reichen nicht; Abbruch und fehlende Barriere halten die Freigabe.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Mit vollständiger Restliste in Leitissue #245 aufnehmen und #727 anschließend als zusammengeführt schließen. Keine Aktivierung allein anhand der vorhandenen Laborprüfungen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_desktop_screen_output.py#L1](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_desktop_screen_output.py#L1): Read-only Witness bindet neues KWin-mapping_id an die ursprüngliche beobachtete Registry-Instanz.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_desktop_screen_admission.py#L94](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_desktop_screen_admission.py#L94): Virtueller Start hat bis zur nachgewiesenen Entfernung keinen wiederverwendbaren Slot.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/desktop-screen-send-v1.md#L132](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/desktop-screen-send-v1.md#L132): Aktuelles Produkt verifiziert Route/startet Beobachter noch nicht; echte Platzierung/Entfernung bleibt getrennt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/727#issuecomment-7052411841](https://github.com/maik3531/Magnolie-Organizer/issues/727#issuecomment-7052411841): Letzter geordneter Wayland-Roundtrip ist eine Laborvorbereitung und keine echte KDE-/Fenster-/Entfernungsabnahme.

## [#731](https://github.com/maik3531/Magnolie-Organizer/issues/731) — Notes-Teststand: lokale Diagnose für Fotosync, Webcam und Bildschirmfreigabe

**Bewertung:** Ursprünglicher Umfang erledigt oder entfallen

Schließkandidat als erfüllter begrenzter Diagnose-/Teststandauftrag. Die eigenständige Funktionsabnahme gehört weiterhin zu #330, #503/#597 und #245.

**Bereits umgesetzt / belegt:** Sechs feste lokale Medienphasen sind mit Foto-Dateikanal, Webcam-Sendefreigabe und Screen-Sendefreigabe/Fehler verbunden. Der opt-in-Puffer ist auf 32 Ereignisse begrenzt, wird bei Abschalten geleert und erscheint nur im lokalen Einstellungsbericht. Der WLAN-Drahtbericht bleibt unverändert. Spätere ARBEITSSTAND-/Issue-Nachweise dokumentieren den regulär signierten privaten Notes-Teststand mit erhaltenem Zertifikat, Paarung und Rechten bei isolierten Updates.

**Noch offen:** Kein eigenständiger Rest an lokalen Diagnosephasen oder privatem Teststand aus diesem Auftrag. Tatsächliche Fotosync-/Kamera-/Spiegelungserfolge sind durch die Phasenmeldungen ausdrücklich nicht bewiesen und bleiben in ihren Funktionsissues offen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als erledigten Diagnose-/privaten Teststandauftrag schließen; in der Abschlussnotiz auf die weiterhin offenen eigentlichen Medien- und Spiegelungsissues verweisen. Keine erneute APK nur wegen des alten offenen Issuezustands bauen.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Historische Bereitstellung wird aus dokumentiertem signiertem Teststand und Update-Nachweisen übernommen; keine heutige erneute APK-Erstellung oder Geräteinstallation behauptet. Der zusätzlich gewünschte gezielte MedienDiagnoseTest ist ein Robolectric-Test mit SDK 35. Die vorhandene Kotlin/JVM-Werkzeugablage besitzt weder Robolectric/android-all/AndroidX-Test noch kotlinx-serialization-json; kein Android-SDK vorhanden. Der Test wurde deshalb nicht neu ausgeführt (kein Exitcode/keine PASS-Zahl), keine neuen Abhängigkeiten installiert. Historischer signierter Teststand und isolierte Updates bleiben separat belegt. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/Entwicklermodus.kt#L34](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/Entwicklermodus.kt#L34): Fester Enum, 32er-Puffer, Opt-in/Clear und lokaler Bericht; keine Medienfelder im normalen bericht().
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/MedienDiagnoseTest.kt#L23](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/test/java/io/gitlab/maik3531/magnolienotes/MedienDiagnoseTest.kt#L23): Vorhandener Test schützt Begrenzung, Deaktivierung, gemeinsame lokale Sicht und unveränderten WLAN-Bericht.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L1144](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt#L1144): Foto-Dateikanal registriert lokale Bereitschaft/Fehler.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PhoneWebcamNotesRuntime.kt#L110](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PhoneWebcamNotesRuntime.kt#L110): Webcam-Ereignis wird am tatsächlichen freigegebenen Sendepfad gesetzt.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PhoneScreenNotesRun.kt#L86](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/PhoneScreenNotesRun.kt#L86): Spiegelungsereignis ist an den tatsächlichen Sendebestätigungspfad angeschlossen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1167](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1167): Signierter privater Notes-Bau und isolierte ON/OFF-Updatefälle mit erhaltenen Rechten/Paarungen dokumentiert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/245#issuecomment-7216893749](https://github.com/maik3531/Magnolie-Organizer/issues/245#issuecomment-7216893749): Signierte private Notes-APK wiederhergestellt und isolierte Updates erneut geprüft; tatsächlicher Spiegeltest bleibt separat offen.
- [https://github.com/maik3531/Magnolie-Organizer/commit/b8a69a102d7ce8de01f4b1b9dc145b9062151402](https://github.com/maik3531/Magnolie-Organizer/commit/b8a69a102d7ce8de01f4b1b9dc145b9062151402): Letzte Änderung an Entwicklermodus/MedienDiagnoseTest ist die ausdrücklich #731 zugeordnete Implementierung. Der begrenzte spätere Main-Nachtrag ändert diese Dateien nicht.
- [https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222229215](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7222229215): Signierte private Notes-APK 4976808e… tatsächlich im isolierten Android-34-Gast betrieben; exaktes privates Paketpaar, keine heutige erneute Installation.
- [/workspace/scratch/7203da5bd564/open-audit/media/special-test-731.json](../media/special-test-731.json): Gezielter vorhandener MedienDiagnoseTest nicht neu ausgeführt: Robolectric/Android35/AndroidX-ApplicationProvider und JSON-Laufzeit fehlen im vorhandenen Kotlin/JVM-Setup; keine Stubs oder erfundene PASS-Zahl.

## [#749](https://github.com/maik3531/Magnolie-Organizer/issues/749) — Medienabgleich: Originalformate über JPEG/PNG und MP4/MOV hinaus, einschließlich iPhone

**Bewertung:** Funktion oder Integration noch offen

Der Auftrag ist durch WebP/BMP-Teilerweiterungen nicht erledigt. Weitere Originalformate und echte iPhone-/Mac-Rundwege bleiben substanzielle eigenständige Kriterien.

**Bereits umgesetzt / belegt:** Der wirkliche Linux-/Windows-Sender erkennt über JPEG/PNG/MP4 hinaus u.a. GIF, statisches WebP und begrenztes BMP. Für weitere Container existieren begrenzte Parser/Fixture- und einzelne Linux-Empfangs-/Backup-/Restore-Nachweise, einschließlich HEIC/HEIF-Originalbytes. Diese bedeuten keine uneingeschränkte Freigabe aller Decoder/Sender/Gegenstellen.

**Noch offen:** Pro Format echten unveränderten Originaltransfer, Empfangsvalidierung, Darstellung wo zugesagt, Backup und Restore auf vorgesehenen Plattformen nachweisen; TIFF/WebM/MKV/AVI/HEIC/HEIF nicht allein anhand eines Parserfixtures allgemein aktivieren. Mac/iPhone benötigen weiterhin den tatsächlichen Medienadapter/-Rundweg; gemeinsame Web-UI ist keine native Implementierung.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Eigenständig offen lassen und Format-/Plattformmatrix konkret führen. Mit #330 verknüpfen, aber nicht als bloße Duplikatbeschreibung schließen und keine pauschale Format-Whitelist erweitern.

**Prüfgrenzen:** Statischer Abgleich der festen Quelle 3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f. Keine neuen Tests, Pakete, Installationen, VM- oder Geräteaktionen ausgeführt. Historische Prüfnachweise sind als solche bewertet; Quelltests beweisen keine heutige native Abnahme. Alle Kommentare vollständig abgerufen und indexiert; bei langen Fortsetzungshistorien wurden die aktuellen Entscheidungen und relevanten früheren Nachweise gezielt inhaltlich gelesen. Begrenzter Nachtrag 3f4b69ca→50b15122 unabhängig per GitHub-Compare verifiziert (zwei Commits: Notes-Hold #338 und Kontakt-Restore #823); kein vollständiger neuer Audit behauptet.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_mime.py#L278](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_mime.py#L278): Produktives identify lässt GIF/WebP/BMP zu; TIFF-Helfer ist ausdrücklich private proof, not sender support.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_mime.py#L157](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_media_mime.py#L157): Begrenzter TIFF-Parser bleibt ein interner Beleg und erweitert den Sender nicht automatisch.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileMediaMime.cs#L5](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/DeviceFileMediaMime.cs#L5): Windows unterscheidet begrenzte Containeridentifikation von vollständiger nativer Empfangsvalidierung.
- [https://github.com/maik3531/Magnolie-Organizer/issues/749#issuecomment-7186480800](https://github.com/maik3531/Magnolie-Organizer/issues/749#issuecomment-7186480800): Jüngste Mac-Prüfung benennt fehlenden nativen Medienadapter; vorhandene gemeinsame Oberfläche ersetzt ihn nicht.

