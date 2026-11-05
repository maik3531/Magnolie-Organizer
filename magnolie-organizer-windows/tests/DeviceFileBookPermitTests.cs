using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBookPermitTests
{
    private const string Before = "{\"syncEpoch\":\"media-book-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}";

    internal static async Task WindowsFailedNativeSaveRevokesAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Root, "native-book"), Before);
        var beforeSaved = host.Saved()!;
        var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); permit.Require();
        TestAssert.That(permit.TrashEnabled && permit.RetentionDays == 0 && permit.ReplacementConsent is not null, "Canonical never-expire trash setting was not retained.");
        host.FailAfterPrimary = true;
        var after = JsonNode.Parse(Before)!.AsObject(); after["changed"] = "actual post-rename failure";
        using var message = JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = after.ToJsonString() }.ToJsonString());
        await host.SaveAsync(message.RootElement);
        TestAssert.That(!host.Responses.Last().Value["ok"]!.GetValue<bool>() && new EncryptionService().Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password) == after.ToJsonString(),
            "Actual native failed-save reproduction did not reach its uncertain post-rename state.");
        TestAssert.Throws<InvalidDataException>(permit.Require, "A failed actual native book save left the historical media permit usable.");
        TestAssert.That(host.Snapshot() is null, "Uncertain actual native saved book was offered as fresh media authority.");
        host.FailAfterPrimary = false;
        await host.SaveAsync(message.RootElement);
        TestAssert.That(host.Responses.Last().Value["ok"]!.GetValue<bool>() && host.Saved()!.Sequence == beforeSaved.Sequence + 1 &&
            host.Saved()!.BookSource == beforeSaved.BookSource, "Successful repair reset the native book identity or monotonic saved sequence.");
        TestAssert.Throws<InvalidDataException>(permit.Require, "A historical media book permit revived after a fresh successful save.");
        NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved).Require();
    }

    internal static async Task WindowsSavedPolicyAndRejectedSaveAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Root, "native-book"), Before); var saved = host.Saved();
        var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        using (var rejected = JsonDocument.Parse(new JsonObject { ["id"] = 0, ["text"] = Before }.ToJsonString())) await host.SaveAsync(rejected.RootElement);
        TestAssert.That(!host.Responses.Last().Value["ok"]!.GetValue<bool>() && host.Saved() == saved, "A rejected pre-write save destroyed the valid native book witness.");
        permit.Require();
        var disabled = JsonNode.Parse(Before)!.AsObject(); disabled["einstellungen"]!["papierkorb"]!["an"] = false;
        using (var message = JsonDocument.Parse(new JsonObject { ["id"] = 2, ["text"] = disabled.ToJsonString() }.ToJsonString())) await host.SaveAsync(message.RootElement);
        TestAssert.Throws<InvalidDataException>(permit.Require, "Changed native book settings did not retire old media ownership.");
        var next = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        TestAssert.That(!next.TrashEnabled && next.RetentionDays == 0 && next.ReplacementConsent is null, "Disabled trash silently authorized a permanent replacement.");
    }

    internal static async Task WindowsBookChangedDuringActualReceiveAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "native-book"), Before);
        var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var manifest = f.Manifest(("new-first.jpg", "new first"u8.ToArray()), ("new-second.jpg", "new second"u8.ToArray()));
        var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest); run.NativeWorkerGuard = permit.Require;
        var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        var chunk = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind);
        using (var message = JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = Before }.ToJsonString())) await host.SaveAsync(message.RootElement);
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(chunk, "new first"u8.ToArray())),
            "Actual incoming data wrote through a retired native saved-book permit.");
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(operation, "Native receive continued after its saved book changed.");
        TestAssert.That(!File.Exists(Path.Combine(f.Root, "new-first.jpg")) && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 1, manifest.TotalBytes) &&
            Directory.EnumerateFiles(f.Root, "*.part", SearchOption.AllDirectories).All(path => new FileInfo(path).Length == 0),
            "Retired book guard wrote/published data or discarded original reserved receive history.");
    }
}
