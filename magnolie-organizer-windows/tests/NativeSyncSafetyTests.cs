using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NativeSyncSafetyTests
{
    internal static async Task RunAsync()
    {
        await DesktopDataReviewTests.RunAsync();
        var root = Path.Combine(Path.GetTempPath(), "magnolie-native-safety-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var settings = new NextcloudMailboxSettingsStore(root + "/settings", root + "/secret", new Protector());
            settings.Save(new NextcloudMailboxSettings(true, true, "https://fixture.invalid", "synthetic"));
            settings.SetApplicationPassword("synthetic-only");
            foreach (var task in new[] { false, true }) await Calendar(settings, task);
            await Contacts();
            PersonalTokens(root);
            SavedResultProof();
            Recovery(root);
            await Mailbox(root, settings);
        }
        finally { Directory.Delete(root, true); }
    }

    private static void Check(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }

    private static async Task Calendar(NextcloudMailboxSettingsStore settings, bool task)
    {
        using var handler = new Dav(task); using var http = new HttpClient(handler);
        using var client = new NextcloudDavClient(settings, http);
        var source = new NextcloudDavSource("nextcloud-calendar:fixture", "fixture", "calendar", new Uri("https://fixture.invalid/calendar/"));
        async Task<JsonArray> Sync(JsonArray values, JsonArray dead, bool additive = false) => task
            ? (await new NextcloudTaskSync(client).SyncAsync(source, values, dead, 100, additive, default)).Tasks
            : (await new NextcloudCalendarSync(client).SyncAsync(source, values, [], dead, 100, additive, default)).Termine;
        var values = await Sync([], [], true);
        var original = values.DeepClone().AsArray();
        values[0]!["titel"] = "LOCAL"; values[0]!["geaendert"] = 90L;
        values = await Sync(values, []);
        Check(handler.Puts == 1 && handler.Text.Contains("LOCAL"), "Clock rollback edit was not uploaded.");
        values[0]!["titel"] = "SAME TIMESTAMP";
        values = await Sync(values, []);
        Check(handler.Puts == 2 && handler.Text.Contains("SAME TIMESTAMP"), "Same-timestamp edit was not uploaded.");
        for (var repeat = 0; repeat < 2; repeat++) values = await Sync(values, []);
        Check(handler.Puts == 2 && values.Count == 1, "Unchanged follow-up rewrote or duplicated data.");
        var writes = handler.Puts + handler.Deletes;
        try { await Sync([], original); throw new Exception("Stale tombstone accepted."); }
        catch (InvalidOperationException) { }
        Check(handler.Puts + handler.Deletes == writes, "Stale deletion mutated the server.");
        var missingBaseline = values.DeepClone().AsArray();
        missingBaseline[0]!["syncQuellen"]![source.Uid]!.AsObject().Remove("etag");
        try { await Sync([], missingBaseline); throw new Exception("Unproven deletion accepted."); }
        catch (InvalidOperationException) { }
        Check(handler.Puts + handler.Deletes == writes, "Missing deletion baseline mutated the server.");
        await Sync([], values, true);
        Check(handler.Puts + handler.Deletes == writes, "Restore/additive run deleted data.");
        handler.Exists = false;
        values = await Sync(values, []);
        Check(values.Count == 0 && handler.Puts + handler.Deletes == writes, "Remote deletion was resurrected.");
        for (var repeat = 0; repeat < 2; repeat++) values = await Sync(values, []);
        Check(values.Count == 0 && handler.Puts + handler.Deletes == writes, "Remote deletion did not converge.");
        var restored = await Sync(original, [], true);
        Check(restored.Count == 1, "Restore additive run lost a missing remote item.");
        restored = await Sync(restored, []);
        Check(restored.Count == 1, "Second post-restore run deleted the retained item.");

        // Legacy mapping migration must preserve a local version when its old content baseline is unavailable.
        handler.Exists = true;
        values = await Sync([], [], true);
        values[0]!["syncQuellen"]![source.Uid]!.AsObject().Remove("inhaltSha256");
        values[0]!["titel"] = "LEGACY LOCAL";
        handler.Revision++;
        values = await Sync(values, []);
        Check(values.Count == 2 && values.Any(value => value?["titel"]?.GetValue<string>() == "LEGACY LOCAL"),
            "Legacy baseline migration lost a local conflict.");
        if (task)
        {
            handler.Text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:u\r\nSUMMARY:Parent\r\nEND:VTODO\r\n" +
                "BEGIN:VTODO\r\nUID:child\r\nRELATED-TO;RELTYPE=PARENT:u\r\nSUMMARY:Child\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
            handler.Revision++;
            values = await Sync([], [], true);
            foreach (var value in values.OfType<JsonObject>()) value["titel"] = value["titel"]!.GetValue<string>() + " edited";
            var before = handler.Puts;
            values = await Sync(values, []);
            Check(values.Count == 2 && handler.Puts == before + 2, "Own shared-resource PUT caused a false conflict.");
            for (var repeat = 0; repeat < 2; repeat++) values = await Sync(values, []);
            Check(values.Count == 2 && handler.Puts == before + 2, "Shared-resource task edits did not converge.");
        }
    }

    private static async Task Contacts()
    {
        const string source = "nextcloud-addressbook:fixture";
        var remote = new ContactsRemote(); var engine = new ContactSyncEngine();
        var first = await engine.SyncAsync(source, [], [], 0, remote, additiveOnly: true);
        var oldTombstone = first.Contacts.DeepClone().AsArray();
        first.Contacts[0]!["vorname"] = "LOCAL"; first.Contacts[0]!["geaendert"] = 90L;
        var next = await engine.SyncAsync(source, first.Contacts, [], 100, remote);
        Check(remote.Writes == 1 && remote.Value["vorname"]!.GetValue<string>() == "LOCAL", "Contact rollback edit lost.");
        next.Contacts[0]!["vorname"] = "SAME TIME";
        next = await engine.SyncAsync(source, next.Contacts, [], 100, remote);
        for (var repeat = 0; repeat < 2; repeat++) next = await engine.SyncAsync(source, next.Contacts, [], 100, remote);
        Check(remote.Writes == 2 && next.Contacts.Count == 1, "Contact follow-up did not converge.");
        try { await engine.SyncAsync(source, [], oldTombstone, 100, remote); throw new Exception("Stale contact tombstone accepted."); }
        catch (InvalidOperationException) { }
        Check(remote.Deletes == 0, "Stale contact deletion reached remote.");
        var deleted = await engine.SyncAsync(source, [], next.Contacts, 100, remote);
        Check(remote.Deletes == 1 && deleted.Contacts.Count == 0 && deleted.Tombstones.Count == 0, "Last contact deletion failed.");
        for (var repeat = 0; repeat < 2; repeat++) deleted = await engine.SyncAsync(source, deleted.Contacts, deleted.Tombstones, 100, remote);
        Check(deleted.Contacts.Count == 0 && remote.Deletes == 1, "Last contact returned on follow-up.");
    }

    private static void Recovery(string root)
    {
        var journal = new RecoveryJournal(root + "/snapshots", root + "/snapshot-settings");
        var healthy = journal.Create(new JsonObject(), SnapshotReason.Manual, "2.0.18");
        foreach (var field in new[] { "createdUtc", "version", "payload" })
        {
            var damaged = journal.Create(new JsonObject { ["fixture"] = field }, SnapshotReason.Manual, "2.0.18");
            var path = damaged.Directory + "/manifest.json";
            var manifest = JsonNode.Parse(File.ReadAllText(path))!.AsObject(); manifest[field] = "invalid";
            new AtomicStore().Write(path, manifest.ToJsonString());
        }
        Check(journal.List().Count(item => item.Integrity == "damaged") == 3, "Malformed records not classified individually.");
        Check(journal.Verify(healthy.Id).Integrity == "ok", "Healthy snapshot became unavailable.");
        journal.Create(new JsonObject { ["fixture"] = "after-corruption" }, SnapshotReason.Manual, "2.0.18");
        journal.Prune();
        Check(journal.List().Count == 5, "Retention silently deleted malformed recovery records.");
    }

    private static void PersonalTokens(string root)
    {
        var paths = new WindowsPaths(root + "/phone"); var key = RandomNumberGenerator.GetBytes(32);
        var store = new TelefonStore(paths, key); var personal = new PersonalSyncStore(store);
        var peer = Guid.NewGuid().ToString(); var run = Guid.NewGuid().ToString();
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        personal.RememberRun(peer, new JsonObject { ["format"] = 3, ["run_id"] = run,
            ["trigger"] = "manual", ["modules"] = new JsonArray("tasks") }, now);
        JsonObject Message(int sequence, bool last) => new()
        {
            ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString(),
            ["kind"] = "personal_sync.batch", ["created_ms"] = now, ["expires_ms"] = now + 60_000,
            ["body"] = new JsonObject { ["format"] = 3, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString(),
                ["sequence"] = sequence, ["last"] = last, ["reply"] = false, ["records"] = new JsonArray(),
                ["records_hash"] = PersonalSyncContract.RecordsHash(new JsonArray()) }
        };
        var first = Message(0, false); var final = Message(1, true);
        Check(personal.StageBatch(peer, first, "wifi", now) is null, "Incomplete direction completed.");
        string token;
        using (var database = store.OpenDatabase())
        {
            database.Open(); using var command = database.CreateCommand();
            command.CommandText = "SELECT commit_token FROM personal_batch"; token = (string)command.ExecuteScalar()!;
        }
        Check(!personal.CommitBatch(peer, first["message_id"]!.GetValue<string>(), token, now, out _), "Incomplete staged direction was discarded.");
        var staged = personal.StageBatch(peer, final, "wifi", now)!;
        var restarted = new PersonalSyncStore(new TelefonStore(paths, key));
        Check(restarted.ReadyBatches(now).Single().CommitToken == token, "Delayed save/restart changed the staging token.");
        Check(!restarted.CommitBatch(peer, staged.PendingMessageId, "wrong", now, out _), "Forged commit succeeded.");
        Check(!restarted.CommitBatch(peer, first["message_id"]!.GetValue<string>(), token, now, out _), "Nonfinal message committed a direction.");
        Check(restarted.ReadyBatches(now).Count == 1, "Failed commit removed recovery staging.");
        Check(restarted.CommitBatch(peer, staged.PendingMessageId, token, now, out var ids) && ids.Count == 2, "Valid complete direction did not commit.");
        Check(!restarted.CommitBatch(peer, staged.PendingMessageId, token, now, out _), "Consumed token was reused.");
        try { restarted.StageBatch(peer, first, "wifi", now); throw new Exception("Committed direction restaged."); }
        catch (InvalidDataException) { }
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
    }

    private static void SavedResultProof()
    {
        var result = new JsonObject { ["termine"] = new JsonArray(new JsonObject { ["uid"] = "u", ["titel"] = "received" }),
            ["aufgaben"] = new JsonArray(), ["kontakte"] = new JsonArray(), ["jahrestage"] = new JsonArray(),
            ["geloescht"] = new JsonObject(), ["letzterSync"] = 100L, ["letzteSyncs"] = new JsonObject(),
            ["syncMetadaten"] = new JsonObject(), ["syncEpoch"] = "original-epoch" };
        var saved = result.DeepClone().AsObject(); saved["termine"]![0]!["id"] = "frontend-local-id";
        Check(SyncBaseline.ContainsSavedResult(result, saved), "Frontend-added defaults rejected a matching saved result.");
        saved["termine"]![0]!["titel"] = "old disk state";
        Check(!SyncBaseline.ContainsSavedResult(result, saved), "Unsaved result was accepted as durable.");
        saved = result.DeepClone().AsObject(); saved["syncEpoch"] = "restored-epoch";
        Check(!SyncBaseline.ContainsSavedResult(result, saved), "Restore consumed another epoch's pending journal.");
        Check(!SyncBaseline.ContainsSavedResult(new JsonObject(), saved), "Empty completion proof was accepted.");
        result["aufgaben"] = new JsonArray(new JsonObject { ["uid"] = "task", ["titel"] = "Task", ["davHref"] = "remote",
            ["davEtag"] = "v1", ["syncQuellen"] = new JsonObject { ["source"] = new JsonObject { ["id"] = "remote", ["etag"] = "v1" } } });
        saved = result.DeepClone().AsObject(); saved["aufgaben"]![0]!.AsObject().Remove("davHref"); saved["aufgaben"]![0]!.AsObject().Remove("davEtag");
        Check(SyncBaseline.ContainsSavedResult(result, saved), "Redundant task DAV fields prevented a durable ACK.");
        saved["aufgaben"]![0]!["syncQuellen"]!["source"]!["etag"] = "wrong";
        Check(!SyncBaseline.ContainsSavedResult(result, saved), "Mismatched authoritative mapping was accepted.");
    }

    private static async Task Mailbox(string root, NextcloudMailboxSettingsStore settings)
    {
        var paths = new WindowsPaths(root + "/baum"); var store = new MagnolienbaumStore(paths);
        var state = store.LoadOrCreate(); state["an"] = true;
        var keys = MagnolienbaumCrypto.GenerateX25519();
        MagnolienbaumPairing.AddPartner(state, new JsonObject { ["kennung"] = "peer", ["name"] = "fixture",
            ["oeffentlich"] = Convert.ToBase64String(keys.Public), ["port"] = 8737 }, "", true);
        store.SaveState(state);
        using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        await coordinator.SetPartnerAsync("peer", true, true, true, "", 8737);
        var field = typeof(MagnolienbaumCoordinator).GetField("mailbox", BindingFlags.Instance | BindingFlags.NonPublic)!;
        ((NextcloudMailbox)field.GetValue(coordinator)!).Dispose();
        using var http = new HttpClient(new Receipts());
        field.SetValue(coordinator, new NextcloudMailbox(settings, http));
        var own = state["kennung"]!.GetValue<string>();
        var key = MagnolienbaumCrypto.PartnerKey(keys.Private, Convert.FromBase64String(state["oeffentlich"]!.GetValue<string>()), "peer", own);
        var method = typeof(MagnolienbaumCoordinator).GetMethod("AcceptMailboxMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
        async Task Receive(JsonObject content, long counter, byte[] id, MagnolienbaumCoordinator? receiver = null)
        {
            var envelope = MagnolienbaumCrypto.EncryptBaum1(key, "peer", counter, content);
            await (Task)method.Invoke(receiver ?? coordinator, [own, "peer", id, envelope, CancellationToken.None])!;
        }
        await Receive(BaumContactSyncContract.Capabilities(false), 1, new byte[16]);
        Check(store.LoadOrCreate()["partner"]![0]!["zaehler_rein"]!.GetValue<long>() == 1, "Capability counter was not durable.");
        await Receive(BaumContactSyncContract.Capabilities(false), 1, new byte[16]);
        var deletion = new JsonObject { ["art"] = "kontakt_loeschen", ["fassung"] = 1, ["freigabeId"] = "fixture",
            ["version"] = 1L, ["quelle"] = "peer", ["geaendert"] = 0L };
        var id2 = new byte[16]; id2[0] = 1;
        await Receive(deletion, 2, id2);
        await Receive(deletion, 2, id2);
        Check(store.LoadInbox().Count == 1 && store.LoadOrCreate()["partner"]![0]!["zaehler_rein"]!.GetValue<long>() == 2,
            "Canonical deletion grant or mailbox deduplication failed.");
        var beforeStateWrite = store.LoadOrCreate();
        beforeStateWrite["partner"]![0]!["zaehler_rein"] = 1L;
        beforeStateWrite["partner"]![0]!["brief_transport_ids"] = new JsonArray();
        store.SaveState(beforeStateWrite);
        using var restarted = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        ((NextcloudMailbox)field.GetValue(restarted)!).Dispose();
        field.SetValue(restarted, new NextcloudMailbox(settings, http));
        await Receive(deletion, 2, id2, restarted);
        Check(store.LoadInbox().Count == 1 && store.LoadOrCreate()["partner"]![0]!["zaehler_rein"]!.GetValue<long>() == 2,
            "Inbox-before-counter-write crash did not recover without duplicate application.");
    }

    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] value) => value.Select(x => (byte)(x ^ 0x55)).ToArray();
        public byte[] Unprotect(byte[] value) => Protect(value);
    }

    private sealed class Receipts : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Check(request.Method == HttpMethod.Put || request.Method == HttpMethod.Delete, "Unexpected mailbox network operation.");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Created));
        }
    }

    private sealed class ContactsRemote : IContactRemote
    {
        internal JsonObject Value = new() { ["uid"] = "u", ["vorname"] = "REMOTE", ["geaendert"] = 50L };
        internal int Writes, Deletes; private int revision = 1;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) => Task.FromResult<IReadOnlyList<RemoteContact>>(
            Deletes == 0 ? [new("remote", "v" + revision, 50, Value.DeepClone().AsObject(), true)] : []);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject value, CancellationToken token) => throw new Exception("Unexpected create.");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject value, CancellationToken token)
        {
            Writes++; revision++; Value = value.DeepClone().AsObject();
            return Task.FromResult(new RemoteContact("remote", "v" + revision, 50, Value.DeepClone().AsObject(), true));
        }
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken token) { Deletes++; return Task.CompletedTask; }
    }

    private sealed class Dav : HttpMessageHandler
    {
        internal int Revision = 1, Puts, Deletes;
        internal bool Exists = true;
        internal string Text;
        internal Dav(bool task)
        {
            var kind = task ? "VTODO" : "VEVENT";
            Text = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:{kind}\r\nUID:u\r\nDTSTART;VALUE=DATE:20260908\r\nSUMMARY:REMOTE\r\nEND:{kind}\r\nEND:VCALENDAR\r\n";
        }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            if (request.Method == HttpMethod.Put)
            {
                if (request.Headers.TryGetValues("If-None-Match", out var create))
                    Check(!Exists && create.Single() == "*", "Unconditional or conflicting create.");
                else Check(request.Headers.GetValues("If-Match").Single() == $"\"v{Revision}\"", "Unconditional or stale update.");
                Text = await request.Content!.ReadAsStringAsync(token); Puts++; Revision++; Exists = true;
                return new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue($"\"v{Revision}\"") } };
            }
            if (request.Method == HttpMethod.Delete) { Deletes++; Exists = false; return new HttpResponseMessage(HttpStatusCode.NoContent); }
            Check(request.Method.Method == "REPORT", "Unexpected DAV operation.");
            return new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new StringContent(
                "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>" + (Exists ?
                $"<d:response><d:href>/calendar/u.ics</d:href><d:propstat><d:prop><d:getetag>&quot;v{Revision}&quot;</d:getetag><c:calendar-data>{System.Security.SecurityElement.Escape(Text)}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" : "") + "</d:multistatus>") };
        }
    }
}
