# Prüfprotokolle

`final-*` enthält die abschließenden gezielten Prüfungen auf dem zusammengeführten Codecommit. Die vollständigen Handbuch-/Mac-Läufe und unabhängigen Importprüfungen nennen ihre eigenen Quellstände in den JSON-Nachweisen.

Vorherprotokolle dokumentieren erwartete Fehler der jeweils ausdrücklich untersuchten Original- oder Zwischenfassung. Sie sind keine Fehler des fertigen Patchstands. `823-before-python.log` ist ein Zwischenkorpus; der vollständige Vergleich mit 37 Vektoren steht in `823-shared-function-before-after.json`.

Umgebungsspezifische absolute Arbeitsverzeichnisse wurden durch `$REVIEW_SOURCE`, `$REVIEW_WORKSPACE`, `$FOLLOWUP_WORKSPACE`, `$PRIMARY_RUNTIME` und `$HOST_USER` ersetzt. Die Prüfergebnisse, Daten und Assertions sind unverändert. Die Prüfsummen beziehen sich auf diese veröffentlichten Textdateien. Testgruppenzahlen und Assertions verschiedener Läufe dürfen nicht als eindeutige Gesamtzahl addiert werden.

Windows-DPAPI, native Geräte-/Provider-/GUI-Prüfungen und persönliche Daten waren nicht Teil der entsprechenden Hostläufe. Die genaue Grenze steht im Hauptbericht und im jeweiligen Protokoll.
