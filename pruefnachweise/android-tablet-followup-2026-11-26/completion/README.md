# Abschlussnachtrag: Quellenidentität und Issue-Abgleich

Der tatsächliche erfolgreiche Build-/Providerlauf ist
[Actions #101](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
auf Head `7a7d90b04796cf338b98f0fdbb87e8da1c967043`, Tree
`06c1a8cf6f115908dc21252682c2a358246f2cb7`. Die Originalbelege und der
ausgeführte Artefaktprüfer liegen im benachbarten Ordner `ci-run-45822320243/`.

Der anschließende Abschlusscommit verändert ausschließlich drei
Dokumentationsdateien und diesen Nachweisordner. Er wird nicht als neuer
APK- oder Emulatorlauf ausgegeben. Der tatsächliche Providercode ist unverändert;
`NativeSystemProviderSmoke.kt` hat weiterhin SHA256
`d8b598923ef3f1d092ed3ffb83268571e748a6cb3ac035c8fb69ca0e1826fba3`.

## Ausgeführter Quellen- und Projektionsvergleich

`documentation-comparison.json` ist eine ausdrücklich abgeleitete Auswertung.
Der daneben enthaltene Prüfer wurde ausgeführt; die drei Dokumentationsdateien
waren zu diesem Zeitpunkt geändert, die abschließenden Nachweisdateien wurden
danach hinzugefügt. Es wurde keine ausführbare Produkt-/Test-/Buildquelle geändert.
Die lokale Vergleichsbasis `41ce9f771ac42c6203f5e7fe2065d086dd2ab306` hat exakt
denselben Git-Baum wie der tatsächlich getestete Remotehead `7a7d90b...`.

Der Projektionsgenerator wurde ausgeführt, anschließend bestand
`node tools/project-web.cjs --check`. Die geprüfte CI-Projektion lautet
`dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09`.
Die Dokumentationsprojektion lautet
`257fa1cd947bbc89cb4db9c2a240dfd784edff2b562029869d904805cde73613`.
**Alle 83 Laufzeitausgaben und ihre SHA256 sind exakt gleich.** Der veränderte
Inputbind stammt aus dem aktualisierten Folgeaudit; die APK aus CI101 behält
ihre ursprüngliche, konkret geprüfte Bindung.

Nach dem normalen Projektionsaufbau ist der Vergleich mit den ursprünglichen
CI101-Artefakten reproduzierbar:

```sh
python3 -B verify-documentation.py \
  --repository /path/to/Magnolie-Organizer \
  --ci-projection /path/to/extracted-ci101/artifacts/projection.json \
  --base-commit 7a7d90b04796cf338b98f0fdbb87e8da1c967043 \
  --output /path/to/documentation-comparison.json
```

## Abschließender Issue-Abgleich

`issue-delta.json` wertet die fünf tatsächlich gelesenen GitHub-Suchantworten
vom 26. November 2026 aus. Es ist kein Original-API-Export und behauptet keine
erneute historische Volluntersuchung. Die heutigen Abfragen ergeben eine
Vereinigungsmenge von 63 Issues und enthalten sämtliche **33 maßgeblichen
Tablet-Issues**: ursprüngliche 26 plus #798–#801, #804, #805 und #807.
Es wurde kein zusätzliches maßgebliches Tablet-Issue erkannt. Zeitpunkt,
Suchausdrücke, Trefferzahlen, vollständige ID-Mengen und begründete Abgrenzungen
der parallelen Desktop-/macOS-Arbeit sind im Beleg enthalten.

Dieser Abschlussnachtrag erweitert keinen fachlichen Abnahmeumfang: echte
UI-/Touch-/IME-/TalkBack-, Berechtigungsdialog-/Live-Widerruf-/Save-ACK-Fälle,
unsynchronisierte lokale Serienausnahmen, zweite Kontaktquelle und die übrige
native Speicher-/SAF-/Restore-/Neustartmatrix bleiben separat ausgewiesen.

## Unveränderte Originalprotokolle

Der vollständige Diff-Whitespacecheck meldet 14 abschließende Leerzeichen in
originalen leeren Zeitstempelzeilen: zwei in `ci-run-45822320243/instrumentation-success.log`
und zwölf in `ci-run-45822320243/provider-progress.log`. Diese Originalbytes
bleiben zur nachprüfbaren Kopiergleichheit erhalten. Der Check aller übrigen
Dateien besteht. Es wurde keine Git-Prüfkonfiguration geändert oder ein Log
nachträglich normalisiert. Die vollständige Patchanwendung protokolliert diese
Whitespacewarnungen ausdrücklich und prüft trotzdem den exakten Ergebnisbaum.
