# Published2.0.30 wire-command inventory mapped to current ports

Release `067c38934b539943d8e1720abafd8a80b401d797`. Current ports snapshot `0288d99f7dcd4b366748b8c36338edd1dbcafb49`. Static names/capabilities are not native feature passes. See [functional acceptance map](FEATURE-ACCEPTANCE-2.0.30.md). This table includes port-specific additions alongside released commands; runtime/permission/transport acceptance remains separate. Issue #121.

| Command | Tag JS literal | Tag C# schema | Tag Python dispatcher | Mac current implementation | Tablet current implementation |
| --- | --- | --- | --- | --- | --- |
| `ablage_holen` | yes | yes | yes | source: text clipboard; native pasteboard untested | native text clipboard; actual device acceptance open |
| `ablage_kopieren` | yes | yes | yes | source: text clipboard; native pasteboard untested | native text clipboard; actual device acceptance open |
| `adressen_ods` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `background_settings_get` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `background_settings_set` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_bestaetigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_briefkasten_pruefen` | yes | yes | yes | partial: explicit bounded DAV collection discovery; no data synchronization | native DAV account config/Keystore/discovery only; no record synchronization |
| `baum_briefkasten_speichern` | yes | yes | yes | partial: revision-bound config/credential transaction; Nextcloud mailbox unsupported | native DAV account config/Keystore/discovery only; no record synchronization |
| `baum_briefkasten_status` | yes | yes | yes | partial: native DAV configuration and Keychain availability; no sync | native DAV account config/Keystore/discovery only; no record synchronization |
| `baum_dav_pruefen` | — | yes | yes | partial: correlated read-only DAV connection discovery; no data synchronization | native DAV account config/Keystore/discovery only; no record synchronization |
| `baum_delegieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_ein` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_eingang_geleert` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_entfernen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_internet_adresse` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_mailbox_schreibpruefen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_mcp` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_paaren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_paarungsdatei_erzeugen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_paarungsdatei_importieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_paarungsqr_erzeugen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_partner_einstellungen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_rueckmeldung` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_stand` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_suchen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_teilen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_weitergabe_annehmen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_weitergabe_erlauben` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `baum_weitergeben` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `beenden` | yes | yes | yes | source: AppKit quit/save/reopen handshake verified for fresh local profiles | NO ADAPTER; shared action disabled/rejected |
| `beenden_abgebrochen` | yes | yes | yes | source: cancel pending quit | explicit cancellation only |
| `beenden_bereit` | yes | yes | yes | source: correlated pending quit only | Activity finish only |
| `bereit` | yes | yes | yes | source: load/new/locked document; native local startup verified | native encrypted load / first profile; cold readiness incomplete |
| `brief` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `chromium_extern_oeffnen` | — | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `cloud_sicherung_kennwort` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `cloud_sicherung_status` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `cloud_sicherung_test` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `contributor_pruefen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `debug_startphase` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `drucken` | yes | yes | yes | source: isolated JS-free print renderer and AppKit system print/PDF dialog; native acceptance pending | separate bridge-free Print WebView; spooler acceptance open |
| `eds_status` | yes | yes | yes | partial: passive native EventKit/Contacts discovery; no synchronization | native DAV account config/Keystore/discovery only; no record synchronization |
| `eigenes_profil_office` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `eigenes_profil_telefon` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `entsperren` | yes | yes | yes | partial: v1/v2 Apple crypto fixtures verified; full password lifecycle pending | NO ADAPTER; shared action disabled/rejected |
| `erinnerung_einrichten` | yes | yes | yes | LIMITATION RESPONSE ONLY: no native scheduler is configured | one-off AlarmManager projection only; no series/anniversary/health/SMS schedule |
| `erinnerung_zeigen` | yes | yes | yes | partial: open/unlocked/consented session only; delivery untested | NO ADAPTER; shared action disabled/rejected |
| `export` | yes | yes | yes | partial: source-preserving appointment/task/anniversary ICS; eight native extended roundtrips passed | REPLACED: tablet_export_ics / tablet_export; not vCard/CSV/office |
| `exportieren` | yes | — | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `feiertage` | yes | yes | yes | source: bounded HTTPS public/school holiday retrieval with regional scope; native service tests/live public retrieval passed; full UI acceptance pending | native HTTPS public/school service; whole response only; real region UI acceptance open |
| `gesamtarchiv_exportieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `gesamtarchiv_importieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `gesamtarchiv_pruefen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `gesamtarchiv_waehlen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `gesundheit_ods` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_abmelden` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_anmelden` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_client_id_speichern` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_konto_aendern` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_konto_stand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_mcp_cancel` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_mcp_start` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `graph_mcp_status` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `handbuch_herunterladen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `handbuch_oeffnen` | yes | yes | yes | source: bundled canonical 2.0.30 manual; isolated local WKWebView/search; native validation pending | NO ADAPTER; shared action disabled/rejected |
| `import` | yes | yes | yes | partial: native selected UTF-8 ICS file; atomic codec and canonical merge; no vCard/CSV/archive import | REPLACED: tablet_import; ICS/JSON only, not every published import format |
| `import_lokal` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `internet_konten_mcp` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `internet_konten_status` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `internet_konto_anmelden` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `internet_konto_verwalten` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_anzahl` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_aufbewahrung` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_einstellungen_setzen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_erzeugen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_intervall` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_liste` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_loeschen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_manuell` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_vorschau` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `journal_wiederherstellen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `karte` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_dateisystem_oeffnen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_dateisystem_stand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_empfangsordner_waehlen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_entfernen` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_input_einstellungen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_input_senden` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_input_stand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_mcp` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_medien_aktion` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_medien_geraete` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_medien_stand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_paaren` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_paarung_bestaetigen` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_pairing_complete` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_pairing_confirm` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_pairing_start` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_player_datei` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_player_stand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_player_titel` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_player_waehlen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_receive_decide` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_receive_settings` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_receive_ziel_waehlen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_reconnect` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_sms_senden` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kde_zeichnen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kennwort_entfernen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `kennwort_setzen` | yes | yes | yes | partial: enable for current profile only; no change/rekey | NO ADAPTER; shared action disabled/rejected |
| `lo_benutzer` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `macos_systemzugriff` | — | — | — | partial: explicit OS access prompt and refreshed source status; no synchronization | NO ADAPTER; shared action disabled/rejected |
| `mail` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `mcp_antwort` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `medikament_suchen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `mutations_snapshot` | yes | yes | yes | partial: durable exact file checkpoint; no desktop journal index/retention | NO ADAPTER; shared action disabled/rejected |
| `notiz_anhang_datei` | yes | yes | yes | partial: selected data-URL attachment Save only; no Open | NO ADAPTER; shared action disabled/rejected |
| `notiz_dateien_importieren` | — | — | — | source: additive selected TXT/literal Markdown/PDF/image notes; explicit preview + recovery + save ACK; native picker unverified | NO ADAPTER; shared action disabled/rejected |
| `notiz_versand` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `ordner_waehlen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `password_status` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_attachment_index` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_betrieb` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_desktop_features` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_einstellungen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_gemeinsam_aendern` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_gemeinsam_initialisieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_gemeinsam_start` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_lauf_senden` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_notizrichtung` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `personal_sync_senden` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `planer_ods` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `protokoll_zeigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `rechtschreibung` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `regional_einstellungen` | — | yes | yes | source: validated durable preferences; native locale handling untested | NO ADAPTER; shared action disabled/rejected |
| `regional_einstellungen_status` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `reminder_privacy_status` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `sicherung` | yes | yes | yes | partial: encrypted whole JSON, native picker; no Gesamtarchiv | NO ADAPTER; shared action disabled/rejected |
| `sicherung_pruefen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `sicherung_waehlen` | yes | yes | yes | source: native JSON picker pins selected path/bytes | NO ADAPTER; shared action disabled/rejected |
| `sicherung_wiederherstellen` | yes | yes | yes | partial: full JSON replacement + checkpoint + UI preflight; no additive/section restore | NO ADAPTER; shared action disabled/rejected |
| `sozial` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `speichern` | yes | yes | yes | source: durable document commit; destructive save requires checkpoint | whole-book atomic AES-GCM save; original-session/revision fences |
| `sync` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `sync_bestaetigen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `sync_commit` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `sync_start` | — | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `tablet_about` | — | — | — | NO ADAPTER; explicit negative/unsupported response | native limitation/version panel |
| `tablet_calendar_import_done` | — | — | — | NO ADAPTER; explicit negative/unsupported response | picker consumption after durable book ACK |
| `tablet_export` | — | — | — | NO ADAPTER; explicit negative/unsupported response | password-encrypted complete JSON; interoperability/device acceptance open |
| `tablet_export_ics` | — | — | — | NO ADAPTER; explicit negative/unsupported response | SAF ICS event/task/anniversary; native picker acceptance open |
| `tablet_import` | — | — | — | NO ADAPTER; explicit negative/unsupported response | SAF ICS merge or encrypted/raw JSON replacement; picker acceptance open |
| `tablet_import_cancel` | — | — | — | NO ADAPTER; explicit negative/unsupported response | one-shot picker cancellation only |
| `tablet_loaded` | — | — | — | NO ADAPTER; explicit negative/unsupported response | loaded ACK only, no feature acceptance |
| `tablet_notifications` | — | — | — | NO ADAPTER; explicit negative/unsupported response | explicit OS notification consent, not recurrence delivery |
| `tablet_replace` | — | — | — | NO ADAPTER; explicit negative/unsupported response | explicit full JSON replacement; pre-change backup/authority fences |
| `telefon_annehmen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_anruf_anzeigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_anruf_audio_einstellung` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_anruf_audio_pruefen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_anruf_lautstaerke_wiederherstellen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_auflegen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_bluetooth_einstellungen` | yes | — | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_bluetooth_schalten` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_ein` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_entfernen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_entwickler_diagnose` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_freigabe` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_freigaben` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_kontakte` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_kontaktfotos` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_kontaktgruppen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_kontaktgruppentitel` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_kontaktwerte` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_mcp` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_meldung_anzeigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_oeffnen` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_paarung_bestaetigen` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_pairing_abbrechen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_pairing_bestaetigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_pairing_oeffnen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_personal_sync_commit` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_sms_benachrichtigen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_stand` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_status_anfordern` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_verbinden` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_verbindung_ein` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_verbindung_stand` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `telefon_waehlen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `thunderbird_einrichten` | — | yes | — | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `tray_einstellungen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `tray_status` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `tray_zaehler` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `update_herunterladen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `update_installieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `update_oeffnen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `update_pruefen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `vorschlaege` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `wetter` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `wort_merken` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeichenblatt_exportieren` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeichenblatt_pdf_oeffnen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeichenblatt_svg_pruefen` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeichenblatt_svg_speichern` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeit_ods` | yes | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
| `zeitzone_erkennen` | — | yes | yes | NO ADAPTER; explicit negative/unsupported response | NO ADAPTER; shared action disabled/rejected |
