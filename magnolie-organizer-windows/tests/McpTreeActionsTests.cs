using System.Text.Json.Nodes;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpTreeActionsTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-mcp-tree-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var emitted = new List<string>();
            using var tree = new MagnolienbaumCoordinator(new WindowsPaths(root), (callback, _) => { emitted.Add(callback); return Task.CompletedTask; });
            var initial = await tree.ExecuteMcpAsync(new() { ["action"] = "read" }, default);
            TestAssert.That(initial["ok"]!.GetValue<bool>(), "Native tree metadata read failed.");
            var status = initial["status"]!.AsObject();
            var revision = status["revision"]!.GetValue<string>();
            TestAssert.That(revision.Length == 64 && !status.ContainsKey("eingang") && !status.ContainsKey("privat") && !status.ContainsKey("oeffentlich"),
                "Tree MCP status exposed private keys or unbounded inbox content.");
            TestAssert.That(emitted.Count == 0, "Tree MCP read emitted a GUI callback.");
            var stale = await tree.ExecuteMcpAsync(new() { ["action"] = "settings", ["enabled"] = false, ["name"] = "Owned disabled tree", ["expectedRevision"] = new string('0', 64) }, default);
            TestAssert.That(stale["ok"]!.GetValue<bool>() == false && stale["code"]!.GetValue<string>() == "conflict", "Stale tree metadata revision was accepted.");
            var updated = await tree.ExecuteMcpAsync(new() { ["action"] = "settings", ["enabled"] = false, ["name"] = "Owned disabled tree", ["expectedRevision"] = revision }, default);
            TestAssert.That(updated["ok"]!.GetValue<bool>() && updated["localVerified"]!.GetValue<bool>() && updated["status"]!["name"]!.GetValue<string>() == "Owned disabled tree" &&
                updated["status"]!["an"]!.GetValue<bool>() == false && updated["status"]!["revision"]!.GetValue<string>() != revision,
                "Tree settings did not use and verify the actual native store transaction.");
            TestAssert.That(emitted.Count == 0, "Correlated tree settings modified the GUI.");
            var created = await tree.ExecuteMcpAsync(new() { ["action"] = "pairing_create", ["expectedRevision"] = updated["status"]!["revision"]!.GetValue<string>(),
                ["address"] = "127.0.0.1", ["port"] = 8737, ["path"] = Path.Combine(root, "owned.magnolie-paarung") }, default);
            TestAssert.That(created["ok"]!.GetValue<bool>() && created["localVerified"]!.GetValue<bool>() && created["document"] is JsonObject,
                "Tree pairing document did not use the real native invitation store.");
            MagnolienbaumPairing.ValidateFile(created["document"]!.AsObject(), DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            var file = created["file"]!.AsObject(); var actual = File.ReadAllBytes(file["path"]!.GetValue<string>());
            TestAssert.That(actual.Length == file["bytes"]!.GetValue<int>() && Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(actual)).ToLowerInvariant() == file["sha256"]!.GetValue<string>() &&
                JsonNode.DeepEquals(JsonNode.Parse(actual), created["document"]), "Pairing file receipt did not match actual persisted bytes/document.");
            var inspected = await tree.ExecuteMcpAsync(new() { ["action"] = "pairing_read_file", ["path"] = file["path"]!.GetValue<string>(), ["expectedRevision"] = created["status"]!["revision"]!.GetValue<string>() }, default);
            TestAssert.That(inspected["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(inspected["document"], created["document"]) && JsonNode.DeepEquals(inspected["file"], file) &&
                inspected["status"]!["revision"]!.GetValue<string>() == created["status"]!["revision"]!.GetValue<string>(), "Pairing file inspection changed control state or lost the actual document digest.");
            var staleFile = await tree.ExecuteMcpAsync(new() { ["action"] = "pairing_import_file", ["path"] = file["path"]!.GetValue<string>(), ["expectedFileSha256"] = new string('0', 64), ["expectedRevision"] = created["status"]!["revision"]!.GetValue<string>() }, default);
            TestAssert.That(!staleFile["ok"]!.GetValue<bool>() && staleFile["code"]!.GetValue<string>() == "conflict", "Stale pairing-file bytes reached the import transport.");
            var qr = await tree.ExecuteMcpAsync(new() { ["action"] = "pairing_create", ["expectedRevision"] = created["status"]!["revision"]!.GetValue<string>(), ["format"] = "qr_svg", ["address"] = "127.0.0.1", ["port"] = 8737 }, default);
            TestAssert.That(!qr["ok"]!.GetValue<bool>() && qr["code"]!.GetValue<string>() == "unsupported_feature" && tree.McpStatus()["revision"]!.GetValue<string>() == created["status"]!["revision"]!.GetValue<string>(), "Unsupported native QR output changed invitations or pretended success.");
            TestAssert.That(created["status"]!["revision"]!.GetValue<string>() != updated["status"]!["revision"]!.GetValue<string>(), "Creating an invitation did not advance its bound control state.");
            await tree.ReportStatusAsync();
            TestAssert.That(emitted.SequenceEqual(new[] { "App.baumStand" }), "The MCP capture swallowed later ordinary GUI status.");
            await PeerActionsAsync(Path.Combine(root, "peer-actions"));
            await OutboxAsync(Path.Combine(root, "outbox"));
        }
        finally { Directory.Delete(root, true); }
    }

    private sealed class OfflineHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.ServiceUnavailable));
    }
    private sealed class AddressHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent("203.0.113.77\n") });
    }

    private static async Task OutboxAsync(string root)
    {
        var paths = new WindowsPaths(root);
        var storage = new MagnolienbaumStore(paths);
        var state = storage.LoadOrCreate(); state["an"] = true;
        var remote = new MagnolienbaumStore(new WindowsPaths(Path.Combine(root, "remote"))).LoadOrCreate();
        var identity = new JsonObject();
        foreach (var key in new[] { "kennung", "name", "oeffentlich", "port" }) identity[key] = remote[key]!.DeepClone();
        var peer = MagnolienbaumPairing.AddPartner(state, identity, "127.0.0.1", true);
        storage.SaveState(state);
        using var tree = new MagnolienbaumCoordinator(paths, (_, _) => throw new InvalidOperationException("MCP send emitted GUI state."));
        var field = typeof(MagnolienbaumCoordinator).GetField("client", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        ((HttpClient)field.GetValue(tree)!).Dispose(); field.SetValue(tree, new HttpClient(new OfflineHandler()));
        var sent = await tree.ExecuteMcpAsync(new() { ["action"] = "send", ["expectedRevision"] = tree.McpStatus()["revision"]!.GetValue<string>(),
            ["peerId"] = peer["kennung"]!.GetValue<string>(), ["fingerprint"] = MagnolienbaumCrypto.Fingerprint(Convert.FromBase64String(peer["oeffentlich"]!.GetValue<string>())),
            ["kind"] = "aufgabe", ["content"] = new JsonObject { ["id"] = "owned-task", ["titel"] = "Owned 🌸 task" } }, default);
        TestAssert.That(sent["ok"]!.GetValue<bool>() && sent["queuedVerified"]!.GetValue<bool>() && !sent["deliveryConfirmed"]!.GetValue<bool>(), "Queue persistence was confused with offline delivery.");
        TestAssert.That(storage.LoadOutbox().OfType<JsonObject>().Single()["inhalt"]!["titel"]!.GetValue<string>() == "Owned 🌸 task", "Actual outbox readback lost the queued content.");
        ((HttpClient)field.GetValue(tree)!).Dispose(); field.SetValue(tree, new HttpClient(new AddressHandler()));
        var address = await tree.ExecuteMcpAsync(new() { ["action"] = "public_address", ["expectedRevision"] = tree.McpStatus()["revision"]!.GetValue<string>() }, default);
        TestAssert.That(address["ok"]!.GetValue<bool>() && address["publicAddress"]!.GetValue<string>() == "203.0.113.77", "Public-address MCP wrapper did not use the shared native address resolver.");
    }

    private static async Task PeerActionsAsync(string root)
    {
        var paths = new WindowsPaths(root);
        var storage = new MagnolienbaumStore(paths);
        var state = storage.LoadOrCreate();
        var remote = new MagnolienbaumStore(new WindowsPaths(Path.Combine(root, "remote"))).LoadOrCreate();
        var identity = new JsonObject();
        foreach (var key in new[] { "kennung", "name", "oeffentlich", "port" }) identity[key] = remote[key]!.DeepClone();
        var peer = MagnolienbaumPairing.AddPartner(state, identity, "127.0.0.1", true);
        storage.SaveState(state);
        storage.SaveInbox(new JsonArray(new JsonObject { ["id"] = "owned-message", ["von"] = "owned-peer", ["inhalt"] = new JsonObject { ["text"] = "Owned 🌸 é inbox" } }));
        using var tree = new MagnolienbaumCoordinator(paths, (_, _) => throw new InvalidOperationException("MCP operation emitted GUI state."));
        var fingerprint = MagnolienbaumCrypto.Fingerprint(Convert.FromBase64String(peer["oeffentlich"]!.GetValue<string>()));
        var id = peer["kennung"]!.GetValue<string>();
        var status = tree.McpStatus();
        var firstChunk = await tree.ExecuteMcpAsync(new() { ["action"] = "inbox_read", ["id"] = "owned-message", ["limit"] = 7 }, default);
        TestAssert.That(firstChunk["ok"]!.GetValue<bool>() && firstChunk["nextOffset"]!.GetValue<int>() == 7, "Native inbox chunking was not bounded.");
        var bytes = new List<byte>(Convert.FromBase64String(firstChunk["dataBase64"]!.GetValue<string>()));
        var nextOffset = firstChunk["nextOffset"]?.GetValue<int>();
        while (nextOffset is not null)
        {
            var chunk = await tree.ExecuteMcpAsync(new() { ["action"] = "inbox_read", ["id"] = "owned-message", ["offset"] = nextOffset.Value, ["limit"] = 7, ["expectedSha256"] = firstChunk["sha256"]!.GetValue<string>() }, default);
            TestAssert.That(chunk["ok"]!.GetValue<bool>(), "Native inbox continuation rejected its exact content revision.");
            bytes.AddRange(Convert.FromBase64String(chunk["dataBase64"]!.GetValue<string>())); nextOffset = chunk["nextOffset"]?.GetValue<int>();
        }
        TestAssert.That(JsonNode.Parse(Encoding.UTF8.GetString(bytes.ToArray()))!["inhalt"]!["text"]!.GetValue<string>() == "Owned 🌸 é inbox", "Native inbox UTF-8 chunks lost Unicode content.");
        var staleChunk = await tree.ExecuteMcpAsync(new() { ["action"] = "inbox_read", ["id"] = "owned-message", ["expectedSha256"] = new string('0', 64) }, default);
        TestAssert.That(!staleChunk["ok"]!.GetValue<bool>() && staleChunk["code"]!.GetValue<string>() == "conflict", "Native inbox content CAS was ignored.");
        var staleConsume = await tree.ExecuteMcpAsync(new() { ["action"] = "consume_inbox", ["id"] = "owned-message", ["expectedSha256"] = new string('0', 64), ["expectedRevision"] = status["revision"]!.GetValue<string>() }, default);
        TestAssert.That(!staleConsume["ok"]!.GetValue<bool>() && storage.LoadInbox().Count == 1, "Stale content consumption removed an inbox item.");
        var consumed = await tree.ExecuteMcpAsync(new() { ["action"] = "consume_inbox", ["id"] = "owned-message", ["expectedSha256"] = firstChunk["sha256"]!.GetValue<string>(), ["expectedRevision"] = status["revision"]!.GetValue<string>() }, default);
        TestAssert.That(consumed["ok"]!.GetValue<bool>() && consumed["localVerified"]!.GetValue<bool>() && storage.LoadInbox().Count == 0, "Content-checked native inbox removal was not persisted.");
        var wrong = await tree.ExecuteMcpAsync(new() { ["action"] = "remove", ["expectedRevision"] = status["revision"]!.GetValue<string>(), ["peerId"] = id, ["fingerprint"] = "wrong" }, default);
        TestAssert.That(wrong["ok"]!.GetValue<bool>() == false && wrong["code"]!.GetValue<string>() == "conflict", "Tree peer identity gate accepted a different fingerprint.");
        var changed = await tree.ExecuteMcpAsync(new() { ["action"] = "partner_settings", ["expectedRevision"] = status["revision"]!.GetValue<string>(), ["peerId"] = id,
            ["fingerprint"] = fingerprint, ["trusted"] = false, ["contacts"] = true, ["contactDeletions"] = false, ["remoteAddress"] = "", ["remotePort"] = 8737 }, default);
        TestAssert.That(changed["ok"]!.GetValue<bool>() && changed["localVerified"]!.GetValue<bool>(), "Actual native partner preferences were not verified.");
        var storedPeer = storage.LoadOrCreate()["partner"]!.AsArray().OfType<JsonObject>().Single();
        TestAssert.That(storedPeer["kontakte"]!.GetValue<bool>() && !storedPeer["vertraut"]!.GetValue<bool>(), "Partner preference receipt did not match disk state.");
        var removed = await tree.ExecuteMcpAsync(new() { ["action"] = "remove", ["expectedRevision"] = changed["status"]!["revision"]!.GetValue<string>(), ["peerId"] = id, ["fingerprint"] = fingerprint }, default);
        TestAssert.That(removed["ok"]!.GetValue<bool>() && removed["localVerified"]!.GetValue<bool>() && storage.LoadOrCreate()["partner"]!.AsArray().Count == 0,
            "Actual native peer removal did not persist or verify.");
    }
}
