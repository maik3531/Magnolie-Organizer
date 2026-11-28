# #854 – BE/NL Feriengruppen, Kotlin-Teilpatch (28.11.2026)

Basis main 1749c92eb42801c38eaba31b272d8c0e27be9164, unverändert seit voriger Runde. Nach #855/#856 anwenden. Nur Tablet-Provider; unabhängig von Linux-/Swift-Teilpatch und FR-Auswahl. Keine GUI-Freischaltung, keine Produktübernahme. #128 laut voriger unveränderter Basis privat aktiv; #691 und alter Desktop-Pumpfix nicht als übernommen bestätigt.

Reproduziert: Der tatsächliche fetch-Methodenablauf verwendet subdivisionCode statt groupCode, ignoriert die Gruppen der Antwort, kann unbelegte Gruppen aus der Anfrage ergänzen und fragt öffentliche Feiertage je Gruppe mehrfach ab. Der Teilpatch trennt öffentliche landesweite Feiertage von den sechs bestätigten Schulgruppen (BE-DE, BE-FR, BE-NL, NL-NO, NL-MI, NL-ZU), erhält Gruppenidentitäten, unterbindet gemischte Gruppen-/Gemeindescopes in Gruppenanfragen und verweigert Coverage bei fehlenden, widersprüchlichen, leeren oder fremden Gruppendaten. Landesweite Schulferien-Coverage erfordert beobachtete Gruppen aller drei bestätigten Codes; dies beweist keine vollständige amtliche Jahresabdeckung. Bestehende AT/DE-Abrufpfade bleiben unverändert. Vorhandene Daten werden durch diesen Dienst nicht selbst gelöscht. GUI/MCP muss später landesweite PublicHolidays-Coverage unabhängig vom Schulgruppenscope zulassen. Quelle/ODbL und belegte Providerkennungen: [Linux-Teilbericht](../codereview-holiday-be-nl-linux-2026-11-28/README.md).

Tatsächlich ausgeführt: Kotlin-JVM 1.9.0 auf Linux, JRE 21.0.12.1. Vorher 20/64, nachher 64/64. Beide tatsächlichen vollständigen fetch-Methoden sind bytegleich an die rekonstruierten Produktblobs gebunden. Query, übrige Modellklassen, Datum/Titel/Normalisierung, JSON-Parser, HTTP-Transport, Abbruch und Bericht sind kontrollierte Doubles; der komplette Dienst, echte JSON-Decodierung, Gradle, Android, GUI, Live-Netz und Paketabnahme sind nicht ausgeführt. Fixtures synthetisch. Der Name "missing" im Probe bezeichnet eine leere Gruppenliste, nicht ein fehlendes JSON-Feld. Die Differenz umfasst Erweiterungsanforderungen, nicht 44 unabhängige Fehler. Vorwärts- und Rückwärts-Kontexthunks eindeutig auf vollständigem Produktblob geprüft; kein git apply auf Checkout (DNS nicht erreichbar). Compilerwarnungen: vorhandene Index-Verschattung und unbenutzte Double-Parameter; Kompilierung erfolgreich.

## Wiederholung

Nach #855/#856 im Produktcheckout die folgende Methode in den Host übernehmen (mit dem hier enthaltenen Skript). Vorher und nach Anwendung des Einzelpatches jeweils:

    python3 extract-host.py /pfad/zu/HolidayService.kt Host.kt
    kotlinc Host.kt Doubles.kt Json.kt Probe.kt -include-runtime -d probe.jar
    java -jar probe.jar

Vorher Exit 1, nachher 0. Host.template.kt, Probe.kt, Json.kt, Doubles.kt entsprechen den tatsächlich lokal kompilierten Dateien. Hashbindung und Ergebnisse in results.json. Keine zusätzliche Netz-/Standortfreigabe. #854 bleibt offen.

Nächster Schritt: Windows-Provider (.NET im aktuellen Container nicht vorhanden); danach gemeinsam GUI/MCP/Cache/Ersteinrichtung mit getrenntem PublicHolidays-/SchoolHolidays-Scope. Erst nach Plattformparität Auswahl freischalten. Live-Abdeckung, native Tests, Handbuch und Übersetzung offen. #853 und Sync-Aufsetzpunkt erhalten.
