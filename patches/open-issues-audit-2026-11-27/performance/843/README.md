# #843 – Kalender-Worker geben URL und Listener wieder frei

## Aktueller Stand: upstream behoben, Alternativpatch nicht erneut anwenden

Issue #843 ist inzwischen unabhängig in
`66b50c44482f279d7c3566fe2959f66ebcc20cd5` umgesetzt und geschlossen
([Abschlusskommentar](https://github.com/maik3531/Magnolie-Organizer/issues/843#issuecomment-7225588940)).
Der aktuelle geprüfte Folgestand ist `1f1f3225ab50fe38902bc8e790454fd944f8b693`.
**Den unten dokumentierten Alternativpatch `9c003363` nicht nochmals anwenden.**

Die unveränderte unabhängige Ownershipprobe besteht auf diesem Upstreamstand
erneut **3/3 Protokollfälle**: Windows- und Linux-Blobzweig sowie
Linux-Custom-Scheme/data:. Konstruktorfehler, ein synchron während der
Providerfehlerveröffentlichung erzeugter Ersatzworker, alte Callbacks, normaler
Erfolg, einzelner Jobfehler und wiederholtes unload bleiben korrekt. Beide
tatsächlichen Mac-/Tablet-Zeitzonenprojektoradapter bestehen ebenfalls.
Die Upstreamlösung gibt die Ressource vor `publish()` frei und hat dafür den
gemeinsamen TZ_PORT-Ersatztext passend aktualisiert. Sie ist keine bytegleiche
Übernahme des hier historisch dokumentierten Alternativpatches.

[upstream-adoption.json](upstream-adoption.json) enthält Entscheidung und
Quellenbindung; [upstream-manifest.json](upstream-manifest.json) die exakten
Befehle, Hashes, Laufzeiten und Protokolle. Die ursprüngliche Quellbindung und
die historischen Einzelprüfungen sind in [delivery.json](delivery.json) und
[after-manifest.json](after-manifest.json) dokumentiert. Das zusätzlich lokal
gesicherte Vollarchiv gehört nicht zu dieser textbasierten Lieferung.
Diese zusätzliche Hostprüfung ist weiterhin kein nativer
WebKit-/WebView2-Heap- oder 30-Tage-Nachweis.

## Historischer Alternativvorschlag und seine ursprünglichen Nachweise

Der damalige enge Quellvorschlag ist als `9c00336342f736f541cf14e006de1248b22b8850`
auf Basis `24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b` gesichert. Er gehört zu
[Issue #843](https://github.com/maik3531/Magnolie-Organizer/issues/843).
Seine Datei [refs-843-worker-url-lifecycle.patch](refs-843-worker-url-lifecycle.patch)
bleibt ausschließlich als historischer Beleg erhalten.
Commit, Patchhash und Bindung aller getesteten Eingaben stehen in [delivery.json](delivery.json).
Es wurden weder Main zusammengeführt noch Pakete gebaut oder veröffentlicht.

## Bestätigter Besitzfehler und Änderung

`icsRuntime` erzeugte vor dem Start eines neuen Workers eine URL. Der bisherige
`finally`-Block registrierte selbst nach einem fehlgeschlagenen Konstruktor einen
`unload`-Listener, der die URL erst beim Schließen des Dokuments freigab. Ein
Workerfehler oder eine verworfene Zeitzonenprovider-Identität beendete den Worker,
ließ seine URL und die zugehörigen Listener jedoch ebenfalls bis dahin bestehen.
Weitere Anfragen durften neue Worker anlegen und damit weitere Ressourcen halten.

Jetzt gehört eine idempotente Freigabefunktion jeweils genau dem erzeugten Worker.
Sie gibt seine URL frei und entfernt ihren eigenen Listener. Sie beendet den
Worker nur, wenn er noch der aktuelle Besitzer ist. Fehler beim Konstruktor,
`onerror` und die bestehende Providerverwerfung benutzen diese Freigabe. Späte
Ereignisse eines alten Workers werden ignoriert; ein neuer Worker und seine
Aufträge bleiben erhalten. Bei erfolgreicher Nutzung bleibt die URL bis zur
Freigabe des Workers bestehen.

Der feste `TZ_PORT:worker-response-identity`-Block ist unverändert. Eine lokale
`finally`-Klammer führt die Freigabe nach dessen bestehender Verwerfung aus.
Damit bleiben die gemeinsam geprüften Mac-/Tablet-Projektionsregeln anwendbar.
Das ist kein vollständiger nativer Port-Build oder Gerätetest.

## Vorher/Nachher: reale URL-Registrierung, kontrollierte Workerfehler

Die Probe ruft die echte Produktfunktion beider Desktopquellen auf. Die URLs und
Blob-Größen stammen aus Nodes wirklicher `Blob`-/Object-URL-Registrierung.
Worker-Konstruktor, Fehlerantworten und Providerverwerfung sind ausdrücklich
kontrollierte Fehlereinspritzungen. Es wurde kein Browserheap aus den Blob-Größen
abgeleitet. Die Tabelle zeigt jeweils den Zustand nach 32 Anfragen **vor unload**;
beide Desktopquellen ergaben dieselben Werte.

| Fall | Vorher: aktive URLs / registrierte Bytes / Listener | Nachher: aktive URLs / registrierte Bytes / Listener |
|---|---:|---:|
| Konstruktor schlägt jedes Mal fehl | 32 / 15.647.552 / 32 | 0 / 0 / 0 |
| Neuer Worker meldet jeweils `onerror` | 32 / 15.647.552 / 64 | 0 / 0 / 0 |
| Neuer Worker meldet jeweils falsche Provideridentität | 32 / 15.647.552 / 64 | 0 / 0 / 0 |
| Erfolgreicher Worker bedient 32 Anfragen | 1 / 488.986 / 2 | 1 / 488.986 / 1 |

Nach `unload` waren in allen Fällen vorher und nachher 0 URLs, 0 registrierte
Bytes und 0 Listener aktiv. Der Fehler lag in der unnötigen Aufbewahrung **während
des weiter geöffneten Dokuments**. Die Erfolgsprobe bestätigt, dass die Quelle
nicht vorzeitig freigegeben wird. Die Rohdaten stehen in
[before-actual-urls.json](before-actual-urls.json) und
[after-actual-urls.json](after-actual-urls.json).

Unter dem nativen Linux-Custom-Scheme wählt derselbe Produktionscode eine
`data:`-URL, weil WebKit dort keine Blob-Worker laden kann. Die obigen Blob-Zahlen
belegen den Produkt-Blobzweig im Harness; sie sind **keine native Linux-RAMzahl**.
Auch für diesen anderen URL-Zweig wird der Listenerbesitz geprüft; der unabhängige
Zusatzreview bestand drei Protokoll-/Besitzfälle einschließlich des echten
Produktzweigs unter `magnolie-organizer:`. Dort wurden keine Blob-URLs erzeugt.
Er bestätigt auch, dass ein synchron während der Fehlermeldung erzeugter
Ersatzworker erhalten bleibt. Die `data:`-Probe führt keinen nativen WebKit-Worker
aus. Ergebnis und Prüfumfang stehen in
[independent-review.json](independent-review.json).

## Ausgeführte Prüfungen

| Prüfung | Ergebnis | Aussage |
|---|---|---|
| Neue Rückfallbedingungen in der vorhandenen Worker-Suite auf unveränderter Basis | ROT, erwartete URL-Assertion | Der neue Test erkennt den reproduzierten Fehler |
| Reale URL-Probe nach Patch | PASS, acht Szenarien | Vier Lebenszyklen auf beiden Desktopquellen; aktive URL-/Byte-/Listenerzahlen |
| Erweiterte vorhandene `recurrence-worker.js` | PASS, beide Quellen | Reale isolierte Worker für normale Serienfälle; Fehlerwiederholungen, alte Callbacks, Erfolgsbesitz und unload |
| Tatsächlicher Mac- und Tablet-Zeitzonenprojektor auf beiden Quellen | PASS | Unveränderte Adapter akzeptieren den neuen Funktionsrahmen, gemeinsame Ausgabe ist identisch und syntaktisch gültig |
| Unabhängiger Zusatzreview | 3/3 PASS | Beide Blob-Zweige, Linux-Custom-Scheme/data:-Zweig, synchroner Ersatzworker und idempotente Freigabe; je 51 TZ_PORT-Blöcke bytegleich zur Basis |
| `git diff --check` | PASS | Keine Whitespacefehler |
| Bestehendes `test_planner_regressions.py` | 1 PASS / 1 FAIL, vorbestehender Ankerfehler | Regex erwartet einen Zeilenanfang vor `function icsRuntime`; die Deklaration trägt schon auf unveränderter Basis davor einen TZ_PORT-Marker |

Der letzte Fehler wurde gegen beide unveränderten Basisdateien geprüft und ist
in [planner-parity-boundary.json](planner-parity-boundary.json) sowie im
[Originalprotokoll](logs/planner-parity.log) festgehalten. Die tatsächlich
ausgelesenen vollständigen `icsRuntime`-Blöcke beider geänderter Desktopquellen
sind bytegleich (SHA-256 `206bc8c75382e764c16523bc95445ef1a69517e0cf8ebad96f944b94d221d8e1`).
Dieser fremde Test wurde nicht im Lebenszykluspatch umgebaut.

Die finalen Prüfungen liefen auf den anschließend unverändert committeten Bytes.
[after-manifest.json](after-manifest.json) enthält Befehle, Arbeitsverzeichnis,
Umgebung, Quellhashes, Exitcodes und Laufzeiten. [delivery.json](delivery.json)
bindet diese Bytes an den fertigen Commit. Frühere Messfassungen in
`superseded-listener-accounting/` und `intermediate-identity-projection/` sind
ausdrücklich überholt und dienen ausschließlich der nachvollziehbaren Historie.

## Gezielt wiederholen

Die bestehenden Werkzeuge genügen. Vorhandene Zeitzonenassets können im normalen
Repositoryablauf erzeugt werden:

```sh
cd /workspace/scratch/7203da5bd564/open-audit-395-worker-url
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --output magnolie-organizer-windows/app/web
NODE_PATH=/workspace/scratch/7203da5bd564/round3-tools/js/node_modules node magnolie-organizer-windows/tests/recurrence-worker.js
python /workspace/scratch/7203da5bd564/open-audit/performance/843/run_checks.py --phase verification --root /workspace/scratch/7203da5bd564/open-audit-395-worker-url --expect-clean
```

Für eine erneute rote Regression zunächst ausschließlich die neue Testdatei auf
eine saubere Basis `24927cf` übernehmen und dieselbe Worker-Suite ausführen.
Der erfolgreiche und der fehlerhafte Produktpfad stammen damit jeweils aus den
angegebenen Originalquellen, nicht aus einem nachgebauten Lifecycle-Algorithmus.

## Offene Grenze

Dieser Patch beseitigt den eng gemessenen Besitzfehler. Er beweist weder die
Ursache des ursprünglichen N100-Berichts noch eine dauerhaft stabile native
Speichernutzung. Die Abnahme von 30 Tagen im Tray, nativen Prozessbäumen und
großen Büchern bleibt in [#395](https://github.com/maik3531/Magnolie-Organizer/issues/395).
Anwendungsfehler, echte Dateispeicherung und native WebKit-/WebView2-Ressourcen
werden durch die Hostfehlerprobe nicht vollständig simuliert.
