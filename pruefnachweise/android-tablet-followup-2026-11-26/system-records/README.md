# Android-Systemprovider-Prüfstufe: Quell- und Hostnachweise zu #791

## Quelle und Einordnung

Diese Ablage gehört zu Folgepatch 10 des Android-Tablet-PRs #795. Lokale
Commitbasis bei der Ablage ist `abe1907fb12d20bfa92d60ebbc6b85c5829c1786`
(Folgepatch 9), Tree `99320dacf950d9ec6f570bbca2ab9ddef1ea6efa`.
Die sechs Änderungen der Provider-Prüfstufe waren darauf noch uncommittet.
Die endgültigen Dateihashes unten binden diese Änderungen unabhängig von einer
später abweichenden Remote-Commit-ID. Der Commit des Folgepatches wird von Root
im Issue zugeordnet.

**Die neue native Provider-Prüfstufe wurde noch nicht ausgeführt.** Die Belege
enthalten tatsächliche Quellkompilierungen und Hostprüfungen. Es wurde hier kein
APK erstellt, signiert oder installiert und kein Emulator gestartet.

Das neue manuelle Actions-Ziel heißt `tablet-system-records`. Es wählt allein die
Suite `system-records` auf API34 mit dem offiziellen `google_apis`-Image.
Die bisherigen all-/UI-/Services-/Files-/Domains-/Timezone-/API26-Ziele behalten
ihre bisherigen Suiten. Produktmanifest, Produktberechtigungen und bestehende
Ressourcen-, Ownership-, Koordinations- und Timeoutregeln sind unverändert.

## Tatsächlich ausgeführte Prüfungen

| Beleg | Umfang | Ergebnis |
|---|---|---|
| `compile-receipt-before-isolation.json`, `compile-cypixxyp/*.log` | 38 Produkt-Kotlin-Dateien, 16 Kotlin-Dateien der Instrumentierung einschließlich des tatsächlich konfigurierten gemeinsamen `tests/input`-Pfads, zwei Java-Testdateien und eine echte mit aapt2 erzeugte R-Klasse | Alle Befehle Exit 0 |
| `host-check-receipt.json`, `source-proof.log` | 24 Provenienz-/Workflowvertragstests | 24/24, Exit 0 |
| `host-check-receipt.json`, `owner-contracts.log` | Vier gezielte Owner-Verträge: Stageausführung, unveränderte Cold-Start-Auswahl, Slotfreigabe vor Seiteneffekten und Ablehnung veralteter/manipulierter Kandidaten | 4/4, Exit 0 |
| `compile-receipt.json`, `compile-isolation-y4c11elh/instrumentation-kotlin.log` | Finaler enger Recompile aller 16 Instrumentierungs-Kotlin-Dateien nach dem Scope-Nachtrag; unveränderte Produkt-/Java-/R-Eingaben wiederverwendet und ihre Quell-/Ressourcenhashes geprüft | Exit 0 |

Toolchain: echte Android-API37.2-Abhängigkeiten, Kotlin 2.4.21, JDK 21.0.13.1,
JVM-Ziel 17; vollständiger erster Quelllauf mit aapt2 36. Die vollständigen
Quell-, Ressourcen- und Abhängigkeitshashes stehen in den beiden Compile-Receipts.
`java-version.log` und sämtliche Compilerbefehle sind unverändert erhalten.
Workflow-YAML und die geänderten Pythonquellen wurden zusätzlich syntaktisch
geprüft; der geänderte Diff war whitespace-fehlerfrei.

### Reihenfolge und finaler Scope-Nachtrag

Die 24+4 Hosttests und die vollständige erste Quellkompilierung erfolgten vor dem
Nachtrag dieser zwei Receipt-Literale in `NativeSystemProviderSmoke.kt`:

```json
{
  "contactsSourceIsolationTested": false,
  "calendarSourceIsolationTested": true
}
```

Die Kontakte-Fixture verwendet nur die eine tatsächliche lokale Kontaktquelle.
Sie prüft Kontaktfelder und Kontaktidentität, aber keine Isolation gegen eine
zweite Kontaktquelle. Die Kalender-Fixture legt zwei lokale Kalender an und
prüft die Auswahl mit einer exakten erwarteten Titelmenge. Es wurden dafür keine
AccountManager-Konten eingerichtet.

Der Nachtrag verändert ausschließlich die deklarierte Prüfgrenze im Receipt.
Sein entfernter einzelner Quelltextabschnitt reproduziert nachweislich exakt den
früher kompilierten und im Hostbeleg gebundenen Dateihash. Alle anderen Inputs der
Hostbelege sind unverändert. Deshalb wurden die 24+4 Hosttests nicht nochmals
ausgeführt; der betroffene Instrumentierungspfad wurde tatsächlich neu kompiliert.
`source-binding-verification.json` hält diesen Abgleich fest. Alte Receipts sind
unverändert archiviert; ihnen wird kein nachträglicher Lauf zugeschrieben.

Die beiden Literale beschreiben den Umfang der Instrumentierung. Sie stellen für
sich noch keinen erfolgreichen Androidlauf dar. Der Host-Compilebeleg verwendet
dafür bewusst `calendarSourceIsolationPlanned: true` und
`nativeRuntimeTest: false`.

## Elf vorgesehene native Prüfgruppen

1. Tatsächliche Kontakt- und Kalenderreads benötigen reguläre READ-Berechtigungen;
   ohne diese liefern Discovery und Read den vorgesehenen Negativfall.
2. Echte Discovery findet die lokale Kontaktquelle und beide erzeugten Kalender.
3. Echte Kontakt-Data-Zeilen liefern Namen, Telefonart und Geburtstag.
4. Dieselbe SOURCE_ID behält bei einer tatsächlich neuen RawContact-Zeile die
   Datensatzidentität; die Zeilenbindung ändert sich.
5. Eine geänderte SOURCE_ID auf derselben Zeile erzeugt eine neue Datensatzidentität
   bei gleicher Zeilenbindung.
6. Nur der ausgewählte Kalender wird übernommen; zeitgebundene Termine und
   UTC-Ganztagsspannen beachten ihre jeweiligen exklusiven Grenzen.
7. Die Ganztagsauswahl behält den letzten gewählten Tag auch in einem westlich
   verschobenen Instant-Fenster.
8. Ein verschobener Einzeltermin behält seine Identität.
9. Echte RRULE-Expansion und eine verschobene Ausnahme behalten die ursprüngliche
   Serieninstanzidentität; der zweite Serientermin bleibt erhalten.
10. Ein vorab ausgelöstes Android-CancellationSignal verhindert beide Reads.
11. Nur die tatsächlich selbst erzeugten Kontakt-/Kalender-IDs werden entfernt;
    Schreibrechte fehlen anschließend.

Die Test-Fixture nimmt ausschließlich WRITE_CONTACTS/WRITE_CALENDAR vorübergehend
an. Vor jedem Produktlesepfad wird die öffentliche Shell-Permission-Identity
explizit abgelegt; effektive WRITE-Denials und der erwartete reguläre READ-Zustand
werden geprüft und im späteren nativen Receipt protokolliert. Kein versteckter
Getter, keine Reflection und keine erweiterte Produktberechtigung werden genutzt.

## Verbleibende Androidabnahme

Erforderlich bleibt ein eigener Actions-Lauf `target=tablet-system-records` auf
dem veröffentlichten Folgepatch, mit dem unveränderten vollständigen APK-Gate und
dem bestehenden Emulator-Owner. Die Suite benötigt dessen frische AVD/Installation.
Die gewährten regulären READ-Rechte bleiben bis zum Owner-Cleanup dieser AVD
bestehen; sie werden nicht mitten in der laufenden Instrumentierung widerrufen.

Auch ein später erfolgreicher Lauf belegt keine Berechtigungsdialoge, keinen
laufenden Berechtigungswiderruf, keine zweite Kontaktquelle, keine UI-/SaveACK-
Abnahme und keinen Abbruch einer bereits laufenden Providerabfrage. Die
Vorab-Cancellation ist ausdrücklich davon getrennt. Eine laufende Synchronisierung
oder Schreibfreigabe an Produktprovider wird nicht behauptet.

## Reproduktion und Belegdateien

`compile-instrumentation.py` und `recompile-isolation-receipt.py` sind die
unveränderten tatsächlich ausgeführten Quellprüfskripte. Ihre absoluten Arbeits-
und Abhängigkeitspfade in Skripten und Logs dokumentieren die Herkunft. Die
Skripte sind historische Reproduktionsbelege: Für eine Wiederholung in einem
anderen isolierten Arbeitsbereich müssen diese Pfade entsprechend eingerichtet
werden. Sie ersetzen keine vorhandenen Build-, Paket-, Ressourcen- oder
Koordinationsgates und gehören nicht zum produktiven Bauablauf.

Es sind ausschließlich Textdateien abgelegt, keine JARs, Klassen, APKs, Archive
oder Screenshots. Die neun Compiler-/Ressourcenlogs und beide Hostlogs sind
vollständig und unverändert kopiert. `source-binding-verification.json` bindet
die 17 kopierten Originaldateien; `SHA256SUMS` bindet sämtliche Belegdateien
außer sich selbst.

## Finale sechs Quellhashes

| Repositorypfad | SHA256 |
|---|---|
| `.github/workflows/ports-2.0.30.yml` | `a3a8d7ae4168afc135f804bb5df0c9bad9b17d732fbfc84617b6567c25915038` |
| `Magnolie-Organizer-Android-Tablet-Beta/app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeSystemProviderSmoke.kt` | `945457ac143bcb85a0b827bd5dd868a5c296c4e4264ec35cbda50a35a1139a2b` |
| `Magnolie-Organizer-Android-Tablet-Beta/app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeTabletInstrumentation.kt` | `0d53017cb81175e0ac4346d478b69e15568c78db5af9cc92e713d88434e52171` |
| `Magnolie-Organizer-Android-Tablet-Beta/tools/emulator-session.py` | `98d41a4f031c441a9b301d22817affe2152d4f45e4136983e1886118bfcd06b3` |
| `Magnolie-Organizer-Android-Tablet-Beta/tools/native-checks.py` | `8b0a30b8d379f7c13c7941492207e528d86e5fb025aa3c875a0c522637f98b15` |
| `Magnolie-Organizer-Android-Tablet-Beta/tests/test_source_proof.py` | `b4db1eea1cabb5e9ac3021661ab34d1eb948ef0241587dcadf107d601d2d686e` |
