# #854 – BE/NL Feriengruppen, Swift-Dienst-Teilpatch (28.11.2026)

Main unverändert 1749c92eb42801c38eaba31b272d8c0e27be9164. **Nach #855 und #856 anwenden**; nur macOS-Dienst, unabhängig vom Linux-Teilpatch. Kein Produktmerge, keine GUI-Freischaltung. Die historische #691/#128-Restserie ist nicht neu übernommen; #128 laut jüngsten Kommentaren weiterhin privat aktiv, nicht konkurrieren.

Reproduziert auf dem vollständigen tatsächlichen HolidayService.swift nach #855+#856: beim BE/NL-Gruppenabruf wird subdivisionCode statt groupCode benutzt; PublicHolidays wird für jede Schulgruppe abgefragt; Gruppen fehlen im Parser, Scope wird bei fehlenden Subdivisions aus der Anfrage ergänzt. Mit denselben kontrollierten JSON-Fixtures vor Korrektur **12/50**, nachher **50/50**. Unterschied umfasst neue Feature-Anforderungen, nicht 38 unabhängige Bugs. Swift 6.2.1, x86_64 Linux, swift-version 5. Der komplette Dienst wurde kompiliert, Transport und BetaError sind Doubles; keine native macOS-/AppKit-/Paket- oder Live-Abnahme. DNS blockiert Checkout; der Swift-Blob der kombinierten Vorpatches wurde aus den exakten Remote-Hunks rekonstruiert, lokale Kopie per git hash-object bestätigt. In isolierter Git-Testablage git apply --check, git apply, cmp, git apply -R --check, git apply -R, cmp bestanden (nur diese Datei, kein vollständiger Produktcheckout).

Sechs belegte Gruppen und Providervertrag siehe [Linux-Teilbericht](../codereview-holiday-be-nl-linux-2026-11-28/README.md) mit gepinnten OpenHolidays-Quellreferenzen/ODbL. Keine neuen Provider oder Rechte. SchoolHolidays groupCode; PublicHolidays einmal pro Land/Jahr ohne Gruppenparameter. Gruppenidentitäten erhalten; fehlende/fremde/widersprüchliche Gruppen, gemischte Gemeinde-/Gruppenscope und unvollständige/leere Antworten nicht als sichere Gruppenabdeckung behandeln. Länderweiter Abruf benötigt alle drei belegten Gruppen für Coverage. Kein tatsächlicher amtlicher Vollständigkeitsnachweis. Unveränderte AT/DE-Subdivision-Gegenproben grün. Alle Fixtures synthetisch, Jahreswechsel beispielhaft. Gruppenauswahl weiterhin nicht freischalten.

## Wiederholung

Nach #855/#856 im Checkout:
```sh
swiftc -swift-version 5 Magnolie-Organizer-macOS-Beta/Sources/BetaCore/HolidayService.swift /pfad/Doubles.swift /pfad/Probe.swift -o probe854
./probe854
```
Vorher Exit 1, nach Anwendung des Einzelpatches Exit 0. Dateien und Logs in diesem Artefaktverzeichnis; Probe ist ein eigenständiger Hosttest, kein neuer XCTest im Produkt. Kompletter regulärer XCTest-/Bridge-/GUI-Lauf offen. SHA256: Patch 2678ccb52055d34f94211b8d41ca9a8576057b584a8fb224ba65152788ca2223; Basis cba42c2c9f134f7bc4569b6c9db1248ff911146008c53987474a948e3f15cc8f; Kandidat 71713312d14f78d62afd8923aadc19ea68fa18ff7a14cf736d89bc7bee783a90. Git-Blobs nach Vorpatch a3ae8d4e038571d4dd0448e03a3002e5b85f9624, Kandidat 6e0c3cc336317d3cf128d4a4c40560b6195415c8. Probe 5cd5ec7defac7644cefbe323b2333e496a799be76de6b0907ba1df478c793a0d; Doubles 973254fb69df7946fdb4ab88cf297028fd39970dd8a30e23d1f3d5d9908a199e; Logs before bdc98c69832f60b3f6e043d9ad17cda6b3c5c231f75c6e8886aa6a2122271111 / after 6672e5797e2886f07bc396b37ef795e8c31c5cfa132ddeb2a45ad9edf00502b3.

Nächster Schritt: Windows- und Kotlin-Provider; .NET im jetzigen Container nicht verfügbar, Kotlin vorhanden. Anschließend GUI/MCP/Cache und Länderweiter PublicHolidays-Scope trotz Schulgruppenwahl, Ersteinrichtung, Live-Provider, native Prüfungen, Handbuch. #853, FR-Patch und Sync-Aufsetzpunkt erhalten.
