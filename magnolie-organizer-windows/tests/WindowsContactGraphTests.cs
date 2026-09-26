using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using System.Xml;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsContactGraphTests
{
    // Explicitly opt-in, aggregate-only audit; never creates a provider or writes a profile.
    internal static async Task<int> AuditIdentityAsync(string path)
    {
        try
        {
            var data = JsonNode.Parse(await File.ReadAllTextAsync(path))!.AsObject();
            var cards = data["kontakte"]!.AsArray().OfType<JsonObject>().ToArray();
            var exact = cards.GroupBy(ContactFields.ContentHash).Where(group => group.Count() > 1).ToArray();
            var named = cards.Where(card => ContactFields.Text(card, "vorname").Length + ContactFields.Text(card, "nachname").Length > 0)
                .GroupBy(card => string.Join('\u001f', new[] { "vorname", "nachname", "firma" }
                    .Select(field => ContactFields.Text(card, field).ToUpperInvariant())))
                .Where(group => group.Count() > 1).ToArray();
            var patterns = named.Select(group => new
            {
                count = group.Count(),
                canonicalVersions = group.Select(ContactFields.ContentHash).Distinct().Count(),
                differentFields = ContactFields.Names.Where(field => group.Select(card =>
                    ContactFields.ContentHash(new JsonObject { [field] = card[field]?.DeepClone() })).Distinct().Count() > 1).ToArray()
            }).GroupBy(value => string.Join(',', value.differentFields)).Select(group => new
            {
                fields = group.Key,
                groups = group.Count(),
                cards = group.Sum(value => value.count),
                fullyEqual = group.Count(value => value.canonicalVersions == 1)
            });
            var conflicts = named.Select(group =>
            {
                var projections = group.Select(ContactFields.ContentProjection).ToArray();
                var fields = ContactFields.Names.Where(field =>
                {
                    var values = projections.Select(card => card[field]).Where(value => value is JsonValue).ToArray();
                    return values.Length > 1 && !values.Any(value => values.All(part => ContactFields.ContainsContent(value, part, field)));
                }).ToArray();
                return string.Join(',', fields);
            }).GroupBy(value => value).Select(group => new { fields = group.Key, groups = group.Count() });
            using var profile = System.Text.Json.JsonDocument.Parse(data.ToJsonString());
            var cleanup = ContactCleanupPlan.Create(profile.RootElement)["groups"]!.AsArray().OfType<JsonObject>().ToArray();
            var completeWithoutPhoto = named.Count(group => {
                var projections = group.Select(ContactFields.ContentProjection).ToArray();
                foreach (var projection in projections) projection.Remove("foto");
                return projections.Any(value => projections.All(part => ContactFields.ContainsContent(value, part, homeCountry: "DE")));
            });
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
            {
                contacts = cards.Length,
                identicalContentGroups = exact.Length,
                redundantIdenticalCards = exact.Sum(group => group.Count() - 1),
                sameNameGroups = named.Length,
                autoCleanupGroups = cleanup.Length,
                autoCleanupRecords = cleanup.Sum(group => group["ids"]!.AsArray().Count - 1),
                remoteCopiesToRemove = cleanup.Sum(group => group["deletions"]!.AsArray().Count),
                completeInformationWithoutPhotoGroups = completeWithoutPhoto,
                scalarConflictPatterns = conflicts,
                differencePatterns = patterns
            }));
            return 0;
        }
        catch (Exception error)
        {
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new { errorType = error.GetType().Name }));
            return 1;
        }
    }

    private sealed class YearlessUnsupportedRemote(params RemoteContact[] contacts) : IContactRemote
    {
        public bool SupportsYearlessBirthdays => false;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) =>
            Task.FromResult<IReadOnlyList<RemoteContact>>(contacts);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject data, CancellationToken token) => throw new InvalidOperationException();
        public Task<RemoteContact> UpdateAsync(RemoteContact old, string uid, JsonObject data, CancellationToken token) => throw new InvalidOperationException();
        public Task DeleteAsync(RemoteContact old, string uid, CancellationToken token) => throw new InvalidOperationException();
    }

    private static async Task TestPlaceholderBirthday(string root)
    {
        var store = new WindowsContactStore(Path.Combine(root, "birthday-placeholder"));
        var original = new JsonObject { ["id"] = "local", ["uid"] = "birthday-placeholder",
            ["vorname"] = "Mia", ["nachname"] = "Muster", ["geburtstag"] = "1604-02-29",
            ["geburtstagJahrUnbekannt"] = false, ["notiz"] = "Preserve this note" };
        var remote = await store.CreateAsync("birthday-placeholder", original, CancellationToken.None);
        var local = original.DeepClone().AsObject();
        ContactFields.SetSource(local, "windows-contacts", remote);
        var engine = new ContactSyncEngine();
        var result = await engine.SyncAsync("windows-contacts", new JsonArray(local), [], 0, store);
        TestAssert.That(result.Contacts.Count == 1 && result.Counts.Errors == 0 && result.Counts.Updated == 1 &&
            result.Contacts[0]!["geburtstag"]!.GetValue<string>() == "--02-29",
            "The mapped placeholder birthday was duplicated or not repaired.");
        var saved = (await store.ReadAsync(CancellationToken.None)).Single();
        TestAssert.That(ContactFields.Text(saved.Data, "geburtstag") == "--02-29" &&
            ContactFields.Text(saved.Data, "notiz") == "Preserve this note",
            "Birthday repair did not reach the source or discarded unrelated content.");
        var again = await engine.SyncAsync("windows-contacts", result.Contacts, result.Tombstones, 0, store);
        TestAssert.That(again.Contacts.Count == 1 && again.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "Repeating the birthday repair was not idempotent.");
        TestAssert.That(ContactFields.Text(original, "geburtstag") == "1604-02-29",
            "Synchronization mutated its input.");
        var importStore = new WindowsContactStore(Path.Combine(root, "birthday-import"));
        await importStore.CreateAsync("birthday-placeholder", original, CancellationToken.None);
        var additive = await engine.SyncAsync("windows-contacts", [], [], 0, importStore, additiveOnly: true);
        TestAssert.That(additive.Contacts[0]!["geburtstag"]!.GetValue<string>() == "--02-29" &&
            ContactFields.Text((await importStore.ReadAsync(CancellationToken.None)).Single().Data, "geburtstag") == "1604-02-29",
            "Additive import either leaked the placeholder or wrote to its source.");
        var imported = await engine.SyncAsync("windows-contacts", [], [], 0, importStore);
        TestAssert.That(imported.Contacts.Count == 1 && imported.Counts.Imported == 1 && imported.Counts.Updated == 1 &&
            imported.Counts.Errors == 0 && ContactFields.Text((await importStore.ReadAsync(CancellationToken.None)).Single().Data, "geburtstag") == "--02-29",
            "First bidirectional import did not repair the remote placeholder.");
        var unsupported = new YearlessUnsupportedRemote(remote);
        var projected = await engine.SyncAsync("microsoft-graph", [], [], 0, unsupported);
        var repeated = await engine.SyncAsync("microsoft-graph", projected.Contacts, [], 0, unsupported);
        TestAssert.That(projected.Counts.Errors == 0 && repeated.Counts == new ContactSyncCounts(0, 0, 0, 0, 0) &&
            repeated.Contacts[0]!["geburtstag"]!.GetValue<string>() == "--02-29",
            "A provider without yearless dates triggered repeated ineffective repair writes.");
    }

    private static async Task TestIdenticalContactBinding()
    {
        var source = "nextcloud-addressbook:" + new string('c', 64);
        var local = new JsonObject { ["id"] = "local", ["uid"] = "local-person",
            ["vorname"] = "Mia", ["nachname"] = "Muster", ["email"] = "mia@example.test" };
        var remoteData = local.DeepClone().AsObject(); remoteData["uid"] = "provider-person";
        var remote = new RemoteContact("card", "\"v1\"", 1, remoteData, true);
        // Every write throws, so success proves that an existing identical
        // provider record was bound rather than exported as another contact.
        var store = new YearlessUnsupportedRemote(remote);
        var engine = new ContactSyncEngine();
        var result = await engine.SyncAsync(source, new JsonArray(local), [], 0, store);
        TestAssert.That(result.Contacts.Count == 1 && result.Counts == new ContactSyncCounts(0, 0, 0, 0, 0) &&
            ContactFields.Source(result.Contacts[0]!.AsObject(), source)?["id"]?.GetValue<string>() == "card" &&
            ContactFields.Text(result.Contacts[0]!.AsObject(), "uid") == "local-person",
            "An identical cross-provider contact was duplicated or lost its local identity.");
        var again = await engine.SyncAsync(source, result.Contacts, [], 0, store);
        TestAssert.That(again.Contacts.Count == 1 && again.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "The confirmed source binding did not survive the next synchronization.");
        var unboundCopy = local.DeepClone().AsObject(); unboundCopy["id"] = "unbound-copy"; unboundCopy["uid"] = "copy-uid";
        var reserved = await engine.SyncAsync(source, new JsonArray(result.Contacts[0]!.DeepClone(), unboundCopy), [], 0, store);
        TestAssert.That(reserved.Contacts.Count == 2 && reserved.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "An equal local copy attempted to create another already-bound provider contact.");
        var duplicateBinding = result.Contacts[0]!.DeepClone().AsObject(); duplicateBinding["id"] = "duplicate-binding";
        var ambiguousBinding = await engine.SyncAsync(source, new JsonArray(result.Contacts[0]!.DeepClone(), duplicateBinding), [], 0, store);
        TestAssert.That(ambiguousBinding.Contacts.Count == 2 && ambiguousBinding.Counts.Exported == 0 && ambiguousBinding.Counts.Imported == 0,
            "An ambiguous local source binding created or imported another contact copy.");
        TestAssert.That(ContactFields.Source(local, source) is null && ContactFields.Text(remoteData, "uid") == "provider-person",
            "Source matching mutated the caller's input.");
        var phoneLocal = local.DeepClone().AsObject();
        phoneLocal["telefone"] = new JsonArray(new JsonObject { ["wert"] = "+49305550123",
            ["label"] = "", ["typen"] = new JsonArray("HOME") });
        var phoneRemote = phoneLocal.DeepClone().AsObject(); phoneRemote["uid"] = "provider-phone";
        phoneRemote["telefone"]![0]!["vcardParameter"] = new JsonArray();
        var phoneStore = new YearlessUnsupportedRemote(new RemoteContact("phone-card", "\"p1\"", 1, phoneRemote, true));
        var phoneMatch = await engine.SyncAsync(source, new JsonArray(phoneLocal), [], 0, phoneStore);
        TestAssert.That(phoneMatch.Contacts.Count == 1 && phoneMatch.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "Empty nested vCard parameters duplicated an otherwise identical phone contact.");
        var phoneAgain = await engine.SyncAsync(source, phoneMatch.Contacts, [], 0, phoneStore);
        TestAssert.That(phoneAgain.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "The normalized phone baseline caused a repeated write or conflict copy.");
        var treePhone = phoneLocal.DeepClone().AsObject();
        treePhone["telefone"]![0]!["typen"] = new JsonArray("CELL", "VOICE");
        treePhone["telefone"]![0]!["label"] = "Mobil";
        var accountPhone = treePhone.DeepClone().AsObject(); accountPhone["uid"] = "account-phone";
        accountPhone["anzeigename"] = "Mia Muster";
        accountPhone["telefone"]![0]!["label"] = "";
        accountPhone["telefone"]![0]!["typen"] = new JsonArray("CELL", "VOICE", "PREF");
        accountPhone["telefone"]![0]!["vcardParameter"] = new JsonArray();
        accountPhone["vcardRoundtrip"] = new JsonArray("N:Muster;Mia;;;", "FN:Mia Muster");
        var accountMatch = await engine.SyncAsync(source, new JsonArray(treePhone), [], 0,
            new YearlessUnsupportedRemote(new RemoteContact("account-card", "\"a1\"", 1, accountPhone, true)));
        TestAssert.That(accountMatch.Contacts.Count == 1 && accountMatch.Counts == new ContactSyncCounts(0, 0, 0, 0, 0),
            "Derived display names, standard phone labels and redundant vCard lines duplicated the same contact.");
        var customRemote = phoneRemote.DeepClone().AsObject();
        customRemote["telefone"]![0]!["vcardParameter"] = new JsonArray("X-KEEP=meaningful");
        var customMatch = await engine.SyncAsync(source, new JsonArray(phoneLocal.DeepClone()), [], 0,
            new YearlessUnsupportedRemote(new RemoteContact("custom-card", "\"c1\"", 1, customRemote, true)));
        TestAssert.That(ContactFields.Source(customMatch.Contacts[0]!.AsObject(), source) is null,
            "Meaningful preserved vCard parameters were ignored during identity comparison.");
        var ambiguous = remote with { Id = "second-card", Data = remoteData.DeepClone().AsObject() };
        ambiguous.Data["uid"] = "second-provider-person";
        var undecided = await engine.SyncAsync(source, new JsonArray(local.DeepClone()), [], 0,
            new YearlessUnsupportedRemote(remote, ambiguous));
        TestAssert.That(ContactFields.Source(undecided.Contacts[0]!.AsObject(), source) is null,
            "Ambiguous provider matches were silently assigned to one person.");
        var knownUid = local.DeepClone().AsObject(); knownUid["uid"] = "provider-person";
        var identified = await engine.SyncAsync(source, new JsonArray(knownUid), [], 0,
            new YearlessUnsupportedRemote(remote, ambiguous));
        TestAssert.That(identified.Counts.Errors == 0 && identified.Counts.Exported == 0 &&
            ContactFields.Source(identified.Contacts[0]!.AsObject(), source)?["id"]?.GetValue<string>() == "card",
            "A stable provider UID did not take precedence over another content-identical record.");
        var namedOnly = new JsonObject { ["id"] = "named", ["uid"] = "local-name", ["vorname"] = "Mia", ["emails"] = new JsonArray("") };
        var namedRemote = namedOnly.DeepClone().AsObject(); namedRemote["uid"] = "remote-name";
        var sameName = await engine.SyncAsync(source, new JsonArray(namedOnly), [], 0,
            new YearlessUnsupportedRemote(new RemoteContact("named-card", "\"n1\"", 1, namedRemote, true)));
        TestAssert.That(ContactFields.Source(sameName.Contacts[0]!.AsObject(), source) is null,
            "Names alone or empty contact-detail lists silently identified a person.");
        var batch = new JsonArray(); var batchRemote = new List<RemoteContact>();
        for (var index = 0; index < 1000; index++)
        {
            var contact = new JsonObject { ["id"] = "local-" + index, ["uid"] = "local-uid-" + index,
                ["vorname"] = "Contact " + index, ["email"] = "contact" + index + "@example.test" };
            batch.Add(contact);
            var counterpart = contact.DeepClone().AsObject(); counterpart["uid"] = "provider-uid-" + index;
            batchRemote.Add(new RemoteContact("remote-" + index, "\"v1\"", 1, counterpart, true));
        }
        var timer = System.Diagnostics.Stopwatch.StartNew();
        var bulk = await engine.SyncAsync(source, batch, [], 0, new YearlessUnsupportedRemote(batchRemote.ToArray()));
        TestAssert.That(bulk.Contacts.Count == 1000 && bulk.Counts == new ContactSyncCounts(0, 0, 0, 0, 0) &&
            bulk.Contacts.OfType<JsonObject>().All(item => ContactFields.Source(item, source) is not null),
            "Bulk matching duplicated contacts, omitted source bindings, or attempted a source write.");
        Console.WriteLine($"  Identical cross-provider contacts: 1000 bound in {timer.ElapsedMilliseconds} ms, no source writes.");
    }

    private static async Task TestContactCleanupPlan()
    {
        var source = "thunderbird-addressbook:managed:fixture:book";
        var tree = new JsonObject { ["id"] = "tree", ["uid"] = "mag-tree@magnolie-organizer", ["vorname"] = "Mia", ["nachname"] = "Muster",
            ["email"] = "mia@example.test", ["baumKontakt"] = new JsonObject { ["freigabeId"] = "share", ["version"] = 1L } };
        var original = tree.DeepClone().AsObject(); original["id"] = "local-provider"; original["uid"] = "provider-original"; original.Remove("baumKontakt");
        var redundant = new RemoteContact("redundant", "\"d1\"", 1, tree.DeepClone().AsObject(), true);
        var provider = new RemoteContact("original", "\"o1\"", 1, original.DeepClone().AsObject(), true);
        ContactFields.SetSource(tree, source, redundant); ContactFields.SetSource(original, source, provider);
        var profile = new JsonObject { ["kontakte"] = new JsonArray(tree, original),
            ["einstellungen"] = new JsonObject { ["sync"] = new JsonObject { ["adressbuchUid"] = source } } };
        var before = profile.ToJsonString();
        using var input = System.Text.Json.JsonDocument.Parse(before);
        var plan = ContactCleanupPlan.Create(input.RootElement);
        TestAssert.That(profile.ToJsonString() == before && plan["groups"]!.AsArray().Count == 1,
            "Cleanup planning changed its input or missed the identical source copies.");
        var group = plan["groups"]![0]!.AsObject();
        TestAssert.That(group["keepId"]!.GetValue<string>() == "tree" && group["mapping"]!["id"]!.GetValue<string>() == "original",
            "Cleanup must retain the local tree identity and the provider's original record.");
        var local = tree.DeepClone().AsObject();
        foreach (var pair in group["metadata"]!.AsObject()) local[pair.Key] = pair.Value?.DeepClone();
        var deletion = group["deletions"]![0]!.AsObject();
        var tombstone = new JsonObject { ["uid"] = "mag-cleanup-marker@magnolie-organizer", ["zeit"] = 1,
            ["syncQuellen"] = new JsonObject { [source] = deletion["mapping"]!.DeepClone() },
            ["kontaktDuplikat"] = new JsonObject { ["source"] = source, ["keeperId"] = deletion["keeperId"]!.DeepClone(),
                ["contentHash"] = deletion["contentHash"]!.DeepClone(),
                ["keeperHash"] = deletion["keeperHash"]!.DeepClone(), ["desiredHash"] = deletion["desiredHash"]!.DeepClone() } };
        var saved = profile.DeepClone().AsObject();
        saved["kontakte"] = new JsonArray(local.DeepClone());
        saved["papierkorb"] = new JsonArray(new JsonObject { ["id"] = "trash", ["art"] = "duplicate", ["eintrag"] = original.DeepClone() });
        saved["geloescht"] = new JsonObject { ["kontakte"] = new JsonArray(tombstone.DeepClone()) };
        var snapshots = new ContactCleanupSnapshot();
        snapshots.Planned(plan); snapshots.Snapshotted(profile); snapshots.Saved(saved.ToJsonString());
        TestAssert.That(snapshots.Consume(saved.ToJsonString(), source) && !snapshots.Consume(saved.ToJsonString(), source),
            "The cleanup snapshot was not reusable exactly once for its following synchronization.");
        var unrelated = saved.DeepClone().AsObject(); unrelated["notizen"] = new JsonArray(new JsonObject { ["id"] = "new", ["text"] = "New independent edit" });
        snapshots.Planned(plan); snapshots.Snapshotted(profile); snapshots.Saved(unrelated.ToJsonString());
        TestAssert.That(!snapshots.Consume(unrelated.ToJsonString(), source), "An unrelated edit incorrectly reused a cleanup snapshot.");
        var acknowledgedCleanup = saved.DeepClone().AsObject();
        acknowledgedCleanup["geloescht"]!["kontakte"] = new JsonArray();
        TestAssert.That(!RecoveryJournal.HasRecoverableChanges(saved, acknowledgedCleanup),
            "Acknowledging technical duplicate-deletion markers created another content snapshot.");
        var presentation = local.DeepClone().AsObject(); presentation["anzeigename"] = "Mia Muster";
        presentation["vcardRoundtrip"] = new JsonArray("N:Muster;Mia;;;", "FN:Mia Muster");
        var presentationOnly = saved.DeepClone().AsObject(); presentationOnly["kontakte"] = new JsonArray(presentation);
        TestAssert.That(!RecoveryJournal.HasRecoverableChanges(saved, presentationOnly),
            "A redundant provider display-name projection created another contact snapshot.");
        presentationOnly["kontakte"]![0]!["notiz"] = "Actual content change";
        TestAssert.That(RecoveryJournal.HasRecoverableChanges(saved, presentationOnly), "A real contact edit lost its recovery boundary.");
        foreach (var variant in new[] { "success", "changed-duplicate", "changed-original", "missing-original", "already-removed" })
        {
            var remote = new CleanupContactRemote();
            if (variant != "missing-original") remote.Items[provider.Id] = provider with { Data = provider.Data.DeepClone().AsObject() };
            if (variant != "already-removed") remote.Items[redundant.Id] = redundant with { ETag = "\"current\"", Data = redundant.Data.DeepClone().AsObject() };
            if (variant == "changed-duplicate") remote.Items[redundant.Id].Data["notiz"] = "Concurrent actual edit";
            if (variant == "changed-original") remote.Items[provider.Id].Data["notiz"] = "Concurrent actual edit";
            var engine = new ContactSyncEngine();
            if (variant is "changed-duplicate" or "changed-original" or "missing-original")
            {
                await TestAssert.ThrowsAsync<InvalidOperationException>(async () =>
                    await engine.SyncAsync(source, new JsonArray(local.DeepClone()), new JsonArray(tombstone.DeepClone()), 0, remote),
                    "A changed or missing original must prevent duplicate deletion.");
                TestAssert.That(remote.Writes == 0, "A failed cleanup proof still wrote to its source.");
                continue;
            }
            var result = await engine.SyncAsync(source, new JsonArray(local.DeepClone()), new JsonArray(tombstone.DeepClone()), 0, remote);
            TestAssert.That(result.Contacts.Count == 1 && result.Tombstones.Count == 0 && remote.Items.Count == 1 && remote.Items.ContainsKey("original"),
                "Cleanup removed the original or left a deletion pending after confirmation.");
            TestAssert.That(remote.Writes == (variant == "success" ? 1 : 0), "Cleanup created or updated a contact unnecessarily.");
            var repeated = await engine.SyncAsync(source, result.Contacts, result.Tombstones, 0, remote);
            TestAssert.That(repeated.Counts == new ContactSyncCounts(0, 0, 0, 0, 0), "Cleanup replay was not idempotent.");
        }
        var protectedRemote = new CleanupContactRemote();
        protectedRemote.Items[provider.Id] = provider; protectedRemote.Items[redundant.Id] = redundant;
        await TestAssert.ThrowsAsync<IOException>(async () => await new ContactSyncEngine().SyncAsync(source,
            new JsonArray(local.DeepClone()), new JsonArray(tombstone.DeepClone()), 0, protectedRemote,
            beforeMutation: () => Task.FromException(new IOException("Snapshot fixture failure"))),
            "A failed recovery snapshot must stop before the first provider mutation.");
        TestAssert.That(protectedRemote.Writes == 0, "A provider was written despite failed snapshot creation.");
        var syncBefore = new JsonObject { ["syncEpoch"] = "epoch", ["kontakte"] = new JsonArray(local.DeepClone()),
            ["termine"] = new JsonArray(), ["aufgaben"] = new JsonArray(), ["jahrestage"] = new JsonArray(),
            ["geloescht"] = new JsonObject(), ["letzterSync"] = 1, ["letzteSyncs"] = new JsonObject(), ["syncMetadaten"] = new JsonObject() };
        var syncResult = syncBefore.DeepClone().AsObject(); syncResult["kontakte"]![0]!["notiz"] = "Incoming actual edit";
        syncResult["transactionId"] = "transaction";
        var savedResult = syncResult.DeepClone().AsObject();
        savedResult.Remove("transactionId");
        savedResult["syncAbgleichNachweis"] = new JsonObject { ["transactionId"] = "transaction" };
        var handoff = new SyncSnapshotHandoff(); handoff.Completed("transaction", syncResult, snapshotExists: true);
        TestAssert.That(handoff.CoversSave(syncBefore, savedResult), "A completed sync did not reuse its pre-mutation snapshot.");
        savedResult["notizen"] = new JsonArray(new JsonObject { ["id"] = "independent", ["text"] = "Local note edit" });
        TestAssert.That(!handoff.CoversSave(syncBefore, savedResult), "Independent local edits incorrectly reused a sync snapshot.");
        savedResult.Remove("notizen"); handoff.Saved();
        TestAssert.That(!handoff.CoversSave(syncBefore, savedResult), "A consumed sync snapshot was reused by another save.");
        profile["syncNachRestore"] = new JsonObject { ["additiv"] = true };
        using var restored = System.Text.Json.JsonDocument.Parse(profile.ToJsonString());
        TestAssert.That(ContactCleanupPlan.Create(restored.RootElement)["groups"]!.AsArray().Count == 0,
            "Additive restoration was turned into a destructive cleanup.");
        profile.Remove("syncNachRestore");
        original["geburtstag"] = "--02-29"; original["geburtstagJahrUnbekannt"] = true;
        using var enriched = System.Text.Json.JsonDocument.Parse(profile.ToJsonString());
        var enrichedPlan = ContactCleanupPlan.Create(enriched.RootElement);
        TestAssert.That(enrichedPlan["groups"]!.AsArray().Count == 1 &&
            enrichedPlan["groups"]![0]!["contentFromId"]!.GetValue<string>() == "local-provider",
            "A missing birthday prevented lossless enrichment from the more complete contact.");
        tree["geburtstag"] = "1980-02-28";
        using var conflicting = System.Text.Json.JsonDocument.Parse(profile.ToJsonString());
        TestAssert.That(ContactCleanupPlan.Create(conflicting.RootElement)["groups"]!.AsArray().Count == 0,
            "Contradictory actual birthdays were silently merged.");
        TestAssert.That(ContactFields.ContainsContent(JsonValue.Create("1980-02-29"), JsonValue.Create("--02-29"), "geburtstag") &&
            !ContactFields.ContainsContent(JsonValue.Create("1981-02-28"), JsonValue.Create("--02-29"), "geburtstag"),
            "Birthday precision refinement lost or invented a date.");
    }

    private sealed class CleanupContactRemote : IContactRemote
    {
        internal readonly Dictionary<string, RemoteContact> Items = new();
        internal int Writes;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) => Task.FromResult<IReadOnlyList<RemoteContact>>(Items.Values.ToArray());
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken token) { Writes++; throw new InvalidOperationException("Unexpected create"); }
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken token) { Writes++; throw new InvalidOperationException("Unexpected update"); }
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken token)
        {
            TestAssert.That(remote.ETag == Items[remote.Id].ETag, "Cleanup used a stale deletion revision.");
            Writes++; Items.Remove(remote.Id); return Task.CompletedTask;
        }
    }

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-contacts-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var store = new WindowsContactStore(root);
            await TestContactConflicts(root);
            await TestPlaceholderBirthday(root);
            await TestIdenticalContactBinding();
            await TestContactCleanupPlan();
            TestNativeContactFields();
            var contact = new JsonObject { ["vorname"] = "Änne", ["nachname"] = "Beispiel", ["email"] = "a@example.test" };
            var stableOne = WindowsContactStore.StableImportUid("Anna.contact", "");
            var stableTwo = WindowsContactStore.StableImportUid("Anna.contact", "");
            TestAssert.That(stableOne == stableTwo && stableOne.StartsWith("urn:magnolie:import:windows-contact:", StringComparison.Ordinal),
                "Der einmalige Windows-Import erzeugte keine idempotente namespaced Bindung.");
            TestAssert.That(WindowsContactStore.StableImportUid("Anna.contact", "mag-eingebettet") == "mag-eingebettet" &&
                WindowsContactStore.StableImportUid("Anna.contact", "ungueltig\n") == stableOne,
                "Eine gültige eingebettete Magnolie-UID hatte keinen Vorrang oder eine ungültige wurde übernommen.");
            var importManifest = new JsonObject { ["art"] = "kontakt_import_manifest", ["fassung"] = 1,
                ["importId"] = Guid.Empty.ToString(), ["anzahl"] = 1,
                ["herkuenfte"] = new JsonArray(new JsonObject { ["kontoTyp"] = "type", ["kontoName"] = "Privat", ["dataSet"] = "", ["anzahl"] = 1 }) };
            BaumContactSyncContract.ValidateImport(importManifest, "kontakt_import_manifest");
            var importCard = new JsonObject { ["art"] = "kontakt_import_karte", ["fassung"] = 1,
                ["importId"] = Guid.Empty.ToString(), ["bindung"] = "urn:magnolie:import:android:" + new string('a', 64),
                ["herkuenfte"] = new JsonArray(new JsonObject { ["kontoTyp"] = "type", ["kontoName"] = "Privat", ["dataSet"] = "" }),
                ["kontakt"] = new JsonObject { ["vorname"] = "Ada", ["nachname"] = "", ["firma"] = "", ["notiz"] = "",
                    ["geburtstag"] = "", ["telefone"] = new JsonArray(), ["emailEintraege"] = new JsonArray(), ["anschriften"] = new JsonArray() } };
            BaumContactSyncContract.ValidateImport(importCard, "kontakt_import_karte");
            var uppercaseBinding = importCard.DeepClone().AsObject();
            uppercaseBinding["bindung"] = "urn:magnolie:import:android:" + new string('A', 64);
            TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.ValidateImport(uppercaseBinding, "kontakt_import_karte"),
                "Der Windows-Import akzeptierte eine plattformfremde grossgeschriebene Bindung.");
            var fractionalSync = new JsonObject { ["art"] = "kontakt_sync", ["fassung"] = 1,
                ["freigabeId"] = "import-test", ["version"] = 1.0, ["quelle"] = "test", ["geaendert"] = 0,
                ["kontakt"] = importCard["kontakt"]!.DeepClone() };
            TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(fractionalSync),
                "Der Kontaktvertrag akzeptierte eine Fließkommazahl als Version.");
            var deleteCard = importCard.DeepClone().AsObject(); deleteCard["loeschen"] = true;
            try { BaumContactSyncContract.ValidateImport(deleteCard, "kontakt_import_karte"); throw new InvalidOperationException("Importkarte akzeptierte eine Löschanweisung."); }
            catch (InvalidDataException) { }
            await TestAssert.ThrowsAsync<IOException>(() => store.UpdateAsync(
                    new RemoteContact("../fremd.contact", "", 0, contact, true), "uid", contact, CancellationToken.None),
                "Windows Contacts akzeptierte Pfadtraversal als Remote-ID.");

            var yearless = contact.DeepClone().AsObject(); yearless["geburtstag"] = "--02-29";
            var yearlessXml = WindowsContactStore.Serialize(yearless, "yearless");
            TestAssert.That(!yearlessXml.Contains("DateCollection", StringComparison.Ordinal) &&
                yearlessXml.Contains("Birthday>--02-29</", StringComparison.Ordinal) &&
                WindowsContactStore.Parse(yearlessXml)["geburtstag"]!.GetValue<string>() == "--02-29",
                "Windows Contacts projizierte ein jahrloses Datum oder verlor die Magnolie-Erweiterung.");
            var full = contact.DeepClone().AsObject(); full["geburtstag"] = "2000-02-29";
            var fullXml = WindowsContactStore.Serialize(full, "full");
            TestAssert.That(fullXml.Contains("DateCollection", StringComparison.Ordinal) &&
                !fullXml.Contains("Birthday>--", StringComparison.Ordinal) &&
                WindowsContactStore.Parse(fullXml)["geburtstag"]!.GetValue<string>() == "2000-02-29",
                "Windows Contacts bewahrte einen echten Geburtstag aus 2000 nicht als volles Datum.");
            TestAssert.That(!GraphApiClient.ToGraph(yearless).ContainsKey("birthday") &&
                GraphApiClient.ToGraph(full)["birthday"]!.GetValue<string>() == "2000-02-29T00:00:00Z",
                "Graph erhielt ein fingiertes Jahr für ein jahrloses Datum oder verlor das echte Jahr 2000.");
            var mergeTarget = yearless.DeepClone().AsObject();
            ContactFields.CopyRemoteFields(mergeTarget, new JsonObject { ["vorname"] = "Remote" });
            TestAssert.That(mergeTarget["geburtstag"]!.GetValue<string>() == "--02-29",
                "Ein Provider ohne Geburtstagsfeld löschte das lokale jahrlose Datum.");
            ContactFields.CopyRemoteFields(mergeTarget, new JsonObject { ["geburtstag"] = "" });
            TestAssert.That(mergeTarget["geburtstag"]!.GetValue<string>() == "--02-29",
                "Ein leeres Provider-Geburtstagsfeld löschte das lokale Datum.");
            using (var graph2000 = System.Text.Json.JsonDocument.Parse("""{"id":"genuine","birthday":"2000-02-29T00:00:00Z"}"""))
                TestAssert.That(GraphApiClient.ParseContact(graph2000.RootElement).Data["geburtstag"]!.GetValue<string>() == "2000-02-29",
                    "Graph interpretierte ein externes Jahr 2000 als unbekannt.");

            var oversized = Path.Combine(root, "gross.contact");
            await using (var stream = File.Create(oversized)) stream.SetLength(2 * 1024 * 1024 + 1);
            await TestAssert.ThrowsAsync<IOException>(async () => { _ = await store.ReadAsync(CancellationToken.None); },
                "An oversized Windows contact was treated as an absent contact.");
            File.Delete(oversized);
            var unreadable = Path.Combine(root, "person.contact");
            File.WriteAllText(unreadable, "<broken");
            var mapped = new JsonArray(new JsonObject { ["id"] = "local", ["uid"] = "person", ["geaendert"] = 1L,
                ["syncQuellen"] = new JsonObject { ["windows-contacts"] = new JsonObject { ["id"] = "person.contact", ["etag"] = "old" } } });
            var before = mapped.ToJsonString();
            await TestAssert.ThrowsAsync<XmlException>(async () => { _ = await new ContactSyncEngine().SyncAsync("windows-contacts", mapped, [], 100, store); },
                "An incomplete Windows source snapshot deleted a mapped local contact.");
            TestAssert.That(mapped.ToJsonString() == before && File.ReadAllText(unreadable) == "<broken", "Failed source read mutated contact data.");

            var requests = new List<(HttpMethod Method, string Uri, string Authorization, string IfMatch, string Body)>();
            var handler = new RecordingHttpHandler(async request =>
            {
                var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync();
                requests.Add((request.Method, request.RequestUri!.ToString(), request.Headers.Authorization?.ToString() ?? "",
                    request.Headers.TryGetValues("If-Match", out var values) ? values.Single() : "", body));
                return request.Method == HttpMethod.Post
                    ? Json(HttpStatusCode.Created, "{\"id\":\"created/id\",\"givenName\":\"Änne\",\"lastModifiedDateTime\":\"2026-08-11T10:00:00Z\"}")
                    : new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"next\"") } };
            });
            using var http = new HttpClient(handler);
            var graph = new GraphApiClient(http, "access-test");
            TestAssert.That(!graph.SupportsYearlessBirthdays, "Graph advertised unsupported yearless birthday writes.");
            var made = await graph.CreateAsync("uid", contact, CancellationToken.None);
            await graph.UpdateAsync(made with { ETag = "\"old\"" }, "uid", contact, CancellationToken.None);
            await graph.DeleteAsync(made with { ETag = "\"next\"" }, "uid", CancellationToken.None);
            TestAssert.That(requests.Count == 3 && requests.All(item => item.Authorization == "Bearer access-test") &&
                requests[1].Method == HttpMethod.Patch && requests[1].IfMatch == "\"old\"" &&
                requests[2].Method == HttpMethod.Delete && requests[2].Uri.EndsWith("created%2Fid", StringComparison.Ordinal),
                "Graph Create/Update/Delete übertrug Authentisierung, ETag oder escaped ID nicht korrekt.");
            TestAssert.That(JsonNode.Parse(requests[0].Body)?["givenName"]?.GetValue<string>() == "Änne" && made.Id == "created/id",
                "Graph verlor Unicode-Kontaktdaten beim Erstellen.");

            var fake = new FakeContactRemote();
            var old = new JsonObject { ["uid"] = "old", ["geaendert"] = 1,
                ["syncQuellen"] = new JsonObject { ["fake"] = new JsonObject { ["id"] = "missing", ["eigen"] = true } } };
            var tombstone = old.DeepClone().AsObject();
            var additiveResult = await new ContactSyncEngine().SyncAsync("fake", new JsonArray(old),
                new JsonArray(tombstone), 100, fake, additiveOnly: true);
            TestAssert.That(additiveResult.Contacts.Count == 1 && additiveResult.Tombstones.Count == 1 && fake.Deletes == 0,
                "Erster Sync nach Restore war nicht additiv und löschungsfrei.");
            var partial = new FailingContactRemote();
            var changedLocal = old.DeepClone().AsObject(); changedLocal["geaendert"] = 200L;
            changedLocal["syncQuellen"]!["fake"]!["id"] = "remote";
            changedLocal["syncQuellen"]!["fake"]!["etag"] = "\"old\"";
            var deleteCandidate = old.DeepClone().AsObject(); deleteCandidate["syncQuellen"]!["fake"]!["id"] = "delete";
            var partialResult = await new ContactSyncEngine().SyncAsync("fake", new JsonArray(changedLocal), new JsonArray(deleteCandidate), 100, partial);
            TestAssert.That(partialResult.Counts.Errors == 1 && partial.Deletes == 0,
                "Ein partiell fehlgeschlagener Kontaktlauf führte eine Remote-Löschung aus.");
            var birthdayRemote = new BirthdayRepairRemote();
            var birthdayLocal = new JsonObject { ["uid"] = "birthday", ["geburtstag"] = "1980-04-03", ["geaendert"] = 10L,
                ["syncQuellen"] = new JsonObject { ["fake"] = new JsonObject { ["id"] = "birthday", ["etag"] = "\"same\"", ["eigen"] = true } } };
            var birthdayResult = await new ContactSyncEngine().SyncAsync("fake", new JsonArray(birthdayLocal), new JsonArray(), 100, birthdayRemote);
            TestAssert.That(birthdayRemote.Updates == 1 && birthdayRemote.Birthday == "1980-04-03" &&
                birthdayResult.Contacts[0]?["geburtstag"]?.GetValue<string>() == "1980-04-03",
                "Ein beim Provider fehlender Geburtstag wurde nicht aus dem lokalen Bestand repariert.");

            using var badNextHttp = new HttpClient(new RecordingHttpHandler(_ => Task.FromResult(Json(HttpStatusCode.OK,
                "{\"value\":[],\"@odata.nextLink\":\"https://attacker.invalid/steal\"}"))));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new GraphApiClient(badNextHttp, "secret").ReadAsync(CancellationToken.None),
                "Graph folgte einem fremden OAuth-Paginationsziel.");
            var pageCalls = 0;
            using var endlessGraphHttp = new HttpClient(new RecordingHttpHandler(_ =>
            {
                pageCalls++;
                return Task.FromResult(Json(HttpStatusCode.OK,
                    "{\"value\":[],\"@odata.nextLink\":\"https://graph.microsoft.com/v1.0/me/contacts?page=next\"}"));
            }));
            await TestAssert.ThrowsAsync<InvalidDataException>(() =>
                    new GraphApiClient(endlessGraphHttp, "secret").ReadAsync(CancellationToken.None),
                "Graph behandelte einen nach 100 Seiten abgeschnittenen Kontaktbestand als vollständig.");
            TestAssert.That(pageCalls == 100, "Die Graph-Seitengrenze wurde nicht deterministisch eingehalten.");

            using var oauthHttp = new HttpClient(new RecordingHttpHandler(async request =>
            {
                var form = await request.Content!.ReadAsStringAsync();
                TestAssert.That(form.Contains("refresh_token=refresh-test", StringComparison.Ordinal) &&
                    form.Contains("Contacts.ReadWrite", StringComparison.Ordinal), "OAuth-Refresh sendete nicht den vereinbarten Scope.");
                return Json(HttpStatusCode.OK, "{\"access_token\":\"access-new\",\"refresh_token\":\"refresh-new\",\"expires_in\":3600}");
            }));
            var token = await new MicrosoftOAuthClient(oauthHttp).RefreshAsync(Guid.Empty.ToString(), "refresh-test", CancellationToken.None);
            TestAssert.That(token.AccessToken == "access-new" && token.RefreshToken == "refresh-new", "OAuth-Refresh-Antwort wurde falsch gelesen.");
            try { OAuthResponseParser.DeviceCode("{\"device_code\":\"x\",\"user_code\":\"y\",\"verification_uri\":\"http://unsafe.test\"}");
                throw new InvalidOperationException("OAuth akzeptierte eine unverschlüsselte Verifikationsadresse."); }
            catch (InvalidDataException) { }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string value) => new(status)
    {
        Content = new StringContent(value, Encoding.UTF8, "application/json")
    };

    private static void TestNativeContactFields()
    {
        foreach (var date in new[] { "--02-29", "--06-07", "2000-02-29", "1980-06-07" })
        {
            var value = new JsonObject { ["vorname"] = "", ["nachname"] = "", ["anzeigename"] = "Van Dame",
                ["geburtstag"] = date, ["jubilaeum"] = date };
            for (var round = 0; round < 2; round++) value = WindowsContactStore.Parse(WindowsContactStore.Serialize(value, "native"));
            TestAssert.That(ContactFields.Text(value, "vorname") == "" && ContactFields.Text(value, "nachname") == "" &&
                ContactFields.Text(value, "anzeigename") == "Van Dame" && ContactFields.Text(value, "geburtstag") == date &&
                ContactFields.Text(value, "jubilaeum") == date && value["geburtstagJahrUnbekannt"]!.GetValue<bool>() == date.StartsWith("--", StringComparison.Ordinal),
                "The native contact extension lost display-only names or full/yearless occasions.");
        }
        var unknown = WindowsContactStore.Parse(WindowsContactStore.Serialize(new JsonObject { ["vorname"] = "Anna Maria", ["nachname"] = "",
            ["geburtstag"] = "1604-02-29", ["geburtstagJahrUnbekannt"] = true,
            ["jubilaeum"] = "2000-06-07", ["jubilaeumJahrUnbekannt"] = true }, "unknown"));
        TestAssert.That(ContactFields.Text(unknown, "nachname") == "" && ContactFields.Text(unknown, "geburtstag") == "--02-29" &&
            ContactFields.Text(unknown, "jubilaeum") == "--06-07", "Explicit unknown-year flags or missing family name were changed.");
        ContactFields.CopyRemoteFields(unknown, new JsonObject { ["vorname"] = "Anna Maria" });
        TestAssert.That(ContactFields.Text(unknown, "jubilaeum") == "--06-07" && unknown["jubilaeumJahrUnbekannt"]!.GetValue<bool>(),
            "A provider without anniversary support erased the local/native occasion.");
    }

    private static async Task TestContactConflicts(string root)
    {
        var remote = new MutableContactRemote();
        remote.Items["remote"] = new RemoteContact("remote", "v2", 10, new JsonObject { ["uid"] = "person", ["vorname"] = "REMOTE" }, true);
        JsonArray Local(long modified, bool edited = false)
        {
            var contact = new JsonObject { ["id"] = "local", ["uid"] = "person", ["vorname"] = edited ? "BASE" : "LOCAL", ["geaendert"] = modified };
            ContactFields.SetSource(contact, "cards", new RemoteContact("remote", "v1", 10, contact.DeepClone().AsObject(), true));
            contact["vorname"] = "LOCAL";
            return new JsonArray(contact);
        }
        var result = await new ContactSyncEngine().SyncAsync("cards", Local(20), [], 30, remote);
        TestAssert.That(result.Contacts.Count == 1 && ContactFields.Text(result.Contacts[0]!.AsObject(), "vorname") == "REMOTE" && remote.Writes == 0,
            "A stale REV won over an ETag-only remote edit.");
        result = await new ContactSyncEngine().SyncAsync("cards", Local(200), [], 100, remote);
        TestAssert.That(result.Contacts.Count == 1 && ContactFields.Text(result.Contacts[0]!.AsObject(), "vorname") == "REMOTE" && remote.Writes == 0,
            "An unchanged content baseline was treated as a local edit because of its clock.");
        var legacy = Local(20);
        var legacyMapping = ContactFields.Source(legacy[0]!.AsObject(), "cards")!;
        legacyMapping.Remove("inhaltFormat"); legacyMapping.Remove("inhaltSha256");
        result = await new ContactSyncEngine().SyncAsync("cards", legacy, [], 100, remote);
        TestAssert.That(result.Contacts.Count == 1 && remote.Writes == 0 && result.Counts.Errors == 0 && result.Counts.Conflicts == 1 &&
            result.Contacts[0]!["vorname"]!.GetValue<string>() == "LOCAL" &&
            result.Contacts[0]!["syncKonflikte"]!["cards"]!["kontakt"]!["vorname"]!.GetValue<string>() == "REMOTE",
            "A changed remote revision without a legacy baseline discarded uncertain local content.");
        result = await new ContactSyncEngine().SyncAsync("cards", Local(20, edited: true), [], 100, remote);
        TestAssert.That(result.Contacts.Count == 1 && result.Counts.Errors == 0 && result.Counts.Conflicts == 1,
            "Concurrent contact versions must remain decisions on one existing person.");
        for (var followup = 0; followup < 2; followup++)
        {
            var file = Path.Combine(root, "contact-conflict.json");
            new AtomicStore().WriteRecoverableJson(file, new JsonObject { ["items"] = result.Contacts.DeepClone() }.ToJsonString());
            var saved = JsonNode.Parse(new AtomicStore().ReadRecoverableJson(file)!)!["items"]!.AsArray();
            result = await new ContactSyncEngine().SyncAsync("cards", saved, [], 300 + followup, remote);
            TestAssert.That(result.Contacts.Count == 1 && result.Contacts[0]!["vorname"]!.GetValue<string>() == "LOCAL" &&
                result.Contacts[0]!["syncKonflikte"]!["cards"]!["kontakt"]!["vorname"]!.GetValue<string>() == "REMOTE" &&
                ContactFields.Source(result.Contacts[0]!.AsObject(), "cards")!["id"]!.GetValue<string>() == "remote",
                "Persisted contact conflict lost a version or created another person.");
        }
        TestAssert.That(remote.Writes == 0, "Unresolved contact conflicts must not be exported as new people.");
    }

    private sealed class MutableContactRemote : IContactRemote
    {
        internal readonly Dictionary<string, RemoteContact> Items = new();
        internal int Writes;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) => Task.FromResult<IReadOnlyList<RemoteContact>>(Items.Values.ToArray());
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken token)
        {
            Writes++; var value = new RemoteContact(uid, "created", contact["geaendert"]!.GetValue<long>(), contact.DeepClone().AsObject(), true);
            Items[uid] = value; return Task.FromResult(value);
        }
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken token) { Writes++; throw new InvalidOperationException("Unexpected update"); }
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken token) => throw new InvalidOperationException("Unexpected delete");
    }

    private sealed class RecordingHttpHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request);
    }

    private sealed class FakeContactRemote : IContactRemote
    {
        internal int Deletes { get; private set; }
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>(Array.Empty<RemoteContact>());
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => Task.FromResult(new RemoteContact(Guid.NewGuid().ToString(), "", 1, contact, true));
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken) => Task.FromResult(remote);
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) { Deletes++; return Task.CompletedTask; }
    }

    private sealed class FailingContactRemote : IContactRemote
    {
        internal int Deletes { get; private set; }
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>([
            new RemoteContact("remote", "\"old\"", 1, new JsonObject { ["vorname"] = "Alt" }, true),
            new RemoteContact("delete", "\"delete\"", 1, new JsonObject { ["vorname"] = "Löschen" }, true)]);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => throw new IOException("partial");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken) => throw new IOException("partial");
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) { Deletes++; return Task.CompletedTask; }
    }

    private sealed class BirthdayRepairRemote : IContactRemote
    {
        internal int Updates { get; private set; }
        internal string Birthday { get; private set; } = "";
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>([
            new RemoteContact("birthday", "\"same\"", 200, new JsonObject { ["uid"] = "birthday" }, true)]);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => throw new InvalidOperationException();
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
        {
            Updates++;
            Birthday = contact["geburtstag"]?.GetValue<string>() ?? "";
            return Task.FromResult(remote with { Data = contact.DeepClone().AsObject() });
        }
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) => throw new InvalidOperationException();
    }
}
