using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task SetupHistoryReproductionAsync(string root, bool addition = false, bool expectReplacementHold = false)
    {
        // #636 pre-UI audit: adding a separate source must not strand a genuine
        // already-saved result for an unchanged native source/book/contact.
        using var h = new Fixture(root);
        var book = h.Book.DeepClone().AsObject(); var other = book["kontakte"]![0]!.DeepClone().AsObject();
        other["id"] = "second-id"; other["uid"] = "second-uid"; book["kontakte"]!.AsArray().Add(other);
        TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Setup audit synthetic second-contact save failed");
        h.Store.Approve([h.Choice]); h.Host.NativeNotesChoices = h.Store;
        byte[] Key() => Enumerable.Repeat((byte)42, 32).ToArray();
        ContactSourcePrivateFiles Files(string name) => new(Path.Combine(h.Root, name), controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
        var requests = new NotesOriginalRequestIntents(Files("requests"), Key);
        var outcomes = new NotesOriginalSavedAckIntents(Files("outcomes"), Key, requests);
        var pending = h.Choice.CreatePending()!; requests.Seal(pending); h.PendingResult = pending;
        var request = pending.Request(); var hash = NotesOriginalSchema.Hash(request);
        var result = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = hash,
            ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
        foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) result[name] = request[name]!.DeepClone();
        h.Send(result); var commit = pending.PrepareCommit(h.Host.SourceResultCommit);
        TestAssert.That((await h.Host.SaveOriginalContactResultAsync(commit.Offer.Token, JsonNode.Parse(commit.Text)!.AsObject()))["ok"]!.GetValue<bool>(), "Setup audit actual metadata save failed");
        outcomes.Seal(pending);
        h.Protocol = new(h.Choice.Pins.Peer, h.Choice.Pins.Own); var offer = h.Protocol.Probe(); offer["antwort"] = true; h.Send(offer);
        TestAssert.That(outcomes.ReadOnlyQuery(hash, h.Store, h.Protocol).Request(h.Protocol).Count == 7, "Unchanged saved history was unavailable before setup edit");
        var updated = h.Export.DeepClone().AsObject(); var provider = updated["kontakt"]!.AsObject();
        foreach (var pair in request["ziel"]!.AsObject()) provider[pair.Key] = pair.Value?.DeepClone();
        updated["before_basis"] = new string('d', 64); updated["native_revision"] = 2L; updated["content_sha256"] = NotesOriginalReturnHash.ContentHash(provider);
        // Complete replacement decisions require fresh native choices, not a
        // restored alias whose callback deliberately binds the previous epoch.
        h.Send(updated); var unchangedChoice = h.MakeChoice();
        var second = h.Export.DeepClone().AsObject(); second["share_id"] = "second-source-share"; second["setup_id"] = "33333333-3333-4333-8333-333333333333";
        h.Send(second); var observed = h.RecoveryObservation;
        var newChoice = new NotesOriginalExportChoice(observed.Body, observed.Origin, observed.Transport, h.Host.Snapshot()!, h.Host.Snapshot,
            _ => "second-id", () => { });
        var before = File.ReadAllBytes(h.Host.DataPath); var saved = outcomes.LoadHeld(hash)!.ToJsonString();
        var keyBefore = File.ReadAllText(Path.Combine(h.ConsentRoot, ".key.dpapi"));
        if (addition) h.Store.AddSources([newChoice]); else h.Store.Approve([unchangedChoice, newChoice]);
        TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before) && outcomes.LoadHeld(hash)!.ToJsonString() == saved,
            "Setup audit changed book or independent saved history");
        if (expectReplacementHold)
        {
            TestAssert.That(File.ReadAllText(Path.Combine(h.ConsentRoot, ".key.dpapi")) != keyBefore, "Full replacement failed to rotate consent key");
            Hold(() => outcomes.ReadOnlyQuery(hash, h.Store, h.Protocol)); return;
        }
        TestAssert.That(outcomes.ReadOnlyQuery(hash, h.Store, h.Protocol).Request(h.Protocol).Count == 7,
            "Adding another genuine native source stranded unchanged saved ACK history");
        if (addition)
        {
            var approval = File.ReadAllText(Path.Combine(h.ConsentRoot, "approval.json"));
            h.Store.AddSources([newChoice]);
            TestAssert.That(File.ReadAllText(Path.Combine(h.ConsentRoot, ".key.dpapi")) == keyBefore &&
                File.ReadAllText(Path.Combine(h.ConsentRoot, "approval.json")) == approval && newChoice.CreatePending() is not null,
                "Identical source addition rewrote keys/approval or failed to bind new choice");
            var terminal = result.DeepClone().AsObject(); terminal["art"] = "kontakt_original_abschlussstatus";
            terminal["phase"] = "settled"; terminal["desktop_sha256"] = h.Host.Saved()!.Sha256;
            h.CaptureRecovery = true; h.Send(terminal); var observation = h.RecoveryObservation;
            var restored = outcomes.Reauthorize(outcomes.ReadOnlyQuery(hash, h.Store, h.Protocol), observation.Body, observation.Origin, observation.Transport, h.Protocol);
            requests.Retire(outcomes.SealTerminal(restored));
            TestAssert.That(requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id")!["state"]!.GetValue<string>() == "request_settled",
                "Source addition stranded exact terminal retirement");
        }
    }

    internal static async Task SetupAdditionAsync(string root)
    {
        await SetupHistoryReproductionAsync(Path.Combine(root, "saved-history"), addition: true);
        await SetupHistoryReproductionAsync(Path.Combine(root, "full-replacement-boundary"), expectReplacementHold: true);
        foreach (var mode in new[] { "fresh", "loaded-query", "missing", "revoked", "collision-id", "collision-share", "changed-setup", "fake-choice",
            "revoked-choice", "unknown-book", "concurrent-revoke", "concurrent-replace", "pending", "lost-key" })
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var book = h.Book.DeepClone().AsObject(); var other = book["kontakte"]![0]!.DeepClone().AsObject();
            other["id"] = "second-id"; other["uid"] = "second-uid"; book["kontakte"]!.AsArray().Add(other);
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Addition fixture save failed");
            if (mode != "missing") h.Store.Approve([h.Choice]);
            h.Host.NativeNotesChoices = h.Store;
            NotesOriginalRequestIntents? requests = null; NotesOriginalPendingResult? original = null;
            NotesOriginalRequestIntents.FreshRequest? fresh = null;
            byte[] Key() => Enumerable.Repeat((byte)42, 32).ToArray();
            if (mode is "fresh" or "loaded-query")
            {
                requests = new(new ContactSourcePrivateFiles(Path.Combine(h.Root, "requests"), controlledUnix: !OperatingSystem.IsWindows(),
                    layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal), Key);
                original = h.Choice.CreatePending()!; fresh = requests.Seal(original);
                h.Protocol = new(h.Choice.Pins.Peer, h.Choice.Pins.Own); var offer = h.Protocol.Probe(); offer["antwort"] = true; h.Send(offer);
            }
            var second = h.Export.DeepClone().AsObject(); second["share_id"] = mode == "collision-share" ? h.Export["share_id"]!.DeepClone() : JsonValue.Create("second-source-share");
            second["setup_id"] = "33333333-3333-4333-8333-333333333333";
            h.Send(second); var observed = h.RecoveryObservation;
            var newChoice = new NotesOriginalExportChoice(observed.Body, observed.Origin, observed.Transport, h.Host.Snapshot()!, h.Host.Snapshot,
                _ => mode is "collision-id" or "changed-setup" ? "chosen-private-id" : "second-id", () =>
                {
                    var hook = h.GuardHook; h.GuardHook = null; hook?.Invoke();
                });
            if (mode == "revoked-choice") newChoice.Revoke();
            if (mode == "revoked") h.Store.Revoke();
            if (mode == "pending") using (var directory = new ContactSourcePrivateFiles(h.ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()).Open()!) directory.Write(".transaction", "pending\n", 32);
            if (mode == "lost-key") File.Delete(Path.Combine(h.ConsentRoot, ".key.dpapi"));
            if (mode == "unknown-book")
            {
                h.Host.NativeNotesChoices = null; var changed = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); changed["unknown-edit"] = true;
                await h.Host.SaveOriginalContactResultAsync("", changed); h.Host.NativeNotesChoices = h.Store;
            }
            if (mode == "concurrent-revoke") h.GuardHook = h.Store.Revoke;
            if (mode == "concurrent-replace") h.GuardHook = () => h.Store.Approve([h.Choice]);
            var before = File.ReadAllBytes(h.Host.DataPath);
            if (mode is "fresh" or "loaded-query")
            {
                h.CheckOutsideLock = true; h.Store.AddSources([newChoice]);
                var query = requests!.ReadOnlyQuery(Path.GetFullPath(h.Host.DataPath), "chosen-private-id", h.Store, h.Protocol!);
                TestAssert.That(query.Request(h.Protocol!).Count == 7 && requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id")!["request"]!["request_id"]!.GetValue<string>() == original!.Request()["request_id"]!.GetValue<string>(),
                    "Addition replaced original request or stranded query-only recovery");
                fresh!.RequireFor(original!, h.Protocol!);
            }
            else Hold(() => h.Store.AddSources(mode == "fake-choice" ? [null!] : [newChoice]));
            TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Source addition mutated user book");
            if (mode == "concurrent-revoke") TestAssert.That(!h.Store.HasDesiredConsent(), "Addition resurrected concurrent revocation");
        }
        Console.WriteLine("Notes monotone source addition: saved history/terminal/idempotence, full-replacement boundary and 14 admission/CAS/intent cases passed.");
    }
}
