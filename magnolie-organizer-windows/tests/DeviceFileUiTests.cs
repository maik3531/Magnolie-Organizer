using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileUiTests
{
    internal static Task StrictRequestsAsync()
    {
        var request = new JsonObject { ["cmd"] = "telefon_medien", ["requestId"] = "synthetic-request", ["device_id"] = Guid.NewGuid().ToString("D"), ["action"] = "status" };
        _ = NativeMediaUiRequest.Parse(request);
        var remove = request.DeepClone().AsObject(); remove["action"] = "trash_purge";
        remove["operation_id"] = new string('a', 32); remove["version"] = new string('b', 64);
        _ = NativeMediaUiRequest.Parse(remove);
        remove["confirmed"] = true;
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(remove), "Browser confirmation bypassed the native removal dialog.");
        var backup = request.DeepClone().AsObject(); backup["action"] = "backup_restore"; backup["media_type"] = "images";
        backup["backup_id"] = new string('a', 64); backup["version"] = new string('b', 64);
        TestAssert.That(NativeMediaUiRequest.Parse(backup).BackupId == new string('a', 64), "Opaque backup selection was not parsed.");
        foreach (var field in new[] { "path", "confirmed", "identity", "version", "backup_id" })
        {
            var changed = backup.DeepClone().AsObject();
            changed[field] = field is "version" or "backup_id" ? null : JsonValue.Create("untrusted");
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(changed), "Backup restore accepted a browser path, authority or stale selection: " + field);
        }
        foreach (var mutation in new[] { "path", "grant", "unknown", "version", "kind" })
        {
            var changed = request.DeepClone().AsObject();
            if (mutation == "path") changed["pfad"] = @"C:\arbitrary";
            if (mutation == "grant") changed["receive_files"] = true;
            if (mutation == "unknown") changed["action"] = "delete";
            if (mutation == "version") { changed["action"] = "sync"; changed["media_type"] = "images"; changed["version"] = null; changed["catalog_id"] = Guid.NewGuid().ToString("D"); changed["album_id"] = Guid.NewGuid().ToString("D"); }
            if (mutation == "kind") { changed["action"] = "discover"; changed["media_type"] = "both"; }
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(changed), "Native media UI admitted ignored/untrusted options: " + mutation);
        }
        return Task.CompletedTask;
    }

    internal static async Task WindowsExplicitNativeUiHandshakeAsync()
    {
        var book = new NativeBookOwnerScope(); book.SetReady(true); book.RecordSaved("native-ui-book", true, new string('a', 64));
        NativeBookSaveState? Saved() => book.SaveState("native-ui-book", true) is { Sequence: > 0 } value && value.Sha256.Length == 64 ? value : null;
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(uiSavedBook: Saved);
        TestAssert.That(f.Current() is not null && f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id).VideosEnabled == false,
            "Explicit native UI did not require actual bilateral data agreement or enabled videos implicitly.");
        book.SetReady(false);
        TestAssert.That(f.Current() is null, "Locked native book kept positive media permission.");
        book.SetReady(true); book.RecordSaved("native-ui-book", true, new string('b', 64));
        TestAssert.That(f.Current() is null, "Historical UI media permission revived after book unlock without explicit choice.");
        DeviceFileConnectionRunsTests.Clear(f);
        var prepare = f.Native.Connection.PrepareNativeMediaUiAsync(Saved, "images", CancellationToken.None);
        var outgoing = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind);
        TestAssert.That(!prepare.IsCompleted && f.Current() is null, "Renewed UI choice skipped the fresh actual data ACK.");
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(outgoing, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        var response = f.Phone.Packet(); f.Phone.MarkSent(response);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(response, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        await prepare;
        TestAssert.That(f.Current() is not null, "Fresh explicit UI choice and correlated ACK did not renew data readiness.");
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        var status = coordinator.NativeMediaUiStatus(f.Native.Peer.Id);
        TestAssert.That(!status["supported"]!.GetValue<bool>(), "Offline/unacknowledged native media UI was shown as available.");
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection);
        status = coordinator.NativeMediaUiStatus(f.Native.Peer.Id);
        TestAssert.That(status["supported"]!.GetValue<bool>() && status["videos"]!.GetValue<bool>() == false && status["automatic"]!.GetValue<bool>() == false &&
            status["skip_deletions"]!.GetValue<bool>() && !status["deletions_ready"]!.GetValue<bool>(), "Native UI invented video/automatic/deletion readiness.");
        var expected = status["version"]!.GetValue<string>();
        TestAssert.Throws<InvalidDataException>(() => coordinator.SetNativeMediaUiChoices(f.Native.Peer.Id, expected, false, false, false), "UI preferences bypassed actual saved native book ownership.");
        const string text = "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}";
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "ui-book"), text);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        coordinator.SetNativeMediaUiChoices(f.Native.Peer.Id, expected, false, false, false);
        var choices = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        TestAssert.That(choices.DeleteFromDesktop && choices.DeleteFromPhone && !choices.AutomaticWifi && !choices.VideosEnabled && f.Current() is null,
            "The single deletion choice diverged, enabled automatic/video, or historical permission survived a settings change.");
        f.Native.Connection.Dispose();
        TestAssert.That(!coordinator.NativeMediaUiStatus(f.Native.Peer.Id)["supported"]!.GetValue<bool>(), "A closed native route kept an unavailable media section visible.");
    }

    internal static async Task WindowsUiActualDiscoveryAsync()
    {
        var book = new NativeBookOwnerScope(); book.SetReady(true); book.RecordSaved("ui-discovery-book", true, new string('a', 64));
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(uiSavedBook: () => book.SaveState("ui-discovery-book", true));
        const string text = "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}";
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "ui-book"), text);
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection); DeviceFileConnectionRunsTests.Clear(f);
        var discovering = coordinator.DiscoverNativeMediaUiAsync(f.Native.Peer.Id, "images", CancellationToken.None);
        var status = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind);
        TestAssert.That(status["body"]!["operation"]!.GetValue<string>() == "status", "UI discovery skipped actual source status.");
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(coordinator.DiscoverNativeMediaUiAsync(f.Native.Peer.Id, "images", CancellationToken.None),
            "UI metadata operations overlapped.");
        var response = DeviceFileConnectionCommandsTests.Configuration(status, false); response["body"]!["operation"] = "status";
        await f.Native.Connection.HandlePlainAsync(response);
        var configure = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 1);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Configuration(configure, false));
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 2);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Catalog(request)); var catalog = await discovering;
        TestAssert.That(catalog.Version == new string('d', 64) && catalog.Page.Albums.Count == 1 &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (0, 0, 0L) && !Directory.EnumerateFileSystemEntries(f.Root).Any(),
            "UI discovery fabricated receive/Saved work or lost the correlated native catalog version.");
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(coordinator.SynchronizeNativeMediaUiAsync(f.Native.Peer.Id, "images", catalog.Version,
            catalog.Page.CatalogId, Guid.NewGuid().ToString("D"), CancellationToken.None), "An unknown browser album acquired native receive authority.");
    }
}
