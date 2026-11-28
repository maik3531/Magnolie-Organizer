# #128 – Windows: atomare Registrierung des gewöhnlichen initialen WLAN-Requests (28.11.2026)

Basis `66dbd86578b84f1236429d789a208f1d3e0e9675`; Review-Elterncommit `28634d93808181f470e825e7b5303b0e55d7103d`. Fünf neue Main-Commits seit df1b1106: Medien-/Dateipfade, Testregistrierung, Arbeitsstand. Kein relevanter Übernahmehunk der fünf früheren Kandidaten gefunden; Linux magnolie_telefon.py geändert in desktop_capabilities, Datei-/Medien-/Native-Pfaden (die sechs Atomic-Run-Hunks bei 950, 1172, 1858, 1875, 8105, 8217 sind nicht betroffen). Kein alter Gesamtpatch anwenden. #128 offen; Issue-Suche auto_connection nur #128, queue_full keine spezifische Dublette.

## Teilbefund und Grenze

TelefonCoordinator.SendPersonalSyncAsync (947 ff.) registriert gewöhnliche Requests über PersonalSyncStore.RememberRun, dessen WriteMeta einen eigenen DB-Aufruf ausführt, vor TelefonStore.Enqueue (763 ff.) mit eigenständiger Transaktion. Scheitert die Kapazitätsprüfung (50 MiB) oder der INSERT, bleibt die Runregistrierung bestehen. Das wurde mit echtem SQLite anhand der SQL-Anweisungen und nachgebildeter Aufrufreihenfolge reproduziert, nicht mit kompiliertem C#. Anders als Linux/Notes wurde für Windows **keine 24-Stunden-Automatikblockade** nachgewiesen. BridgeDispatcher.Sync.cs 1374 ff. sendet weiterhin Request vor Attachment-Staging und Batches; der vorliegende Kandidat löst **nur** die initiale Request-/Run-Grenze, nicht den vollständigen Lauf. Kein neuer Trigger, keine Änderung am Actor/Scope, Manual oder Format 3/14.

Kandidat: eng begrenzter EnqueueInitialAutoRequest für Format 1/2 auto_wifi mit bisherigem wifi_only und unveränderter Lauf- und Nachrichtenlebensdauer; Run-Metadaten in derselben bestehenden Outbox-Transaktion. Kein Cleanup durch Löschung bereits bestehender Runs, kein Rechte- oder Pairingwechsel. RememberRun liest/schreibt über optionalen gemeinsamen DB-Kontext; bisherige Aufrufe behalten ihren Pfad. Bestehende Store-Restore-Sperre und Nachrichtengültigkeit bleiben. Kandidat unkompiliert; vor Einpflege reguläre .NET-Tests ausführen.

## Tatsächlicher SQL-Modelltest

`python3 probe.py before` 3/6; `python3 probe.py after` 6/6; SQLite 3.46.1. Reale temporäre DB, erneute Verbindung zur Prüfung des persistenten Zustands, 50 MiB Kapazität, injizierter SQLite-Insertfehler, Retry (in der Vorher-Variante scheitert dessen Vorbedingung), bereits bestehender Run, widersprüchlicher Run und Erfolg mit wifi_only. Alter Run und Statuszeile bleiben. Vereinfachtes Schema, opaque Testpayloads, modellierte Metadatenvalidierung und Ablauf; keine Produktverschlüsselung, C#-Ausführung oder Wire-/Geräteprüfung. Originale SQL-Strings SELECT value, INSERT OR IGNORE (false-Zweig), SUM(length(payload)) und INSERT INTO outbox. Logdateien und Probe beigelegt. Lokal ausgeführte SHA-256: Probe 5739e9b31442f568df7ed301d1cc51d1ca87ba9a8bf49c9b3366b0e8131cc111; vor d8852b7131c0baae256502c9b902b655dc7b364757c661708d539ac673a40ccb; nach 1e4bf8006dfb8b31e621d142b62e404120b4d8a38229b1d49a53e8f3cb101895.

## Quellenbindung

- magnolie-organizer-windows/PersonalSyncStore.cs 617f676f4c830626268c4ada21b5f99b6112675d
- magnolie-organizer-windows/TelefonStore.cs f056294b16f3c46bed93983f93ebe441ec8cb359
- magnolie-organizer-windows/TelefonCoordinator.cs ab2a7b84236135709c0c18bac7f86e5b8437d1b4
- magnolie-organizer-windows/tests/PersonalSyncTests.cs ed0c18a6b3b98bfce07ca8067a9298c4005453df
- magnolie-organizer-windows/tests/Program.cs fad3d85edf8ccdf4d5296ec21bdc1bc1421edee2
Alle Textänderungen mit eindeutigen Ankern gegen vollständige entfernte Quellen vorwärts und exakt rückwärts geprüft; kein lokaler git apply. Neuer .NET-Test in PersonalSyncTests mit echten SQLite-INSERT-Fehlern für beide Formate und WLAN/BT-Gegenprobe, in Program.cs registriert, **nicht ausgeführt**. .NET/Gradle fehlen im Testcontainer, git ls-remote meldet DNS-Fehler; Zugriff auf GitHub-Text über Connector möglich.

## Nächster Schritt

1. Echte C#-Regressionsgruppe und betroffenen Coordinator-/Bridge-Pfad ausführen; prüfen, ob der initiale Request und alle Attachments/Batches vor erster Zustellung in einer gemeinsamen Transaktion vorbereitet werden können. Fehlgeschlagene spätere Staging-Operationen sind bislang nicht korrigiert. Keine Behauptung eines vollständigen Windows-Fixes.
2. Linux-/Notes-Kandidaten vollständig integrieren und Android-Completion-Lifecycle mit tatsächlichen Tests abnehmen sobald Umgebung verfügbar.
3. Danach vollständiger ausgehandelter Marker-8-Vertrag, kein vorzeitiges Bewerben/Parserlockern. Kein Produktmerge.
