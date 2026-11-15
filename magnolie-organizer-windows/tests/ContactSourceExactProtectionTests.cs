using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class ContactSourceUpdateRunTests
{
    internal static async Task ExactProtectionAsync()
    {
        // Actual native SaveAsync -> exact primary/journal/readback guard -> DAV
        // session. The original generic callback's six RED variants are retained
        // in private evidence; this is the linked production protection helper.
        var failures = new List<string>();
        foreach (var mode in new[] { "schema6", "recent-different", "metadata-dedupe", "already-exact", "fractional" })
        foreach (var encrypted in new[] { false, true })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var source = new Source("exact-protection", "generic-dav", original);
            var remote = await source.OriginalAsync(); var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, source.Catalog.Uid, remote, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var document = new JsonObject { ["version"] = mode == "schema6" ? 6 : 7, ["kontakte"] = new JsonArray(local),
                ["notizen"] = new JsonArray(new JsonObject { ["id"] = "unrelated-note", ["text"] = "Keep original note" }),
                ["einstellungen"] = new JsonObject { ["allgemein"] = new JsonObject {
                    ["wiederherstellungsmodus"] = mode == "metadata-dedupe" ? "change" : "weekly", ["nativeProtectionMarker"] = "current-settings" } },
                ["syncMetadaten"] = new JsonObject { ["syntheticMapping"] = "current-mapping" },
                ["unrelatedDomain"] = new JsonObject { ["keep"] = true }, ["syncEpoch"] = "exact-protection-epoch" };
            if (mode == "fractional") document["unrelatedDomain"]!["drawing"] = new JsonObject { ["x"] = .125, ["y"] = 1.75 };
            var root = Path.Combine(Path.GetTempPath(), "magnolie-exact-protection-" + Guid.NewGuid().ToString("N"));
            var cipher = new EncryptionService();
            if (encrypted) _ = cipher.Enable("{}", PersonalActorNativeSaveHost.Password);
            try
            {
                var host = new PersonalActorNativeSaveHost(Path.Combine(root, "book"), document.ToJsonString());
                var saved = encrypted ? await host.SaveOriginalContactResultAsync("", document) : await host.SavePlainForExactProtectionAsync(document);
                TestAssert.That(saved["ok"]!.GetValue<bool>(), "Exact protection fixture native save failed");
                var snapshot = host.Snapshot()!;
                var now = new DateTimeOffset(2026, 11, 15, 12, 0, 0, TimeSpan.Zero);
                var journal = new RecoveryJournal(Path.Combine(root, "journal"), Path.Combine(root, "settings.json"), clock: () => now);
                Func<string, string>? protect = encrypted ? cipher.EncryptData : null;
                string Unprotect(string text) => EncryptionService.IsEncrypted(text) ? cipher.DecryptDataWithSession(text) : text;
                if (mode is "recent-different" or "metadata-dedupe")
                {
                    var previous = document.DeepClone().AsObject();
                    previous["einstellungen"]!["allgemein"]!["nativeProtectionMarker"] = "older-settings";
                    previous["syncMetadaten"]!["syntheticMapping"] = "older-mapping";
                    if (mode == "recent-different") previous["notizen"]![0]!["text"] = "Older different note";
                    _ = journal.Create(previous, SnapshotReason.Manual, "2.0.30", protect, unprotect: Unprotect);
                    now = now.AddMinutes(1);
                }
                SnapshotInfo? protection = null;
                var session = new ContactSourceNativeSession(host.Snapshot, host.Saved, source.Settings, host.SourceResultCommit,
                    () => true, native =>
                    {
                        TestAssert.That(source.Writes == 0 && native.SavedBook == snapshot.SavedBook, "Protection did not precede provider write");
                        protection = new ContactSourceExactProtection(journal, host.DataPath, host.Snapshot, host.Primary,
                            "2.0.30", protect, Unprotect).Protect(native);
                    }, source.Transport);
                await session.ConfigureAsync((catalog, _, _) => Task.FromResult<IReadOnlyList<string>?>([catalog.Single().Uid]));
                var result = await session.RunAsync(snapshot.SavedBook.Sha256);
                TestAssert.That(source.Writes == 1 && result.SourceErrors == 0 && protection is not null,
                    "Exact-protection reproduction did not reach actual synthetic DAV write");
                var archive = JsonNode.Parse(Unprotect(journal.ReadPayload(protection!.Id)))!.AsObject();
                var actual = archive["daten"]!.AsObject();
                var exact = NativeBookJson.Same(actual, JsonNode.Parse(snapshot.Text)!);
                if (!exact) failures.Add($"{mode}/encrypted={encrypted}: providerWrites={source.Writes}, nativeVersion={document["version"]}, protectedVersion={actual["version"]}, full-original-mismatch");
                TestAssert.That(host.Saved() == snapshot.SavedBook && NativeBookJson.Same(document, JsonNode.Parse(host.CurrentNativeText!)!),
                    "Protection fixture mutated the actual user book");
                TestAssert.That(protection.Encrypted == encrypted && host.Primary().Encrypted == encrypted &&
                    GesamtarchivService.Read(Unprotect(journal.ReadPayload(protection.Id))).Daten["version"]!.GetValue<int>() == 7,
                    "Exact protection changed encryption policy or normal restore migration");
                await MutationGate.Global.WaitAsync();
                try
                {
                    var repeated = new ContactSourceExactProtection(journal, host.DataPath, host.Snapshot, host.Primary,
                        "2.0.30", protect, Unprotect).Protect(snapshot);
                    TestAssert.That(repeated.Id == protection.Id, "Unchanged complete exact protection was not safely reused");
                }
                finally { MutationGate.Global.Release(); }
            }
            finally
            {
                cipher.Clear();
                if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
            }
        }
        TestAssert.That(failures.Count == 0, "Exact original book was NOT protected before actual synthetic DAV PUT: " + string.Join("; ", failures));
        await ExactProtectionFailuresAsync();
        ExactArchiveBoundaries();
        Console.WriteLine("Exact original protection: 10 actual native writer/journal/DAV success + 8 held-write cases and archive boundaries passed.");
    }

    private static async Task ExactProtectionFailuresAsync()
    {
        foreach (var mode in new[] { "stale-saved", "wrong-binding", "encryption-downgrade", "plaintext-callback",
            "bad-readback", "tampered", "primary-before", "primary-during" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var source = new Source("exact-held", "generic-dav", original);
            var remote = await source.OriginalAsync(); var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, source.Catalog.Uid, remote, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var document = new JsonObject { ["version"] = 6, ["kontakte"] = new JsonArray(local), ["keep"] = "original" };
            var root = Path.Combine(Path.GetTempPath(), "magnolie-exact-held-" + Guid.NewGuid().ToString("N"));
            var cipher = new EncryptionService(); _ = cipher.Enable("{}", PersonalActorNativeSaveHost.Password);
            try
            {
                var host = new PersonalActorNativeSaveHost(Path.Combine(root, "book"), document.ToJsonString());
                TestAssert.That((await host.SaveOriginalContactResultAsync("", document))["ok"]!.GetValue<bool>(), "Held protection fixture save failed");
                var stale = host.Snapshot()!;
                if (mode == "stale-saved")
                {
                    document["new-user-data"] = true;
                    TestAssert.That((await host.SaveOriginalContactResultAsync("", document))["ok"]!.GetValue<bool>(), "Stale protection fixture save failed");
                }
                var before = host.Snapshot()!;
                var foreign = document.DeepClone().AsObject(); foreign["keep"] = "external native edit";
                var journal = new RecoveryJournal(Path.Combine(root, "journal"), Path.Combine(root, "settings.json"));
                var protections = 0;
                string Protect(string archive)
                {
                    if (mode == "plaintext-callback") return archive;
                    if (mode == "primary-during") host.ReplacePrimaryForExactProtectionTest(foreign);
                    if (mode is "bad-readback" or "tampered")
                    {
                        var changed = JsonNode.Parse(archive)!.AsObject(); changed["daten"]!["keep"] = "not the original";
                        archive = mode == "bad-readback" ? GesamtarchivService.CreateExactBook(changed["daten"]!.AsObject(), "windows", "2.0.30") : changed.ToJsonString();
                    }
                    return cipher.EncryptData(archive);
                }
                var session = new ContactSourceNativeSession(host.Snapshot, host.Saved, source.Settings, host.SourceResultCommit, () => true,
                    snapshot =>
                    {
                        protections++;
                        if (mode == "primary-before") host.ReplacePrimaryForExactProtectionTest(foreign);
                        _ = new ContactSourceExactProtection(journal,
                            mode == "wrong-binding" ? Path.Combine(root, "other.json") : host.DataPath, host.Snapshot, host.Primary, "2.0.30",
                            mode == "encryption-downgrade" ? null : Protect, cipher.DecryptDataWithSession)
                            .Protect(mode == "stale-saved" ? stale : snapshot);
                    }, source.Transport);
                await session.ConfigureAsync((catalog, _, _) => Task.FromResult<IReadOnlyList<string>?>([catalog.Single().Uid]));
                var result = await session.RunAsync(before.SavedBook.Sha256);
                TestAssert.That(protections == 1 && source.Writes == 0 && result.SourceErrors == 1 && result.Offer is null,
                    "Failed exact saved/primary/readback/privacy guard reached a provider write: " + mode);
                TestAssert.That(host.Saved() == before.SavedBook && NativeBookJson.Same(JsonNode.Parse(host.CurrentNativeText!)!, document),
                    "Failed protection changed native memory/saved authority");
                if (mode is "primary-before" or "primary-during")
                    TestAssert.That(host.Primary().Content == NativeBookJson.Hash(foreign), "Protection overwrote an external primary edit");
            }
            finally { cipher.Clear(); if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
        }
    }

    private static void ExactArchiveBoundaries()
    {
        var data = JsonNode.Parse("""{"version":6,"termine":[{"id":"t","wiederholung":{"art":"monthly_weekday"}}],"einstellungen":{"original":true},"drawing":{"x":0.125},"keep":[null,false,1]}""")!.AsObject();
        var originalHash = NativeBookJson.Hash(data);
        var root = Path.Combine(Path.GetTempPath(), "magnolie-exact-archive-" + Guid.NewGuid().ToString("N"));
        var cipher = new EncryptionService(); _ = cipher.Enable("{}", PersonalActorNativeSaveHost.Password);
        try
        {
            var archive = GesamtarchivService.CreateExactBook(data, "windows", "2.0.30");
            TestAssert.That(NativeBookJson.Hash(GesamtarchivService.ReadOriginalBook(archive).Daten) == originalHash && NativeBookJson.Hash(data) == originalHash,
                "Exact reader migrated/dropped original book values");
            var normal = GesamtarchivService.Read(archive).Daten;
            TestAssert.That(normal["version"]!.GetValue<int>() == 7 && normal["termine"]![0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly",
                "Normal restore/import stopped applying its existing migration");
            var withoutDrawing = data.DeepClone().AsObject(); withoutDrawing.Remove("drawing");
            TestAssert.That(GesamtarchivService.ReadOriginalBook(GesamtarchivService.Create(withoutDrawing, "windows", "2.0.30")).Daten["version"]!.GetValue<int>() == 7,
                "Ordinary archive creation no longer normalizes old schemas");
            var invalid = JsonNode.Parse(archive)!.AsObject(); invalid["exactBook"] = "true";
            TestAssert.Throws<InvalidDataException>(() => GesamtarchivService.ReadOriginalBook(invalid.ToJsonString()), "String exact marker bypassed archive validation");
            invalid = JsonNode.Parse(archive)!.AsObject(); invalid["daten"]!["version"] = 7;
            TestAssert.Throws<InvalidDataException>(() => GesamtarchivService.ReadOriginalBook(invalid.ToJsonString()), "Tampered exact archive skipped its checksum");
            var journal = new RecoveryJournal(Path.Combine(root, "journal"), Path.Combine(root, "settings.json"));
            var plain = journal.CreateExactBook(data, "2.0.30");
            var encrypted = journal.CreateExactBook(data, "2.0.30", cipher.EncryptData, cipher.DecryptDataWithSession);
            TestAssert.That(plain.Id != encrypted.Id && encrypted.Encrypted, "Exact dedup reused an unencrypted point for an encrypted book");
            var rewritten = journal.RewritePayloads((text, wasEncrypted) => wasEncrypted ? cipher.DecryptDataWithSession(text) : text);
            TestAssert.That(rewritten.Failed == 0 && rewritten.Changed == 1 &&
                NativeBookJson.Hash(GesamtarchivService.ReadOriginalBook(journal.ReadPayload(encrypted.Id)).Daten) == originalHash,
                "Password removal rewrote or migrated exact original contents");
            rewritten = journal.RewritePayloads((text, wasEncrypted) => wasEncrypted ? text : cipher.EncryptData(text));
            TestAssert.That(rewritten.Failed == 0 && rewritten.Changed == 2 &&
                NativeBookJson.Hash(GesamtarchivService.ReadOriginalBook(cipher.DecryptDataWithSession(journal.ReadPayload(plain.Id))).Daten) == originalHash,
                "Encryption rewrite dropped original schema/settings/fractional data");
        }
        finally { cipher.Clear(); if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
}

internal sealed partial class PersonalActorNativeSaveHost
{
    // Controlled plaintext primary for the real writer/primary protection tests;
    // production host code is untouched and no actual profile/key is loaded.
    internal Task<JsonObject> SavePlainForExactProtectionAsync(JsonObject document)
    {
        encryption.Clear(); currentEnvelope = "";
        return SaveOriginalContactResultAsync("", document);
    }
    internal void ReplacePrimaryForExactProtectionTest(JsonObject document)
    {
        var text = document.ToJsonString();
        store.WriteRecoverableJson(paths.Data, encryption.Session is null ? text : encryption.EncryptData(text));
    }
}
