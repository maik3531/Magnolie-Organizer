using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorSourceTests
{
    private static JsonObject Message(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "actor-native-source-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)37, 32).ToArray());
            var identity = store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)23, 32).ToArray());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
            var settings = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var capabilities = TelefonProtocolContract.DesktopCapabilities();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) capabilities["items"]![name]!["versions"]!.AsArray().Add(12);
            var grants = TelefonProtocolContract.DesktopGrants(); grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
            Task<TelefonAck?> Receive(TelefonPeer _, JsonObject message)
            {
                var body = message["body"]!.AsObject();
                if (message["kind"]!.GetValue<string>() == "capabilities.update")
                    store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null);
                else if (message["kind"]!.GetValue<string>() == "grants.update")
                    store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject());
                else if (message["kind"]!.GetValue<string>() == "personal_sync.settings")
                    store.SetPersonalSettings(peer.Id, remoteOwnDevice: body["own_device"]!.GetValue<bool>());
                return Task.FromResult<TelefonAck?>(null);
            }
            var emitted = 0;
            using var coordinator = new TelefonCoordinator(paths, (_, _) => { emitted++; return Task.CompletedTask; }, dataStore: store,
                foregroundEnabled: true, localOnly: true) { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
            using var wire = new MemoryStream();
            using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store, Receive, CancellationToken.None, "wifi")
                { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            string? Read(Func<string?>? book = null) => coordinator.CurrentActorSource(peer.Id, fingerprint, book ?? (() => new string('a', 64)));
            TestAssert.That(Read() is null, "Missing fresh native controls admitted an actor source.");
            await connection.HandlePlainAsync(Message("capabilities.update", capabilities));
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = grants }));
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), settings, peer.Id, identity.Id)));
            TestAssert.That(Read() is null, "A persisted preference agreement replaced fresh membership.");
            var manifest = PhoneContentScope.Create(["note-one"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(manifest)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var revision = Read(); var beforeWire = wire.Length; var beforeEmitted = emitted;
            TestAssert.That(revision is { Length: 64 } && Read() == revision, "Actual native source was unavailable or unstable.");
            TestAssert.That(Read(() => new string('b', 64)) != revision && Read(() => null) is null && Read(() => "client-digest") is null,
                "Native book ownership was ignored or an invalid book source was accepted.");
            var checks = 0;
            TestAssert.That(Read(() => ++checks == 1 ? new string('a', 64) : new string('b', 64)) is null, "Book-owner race produced a source revision.");
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, "AAAA-BBBB-CCCC-DDDD", () => new string('a', 64)) is null, "Another peer key was accepted.");
            store.SetLocalGrant("personal_tasks_sync", false);
            TestAssert.That(Read() is null, "Grant revocation reused an actor source.");
            store.SetLocalGrant("personal_tasks_sync", true); store.NextOwnRevision("grants");
            var granted = Read();
            TestAssert.That(granted is { Length: 64 } && granted != revision, "Native grant revision was not source-bound.");
            var changed = PhoneContentScope.Advance(manifest, ["note-two"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var current = Read();
            TestAssert.That(current is not null && current != granted, "Scope replacement retained source identity.");
            beforeWire = wire.Length; beforeEmitted = emitted;
            TestAssert.That(Read() == current && wire.Length == beforeWire && emitted == beforeEmitted, "Source inspection emitted transport or GUI work.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = grants.DeepClone() }));
            var remoteRevision = Read();
            TestAssert.That(remoteRevision is not null && remoteRevision != current, "Fresh remote grant revision was not source-bound.");
            store.UpdatePeerProtocol(peer.Id, 0, null, 3, grants);
            TestAssert.That(Read() is null, "Cached fresh flags authorized a control revision unseen on this connection.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 4, ["grants"] = grants.DeepClone() }));
            current = Read();
            TestAssert.That(current is not null, "Actual current grant control did not refresh source authority.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = false }));
            TestAssert.That(Read() is null, "Remote ownership revocation stayed authorized.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            var renewed = store.SharedSettings(peer.Id, peer.PublicKey) ?? store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), renewed, peer.Id, identity.Id)));
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var reowned = Read();
            TestAssert.That(reowned is not null && reowned != current, "Remote revoke/regrant inherited an old actor source.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            TestAssert.That(Read() == reowned, "Unchanged ownership replay rotated actor authority.");
            online.Clear(); TestAssert.That(Read() is null, "A disconnected native source stayed authorized.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
