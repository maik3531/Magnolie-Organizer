### Issue #843 – inzwischen upstream behoben

Die unabhängige Quelllösung ist in `66b50c44482f279d7c3566fe2959f66ebcc20cd5` übernommen; #843 wurde geschlossen. Auf dem anschließend eingefrorenen Stand `1f1f3225ab50fe38902bc8e790454fd944f8b693` bestand die unveränderte unabhängige Ownershipprobe 3/3 Fälle: beide Desktop-Blobzweige, Linux-Custom-Scheme/data:, Fehlerfreigabe, synchroner Ersatzworker während Providerfehler-Publish, alte Callbacks, Erfolg und idempotentes unload. Beide tatsächlichen Zeitzonenprojektoradapter akzeptieren die Upstreamquelle und deren aktualisierte TZ_PORT-Regel. Kein Produktcode wurde für diesen Nachtrag verändert.

Der frühere Alternativpatch `9c00336342f736f541cf14e006de1248b22b8850` samt damaliger Restserienübernahme `aed96df0` ist historisch und darf nicht nochmals angewendet werden. Entscheidung, exakte Befehle, Hashes und neue Logs: `open-audit/performance/843/upstream-adoption.json` und `upstream-manifest.json`. Der vollständige vorherige 77-Dateien-Nachweisstand ist unverändert archiviert.

Die Blob-Zahlen der ursprünglichen Reproduktion bleiben registrierte URL-Daten im Hostharness. Der data:-Fall prüft Protokollwahl und Besitz, keine native WebKit-Worker-Ausführung. Keine native Heap-/N100-/Monats-Trayabnahme; die übergreifende #395-Abnahme, numerische Suche und weitere Import-/Zeichenphasenanalyse bleiben eigenständig offen.
