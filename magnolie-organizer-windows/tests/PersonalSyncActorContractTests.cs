using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorContractTests
{
    internal static Task RunAsync()
    {
        var root = TestSource.Root("magnolie-notes/app/src/test/resources/notes-actor-start.json");
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "magnolie-notes/app/src/test/resources/notes-actor-start.json")))!["cases"]!.AsArray();
        foreach (var item in vectors.OfType<JsonObject>())
        {
            var accepted = false;
            try { PersonalSyncActorContract.ValidateStart(item["body"]!.AsObject()); accepted = true; } catch (InvalidDataException) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor-start contract drift: " + item["name"]);
        }
        var dataFixture = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "magnolie-notes/app/src/test/resources/notes-actor-data.json")))!.AsObject();
        var dataVectors = dataFixture["cases"]!.AsArray();
        foreach (var item in dataVectors.OfType<JsonObject>())
        {
            var value = item["body"]!.AsObject(); var accepted = false;
            try { PersonalSyncActorContract.ValidateData(value); accepted = true; } catch (InvalidDataException) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor-data contract drift: " + item["name"]);
            if (!accepted) continue;
            TestAssert.That(JsonNode.DeepEquals(PersonalSyncActorContract.Wrap(value["run_id"]!.GetValue<string>(), value["kind"]!.GetValue<string>(), value["body"]!.AsObject()), value), "Actor wrap changed existing record/schema content.");
            var unwrapped = PersonalSyncActorContract.Unwrap(value);
            TestAssert.That(unwrapped.Kind == value["kind"]!.GetValue<string>() && JsonNode.DeepEquals(unwrapped.Body, value["body"]), "Actor unwrap lost original scoped/legacy body.");
            unwrapped.Body["owned_mutation"] = true;
            TestAssert.That(value["body"]!["owned_mutation"] is null, "Unwrapped data aliased the stored actor envelope.");
        }
        var ackVectors = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "magnolie-notes/app/src/test/resources/notes-actor-ack.json")))!["cases"]!.AsArray();
        foreach (var item in ackVectors.OfType<JsonObject>())
        {
            var body = item["body"]!.AsObject(); var accepted = false;
            try { PersonalSyncActorContract.ValidateAck(body); accepted = true; } catch (InvalidDataException) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor acknowledgement drift: " + item["name"]);
            if (!accepted) continue;
            TestAssert.That(JsonNode.DeepEquals(body, PersonalSyncActorContract.Ack(body["run_id"]!.GetValue<string>(), body["message_id"]!.GetValue<string>(), body["status"]!.GetValue<string>(), body["error"]!.GetValue<string>())), "Actor acknowledgement factory changed its identity/status.");
            TestAssert.That(PersonalSyncActorContract.IsReservedMessage(new JsonObject { ["type"] = "message", ["kind"] = PersonalSyncActorContract.AckKind, ["body"] = body.DeepClone() }), "Actor ACK lost its reserved wire identity.");
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.Wrap(body["run_id"]!.GetValue<string>(), PersonalSyncActorContract.AckKind, body), "An actor ACK could be laundered as nested actor data.");
        }
        CheckWireBudget(dataFixture["wire_budget"]!.AsObject());
        var values = new JsonObject();
        foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" })
            values[name] = new JsonObject { ["available"] = true, ["versions"] = new JsonArray(9, 12) };
        TestAssert.That(PersonalSyncActorContract.Supported(values, values), "Actor/shared markers were not recognized.");
        foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) foreach (var version in new[] { 9, 12 })
        {
            var missing = values.DeepClone().AsObject(); missing[name]!["versions"] = new JsonArray(version);
            TestAssert.That(!PersonalSyncActorContract.Supported(values, missing) && !PersonalSyncActorContract.Supported(missing, values), "A one-sided/incomplete actor contract was accepted.");
        }
        return Task.CompletedTask;
    }

    private static void CheckWireBudget(JsonObject fixture)
    {
        const string run = "11111111-1111-4111-8111-111111111111";
        JsonObject Record(string id, int length)
        {
            var value = fixture["value"]!.DeepClone().AsObject(); value["text"] = new string('A', length);
            return new JsonObject { ["kind"] = "note", ["id"] = id, ["state"] = "live", ["modified_ms"] = 0,
                ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = run, ["counter"] = 1 }), ["hash"] = PersonalSyncContract.ProjectionHash(value), ["value"] = value };
        }
        var records = new JsonArray(Record("note-a", 128 * 1024), Record("note-b", 0));
        var body = new JsonObject { ["format"] = 1, ["run_id"] = run, ["batch_id"] = "33333333-3333-4333-8333-333333333333",
            ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records"] = records };
        var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = "22222222-2222-4222-8222-222222222222", ["kind"] = "personal_sync.batch",
            ["created_ms"] = 1700000000000L, ["expires_ms"] = 1700000060000L, ["body"] = body };
        var target = fixture["portable_body_bytes"]!.GetValue<int>(); records[1] = Record("note-b", target - TelefonCrypto.Canonical(body).Length);
        TestAssert.That(TelefonCrypto.Canonical(body).Length == target, "Boundary fixture did not reach its exact valid original batch size.");
        TelefonMessageContract.ValidateMessage(message, 1700000000000L, false);
        var envelope = PersonalSyncActorContract.Wrap(run, "personal_sync.batch", body);
        TestAssert.That(TelefonCrypto.Canonical(envelope).Length <= PersonalSyncContract.MaxChunkBody, "Boundary actor body itself was oversized.");
        var wrapped = message.DeepClone().AsObject(); wrapped["kind"] = PersonalSyncActorContract.DataKind; wrapped["body"] = envelope;
        TestAssert.That(TelefonCrypto.Canonical(wrapped).Length > 192 * 1024 && TelefonCrypto.Canonical(wrapped).Length <= PersonalSyncContract.MaxChunkBody,
            "Actor overhead was incorrectly charged against the existing inner-batch budget.");
        TestAssert.That(JsonNode.DeepEquals(wrapped, PersonalSyncActorContract.WireMessage(message, run)), "A valid portable batch did not retain its complete bounded actor frame.");
    }
}
