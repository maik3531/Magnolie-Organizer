# Gesicherter Auditstand und aktuelle Lieferung

Die vollständige Sichtung der ursprünglich **106 offenen Issues**, die ausgeführte Bereinigung und die vorbereiteten Patches sind auf diesem eigenen Artefaktzweig abgelegt. Der Einstieg in den abschließenden Stand ist [README.md](README.md); die aktuellen anwendbaren Patches stehen ausschließlich unter [final-patches](final-patches).

## Bereits vor der Schlusslieferung gesichert

Der frühere Zwischenstand wurde als Commit [`2baf32b3d28079933acc6a366ae17f3f4499edeb`](https://github.com/maik3531/Magnolie-Organizer/commit/2baf32b3d28079933acc6a366ae17f3f4499edeb) veröffentlicht und mit den tatsächlichen Remote-Dateiinhalten zurückgeprüft. Er enthielt 20 Dateien mit 741.395 Bytes, darunter die vollständige 106-Issue-Matrix, die 31 verifizierten Schließungen und die damalige Serie auf `24927cf9`. Dieser Commit bleibt als eigener historischer Stand erhalten.

Die damaligen Patchdateien sind ergänzend unter [checkpoint-patches-24927cf9](checkpoint-patches-24927cf9) archiviert. Sie sind **keine zweite aktuelle Anwendungsempfehlung**. Insbesondere wurde der dortige #843-Alternativpatch später durch eine tatsächlich geprüfte Upstreamkorrektur überholt.

## Abschließende Quellenbasis

Die aktuelle Serie setzt auf dem endgültig eingefrorenen Stand **`7a490dd87e94eec08d7f09cb95a04b34bf4621c2`** auf. #823, #843 und die ursprünglichen #844-/#845-Übernahmen sind darin bereits vorhanden. Die beiden letzten Nachträge behandeln ausschließlich unabhängig bestätigte Reste.

Auch die vorherige vollständige Serie auf `1f1f3225` hatte alle gezielten Integrationsprüfungen bestanden. Sie liegt unverändert unter [checkpoint-patches-1f1f3225](checkpoint-patches-1f1f3225), nachdem #845 inzwischen upstream umgesetzt worden war. Diese ältere Serie ist Historie und wird nicht zusätzlich auf den aktuellen Stand angewandt. [source-followups.json](source-followups.json) dokumentiert die begrenzten Nachprüfungen zwischen den Quellenständen.

Die Produktdateien dieses Artefaktzweigs werden durch die Lieferung nicht verändert. Maßgeblich für eine Patchanwendung ist die im [Patchmanifest](final-patches/manifest.json) genannte Basis, nicht der historische Produktstand des Artefaktzweigs. Übernahme nach `main`, installierte Abnahme und öffentliche Pakete sind eigenständige Schritte.
