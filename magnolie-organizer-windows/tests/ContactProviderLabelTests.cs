using System.Text.Json.Nodes;
using System.Text.Json;

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
        internal bool? Writable = true;
        public bool? CanWrite => Writable;
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
        await PhoneCountryComparisonAsync();
        await EmailCaseComparisonAsync();
        await BoundSharpSComparisonAsync();
        await ObfuscatedEmailAsync();
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
        await ContactSourceUpdateRunTests.RunAsync();
        CheckUnknownLabelsAndCategories();
    }
    private static async Task ObfuscatedEmailAsync()
    {
        foreach (var spelling in new[] { "Maik3531(at)Gmail.com", "Maik3531[at]Gmail.com", "Maik3531[AT]Gmail.com" })
        {
            var parsed = ExchangeCodec.ParseVCard("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:mail-fixture\r\nFN:Synthetic\r\nEMAIL:" + spelling + "\r\nEND:VCARD\r\n").Kontakte.Single()!.AsObject();
            TestAssert.That(parsed["emailEintraege"]!.AsArray().Count == 1, "Actual vCard reader discarded an obfuscated email");
            parsed["notiz"] = "Keep " + spelling;
            var local = parsed.DeepClone().AsObject(); local["id"] = "mail-local"; local["sync"] = true;
            ContactFields.NormalizeEmailAddresses(local);
            TestAssert.That(ContactFields.Text(local, "email") == "maik3531@gmail.com" && ContactFields.Text(local, "notiz") == "Keep " + spelling,
                "Mail field was not normalized or free text was rewritten");
            var wire = new Remote("obfuscated", new RemoteContact("mail-record", "\"v1\"", 1000, parsed, true)) { Writable = false };
            var result = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local), [], 0, wire);
            TestAssert.That(result.Contacts.Count == 1 && result.Counts.Errors == 0 && result.Counts.Conflicts == 0 && wire.Updates == 0,
                "Read-only obfuscated email caused a duplicate/error/conflict/write");
            wire.Writable = true;
            result = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, wire);
            result = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, wire);
            TestAssert.That(wire.Updates == 1 && ContactFields.Text(wire.Current.Data, "email") == "maik3531@gmail.com" &&
                ContactFields.Text(wire.Current.Data, "notiz") == "Keep " + spelling && result.Counts.Conflicts == 0,
                "Obfuscated email did not converge through the original guarded source");
        }
        TestAssert.That(ExchangeCodec.ParseVCard("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Synthetic\r\nEMAIL:a(at)b(at)example.test\r\nEND:VCARD\r\n")
            .Kontakte.Single()!["emailEintraege"]!.AsArray().Count == 0, "Ambiguous obfuscation was guessed as an email");
    }

    private static async Task BoundSharpSComparisonAsync()
    {
        foreach (var field in new[] { "email", "notiz" })
        {
            var a = new JsonObject { [field] = field == "email" ? "groß@example.test" : "Maße" };
            var b = new JsonObject { [field] = field == "email" ? "gross@example.test" : "Masse" };
            TestAssert.That(!ContactFields.SameLabelValues(a, b, sourceTransliteration: true),
                "Transliteration changed an address identifier or free text");
        }
        TestAssert.That(!ContactFields.SameLabelValues(new JsonObject { ["nachname"] = "Groß" }, new JsonObject { ["nachname"] = "Gross" }),
            "Unbound people were granted source transliteration equivalence");
        foreach (var field in new[] { "nachname", "firma", "strasse", "ort", "anschriften" })
        foreach (var readOnly in new[] { false, true })
        {
            var local = Card("telefone", "local", 2000);
            var remote = local.DeepClone().AsObject(); var old = local.DeepClone().AsObject();
            if (field == "anschriften")
            {
                local[field] = new JsonArray(new JsonObject { ["strasse"] = "Großstraße 12", ["ort"] = "Großstadt", ["region"] = "Großregion" });
                remote[field] = new JsonArray(new JsonObject { ["strasse"] = "Grossstrasse 12", ["ort"] = "Grossstadt", ["region"] = "Grossregion" });
            }
            else { local[field] = "Großstraße"; remote[field] = "Grossstrasse"; old[field] = "Previous"; }
            var wire = new Remote("sharp-s", new RemoteContact("sharp-record", "\"new\"", 3000, remote, true)) { Writable = !readOnly };
            ContactFields.SetSource(local, A, wire.Current with { ETag = "\"old\"", Data = old }, remoteBaseline: true);
            var exact = ContactFields.ContentHash(local);
            var result = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local.DeepClone()), [], 0, wire);
            TestAssert.That(result.Counts.Conflicts == 0 && result.Counts.Errors == 0 && wire.Updates == 0 && result.Contacts.Count == 1 &&
                JsonNode.DeepEquals(result.Contacts[0]![field], local[field]) && JsonNode.DeepEquals(wire.Current.Data[field], remote[field]) &&
                ContactFields.ContentHash(local) == exact, "Bound German source transliteration conflicted or lost spelling: " + field);
            var repeat = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, wire);
            TestAssert.That(repeat.Counts.Conflicts == 0 && repeat.Counts.Errors == 0 && wire.Updates == 0, "Transliteration caused source churn");
        }
    }

    private static async Task EmailCaseComparisonAsync()
    {
        foreach (var sourceReadOnly in new[] { false, true })
        foreach (var clientReadOnly in new[] { false, true })
        {
            using var http = new HttpClient();
            using var client = new NextcloudDavClient((NextcloudMailboxSettingsStore)null!, http) { ReadOnly = clientReadOnly };
            var source = new NextcloudDavSource(A, "Synthetic", "addressbook", new Uri("https://example.invalid/book/"), ReadOnly: sourceReadOnly);
            TestAssert.That(new NextcloudCardDavRemote(client, source).CanWrite == (!sourceReadOnly && !clientReadOnly),
                "DAV/bridge read-only capability was not propagated");
        }
        foreach (var field in new[] { "email", "emails", "emailEintraege" })
        {
            JsonObject Email(string address) => new() {
                ["id"] = "email-person", ["uid"] = "email@example.test", ["vorname"] = "Alex", ["nachname"] = "Email Fixture",
                ["sync"] = true, ["geaendert"] = 2000L,
                [field] = field == "email" ? JsonValue.Create(address) : field == "emails" ? new JsonArray(address) :
                    new JsonArray(new JsonObject { ["wert"] = address, ["typen"] = new JsonArray("HOME") }) };
            var local = Email("Alex.Example+tag@Example.Test");
            var lower = Email("alex.example+tag@example.test");
            var original = Email("old@example.test");
            var first = new Remote("email-a", new RemoteContact("email-a", "\"a-v2\"", 3000, lower.DeepClone().AsObject(), true));
            var second = new Remote("email-b", new RemoteContact("email-b", "\"b-v2\"", 3000, lower.DeepClone().AsObject(), true));
            var exact = ContactFields.ContentHash(local);
            var adopted = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local.DeepClone()), [], 0, first);
            TestAssert.That(adopted.Contacts.Count == 1 && adopted.Counts.Errors == 0 && adopted.Counts.Conflicts == 0 && first.Updates == 0,
                "E-mail case created an unbound duplicate or write: " + field);
            ContactFields.SetSource(local, A, first.Current with { ETag = "\"a-v1\"", Data = original }, remoteBaseline: true);
            ContactFields.SetSource(local, B, second.Current with { ETag = "\"b-v1\"", Data = original }, remoteBaseline: true);
            var result = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local.DeepClone()), [], 0, first);
            result = await new ContactSyncEngine().SyncAsync(B, result.Contacts, [], 0, second);
            result = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            TestAssert.That(result.Counts.Conflicts == 0 && first.Updates == 0 && second.Updates == 0 && result.Contacts.Count == 1 &&
                JsonNode.DeepEquals(result.Contacts[0]![field], lower[field]) && ContactFields.ContentHash(local) == exact &&
                result.Contacts[0]!["syncQuellen"]!.AsObject().Count == 2, "E-mail case caused two-source churn or failed canonical lowercase: " + field);
            first.Current = first.Current with { ETag = "\"a-v3\"", Data = Email("Alex.Example+tag@Example.Test") };
            second.Current = second.Current with { ETag = "\"b-v3\"", Data = Email("Alex.Example+tag@Example.Test") };
            var readOnly = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first, additiveOnly: true);
            TestAssert.That(first.Updates == 0 && JsonNode.DeepEquals(readOnly.Contacts[0]![field], lower[field]), "Read-only import wrote a provider");
            first.Writable = false;
            var noWriteGrant = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            TestAssert.That(noWriteGrant.Counts.Errors == 0 && noWriteGrant.Counts.Conflicts == 0 && first.Updates == 0,
                "Read-only source e-mail case caused an error/conflict or a write attempt");
            first.Writable = null;
            var unknownGrant = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            TestAssert.That(unknownGrant.Counts.Errors == 0 && unknownGrant.Counts.Conflicts == 0 && first.Updates == 0,
                "Unknown capability granted an optional spelling write");
            first.Writable = true;
            result = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            result = await new ContactSyncEngine().SyncAsync(B, result.Contacts, [], 0, second);
            result = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            TestAssert.That(result.Counts.Conflicts == 0 && first.Updates == 1 && second.Updates == 1 &&
                JsonNode.DeepEquals(first.Current.Data[field], lower[field]) && JsonNode.DeepEquals(second.Current.Data[field], lower[field]),
                "Uppercase provider e-mail was not written lowercase once to each original source");
            first.Current = first.Current with { ETag = "\"a-v4\"", Data = Email("Alex.Example+tag@Example.Test") };
            first.FailUpdate = true;
            var failed = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, first);
            TestAssert.That(failed.Counts.Errors == 1 && first.Updates == 1 &&
                ContactFields.Source(failed.Contacts[0]!.AsObject(), A)?["etag"]?.GetValue<string>() != "\"a-v4\"",
                "Failed lowercase write was falsely acknowledged");
            foreach (var different in new[] { "alex.example@example.test", "alexexample+tag@example.test", "alex.example+other@example.test" })
                TestAssert.That(!ContactFields.SameLabelValues(local, Email(different)), "Significant e-mail characters were ignored: " + different);
        }
    }

    private static async Task PhoneCountryComparisonAsync()
    {
        foreach (var (country, national, international) in new[] {
            ("DE", "0123456", "+49123456"), ("DE", "030 123456", "+4930123456"),
            ("GB", "07700 900123", "+447700900123"), ("IT", "02 12345678", "+390212345678") })
        foreach (var spelling in new[] { national, "00" + international[1..], international })
        {
            var local = Card("telefone", "local", 2000);
            local["telefone"]![0]!["wert"] = spelling;
            var incoming = local.DeepClone().AsObject(); incoming["telefone"]![0]!["wert"] = international;
            incoming["uid"] = "provider-phone@example.test";
            var localBefore = local.ToJsonString(); var hashBefore = ContactFields.ContentHash(local);
            TestAssert.That(ContactFields.StrongKeys(local, country).Overlaps(ContactFields.StrongKeys(incoming, country)),
                "National phone spelling did not match with explicit country: " + country + spelling);
            var remote = new Remote("phone", new RemoteContact("phone-record", "\"v1\"", 3000, incoming, true));
            // Actual unbound sync must bind, not create another provider card.
            var result = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local.DeepClone()), [], 0, remote, homeCountry: country);
            TestAssert.That(result.Contacts.Count == 1 && result.Counts.Conflicts == 0 && result.Counts.Errors == 0 &&
                remote.Updates == 0 && ContactFields.Source(result.Contacts[0]!.AsObject(), A)?["id"]?.GetValue<string>() == "phone-record",
                "Phone spelling caused a duplicate, conflict, write or lost binding");
            TestAssert.That(result.Contacts[0]!["telefone"]![0]!["wert"]!.GetValue<string>() == spelling &&
                local.ToJsonString() == localBefore && ContactFields.ContentHash(local) == hashBefore &&
                remote.Current.Data["telefone"]![0]!["wert"]!.GetValue<string>() == international,
                "Comparison rewrote original numbers or exact content hashes");
            var again = await new ContactSyncEngine().SyncAsync(A, result.Contacts, [], 0, remote, homeCountry: country);
            TestAssert.That(again.Counts.Conflicts == 0 && remote.Updates == 0 && again.Contacts.Count == 1,
                "Repeated phone spelling comparison was not stable");
            var old = local.DeepClone().AsObject(); old["telefone"]![0]!["wert"] = "+49305550999";
            ContactFields.SetSource(local, A, remote.Current with { ETag = "\"old\"", Data = old }, remoteBaseline: true);
            var simultaneous = await new ContactSyncEngine().SyncAsync(A, new JsonArray(local.DeepClone()), [], 0, remote, homeCountry: country);
            TestAssert.That(simultaneous.Counts.Conflicts == 0 && remote.Updates == 0 &&
                simultaneous.Contacts[0]!["telefone"]![0]!["wert"]!.GetValue<string>() == spelling,
                "Simultaneous equivalent source edits conflicted or rewrote spelling");
        }
        JsonObject Number(string value) => new() { ["telefone"] = new JsonArray(new JsonObject { ["wert"] = value }) };
        foreach (var country in new[] { "", "ZZ", "GB" })
            TestAssert.That(!ContactFields.StrongKeys(Number("0123456"), country).Overlaps(ContactFields.StrongKeys(Number("+49123456"), country)),
                "Missing or different country silently assumed Germany");
        foreach (var value in new[] { "+49123457", "+49123456 ext 2" })
            TestAssert.That(!ContactFields.StrongKeys(Number("0123456 ext 1"), "DE").Overlaps(ContactFields.StrongKeys(Number(value), "DE")),
                "Different numbers or extensions became the same identity");
        TestAssert.That(ContactFields.StrongKeys(Number("0123456 ext 1"), "DE").Overlaps(ContactFields.StrongKeys(Number("+49123456 ext 1"), "DE")),
            "Equivalent extension spellings failed comparison");
        TestAssert.That(ContactFields.StrongKeys(Number("0123456 ext 1"), "DE").Overlaps(ContactFields.StrongKeys(Number("tel:+49123456;ext=1"), "DE")),
            "RFC phone URI extension stopped matching");
    }
    private static void CheckUnknownLabelsAndCategories()
    {
        foreach (var label in new[] { "Immobilienbuero", "Automobilclub", "Wohnmobilverein" })
        {
            var text = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:category-fixture\r\nN:Fixture;Alex;;;\r\nFN:Alex Fixture\r\n" +
                "item1.TEL;TYPE=VOICE:+49305550123\r\nitem1.X-ABLabel:" + label + "\r\nCATEGORIES:Home,Privat,OR6-600 Custom\r\nEND:VCARD\r\n";
            for (var pass = 0; pass < 3; pass++)
            {
                var contact = ExchangeCodec.ParseVCard(text).Kontakte.Single()!.AsObject();
                var phone = contact["telefone"]!.AsArray().Single()!.AsObject();
                TestAssert.That(phone["typen"]!.AsArray().Select(type => type!.GetValue<string>()).SequenceEqual(new[] { "VOICE" }) &&
                    phone["label"]!.GetValue<string>() == label && phone["rolle"] is null && contact["vertraulich"] is null,
                    "Free label was classified as mobile/private or lost after repeated interchange");
                TestAssert.That(contact["vcardRoundtrip"]!.AsArray().Any(line => line!.GetValue<string>() == "CATEGORIES:Home,Privat,OR6-600 Custom"),
                    "Contact group names were confused with field types or lost during repeated import");
                using var input = JsonDocument.Parse(new JsonArray(contact.DeepClone()).ToJsonString());
                text = ExchangeCodec.WriteVCard(input.RootElement).Text;
            }
        }
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
