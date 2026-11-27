# Ergänzung zu #838: Status nach erfolgreichem JSON-Import

Basis: **244b1d62aa738ea5cd8fa7fc9449ccf62fb7b99d**. Die vier Catch-Korrekturen sind darin enthalten. Die zusätzliche Statusaktualisierung aus **08887a810befd4cda824a8bd6f504c95c4b3068a** fehlt in beiden Frontends.

## Nachweis

Ein ungültiges JSON wird über das tatsächliche Dateiauswahl-Control und FileReader geladen; anschließend wird über dasselbe Control ein gültiges Zeichenblatt geladen. Dieses ersetzt in allen Fällen die Zeichnung. Auf unverändertem main bleibt trotzdem die vorherige lokalisierte Fehlermeldung stehen.

**4 rot → 4 grün:** Linux/Windows jeweils auf Englisch/Deutsch. Ausgangslauf Exit 1, ergänzter Lauf Exit 0. before.json und after.json dokumentieren alle Statuswerte, die tatsächliche Datenübernahme und die ausbleibenden JavaScript-Ausnahmen. Der Fehlversuch verändert weder Zeichnungsdaten noch Speicherzustand. Nach der Ergänzung zeigt der Status in allen vier Fällen owned-drawing.json.

## Minimaler Patch

838-retry-only-against-244b1d62.patch ändert je eine vorhandene Zeile in magnolie-organizer/web/anwendung.js und magnolie-organizer-windows/app/web/anwendung.js: Der erfolgreiche JSON-Import setzt unmittelbar vor dem Fokus den Status auf file.name. Keine neuen Übersetzungstexte, keine Änderungen am Fehler- oder Speicherpfad. Der Patch enthält ausschließlich diese zwei Produktzeilen. git apply --check gegen die genannte Basis ist erfolgreich.

Patch SHA-256: 6630017c6f9b9fcb494f58749e5d1ab3b689026f156a100112233f5085436726

## Vollständiger Bytevergleich

Die im grünen Lauf geladenen vollständigen JavaScript-Texte wurden aus den exakt im Prüfer verwendeten Ersetzungs-Literalen rekonstruiert. Ihr Vergleich mit den vollständigen Git-Blobs nach Anwendung des Patches in einem temporären Index ist für beide Dateien bytegleich. byte-comparison.json dokumentiert Methode, Größen und Hashes.

| Datei | Basis SHA-256 | Patch und grüner Prüfer SHA-256 |
| --- | --- | --- |
| magnolie-organizer/web/anwendung.js | 472eb5b801f1862cce3c7a5c0bd7436127e2fc750e0c20c581c44a58c339fb49 | ba456e10baa48a72a2107139b06f9aa1f26809fa672106c6278bedda7077901a |
| magnolie-organizer-windows/app/web/anwendung.js | 7a28602891d5eeebc232c5424543e65360f0b622bdc0b2b1bf13adbe6a42739d | 68d1116b4bc03ed8be8789e97b91fca754ebcb81a9307e13dd53423633508e5a |

## Reproduktion und Grenzen

probe-retry.cjs nimmt als erstes Argument einen sauberen Checkout des genannten Basiscommits, als zweites before oder after. Benötigt werden die bestehenden Node-Testabhängigkeiten sowie die regulär erzeugten Zeitzonen- und deutschen Übersetzungsdateien. Mit vorbereitetem NODE_PATH: node probe-retry.cjs /pfad/zum/checkout before beziehungsweise after. manifest.json enthält die SHA-256 aller Nachweise.

Die Produkttexte wurden im Test geladen und für den grünen Lauf ausschließlich im Speicher um die beiden Patchzeilen angepasst. **Keine Mutation von main oder anderen Produktdateien, kein Commit, kein Push und keine GitHub-Änderung.** Die Anwendung lief unter JSDOM mit tatsächlichen Controls und FileReader-I/O; Canvas und native Grenzen sind simuliert. Keine native Linux-/Windows- oder Paketabnahme, keine kombinierte Prüfung mit weiteren Review-Patches. Der ursprüngliche UI-Zweig bleibt unverändert bei 08887a81; der getrennte main-Checkout bleibt bei 244b1d62 sauber.
