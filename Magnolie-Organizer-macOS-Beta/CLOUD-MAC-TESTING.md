# Mac-Prüfung aus „Magnolie-Organizer einrichten“

Stand: **26. November 2026**. Zugeordnet zu **#121, #783, #785, #786, #806 und #808**;
auch als Abnahmehilfe für die übrigen Mac-Issues dieser Übergabe.

**Aktueller Einstieg:** Der
[Stabilitätsbericht](STABILITY-VERIFICATION-2026-11-26.md) ordnet die spätere
Nachprüfung, die #806/#808-Korrekturen und den erweiterten nativen Workflow ein.
Der veröffentlichte Prüfkandidat ist
`3f3ec069895dec254c53660d14e6851cb23077cd`, Tree
`176fa7f362227c92ec4d7c4bf08d09b855951ae7`.
[Lauf #104 / 45827353062](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
lief am 26. November 2026 von **14:15:18 bis 14:49:42 Uhr Europe/Berlin**
(13:15:18–13:49:42 UTC) und endete insgesamt sowie für beide Mac-Architekturen
mit **`completed` / `success`**. Der
[dauerhafte Gesamtbeleg](verification/native-run-104.json) bindet diesen Erfolg
an `3f3ec069`; spätere Dokumentationsstände sind keine neuen nativen Prüfläufe.

| Nachweis je Architektur | Tatsächliches Ergebnis in #104 |
| --- | --- |
| Runtime / AirPlay / ImportHelper | 26 / 27 / 17 bestanden, keine Skips oder Fehler |
| Hostprüfungen | 34 bestanden, ein Linux-spezifischer Skip, keine Fehler |
| Swift Debug | Vier Kontexte mit jeweils denselben 501 Testnamen; 4/5/5/6 Skips, keine Fehler |
| Swift Release, eigener optimierter Kontext | 501 Fälle: 495 bestanden, sechs Skips, keine Fehler |
| Unveränderter Swift-Prozess → tatsächlich gebündelter Python-Helper | Neun Kriterien bestanden; 22 originale OR6-Felder in vier Kollektionen |
| Wirkliche App: frisches Profil, Speichern, normales Beenden, Wiederöffnen | Sieben Kriterien bestanden |
| Unabhängiger Paket-Byteaudit | 65 Prüfungen bestanden; 3921 gebundene Quelldateien, 555 Projektionsinputs und 1312 Ausgaben |

Die wiederholten Swift-Kontexte werden nicht als fünf unabhängige Testmengen
addiert. Das ausgelieferte Entwicklungspaket bleibt **Debug/ad hoc**. Die
Prozessprobe bedient keinen Picker oder Editor und speichert keine Importdaten;
der getrennte App-Smoke prüft das frische Startprofil. Vollständige UI-, TCC-,
Provider-, Monterey- und Produktionsfreigaben bleiben gesondert.

**Historischer nativer Abschluss:** Die unten beschriebene ursprüngliche
lokale Bestandsaufnahme und der
[native Fortsetzungsbericht bis #97](NATIVE-VERIFICATION-2026-11-26.md)
behalten ihren eigenen Quell- und Zeitbezug.
[Lauf #97](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
bestand auf `215d89029df02df2dce78f35412785ec9f9b36d8` die vollständige
definierte CI-Kette auf ARM64 und Intel einschließlich tatsächlichem
App-Start/Speichern/Beenden/Wiederöffnen. Die
[dauerhaften Belege](verification/native-run-97.json) ersetzen keine
vollständige UI-, Monterey-, TCC-, Konto- oder Geräteabnahme. Der übrige Plan
führt diese offenen Prüfungen konkret auf.

Die zusätzliche [gemeinsame Hostregression](verification/stability-2026-11-26/SHARED-REGRESSION-2026-11-26.md)
bleibt an `c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b` gebunden; ihr späterer
lesender Quellenvergleich gilt für `8c860a14f7e10904c1b3a159ae84619c2c24ba82`.
Diese Belege werden nicht nachträglich in Tests des neuen Prüfkandidaten
umbenannt. Die eigenen nativen Ergebnisse der geänderten Bauprüfer und
Extraktion liegen jetzt im getrennten #104-Gesamtbeleg vor.

## Entscheidung und nachgewiesene Ausgangslage

Die Patches sollen hier so weit wie möglich geprüft werden. Für die Ausführung
von Apple-Code ist eine **richtige macOS-VM** ein passendes Ziel; ein eigener
physischer Mac beim Nutzer ist keine Voraussetzung. Die konkrete erreichbare
Laufzeit entscheidet über den Beleg, nicht die Bezeichnung „Cloud“ oder
„Emulator“.

Die ursprüngliche Arbeitsumgebung „Magnolie-Organizer einrichten“ wurde lesend
inventarisiert. Ergebnis: Linux x86_64, Kernel 6.18.57, 4096-Byte-Seiten, keine
effektiven Linux-Capabilities, kein `/dev/kvm`, kein Swift/Xcode/xcrun und keine
gefundenen QEMU-, Docker- oder Tart-Programme. Der vollständige technische
Beleg steht in
[`contracts/macos-cloud-environment-2026-11-26.json`](../contracts/macos-cloud-environment-2026-11-26.json).
Es wurde keine VM installiert, kein Kernelmodul geladen und keine Berechtigung
geändert. Daraus folgt kein allgemeines Urteil gegen macOS unter Linux:
**Die Voraussetzungen der untersuchten Wege fehlen in genau diesem Host.**

Der wiederholbare Umgebungstest ist:

```sh
python3 Magnolie-Organizer-macOS-Beta/tools/check_cloud_environment.py \
  --name 'Magnolie-Organizer einrichten' --output /absolute/new/environment.json
```

In einer macOS-VM ergänzt `--require-native-build` ein überprüfbares Gate:
Darwin, funktionsfähige Swift-/SDK-Abfrage, Codesign und vorhandene benötigte
Frameworks. Exitcode 2 bedeutet fehlende Bauvoraussetzungen. Exitcode 0 ohne
diese Option bedeutet nur, dass die Inventur durchgeführt wurde. **Keiner der
beiden Fälle ist ein bestandener Magnolie-Test.** Bereits vorhandene
Nachweisdateien werden nicht überschrieben.

## Welche Wege sich wofür eignen

| Weg | Belegte Voraussetzungen | Sinnvoller Magnolie-Prüfumfang | Grenze für diese Übergabe |
| --- | --- | --- | --- |
| Vorhandene GitHub-macOS-Jobs | Erreichbares GitHub Actions, passender Runner, exakter Quellcommit | Swift-Bau, Core-Tests, WKWebView-Tests, signiertes Entwicklungsbundle, Start/Speichern/Neustart | Persönliche Apple-Konten oder bereits freigegebene TCC-Dialoge werden nicht vorausgesetzt. |
| Dauerhafte macOS-VM über Apple Virtualization, etwa Tart oder UTM | Passender Apple-Silicon-Mac-Host beim Anbieter; unterstützte Host-/Gastversion und Image | Bedienbare App, Berechtigungsdialoge, EventKit/Contacts, lokale Testquellen, Wiederaufnahme nach Neustart; bei geeigneter VM auch iCloud | VM-Identität, Kontoeinrichtung, GUI-Sitzung und Netz müssen tatsächlich verfügbar sein. |
| Intel-macOS-VM über QEMU/KVM | Geeigneter x86-Host, QEMU, nutzbare Hardwarevirtualisierung und macOS-Image | Getrennte Intel-Abnahme, gegebenenfalls Mindestversionsprüfung | Hier fehlen QEMU und `/dev/kvm`; ein Docker-Container allein stellt KVM nicht her. |
| xnulinux | ARM64/PAC, 4-KiB-Seiten, Systemzugriff, RAM-/Disk-/Toolchain-Voraussetzungen | Zusätzlicher experimenteller Apple-Userspace-Prüfweg nach erfolgreicher eigener Einrichtung | Hier verhindern Architektur und fehlende Modulrechte den direkten Start; veränderte Systemschutzmechanismen begrenzen bestimmte Aussagen. |
| Aktueller Linux-Quellhost | Python, Node/JSDOM und deklarierte Projektabhängigkeiten | Tatsächliche aktuelle Parser, vollständige projizierte UI, Fehlerpfade, synthetische Bridge-/Save-ACK-Transaktionen, SourceFreeze | Kein Nachweis für AppKit, Apple-Berechtigungen oder einen echten Apple-Kontenrundlauf. |

Die Tabelle verbindet Hersteller-/Projektangaben mit unserer Testplanung;
ein vorgeschlagener Prüfweg ist noch keine eingerichtete Umgebung.

### Bereits vorhandener CI-Weg

GitHub dokumentiert seine regulären gehosteten Runner als frische VMs und
bietet macOS für Intel und ARM an. Quellen:
[Runnerauswahl](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
und [Runnerreferenz](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Unser bestehender Workflow `.github/workflows/ports-2.0.30.yml` enthält bereits
`macos-15`/arm64 und `macos-15-intel`/x86_64. Er sammelt jetzt zusätzlich
den tatsächlichen Umgebungsbeleg pro Architektur. Die vorhandenen Runnernamen
bleiben für einen reproduzierbaren Vergleich erhalten; einen zusätzlichen
aktuellen Gast getrennt prüfen, statt unbemerkt die Referenz auszutauschen.

Es gibt historische erfolgreiche Läufe, etwa
[42562106430](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42562106430)
und [42547724299](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42547724299).
Diese liefen mit den jeweiligen Portständen und der Desktopbasis
`067c38934b539943d8e1720abafd8a80b401d797`. Sie beweisen **keinen** aktuellen
OR6-, Import- oder Systemkontenpatch. #783 beseitigt gerade die bisherige
Rücksetzung aktueller Desktopquellen auf diesen veröffentlichten Stand.

### Dauerhafte VM für die Kontenprüfung

Apple beschreibt macOS-Gäste über sein
[Virtualization-Framework](https://developer.apple.com/documentation/virtualization/virtualize-macos-on-a-mac).
[Tart](https://tart.run/quick-start/) ergänzt automatisierbare Images und
CI-Anschlüsse; sein dokumentierter Host benötigt Apple Silicon und macOS 13+.
[UTM](https://docs.getutm.app/guest-support/macos/) unterstützt macOS-Gäste ab
12 auf passenden Apple-Silicon-Hosts. Verfügbare Images, Gastversion und
Image-Digest vor dem Lauf festhalten. Ein `latest`-Tag allein ist kein
wiederholbarer Versionsbeleg. Ein ungeprüfter Klon mit gespeicherten
Zugangsdaten gehört nicht in öffentliche Artefakte.

Für GUI-Arbeit muss im Gast eine tatsächliche Benutzersitzung existieren.
Tart dokumentiert außerdem mögliche Keychain-Probleme bei unbeaufsichtigtem
Betrieb und SSH: [FAQ](https://tart.run/faq/). Der Test soll diese Voraussetzungen
erfassen und verständlich abbrechen. Globale Schutz- oder Netzfreigaben
abzuschalten ist kein Ersatz für einen passenden Testbenutzer und eine
funktionierende Sitzung.

**iCloud ist in geeigneten VMs tatsächlich möglich.** Apple verlangt für
seinen Apple-Silicon-Weg **Host und neu erzeugten Gast mit macOS 15+**;
das Upgrade eines älteren Gasts allein schafft diese Identität nicht.
Verschieben auf einen anderen Host oder gleichzeitige Klone können eine neue
Identität und erneute Anmeldung auslösen. Siehe
[Apples Entwicklerdokumentation](https://developer.apple.com/documentation/virtualization/using-icloud-with-macos-virtual-machines).
Deshalb eine frisch geeignete, dauerhaft gebundene Test-VM für #786 verwenden
und ihre Identität während der Wiederanlaufprüfung erhalten.

Apple nennt weiterhin nicht verfügbare VM-Dienste, darunter Apple Media
Services: [iCloud in VMs](https://support.apple.com/en-us/120468).
Eine fehlende Store-Anmeldung beweist daher keinen Magnolie- oder KDE-Fehler.
KDE bietet zusätzlich einen
[offiziellen stabilen macOS-Download](https://kdeconnect.kde.org/download.html).
Genau die verwendete Gegenstelle und Version dokumentieren. Die App-Store-
Ausgabe und der macOS-Desktopclient dürfen nicht allein anhand des Namens als
funktionsgleich gelten. Keine eigene Magnolie-Notes-App voraussetzen.

### QEMU/KVM und xnulinux nachvollziehbar einordnen

[OSX-KVM](https://github.com/kholia/OSX-KVM) beschreibt einen Linux-Weg mit
QEMU und Hardwarevirtualisierung. Die
[Docker-OSX-FAQ](https://github.com/sickcodes/Docker-OSX/blob/master/FAQ.md)
erläutert die zusätzliche Cloud-Grenze fehlender verschachtelter
Virtualisierung. Auf einem dafür bereitgestellten Host kann das untersucht
werden. Das Fehlen von `/dev/kvm` hier wird weder durch einen Containerstart
noch durch Umbenennen eines UI-Tests behoben. Ein QEMU-TCG-Softwarepfad ist
hier nicht eingerichtet oder als Magnolie-Testumgebung nachgewiesen.

Der Nutzerhinweis auf
[xnulinux bei Heise](https://www.heise.de/en/news/xnulinux-loads-the-macOS-kernel-into-Linux-as-a-module-11538272.html)
wurde anhand der Primärquellen geprüft; die Heise-Seite ließ sich im Abruf
nicht lesen. Prüfstand ist xnulinux-Commit
[`d9b9bcba651c2da505f535524e02e2d9d309835e`](https://github.com/AFK-surf/xnulinux/commit/d9b9bcba651c2da505f535524e02e2d9d309835e).
Die [Projektübersicht](https://github.com/AFK-surf/xnulinux) berichtet einen
laufenden macOS-Desktop und verlangt unter anderem ARM64/PAC, 4-KiB-Seiten,
mindestens 16 GB Host-RAM sowie passende System- und Bauartefakte.
[production.md](https://github.com/AFK-surf/xnulinux/blob/d9b9bcba651c2da505f535524e02e2d9d309835e/docs/production.md)
führt Änderungen an AMFI/SIP und dem Systemvolume auf. Daraus leiten wir ab:
Ein dort bestandener App-Test ersetzt nicht automatisch eine Signatur- oder
Berechtigungsprüfung unter unverändertem macOS. Vor einem Versuch erst den
Umgebungstest wiederholen und die offenen Voraussetzungen separat erfüllen.

## Konkreter Codex-Ablauf

### 1. Den zu prüfenden Quellstand festlegen

Den vollständigen gesicherten Prüfzweig samt Issue-Kommentaren lesen. In einem
eigenen Checkout arbeiten und den überprüften Commit notieren. Kein Mischen
von Main, alten v2.0.30-Desktopdateien, fremden `Generated`-Verzeichnissen und
neuen Portdateien. `candidate_sources.py record/verify` sowie SourceFreeze
gehören zum Lauf; die beiden Prüfungen erfassen unterschiedliche Grenzen.

Nach Review kann der bereits definierte Mac-Workflow aus GitHub Actions mit
`target=macos` auf dem Prüfzweig gestartet werden. Beispiel für eine dafür
autorisierte und angemeldete GitHub-CLI:

```sh
gh workflow run ports-2.0.30.yml \
  --repo maik3531/Magnolie-Organizer \
  --ref work/macos-issue-fixes-20261126 --field target=macos
```

Die ursprüngliche Vorbereitung konnte noch keinen Lauf starten: Der
GitHub-Connector bot keinen Workflow-Start und die lokale CLI keine Anmeldung.
Die Fortsetzung nutzte anschließend die bereits angemeldete GitHub-Oberfläche;
die historischen Läufe #91 bis #97 und ihre tatsächlichen Ergebnisse stehen
im nativen Bericht. Die ebenfalls erfolgreiche erweiterte Prüfung #104 steht
im Stabilitätsbericht. Bei jedem weiteren Start die tatsächliche Run-ID
und `head_sha` auslesen; parallele Tablet-Läufe machen eine vermutete nächste
Laufnummer unzuverlässig.
Nur ein grüner Lauf auf genau dem geprüften Commit zählt für dessen native
Abnahme. Die Prüfung ist keine Freigabe zur Veröffentlichung eines Pakets.

### 2. Bau und tatsächlichen Start in beiden Architekturen prüfen

Der Workflow bereitet die kanonischen Kataloge und Importabhängigkeiten vor,
bindet den aktuellen Quellstand, prüft die Projektions-/Hostverträge, baut die
private CPython-Laufzeit und führt Swift-Tests sowie den Bundlebau aus.
`IMPORT-RUNTIME.md` beschreibt die feste Quellenprüfsumme, Mach-O-Abhängigkeiten,
die durch #806 eindeutig an macOS gebundene Deploymentdeklaration,
Mindestversion und Relokationsprüfung. #808 erhält nach der validierten
Extraktion die Archivzeitstempel regulärer Dateien, damit Make die
mitgelieferten generierten Bauquellen korrekt einordnet. Ein fehlender
Importhelfer darf nicht zu einem scheinbar vollständigen ICS-only-Paket führen.

Der erweiterte Ablauf enthält außerdem drei gesondert auszuweisende Prüfungen:

1. Die tatsächliche Darwin-Mach-O-Plattformprobe und die vollständige
   AirPlay-Boundarysuite auf beiden Architekturen. Ein solcher Grenztest ist
   keine Abnahme des optionalen Receivers mit einer Gerätegegenstelle.
2. `tools/check_native_file_import_process.py` verbindet die unveränderte
   Produktionsdatei `FileImportProcess.swift` mit den tatsächlich gebauten
   BetaCore-Objekten und startet den privaten Interpreter des signierten
   App-Bundles mit der originalen OR6-Fixture. Dieser Prozessnachweis bedient
   keinen Dateiauswahldialog oder Editor und speichert kein Buch.
3. `swift test -c release --jobs 2` prüft optimierten Swift-Code in einem
   eigenen Kontext. Das tatsächlich paketierte Entwicklungsbundle bleibt
   Debug und ad-hoc signiert; Produktionssignatur und Notarisierung gehören
   nicht zu diesem Test.

Diese Gates sind in #104 auf beiden Architekturen erfolgreich abgeschlossen;
Phasen, Ergebnisse und Skips stehen im Gesamtbeleg. Die Objekt-/Modul-/Probe-
Hashes der Prozessprüfung sind originale native Nachweise: Diese Binärdateien
liegen nicht im Artefakt und wurden vom Linux-Byteaudit nicht erneut gehasht.
Dessen Prüfung der tatsächlich paketierten Dateien und Signaturbestandteile
ersetzt keine native Codesign- oder Vertrauensprüfung. Die Bedien-/Import-Save-/
Provider-Matrix unten bleibt getrennt.

`tools/smoke_app.swift` startet **das wirkliche App-Bundle**, beobachtet sein
Fenster und prüft Speichern, Beenden und erneutes Öffnen. Es verweigert ein
bereits vorhandenes Beta-Profil. In einer dauerhaften VM daher einen frischen
Testbenutzer oder einen sauberen VM-Prüfstand verwenden; keine vorhandenen
Profile löschen, um den Test zum Bestehen zu bringen. Dieser Smoke-Test
beweist noch keine Editor-, TCC-, Konten- oder Gerätefunktion.

### 3. Drei VM-Prüfstände unterscheiden

| Prüfstand | Zweck | Mindestnachweis |
| --- | --- | --- |
| Bestehende arm64- und Intel-CI-VM | Neue Quelle bauen, isolierte Tests und Bundle-Start | Beide Joblogs, Quellmanifest, tatsächliche Architektur, SDK/OS, Bundle-Prüfsumme und Smoke-Beleg |
| macOS 12.7 auf einem kompatiblen VM-Host | Bisherige Magnolie-Untergrenze einschließlich älterer Berechtigungs-API | Wirklicher Start und relevante Tests unter 12.7; ein Mach-O-Deploymentziel allein reicht nicht |
| Neu erzeugte geeignete macOS-15+-VM | Systemberechtigungen, Apple-Programme und ausdrücklich eingerichtete Testkonten | TCC-Zustände, Native-Readback, Änderungen in beide Richtungen, Neustart und Konfliktfälle |

Ein ARM-Lauf ersetzt keinen Intel-Lauf. Ein moderner Gast ersetzt keine
12.7-Prüfung. Für iCloud ist der geeignete neuere Gast maßgeblich; aus einer
VM-Einschränkung der älteren Testumgebung keinen künstlichen Produktfehler
oder eine Erhöhung der Mindestversion ableiten.

### 4. Funktionsmatrix tatsächlich abarbeiten

| Bereich / Issues | Konkrete Handlung | Erwartetes Ergebnis und Beleg |
| --- | --- | --- |
| Aktuelle Dateien / #783, #785 | Original-OR6-Fixtures und ICS/VCS/LCS, CSV, vCard, LDIF, Claws, ZIP sowie Mülltermine über den echten Picker öffnen | Importvorschau, bekannte Felder/Serien/Planer prüfen; nach Save-ACK beenden und wieder öffnen; gespeicherten Bestand vergleichen |
| Importfehler / #778, #781, #785 | Fehler vor Mutation, Rendererfehler nach Mutation, fehlendes/falsches Save-ACK, erneutes Speichern | Keine falsche Erfolgsmeldung; schon angehängte Daten bleiben sichtbar; erneuter Save erzeugt keine zweite Kopie |
| Kalender / #465, #770, #771 | Ganze Tage, floating, DST-Lücke/-Überlappung, wiederkehrende Ausnahmen, alter Android-Alias, Zeitraumgrenze | Identität und Originaldaten erhalten; keine Vollständigkeit außerhalb der tatsächlichen Abfrage behaupten |
| Kontakte / #775, #776 | Mehrere Nummern/Adressen, Fotos, kontaktbezogener Geburtstag, bekannter/gleichnamiger Kontakt | Gemeinsame Konfliktvorschau bedienen; lokale Originale und explizite Geburtstagsregel nach Neustart erhalten |
| Erinnerungen / #777, #779 | Offene/erledigte Einträge, unterstützte Daten, Wiederimport und JSON-Rundlauf | Neue lokale IDs, passive Herkunft, keine Duplikate; ausgeschlossenes Quellmerkmal bleibt ausdrücklich ausgeschlossen |
| Apple Notizen / #772, #774 | Lokale Textkopie, Kontoeingabeentwurf, Format-/Anhangsgrenze | Tatsächliche Automation-Freigabe; Originalnotiz unverändert, lokale Kopie dauerhaft; kein Rückabgleich aus einer Kopie ableiten |
| Echter Systemabgleich / #786 | Quelle bewusst binden; extern ändern; lokal ändern; gleichzeitig ändern; Recht entziehen; nach vorbereitetem Write/Save neu starten | Nur unterstützte Felder abgleichen; Konflikte/Ungewissheit erhalten; Quellbindung und dauerhaft rückgelesener Buchstand passen zusammen |
| Wiederherstellung / #454, #511 | Checkpoint und verschlüsseltes Buch wiederherstellen, native Epoche/Quarantäne, ungewöhnliche Unicode-Schlüssel | Vorhandene Schranken erhalten; nicht darstellbare Schlüsselpaare weiter klar ablehnen; keine neue Sync-Autorität aus Importdaten |
| Bedienung / #451, #452, #458, #464, #468 | Cmd-Tasten, Textauswahl, lange Listen, pointer/touch soweit verfügbar, skalierte Darstellung | Wirkliche WKWebView-/Gestenbelege mit OS-/Engineversion; DOM-Werte allein gelten nicht als Bedienabnahme |
| KDE Connect / #121, #784 | Offiziellen Client in einer passenden VM verwenden, Testdatei empfangen und in Magnolie importieren | Übertragene Byte-Prüfsumme plus gespeicherter Import; externe Übertragung und direkte Magnolie-Gerätefunktion getrennt ausweisen |
| AirPlay / #721 | Receiver tatsächlich bauen/starten; erreichbare Gegenstelle verbinden und wieder trennen | Bild, Start/Stop, Netz-/Fehlerverhalten prüfen. Ohne erreichbare Gegenstelle bleibt dieser Teil offen, auch bei grünem VM-Bau |

Die Issue-Verträge legen die Einzelassertionen und vorbereiteten Tests fest.
Diese Matrix ergänzt ihre native Durchführung. Durch #786 nicht implementierte
Neuanlagenexporte, Löschungen, Serienfelder und Automatik werden ausdrücklich
als Rest behandelt; ein Grundabgleich darf keine Vollparität vortäuschen.

### 5. Systemkonten und Gegenstellen gestuft prüfen

Zuerst synthetische Datensätze in ausdrücklich eingerichteten lokalen
Testkalendern, Testlisten und Testadressbüchern verwenden. Tatsächliche
EventKit-/Contacts-Freigaben in der VM erteilen beziehungsweise ablehnen und
den Zustand über die App neu lesen. Nur die eigens erzeugten Testobjekte
später anhand ihrer dokumentierten Kennungen bereinigen.

Danach, sofern eine geeignete VM und ein ausdrücklich bereitgestelltes
Testkonto vorhanden sind, den Serverrundlauf prüfen: Apple-Programm ändern,
Synchronisation abwarten, Magnolie abgleichen; anschließend umgekehrt.
Eine erfolgreiche EventKit-Schreibantwort allein beweist keine bereits
erfolgte Server-/iPhone-Synchronisation. Letzte Inhalte separat im
Apple-Programm und in Magnolies erneut geöffnetem Buch lesen.

Paralleländerungen vor dem Schreiben und nach dem ersten Provider-Readback
gezielt erzeugen. Die öffentlichen Apple-Schnittstellen bieten hier keinen
von uns nachgewiesenen atomaren Server-CAS. Unsichere Ergebnisse müssen als
solche im Journal bleiben. Das ist ein eigener Prüffall und darf nicht durch
ein künstliches `verified=true` ersetzt werden.

KDE-/AirPlay-Gegenstellen brauchen eine tatsächlich passende Netzverbindung.
NAT, lokale Netzfreigaben und Erreichbarkeit gesondert protokollieren. Eine
bereits im VM-Dateisystem liegende Datei prüft den Magnolie-Import, aber noch
keinen zuvor nicht ausgeführten Telefontransport.

## Was pro Issue als Nachweis hinterlegt wird

Jeder Abschluss oder Teilabschluss nennt Patch/Commit, Abhängigkeiten,
Umgebung und tatsächliche Tests. Für einen VM-Lauf gehören dazu OS-Build,
Architektur, SDK/Swift-/WebKit-Version soweit ermittelbar, Eingabefixtures,
Quellmanifest, Ergebnis und begrenzter Log-/Screenshotbeleg. Kontoidentitäten,
Zugangsdaten und persönliche Inhaltsdaten gehören nicht in öffentliche
Nachweise.

Bei einem Blocker die letzte erfolgreiche Phase und die konkrete fehlende
Voraussetzung nennen: etwa fehlender KVM-Zugriff, fehlendes Apple-SDK,
verweigerte Kontaktefreigabe, nicht geeignete iCloud-VM-Identität oder nicht
erreichbare KDE-Gegenstelle. Den passenden nächsten Befehl oder manuellen
Prüfschritt im Issue angeben. **Vorbereitet**, **hier bestanden** und
**in der macOS-VM bestanden** bleiben getrennte Statusangaben.
