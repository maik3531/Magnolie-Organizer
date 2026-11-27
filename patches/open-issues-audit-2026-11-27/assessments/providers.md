# Einzelbewertungen: providers

Die Aussagen unterscheiden Quellbefund, vorbereiteten Patch und noch offene installierte Abnahme.

## [#64](https://github.com/maik3531/Magnolie-Organizer/issues/64) — Google-Tasks- und Microsoft/EAS-Aufgabenadapter anbinden – Folge #39

**Bewertung:** Funktion oder Integration noch offen

Die beiden separaten Aufgabenadapter fehlen weiterhin; eine korrekt ausgewählte VTODO-CalDAV-Quelle erledigt diesen Folgeauftrag nicht.

**Bereits umgesetzt / belegt:** Vorhandene DAV-Aufgabenwege und Quellenwahl sind implementiert. Die verwaltete Bridge nennt Google Tasks ausdrücklich nicht verfügbar; Microsoft-Ordner können eingerichtet und eindeutig ausgewählt werden.

**Noch offen:** Google-Tasks-Datenservice sowie tatsächliche Microsoft/EAS-Aufgabendaten einschließlich Lesen, Schreiben, Quellbindung und Rücklesebeleg anbinden. Keine neue OAuth-Appregistrierung aus diesem Auftrag ableiten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen halten als Adapterintegration; vorhandenen CalDAV-Auswahlfix nicht erneut implementieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L292](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L292): google.tasks.available bleibt false; der Quellenexport erfasst CalDAV-Kalender.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedEasSourceFolders.cs#L15](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedEasSourceFolders.cs#L15): Der Ordnervertrag ist ausdrücklich nur Einrichtung; keine Daten-, Schreib- oder Commitquittung.

## [#65](https://github.com/maik3531/Magnolie-Organizer/issues/65) — Linux/Google-Kalender: gemeldete fehlende Rücksynchronisation unter 2.0.24 prüfen

**Bewertung:** Gemeldeter Fehler noch nicht bestätigt

Der historische Google-Rücksyncbericht ist weiterhin nicht als aktueller allgemeiner Programmfehler reproduziert. Die konkrete Google-Livebedingung ist von erfolgreich geprüften anderen Wegen zu trennen.

**Bereits umgesetzt / belegt:** Native EDS-/Akonadi-Anlage und -Änderung sind im Produkt vorhanden. Die Diskussion dokumentiert positive installierte EDS-/Akonadi- und isolierte DAV-Rückleseläufe ohne Dubletten.

**Noch offen:** Bei passender echter Google-Quelle Rechte, beschreibbare Auswahl und denselben regulären Save-/Sync-/Readbackweg beobachten; die ursprüngliche unbekannte Adapterursache nicht erfinden.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als unbestätigten Bericht mit engem Google-Nachweisziel führen; keinen spekulativen Reparaturpatch und keine pauschale Behauptung eines weiterhin defekten Rücksyncs.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Ohne Originalreproduktion oder neuen Google-Lauf ist weder aktuelle Fehlerbestätigung noch eine abschließende Entwarnung möglich.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L20054](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L20054): eds_event_anlegen und eds_event_aendern verwenden echte EDS- beziehungsweise Akonadi-Schreibmethoden.
- [https://github.com/maik3531/Magnolie-Organizer/issues/65#issuecomment-5891005148](https://github.com/maik3531/Magnolie-Organizer/issues/65#issuecomment-5891005148): Positive andere Adapterproben; Google-Live-/Rechteprüfung ausdrücklich offen.

## [#75](https://github.com/maik3531/Magnolie-Organizer/issues/75) — Wunsch: Doppelte Erinnerungen anderer Programme optional zugunsten von Magnolie unterdrücken

**Bewertung:** Funktion oder Integration noch offen

Der optionale programmübergreifende Erinnerungsbesitz ist ein weiterhin eigenständiger Machbarkeits- und Funktionsauftrag.

**Bereits umgesetzt / belegt:** Magnolie besitzt eigene persistierte Erinnerungsquittungen und interne Dublettenregeln. Beim Einrichten verwalteter Google-Kalender setzt die Thunderbird-Bridge suppressAlarms; das ist eine enge Integration.

**Noch offen:** Dokumentierte Linux-/Windows-/Providerwege für selektive fremde Erinnerungen klären, stabile Ereignis-/Instanzidentität und rückgängig machbare Zuständigkeit bei Dienstende/Widerruf nachweisen. Ein universeller Schalter ist nicht vorhanden.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als begrenzte Machbarkeitsarbeit führen; interne Alarmkorrekturen nicht als Erledigung dieses Wunsches ausweisen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L37](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L37): signInGoogle setzt bei neu registrierten Kalendern suppressAlarms; kein allgemeiner Fremdprogrammvertrag.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L9](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L9): Der Scheduler verwaltet Magnolies eigenen Zustand und eigene Notice-Ausgabe.
- [https://github.com/maik3531/Magnolie-Organizer/issues/75](https://github.com/maik3531/Magnolie-Organizer/issues/75): Nutzer verlangt zuerst belegte Machbarkeit und reversible, identitätsgebundene Unterdrückung anderer Programme.

## [#146](https://github.com/maik3531/Magnolie-Organizer/issues/146) — Eigenprofil: Kontaktkarte, selektives Senden und echte Android-Profilquelle

**Bewertung:** Funktion oder Integration noch offen

Eigenprofilkarte, normaler Editor und selektive Weitergabe sind umgesetzt. Offen ist vor allem die automatische tatsächliche Samsung-Eigenprofilquelle, deren Zugriff im dokumentierten Gerätetest gerade nicht gelang.

**Bereits umgesetzt / belegt:** Separates eigenesProfil, normaler Mehrfeld-/Fotoeditor und Profilversand bestehen. Android liest canonical Profile oder eindeutig systemmarkiertes Eigenprofil, prüft Identität erneut und übernimmt Foto/Geburtstag, wenn der Provider sie liefert.

**Noch offen:** Einen unterstützten automatischen Zugriff für die betroffene OEM-Konfiguration finden oder dessen konkrete Grenze festhalten. Manuelle VCF-Übernahme ist vom Nutzer ausdrücklich kein Ersatz. Kein persönlicher Namensabgleich oder privater API-Bypass.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Titel/Rest auf automatische unterstützte Profilquelle präzisieren; bereits vorhandene UI-Funktionen nicht neu implementieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Die Diskussion belegt eine bestimmte OEM-Konfiguration, keine generelle Unmöglichkeit auf Android oder allen Samsung-Geräten.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactReadAndroid.kt#L96](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactReadAndroid.kt#L96): readOwnProfile nutzt Profile.CONTENT_URI und eine exakt revalidierte IS_USER_PROFILE-Ausweichquelle.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L20729](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L20729): Die getrennte Profilkarte verwendet die gemeinsamen Kontaktkarten-/Editorwege.
- [https://github.com/maik3531/Magnolie-Organizer/issues/146#issuecomment-6133017029](https://github.com/maik3531/Magnolie-Organizer/issues/146#issuecomment-6133017029): Konkrete Samsung-/Android-Diagnose lieferte keine öffentlich lesbaren Eigenprofilzeilen; keine allgemeine Samsung-Aussage.

## [#156](https://github.com/maik3531/Magnolie-Organizer/issues/156) — Native Online-Konten: Kontakt- und Kalenderabgleich über alle Systemanbieter prüfen

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Es bleibt eine Anbieter-/Fähigkeitsmatrix der vorhandenen nativen Online-Konten; kein aus dem Issue bewiesener neuer Adapterfehler.

**Bereits umgesetzt / belegt:** Der EDS-Einstieg lädt SourceRegistry, Kalender- und Adressbuchschnittstellen generisch. Er ist nicht auf Google als Anbieter fest verdrahtet.

**Noch offen:** Tatsächlich installierte WebDAV-/Nextcloud-/Exchange-/Microsoft365-Quellen mit den jeweils vom System angebotenen Rechten, Baselines, Aktualisierung und Fehlererhaltung prüfen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als konkrete Providerabnahme führen; nur einen neu reproduzierten Fehler als Quellfix abspalten, keine zusätzlichen Authentifizierungswege vorsorglich bauen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L19655](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L19655): EDS-Laden, SourceRegistry und eds_quellen verwenden die vorhandenen nativen Systemquellen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/156](https://github.com/maik3531/Magnolie-Organizer/issues/156): Google/EDS-Erfolg wird bestätigt, universelle Anbieterabnahme ausdrücklich nicht.

## [#158](https://github.com/maik3531/Magnolie-Organizer/issues/158) — Eigener Geburtstag: persönliche Glückwünsche und quellenübergreifende Identität

**Bewertung:** Funktion oder Integration noch offen

Persönliche Geburtstagsansprache und bestätigte quellenübergreifende Eigenidentität fehlen weiterhin als zusammenhängende Funktion.

**Bereits umgesetzt / belegt:** Das Eigenprofil bleibt getrennt; allgemeine Kontaktgeburtstage und native Jahrestagserinnerungen sind vorhanden.

**Noch offen:** Bestätigte Eigenprofil-/Kontakt-/Terminbindungen über Quellen nutzen, bestehende UIDs/ETags erhalten und persönliche Vorab-/Tagesansprache ohne zweite generische Meldung ergänzen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen halten; Identitätsvertrag vor Textänderung umsetzen. Nicht mit interner Alarmdeduplizierung oder der Profilkarte gleichsetzen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L464](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L464): AnniversaryNotice verwendet weiterhin generische Namens-/Geburtstagsansprache ohne Eigenprofilzuordnung.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L21639](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L21639): Der allgemeine Kontakt-Geburtstagseditor wird beim eigenen Profil bewusst nicht verwendet.
- [https://github.com/maik3531/Magnolie-Organizer/issues/158#issuecomment-6123028994](https://github.com/maik3531/Magnolie-Organizer/issues/158#issuecomment-6123028994): Neu gelesenes Eigenprofilgeburtsdatum muss mit vorhandener bestätigter Google/EDS/DAV-Identität zusammengeführt werden.

## [#159](https://github.com/maik3531/Magnolie-Organizer/issues/159) — Samsung-Eigenprofil: medizinische Informationen optional übernehmen und anzeigen

**Bewertung:** Funktion oder Integration noch offen

Medizinische OEM-Eigenprofildaten sind noch kein angebotener Übernahme-/Anzeigepfad; ihre tatsächliche Zugänglichkeit bleibt Voraussetzung.

**Bereits umgesetzt / belegt:** Der Android-Reader erfasst nur medizinisch benannte MIME-Typen als Fähigkeitsmetadaten und überträgt ausdrücklich keine Werte.

**Noch offen:** Tatsächlich erreichbare, ausgewählte Felder und getrennte Übernahme-/Anzeigeoptionen definieren; manuelle Werte bewahren und fehlenden OEM-Zugriff sichtbar behandeln.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als bedingte Provider-/Datenmodellfunktion führen, mit #146-Zugriffsgrenze verknüpfen; kein Blindpatch anhand von MIME-Namen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactReadAndroid.kt#L179](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactReadAndroid.kt#L179): Expliziter Kommentar: Capability metadata only; medizinische Werte benötigen einen eigenen angeforderten Datenpfad.
- [https://github.com/maik3531/Magnolie-Organizer/issues/159](https://github.com/maik3531/Magnolie-Organizer/issues/159): Abnahme verlangt echte zugängliche Felder und Freigaben; keine behaupteten privaten Samsung-Schnittstellen.

## [#161](https://github.com/maik3531/Magnolie-Organizer/issues/161) — Schulferien: keine täglichen Erinnerungen, optional einmal pro Zeitraum

**Bewertung:** Funktion oder Integration noch offen

Native Ferienanzeige und Terminerinnerungen sind getrennt, aber der geforderte quellengebundene Umgang mit importierten Ferien sowie die optionale einzelne Zeitraummeldung ist nicht vollständig umgesetzt.

**Bereits umgesetzt / belegt:** Ferien werden als eigene Kalenderdarstellung beziehungsweise aus synchronisierten Terminen projiziert. Native Erinnerungsreader bearbeiten Termine/Aufgaben/Jahrestage, nicht pauschal die Ferienanzeigeliste.

**Noch offen:** Bekannte importierte Ferienquellen sicher identifizieren und deren Standardunterdrückung beziehungsweise einmalige Zeitraumoption in Linux/Windows verbinden. Normale Termine nicht anhand ähnlicher Titel unterdrücken.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als eng zu spezifizierende Ferien-Erinnerungsfunktion halten; keine tägliche Fehlmeldung für alle nativen Ferienobjekte pauschal behaupten.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L11309](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L11309): istSynchronisierteFerien/ferienAusTermin sind Darstellungsprojektionen; sie erteilen keinen nativen Alarmvertrag.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L8769](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L8769): faellige_erinnerungen arbeitet auf Termineinträgen; keine quellengebundene Ferienperiode in diesem Auswahlpfad.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L115](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ReminderScheduler.cs#L115): SelectData übernimmt Termin-/Aufgabenprojektionen unter den bestehenden Gruppen-/Datenschutzregeln.

## [#192](https://github.com/maik3531/Magnolie-Organizer/issues/192) — MCP: Telefonie und SMS-Aktionen über bestehende Adapter vervollständigen – Rest #170

**Bewertung:** Funktion oder Integration noch offen

Die alte Aussage, öffentliche Wählen/Annehmen/Auflegen-Aktionen fehlten, ist überholt. SMS und Kommunikationsvorgaben bleiben eigenständiger Rest.

**Bereits umgesetzt / belegt:** Beide Frontends registrieren call_read sowie call_command_start/status/cancel; Linux und C# besitzen native Actor-Owner, Source-CAS, Dispatch-/Receipt- und Late-Reply-Grenzen. Der aktuelle mcp.md-Vertrag beschreibt diese Umsetzung bereits.

**Noch offen:** Routing-/Benachrichtigungsvorgaben, SMS-Senden, -Verlauf und -Planung an die vorhandenen angebotenen Adapter anbinden und deren Ergebnis-/Zustellungsgrenzen sowie reale Plattformabnahme erhalten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen für SMS/Routing und passende Abnahme halten. Engen Dokumentationspatch zu #192 liefern, der die veraltete Coverage-Zeile korrigiert; keinen vorhandenen Call-Actor neu implementieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Der neue Patch ändert nur die Coverage-Dokumentation; statischer Registrierungsabgleich genügt, keine Telefonaktion wird ausgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L40423](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L40423): Vier öffentliche Telefonwerkzeuge einschließlich dial/answer/end werden in mcpWerkzeuge registriert.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/web/anwendung.js#L39280](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/web/anwendung.js#L39280): Windows registriert denselben Call-Startvertrag.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_call_actors.py#L88](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie_call_actors.py#L88): Linux besitzt native Create/Start/Status/Cancel-Actors.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/TelefonCallActors.cs#L58](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/TelefonCallActors.cs#L58): C# revalidiert native Quelle, Verbindung und Owner.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/mcp.md#L118](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/mcp.md#L118): Aktueller Vertrag trennt persistierte Commandquittung von authentifiziertem Telefonergebnis und Zustellung.

## [#193](https://github.com/maik3531/Magnolie-Organizer/issues/193) — MCP: verbleibende KDE-Empfangs-, Routing- und Geräteaktionen anbinden – Rest #170

**Bewertung:** Funktion oder Integration noch offen

Grundkopplung, Medien, Dateisystem und grundlegende Eingabeeinstellungen existieren; der weitergehende KDE-Empfangs-/Routingumfang ist nicht vollständig an MCP angeschlossen.

**Bereits umgesetzt / belegt:** Der aktuelle KDE-Werkzeugkatalog enthält Mediengeräte/-status/-aktionen, Playerwahl, input_status/input_settings und Dateisystemstatus/-öffnen; gesonderte Kopplungswerkzeuge sind registriert.

**Noch offen:** Tatsächlich angebotene Empfangsvorgaben, Routing und weitere Geräte-/Zeichenaktionen mit existierenden nativen Fähigkeiten verbinden oder eine konkrete Plattformgrenze benennen. Standardmäßig ausgeschaltete Zeichenblattweitergabe bleibt erhalten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen, bereits verbundene input_settings nicht als fehlend zählen; Restaktionen einzeln inventarisieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L43438](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L43438): mcpKdeWerkzeuge zeigt den tatsächlichen begrenzten öffentlichen Operationenkatalog.
- [https://github.com/maik3531/Magnolie-Organizer/issues/193](https://github.com/maik3531/Magnolie-Organizer/issues/193): Der Rest ist ausdrücklich außerhalb bereits verbundener Basis-/Medien-/Dateisystemfunktionen abgegrenzt.

## [#194](https://github.com/maik3531/Magnolie-Organizer/issues/194) — MCP: verbleibende Produktwerkzeuge und Einstellungen verbinden – Rest #170

**Bewertung:** Funktion oder Integration noch offen

Mehrere Produktwerkzeuge sind bereits vorhanden, die konkret genannten übrigen Such-/Assistenten-/Setup- und Transferaktionen bleiben jedoch nicht insgesamt angebunden.

**Bereits umgesetzt / belegt:** Notes-Diagnostik und aktueller quellengebundener Medienstatus sind öffentlich verbunden. Medikamentendatensätze besitzen CRUD und Einstellungen; das ist nicht die externe Medikamentensuche. Eigenprofildaten können gelesen/bearbeitet werden.

**Noch offen:** Kontaktduplikat-Assistent, Wetter-/Medikamentensuche, noch fehlende Entwickler-/Support-/Thunderbird-Setupaktionen und tatsächliche Profil-/Foto-Transfers gegen aktuelle Handler einzeln verbinden.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als präzise Restliste führen; vorhandene Diagnostik, Medienstatus und Gesundheits-CRUD aus der Fehlmenge entfernen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L40238](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L40238): organizer_phone_media_status_read ist implementiert; nicht erneut als fehlendes nächstes Werkzeug behandeln.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L39115](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L39115): Medikamenten-CRUD ist vorhanden, während die Produktsuche einen getrennten Handler verwendet.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L43847](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L43847): Aktuelle Werkzeugregistrierung und bestehende Diagnostik sind überprüfbar.
- [https://github.com/maik3531/Magnolie-Organizer/issues/194#issuecomment-6928754174](https://github.com/maik3531/Magnolie-Organizer/issues/194#issuecomment-6928754174): Die Medienstatus-Teilumsetzung ist bereits im Thread bestätigt; gesamter Restauftrag bleibt getrennt.

## [#272](https://github.com/maik3531/Magnolie-Organizer/issues/272) — Internetkonten: integrierte Konto-Erweiterungen zusammen mit der Laufzeit automatisch aktualisieren

**Bewertung:** Funktion oder Integration noch offen

Eine gemeinsame regelmäßige Aktualisierung kompatibler Laufzeit-/Providerpakete ist weiterhin nicht vorhanden.

**Bereits umgesetzt / belegt:** PrepareProfile übernimmt paketierte angepasste Erweiterungen und berücksichtigt Version/Hash. EnsureAvailableAsync wählt zuerst eine bereits kompatible Laufzeit und bereitet nur bei deren Fehlen eine neue vor; Eigenupdates bleiben ausgeschaltet.

**Noch offen:** Den vorhandenen Updateweg um ein zusammengehöriges kompatibles Komponentenset und Wiederholungs-/Offlineverhalten ergänzen, bestehendes Profil und nutzbares Set erhalten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als echte Updateintegration offen halten. Früheren LastVersion-/Warmstartfix nicht als gesamte automatische Komponentenpflege ausweisen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedAccountRuntimeUpdater.cs#L22](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedAccountRuntimeUpdater.cs#L22): Ein vorhandener kompatibler Kandidat wird unmittelbar zurückgegeben; kein regelmäßiger gemeinsamer Updatezyklus.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L163](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L163): PrepareProfile staged integrierte XPIs; extensions.update.enabled und app.update.auto sind false.

## [#273](https://github.com/maik3531/Magnolie-Organizer/issues/273) — Thunderbird-Quellen beim Import wahlweise dauerhaft synchronisieren

**Bewertung:** Funktion oder Integration noch offen

Der ausdrücklich verlangte Importdialog mit Wahl zwischen einmaligem Import und dauerhaft gebundener Thunderbird-Synchronisation ist noch nicht verbunden.

**Bereits umgesetzt / belegt:** Die Livebridge exportiert vorhandene HTTPS-CardDAV-/CalDAV-Quellen mit stabiler Profil-/Quellidentität. Der Kontaktassistent trennt einmaligen Thunderbird-Import und die allgemeine Onlineadressbuch-Synchronisation.

**Noch offen:** Die gewählte tatsächliche Thunderbird-Livequelle nach Vorschau und SaveACK dauerhaft binden; Anbieterbreite, Read-only, fehlende Bridge, Gruppen, Abbruch und Wiederöffnung im selben Ablauf behandeln.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen halten; die vorhandene Bridge und DAV-Engine weiterverwenden. Eine separate Onlinequellenauswahl nicht als abgeschlossenen Import-/Syncwahlvertrag ausgeben.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L114](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L114): sources erfasst konfigurierte DAV-Ressourcen unter stabilen Thunderbird-Profilkennungen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L26726](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L26726): Thunderbird steht ausdrücklich unter Import once; Synchronize permanently führt zu einem getrennten allgemeinen Onlineadressbuchweg.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L34303](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L34303): starteImport(lokal) sendet Quelle/Bereich, keine persistente Syncwahl.

## [#274](https://github.com/maik3531/Magnolie-Organizer/issues/274) — Offlinebetrieb als normalen Zustand behandeln und gespeicherte Konten still weiterverwenden

**Bewertung:** Funktion oder Integration noch offen

Lokaler Betrieb und mehrere Retry-/Erhaltungsmechanismen bestehen; ein durchgehender normaler Offlinezustand für Konto-/Status-/Synchronisationsabläufe ist weiterhin nicht belegt oder vollständig modelliert.

**Bereits umgesetzt / belegt:** Lokal gespeicherte Inhalte und Telefon-WLAN-Wege sind unabhängig vorhanden. Helferstart verhindert doppelte Prozesse; kompatible lokale Laufzeit wird ohne Download gewählt. Statuslesen löst keine explizite sign_in-Aktion aus.

**Noch offen:** Nichterreichbarkeit/DNS/Offline von echten Authentifizierungs- und Speicherfehlern unterscheiden; Jobs sichtbar warten und ohne Credentialverlust oder Fenster bei Wiederverbindung fortsetzen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als durchgehende Zustands-/Integrationsarbeit; einen konkreten neuen Popup-/Datenverlustfehler erst nach Reproduktion behaupten.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Dies ist keine Behauptung, dass jeder Offline-Start Fehlerfenster öffnet oder Daten verliert.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L76](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L76): ReadAsync verwendet Status/EnsureStarted; kein eigener normalisierter Offlinezustand in dieser öffentlichen Projektion.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/background.js#L84](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/background.js#L84): Providerexceptions werden auf ok:false begrenzt; der gemeinsame Offline-/Authzustandsvertrag ist hier nicht vollständig.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L27708](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L27708): Die bestehende Syncoberfläche beschreibt Fehler weiterhin allgemein als immer anzuzeigen.

## [#275](https://github.com/maik3531/Magnolie-Organizer/issues/275) — Internetkonten: notwendige Anmeldung und Providerfehler einheitlich in Magnolie führen

**Bewertung:** Funktion oder Integration noch offen

Der frühere Warmstart-/Silentstartblocker ist korrigiert. Einheitliche erforderliche Anmeldung, Wiederanmeldung, Abbruch und Anbieterfehler sind ein größerer noch gültiger Rest.

**Bereits umgesetzt / belegt:** MOZ_APP_SILENT_START und fensterloser profilgebundener Start sind vorhanden. Die Diskussion belegt frischen und zweiten Start desselben isolierten Profils ohne sichtbare Komponentenfenster; gemeinsame Kontoaktionen nutzen vorhandene Provider.

**Noch offen:** Notwendige Anmeldung und Providerfehler einheitlich führen; vollständige Kontakt-/Kalenderbereitschaft statt bloß angelegter Teilkonten prüfen. Offlinegrenze #274 und echte Datenpipeline #292 getrennt halten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen mit präzisem Rest führen; Warmstartfehler nicht erneut als unbehoben zählen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L343](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedInternetAccounts.cs#L343): CreateStartInfo setzt frühen Mozilla-Silentstart und vorhandene stille Startargumente.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/background.js#L51](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/background.js#L51): Explizite Loginoperation vermittelt Google beziehungsweise TbSync/EAS; Status ist getrennt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/275#issuecomment-6499051270](https://github.com/maik3531/Magnolie-Organizer/issues/275#issuecomment-6499051270): Nativer Fail→Pass-Doppelstart korrigiert nur den konkreten Helferstart, nicht den gesamten persönlichen Cloud-Anmeldeablauf.
- [https://github.com/maik3531/Magnolie-Organizer/issues/275#issuecomment-6541946900](https://github.com/maik3531/Magnolie-Organizer/issues/275#issuecomment-6541946900): Angelegte Google-/Microsoftkonten waren kein Beleg für sämtliche gewünschten Datenquellen.

## [#276](https://github.com/maik3531/Magnolie-Organizer/issues/276) — Telefonkontakte: allgemeine Schreibfreigabe und automatischer bidirektionaler Providerabgleich

**Bewertung:** Funktion oder Integration noch offen

Die Diskussion unterschätzt den aktuellen Stand: allgemeine Schreibfreigabe und automatische Telefon-/E-Mail-Wertewrites samt Transport/UI sind inzwischen vorhanden. Vollständiger Kontakt-/Foto-/Mehrwegeabgleich bleibt darüber hinaus offen.

**Bereits umgesetzt / belegt:** v19 ist aktiviert; gemeinsame contacts_write_enabled-Freigabe übernimmt alte Gruppenschreibwahl. Native Prepare/Apply schützt eindeutigen RawContact, Version und tatsächlichen Readback. Beide Desktops und normaler Save-/Reconciliationpfad führen Telefon-/E-Mailabsichten mit SaveACK aus; Gruppen und deren Titel besitzen getrennte Pfade.

**Noch offen:** Weitere Kontaktfelder und Fotos, vollständige Provider-/Internetfallback- und Mehrwegeidentität sowie tatsächliche native Geräte-/Windowsabnahme des Gesamtumfangs erfüllen. Ressource 19 umfasst ausdrücklich nur Telefon-/E-Maillisten.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen lassen, implementierten Telefon-/E-Mail-/Freigabeteil ausdrücklich abhaken und nur verbleibende Felder, Mehrwegeintegration und aktuelle native Gesamtbelege verfolgen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-contact-values-v19.md#L1](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/phone-contact-values-v19.md#L1): Aktueller Vertrag beschreibt allgemeine Freigabe, automatische SaveACK-Kette und explizit ausgeschlossene Namen/Skalarfelder/Adressen/Fotos.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactValueWrite.kt#L9](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactValueWrite.kt#L9): RUNTIME_ENABLED=true; Felder telefone und emailEintraege.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactValueWriteAndroid.kt#L25](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/ContactValueWriteAndroid.kt#L25): Echter Providerprepare und atomarer wertListenUebernehmen-Readback.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L14890](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/web/anwendung.js#L14890): Automatischer Write wartet auf lokalen SaveACK, prüft Prepare, Apply und gespeicherten Readback.
- [https://github.com/maik3531/Magnolie-Organizer/issues/276#issuecomment-6515264816](https://github.com/maik3531/Magnolie-Organizer/issues/276#issuecomment-6515264816): Die historische Aussage ohne Transport-/GUI-Aufrufer wird durch die heutige Implementierung überholt.

## [#278](https://github.com/maik3531/Magnolie-Organizer/issues/278) — Windows: nativer Sync-Commit bestätigt gespeicherten erfolgreichen Providerabgleich nicht

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der konkret bestätigte Commitmarker-Quellfehler ist behoben; die eigenständige echte Abschlussquittung aus der neu installierten Windows-GUI bleibt offen.

**Bereits umgesetzt / belegt:** ContainsSavedResult normalisiert nur die fehlende eigene Fortschrittsmarke bei passender 64-Hex-Transaktion, Basis und dauerhaftem Handoff; Inhalt, Quellen und Epoch bleiben Pflicht. Eine positive und sieben negative Regressionsvarianten sind vorhanden.

**Noch offen:** Regulären neuen Produktabschluss auf einem Paket mit dem Fix bis native_commit_confirmed=true nachweisen; vorhandenen Journalbestand nicht zurücksetzen oder manuell entfernen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Als Abnahmerest führen, keine erneute Quellkorrektur. Erst nach der spezifischen realen Commitquittung schließen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSyncModels.cs#L735](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSyncModels.cs#L735): Eng begrenzte Normalisierung der eigenen ausstehendenTransaktion ist aktuell enthalten.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/tests/SyncCommitProjectionTests.cs#L10](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/tests/SyncCommitProjectionTests.cs#L10): Regression enthält den echten Markerunterschied und Schutznegative.
- [https://github.com/maik3531/Magnolie-Organizer/issues/278#issuecomment-6541809090](https://github.com/maik3531/Magnolie-Organizer/issues/278#issuecomment-6541809090): Originaler Kalenderfehler wurde geschlossen; ausdrücklich separat offen bleibt die neue native GUI-Commitbestätigung.

## [#290](https://github.com/maik3531/Magnolie-Organizer/issues/290) — EDS: Provider-Schreibbeleg und historischen Cache-Auslöser nachverfolgen – Rest #285

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Dies ist ausdrücklich kein bestätigter neuer EDS-Programmfehler, sondern zwei noch eigenständige Belegaufträge.

**Bereits umgesetzt / belegt:** Cachewiederherstellung und Prävention des gefährlichen Testmechanismus sind laut dokumentiertem Verlauf abgeschlossen; Produktquellen besitzen native Kontakt-Schreib- und Rücklesepfade.

**Noch offen:** Einen tatsächlich beauftragten Providerwrite mit nativer Rücklese-/Speicherquittung dokumentieren. Den historischen konkreten cacheverschiebenden Aufruf nur soweit vorhandene Belege reichen eingrenzen; eine Korrelation ist kein Ursachenbeweis.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als enges Nachweisissue halten; keine weitere Dublette öffnen, keine persönlichen Testkontakte oder Cache-/Kontenresets erzeugen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Private historische Originalbelege wurden in diesem Audit nicht neu erhoben; eine abschließende historische Verursacherzuordnung ist damit nicht möglich.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L20688](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L20688): Native EDS-Kontaktanlage/-Änderung/-Löschung sind vorhanden; Quellcode allein beweist keinen konkreten produktiven Schreibvorgang.
- [https://github.com/maik3531/Magnolie-Organizer/issues/290#issuecomment-6861501441](https://github.com/maik3531/Magnolie-Organizer/issues/290#issuecomment-6861501441): #267 wurde als echte inhaltliche Dublette geschlossen und hier konsolidiert; diese beiden Restbedingungen bleiben bewusst erhalten.

## [#292](https://github.com/maik3531/Magnolie-Organizer/issues/292) — Microsoft-Internetkonten: tatsächliche Kontakt-/Kalenderdatenpipeline abschließen – Rest #29

**Bewertung:** Funktion oder Integration noch offen

Die tatsächliche Microsoft-Kontakt-/Kalenderdatenpipeline ist gegenüber vorhandener Kontoeinrichtung weiterhin ein realer eigenständiger Integrationsrest.

**Bereits umgesetzt / belegt:** TbSync/EAS-Einrichtung, Konto-/Ordnerermittlung und sichere Auswahl sind vorhanden. Der Quellenexport für eigentliche DAV-Daten arbeitet jedoch mit CardDAV und CalDAV.

**Noch offen:** Die tatsächlich vorhandenen EAS-/Outlook-/Microsoft365-Daten über den verwalteten Anbieterweg lesen/schreiben und dauerhaft bestätigen, einschließlich genauer Ordnerbindung, Rechte und Offline-/Wiederverbindungsfällen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als Datenadapterintegration halten; keine neue OAuth-App oder fremde Tokens, keine Neuanlage von Konten für diesen Audit.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedEasSourceFolders.cs#L15](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ManagedEasSourceFolders.cs#L15): EAS-Ordnerquittungen sind ausdrücklich keine Provider-Datensync- oder Schreibquittungen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L114](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/app/thunderbird/api.js#L114): Live-Datenquellen werden aus CardDAV-Verzeichnissen und CalDAV-Kalendern gebildet.
- [https://github.com/maik3531/Magnolie-Organizer/issues/292](https://github.com/maik3531/Magnolie-Organizer/issues/292): #29 wurde nur für Einrichtung/Ermittlung geschlossen; eine sichtbare Konto-/Kalenderauswahl ist kein vollständiger Microsoft-Datennachweis.

## [#441](https://github.com/maik3531/Magnolie-Organizer/issues/441) — Linux/CalDAV: typisierten Jahrestagsabgleich vollständig anschließen – Rest aus #440

**Bewertung:** Funktion oder Integration noch offen

Der vollständige typisierte Linux-CalDAV-Jahrestagsabgleich fehlt weiterhin; der vorhandene ehrliche Schutzblock ist kein vollständiger Sync.

**Bereits umgesetzt / belegt:** Die Orchestrierung erkennt ausdrücklich X-MAGNOLIE-JAHRESTAG-TYP-markierte Jahrestage vor Kalenderwrites und bricht mit calendar_anniversaries_unsupported ab. Legacy-Kontaktgeburtstagsbereinigung bleibt gesondert.

**Noch offen:** Eigenen Scope mit Quellen/UID/ETag, Baselines, gemischten Ressourcen, Konflikten und Löschungen sowie dauerhaftem Commitnachweis integrieren; erst dann den Schutz ersetzen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als echte größere Syncintegration führen; vorhandenen #440-Schutz weder entfernen noch als ursprünglichen Bug erneut melden.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L30047](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer/bin/magnolie-organizer#L30047): pruefe_jahrestagsbereich blockiert den explizit markierten ununterstützten Scope vor jedem ausgewählten Kalenderwrite.
- [https://github.com/maik3531/Magnolie-Organizer/issues/441](https://github.com/maik3531/Magnolie-Organizer/issues/441): Abnahme enthält gemischte VEVENT/VTODO-Ressourcen, ETag-Konflikte, Wiederholung und dauerhaften Abschluss.

## [#454](https://github.com/maik3531/Magnolie-Organizer/issues/454) — Mac/Tablet: persistierte Sync-Epoche und Löschquarantäne bei Wiederherstellung ergänzen

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die ursprüngliche Behauptung fehlender Mac-/Tablet-Restoreintegration ist überholt. Persistierte Epochentransformation und Quarantäne sind in beiden tatsächlichen Hosts enthalten.

**Bereits umgesetzt / belegt:** Mac verwendet NativeBookRestore prepare/validate/commit/apply/finish. Tablet Vault.replace transformiert den authentifizierten Import gegen den aktuellen Vaultstand. Historische native Mac- und Android-Keystore-/Os-Teilproben sind dokumentiert.

**Noch offen:** Aktuelle Gesamtbasis mit tatsächlicher Dateiauswahl/SAF, Abbruch, Neustart/Crash und den fünf vorbereiteten nativen OS-Fehlerinjektionen prüfen; gespeicherte Epoche und Sperre alter Sitzungen nachweisen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als konkrete native Abnahmematrix; keine bereits integrierten Restorebausteine erneut implementieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L794](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L794): Tatsächlicher Restorehost ruft NativeBookRestore bis zur finalen UI-/Nativebestätigung auf.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/Vault.kt#L214](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/Vault.kt#L214): replace verwendet BookRestore.transform und eine frische UUID gegen den aktuellen Snapshot.
- [https://github.com/maik3531/Magnolie-Organizer/issues/454#issuecomment-6732747019](https://github.com/maik3531/Magnolie-Organizer/issues/454#issuecomment-6732747019): Native Keystore-/Os-Teilprobe bestätigt Epochendrehung und alte Sitzung; fünf weitere OS-Fehlerfälle zunächst nur vorbereitet.
- [https://github.com/maik3531/Magnolie-Organizer/issues/454](https://github.com/maik3531/Magnolie-Organizer/issues/454): Aktualisierter Body grenzt noch offene SAF-/Crash-/Fehlermatrix ausdrücklich ab.

## [#682](https://github.com/maik3531/Magnolie-Organizer/issues/682) — Kalenderanhänge: echte HTTPS-/Clipboard-Handler und native Portmatrix – Rest #651

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

HTTPS- und Clipboard-Handler sind als Quellpfade vorhanden; die reale OS-Handler-/Zwischenablage- und Portformularkette ist der weiterhin gültige Rest.

**Bereits umgesetzt / belegt:** Tablet validiert den bereits gespeicherten HTTPS-Anhang und ruft ACTION_VIEW mit klassifizierten Handlerfehlern auf. ClipboardManager ist angeschlossen. Mac hat HTTPS-/Credential-Policy und CommunicationLaunchBroker; Desktopformular-/Speicherteil ist historisch geprüft.

**Noch offen:** Bewussten echten HTTPS-Aufruf einschließlich fehlender Handler, tatsächliche Clipboardaktion sowie native Mac-/Tablet-Formular-/Save-/Reopenfälle unter den konkret erlaubten Testbedingungen abnehmen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als native Handler-/Portabnahme, keine falsche Aussage mehr über einen fehlenden Tablet-HTTPS-Quellanschluss.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Lange Patchdiskussion vollständig indiziert; relevante Handler-/Bridge-Abschnitte im Original und gegen heutige Dateien geprüft.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt#L110](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt#L110): Gespeicherte URI wird geprüft, ACTION_VIEW ausgeführt; Handlerannahme wird nicht als Netzwerk-/Downloadbeweis bezeichnet.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt#L582](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/MainActivity.kt#L582): ablage_kopieren verwendet den echten ClipboardManager.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CommunicationLaunchPolicy.swift#L182](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/BetaCore/CommunicationLaunchPolicy.swift#L182): HTTPS ohne URL-Zugangsdaten bleibt die enge native Policy.
- [https://github.com/maik3531/Magnolie-Organizer/issues/682](https://github.com/maik3531/Magnolie-Organizer/issues/682): Die vorliegenden Formulartests hielten externe Handler und Clipboard; diese konkrete OS-Grenze ist ausdrücklich nicht abgenommen.

## [#683](https://github.com/maik3531/Magnolie-Organizer/issues/683) — CalDAV: echter Testserver, Legacy-Baselines und Konfliktmatrix nach installierter Farbformularabnahme – Rest #652

**Bewertung:** Funktion oder Integration noch offen

Desktopformular und Codecs sind umgesetzt; echter DAV-Gesamtrundlauf und noch unvollständige DAV-Portkoordination bleiben getrennte aktuelle Reste.

**Bereits umgesetzt / belegt:** Desktop-Farb-/ICS-Felder und historische native Formular-/Speichernachweise sind dokumentiert. Mac besitzt Codecs und begrenzten Apple-Systemfeldsync; Tablet besitzt lokale Android-Providerkopien.

**Noch offen:** Zugelassenen DAV-Testserver mit Farbsetzen/-ändern/-leeren, If-Match/412, alten cleanHash-Baselines, parallelen Änderungen und dauerhaftem Journal-/Buchabschluss prüfen. Mac-/Tablet-DAV-Syncumfang weiterhin konkret anbinden; Apple-/Androidlokalkopien ersetzen ihn nicht.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen halten; Abnahmefälle und fehlende Portintegration getrennt ausweisen, nicht durch zusätzliche reine Codectests schließen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/tests/CalendarAccentSyncTests.cs#L61](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/tests/CalendarAccentSyncTests.cs#L61): Vorhandene Farb-Sync-Regressionen bilden Quellfälle ab, keinen neuen realen Serverlauf dieses Audits.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/SystemSourceBridge.kt#L25](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/SystemSourceBridge.kt#L25): Android-Quelle/Import wird ausdrücklich getrennt von implementierter Systemkontensynchronisation dargestellt.
- [https://github.com/maik3531/Magnolie-Organizer/issues/683#issuecomment-7186479357](https://github.com/maik3531/Magnolie-Organizer/issues/683#issuecomment-7186479357): Mac-Codec vorhanden; vollständige DAV-Koordination und tatsächlicher Serverabschluss bleiben offen.
- [https://github.com/maik3531/Magnolie-Organizer/issues/683](https://github.com/maik3531/Magnolie-Organizer/issues/683): Konkrete Server-/Legacy-/Konflikt-/Neustartmatrix ist eigenständig gegenüber abgeschlossenem Formular-/Codecumfang.

## [#689](https://github.com/maik3531/Magnolie-Organizer/issues/689) — Windows-Kontaktautomatik: korrigiertes Paket und echte Schlüssel-/Konto-/WLAN-/Monitorabnahme – Rest #681

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Der SaveACK-/Konfigurationswettlauf ist quellenmäßig behoben; echte Schlüssel-/Konten-/Monitor- und installierte End-to-End-Abnahme wurde dadurch nicht ersetzt.

**Bereits umgesetzt / belegt:** ContactSourceAutomation besitzt generationsgebundene SaveACK-/Setupgrenzen. Native gespeicherte Buchzeugen und DPAPI-basierter Consentstore sind vorhanden; dokumentierte Kandidatenproben nutzten bei mehreren externen Grenzen synthetische Adapter.

**Noch offen:** Auf dem korrigierten Paket tatsächliche Settings→Consent→SaveACK→Neustartkette, DPAPI/ACL/Accountbindung, Produktionsmonitor sowie genehmigte Provider-CAS/Readback-/Result-SaveACK-Kette inklusive Schutznegativen belegen.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als spezifischen installierten/native Abnahmerest führen; #688/#619 nicht als erneut unbehoben darstellen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceAutomation.cs#L16](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceAutomation.cs#L16): SaveAcknowledgement/Generation und Setup-/Widerrufsgrenzen bilden den korrigierten Quellpfad.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceApprovalStore.cs#L44](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceApprovalStore.cs#L44): Produktiver ConsentKeyProtector verwendet Windows ProtectedData.CurrentUser.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceApprovalSave.cs#L145](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/magnolie-organizer-windows/ContactSourceApprovalSave.cs#L145): ConfirmSave verlangt unabhängigen aktuellen nativen Speicherzeugen; Renderer-ACK genügt nicht.
- [https://github.com/maik3531/Magnolie-Organizer/issues/689](https://github.com/maik3531/Magnolie-Organizer/issues/689): Die ursprüngliche Abnahme dokumentiert explizit alte installierte DLL versus synthetischen korrigierten Kandidaten und benennt die verbleibende reale Matrix.

## [#785](https://github.com/maik3531/Magnolie-Organizer/issues/785) — Mac-Importparität: aktuelle OR6-/Dateiparser und vollständige native Importwege anbinden

**Bewertung:** Funktion oder Integration noch offen

Der ursprüngliche nur-ICS-Dispatcher ist überholt. Klassische Dateiformate und aktuelle OR6-Projektion sind verbunden; Gesamtarchiv und lokale Mac-Quellen fehlen weiterhin.

**Bereits umgesetzt / belegt:** Native import-Route ruft FileImportHost auf, mit privatem inventarisiertem Pythonhelper, Pickerbytes, gemeinsamer Vorschau/Merge und Speicherquittung. Aktuelle OR6-/vCard-/LDIF-/klassische ZIP-Pfade sind dokumentiert.

**Noch offen:** Vollständiges .magnolie-Archiv mit Kennwort/Integrität/Recovery/Restore und echte Mac-Programmerkennung integrieren. Privaten Interpreter und Picker-/Save-/Reopenfluss auf beiden Mac-Architekturen abnehmen; offene OR6-Detailgrenzen bleiben.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen mit aktualisiertem Resttitel; vorhandenen klassischen Importpatch nicht erneut anwenden oder nachbauen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L288](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L288): importFile verwendet den begrenzten FileImportHost und tatsächliche Prepare/Commit-UI-Schnittstellen.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L941](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/main.swift#L941): Der import-Dispatcher ruft importFile statt eines reinen ICS-Sonderwegs auf.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/IMPORT-CODECS.md#L255](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/IMPORT-CODECS.md#L255): Präzise offene Folgearbeiten: Vollarchiv und lokale Evolution-/Thunderbird-Erkennung.
- [https://github.com/maik3531/Magnolie-Organizer/issues/785#issuecomment-7186492012](https://github.com/maik3531/Magnolie-Organizer/issues/785#issuecomment-7186492012): Klassische Parser-/UI-Teilnachweise und offene native Laufzeit-/Archivgrenzen sind ausdrücklich getrennt.

## [#786](https://github.com/maik3531/Magnolie-Organizer/issues/786) — macOS-Systemkonten: echten Apple-Kalender-, Kontakt- und Erinnerungsabgleich anbinden

**Bewertung:** Funktion oder Integration noch offen

Die ursprüngliche Aussage ohne echten Apple-Koordinator ist überholt. Ein gebundener manueller Feldabgleich ist vorhanden, vollständige Systemkontenparität weiterhin nicht.

**Bereits umgesetzt / belegt:** EventKit-/Contacts-Provider, Dreiwegevergleich, persistierte Freigabe, verschlüsseltes Ledger und unabhängig zurückgelesener Buchabschluss sind im Host angeschlossen. Bestehende ausgewählte Datensätze können im definierten Feldumfang in beide Richtungen abgeglichen werden.

**Noch offen:** Create/Delete, beliebige neue lokale Einträge, Serien/Alarme/weitere Felder, Automatik, geführte Recovery ungeklärter Writes und Quellenverlust-Freigabenverwaltung sowie Apple-Notes-Rückabgleich. Neue native Swift-/Provider-/Restartprüfung auf dem Gesamtstand fehlt.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als konkret abgegrenzte weitere Integration plus native Abnahme; passive Kopien und vorhandenen Feldsync nicht vermischen.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Lokaler Apple-Readback beweist keinen iCloud-/iPhone-Serverrundlauf und keinen atomaren Provider-CAS.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/SystemAccountSyncHost.swift#L45](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/SystemAccountSyncHost.swift#L45): begin verbindet tatsächlichen Diskstand, UI-Admission, Quellenfreigabe, Providerplan und Ledger.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/SystemAccounts.swift#L323](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-macOS-Beta/Sources/MacBeta/SystemAccounts.swift#L323): Aktueller Normalstatus meldet systemAccountSyncImplemented:true; false im Host ist der Fehlerfallback.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/macos-786-native-system-sync.md#L18](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/contracts/macos-786-native-system-sync.md#L18): Konkrete Feldmatrix und verbleibende Create/Delete-/Automatik-/API-Grenzen sind dokumentiert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/786#issuecomment-7186492778](https://github.com/maik3531/Magnolie-Organizer/issues/786#issuecomment-7186492778): Teilabgleich wurde bereitgestellt; native neue Gesamtausführung und weitergehende Funktionen bleiben offen.

## [#791](https://github.com/maik3531/Magnolie-Organizer/issues/791) — Android-Tablet: Kontakte und Termine direkt aus Android übernehmen

**Bewertung:** Konkrete Abnahme oder Livebeleg offen

Die direkte Android-Kontakt-/Terminübernahme ist implementiert und teilweise gegen echte Provider geprüft. Die alte Metadaten-only-Beschreibung trifft nicht mehr zu.

**Bereits umgesetzt / belegt:** AndroidSystemRecords liest explizit gewählte Quellen, Kontaktfelder und Kalenderinstanzen; Schema 2 bindet stabile Herkunft. UI-Merge bewahrt vorhandene Kopien und meldet Erfolg erst nach SaveACK. Der aktualisierte Body dokumentiert erfolgreiche API34-Providergruppen mit fehlenden Schreibrechten.

**Noch offen:** Unsynchronisierte lokale Serienausnahme, zweite Kontaktquelle, Berechtigungsdialog/Live-Widerruf, laufende Query-Cancellation sowie echte Activity-/SaveACK-/Reopen-/IME-/TalkBackkette. Der Auftrag ist lokale Kopie, kein still hinzugefügter bidirektionaler Sync.

**Vorgesehene beziehungsweise ausgeführte Weiterführung:** Offen als eng benannte native Bedien-/Provider-Restmatrix; bereits vorhandenen Import nicht nochmals implementieren.

**Prüfgrenzen:** Aktuelle Quellen und vollständiger Diskussionsbestand geprüft; keine neue native Geräte-, Konto- oder installierte Produktabnahme durchgeführt. Alle neun Patchkommentare vollständig indiziert; relevante ursprüngliche Reader-/Bridge-/UI-/Providerstufenabschnitte mit heutigen Quellen abgeglichen. Historische CI-Ergebnisse wurden nicht als heutiger neuer Lauf ausgegeben.

**Belege:**

- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/AndroidSystemRecords.kt#L16](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/AndroidSystemRecords.kt#L16): Tatsächlicher ContentResolver-Reader für explizite schreibfreie Kontakt- und Kalenderimporte; keine Provider-Mutation.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/web/system-import.js#L1](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/Magnolie-Organizer-Android-Tablet-Beta/web/system-import.js#L1): Aktuelle UI-Import-/Herkunftspolitik statt bloßer Quellenanzeige.
- [https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1514](https://github.com/maik3531/Magnolie-Organizer/blob/3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f/ARBEITSSTAND.md#L1514): CI101-Teilnachweise und nachfolgend explizite offene UI-/Berechtigungs-/lokale Ausnahmefälle sind dokumentiert.
- [https://github.com/maik3531/Magnolie-Organizer/issues/791](https://github.com/maik3531/Magnolie-Organizer/issues/791): Aktualisierter CI101-Abschnitt dokumentiert begrenzten Erfolg und konkret verbleibende Abnahmegrenzen.

