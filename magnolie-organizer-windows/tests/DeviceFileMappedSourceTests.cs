using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMappedSourceTests
{
    private const string Book = "{\"syncEpoch\":\"mapped-source-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static readonly string PhoneTarget = new('f', 64);
    private static void Change(DeviceFileReceiveJobTests.Fixture f, string field, JsonNode value)
        => f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, field, value,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, field));

    private static async Task<DeviceFileReceiveJobTests.Fixture> Established()
    {
        var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sharedMedia: true);
        try
        {
            Change(f, "enabled", JsonValue.Create(true)!); await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            await DeviceFileReconcileTests.Establish(f);
            Change(f, "direction", JsonValue.Create("two_way")!); await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            return f;
        }
        catch { f.Dispose(); throw; }
    }

    private static async Task AllowSending(DeviceFileReceiveJobTests.Fixture f)
    {
        f.Local = new(new(8, new string('c', 64), true, true), f.Local.Owner, true);
        f.RemoteLocal = new(new(4, new string('d', 64), true, true), f.RemoteLocal.Owner, true);
        DeviceFileConnectionRunsTests.Clear(f);
        TestAssert.That(await f.Native.Connection.SendNativeFileControlsAsync(), "Updated local SEND had no actual secure output.");
        var first = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Last(frame => frame["kind"]!.GetValue<string>() == DeviceFileControl.Kind);
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(first, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        var response = f.Phone.Packet(); f.Phone.MarkSent(response);
        DeviceFileConnectionRunsTests.Clear(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(response, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        var echo = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Last(frame => frame["kind"]!.GetValue<string>() == DeviceFileControl.Kind);
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(echo, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        TestAssert.That(f.Owner.Binding(PhoneTarget, senderIsLocal: true) is not null, "Positive native SEND/RECEIVE did not match.");
    }

    internal static async Task WindowsCompletedMappingAsync()
    {
        using var f = await Established();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "source-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var fileId = 1.ToString("x32");
        TelefonStore.NativeMappedMediaSource Open(string? jobVersion = null, string? member = null) => f.Native.Connection.OpenNativeMappedMediaSource(
            "images", history.JobId, jobVersion ?? history.Version, member ?? fileId, PhoneTarget, book);
        TestAssert.Throws<InvalidDataException>(() => Open(), "Matched two-way intent alone granted local SEND.");
        await AllowSending(f);
        TestAssert.Throws<InvalidDataException>(() => Open(new string('0', 64)), "Stale receive head selected a source.");
        TestAssert.Throws<InvalidDataException>(() => Open(member: new string('f', 32)), "Foreign PC member entered phone-inventory scope.");
        var edited = "intentional mapped PC edit"u8.ToArray();
        using (var file = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write)) { file.SetLength(0); file.Write(edited); }
        using (var source = Open())
        {
            TestAssert.That(source.ReadExact(0, edited.Length).SequenceEqual(edited), "Mapped source read old phone bytes instead of current PC edit.");
            var reference = source.OriginalReference;
            TestAssert.That(reference["original_size"]!.GetValue<long>() == "original first"u8.Length && reference["file_id"]!.GetValue<string>() == fileId &&
                reference.Count == 8, "Outgoing correlation did not retain the exact protected phone baseline.");
            reference["photo_id"] = "injected";
            TestAssert.That(source.OriginalReference["photo_id"]!.GetValue<string>() != "injected", "Caller mutated the protected source reference.");
            Change(f, "direction", JsonValue.Create("phone_to_pc")!);
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "A changed direction left the old source readable.");
            await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            TestAssert.Throws<InvalidDataException>(() => Open(), "Phone-to-PC intent exported PC bytes.");
        }
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == history &&
            File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(edited), "Source preparation rewrote incoming history or mapped bytes.");
    }

    internal static async Task WindowsOriginalBookAndFileAsync()
    {
        using var f = await Established(); await AllowSending(f);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "source-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        TelefonStore.NativeMappedMediaSource Open(NativeMediaBookPermit permit) => f.Native.Connection.OpenNativeMappedMediaSource(
            "images", history.JobId, history.Version, 1.ToString("x32"), PhoneTarget, permit);
        using (var source = Open(book))
        {
            using var save = JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = Book }.ToJsonString());
            await host.SaveAsync(save.RootElement);
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Original saved-book change left source authority usable.");
        }
        var fresh = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        TestAssert.Throws<InvalidDataException>(() => Open(book), "New book revived old source permit.");
        var path = Path.Combine(f.Root, "first.jpg"); File.Move(path, Path.Combine(f.Root, "original-kept.jpg")); File.WriteAllText(path, "unrelated replacement");
        TestAssert.Throws<InvalidDataException>(() => Open(fresh), "Same filename adopted a different PC file identity.");
        TestAssert.That(File.ReadAllText(path) == "unrelated replacement" && File.Exists(Path.Combine(f.Root, "original-kept.jpg")), "Rejected source modified either local file.");
    }

    internal static async Task WindowsScopeAndMetadataAsync()
    {
        using var f = await Established(); await AllowSending(f);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "source-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        TelefonStore.NativeMappedMediaSource Open(string? jobId = null, string? version = null) => f.Native.Connection.OpenNativeMappedMediaSource(
            "images", jobId ?? history.JobId, version ?? history.Version, 1.ToString("x32"), PhoneTarget, book);
        Change(f, "collection_mode", JsonValue.Create("import_only")!); await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        TestAssert.Throws<InvalidDataException>(() => Open(), "Import-only exported a mapped PC edit despite its effective direction restriction.");
        Change(f, "collection_mode", JsonValue.Create("phone_inventory")!); await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        using (var source = Open()) TestAssert.That(source.Size > 0, "Returning to phone inventory lost the independent two-way direction.");
        Change(f, "photos_only", JsonValue.Create(true)!); await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        TestAssert.Throws<InvalidDataException>(() => Open(), "A completed mapping without actual capture metadata bypassed photos-only.");
        var capture = PhotoCaptureMetadataTests.Jpeg(); var path = Path.Combine(f.Root, "first.jpg");
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Write)) { file.SetLength(0); file.Write(capture); }
        using (var source = Open())
            TestAssert.That(source.ReadExact(0, capture.Length).SequenceEqual(capture) && source.OriginalReference["original_size"]!.GetValue<long>() != capture.Length,
                "Actual selected PC capture was not separated from the preserved phone baseline.");
        var unfinished = f.Manifest(("not-completed.jpg", "not Saved or END"u8.ToArray()));
        using (var job = f.Begin(unfinished))
        {
            var active = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(item => item.JobId == job.JobId);
            TestAssert.Throws<InvalidDataException>(() => Open(active.JobId, active.Version), "Unfinished receive metadata became a PC source mapping.");
        }
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(item => item.JobId == history.JobId) == history &&
            File.ReadAllBytes(path).SequenceEqual(capture), "Scope/filter checks changed original history or PC bytes.");
    }
}
