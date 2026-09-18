using System.Reflection;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DesktopDataReviewTests
{
    internal static async Task RunAsync()
    {
        var directory = Path.Combine(Path.GetTempPath(), "desktop-data-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            SavedReconciliationProof();
            var first = new WindowsContactStore(directory);
            var second = new WindowsContactStore(directory);
            var contact = new JsonObject { ["vorname"] = "Synthetic", ["notiz"] = "AAAA" };
            var revision = await first.CreateAsync("synthetic", contact, default);
            var nativePath = Path.Combine(directory, revision.Id);
            var originalTime = File.GetLastWriteTimeUtc(nativePath);
            var originalSize = new FileInfo(nativePath).Length;
            var local = revision.Data.DeepClone().AsObject();
            local["id"] = "local"; local["uid"] = "synthetic";
            local["foto"] = "synthetic-photo";
            local["sozialeMedien"] = new JsonArray("synthetic-social");
            local["vcardRoundtrip"] = new JsonArray("X-LOCAL:preserve");
            ContactFields.SetSource(local, "windows-contacts", revision);
            contact["notiz"] = "BBBB";
            await second.UpdateAsync(revision, "synthetic", contact, default);
            File.SetLastWriteTimeUtc(nativePath, originalTime);
            TestAssert.That(new FileInfo(nativePath).Length == originalSize &&
                (await first.ReadAsync(default))[0].ETag != revision.ETag,
                "Revision depended on file size/timestamp instead of the content read.");
            await TestAssert.ThrowsAsync<IOException>(() => first.UpdateAsync(revision, "synthetic", contact, default), "Stale equal-size update was accepted.");
            await TestAssert.ThrowsAsync<IOException>(() => first.DeleteAsync(revision, "synthetic", default), "Stale deletion was accepted.");
            var merged = await new ContactSyncEngine().SyncAsync("windows-contacts", new JsonArray(local), [], 0, first);
            TestAssert.That(merged.Contacts[0]!["foto"]!.ToString() == "synthetic-photo" &&
                merged.Contacts[0]!["sozialeMedien"]![0]!.ToString() == "synthetic-social" &&
                merged.Contacts[0]!["vcardRoundtrip"]![0]!.ToString() == "X-LOCAL:preserve" &&
                merged.Contacts[0]!["notiz"]!.ToString() == "BBBB", "Native projection erased unsupported fields.");
            var fresh = (await first.ReadAsync(default))[0];
            await first.DeleteAsync(fresh, "synthetic", default);
            var restored = await new ContactSyncEngine().SyncAsync("windows-contacts", merged.Contacts, [], 0, first, additiveOnly: true);
            TestAssert.That(restored.Contacts.Count == 1, "Additive native restore removed a contact.");
            restored = await new ContactSyncEngine().SyncAsync("windows-contacts", restored.Contacts, [], 0, first);
            TestAssert.That(restored.Contacts.Count == 1 && restored.Counts.Exported == 1, "Second native restore run did not retain and upload the contact.");
            foreach (var provider in new[] { "windows-contacts", "microsoft-graph" })
            {
                var projected = local.DeepClone().AsObject();
                ContactFields.CopyRemoteFields(projected, new JsonObject { ["notiz"] = "", ["foto"] = null }, provider);
                TestAssert.That(projected["notiz"]!.ToString() == "" && projected["foto"]!.ToString() == "synthetic-photo", "Field authority confused supported deletion and unsupported absence.");
            }
            foreach (var type in new[] { typeof(NextcloudCalendarSync), typeof(NextcloudTaskSync) })
            {
                var target = new JsonObject { ["icsRangeOverrides"] = new JsonArray("old"), ["icsZeitzonen"] = new JsonArray("old"), ["localOnly"] = "keep" };
                var method = type.GetMethod(type == typeof(NextcloudCalendarSync) ? "CopyCalendar" : "CopyTask", BindingFlags.NonPublic | BindingFlags.Static)!;
                method.Invoke(null, [target, new JsonObject { ["icsRoundtrip"] = new JsonArray("RRULE:FREQ=DAILY") }]);
                TestAssert.That(!target.ContainsKey("icsRangeOverrides") && !target.ContainsKey("icsZeitzonen") && target["localOnly"]!.ToString() == "keep", "Stale recurrence companions survived authoritative replacement.");
            }
            fresh = (await first.ReadAsync(default))[0];
            var contactPath = Path.Combine(directory, fresh.Id);
            var interrupted = new WindowsContactStore(directory, stage =>
            {
                if (stage == "parked") throw new IOException("synthetic interruption");
            });
            await TestAssert.ThrowsAsync<IOException>(() => interrupted.UpdateAsync(fresh, "synthetic", contact, default), "Missing crash injection.");
            TestAssert.That(!File.Exists(contactPath), "Interruption did not reach publication gap.");
            TestAssert.That((await first.ReadAsync(default))[0].ETag == fresh.ETag, "Interrupted publication did not recover the exact preimage.");
            var racing = new WindowsContactStore(directory, stage =>
            {
                if (stage == "validated" && OperatingSystem.IsWindows())
                    TestAssert.Throws<IOException>(() => File.WriteAllText(contactPath, "foreign"), "Windows handle allowed an intervening write.");
                if (stage == "parked") File.WriteAllText(contactPath, WindowsContactStore.Serialize(new JsonObject { ["notiz"] = "external winner" }, "foreign"));
            });
            await TestAssert.ThrowsAsync<IOException>(() => racing.UpdateAsync(fresh, "synthetic", contact, default), "Publication overwrote an independent writer.");
            TestAssert.That((await first.ReadAsync(default))[0].Data["notiz"]!.ToString() == "external winner", "Recovery replaced the independent writer.");
            TestAssert.That(first.ImportUid(fresh) == "synthetic", "Import UID was reread from a different file revision.");
            if (OperatingSystem.IsWindows()) await WindowsContactLockTests.RunAsync(Path.Combine(directory, "locked-handles"));
        }
        finally { Directory.Delete(directory, true); }
    }

    private static void SavedReconciliationProof()
    {
        var baseline = new JsonObject();
        foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage" }) baseline[field] = new JsonArray();
        baseline["geloescht"] = new JsonObject { ["termine"] = new JsonArray(), ["aufgaben"] = new JsonArray(), ["kontakte"] = new JsonArray() };
        baseline["aufgaben"] = new JsonArray(new JsonObject { ["id"] = "one", ["titel"] = "before" });
        var completed = baseline.DeepClone().AsObject();
        completed["transactionId"] = "transaction";
        completed["syncAbgleichBasis"] = baseline.DeepClone();
        completed["aufgaben"]![0]!["notiz"] = "remote";
        completed["syncEpoch"] = "epoch";
        completed["letzterSync"] = 10;
        completed["letzteSyncs"] = new JsonObject();
        completed["syncMetadaten"] = new JsonObject { ["nextcloud"] = new JsonObject { ["pendingCommitId"] = "transaction" } };
        var proof = baseline.DeepClone().AsObject();
        proof["transactionId"] = "transaction";
        proof["aufgaben"]![0]!["titel"] = "saved intervening edit";
        var saved = completed.DeepClone().AsObject();
        saved["syncAbgleichNachweis"] = proof;
        saved["aufgaben"]![0]!["titel"] = "saved intervening edit";
        TestAssert.That(SyncBaseline.ContainsSavedResult(completed, saved), "Exact three-way result was not accepted as durable.");
        saved["aufgaben"]![0]!.AsObject().Remove("notiz");
        TestAssert.That(!SyncBaseline.ContainsSavedResult(completed, saved), "Proof accepted discarded remote content.");
        saved["aufgaben"]![0]!["notiz"] = "remote";
        saved["syncMetadaten"]!["nextcloud"]!.AsObject().Remove("pendingCommitId");
        TestAssert.That(!SyncBaseline.ContainsSavedResult(completed, saved), "Proof accepted a missing durable transaction marker.");
    }
}
