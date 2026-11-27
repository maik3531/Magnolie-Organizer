# Letzter Übernahmeabgleich: da81f59 → 7c9f939

**Ergebnis: Fünf der sieben vorbereiteten Restpatches sind inzwischen übernommen. Die aktuelle Übergabe benötigt nur noch den Notes-Postfachfix #691 und den Desktop-Actor-Postfachfix auf Basis `7c9f939`.**

## Unveränderliche Vergleichsstände

- Bisheriger `main`: `da81f594a2709d2c0ba78696b3af4775f38313f8`.
- Neuer `main`: `7c9f9395ac7fcac03b0ce229f9707643be4b06fa`.
- Bisheriger vorbereiteter Integrationsbaum aus `outbox-latest-current`: `f356e23260b661a00b753b01519c46cba977ca0b` — da81 plus sieben Restpatches.
- Methode: lesender Git-Log, vollständiger Vergleich der geänderten Dateien und gezielte Quell-/Test-/Dokumentationsdiffs. **Keine Programme oder Tests erneut ausgeführt.**

Die frühere Prüfung `upstream-adoption-review.json` und `.md` bleibt unverändert als Historie erhalten. Dieser Nachweis betrifft ausschließlich den danach hinzugekommenen Upstream-Stand.

## Vier neue Commits und fünf entfallende Restpatches

| Upstream-Commit | Übernommener Umfang | Entfallender ursprünglicher Einzelpatch |
|---|---|---|
| `37314cccba7d69ecb59de572a30f51dd47d62c3d` — #395 | Organisatorvorschläge nur bei Bedarf, begrenzte Vorschlagsliste und gezielte Tests | `06-395-organizer-suggestions.patch` |
| `0ffd44bb116b9ff18b1421f43c378bf69952b0b5` — #330/#759 | Auf gemeinsame Medieneinstellungen warten und erste Recovery-Antworten bis zur UI-Einbindung halten | `04-330-shared-media-wait.patch` **und** `05-330-initial-recovery-and-refresh.patch` |
| `a7853a2899dbb3bcb78e74a8bbbd353f2e8be297` — #192 | Bereits verbundene MCP-Telefonwerkzeuge korrekt dokumentieren | `02-192-correct-mcp-coverage.patch` |
| `7c9f9395ac7fcac03b0ce229f9707643be4b06fa` — #148 | Fernproben nach dem letzten tatsächlich versuchten Partner fortsetzen | `notes-148-fair-remote-probes.patch` |

Die Patchnamen bezeichnen die ursprünglichen Quellartefakte; eine spätere Nummerierung der da81-Übergabe wird damit nicht behauptet.

## Gleichheit und verbleibende Unterschiede

**#395:** Beide tatsächlichen Produktdateien `magnolie-organizer/web/anwendung.js` und `magnolie-organizer-windows/app/web/anwendung.js` sowie `magnolie-organizer-windows/tests/appointment-organizer-suggestions.js` sind mit dem vorbereiteten Integrationsbaum identisch.

**#330/#759:** `magnolie-organizer-windows/app/web/phone-media.js`, die Tests `phone-media-wait-ui.js`, `phone-media-recovery-mount-ui.js`, `phone-media-ui.js` und die betroffenen Registrierungen in `magnolie-organizer-windows/tests/run.js` sowie `magnolie-organizer/pruefungen/test.js` sind identisch.

**#192:** Der fachliche Dokumentationsnachtrag ist übernommen. Die einzige Abweichung in `contracts/mcp-coverage.md` zur vorbereiteten Fassung ist die genauere Aufzählung der drei vollständigen Befehlsnamen; sie bleibt erhalten.

**#148:** `FernAbgleichReihenfolge.kt` und `FernAbgleichReihenfolgeTest.kt` sind identisch. Der gesamte verbleibende Diff in `magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt` besteht ausschließlich aus dem **sechszeiligen #691-Nachtrag**: Der reine LAN-Wartezweig gibt mit `versucht--` seinen Versuch zurück und führt anschließend dasselbe `continue` aus. Das ursprüngliche `versucht++` bleibt stehen; Null-/Fehler-/fehlende-Partner-Fälle behalten ihre bisherige Budgetbegrenzung. Ein zusätzlicher #148-Rest besteht im gelieferten Rotationsumfang nicht.

## Zwei Upstream-Ergänzungen unbedingt erhalten

1. **`magnolie-organizer-windows/tests/web-smoke.js`:** Upstream liest das Organisatorfeld und ruft `organizerName.focus()` auf, bevor der Smoke-Test Vorschläge erwartet. Das passt zum neuen bedarfsabhängigen Verhalten. Der alte vorbereitete Baum enthält diese zusätzliche Aktion noch nicht.
2. **`contracts/mcp-coverage.md`:** Upstream nennt `organizer_phone_call_command_start`, `organizer_phone_call_command_status` und `organizer_phone_call_command_cancel` jeweils vollständig. Die alte Fassung verwendete die verkürzte Schreibweise `organizer_phone_call_command_start/status/cancel`.

Auch die aktuellen Upstream-Einträge in `ARBEITSSTAND.md` bleiben bestehen. Ein pauschaler Diff vom neuen `main` zum alten Baum `f356e232` würde diese Ergänzungen zurücknehmen. Die gewünschte Restübergabe entsteht durch die beiden verbleibenden Patches auf `7c9f939`.

## Aktueller Zweier-Rest

| Patchumfang | Verbleibende Produkt-/Testdateien |
|---|---|
| Notes #691: LAN-Warten verbraucht kein Versandversuchsbudget | `magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt` |
| Desktop: begrenzte faire Actor-Postfachauswahl | `magnolie-organizer-windows/TelefonCoordinator.cs`, `TelefonStore.cs`, `tests/Program.cs`, `tests/TelefonOutboxFairnessTests.cs`; `magnolie-organizer/bin/magnolie_telefon.py`; `magnolie-organizer/pruefungen/test_telefon_outbox_actor_fairness.py` |

Die jeweils zugehörige aktuelle Arbeitsstandsdokumentation wird mit diesen beiden Patches zusammengeführt. Diese Übernahmeprüfung erzeugt keinen neuen Produktpatch.

## Grenzen

Keine weitere Forschung, Laufzeitprüfung, Suite, Produktänderung oder externe Mutation. Der Nachweis betrifft die Übernahme des gelieferten Quellumfangs; er ist keine neue Geräte-/Paketabnahme und keine pauschale Abschlusserklärung für sämtliche übergeordneten Issues. Die früheren gezielten UI-Laufnachweise bleiben getrennt unter `outbox-ui-integration-evidence` dokumentiert.

Maschinenlesbarer Begleitnachweis: `upstream-adoption-current.json` im selben Verzeichnis.
