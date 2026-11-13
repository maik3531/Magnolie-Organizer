using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContactProviderLabelTests
{
    private const string A = "nextcloud-addressbook:fixture-a", B = "nextcloud-addressbook:fixture-b";
    private static JsonObject Card(string field, string phase, long time)
    {
        string type = phase == "base" ? "OTHER" : field == "telefone" ? phase == "local" ? "CELL" : "HOME" : phase == "local" ? "HOME" : "WORK";
        var row = field == "anschriften" ? new JsonObject { ["strasse"] = "Testweg 12", ["plz"] = "10115", ["ort"] = "Berlin", ["region"] = "Berlin", ["land"] = "Germany" }
            : new JsonObject { ["wert"] = field == "telefone" ? "+49305550123" : "alex@example.test" };
        row["typen"] = new JsonArray(type); row["label"] = type switch { "CELL" => "Mobile", "HOME" => "Home", "WORK" => "Work", _ => "Original" };
        return new JsonObject { ["id"] = "local", ["uid"] = "fixture@example.test", ["vorname"] = "Alex", ["nachname"] = "Fixture", ["sync"] = true,
            ["geaendert"] = time, [field] = new JsonArray(row) };
    }
    private sealed class Remote(string name, RemoteContact current) : IContactRemote
    {
        internal RemoteContact Current = current;
        internal int Updates;
        internal bool FailUpdate;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<RemoteContact>>([Current with { Data = Current.Data.DeepClone().AsObject() }]);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => throw new Exception("Unexpected creation");
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) => throw new Exception("Unexpected deletion");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
        {
            if (FailUpdate || remote.Id != Current.Id || remote.ETag != Current.ETag) throw new InvalidOperationException("Original source revision refused");
            Updates++;
            // The provider's own write time must not turn old label content into
            // a newer user edit when this source is revisited after source B.
            Current = new(Current.Id, $"\"{name}-write-{Updates}\"", 9000L, contact.DeepClone().AsObject(), true);
            return Task.FromResult(Current);
        }
    }
    private static (JsonArray Local, Remote First, Remote Second) Pair(string field, long localTime, long remoteTime)
    {
        var original = Card(field, "base", 1000L);
        var local = Card(field, "local", localTime);
        var oldA = new RemoteContact("source-a-record", "\"a-v1\"", 1000L, original, true);
        var oldB = new RemoteContact("source-b-record", "\"b-v1\"", 1000L, original.DeepClone().AsObject(), true);
        ContactFields.SetSource(local, A, oldA, remoteBaseline: true); ContactFields.SetSource(local, B, oldB, remoteBaseline: true);
        return (new JsonArray(local), new Remote("a", oldA), new Remote("b", oldB with { ETag = "\"b-v2\"", Modified = remoteTime, Data = Card(field, "remote", remoteTime) }));
    }
    internal static async Task TwoSourceConvergenceAsync()
    {
        var failures = new List<string>();
        foreach (var field in new[] { "telefone", "emailEintraege", "anschriften" })
        foreach (bool remoteNewer in new[] { false, true })
        {
            try
            {
                var pair = Pair(field, 2000L, remoteNewer ? 3000L : 1500L); var engine = new ContactSyncEngine();
                var one = await engine.SyncAsync(A, pair.Local, [], 0, pair.First);
                var two = await engine.SyncAsync(B, one.Contacts, [], 0, pair.Second);
                TestAssert.That(two.Counts.Conflicts == 0, "Identical values with different labels became a value conflict");
                var three = await engine.SyncAsync(A, two.Contacts, [], 0, pair.First);
                var four = await engine.SyncAsync(B, three.Contacts, [], 0, pair.Second);
                var expected = Card(field, remoteNewer ? "remote" : "local", remoteNewer ? 3000L : 2000L);
                foreach (var card in new[] { four.Contacts.Single()!, pair.First.Current.Data, pair.Second.Current.Data })
                    TestAssert.That(JsonNode.DeepEquals(card[field], expected[field]), "An older source did not receive the canonical newer labels");
                TestAssert.That(four.Contacts.Single()!["geaendert"]!.GetValue<long>() == (remoteNewer ? 3000L : 2000L), "Own provider write time replaced the original content time");
                TestAssert.That(four.Contacts.Count == 1 && four.Contacts[0]!["syncQuellen"]!.AsObject().Count == 2, "Convergence duplicated a person or detached a source");
                int updates = pair.First.Updates + pair.Second.Updates;
                var repeatA = await engine.SyncAsync(A, four.Contacts, [], 0, pair.First);
                var repeatB = await engine.SyncAsync(B, repeatA.Contacts, [], 0, pair.Second);
                TestAssert.That(repeatA.Counts.Conflicts == 0 && repeatB.Counts.Conflicts == 0 && updates == pair.First.Updates + pair.Second.Updates,
                    "Unchanged converged sources reopened a conflict or rewrote the same labels");
            }
            catch (Exception error) { failures.Add(field + "/" + (remoteNewer ? "remote" : "local") + ": " + error.Message); }
        }
        TestAssert.That(failures.Count == 0, string.Join("; ", failures));
    }
    internal static async Task RealChangesAndFailedWritesAsync()
    {
        var engine = new ContactSyncEngine(); var pair = Pair("telefone", 2000L, 1500L);
        pair.Second.Current.Data["telefone"]![0]!["wert"] = "+49305550999";
        var real = await engine.SyncAsync(B, pair.Local, [], 0, pair.Second);
        TestAssert.That(real.Counts.Conflicts == 1 && pair.Second.Updates == 0 && real.Contacts[0]!["syncKonflikte"]?[B] is JsonObject,
            "A genuinely different phone value was silently resolved as a label");
        pair = Pair("telefone", 2000L, 1500L); pair.Second.FailUpdate = true;
        var failed = await engine.SyncAsync(B, pair.Local, [], 0, pair.Second);
        TestAssert.That(failed.Counts.Errors == 1 && failed.Counts.Conflicts == 0 && pair.Second.Updates == 0 &&
            failed.Contacts[0]!["syncQuellen"]![B]!["etag"]!.GetValue<string>() == "\"b-v1\"" &&
            ContactFields.Dirty(failed.Contacts[0]!.AsObject(), failed.Contacts[0]!["syncQuellen"]![B]!.AsObject()),
            "Label reconciliation skipped the guarded write or failed to retain its pending original baseline");
        foreach (var (localTime, remoteTime) in new[] { (0L, 3000L), (2000L, 0L), (2000L, long.MaxValue) })
        {
            pair = Pair("telefone", localTime, remoteTime);
            var unknownTime = await engine.SyncAsync(B, pair.Local, [], 0, pair.Second);
            TestAssert.That(unknownTime.Counts.Conflicts == 0 && pair.Second.Updates == 1 &&
                unknownTime.Contacts[0]!["telefone"]![0]!["typen"]![0]!.GetValue<string>() == "CELL" &&
                unknownTime.Contacts[0]!["geaendert"]!.GetValue<long>() == localTime,
                "Unknown or future source time invented a newer label authority");
        }
        foreach (var field in new[] { "telefone", "emailEintraege", "anschriften" })
        {
            pair = Pair(field, 2000L, 3000L);
            var localRow = pair.Local[0]![field]![0]!.AsObject();
            localRow["typen"] = new JsonArray("HOME"); localRow["label"] = "Home";
            var remoteRow = pair.Second.Current.Data[field]![0]!.AsObject();
            remoteRow.Remove("typen"); remoteRow["label"] = "Privat"; remoteRow["rolle"] = "private";
            var aliases = await engine.SyncAsync(B, pair.Local, [], 0, pair.Second);
            var again = await engine.SyncAsync(B, aliases.Contacts, [], 0, pair.Second);
            TestAssert.That(aliases.Counts.Conflicts == 0 && again.Counts.Conflicts == 0 && pair.Second.Updates == 0 &&
                again.Contacts[0]![field]!.AsArray().Count == 1, "Equivalent Home/Privat roles caused repeated writes or duplicate values");
        }
    }
}
