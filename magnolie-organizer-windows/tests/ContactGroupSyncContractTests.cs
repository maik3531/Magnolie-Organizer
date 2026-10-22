using System.Text.Json.Nodes;
using System.Reflection;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContactGroupSyncContractTests
{
    internal static async Task RunAsync()
    {
        JsonObject Message(JsonArray groups) => new()
        {
            ["art"] = "kontakt_sync", ["fassung"] = 4, ["freigabeId"] = "fixture:contact", ["version"] = 2,
            ["quelle"] = "fixture", ["geaendert"] = 1000, ["inhaltGeaendert"] = 900,
            ["kontakt"] = new JsonObject { ["vorname"] = "Synthetic", ["nachname"] = "", ["firma"] = "", ["notiz"] = "", ["geburtstag"] = "",
                ["anzeigename"] = "", ["jubilaeum"] = "", ["vcardName"] = new JsonArray(), ["telefone"] = new JsonArray(),
                ["emailEintraege"] = new JsonArray(), ["anschriften"] = new JsonArray(), ["gruppen"] = groups }
        };
        var peer = new JsonObject { ["bestaetigt"] = true, ["kontaktFaehigkeiten"] = BaumContactSyncContract.Capabilities(false, 4) };
        BaumContactSyncContract.ValidateCapabilities(peer["kontaktFaehigkeiten"]!);
        TestAssert.That(BaumContactSyncContract.PeerVersion(peer, "kontakt_sync") == 4, "Group capability was not negotiated.");
        foreach (var groups in new[] { new JsonArray("Arbeit", "Kollegen"), new JsonArray("Arbeit"), new JsonArray() })
        {
            var message = Message(groups);
            BaumContactSyncContract.Validate(message);
            TestAssert.That(JsonNode.DeepEquals(BaumContactSyncContract.ForPeer(peer, message), message), "Group set was changed in transport.");
            foreach (var maximum in new[] { 2, 3 })
            {
                var old = new JsonObject { ["bestaetigt"] = true, ["kontaktFaehigkeiten"] = BaumContactSyncContract.Capabilities(false, maximum) };
                TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.ForPeer(old, message), "Authoritative groups were silently dropped for an old peer.");
            }
        }
        foreach (var invalid in new JsonNode?[] { null, JsonValue.Create("Arbeit"), new JsonArray(""), new JsonArray("bad\nname"), new JsonArray(true), new JsonArray(new string('x', 257)) })
        {
            var message = Message(new JsonArray("Arbeit")); message["kontakt"]!["gruppen"] = invalid;
            TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(message), "Malformed group set was accepted.");
        }
        var missing = Message(new JsonArray()); missing["kontakt"]!.AsObject().Remove("gruppen");
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(missing), "Unknown groups became an implicit clear.");
        var root = Path.Combine(Path.GetTempPath(), "groups-negotiation-" + Guid.NewGuid().ToString("N"));
        try { NativeNegotiation(root); }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
        await NativeProviderGroups();
    }

    private static async Task NativeProviderGroups()
    {
        JsonObject Card(params string[] groups) => new() { ["id"] = "local", ["uid"] = "same-person", ["vorname"] = "Synthetic",
            ["vcardRoundtrip"] = groups.Length == 0 ? new JsonArray() : new JsonArray("CATEGORIES:" + string.Join(',', groups)) };
        foreach (var concurrent in new[] { false, true })
        {
            var baseline = Card("Colleagues", "Work");
            var local = baseline.DeepClone().AsObject();
            ContactFields.SetSource(local, "cards", new RemoteContact("native-card", "v1", 100, baseline, true));
            if (concurrent) local["vcardRoundtrip"] = Card("Colleagues")["vcardRoundtrip"]!.DeepClone();
            var remote = new GroupRemote(new RemoteContact("native-card", "v2", 200, Card("Work"), true));
            var result = await new ContactSyncEngine().SyncAsync("cards", new JsonArray(local), [], 0, remote);
            TestAssert.That(result.Counts.Conflicts == (concurrent ? 1 : 0), "Competing membership sets bypassed source conflict detection.");
            var expected = concurrent ? Card("Colleagues") : Card("Work");
            TestAssert.That(JsonNode.DeepEquals(result.Contacts[0]!["vcardRoundtrip"], expected["vcardRoundtrip"]),
                "A removed membership was restored by additive provider merge.");
            if (concurrent) TestAssert.That(result.Contacts[0]!["syncKonflikte"]!["cards"] is JsonObject, "Competing group version was lost.");
        }
        var initial = Card("Colleagues", "Work");
        var provider = new GroupRemote(new RemoteContact("native-card", "v1", 100, initial.DeepClone().AsObject(), true));
        ContactFields.SetSource(initial, "cards", provider.Item);
        foreach (var groups in new[] { new[] { "Work" }, Array.Empty<string>() })
        {
            initial["vcardRoundtrip"] = Card(groups)["vcardRoundtrip"]!.DeepClone();
            var before = provider.Writes;
            var result = await new ContactSyncEngine().SyncAsync("cards", new JsonArray(initial), [], 0, provider);
            TestAssert.That(provider.Writes == before + 1 && result.Counts.Conflicts == 0, "Local group removal was not exported once.");
            var again = await new ContactSyncEngine().SyncAsync("cards", result.Contacts, [], 0, provider);
            TestAssert.That(provider.Writes == before + 1 && JsonNode.DeepEquals(again.Contacts[0]!["vcardRoundtrip"], Card(groups)["vcardRoundtrip"]),
                "Repeated synchronization resurrected or rewrote removed groups.");
            initial = again.Contacts[0]!.DeepClone().AsObject();
        }
    }

    private sealed class GroupRemote(RemoteContact item) : IContactRemote
    {
        internal RemoteContact Item = item;
        internal int Writes;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) => Task.FromResult<IReadOnlyList<RemoteContact>>([Item]);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken token) => throw new InvalidOperationException("Unexpected create");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken token)
        { Writes++; Item = new RemoteContact(remote.Id, "updated-" + Writes, 300 + Writes, contact.DeepClone().AsObject(), true); return Task.FromResult(Item); }
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken token) => throw new InvalidOperationException("Unexpected delete");
    }

    private static void NativeNegotiation(string root)
    {
        var paths = new WindowsPaths(root);
        var storage = new MagnolienbaumStore(paths);
        var state = storage.LoadOrCreate();
        state["an"] = true;
        var remote = MagnolienbaumCrypto.GenerateX25519();
        var peer = new JsonObject { ["kennung"] = "synthetic-peer", ["bestaetigt"] = true,
            ["oeffentlich"] = Convert.ToBase64String(remote.Public), ["protokoll"] = "baum-1" };
        state["partner"]!.AsArray().Add(peer); storage.SaveState(state);
        var userData = new JsonObject { ["id"] = "preserved-user-packet", ["an"] = "synthetic-peer",
            ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["art"] = "aufgabe", ["titel"] = "Synthetic" } };
        storage.SaveOutbox(new JsonArray(userData.DeepClone()));
        using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        typeof(MagnolienbaumCoordinator).GetMethod("QueueContactCapabilities", BindingFlags.Instance | BindingFlags.NonPublic)!
            .Invoke(coordinator, new object[] { peer, false, 0 });
        var queue = storage.LoadOutbox().OfType<JsonObject>().ToArray();
        TestAssert.That(queue.Length == 4 && JsonNode.DeepEquals(queue[0], userData), "Optional probes changed queued user data.");
        TestAssert.That(queue.Count(item => item["kontaktV3Probe"]?.GetValue<bool>() == true) == 1 &&
            queue.Count(item => item["kontaktV4Probe"]?.GetValue<bool>() == true) == 1, "V3/V4 probes are not independent.");
        TestAssert.That(storage.LoadOrCreate()["partner"]![0]!["zaehler_raus"]?.GetValue<long>() is null or 0,
            "Queuing optional capabilities consumed a user-data counter.");
        var key = MagnolienbaumCrypto.PartnerKey(remote.Private, Convert.FromBase64String(state["oeffentlich"]!.GetValue<string>()),
            "synthetic-peer", state["kennung"]!.GetValue<string>());
        try
        {
            long counter = 0;
            void Deliver(int maximum, bool response)
            {
                var wire = MagnolienbaumCrypto.EncryptBaum1(key, "synthetic-peer", ++counter, BaumContactSyncContract.Capabilities(response, maximum));
                var result = coordinator.HandleProtocolRequest("/magnolie/v1/nachricht", wire, "127.0.0.1");
                TestAssert.That(result.Status == 200 && BaumReceipt.Verify(key, "synthetic-peer", state["kennung"]!.GetValue<string>(), wire, result.Body),
                    "Authenticated capabilities were not durably acknowledged: " + result.Status + " " + result.Body.ToJsonString());
            }
            int Version() => BaumContactSyncContract.PeerVersion(storage.LoadOrCreate()["partner"]![0]!.AsObject(), "kontakt_sync");
            Deliver(4, false); TestAssert.That(Version() == 4, "Authenticated V4 advertisement was not retained.");
            Deliver(2, true); Deliver(3, true);
            TestAssert.That(Version() == 4, "Delayed V2/V3 replies erased V4 groups.");
            Deliver(2, false); TestAssert.That(Version() == 2, "Fresh explicit peer downgrade was ignored.");
        }
        finally { CryptographicOperations.ZeroMemory(key); CryptographicOperations.ZeroMemory(remote.Private); }
    }
}
