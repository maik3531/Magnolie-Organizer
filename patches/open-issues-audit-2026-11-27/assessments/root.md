# Einzelbewertungen: root

Die Aussagen unterscheiden Quellbefund, vorbereiteten Patch und noch offene installierte Abnahme.

## [#243](https://github.com/maik3531/Magnolie-Organizer/issues/243) — OR6: verbleibende Overrides, Metadaten und Originalkontexte – Rest #222

**Bewertung:** Funktion oder Integration noch offen

Die früheren Basislücken sind überwiegend geschlossen; unverstandene OR6-Metadaten und komplexere Originalkontexte bleiben ein realer eigener Rest.

**Bereits umgesetzt / belegt:** Die Reader erhalten verifizierte finite Serien, verschobene indizierte Ausnahmen, frühere Seriensegmente, Kontaktgruppen, bekannte Telefonkontexte, Planerwerte und jährliche gegenüber einmaligen Jahrestagen.

**Noch offen:** Unabhängige Originalsemantik für abweichende Meeting-/Busy-Daten, leere/verschachtelte Verteiler, weitere Anhänge/Erinnerungen und vertrauliche Zielbereiche fehlt. Die aktuellen Gleichheitswächter halten unbekannte Unterschiede bewusst zurück.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen; nächste Erweiterung nur an unabhängig belegtem synthetischem Originalfall. Keine bereits vorhandenen Mappingfixes nochmals erstellen.

**Prüfgrenzen:** Keine privaten Originalbücher oder ausgeschlossenen Notizbereiche verwendet; kein neuer Originalprogramm-/Migrationsnachweis.

**Belege:**

- [contracts/or6-import.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-import.md): Aktuelle unterstützte Teilmenge und ausdrücklich nicht unterstützte Restformen.
- [magnolie-organizer/bin/magnolie_or6.py](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie_or6.py): Serienhistorie und Overrides verwerfen unbekannte Inhalts-/Busy-/Meetingunterschiede nicht stillschweigend.
- [magnolie-organizer-windows/Or6Codec.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/Or6Codec.cs): Entsprechender C#-Importumfang.
- [https://github.com/maik3531/Magnolie-Organizer/issues/243#issuecomment-6867933825](https://github.com/maik3531/Magnolie-Organizer/issues/243#issuecomment-6867933825): #616 erledigt; verbleibende abweichende Meetingfelder konkret benannt.

## [#258](https://github.com/maik3531/Magnolie-Organizer/issues/258) — Zeitzonenmanagement: IANA/iCalendar-konforme Technik mit einfacher seniorengerechter Oberfläche

**Bewertung:** Funktion oder Integration noch offen

Die Zeitzonentechnik ist vorhanden, die verlangte vereinfachte Normalansicht ist noch nicht vollständig umgesetzt.

**Bereits umgesetzt / belegt:** Normative IANA-Daten, automatische/manuelle Erkennung, Quell-/Kontakt-/Kalenderanzeigen und getrennte Anzeigeplanung sind im aktuellen Code vorhanden.

**Noch offen:** oeffneZeitzonenManagement zeigt weiterhin Bereichswahl, Quellenfolge Phone→GPS→IP→System sowie einen achtzeiligen manuellen Fallback direkt. Der geforderte standardmäßig geschlossene erweiterte Bereich und die tatsächliche 20-Sprachen-/native UX-Abnahme fehlen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als enges UX-Restissue behalten; vorhandene Technik wiederverwenden und die Bedienung samt Übersetzungen gezielt vereinfachen.

**Prüfgrenzen:** Kein neuer nativer Bedienlauf. Der aktuelle Sourcebefund betrifft die sichtbare Dialogstruktur, nicht einen erneut behaupteten TZDB-Rechenfehler.

**Belege:**

- [magnolie-organizer/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/web/anwendung.js): oeffneZeitzonenManagement: sichtbare scope/source/picker-Struktur ohne geschlossenes details für Sonderregeln.
- [magnolie-organizer-windows/app/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/app/web/anwendung.js): Zweiter Desktop verwendet dieselbe Zeitzonenbedienung.
- [magnolie-organizer-windows/TimeZoneManagement.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/TimeZoneManagement.cs): Vorhandene native Erkennung und Revisionsgrenzen.
- [magnolie-organizer-windows/tests/TimeZoneManagementTests.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/tests/TimeZoneManagementTests.cs): Bestehende technische Regressionen; ersetzen keine Senioren-UX-Abnahme.

## [#380](https://github.com/maik3531/Magnolie-Organizer/issues/380) — Müllkalender: Feiertagsverschiebung und einzelne Ersatztermine ohne erfundene Abholdaten

**Bewertung:** Funktion oder Integration noch offen

Kein belegter falscher Feiertagsalgorithmus; die manuelle Ausnahme-/Ersatzbedienung im Müllkalender bleibt offen.

**Bereits umgesetzt / belegt:** Manuelles Wochenintervall und kommunaler ICS-/CSV-Import sind getrennt. EXDATE lässt aus, ein tatsächlich geliefertes RDATE benennt den Ersatz; ohne Ersatz wird kein Folgetag erfunden.

**Noch offen:** Für den ursprünglichen Bericht fehlen Kommune, Jahr, Quelle und Importart. Ein eigener Bedienweg für manuelle Einzelausnahme/Ersatz im Müllkalender ist nicht durch normale Termin-Einzellöschung erledigt.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen, Beschreibung auf den konkreten Bedienrest konzentrieren. Kein pauschales Verschieben von Feiertagen implementieren.

**Prüfgrenzen:** Keine kommunale Originaldatei vorhanden; vorhandene Fälle in dieser Bestandsprüfung nicht als neue native Abnahme ausgegeben.

**Belege:**

- [contracts/waste-holiday-authority.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/waste-holiday-authority.md): Expliziter Quellenvorrang und genau abgegrenzter Rest.
- [magnolie-organizer/pruefungen/waste-holiday-authority.cjs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/pruefungen/waste-holiday-authority.cjs): Sechs bestehende duale Desktopfälle.
- [https://github.com/maik3531/Magnolie-Organizer/issues/380#issuecomment-6637726022](https://github.com/maik3531/Magnolie-Organizer/issues/380#issuecomment-6637726022): Bisherige Fälle positiv; unbekannte kommunale Eingabe und manueller UI-Rest getrennt.

## [#382](https://github.com/maik3531/Magnolie-Organizer/issues/382) — Termin-Einzellöschung: native Providerabnahme und alte Mehrfach-Uhrzeiten nach #379

**Bewertung:** Funktion oder Integration noch offen

Die ursprüngliche sichere Einzel-/Serienlöschung ist umgesetzt; Legacy-Mehrfachuhrzeiten und native Providerabnahme bleiben eigenständig.

**Bereits umgesetzt / belegt:** EXDATE wird an den exakten UTC-/floating-/DATE-Vorkommensfall gebunden. Ersatztermine und konservative Rollbackgrenzen sind vorhanden.

**Noch offen:** terminVorkommenAusnahme hält Legacy-Einträge mit icsZusatzTermine weiterhin zurück, weil eine Tagesausnahme mehrere Uhrzeiten träfe. Dazu fehlen aktueller nativer Provider-Save/Reopen sowie Papierkorb-/Rollbacknachweis.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen: Legacy-Ausnahmeidentität gezielt erweitern und native Fälle getrennt nachweisen.

**Prüfgrenzen:** Ein Host-/DOM-Test wäre kein Beleg für eine tatsächliche Providerübernahme oder installierte Paketabnahme.

**Belege:**

- [magnolie-organizer/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/web/anwendung.js): terminVorkommenAusnahme: ausdrücklicher Guard bei Legacy-icsZusatzTermine; vollständige ICS-EXDATE-Identität.
- [magnolie-organizer-windows/app/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/app/web/anwendung.js): Entsprechender Windows-UI-Pfad.
- [https://github.com/maik3531/Magnolie-Organizer/issues/382#issuecomment-6638434337](https://github.com/maik3531/Magnolie-Organizer/issues/382#issuecomment-6638434337): #383-Ersatzfälle bestanden; geänderte/fehlende/synchronisierte Providerobjekte werden konservativ gehalten.

## [#449](https://github.com/maik3531/Magnolie-Organizer/issues/449) — Notizenimport: native Linux-/Windows-Abnahme des Anhangserhalts (Rest aus #445)

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der Anhangsverlust ist im Quellcode behoben; übrig ist die echte native Datei-/Speicher-/Wiederöffnungsabnahme.

**Bereits umgesetzt / belegt:** mergeNotizen vergleicht sichtbaren Namen, abgeleiteten Typ und exakte Datenbytes; zufällige Anhangs-IDs sind keine Inhaltsidentität. Teilweise ungültige Anhangslisten werden nicht still gekürzt übernommen.

**Noch offen:** Im echten GTK/WebKit und Windows/WebView2 je zwei gleichnamige PNG/PDF mit unterschiedlichen Bytes auswählen, speichern und nach Prozessneustart prüfen; Abbruch und Größenüberschreitungen einschließen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Keinen neuen Produktpatch. Native Restkriterien mit aktuellem Paket-/Quellhash ausführen bzw. in geeignetem Abnahmeissue erhalten.

**Prüfgrenzen:** Keine reale GTK-/WebView2-Dateiauswahl oder installierte Wiederöffnung in dieser Quellsichtung.

**Belege:**

- [magnolie-organizer/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/web/anwendung.js): mergeNotizen und gleicheAnhaenge enthalten den erforderlichen Bytes-/Namens-/Typvergleich und Ganzlisten-Guard.
- [magnolie-organizer-windows/tests/note-import-attachments.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/tests/note-import-attachments.js): Bestehender tatsächlicher UI-Import mit synthetischen Save-ACKs; Umfang ist ausdrücklich Host/DOM.

## [#452](https://github.com/maik3531/Magnolie-Organizer/issues/452) — Tablet/TZDB: ThreeTenBP liefert falsche Gaza-/Hebron-Zeiten und erfolgreiche falsche ICS-Roundtrips

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der titelgebende ThreeTenBP-Zonenfehler ist im aktuellen Codec ersetzt; offen ist die aktuelle native Portmatrix.

**Bereits umgesetzt / belegt:** Kotlin nutzt ProviderZoneDatabase.bundled und PointResolver für Zonenregeln; ThreeTenBP bleibt für lokale Kalenderarithmetik. Die Gaza-2074- und eingebetteten-Zonen-Regressionsfälle liegen vor. Swift CalendarTimeContext bindet normative Regeln.

**Noch offen:** Aktuelle Android-/Mac-Dateiimport-, WebView-/Worker-, Restore- und Prozessneustartfälle mit dem tatsächlich gebündelten Datenstand; nicht erneut denselben bereits korrigierten Provider implementieren.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Verbleibende native Fälle in Leitissue #680 übernehmen, dann dieses erledigte Codefehlerissue als zusammengeführt schließen.

**Prüfgrenzen:** Historische Referenzzahlen sind dokumentierte Vorbelege. Neue gezielte JVM-Prüfung wird separat protokolliert; kein Android-/Mac-Geräteerfolg daraus ableiten.

**Belege:**

- [Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/ICalendarImport.kt](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/ICalendarImport.kt): knownZone verwendet ProviderZoneDatabase; Resolver bevorzugt eingebettete Definitionen.
- [Magnolie-Organizer-Android-Tablet-Beta/app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/ProviderCodecMigrationTest.kt](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-Android-Tablet-Beta/app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/ProviderCodecMigrationTest.kt): Gaza 2074 und bisherige Markerfälle im tatsächlichen Codec.
- [Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift): Explizite normative Zeitautorität.
- [https://github.com/maik3531/Magnolie-Organizer/issues/452#issuecomment-7186470845](https://github.com/maik3531/Magnolie-Organizer/issues/452#issuecomment-7186470845): Aktueller Mac-Code vorhanden; historische Läufe sind keine neue Paketmatrix.

## [#453](https://github.com/maik3531/Magnolie-Organizer/issues/453) — ICS-Ports: eigene VTIMEZONE-TZIDs kollidieren mit privaten UTC-Stringmarkern

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

UTC-Stringmarker kollidieren im aktuellen Portcode nicht mehr mit benutzerdefinierten TZIDs.

**Bereits umgesetzt / belegt:** Kotlin trennt absolute UTC per null von floating und benannter Quelle; Swift verwendet CalendarTimeSource.absoluteUTC/floating/named. Eingebettete Zonen besitzen Vorrang vor Datenbanknamen.

**Noch offen:** Eigene TZIDs @utc, @magnolie-utc-instant und UTC mit eingebetteter VTIMEZONE im aktuellen nativen Import/Export/Save/Reopen auf Android und Mac nachweisen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Diese drei expliziten TZID-Sonderfälle in #680 erhalten und #453 danach zusammengeführt schließen.

**Prüfgrenzen:** Keine Behauptung eines neuen native Save/Reopen; eine erneute enge JVM-Prüfung wird gesondert belegt.

**Belege:**

- [Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/ICalendarImport.kt](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/ICalendarImport.kt): Resolver.instant/clock: null ist Protokollzustand, keine benutzbare TZID-Zeichenfolge.
- [Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift): Typisierte CalendarTimeSource statt Sentinelstring.
- [Magnolie-Organizer-Android-Tablet-Beta/app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/ProviderCodecMigrationTest.kt](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-Android-Tablet-Beta/app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/ProviderCodecMigrationTest.kt): Former-marker-Sonderfälle liegen als Regression vor.
- [https://github.com/maik3531/Magnolie-Organizer/issues/453#issuecomment-7186471583](https://github.com/maik3531/Magnolie-Organizer/issues/453#issuecomment-7186471583): Bestehender Mac-Fix und historischer nativer Teilnachweis klar abgegrenzt.

## [#464](https://github.com/maik3531/Magnolie-Organizer/issues/464) — Serientermine: verschiedene Ausnahmen am selben Zielzeitpunkt werden zusammengefaltet

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der ursprüngliche Zusammenfaltfehler ist durch quellen- und RID-genaue Identität geschützt.

**Bereits umgesetzt / belegt:** portTerminOccurrenceCompatible prüft Quellkennung, Wire-UID und vollständige rohe RECURRENCE-ID einschließlich TZID/VALUE/RANGE. Gleicher Zielzeitpunkt oder Titel reicht nicht zum Zusammenfalten; mehrdeutige Daten bleiben getrennt.

**Noch offen:** Beide unterschiedlichen Ausnahmen in aktuellem Mac/Tablet nativ speichern und separat wiederöffnen, einschließlich lokaler IDs, Referenzen und unbekannter Felder.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Native Restfälle in #465 als eigene Untergruppe übernehmen; #464 anschließend zusammengeführt schließen.

**Prüfgrenzen:** Die projizierte UI verwendet Test-ACKs; aktuelle erneute Regression ersetzt keine echte Mac-/Tablet-Diskwiederöffnung.

**Belege:**

- [port-adapters/occurrence-identity.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/port-adapters/occurrence-identity.js): Expliziter opaque Quellen-/Wire-/RID-Vergleich und konservative Fehlformen.
- [port-adapters/tests/occurrence-identity.cjs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/port-adapters/tests/occurrence-identity.cjs): 29 relevante UI-Identitätsfälle samt synthetischer Speicherung.
- [https://github.com/maik3531/Magnolie-Organizer/issues/464#issuecomment-7186473921](https://github.com/maik3531/Magnolie-Organizer/issues/464#issuecomment-7186473921): Codefix und UI-Prüfungen bereits vorhanden; nativer Rest bleibt.

## [#465](https://github.com/maik3531/Magnolie-Organizer/issues/465) — ICS-Altbestand: verbleibende Port-Abnahme und exakte Reparatur bereits gespeicherter Ausnahme-Duplikate

**Bewertung:** Funktion oder Integration noch offen

Altkennungsbelege und begrenzte Wiederimportadoption sind implementiert; die Reparatur bereits gespeicherter Doppelpaare fehlt.

**Bereits umgesetzt / belegt:** Die heutige Mac-Dateiroute läuft über FileImportHost und den Python-Helfer. calendar_evidence erzeugt den transienten quellhash-/index-/Wire-/RID-gebundenen Sidecar; file-import.js führt ihn zur streng gebundenen Aliasregistrierung. Die frühere direkte main.swift→ICalendarImport.response-Route ist nicht mehr die aktuelle Route.

**Noch offen:** Exakt bestätigte bereits doppelte gespeicherte Paare samt widersprüchlichen Listen, unbekannten Feldern, Verweisen und Komponentenassoziationen reparieren; strenge Wiederöffnungsprüfung erhalten; aktueller nativer Mac-/Tablet-Save/Reopen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leitissue für Ausnahmeidentität/Altbestand behalten; native Restfälle aus #464 als gesonderte Abnahmepunkte aufnehmen.

**Prüfgrenzen:** Kein pauschaler automatischer Dedup-Patch und keine neue native Paarreparatur ausgeführt.

**Belege:**

- [Magnolie-Organizer-macOS-Beta/ImportHelper/calendar_evidence.py](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/ImportHelper/calendar_evidence.py): Aktueller Python-Dateiimport erzeugt legacyAndroidAliases.
- [Magnolie-Organizer-macOS-Beta/Projection/file-import.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Projection/file-import.js): Übergabe an macOSBetaNativeCalendarResult.
- [Magnolie-Organizer-macOS-Beta/Projection/calendar-legacy-alias.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Projection/calendar-legacy-alias.js): Transienter WeakMap-Beleg und erneute Bindungsprüfung vor Mutation.
- [contracts/macos-465-native-calendar-alias-adoption.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/macos-465-native-calendar-alias-adoption.md): Paarreparatur ausdrücklich nicht vom bestehenden Teilfix abgedeckt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/465#issuecomment-7186474755](https://github.com/maik3531/Magnolie-Organizer/issues/465#issuecomment-7186474755): Teilfix, Hostbelege und verbleibende gespeicherte Duplikate getrennt.

## [#511](https://github.com/maik3531/Magnolie-Organizer/issues/511) — Fortsetzung #455: opaque Unicode-JSON-Schlüssel verlustfrei bis zum nativen Mac-Buch erhalten

**Bewertung:** Funktion oder Integration noch offen

Die No-loss-Prüfung ist korrigiert; der vollständige verlustfreie Swift-JSON-Pfad für kollidierende Unicode-Schlüssel bleibt offen.

**Bereits umgesetzt / belegt:** Document.assertNoLoss ordnet Feldnamen und IDs über OpaqueUTF8Identity zu. JSONKeys unterscheidet echte doppelte dekodierte Schlüssel von der noch nicht darstellbaren kanonischen Swift-Kollision.

**Noch offen:** Eine durchgängige Objektstruktur muss zugleich NFC-/NFD-äquivalente verschiedene Schlüssel in Parse/Validate/Save/Restore/Export erhalten. [String:Any] kann das weiterhin nicht; der Guard vor JSONSerialization darf nicht einfach entfernt werden.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen; eigenständige verlustfreie Repräsentation mit kompletter nativer Speicher-/Restorefolge entwickeln.

**Prüfgrenzen:** Kein Swift-Compiler-/WKWebView-Erfolg in dieser Linux-Umgebung behauptet; der aktuelle Guard vermeidet stillen Verlust.

**Belege:**

- [Magnolie-Organizer-macOS-Beta/Sources/BetaCore/Contract.swift](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/Contract.swift): assertNoLoss verwendet opaque Identität; JSONKeys besitzt getrennte decodedKeys/foundationKeys-Guards.
- [Magnolie-Organizer-macOS-Beta/JSON-IDENTITY-511.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/JSON-IDENTITY-511.md): Konkrete End-to-End-Grenzen und vorbereitete native Regressionen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/511#issuecomment-7186477162](https://github.com/maik3531/Magnolie-Organizer/issues/511#issuecomment-7186477162): Begrenzter Teilfix bereits vorhanden; vollständige Darstellung weiterhin offen.

## [#566](https://github.com/maik3531/Magnolie-Organizer/issues/566) — Windows: gemeldete Kontakt-Importkonflikte mit Linux-Verhalten vergleichen

**Bewertung:** Konkreter Quellen-/Testfehler, Patch bereit

Der synthetisch belegte CSV-Teilfehler ist auf der aktuellen Basis weiterhin reproduzierbar; der historische private OR6-/UI-Bericht ist separat ungeklärt.

**Bereits umgesetzt / belegt:** Die Sammelentscheidung 'neue Kontakte für alle' ist seit #572 umgesetzt. Der aktuelle Windows-CSV-Reader nimmt dennoch nur die zuerst gefundene Anschrift und verliert HOME-/WORK-Telefonrollen; Linux bildet bei bestimmten Spalten falsche Misch-/HOME-Adressen.

**Noch offen:** Den bereits geprüften CSV-Fix auf den aktuellen Stand übernehmen. Anschließend bleibt die historische installierte Windows-Konfliktfolge mit ihrem Zielbestand und genauer Entscheidung gesondert zu reproduzieren.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Beiliegenden #566-Teilpatch anwenden; Issue für den unabhängigen historischen GUI-Rest offen halten.

**Prüfgrenzen:** Nur synthetische CSV-/vCard-Fixtures und tatsächliche Python-/C#-Reader auf Linux. Keine private Datei oder native Windows-Paketabnahme.

**Belege:**

- [magnolie-organizer-windows/ExchangeCodec.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/ExchangeCodec.cs): ParseLotusCsv bildet im ungepatchten Stand genau ein Anschriftenobjekt und nur CELL/FAX/VOICE.
- [magnolie-organizer/bin/magnolie-organizer](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie-organizer): Ungepatchter _lotus_kontakte-Pfad; neue Vorherprüfung bestätigt sechs Adress-/Rollenfehler.
- [magnolie-organizer/web/anwendung.js](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/web/anwendung.js): Sammelaktion erlaubt plan.modus===new bereits zielunabhängig.
- [https://github.com/maik3531/Magnolie-Organizer/issues/566#issuecomment-7218612878](https://github.com/maik3531/Magnolie-Organizer/issues/566#issuecomment-7218612878): Vorhandener enger CSV-Patch, Aufgabenaliase und Grenze zum privaten OR6-Konfliktbericht.
- [validation/before/python.log](../validation/before/python.log): Aktuelle Basis: sechs CSV-Kontaktfälle rot.
- [validation/after/csv.log](../validation/after/csv.log): Gepatchte C#-CSV-Gruppen beide grün.

## [#569](https://github.com/maik3531/Magnolie-Organizer/issues/569) — Lotus-Jahrestage: separaten ICS-Export samt Wiederholung und Zielbereich prüfen

**Bewertung:** Gemeldeter Fehler noch nicht bestätigt

Der gemeldete LCS-/ICS-Verlust ist ohne die tatsächliche berichtete Eingabe weiterhin nicht als Magnolie-Parserfehler belegt.

**Bereits umgesetzt / belegt:** Unabhängige synthetische Lotus-LCS-Ausgaben mit Jahrescheckbox an/aus waren abgesehen von UID/DTSTAMP identisch und enthielten keine RRULE/RDATE. Der native OR6-Reader unterscheidet jährliche und einmalige Jahrestage anhand belegter Originalflags.

**Noch offen:** Exakte LCS-/ICS-Eingabe des ursprünglichen Berichts oder ein weiterer unabhängiger synthetischer Originalexport mit wirklicher Wiederholungsinformation fehlt.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als unbestätigten Bericht offen halten oder in den OR6-Audit aufnehmen; keine Jahresregel allein aus Kategorie/Titel erfinden.

**Prüfgrenzen:** Kein Zugriff auf die fehlende Originaleingabe; bestehende synthetische Originalprobe nicht als Lösung des historischen Falls ausgeben.

**Belege:**

- [magnolie-organizer/bin/magnolie_or6.py](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie_or6.py): Jahrescheckbox und einmaliger All-day-Termin werden getrennt abgebildet.
- [contracts/or6-import.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-import.md): Verifizierte Annual-/One-off-Abgrenzung.
- [https://github.com/maik3531/Magnolie-Organizer/issues/569#issuecomment-6862703283](https://github.com/maik3531/Magnolie-Organizer/issues/569#issuecomment-6862703283): Original-LCS-Gegenprobe enthält keine belastbare Jahresregel.
- [https://github.com/maik3531/Magnolie-Organizer/issues/569#issuecomment-6866510540](https://github.com/maik3531/Magnolie-Organizer/issues/569#issuecomment-6866510540): Tatsächlich gemeldete Datei fehlt weiter; kein Parserfehler nachgewiesen.

## [#578](https://github.com/maik3531/Magnolie-Organizer/issues/578) — OR6: bereitgestellte Original- und Exportdatei auf weitere unbemerkte Übernahmefehler prüfen

**Bewertung:** Leitauftrag oder verbindliche Vorgabe

Der breite OR6-Migrationsauftrag ist weiterhin ein Audit-/Koordinationsissue, keine einzelne noch offene Parserkorrektur.

**Bereits umgesetzt / belegt:** Mehrere konkrete Aufgaben-, Planer-, Kategorien-, Datums-, Serien- und Rubriklöschlücken wurden in eigenen Issues umgesetzt und sind in den aktuellen Readern und Verträgen vorhanden.

**Noch offen:** Vollständige semantische Migration, fehlende strukturierte Zielmöglichkeiten und unabhängige Originalkontexte bleiben; aktuelle konkrete Reste liegen besonders in #243/#569/#611/#615. Backup-/Restorequalität gehört zum ausdrücklich einbezogenen Auftrag.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Leit-/Auditissue behalten; konkrete Teilissues verlinken und erledigte Altaufgaben aus der aktiven Restliste entfernen.

**Prüfgrenzen:** Keine pauschale 100%-Migrationsabnahme; private ausgeschlossene Notizbereiche bleiben außerhalb der Untersuchung.

**Belege:**

- [contracts/or6-import.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-import.md): Aktueller Umfang mit abgegrenzten unterstützten und nicht unterstützten Originalformen.
- [magnolie-organizer/bin/magnolie_or6.py](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie_or6.py): Tatsächlicher Reader hält unbekannte Formen zurück und berichtet Verluste.
- [https://github.com/maik3531/Magnolie-Organizer/issues/578#issuecomment-6863158630](https://github.com/maik3531/Magnolie-Organizer/issues/578#issuecomment-6863158630): Nutzerziel: fehlende nötige Zielfunktionen ergänzen, nicht nur Ersatznotizen; Backups/Restore einbezogen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/578#issuecomment-6866773323](https://github.com/maik3531/Magnolie-Organizer/issues/578#issuecomment-6866773323): Ältere Unterbefunde bereits erledigt; präzise Folgereste genannt.

## [#611](https://github.com/maik3531/Magnolie-Organizer/issues/611) — OR6: aktive Bereichs-/Containerbindung getrennt von gewöhnlicher Rubriklöschung verifizieren

**Bewertung:** Gemeldeter Fehler noch nicht bestätigt

Ein allgemeiner aktiver-aber-unerreichbarer OR6-Bereich ist noch nicht unabhängig bewiesen; ein vorschneller Filter wäre unbegründet.

**Bereits umgesetzt / belegt:** Gewöhnliche Rubriklöschung und getrennte innere Bereichsidentität trotz äußerer Tabumbenennung sind anhand synthetischer Originalfälle belegt. Statische Originalhilfe bestätigt die getrennten From/Section/Tab-Begriffe.

**Noch offen:** Feste äußere Container-/Include-/Detach-Links und ein aktiver, tatsächlich nicht erreichbarer Original-Sollfall fehlen. Weder Namensgleichheit noch Allokation beweist globale Sichtbarkeit.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Unbestätigte Semantik gezielt mit synthetischem Include-/Detach-Fall klären; kein Namens-/Namespacefilter patchen.

**Prüfgrenzen:** Keine privaten Bücher, externen Included-Dateien oder ausgeschlossenen Payloads verwendet; keine neue VM-/Originalprogrammsitzung.

**Belege:**

- [contracts/or6-import.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-import.md): #570-Löschung bleibt ausdrücklich enger als allgemeine Root-/Containersemantik.
- [contracts/or6-native-section-removal.json](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-native-section-removal.json): Unabhängige bekannte Rubriklöschfixtures.
- [https://github.com/maik3531/Magnolie-Organizer/issues/611#issuecomment-6866738543](https://github.com/maik3531/Magnolie-Organizer/issues/611#issuecomment-6866738543): Umbenennen/gezieltes Entfernen belegt; allgemeine Erreichbarkeit nicht.
- [https://github.com/maik3531/Magnolie-Organizer/issues/611#issuecomment-6891656309](https://github.com/maik3531/Magnolie-Organizer/issues/611#issuecomment-6891656309): HLP jetzt statisch lesbar; dennoch kein Beleg für einen allgemeinen Sichtbarkeitsfilter.

## [#615](https://github.com/maik3531/Magnolie-Organizer/issues/615) — OR6: Pencil-in und natives Busy-Feld getrennt von Serien-Overrides abbilden

**Bewertung:** Funktion oder Integration noch offen

Vorläufiger Terminstatus ist abgebildet; eine belastbare allgemeine Busy-/Verfügbarkeitszuordnung fehlt weiterhin.

**Bereits umgesetzt / belegt:** Beide Reader setzen vorlaeufig aus dem nativen Pencil-in-Feld. Die inzwischen statisch lesbare Originalhilfe erklärt Pencil-in als tentative und unterscheidet Konfliktprüfung; der frühere HLP-Zugriffsblocker ist überholt.

**Noch offen:** Die beobachtete Busy-Änderung 0100→fehlend→0100 beweist keine allgemeine TRANSP-Abbildung. Es fehlt ein kontrollierter unabhängiger Verfügbarkeits-/Meeting-Sollfall samt exakter Feldbindung.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen; konkrete Verfügbarkeit an unabhängiger Synthetik klären und dann eng mappen.

**Prüfgrenzen:** Kein spekulatives TRANSP-Mapping; keine privaten Termine oder neuen Originalprogramm-Aktionen.

**Belege:**

- [magnolie-organizer/bin/magnolie_or6.py](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie_or6.py): vorlaeufig aus Feld 18 vorhanden; abweichende Busy-/Meeting-Seriendaten werden gehalten.
- [magnolie-organizer-windows/Or6Codec.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/Or6Codec.cs): Entsprechender vorlaeufig-Pfad.
- [contracts/or6-import.md](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/contracts/or6-import.md): Busy-Verfügbarkeit separat von sicheren Serienoverrides.
- [https://github.com/maik3531/Magnolie-Organizer/issues/615#issuecomment-6891647632](https://github.com/maik3531/Magnolie-Organizer/issues/615#issuecomment-6891647632): Originalhilfe ist lesbar, aber persistierte Busy→TRANSP-Semantik nicht bewiesen.

## [#659](https://github.com/maik3531/Magnolie-Organizer/issues/659) — Windows-Zeitzonen: installierte Organizer-/WebView2-/Scheduler-Abnahme nach #653

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die installierte Windows-Zeitmatrix ist weitgehend belegt; verbleibend ist der echte Datei-Speichern-/Reimportdialog.

**Bereits umgesetzt / belegt:** Dokumentiert sind 37 native und 37 WebView-Uhren, DATE/floating/VTIMEZONE in zwei Kontexten, echter stiller Timer, persistierte Foldidentität über getrennten Prozess und unveränderter Autostart. Echter Datei-Öffnen-Import war ebenfalls erfolgreich.

**Noch offen:** Der tatsächliche Save-Dialog lieferte bei Win32-Automation nicht den gewünschten Zielnamen; die semantische Gegenprobe fand kein eindeutig bedienbares Feld. Das ist ein Automationsblocker, kein belegter Produktfehler. Echter Save und Reimport fehlen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Den genauen Windows-Save-/Reimportrest samt positiven Vorbelegen nach #680 übertragen und #659 zusammengeführt schließen.

**Prüfgrenzen:** Die hier verfügbare Linux-Prüfumgebung ersetzt keinen installierten Windows-IFileDialog.

**Belege:**

- [magnolie-organizer-windows/TimeZoneManagement.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/TimeZoneManagement.cs): Vorhandene aktuelle native Zeitverwaltung.
- [magnolie-organizer-windows/tests/TimeZoneManagementTests.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/tests/TimeZoneManagementTests.cs): Bestehende technische Regression, kein echter Dialognachweis.
- [https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6917640439](https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6917640439): Konkrete erfolgreiche installierte Teilmatrix.
- [https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6918327685](https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6918327685): Datei-Öffnen positiv; Save-Ziel nicht korrekt bestätigt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6918378666](https://github.com/maik3531/Magnolie-Organizer/issues/659#issuecomment-6918378666): Semantische Dialogprobe blockiert; keine weitere Produktursache bewiesen.

## [#680](https://github.com/maik3531/Magnolie-Organizer/issues/680) — Zeitzonen: nativer Linux-Journal-Restore und verbleibende macOS-/Tablet-/Android-Matrix – Rest #661

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der titelgebende Linux-Journal-Restore ist bereits belegt; dieses Issue eignet sich als Leitissue für die aktuelle native Zeitzonenmatrix.

**Bereits umgesetzt / belegt:** Installierter Linux-Restore v152 stellte 37 Kalenderfälle atomar wieder her und erhielt Notizen/Sync-Epoch über getrennten Prozess. Start-/Ressourcen- und DEB-Payloadlücken wurden separat korrigiert. #839-Tablet-Zustellung wurde nativ nachgewiesen.

**Noch offen:** Aktueller installierter Linux-Paket-/Dienst-/OS-Reminderpfad, vollständige aktuelle Mac-/Tablet-Matrix und tatsächliche macOS-Notification-Zustellung bleiben. Die vorliegenden entpackten Payload-/Hostläufe ersetzen diese Grenzen nicht.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Leitissue auf den heutigen Rest umbenennen und #452/#453/#659 mit konkreten Sonderfällen/positiven Vorbelegen konsolidieren.

**Prüfgrenzen:** Keine neue native Installation oder Mac-Zustellung behauptet. Historische private Belege werden als dokumentierte Nachweise, nicht als hier neu gelesene private Dateien behandelt.

**Belege:**

- [magnolie-organizer/bin/magnolie-organizer](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie-organizer): Aktueller _journal_wiederherstellen-Pfad mit Worker/atomarem Save.
- [Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CalendarTimeContext.swift): Normative Portgrundlage vorhanden.
- [https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-6918648959](https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-6918648959): Linux-Journal v152 ist ausdrücklich erfolgreich; nicht länger als fehlend führen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-6920564443](https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-6920564443): Korrigierte DEB-Payload geprüft, installierte Restgates getrennt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-7223554317](https://github.com/maik3531/Magnolie-Organizer/issues/680#issuecomment-7223554317): #839 geschlossen; installierte macOS-Zustellung bleibt hier.

## [#823](https://github.com/maik3531/Magnolie-Organizer/issues/823) — Additive Wiederherstellung: gleiche UID aus verschiedenen Kalendern verliert Einträge; Windows kann abbrechen oder Notizen duplizieren

**Bewertung:** Ursprünglicher Umfang erledigt oder entfallen

Während der Prüfung in main 50b15122 übernommen und bereits geschlossen: der letzte Kontaktlistenverlust ist damit behoben.

**Bereits umgesetzt / belegt:** Der ursprüngliche Quellen-/UID-Fix und nun auch kontaktpersonen in beiden Inhaltswhitelists sind vorhanden. Main hat die geprüften Produktänderungen unverändert übernommen und den gemeinsamen Vektor sowie dauerhaften Restore/Editorfälle zusätzlich um Betreuer/Betreuerin ergänzt.

**Noch offen:** Kein eigenständiger offener Quellrest dieses Issues. Historische Test- und Patchbelege bleiben nachvollziehbar, werden aber nicht nochmals als notwendiger Produktfix angeboten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Bereits erfolgte Schließung beibehalten. #823 aus der empfohlenen Rest-Patchfolge auf Basis 50b15122 entfernen.

**Prüfgrenzen:** Geprüft mit synthetischen Datensätzen im tatsächlichen Python-/C#-Code. Keine Aussage zur installierten GUI-/Paketabnahme.

**Belege:**

- [magnolie-organizer-windows/RestoreSelection.cs](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer-windows/RestoreSelection.cs): Kontakt-HashSet fehlt kontaktpersonen im ungepatchten Prüfstand.
- [magnolie-organizer/bin/magnolie-organizer](https://github.com/maik3531/Magnolie-Organizer/blob/7a490dd87e94eec08d7f09cb95a04b34bf4621c2/magnolie-organizer/bin/magnolie-organizer): Entsprechende inhaltsfelder-Liste fehlt ebenfalls.
- [https://github.com/maik3531/Magnolie-Organizer/issues/823#issuecomment-7223870692](https://github.com/maik3531/Magnolie-Organizer/issues/823#issuecomment-7223870692): Bereits übergebener Feldrest und eingegrenzter Patch.
- [validation/before/restore-identity.log](../validation/before/restore-identity.log): Aktueller C#-Quellhost scheitert genau am neuen Notfallkontaktfall.
- [validation/after/restore-identity.log](../validation/after/restore-identity.log): Gepatchte gemeinsame Identitätsgruppe besteht.
- [https://github.com/maik3531/Magnolie-Organizer/commit/50b1512234a765635f82af4537f277594fbf9878](https://github.com/maik3531/Magnolie-Organizer/commit/50b1512234a765635f82af4537f277594fbf9878): Beide Produktwhitelists übernehmen exakt das fehlende kontaktpersonen-Feld.
- [https://github.com/maik3531/Magnolie-Organizer/issues/823#issuecomment-7224612753](https://github.com/maik3531/Magnolie-Organizer/issues/823#issuecomment-7224612753): Übernahme, zusätzliche Rollenfälle, gezielte Prüfungen und Schließung dokumentiert.

