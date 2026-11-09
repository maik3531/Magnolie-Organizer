using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileUiTests
{
    internal static async Task WindowsReadBeforeAlbumScanAsync()
    {
        var book = new NativeBookOwnerScope(); book.SetReady(true); book.RecordSaved("read-ui-book", true, new string('a', 64));
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false,
            uiSavedBook: () => book.SaveState("read-ui-book", true));
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "read-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection); DeviceFileConnectionRunsTests.Clear(f);
        var requesting = coordinator.RequestNativeMediaUiReadAsync(f.Native.Peer.Id, "images", null, CancellationToken.None);
        if (requesting.IsCompleted) _ = await requesting;
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "status", "Access rights fabricated a catalog version or required an album scan.");
        var response = DeviceFileConnectionCommandsTests.Configuration(request, false);
        response["body"]!["operation"] = "status"; response["body"]!["enabled"] = false;
        await f.Native.Connection.HandlePlainAsync(response);
        request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 1);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Configuration(request, false));
        TestAssert.That(!requesting.IsCompleted && f.Current() is null, "Permission preparation treated configuration as the current data ACK.");
        f.RemoteLocal = new(new(4, new string('e', 64), true, false), f.RemoteLocal.Owner, true);
        var control = f.Phone.Packet(); f.Phone.MarkSent(control);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(control, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 2);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "request_read", "Access rights started an inventory or synchronization instead of asking foreground consent.");
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        await f.Native.Connection.HandlePlainAsync(new JsonObject { ["type"] = "message", ["v"] = 1,
            ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = DeviceFileSources.PermissionResultKind,
            ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = new JsonObject { ["format"] = 1,
                ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = "request_read",
                ["version"] = request["body"]!["expected_version"]!.DeepClone(), ["state"] = "foreground_required" } });
        TestAssert.That((await requesting).State == "foreground_required" && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0,
            "The top access-rights action invented OS access or data permission.");
    }
    internal static async Task WindowsClosedSourceBootstrapAsync()
    {
        var book = new NativeBookOwnerScope(); book.SetReady(true); book.RecordSaved("closed-source-ui", true, new string('a', 64));
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false,
            uiSavedBook: () => book.SaveState("closed-source-ui", true));
        TestAssert.That(f.Current() is null, "A closed phone source gained a data binding from metadata readiness.");
        DeviceFileConnectionRunsTests.Clear(f);
        var reading = f.Native.Connection.ReadNativeFileSourceStatusAsync(CancellationToken.None);
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind);
        var response = DeviceFileConnectionCommandsTests.Configuration(request, false);
        response["body"]!["operation"] = "status"; response["body"]!["enabled"] = false;
        await f.Native.Connection.HandlePlainAsync(response);
        var status = await reading;
        TestAssert.That(!status.Enabled && f.Current() is null,
            "Reading a fresh closed source either required prior data consent or fabricated it.");
        var configuring = f.Native.Connection.ConfigureNativeMediaSourceAsync(status.Version, "images", true, CancellationToken.None);
        request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 1);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Configuration(request, false));
        _ = await configuring;
        TestAssert.That(f.Current() is null, "Source configuration bypassed the separate actual data permission echo.");
    }
    internal static Task WindowsDefaultDestinationsAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture();
        _ = f.Store.LoadOrCreateIdentity();
        using var coordinator = new TelefonCoordinator(f.Paths, (_, _) => Task.CompletedTask, dataStore: f.Store, localOnly: true);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Paths.Root, "default-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var pictures = Path.Combine(f.Paths.Root, "Pictures"); var videos = Path.Combine(f.Paths.Root, "Videos");
        Directory.CreateDirectory(pictures); Directory.CreateDirectory(videos);
        coordinator.EnsureNativeMediaDefaultDestination(f.Peer.Id, "images", pictures);
        coordinator.EnsureNativeMediaDefaultDestination(f.Peer.Id, "video", videos);
        var images = f.Store.ReadNativeMediaDestination(f.Peer.Id, "images")!;
        var clips = f.Store.ReadNativeMediaDestination(f.Peer.Id, "video")!;
        TestAssert.That(images.NativePath.TrimEnd('\\') == Path.Combine(pictures, "Synthetic-Fotos") &&
            clips.NativePath.TrimEnd('\\') == Path.Combine(videos, "Synthetic-Videos"), "Default destinations did not use independent native media roots and the phone name.");
        var original = Path.Combine(images.NativePath, "personal.jpg"); File.WriteAllText(original, "keep");
        coordinator.EnsureNativeMediaDefaultDestination(f.Peer.Id, "images", videos);
        TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") == images && File.ReadAllText(original) == "keep",
            "An existing destination was replaced or existing media were overwritten by default initialization.");
        TestAssert.That(f.Store.ReadNativeMediaPreferences(f.Peer.Id) is { PhotosEnabled: false, VideosEnabled: false, AutomaticWifi: false },
            "Creating a chosen default folder silently granted media or automatic synchronization permissions.");
        return Task.CompletedTask;
    }
    internal static async Task WindowsLegacyActivationAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(legacy: true);
        _ = f.Store.LoadOrCreateIdentity();
        using var coordinator = new TelefonCoordinator(f.Paths, (_, _) => Task.CompletedTask, dataStore: f.Store, localOnly: true);
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Peer.Id, f.Connection);
        TestAssert.That(!coordinator.NativeMediaUiStatus(f.Peer.Id)["supported"]!.GetValue<bool>(), "Cached old pairing exposed media activation without current ACKs.");
        foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
            await f.Connection.HandlePlainAsync(f.Message(kind));
        var status = coordinator.NativeMediaUiStatus(f.Peer.Id);
        TestAssert.That(status["supported"]!.GetValue<bool>() && status["activation_required"]!.GetValue<bool>() && status.Count == 2 &&
            !f.Connection.FileMetadataReady() && f.Store.LoadPeers().Single().FilePairingEpoch is null,
            "Compatible legacy pairing stayed hidden, gained transfer authority or status inspection wrote pairing metadata.");
        TestAssert.Throws<InvalidDataException>(() => coordinator.ActivateLegacyNativeMediaUi(f.Peer.Id), "Activation bypassed a saved native book.");
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Paths.Root, "activation-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var before = f.Store.LoadPeers().Single();
        coordinator.ActivateLegacyNativeMediaUi(f.Peer.Id);
        var after = f.Store.LoadPeers().Single();
        var serialize = typeof(TelefonStore).GetMethod("WritePeer", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
        TestAssert.That(DeviceFileControl.Hash(after.FilePairingEpoch ?? "") &&
            JsonNode.DeepEquals((JsonNode)serialize.Invoke(null, [after with { FilePairingEpoch = null }])!, (JsonNode)serialize.Invoke(null, [before])!) &&
            !f.Connection.FileMetadataReady() && !f.Connection.NativeMediaLegacyActivationAvailable(),
            "Activation changed existing pairing data or transplanted old-channel receipts into the new native relationship.");
        TestAssert.That(f.Store.ReadNativeMediaPreferences(f.Peer.Id) is { PhotosEnabled: false, VideosEnabled: false, AutomaticWifi: false },
            "Native relationship initialization silently enabled transfers, video or automatic sync.");
        using var fresh = f.NewConnection(new DeviceFileConnectionMetadataTests.ProbeStream(), connectionPeer: after);
        online[f.Peer.Id] = fresh;
        TestAssert.That(!coordinator.NativeMediaUiStatus(f.Peer.Id)["supported"]!.GetValue<bool>(), "Reconnect reused old ACK receipts.");
        foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
            await fresh.HandlePlainAsync(f.Message(kind, revision: 2));
        status = coordinator.NativeMediaUiStatus(f.Peer.Id);
        TestAssert.That(status["supported"]!.GetValue<bool>() && status["activation_required"] is null &&
            !status["photos"]!.GetValue<bool>() && !status["videos"]!.GetValue<bool>() && !status["automatic"]!.GetValue<bool>(),
            "Fresh acknowledged reconnect did not expose manual media settings with photo/video policy still disabled: " + status.ToJsonString() +
            "; receipts=" + ((Dictionary<string, JsonObject>)typeof(TelefonConnection).GetField("fileMetadataReceipts", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(fresh)!).Count +
            "; revoked=" + typeof(TelefonConnection).GetField("fileMetadataRevoked", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(fresh));
    }
    internal static Task StrictRequestsAsync()
    {
        var request = new JsonObject { ["cmd"] = "telefon_medien", ["requestId"] = "synthetic-request", ["device_id"] = Guid.NewGuid().ToString("D"), ["action"] = "status" };
        _ = NativeMediaUiRequest.Parse(request);
        foreach (var mediaType in new[] { "images", "video" })
        {
            var source = request.DeepClone().AsObject(); source["action"] = "pick_collection_source";
            source["media_type"] = mediaType; source["version"] = new string('d', 64);
            TestAssert.That(NativeMediaUiRequest.Parse(source).MediaType == mediaType, "Source-folder action lost its independent media type.");
            foreach (var field in new[] { "path", "confirmed", "witness", "identity", "receive_files", "source_id", "version" })
            {
                var forged = source.DeepClone().AsObject(); forged[field] = field == "version" ? null : JsonValue.Create("untrusted");
                TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(forged), "Source-folder action accepted browser authority: " + field);
            }
        }
        foreach (var (field, value) in MediaSyncSettings.Effective(MediaSyncSettings.Create("11111111-1111-4111-8111-111111111111")))
        {
            var edit = request.DeepClone().AsObject(); edit["action"] = "shared_setting"; edit["field"] = field;
            edit["value"] = value!.DeepClone(); edit["version"] = new string('a', 64);
            var parsed = NativeMediaUiRequest.Parse(edit);
            TestAssert.That(parsed.SharedField == field && JsonNode.DeepEquals(parsed.SharedValue, value), "Shared media choice was changed by bridge parsing.");
            edit["version"] = null;
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(edit), "Shared media choice omitted its exact field version.");
        }
        var consent = request.DeepClone().AsObject(); consent["action"] = "receive_consent";
        consent["granted"] = true; consent["version"] = new string('b', 64);
        TestAssert.That(NativeMediaUiRequest.Parse(consent).ReceiveConsent, "Explicit local consent was not parsed independently.");
        consent["granted"] = "true";
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(consent), "Local permission accepted a truthy string.");
        var send = request.DeepClone().AsObject(); send["action"] = "send_consent";
        send["photos"] = true; send["videos"] = false; send["version"] = new string('c', 64);
        TestAssert.That(NativeMediaUiRequest.Parse(send) is { Photos: true, Videos: false }, "Independent send choices were not parsed.");
        foreach (var field in new[] { "confirmed", "send_files", "path" })
        {
            var forged = send.DeepClone().AsObject(); forged[field] = true;
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(forged), "Browser manufactured native send approval: " + field);
        }
        send["photos"] = "true";
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(send), "Send consent accepted a truthy string.");
        send["photos"] = true; send["version"] = null;
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(send), "Send consent accepted an unversioned choice.");
        var unknownField = request.DeepClone().AsObject(); unknownField["action"] = "shared_setting";
        unknownField["field"] = "receive_files"; unknownField["value"] = true; unknownField["version"] = new string('a', 64);
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(unknownField), "A shared edit attempted to manufacture native receiving rights.");
        var remove = request.DeepClone().AsObject(); remove["action"] = "trash_purge";
        remove["operation_id"] = new string('a', 32); remove["version"] = new string('b', 64);
        _ = NativeMediaUiRequest.Parse(remove);
        foreach (var action in new[] { "trash_thumbnail", "trash_preview" })
        {
            var preview = remove.DeepClone().AsObject(); preview["action"] = action;
            TestAssert.That(NativeMediaUiRequest.Parse(preview).TrashOperation == new string('a', 32), "Preview lost its opaque operation.");
            preview["path"] = @"C:\untrusted";
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(preview), "Preview accepted a filesystem path.");
            preview.Remove("path"); preview["version"] = null;
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(preview), "Preview accepted an unversioned selection.");
        }
        remove["confirmed"] = true;
        TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(remove), "Browser confirmation bypassed the native removal dialog.");
        var backup = request.DeepClone().AsObject(); backup["action"] = "backup_restore"; backup["media_type"] = "images";
        backup["backup_id"] = new string('a', 64); backup["version"] = new string('b', 64);
        TestAssert.That(NativeMediaUiRequest.Parse(backup).BackupId == new string('a', 64), "Opaque backup selection was not parsed.");
        backup["location_id"] = new string('c', 64);
        TestAssert.That(NativeMediaUiRequest.Parse(backup).BackupLocation == new string('c', 64), "Historical backup source locator was not parsed independently.");
        foreach (var action in new[] { "pick_backup_parent", "backup_default", "pick_destination", "default_destination" })
        {
            var pick = request.DeepClone().AsObject(); pick["action"] = action; pick["media_type"] = "images"; pick["version"] = null;
            _ = NativeMediaUiRequest.Parse(pick);
            pick["path"] = @"C:\untrusted";
            TestAssert.Throws<InvalidDataException>(() => NativeMediaUiRequest.Parse(pick), "Backup parent action accepted a browser path.");
        }
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
