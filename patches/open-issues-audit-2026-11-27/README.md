# Magnolie: vollständige Issue-Sichtung und geprüfte Patchserie

**Prüfdatum: 27. November 2026.** Die vollständige Sichtung bezieht sich auf die 106 beim ersten Abruf offenen Issues. Quellenbasis dafür war `3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f`; die hier empfohlene Patchserie baut auf dem begrenzt nachgeprüften, endgültig eingefrorenen Stand `7a490dd87e94eec08d7f09cb95a04b34bf4621c2` auf.

Die Lieferung enthält die vollständige Bewertung, ausgeführte Bereinigung, überprüfbare Patchdateien und konkrete Prüfgrenzen. Eine bereitgestellte Korrektur ist noch keine Übernahme in ein installiertes Produkt. [Quellenstände und Nachprüfungen](source-followups.json) sowie [die frühere gesicherte Übergabe](CHECKPOINT.md) bleiben nachvollziehbar.

## Ergebnis der vollständigen Sichtung

Jedes der ursprünglichen 106 Issues wurde einzeln bewertet: Beschreibung und Diskussionsverlauf wurden abgerufen, relevante Entscheidungen mit dem tatsächlichen Quellstand verglichen und geeignete Sonderfälle ausgeführt. Der [Diskussionsindex](discussion-index.json) enthält 743 ursprüngliche Kommentare sowie zwei nachgeprüfte Ergänzungen. Das bedeutet keine erneute Ausführung jedes historischen, in Kommentaren abgelegten Patchs oder jedes nativen Abnahmeschritts.

Die [vollständige Issue-Matrix](ISSUE-MATRIX.md) enthält für jedes Issue Befund, Restumfang und ausgeführte Aktion. Die [Einzelbewertungen](assessments.json) ergänzen die Quellen und Prüfgrenzen.

| Bewertung des ursprünglichen Umfangs | Issues | Bedeutung |
| --- | ---: | --- |
| Funktion oder Integration noch offen | 47 | Tatsächlicher Restauftrag bleibt erhalten. |
| Abnahme oder Livebeleg offen | 37 | Implementierung beziehungsweise Quellbeleg reicht noch nicht für die verlangte reale Abnahme. |
| Konkreter Quellen- oder Testfehler mit vorbereitetem Patch | 4 | #566, #759, #790 und der zusätzlich konkretisierte Teil von #395. |
| Fehlerbericht noch nicht bestätigt | 9 | Fehlende Reproduktion ist kein Grund, den Bericht für erledigt zu erklären. |
| Leitauftrag oder verbindliche Vorgabe | 4 | Bewusst weitergeführte Anforderungen und Abnahmegrenzen. |
| Ursprünglicher Umfang erledigt oder entfallen | 5 | #254, #809, #389, #731 und #823; übertragene Restabnahmen bleiben erhalten. |

Die bei den zusätzlichen Leistungs-, Import- und Nextcloud-Prüfungen neu gefundenen Fehler #843, #844 und #845 gehören nicht rückwirkend zu diesen 106. Sie stehen gesondert unter [new-issues](new-issues). #843 wurde während der Prüfung upstream behoben und unabhängig nachgeprüft. Bei #844 und #845 wurden die ersten upstream übernommenen Korrekturen erhalten; nur die eng nachgewiesenen Reste werden mit eigenen Nachträgen behandelt.

Nach diesem ursprünglichen Bestand kam #846 hinzu. Der dort gemeldete unveränderte MCP-Importtest wurde für beide Desktop-Webquellen gezielt verglichen: auf `7a490dd8` jeweils der gemeldete Fehler, auf dem finalen Ergebnisstand jeweils bestanden. Dafür ist keine weitere Produktkorrektur nötig. Der später gemeldete Commit `f8ad956e` behandelt ebenfalls diesen Alias-Teil; er ersetzt die übrigen Farbkorrekturen nicht. Der [gesonderte Nachtrag](new-issues/846-followup.json) trennt diese spätere Übernahme und den hier ausgeführten Node-Test von der weiterhin gesonderten Bun-/Windows-Archivabnahme. Die anwendungsgeprüfte Patchbasis bleibt `7a490dd8`; bei der Übernahme auf einen neueren Hauptzweig müssen spätere Änderungen berücksichtigt werden.

## Bereinigung der offenen Issues

**31 Schließungen wurden nach dem Schreiben einzeln auf GitHub zurückgelesen:** 29 zusammengeführte oder übertragene Issues, #389 wegen zurückgenommener Anforderung und #731 wegen des bereits erledigten begrenzten Diagnose-/Testlieferumfangs. #823 wurde während der Sichtung zusätzlich durch eine tatsächliche Übernahme nach `main` geschlossen.

Vor dem Schließen wurden die jeweils einzigartigen offenen Kriterien in das Leitissue übernommen. Daher bedeutet „zusammengeführt“ keine behauptete Fertigstellung der zugrunde liegenden Funktion. [Zuordnung und Nachweise](CONSOLIDATION.md) dokumentieren alle 13 Gruppen und die einzelnen Rücklesebestätigungen.

Bei #113 wurde der Umfang ausdrücklich auf den nächsten Gesamtkandidaten mit **privater Testlieferung an den Nutzer** präzisiert. Öffentliche Pakete benötigen weiterhin dessen ausdrückliche Freigabe. Die speziellen Desktop-, Android-, Flathub- und Geräteanforderungen wurden bei der Zusammenführung erhalten.

## Bedienung: gemeinsam einmal einstellen

Die Vorgabe bleibt: Eine gemeinsame Einstellung wird einmal im Organizer geändert und automatisch mit Notes abgeglichen. Ein technisches Übernahme-ACK ist eine Nachricht zwischen den Programmen; daraus wird keine weitere Bestätigung durch den Menschen.

Die beiden Teilpatches zu #759, weitergeführt in #330, beheben zwei konkrete Oberflächenfehler:

1. Fehlen gemeinsame Medieneinstellungen vollständig, werden nicht länger alte, scheinbar bedienbare Optionen angeboten. Die Oberfläche zeigt einen lokalisierten Wartezustand. Sobald der gemeinsame Zustand vorliegt, wird er automatisch angezeigt; während einer ausstehenden technischen Übernahme können vorhandene Einstellungen weiterhin geändert werden.
2. Beim ersten Aufbau der Oberfläche wurden Wiederherstellungsanfragen und Aktualisierungsbesitzer zu früh entfernt, weil die gerade erzeugten Elemente noch nicht im Dokument standen. Die Bereinigung wartet nun den gemeinsamen Einhängezeitpunkt ab. Mehrere Telefone behalten ihre laufenden Aktualisierungen; entsorgte Ansichten geben Anfragen und Timer wieder frei.

Die direkten Vorher-/Nachherfälle und der unabhängige Lebenszyklusreview sind unter [desktop/evidence/759](desktop/evidence/759/README.md) und [media/review-759-lifecycle-signoff.json](media/review-759-lifecycle-signoff.json) abgelegt. Die 128 Wiederholungen des Zwei-Telefon-Aufbaus sind ein gezielter Testfall und kein 128-facher Monatsnachweis.

Der begrenzte Folgeabgleich berücksichtigt bereits die inzwischen vorhandene erste manuelle Linux-Foto- und Videoübernahme, die getrennte Videozustimmung, die Prüfung gemischter Medienauswahlen sowie die stabilisierte technische Bestätigung bei gleichwertigen WLAN-Revisionen. Der letzte Nachtrag `bc9b4db5` ergänzt außerdem die private Linux-WLAN-Empfangseinrichtung. Diese upstream ergänzten Teilpfade werden nicht als fehlend behauptet. Falls die Android-Leseberechtigung noch fehlt, bleibt diese lokale Einrichtung ausstehend und kann einen erneuten Abschluss verlangen; daraus wird kein automatischer Ein-Klick-Gesamtabschluss behauptet. Es handelt sich nicht um eine zweite Bestätigung derselben gemeinsamen Einstellung in Notes.

Die vollständige produktive Organizer–Notes-Medienkette bleibt dennoch in #330 offen: Standard-Fähigkeitsmeldungen, echte Gerätepaare und die vollständige native Abnahme sind damit noch nicht belegt. Details: [früherer Mediennachtrag](desktop/media-latest-delta.json), [letzter Einrichtungsnachtrag](media/upstream-bc9b4db5-review.json), [abschließender Quellenabgleich](source-followups.json) und [aktuelle Medienmatrix](media/formats-mirror-webcam-audit.md).

## Dauerbetrieb und große Datenbestände

Zwei konkrete Ursachen unnötiger Ressourcenbelegung wurden eingegrenzt. Eine Korrektur ist als Teilpatch vorbereitet, die andere wurde inzwischen upstream übernommen:

- **#395 – Namensvorschläge im Terminfenster:** Vorher wurden im synthetischen Bestand bei jedem Öffnen 2.002 unsichtbare Namensoptionen aufgebaut, obwohl die Zusatzfelder geschlossen waren. Danach entstehen vor Benutzung keine solchen Optionen. Bei Benutzung werden höchstens 250 passende Optionen gleichzeitig angezeigt; der vollständige aktuelle Kontaktbestand bleibt durchsuchbar. Ein exakter später Kurzname, freie Namen, Firmenkontakte und gleiche Namen mit mehreren E-Mail-Adressen sind abgesichert. Es wurde kein dauerhafter Kontaktcache ergänzt. [Vorher/Nachher und Grenzen](performance/395-suggestions/README.md).
- **#843 – freigegebene Quellen des Wiederholungs-Workers, inzwischen upstream behoben:** Fehlgeschlagene Worker-Erzeugung, Laufzeitfehler und verworfene Provideridentität gaben vorher zugehörige Blob-URLs beziehungsweise Entlade-Listener erst beim Schließen der Oberfläche frei. Nach 32 kontrollierten Fehlstarts blieben 32 URLs mit 15.647.552 registrierten Blob-Bytes zurück. Die tatsächlich übernommene Korrektur `66b50c44` wurde unabhängig auf Eigentum der Ressourcen, späte Rückrufe, Ersatzworker sowie `blob:`-/`data:`-Wege und die echten Portprojektoren geprüft. Der Erfolgsfall hält genau eine Quelle bis zu deren tatsächlichem Lebensende. Blob-Bytes sind keine gemessenen nativen Heap-Bytes. Der frühere Alternativpatch ist nur noch historischer Beleg und wird nicht erneut zur Anwendung empfohlen. [Befund und Übernahmenachweis](performance/843/README.md).

Die vorhandene Volumensuite wurde mit unveränderten Produkt- und Prüfroutinen ausgeführt:

| Synthetischer Bestand | Ergebnis der bestehenden Suite | Einordnung |
| --- | --- | --- |
| Je 10.000 Termine, Kontakte, Aufgaben, Notizen und Jahrestage: 50.000 insgesamt | Bestanden; Gesamtlauf rund 15,6 s | Prüflauf im Node/JSDOM-Host, keine native Reaktionsgarantie. |
| Je 50.000 in denselben fünf Bereichen: 250.000 insgesamt | Datenmengen-/Vollständigkeits-/Dublettenprüfungen bestanden; zwei bestehende Zeitgrenzen überschritten | Import plus Zeichnen 22,10 s bei 20-s-Grenze; fünf Öffnen-/Schließen-Vorgänge 4,588 s bei 4-s-Grenze. |
| 50.000 Termine plus 50.000 Kontakte, erfolglose Suche mit Ziffern | Korrekte Trefferzahl, ungefähr 2,29–2,44 s | Der Zahlen-/Datumsformatierungsweg ist ein weiter zu untersuchender Aufwand. Vergleich ohne Ziffern ungefähr 0,09–0,18 s. |

Diese Messungen liefen vor der #395-Korrektur und der #843-Übernahme. Der Gesamtbestand von 250.000 Einträgen wurde danach nicht erneut vollständig gemessen; die konkrete Reduktion unnötiger DOM-Arbeit und die Ressourcenfreigabe wurden direkt geprüft. Eine pauschale Beschleunigungsquote wird deshalb nicht abgeleitet.

Die maximalen Host-RSS-Werte von rund 781,6 MiB beziehungsweise 2.499,9 MiB enthalten Node, JSDOM, Prüfhilfen und synthetische Testdaten. Sie sind weder der native Speicherbedarf des Organizers noch ein Nachweis eines Speicherlecks. Die ursprüngliche N100-Ursache bleibt unbestätigt.

**Noch erforderlich:** echte 30-Tage-Läufe mit Tray, Suspend/Resume, wiederholtem Verbinden, verschiedenen Ansichten und großen realistischen Büchern auf benannter Hardware; Prüfung auf anhaltenden Speicheranstieg; native Bedienmessungen; weitere Eingrenzung von Import/Zeichnen und numerischer Suche. Diese Anforderungen sind in #395 und als Abnahmeverweis in #113 verankert. [Gesamter Performancebericht](performance/README.md).

## Import und Export

Die zusätzlichen Prüfungen beziehen sich auf die tatsächlich vorhandenen Python- und C#-Codecs, das Speichern/Wiederöffnen in den getesteten UI-Wegen sowie gezielte Sonderfälle. Erfasst wurden unter anderem CSV, VCF, ICS, LDIF, Lotus-/Claws-/Thunderbird-Varianten, OR6, Gesamtarchive und Notizanhänge. [Detaillierte Abdeckung und Grenzen](IMPORT-EXPORT.md).

Ein jährlich wiederkehrender Termin ist nicht automatisch ein Geburtstag. Die geprüften eindeutigen Geburtstagskennzeichnungen bleiben Jahrestage vom Typ Geburtstag; auch ein Jahr-unbekannt-Datum `--02-29` wird nicht in einen gewöhnlichen Ganztagstermin umgedeutet. Ein gewöhnlicher jährlicher Termin bleibt dagegen ein Termin. Komplexe Serien und Ausnahmen werden nicht still zu einer einfachen Serie reduziert. Nicht verstandene OR6-Bedeutungen werden nicht erfunden.

#566 enthält einen bestätigten CSV-Verlust: weitere Kontaktfelder beziehungsweise HOME-/WORK-Zuordnungen wurden beim Import nicht vollständig erhalten. Der Patch bewahrt diese Daten in beiden Desktop-Codecs. Der historische private Originalbuch-/UI-Bericht wird dadurch nicht pauschal als erledigt erklärt.

Bei den zusätzlichen Kalenderfällen wurde #844 neu festgestellt: gültige fremde `COLOR`-Angaben wurden nicht in die sichtbare Akzentfarbe übernommen; auf Kalenderebene konnten Farbhinweise vollständig verloren gehen. Der erste upstream übernommene Fix ist bereits in der Patchbasis enthalten. Der unabhängig geprüfte Nachtrag ergänzt die fehlende Geburtstags-/Jahrestagsfarbe bis zur sichtbaren Darstellung und zum Export, erhält unveränderte parameterisierte Fremdfarben und behebt einen tatsächlichen Altimport- sowie einen Fehler im ungültigen ICS-Pfad. Es entsteht kein weiterer Farbdialog und keine zusätzliche Bestätigung. [Nachtrag mit echten Speicher-/Wiederöffnenketten](import-export/after-7a490dd8-844/README.md).

## Nextcloud, CalDAV und CardDAV

Die wesentlichen Desktopbausteine sind vorhanden: Kontoeinrichtung und Erkennung der Quellen, Termine und Aufgaben, Kontaktadressbücher, Versionsprüfungen beim Schreiben und Löschen sowie Konfliktschutz. Die zusätzliche Prüfung fand jedoch konkrete verbleibende Unterschiede:

- **#845:** Ausdrücklich als Nextcloud-Geburtstag gekennzeichnete ICS-Einträge wurden in beiden Codecs als gewöhnliche Termine behandelt. Diese erste Korrektur wurde inzwischen in `7a490dd8` übernommen und bleibt erhalten. Drei echte Reste wurden danach bestätigt: Der Linux-DAV-Aufrufer darf den nun korrekt erkannten Geburtstag nicht still auslassen; bei einer bewussten Typänderung mit unverändertem Schalttagsdatum darf die Regel für den letzten Februartag nicht in eine andere Jahresregel kippen; auch ein bereits exportierter Geburtstag mit zusätzlicher eigener Typkennung muss nach Ergänzung einer getrennten Serienausnahme vollständig im Serienmodell bleiben. Die beiden aktuellen Teilpatches behandeln diese Reste und ersetzen die bereits übernommene Erkennung nicht.
- **#441:** Der vollständige typisierte Jahrestagsabgleich über CalDAV fehlt unter Linux weiterhin. Vorhandene Schutzprüfungen verhindern unvollständige Schreibvorgänge. Eine Korrektur des Dateiimports ersetzt diese Integration nicht.
- **#683:** Geteilte und schreibgeschützte Kalender, echte parallele Änderungen, Konfliktantworten, Neustart und dauerhafter Abschluss benötigen weiterhin die konkrete Server- und Portabnahme.

Für große Bestände ist außerdem relevant, dass beide Desktopwege derzeit vollständige DAV-Berichte lesen. Eine vollständige inkrementelle Abgleichkette über Änderungsmarken ist damit nicht belegt. Es gelten begrenzte Antwortgrößen; aus den vorhandenen Tests folgt keine flüssige Abnahme von 50.000 Serverobjekten.

Ein zwingend fehlendes zusätzliches Nextcloud-Dateiformat ist nicht belegt: ICS und vCard sind vorhanden. Vorrang haben korrekte Datenbedeutung und vollständige Abläufe in diesen bestehenden Wegen. Weitere proprietäre Formate benötigen einen konkreten gewünschten Quellprogramm-Workflow. [Ausführlicher DAV-Bericht mit Quell- und Testbelegen](providers/nextcloud-caldav-README.md).

## Fotos, Videos, Telefonspiegelung und Webcam

**Nicht alle Formate sind in jeder Richtung freigegeben.** Originalempfang, unveränderte Sicherung, Vorschau und Versand zurück zum Telefon sind getrennte Fähigkeiten. Die [vollständige Formatmatrix](media/formats-mirror-webcam-audit.md) unterscheidet zwölf Formatgruppen und bindet sie an 36 aktuelle Quellstellen.

| Bereich | Tatsächlicher Stand | Wichtigste Grenze |
| --- | --- | --- |
| Desktop-Sender | JPEG, PNG, GIF, statisches WebP, eine begrenzte BMP-Variante, definierte MP4-/QuickTime-Container | Kein Versprechen beliebiger Bildvarianten oder Video-/Audiocodecs. |
| HEIC/HEIF/TIFF/WebM/MKV/AVI | Bytegleicher Linux-Originalempfang, Backup und Offline-Wiederherstellung mit echten Formatfixtures geprüft | Daraus folgt keine Freigabe des Desktop-Senders oder jeder Vorschau. |
| AVIF/RAW/DNG/3GP | Kein positiver formatspezifischer vollständiger Übertragungsnachweis in diesem Audit | Diese Formate werden nicht als durchgehend unterstützt ausgegeben. |
| Dateigrößen | 50 MiB je Datei; 128 Dateien und 400 MiB je Manifest | Längere Handyvideos können schon an der Dateigrenze scheitern. Eine Manifestgrenze ist keine Höchstzahl der ganzen Galerie. |
| Telefonbild auf dem Desktop | Eigener Bildkanal und vorhandene Viewer | Keine Maus-/Tastatursteuerung, kein Ton und keine Zwischenablage; vollständige Produktintegration und Geräteabnahme offen. |
| Telefon als Webcam | Tatsächliche Kamera-/Ton- und Betriebssystembausteine; Vertrag mit 640×480 bei 15 fps und Mono-Audio | Windows-Freigabe weiterhin geschlossen; Kamera-/Mikrofonquelle in Zielprogrammen, Bild-/Tonsynchronität und längerer Betrieb nicht nativ abgenommen. |

**111 gezielte vorhandene Hosttests bestanden** zu Originalformaten, Metadaten, Spiegeltransport und Webcam-Schutz-/Ausgabepfaden. Es wurde dabei kein physisches Telefon und kein OBS-/Teams-/Zoom-Lauf verwendet. Die positiven Teilbelege sind deshalb keine Gesamtfreigabe „fehlerfrei“.

## Magnolienbaum und Notes über Internet

**Eine direkte entfernte Verbindung ist implementiert, auch für Magnolie Notes.** Bereits geteilte Notizen werden beim Speichern automatisch zur Fortschreibung eingereiht; die Postfachverarbeitung startet anschließend. Die zusätzliche Fernaktion kann eine ausgewählte bereits freigegebene Notiz oder Aufgabe über einen eingerichteten entfernten Zugang senden. Das bestätigt die vorhandene Fähigkeit, keine pauschale Internetabnahme.

Der vollständige zweiseitige Abgleich braucht erreichbare Zustellwege in beiden Richtungen. Ein Telefon, das den Heimrechner erreicht, ist dadurch noch nicht selbst vom Heimrechner aus erreichbar. Die vorhandene Einrichtung verlangt Host und Port und setzt beispielsweise einen funktionierenden VPN-/Internetweg voraus; Magnolie richtet in diesem Ablauf keinen zentralen Vermittler ein. Gemessen an der Vorgabe für wenig technikversierte und ältere Menschen ist diese Einrichtung noch zu technisch.

Der regelmäßige vollständige Abgleich hat eine eigene, standardmäßig ausgeschaltete Option: „Automatisch im lokalen WLAN synchronisieren“. Mit eingeschaltetem Empfang, bestätigten und vertrauten Partnern und aktiver WLAN-Verbindung läuft er frühestens nach sechs Stunden. Das ist vom unmittelbaren Fortschreiben einer bearbeiteten Notiz zu unterscheiden. Mobilfunk löst diesen periodischen Vollabgleich nicht aus. Der ältere Desktop-WebDAV-Briefkasten ist kein allgemeiner Vermittler für die aktuelle FS1-Verbindung zu Notes.

Als optionale Weiterentwicklung ist eine einmalige geführte Einrichtung mit automatischer Prüfung beider Richtungen sinnvoll. Normale Änderungen sollen danach selbstständig laufen; technische Quittungen sollen keine zusätzlichen menschlichen Bestätigungen auslösen. [Vollständiger Internet-/Notes-Bericht und unabhängiger Quellenreview](internet-notes/README.md).

## Prüfstand und verbleibende Grenzen

Auf dem endgültigen Ergebnisstand `f3ea06e2` bestanden nach einem frischen C#-Rebuild **17 von 17 Prüfgruppen** und anschließend **48 von 48 tatsächlichen Import→Oberfläche→Speicherdatei→Wiederöffnen→Export/Reimport-Fällen**. Die unveränderten Python- und UI-Eingaben sind exakt an den unmittelbar vorherigen gemeinsamen grünen Stand gebunden: 155 CSV-/Wiederherstellungsfälle, 286 Import-/Export-Semantikfälle, 26 direkte Dateivertragsprüfungen und 15 JavaScript-Prüfprogramme. Diese Läufe werden mit ihrem tatsächlichen Quellenstand ausgewiesen; die alte C#-Assembly wird nicht weiterverwendet. Die Zahlen überlappen und werden nicht zu einer angeblich eindeutigen Gesamttestzahl addiert. Der [abschließende Integrationsnachweis](final-integration-summary.json) verknüpft die Manifeste und Prüfsummen.

Die Belege enthalten konkrete Quellenstände, Eingabe- und Logprüfsummen, tatsächliche Befehle und Umgebung. Vorherige fehlgeschlagene Läufe bleiben erhalten und werden von erfolgreichen Folgeläufen unterschieden. Zwei frühere Importprüfungen hatten einen falschen Quellen- beziehungsweise Arbeitsverzeichnispfad im Runner; dieselbe unveränderte Assembly bestand nach Korrektur dieses Aufrufs. Diese Fälle sind als Prüfhilfenfehler dokumentiert, nicht als reparierte Produktfehler.

Ein alter Planer-Paritätstest findet seine Zielfunktion mit seiner bisherigen regulären Expression bereits auf der unveränderten Basis nicht. Der gleiche Befund auf dem Patch ist kein neuer Rückfall; der Prüfhelfer wurde hier nicht nebenbei umgebaut. [Abgrenzung](performance/843/planner-parity-boundary.json).

Es wurden keine installierte Windows-/macOS-/Android-Abnahme, kein neuer signierter Paketbau, kein echter Monat im Tray und keine vollständige Prüfung privater Originaldaten behauptet. Der Notes-Robolectric-Lauf zu #731 war mangels vollständiger Android-Prüfumgebung hier nicht neu ausführbar. Die geschlossene Diagnose-/Testlieferaufgabe ersetzt daher keine native Medienabnahme.

## Optionale Bedienverbesserungen

[Die Vorschläge](OPTIONAL-UX.md) sind getrennt von den bestätigten Fehlerkorrekturen. Sie wurden weder umgesetzt noch als neue Issues angelegt. Maßstab ist weniger Suchen, weniger wiederholte Eingabe und verständliche sichtbare Bedienung. Der Nutzer entscheidet, welche Erweiterung aufgenommen wird.

## Lieferung und Anwendung

Die aktuelle Serie aus **neun Teilpatches** und der Gesamtpatch stehen unter [final-patches](final-patches). Das [Patchmanifest](final-patches/manifest.json) nennt Basis, Einzelcommits, sämtliche geänderten Dateien und Prüfsummen. Die Einzelserie und der Gesamtpatch wurden jeweils auf einem gesonderten Git-Index angewandt; beide erzeugen exakt denselben geprüften Ergebnisbaum.

| Teil | Zweck |
| --- | --- |
| #566 | Zusätzliche Kontaktfelder und Adressrollen beim CSV-Import bewahren. |
| #192 | Dokumentation des tatsächlich vorhandenen MCP-Aufrufumfangs korrigieren. |
| #790 | Veraltete Erwartung im Test der aktuellen Quellenkennung korrigieren. |
| #330, zwei Teile aus #759 | Gemeinsamen Medienzustand automatisch abwarten und Lebensdauer der ersten Wiederherstellungs-/Aktualisierungsansicht korrigieren. |
| #395 | Namensvorschläge erst bei Bedarf erzeugen und die gleichzeitig dargestellte Menge begrenzen. |
| #844 | Geprüfte Reste nach der ersten Farbübernahme beheben. |
| #845, zwei Teile | Nach der Übernahme verbleibende DAV-Auslassung verhindern, die Schalttagsregel bei Typänderung bewahren und exportierte Geburtstagsmaster mit ihren getrennten Ausnahmen zusammenhalten. |

#823 und #843 werden wegen tatsächlicher upstream Übernahme nicht nochmals als aktuelle Patches mitgeliefert. Die ursprünglichen #844-/#845-Übernahmen werden ebenfalls nicht verdoppelt. Ältere Alternativentwürfe und die vollständig geprüfte vorherige Serie auf `1f1f3225` sind als historische Belege getrennt abgelegt; zur aktuellen Anwendung ist ausschließlich `final-patches` vorgesehen.

Der [abschließende Integrationsnachweis](final-integration-summary.json), die [aktuelle Issue-Liste](final-open-issues.json) und [SHA256SUMS](SHA256SUMS) ergänzen die Lieferung. Die Patches werden zur Prüfung bereitgestellt; die Produktdateien auf `main` und öffentliche Pakete werden durch diese Artefaktlieferung nicht geändert.
