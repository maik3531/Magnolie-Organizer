using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncTests
{
    internal static async Task RunAsync()
    {
        PersonalCustomConsentTests.Run();
        var resource = Path.Combine(AppContext.BaseDirectory, "resources", "personal-sync-contract.json");
        TestAssert.That(File.Exists(resource), "Repository-lokaler Personal-Sync-Vertrag fehlt.");
        var vectors = JsonNode.Parse(await File.ReadAllTextAsync(resource))!.AsObject(); var value = vectors["value"]!.AsObject();
        TestAssert.That(Encoding.UTF8.GetString(TelefonCrypto.Canonical(value)) == vectors["canonical"]!.GetValue<string>() && PersonalSyncContract.ProjectionHash(value) == vectors["sha256"]!.GetValue<string>(),
            "Kanonische Personal-Sync-Projektion weicht vom Vektor ab.");
        var unicode = vectors["unicode_order"]!.AsObject();
        TestAssert.That(Encoding.UTF8.GetString(TelefonCrypto.Canonical(unicode["value"]!)) == unicode["canonical"]!.GetValue<string>(), "Unicode-Codepoint-Sortierung weicht ab.");
        var conflict = vectors["conflict"]!.AsObject();
        TestAssert.That(PersonalSyncContract.ConflictId(conflict["kind"]!.GetValue<string>(), conflict["id"]!.GetValue<string>(), conflict["loser_hash"]!.GetValue<string>()) == conflict["id_v4"]!.GetValue<string>(), "Konflikt-ID weicht ab.");
        var clock = vectors["clock"]!.AsObject(); TestAssert.That(PersonalSyncContract.CompareClocks(clock["left"]!, clock["right"]!) == clock["comparison"]!.GetValue<string>(), "Vektoruhrvergleich weicht ab.");
        var deletion = vectors["deletions"]!.AsObject();
        TestAssert.That(PersonalSyncContract.DeletionProposalId(deletion["peer_device_id"]!.GetValue<string>(), deletion["kind"]!.GetValue<string>(), deletion["id"]!.GetValue<string>(), deletion["parent_id"]!.GetValue<string>(), deletion["clock"]!, deletion["prior_hash"]!.GetValue<string>()) == deletion["proposal_id"]!.GetValue<string>(), "Löschvorschlags-ID weicht ab.");

        var format2 = vectors["format2"]!.AsObject(); var format2Value = format2["value"]!.AsObject();
        TestAssert.That(Encoding.UTF8.GetString(TelefonCrypto.Canonical(format2Value)) == format2["canonical"]!.GetValue<string>() && PersonalSyncContract.ProjectionHash(format2Value) == format2["sha256"]!.GetValue<string>(), "Format-2-Projektion weicht ab.");
        var decoded = PersonalSyncContract.DecodeDataUrl(format2["data_url"]!.GetValue<string>()); TestAssert.That(decoded.Mime == "image/png" && decoded.Data.Length == 8, "PNG-Data-URL wurde nicht streng dekodiert.");
        foreach (var invalid in format2["invalid_names"]!.AsArray())
        {
            var bad = format2Value.DeepClone().AsObject(); bad["attachments"]![0]!["name"] = invalid!.GetValue<string>();
            var record = Record("note", "note-1", bad, format: 2); var body = Batch("44444444-4444-4444-8444-444444444444", record, 2);
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.batch", body), "Ungültiger Attachment-Dateiname wurde angenommen.");
        }
        foreach (var name in new[] { "whitespace_id", "leading_space_id", "trailing_space_id", "leading_tab_id", "trailing_tab_id" })
        {
            var record = Record("note", vectors["invalid"]![name]!.GetValue<string>(), value);
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.batch", Batch("44444444-4444-4444-8444-444444444444", record)), $"Ungültige ID {name} wurde angenommen.");
        }
        var unsorted = Record("note", "note-1", value); unsorted["clock"] = vectors["invalid"]!["unsorted_clock"]!.DeepClone();
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.batch", Batch("44444444-4444-4444-8444-444444444444", unsorted)), "Unsortierte Vektoruhr wurde angenommen.");
        var task3Value = new JsonObject { ["title"] = "Kind", ["note"] = "", ["due"] = "", ["priority"] = 2,
            ["completed"] = false, ["remind"] = false, ["lead_days"] = 0, ["reminder_minute"] = 0,
            ["created_ms"] = 1, ["modified_ms"] = 2, ["uid"] = "kind-1", ["parent_uid"] = "parent-1", ["order"] = 7 };
        var task3Record = Record("task", "task-1", task3Value, format: 3);
        TestAssert.That(task3Record["modified_ms"]!.GetValue<long>() == 2,
            "Eine als Int32 aufgebaute JSON-Ganzzahl wurde nicht verlustfrei in den Personal-Sync-Datensatz übernommen.");
        PersonalSyncContract.ValidateBody("personal_sync.batch", Batch("45454545-4545-4545-8545-454545454545", task3Record, 3));
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.batch",
            Batch("45454545-4545-4545-8545-454545454545", task3Record.DeepClone().AsObject(), 2)),
            "Format 2 akzeptierte AufgabenGraph-Felder aus Format 3.");

        var tempRoot = Path.Combine(Path.GetTempPath(), "magnolie-personal-tests-" + Guid.NewGuid().ToString("N"));
        try
        {
            await TestNegotiatedRoundtripAndFullChunks(Path.Combine(tempRoot, "roundtrip"), task3Value);
            var key = Enumerable.Range(1, 32).Select(value => (byte)value).ToArray(); var store = new TelefonStore(new WindowsPaths(tempRoot), key); var personal = new PersonalSyncStore(store);
            var runtimeNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            const string peer = "55555555-5555-4555-8555-555555555555"; const string run = "66666666-6666-4666-8666-666666666666";
            var request = new JsonObject { ["format"] = 1, ["run_id"] = run, ["trigger"] = "auto_wifi", ["modules"] = new JsonArray("notes") }; personal.RememberRun(peer, request, runtimeNow, runtimeNow + 50_000);
            TestAssert.That(personal.LoadRun(peer, run, runtimeNow + 1000)?.Policy == "wifi_only" && personal.LoadRun(peer, run, runtimeNow + 50_001)?.Expired == true, "Laufpolicy oder Ablauf ist nicht dauerhaft.");
            var emptyCounts = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0 };
            var report = new JsonObject { ["format"] = 1, ["run_id"] = run, ["state"] = "complete", ["trigger"] = "auto_wifi",
                ["transport"] = "wifi", ["sent"] = emptyCounts.DeepClone(), ["received"] = emptyCounts.DeepClone(), ["conflicts"] = 0,
                ["attachments_omitted"] = 0, ["oversized_skipped"] = 0, ["started_ms"] = runtimeNow, ["finished_ms"] = runtimeNow,
                ["error"] = "none", ["deletions"] = new JsonObject { ["pending"] = 0, ["deleted"] = 0, ["restored"] = 0,
                    ["conflicts"] = 0, ["blocked"] = 0, ["trash"] = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0, ["attachments"] = 0 } } };
            personal.StageReport(peer, report);
            TestAssert.That(personal.ReadyReport(peer, run, runtimeNow + 1) is not null && personal.ReadyReport(peer, run, runtimeNow + 2) is not null,
                "Ein Personal-Sync-Bericht wurde vor erfolgreichem Enqueue gelöscht.");
            personal.DeleteReport(peer, run);
            TestAssert.That(personal.ReadyReport(peer, run, runtimeNow + 3) is null,
                "Ein erfolgreich enqueueter Personal-Sync-Bericht blieb staged.");
            var record = Record("note", "note-1", value); var batchBody = Batch(run, record); var message = Message("personal_sync.batch", batchBody, runtimeNow + 2000, runtimeNow + 40_000);
            TestAssert.Throws<InvalidDataException>(() => personal.StageBatch(peer, message, "bluetooth", runtimeNow + 2000), "Auto-WLAN-Batch wurde über Bluetooth angenommen.");
            var pending = store.CommitIncoming(peer, message, runtimeNow + 2000, (_, _) => null, deferAcceptance: true);
            TestAssert.That(pending.Process && pending.Status == "accepted", "Batch wurde vor Dispatch nicht durable im Inbox staged.");
            var staged = personal.StageBatch(peer, message, "wifi", runtimeNow + 2000)!; TestAssert.That(staged.Records.Count == 1, "Vollständiger Batch wurde nicht staged.");
            var restartedStore = new TelefonStore(new WindowsPaths(tempRoot), key); var restarted = new PersonalSyncStore(restartedStore);
            var beforeCommit = restartedStore.CommitIncoming(peer, message, runtimeNow + 2001, (_, _) => null, deferAcceptance: true);
            var replay = restarted.StageBatch(peer, message, "wifi", runtimeNow + 2001)!;
            TestAssert.That(beforeCommit.Process && replay.CommitToken == staged.CommitToken &&
                !restarted.CommitBatch(peer, replay.PendingMessageId, "wrong-token", runtimeNow + 2999, out _) &&
                restartedStore.CommitIncoming(peer, message, runtimeNow + 2999, (_, _) => null, deferAcceptance: true).Process &&
                restarted.CommitBatch(peer, replay.PendingMessageId, replay.CommitToken, runtimeNow + 3000, out var committed) && committed.Count == 1,
                "Batch-Staging/Commit ist nach Neustart nicht genau-einmalig.");
            var afterAckLoss = restartedStore.CommitIncoming(peer, message, runtimeNow + 3001, (_, _) => null, deferAcceptance: true);
            TestAssert.That(afterAckLoss.Status == "duplicate" && !afterAckLoss.Process,
                "ACK-Verlust führte nach durablem Commit zu erneutem Web-Apply.");
            var malformed = Message("personal_sync.batch", new JsonObject(), runtimeNow + 3000, runtimeNow + 40_000,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
            var rejected = restartedStore.CommitIncoming(peer, malformed, runtimeNow + 3000, (_, _) => null, deferAcceptance: true);
            var rejectedAgain = restartedStore.CommitIncoming(peer, malformed, runtimeNow + 3001, (_, _) => null, deferAcceptance: true);
            TestAssert.That(rejected.Status == "rejected" && rejected.Error == "invalid_schema" &&
                rejectedAgain.Status == "rejected" && rejectedAgain.Error == "invalid_schema",
                "Ungültiges Personal-Sync-Schema wurde nicht deterministisch dedupliziert.");
            var decisionBody = new JsonObject { ["format"] = 1, ["run_id"] = run, ["decision_id"] = "77777777-7777-4777-8777-777777777777", ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = deletion["proposal_id"]!.GetValue<string>(), ["decision"] = "restore", ["expected_clock"] = deletion["clock"]!.DeepClone() }) };
            var decisionMessage = Message("personal_sync.deletion_decision", decisionBody, runtimeNow + 3000, runtimeNow + 40_000, "88888888-8888-4888-8888-888888888888");
            _ = restartedStore.CommitIncoming(peer, decisionMessage, runtimeNow + 3000, (_, _) => null, deferAcceptance: true);
            var decision = restarted.StageDecisionIntent(peer, decisionMessage, "wifi", runtimeNow + 3000);
            var afterCrash = new PersonalSyncStore(new TelefonStore(new WindowsPaths(tempRoot), key)).DecisionIntents(runtimeNow + 3001).Single();
            TestAssert.That(afterCrash.CommitToken == decision.CommitToken && afterCrash.Body["decisions"]![0]!["expected_clock"]!.ToJsonString() == deletion["clock"]!.ToJsonString(), "Crash-durabler Entscheidungsintent verlor die exakte expected_clock.");
            TestAssert.That(!restarted.CommitDecisionIntent(peer, decision.PendingMessageId, decision.CommitToken, "temporary", runtimeNow + 3002),
                "Temporärer Löschfehler wurde terminal abgeschlossen.");
            var temporaryRestartStore = new TelefonStore(new WindowsPaths(tempRoot), key); var temporaryRestart = new PersonalSyncStore(temporaryRestartStore);
            var temporaryReplayAck = temporaryRestartStore.CommitIncoming(peer, decisionMessage, runtimeNow + 3003, (_, _) => null, deferAcceptance: true);
            var temporaryIntent = temporaryRestart.StageDecisionIntent(peer, decisionMessage, "wifi", runtimeNow + 3003);
            TestAssert.That(temporaryReplayAck.Process && temporaryIntent.PendingMessageId == decision.PendingMessageId && temporaryIntent.CommitToken == decision.CommitToken &&
                JsonNode.DeepEquals(temporaryIntent.Body, decision.Body), "Temporärer Löschfehler verlor beim Neustart die durable Entscheidungsidentität.");
            var outgoingDecisionId = temporaryRestartStore.Enqueue(peer, "personal_sync.deletion_decision", decisionBody, 30_000, runtimeNow + 3004, "wifi_only");
            var outgoingDecision = temporaryRestartStore.OutboxMessage(peer, outgoingDecisionId)!.DeepClone();
            TestAssert.That(temporaryRestartStore.AcknowledgePersonalOutbox(peer, outgoingDecisionId, "rejected", "temporary_failure", runtimeNow + 3005),
                "Retryable Lösch-ACK wurde nicht erkannt.");
            var outgoingRestart = new TelefonStore(new WindowsPaths(tempRoot), key);
            TestAssert.That(JsonNode.DeepEquals(outgoingRestart.OutboxMessage(peer, outgoingDecisionId), outgoingDecision),
                "Retryable Lösch-ACK verlor nach Neustart Nachrichtenidentität oder Payload.");
            TestAssert.That(outgoingRestart.AcknowledgePersonalOutbox(peer, outgoingDecisionId, "rejected", "permanent_failure", runtimeNow + 3006) &&
                new TelefonStore(new WindowsPaths(tempRoot), key).OutboxMessage(peer, outgoingDecisionId) is null,
                "Terminaler Lösch-ACK blieb nach Neustart retryable.");
            TestAssert.That(restarted.CommitDecisionIntent(peer, decision.PendingMessageId, decision.CommitToken, "restore_unavailable", runtimeNow + 3006) && restarted.DecisionIntents(runtimeNow + 3006).Count == 0,
                "Terminaler Restore-Fehler wurde nicht atomar abgeschlossen.");
            var terminalReplay = new TelefonStore(new WindowsPaths(tempRoot), key).CommitIncoming(peer, decisionMessage, runtimeNow + 3007, (_, _) => null, deferAcceptance: true);
            TestAssert.That(terminalReplay.Status == "rejected" && terminalReplay.Error == "restore_unavailable" && !terminalReplay.Process,
                "Terminaler Löschfehler wurde nach Neustart erneut angewandt oder abgefragt.");
            var timeoutBody = decisionBody.DeepClone().AsObject(); timeoutBody["decision_id"] = "99999999-7777-4777-8777-777777777777";
            var timeoutMessage = Message("personal_sync.deletion_decision", timeoutBody, runtimeNow + 3008, runtimeNow + 40_000, "99999999-8888-4888-8888-888888888888");
            _ = restartedStore.CommitIncoming(peer, timeoutMessage, runtimeNow + 3008, (_, _) => null, deferAcceptance: true);
            var timeoutIntent = restarted.StageDecisionIntent(peer, timeoutMessage, "wifi", runtimeNow + 3008);
            TestAssert.That(!restarted.CommitDecisionIntent(peer, timeoutIntent.PendingMessageId, timeoutIntent.CommitToken, "temporary", runtimeNow + 3009) &&
                restarted.DecisionIntents(runtimeNow + 3010).Any(item => item.CommitToken == timeoutIntent.CommitToken),
                "Ein interner Timeout entfernte den retrybaren Löschentscheidungsintent.");
            var terminalOutcomes = new[] { (Outcome: "conflict", Error: "conflict"), (Outcome: "invalid", Error: "invalid_schema") };
            for (var index = 0; index < terminalOutcomes.Length; index++)
            {
                var terminalBody = decisionBody.DeepClone().AsObject(); terminalBody["decision_id"] = $"{index + 1:D8}-7777-4777-8777-777777777777";
                var terminalMessage = Message("personal_sync.deletion_decision", terminalBody, runtimeNow + 3010 + index, runtimeNow + 40_000, $"{index + 1:D8}-8888-4888-8888-888888888888");
                _ = restartedStore.CommitIncoming(peer, terminalMessage, runtimeNow + 3010 + index, (_, _) => null, deferAcceptance: true);
                var terminalIntent = restarted.StageDecisionIntent(peer, terminalMessage, "wifi", runtimeNow + 3010 + index);
                TestAssert.That(restarted.CommitDecisionIntent(peer, terminalIntent.PendingMessageId, terminalIntent.CommitToken, terminalOutcomes[index].Outcome, runtimeNow + 3020 + index), "Terminaler Löschfehler wurde nicht gespeichert.");
                var repeated = new TelefonStore(new WindowsPaths(tempRoot), key).CommitIncoming(peer, terminalMessage, runtimeNow + 3030 + index, (_, _) => null, deferAcceptance: true);
                TestAssert.That(repeated.Status == "rejected" && repeated.Error == terminalOutcomes[index].Error && !repeated.Process, "Terminaler Löschfehler wurde nach Neustart wiederholt.");
            }
            var descriptor = format2["descriptor"]!.AsObject(); restarted.StageAttachment(peer, run, false, format2["sha256"]!.GetValue<string>(), descriptor, "incoming", "wifi_only", runtimeNow + 40_000, new[] { (0, decoded.Data) });
            var attachmentRestart = new PersonalSyncStore(new TelefonStore(new WindowsPaths(tempRoot), key));
            TestAssert.Throws<InvalidDataException>(() => attachmentRestart.ReadVerifiedAttachment(peer, run, false, format2["sha256"]!.GetValue<string>(), descriptor["sha256"]!.GetValue<string>(), "incoming", "bluetooth", runtimeNow + 4000), "wifi_only-Attachment wurde über Bluetooth gelesen.");
            TestAssert.That(attachmentRestart.ReadVerifiedAttachment(peer, run, false, format2["sha256"]!.GetValue<string>(), descriptor["sha256"]!.GetValue<string>(), "incoming", "wifi", runtimeNow + 4000).SequenceEqual(decoded.Data), "Attachment-Resume nach Neustart verlor authentisierte Chunks.");

            const string format2Run = "34343434-3434-4434-8434-343434343434";
            var format2Request = new JsonObject { ["format"] = 2, ["run_id"] = format2Run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
            restarted.RememberRun(peer, format2Request, runtimeNow + 4100, runtimeNow + 40_000);
            var format2Record = Record("note", "note-format-2", format2Value, 2); var format2Batch = Batch(format2Run, format2Record, 2);
            var format2Message = Message("personal_sync.batch", format2Batch, runtimeNow + 4200, runtimeNow + 40_000, "45454545-4545-4545-8545-454545454545");
            _ = restartedStore.CommitIncoming(peer, format2Message, runtimeNow + 4200, (_, _) => null, deferAcceptance: true);
            var pendingFormat2 = restarted.StageBatch(peer, format2Message, "wifi", runtimeNow + 4200)!;
            restarted.StageAttachment(peer, format2Run, false, pendingFormat2.RecordsHash, descriptor, "incoming", "any", runtimeNow + 40_000, []);
            TestAssert.That(restarted.MissingAttachmentRanges(peer, format2Run, false, pendingFormat2.RecordsHash, descriptor["sha256"]!.GetValue<string>(), "incoming", runtimeNow + 4201).SequenceEqual(new[] { (0, 1) }),
                "Format-2-Empfänger forderte nicht exakt die fehlenden Bereiche nach dem Batch an.");
            var resumedFormat2 = new PersonalSyncStore(new TelefonStore(new WindowsPaths(tempRoot), key));
            TestAssert.That(resumedFormat2.ReadyBatches(runtimeNow + 4202).Any(batch => batch.RunId == format2Run && batch.RecordsHash == pendingFormat2.RecordsHash),
                "Pending Format-2-Batch wurde nach Neustart nicht fortgesetzt.");
            resumedFormat2.StageAttachmentChunk(peer, format2Run, false, pendingFormat2.RecordsHash, descriptor["sha256"]!.GetValue<string>(), "incoming", 0, decoded.Data, runtimeNow + 40_000);
            TestAssert.That(resumedFormat2.ReadVerifiedAttachment(peer, format2Run, false, pendingFormat2.RecordsHash, descriptor["sha256"]!.GetValue<string>(), "incoming", "wifi", runtimeNow + 4203).SequenceEqual(decoded.Data),
                "Angeforderter Android/Linux-Chunk wurde nicht durable verifiziert.");

            const string expiryRun = "56565656-5656-4656-8656-565656565656"; var expiryAt = runtimeNow + 10_000;
            var expiryRequest = new JsonObject { ["format"] = 2, ["run_id"] = expiryRun, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
            resumedFormat2.RememberRun(peer, expiryRequest, runtimeNow + 4300, expiryAt);
            var expiryRecord = Record("note", "note-expiry", format2Value, 2); var expiryBatch = Batch(expiryRun, expiryRecord, 2);
            var recordsHash = expiryBatch["records_hash"]!.GetValue<string>(); var attachmentHash = descriptor["sha256"]!.GetValue<string>();
            var queuedBatch = restartedStore.Enqueue(peer, "personal_sync.batch", expiryBatch, 86_400_000, runtimeNow + 4400);
            var queuedChunk = restartedStore.Enqueue(peer, "personal_sync.attachment_chunk", new JsonObject { ["format"] = 2, ["run_id"] = expiryRun, ["reply"] = false, ["records_hash"] = recordsHash, ["sha256"] = attachmentHash, ["index"] = 0, ["data"] = Convert.ToBase64String(decoded.Data) }, 86_400_000, runtimeNow + 4401);
            var queuedResult = restartedStore.Enqueue(peer, "personal_sync.attachment_result", new JsonObject { ["format"] = 2, ["run_id"] = expiryRun, ["reply"] = false, ["records_hash"] = recordsHash, ["sha256"] = attachmentHash, ["state"] = "complete", ["error"] = "none" }, 86_400_000, runtimeNow + 4402);
            resumedFormat2.StageAttachment(peer, expiryRun, false, recordsHash, descriptor, "outgoing", "any", expiryAt, []);
            var beforeExpiry = new TelefonStore(new WindowsPaths(tempRoot), key);
            TestAssert.That(new[] { queuedBatch, queuedChunk, queuedResult }.All(id => beforeExpiry.Due(peer, runtimeNow + 4500).Any(item => item.Id == id)), "Aktive Personal-Nachrichten wurden vor Laufablauf verworfen.");
            TestAssert.That(beforeExpiry.Due(peer, expiryAt + 1).All(item => item.Message["body"]?["run_id"]?.GetValue<string>() != expiryRun), "Abgelaufene Batch-/Chunk-/Result-Nachricht wurde noch gesendet.");
            var afterExpiryRestart = new TelefonStore(new WindowsPaths(tempRoot), key);
            TestAssert.That(new[] { queuedBatch, queuedChunk, queuedResult }.All(id => afterExpiryRestart.OutboxMessage(peer, id) is null) && CountRunStaging(afterExpiryRestart, peer, expiryRun) == 0,
                "Abgelaufene Batch-/Chunk-/Result-Queue oder Staging wurde nach Neustart erneut versucht.");

            foreach (var failure in new[] { "expired", "missing", "tampered" })
            {
                var prefix = failure == "expired" ? "67676767" : failure == "missing" ? "78787878" : "89898989";
                var ackRun = $"{prefix}-{prefix[0..4]}-4{prefix[1..4]}-8{prefix[1..4]}-{prefix}{prefix[0..4]}";
                var ackRequest = new JsonObject { ["format"] = 1, ["run_id"] = ackRun, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
                var ackNow = runtimeNow + 11_000; var ackExpiry = ackNow + 1000; var ackPersonal = new PersonalSyncStore(afterExpiryRestart);
                ackPersonal.RememberRun(peer, ackRequest, ackNow, ackExpiry);
                var ackId = afterExpiryRestart.Enqueue(peer, "personal_sync.batch", Batch(ackRun, Record("note", "note-ack-" + failure, value)), 86_400_000, ackNow);
                if (failure != "expired")
                {
                    using var database = afterExpiryRestart.OpenDatabase(); database.Open(); using var alter = database.CreateCommand();
                    alter.CommandText = failure == "missing" ? "DELETE FROM meta WHERE key=$key" : "UPDATE meta SET value=zeroblob(length(value)) WHERE key=$key";
                    alter.Parameters.AddWithValue("$key", $"personal_run:{peer}:{ackRun}"); alter.ExecuteNonQuery();
                }
                TestAssert.That(afterExpiryRestart.CompletePersonalOutbox(peer, ackId, failure == "expired" ? ackExpiry + 1 : ackNow + 1), $"{failure}-ACK wurde nicht terminal abgeschlossen.");
                var ackRestart = new TelefonStore(new WindowsPaths(tempRoot), key);
                TestAssert.That(ackRestart.OutboxMessage(peer, ackId) is null && ackRestart.Due(peer, ackExpiry + 2).All(item => item.Id != ackId), $"{failure}-ACK wurde nach Neustart erneut übertragen.");
            }
            using (var database = restartedStore.OpenDatabase())
            {
                database.Open(); using var tamper = database.CreateCommand();
                tamper.CommandText = "UPDATE personal_attachment_chunk SET payload=zeroblob(length(payload)) WHERE peer_id=$peer";
                tamper.Parameters.AddWithValue("$peer", peer); tamper.ExecuteNonQuery();
            }
            TestAssert.Throws<System.Security.Cryptography.CryptographicException>(() => attachmentRestart.ReadVerifiedAttachment(peer, run, false,
                format2["sha256"]!.GetValue<string>(), descriptor["sha256"]!.GetValue<string>(), "incoming", "wifi", runtimeNow + 4000),
                "Manipulierter verschlüsselter Attachment-Chunk wurde angenommen.");

            const string taskRun = "12121212-1212-4212-8212-121212121212";
            var taskRequest = new JsonObject { ["format"] = 1, ["run_id"] = taskRun, ["trigger"] = "manual", ["modules"] = new JsonArray("tasks") };
            restarted.RememberRun(peer, taskRequest, runtimeNow + 5000, runtimeNow + 45_000);
            restarted.PurgeModules(peer, new HashSet<string>(StringComparer.Ordinal) { "notes" });
            TestAssert.That(restarted.LoadRun(peer, run, runtimeNow + 5000) is null && restarted.LoadRun(peer, taskRun, runtimeNow + 5000) is not null,
                "Modulwiderruf löschte unabhängige Personal-Sync-Läufe nicht selektiv.");

            restartedStore.Cleanup(runtimeNow + 40_001); restarted.CleanupExpiredRuns(runtimeNow + 40_001);
            using (var database = restartedStore.OpenDatabase())
            {
                database.Open(); using var count = database.CreateCommand();
                count.CommandText = "SELECT (SELECT COUNT(*) FROM personal_attachment_transfer)+(SELECT COUNT(*) FROM personal_attachment_chunk)+(SELECT COUNT(*) FROM personal_domain)";
                TestAssert.That(Convert.ToInt64(count.ExecuteScalar()) == 0, "Abgelaufene Personal-Sync-Stagingdaten wurden nicht begrenzt bereinigt.");
            }
            TestAssert.That(restarted.LoadRun(peer, format2Run, runtimeNow + 40_001) is null, "Abgelaufene personal_run-Metadaten wurden nicht bereinigt.");
            var expiredDuplicate = restartedStore.CommitIncoming(peer, format2Message, runtimeNow + 40_002, (_, _) => "expired", deferAcceptance: true, reauthorizeDuplicates: true);
            TestAssert.That(expiredDuplicate.Status == "rejected" && expiredDuplicate.Error == "expired" && !expiredDuplicate.Process,
                "Abgelaufener Personal-Sync-Lauf durfte einen durable Inbox-Eintrag erneut anwenden.");
            _ = new TelefonStore(new WindowsPaths(tempRoot), key);

            var oversized = descriptor.DeepClone().AsObject(); oversized["size"] = PersonalSyncStore.MaximumAttachmentBytes + 1;
            TestAssert.Throws<InvalidDataException>(() => restarted.StageAttachment(peer, taskRun, false, format2["sha256"]!.GetValue<string>(), oversized, "incoming", "any", runtimeNow + 80_000, []),
                "Attachment über 8 MiB wurde staged.");
            for (var index = 0; index < 4; index++)
            {
                var quotaRun = $"{index + 1:D8}-1234-4234-8234-123456789abc";
                restarted.RememberRun(peer, new JsonObject { ["format"] = 1, ["run_id"] = quotaRun, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") }, runtimeNow + 6000, runtimeNow + 80_000);
                restarted.StageAttachment(peer, quotaRun, false, format2["sha256"]!.GetValue<string>(), descriptor, "incoming", "any", runtimeNow + 80_000, []);
            }
            const string fifthRun = "00000005-1234-4234-8234-123456789abc";
            restarted.RememberRun(peer, new JsonObject { ["format"] = 1, ["run_id"] = fifthRun, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") }, runtimeNow + 6000, runtimeNow + 80_000);
            TestAssert.Throws<InvalidDataException>(() => restarted.StageAttachment(peer, fifthRun, false, format2["sha256"]!.GetValue<string>(), descriptor, "incoming", "any", runtimeNow + 80_000, []),
                "Mehr als vier aktive Attachment-Transfers pro Peer wurden staged.");
            restartedStore.Cleanup(runtimeNow + 80_001);
            using (var database = restartedStore.OpenDatabase()) { database.Open(); using var count = database.CreateCommand(); count.CommandText = "SELECT COUNT(*) FROM personal_attachment_transfer"; TestAssert.That(Convert.ToInt64(count.ExecuteScalar()) == 0, "Attachment-Quoten wurden nach Ablauf/Neustart nicht freigegeben."); }
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(tempRoot)) Directory.Delete(tempRoot, true);
        }
    }

    private static JsonObject Record(string kind, string id, JsonObject value, int format = 1) => new()
    { ["kind"] = kind, ["id"] = id, ["state"] = "live", ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = "11111111-1111-4111-8111-111111111111", ["counter"] = 1 }), ["hash"] = PersonalSyncContract.ProjectionHash(value), ["modified_ms"] = TelefonProtocolContract.Integer(value["modified_ms"]), ["value"] = value.DeepClone() };
    private static JsonObject Batch(string run, JsonObject record, int format = 1)
    {
        var body = new JsonObject { ["format"] = format, ["run_id"] = run, ["batch_id"] = "99999999-9999-4999-8999-999999999999", ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records"] = new JsonArray(record) };
        if (format >= 2) body["records_hash"] = PersonalSyncContract.RecordsHash(new JsonArray(record.DeepClone()));
        return body;
    }
    private static JsonObject Message(string kind, JsonObject body, long created, long expires, string id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") => new()
    { ["type"] = "message", ["v"] = 1, ["message_id"] = id, ["kind"] = kind, ["created_ms"] = created, ["expires_ms"] = expires, ["body"] = body };
    private static long CountRunStaging(TelefonStore store, string peer, string run)
    {
        using var database = store.OpenDatabase(); database.Open(); using var count = database.CreateCommand();
        count.CommandText = "SELECT (SELECT COUNT(*) FROM personal_batch WHERE peer_id=$peer AND run_id=$run)+(SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run)+(SELECT COUNT(*) FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run)";
        count.Parameters.AddWithValue("$peer", peer); count.Parameters.AddWithValue("$run", run); return Convert.ToInt64(count.ExecuteScalar());
    }

    private static async Task TestNegotiatedRoundtripAndFullChunks(string root, JsonObject task3Value)
    {
        var paths = new WindowsPaths(root); var key = Enumerable.Repeat((byte)73, 32).ToArray();
        var store = new TelefonStore(paths, key); var personal = new PersonalSyncStore(store);
        const string peer = "34343434-3434-4434-8434-343434343434";
        var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
        store.SavePeers([new TelefonPeer(peer, "Synthetic", TelefonCrypto.GenerateX25519().Public,
            StoredCapabilities: capabilities, StoredGrants: new JsonObject { ["personal_tasks_sync"] = true, ["personal_notes_sync"] = true })]);
        store.SetLocalGrant("personal_tasks_sync", true); store.SetLocalGrant("personal_notes_sync", true);
        store.SetPersonalSettings(peer, ownDevice: true, remoteOwnDevice: true);
        var emitted = new List<JsonObject>();
        Task Emit(string name, object payload) { if (name == "App.telefonPersonalSync") emitted.Add(System.Text.Json.JsonSerializer.SerializeToNode(payload)!.AsObject()); return Task.CompletedTask; }
        foreach (var format in new[] { 1, 2, 3 })
        {
            var run = Guid.NewGuid().ToString(); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var request = new JsonObject { ["format"] = format, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = format == 3 ? new JsonArray("notes", "tasks") : new JsonArray("tasks") };
            using (var sender = new TelefonCoordinator(paths, Emit, dataStore: store))
                await sender.SendPersonalSyncAsync(peer, "personal_sync.request", request);
            var value = task3Value.DeepClone().AsObject();
            if (format != 3) { value.Remove("uid"); value.Remove("parent_uid"); value.Remove("order"); }
            var body = Batch(run, Record("task", "task-1", value, format), format); body["batch_id"] = Guid.NewGuid().ToString();
            if (format == 3)
            {
                body["records"]!.AsArray().Insert(0, Record("note", "note-1", new JsonObject { ["title"] = "Note", ["text"] = "Text", ["html"] = "", ["notebook_id"] = "book",
                    ["symbol"] = "note", ["created_ms"] = 1, ["modified_ms"] = 2, ["attachments"] = new JsonArray() }, 3));
                body["records_hash"] = PersonalSyncContract.RecordsHash(body["records"]!.AsArray());
            }
            var message = Message("personal_sync.batch", body, now, now + 60_000, Guid.NewGuid().ToString());
            store.CommitIncoming(peer, message, now, (_, _) => null, deferAcceptance: true);
            var staged = personal.StageBatch(peer, message, "wifi", now)!;
            var restartedStore = new TelefonStore(paths, key);
            var replay = new PersonalSyncStore(restartedStore).ReadyBatches(now + 1).Single(item => item.RunId == run);
            TestAssert.That(replay.Format == format && JsonNode.DeepEquals(replay.Records, staged.Records), "Restart changed the negotiated batch format or hierarchy.");
            using var receiver = new TelefonCoordinator(paths, Emit, dataStore: restartedStore);
            await receiver.ReplayPersonalSyncAsync();
            var delivered = emitted.Last()["body"]!.AsObject();
            TestAssert.That(delivered["format"]!.GetValue<int>() == format &&
                JsonNode.DeepEquals(delivered["records"]!.AsArray().OfType<JsonObject>().Single(item => item["kind"]!.GetValue<string>() == "task")["value"], value), "Coordinator aggregate omitted format or task graph fields.");
            var reply = body.DeepClone().AsObject(); reply["reply"] = true; reply["batch_id"] = Guid.NewGuid().ToString();
            var outgoing = await receiver.SendPersonalSyncAsync(peer, "personal_sync.batch", reply);
            TestAssert.That(restartedStore.OutboxMessage(peer, outgoing)?["body"]?["format"]?.GetValue<int>() == format,
                "Reply did not retain the existing negotiated run format.");
            if (format == 3)
            {
                var downgraded = Batch(run, Record("task", "task-1", new JsonObject { ["title"] = "Task", ["note"] = "", ["due"] = "", ["priority"] = 2,
                    ["completed"] = false, ["remind"] = false, ["lead_days"] = 0, ["reminder_minute"] = 0, ["created_ms"] = 1, ["modified_ms"] = 2 }, 2), 2);
                await TestAssert.ThrowsAsync<InvalidDataException>(async () => { _ = await receiver.SendPersonalSyncAsync(peer, "personal_sync.batch", downgraded); }, "A format-3 run accepted a downgraded reply.");
                TestAssert.Throws<InvalidDataException>(() => personal.StageBatch(peer, Message("personal_sync.batch", downgraded, now, now + 60_000, Guid.NewGuid().ToString()), "wifi", now),
                    "A format-3 run staged a downgraded incoming batch.");
            }
            TestAssert.That(receiver.CommitPersonalSync(peer, replay.PendingMessageId, replay.CommitToken, "applied"), "Negotiated batch could not be committed after replay.");
        }
        var chunkRun = Guid.NewGuid().ToString(); var instant = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        personal.RememberRun(peer, new JsonObject { ["format"] = 3, ["run_id"] = chunkRun, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") }, instant);
        var bytes = new byte[PersonalSyncContract.ChunkRaw + 1]; new byte[] { 0x89, 0x50, 0x4e, 0x47, 13, 10, 26, 10 }.CopyTo(bytes, 0); bytes[^1] = 77;
        var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
        var recordsHash = new string('a', 64);
        var descriptor = new JsonObject { ["attachment_id"] = "full", ["name"] = "full.png", ["kind"] = "image", ["mime"] = "image/png", ["size"] = bytes.Length, ["sha256"] = hash };
        var chunk = new JsonObject { ["format"] = 2, ["run_id"] = chunkRun, ["reply"] = false, ["records_hash"] = recordsHash,
            ["sha256"] = hash, ["index"] = 0, ["data"] = Convert.ToBase64String(bytes, 0, PersonalSyncContract.ChunkRaw) };
        PersonalSyncContract.ValidateBody("personal_sync.attachment_chunk", chunk);
        TelefonMessageContract.ValidateMessage(Message("personal_sync.attachment_chunk", chunk, instant, instant + 60_000), instant, true);
        TestAssert.That(PersonalSyncContract.ChunkRaw == 180000 && PersonalSyncContract.MaxChunkBody == 256 * 1024 && TelefonCrypto.Canonical(chunk).Length > 192 * 1024 &&
            TelefonCrypto.Canonical(chunk).Length <= PersonalSyncContract.MaxChunkBody, "Full raw blocks do not fit the agreed bounded chunk body.");
        personal.StageAttachment(peer, chunkRun, false, recordsHash, descriptor, "incoming", "any", instant + 60_000,
            [(0, bytes[..PersonalSyncContract.ChunkRaw])]);
        var resumedChunks = new PersonalSyncStore(new TelefonStore(paths, key));
        TestAssert.That(resumedChunks.MissingAttachmentRanges(peer, chunkRun, false, recordsHash, hash, "incoming", instant).SequenceEqual(new[] { (1, 2) }), "Persisted raw chunk offsets changed.");
        resumedChunks.StageAttachmentChunk(peer, chunkRun, false, recordsHash, hash, "incoming", 1, [bytes[^1]], instant + 60_000);
        TestAssert.That(resumedChunks.ReadVerifiedAttachment(peer, chunkRun, false, recordsHash, hash, "incoming", "wifi", instant).SequenceEqual(bytes), "Full chunk and final byte did not resume exactly.");
        chunk["data"] = Convert.ToBase64String(bytes);
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.attachment_chunk", chunk), "Larger body allowance changed the persisted raw-block limit.");
    }
}
