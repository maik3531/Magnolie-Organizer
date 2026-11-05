using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionCommandsTests
{
    private static readonly string SourceVersion = new('d', 64);
    private static JsonObject Request(DeviceFileReceiveJobTests.Fixture f)
    {
        var request = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single();
        _ = DeviceFileSources.ParseRequest(request, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); return request;
    }
    private static void Clear(DeviceFileReceiveJobTests.Fixture f) { f.Native.Stream.SetLength(0); f.Native.Stream.Position = 0; }
    private static JsonObject Reply(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind,
            ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
    }
    internal static JsonObject Configuration(JsonObject request, bool video, bool enabled = true)
        => Reply(DeviceFileSources.ResultKind, new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(),
            ["operation"] = video ? "configure_videos" : "configure", ["version"] = SourceVersion, ["revision"] = 2,
            ["enabled"] = true, ["associated"] = true, ["repair_pending"] = false,
            ["kinds"] = new JsonArray("camera", "downloads", "screenshots", "whatsapp_received"),
            ["videos"] = new JsonObject { ["enabled"] = video && enabled, ["revision"] = video ? 1 : 0 } });
    internal static JsonObject Catalog(JsonObject request, bool video = false)
    {
        var body = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(),
            ["operation"] = "discover", ["version"] = SourceVersion,
            ["page"] = new JsonObject { ["format"] = 1, ["catalog_id"] = Guid.NewGuid().ToString("D"), ["after"] = 0,
                ["next_cursor"] = null, ["coverage"] = video ? "full_videos" : "full_images", ["proves_deletion"] = false,
                ["albums"] = new JsonArray(new JsonObject { ["album_id"] = Guid.NewGuid().ToString("D"), ["kind"] = "camera", ["display_name"] = "Synthetic camera",
                    ["visible_images"] = 1, ["needs_choice"] = false }) } };
        if (video) body["media_type"] = "video";
        return Reply(DeviceFileSources.CatalogKind, body);
    }
    private static Task Fails(Task task) => DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(task, "Native command was not held.");

    internal static async Task WindowsConfigureDiscoverPermissionAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); Clear(f);
        var legacy = 0; f.Native.DuringReceive = () => legacy++;
        var configuring = f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "images", true);
        var command = Request(f); TestAssert.That(!configuring.IsCompleted && command["body"]!["operation"]!.GetValue<string>() == "configure", "Configure was not an actual correlated output.");
        await f.Native.Connection.HandlePlainAsync(Configuration(command, false)); var configured = await configuring;
        TestAssert.That(configured.Version == SourceVersion && configured.Enabled, "Actual configure reply not returned.");
        Clear(f); var discovering = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); var request = Request(f);
        TestAssert.That(!discovering.IsCompleted && request["body"]!["operation"]!.GetValue<string>() == "discover", "Discovery did not wait for its actual source reply.");
        var reply = Catalog(request); await f.Native.Connection.HandlePlainAsync(reply); var catalog = await discovering;
        TestAssert.That(catalog.Coverage == "full_images" && catalog.Albums.Single().DisplayName == "Synthetic camera", "Typed catalog reply not delivered.");
        TestAssert.That(legacy == 0 && !f.Native.Store.HasIncomingReceipt(f.Native.Peer.Id, reply["message_id"]!.GetValue<string>()), "Native catalog entered generic inbox/callbacks.");
        Clear(f); var requesting = f.Native.Connection.RequestNativeMediaReadAsync(SourceVersion); var permission = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(DeviceFileSources.PermissionResultKind, new JsonObject { ["format"] = 1,
            ["request_id"] = permission["message_id"]!.DeepClone(), ["operation"] = "request_read", ["version"] = SourceVersion, ["state"] = "foreground_required" }));
        TestAssert.That((await requesting).State == "foreground_required", "OS foreground requirement was treated as READ permission.");
    }

    internal static async Task WindowsChoiceAndOutputWithdrawalAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); Clear(f);
        var current = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, current.Version, false, false, false);
        try { await f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); throw new InvalidOperationException("Saved OFF choice reached phone discovery."); }
        catch (InvalidDataException) { }
        TestAssert.That(f.Native.Stream.Length == 0, "Rejected OFF choice wrote source command.");
        current = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, current.Version, true, false, false);
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Stream.BeforeWrite = () => f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, false, false, false);
        await Fails(f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion));
        TestAssert.That(f.Owner.Binding(f.Destination.DestinationToken) is null, "Choice withdrawal during output left the old native data owner usable.");
        f.Native.Stream.BeforeWrite = null;
    }

    internal static async Task WindowsVideoNeedsCurrentPositiveAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var path = Path.Combine(f.Native.Paths.Root, "native-video-target"); Directory.CreateDirectory(path);
        using (var root = DeviceFileNativeDirectory.OpenExistingForReceive(path)) f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, root);
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, true, true, false);
        Clear(f);
        try { await f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video"); throw new InvalidOperationException("Saved video choice fabricated fresh source configuration."); }
        catch (InvalidDataException) { }
        TestAssert.That(f.Native.Stream.Length == 0, "Saved video intent alone sent source READ.");
        var configure = f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "video", true); var command = Request(f);
        TestAssert.That(command["body"]!["operation"]!.GetValue<string>() == "configure_videos" && command["body"]!["media_type"] is null, "Video configuration changed the normative metadata body.");
        await f.Native.Connection.HandlePlainAsync(Configuration(command, true)); await configure;
        var captured = f.Native.Connection.CaptureNativeMediaReceiveBinding(SourceVersion, "video"); TestAssert.That(captured() is not null, "Actual fresh native video configuration did not bind current receiver.");
        Clear(f); var key = f.Native.Paths.TelefonStorageKey; var held = key + ".fixture-held"; File.Move(key, held);
        try { await Fails(f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video")); }
        finally { File.Move(held, key); }
        TestAssert.That(f.Native.Stream.Length == 0, "Missing key emitted a new source READ.");
        await Fails(f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video"));
        try { _ = captured(); throw new InvalidOperationException("Key return revived the earlier video activation."); } catch (InvalidDataException) { }
        var oldBinding = captured;
        Clear(f); var renewed = f.Native.Connection.ConfigureNativeMediaSourceAsync(SourceVersion, "video", true); var renewedRequest = Request(f);
        await f.Native.Connection.HandlePlainAsync(Configuration(renewedRequest, true)); await renewed;
        captured = f.Native.Connection.CaptureNativeMediaReceiveBinding(SourceVersion, "video");
        TestAssert.That(captured() is not null && oldBinding() is null, "Fresh positive configuration revived an old revoked binding instead of creating a new one.");
        Clear(f); var discover = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video"); var query = Request(f);
        TestAssert.That(query["body"]!["media_type"]!.GetValue<string>() == "video", "Video request fell back to images.");
        await f.Native.Connection.HandlePlainAsync(Catalog(query, true)); TestAssert.That((await discover).MediaType == "video", "Video catalog lost its native scope.");
        Clear(f); var off = f.Native.Connection.ConfigureNativeMediaSourceAsync(SourceVersion, "video", false); var offRequest = Request(f);
        await f.Native.Connection.HandlePlainAsync(Configuration(offRequest, true, false)); await off;
        try { _ = captured(); throw new InvalidOperationException("Old video binding survived explicit source decrease."); } catch (InvalidDataException) { }
        try { await f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video"); throw new InvalidOperationException("Disabled video source reused old positive activation."); }
        catch (InvalidDataException) { }
    }

    internal static async Task WindowsPendingCloseAndWrongScopeAsync()
    {
        using (var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync())
        {
            Clear(f); var pending = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); var request = Request(f);
            var wrong = Catalog(request); wrong["body"]!["request_id"] = Guid.NewGuid().ToString("D");
            await Fails(f.Native.Connection.HandlePlainAsync(wrong)); await Fails(pending);
            TestAssert.That(!f.Native.Store.HasIncomingReceipt(f.Native.Peer.Id, wrong["message_id"]!.GetValue<string>()), "Foreign native result became a generic receipt.");
        }
        using (var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync())
        {
            Clear(f); var pending = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); _ = Request(f);
            f.Native.Connection.Dispose(); await Fails(pending);
        }
    }

    internal static async Task WindowsCancellationAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); Clear(f);
        using var already = new CancellationTokenSource(); already.Cancel();
        await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, token: already.Token), "Cancelled-before-admission discovery sent a request.");
        TestAssert.That(f.Native.Stream.Length == 0, "Already-cancelled discovery wrote output.");
        using var cancellation = new CancellationTokenSource();
        var previous = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, token: cancellation.Token); var old = Request(f);
        cancellation.Cancel(); await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(previous, "Native discovery cancellation left its pending task alive.");
        Clear(f); var current = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); var fresh = Request(f);
        TestAssert.That(old["message_id"]!.GetValue<string>() != fresh["message_id"]!.GetValue<string>(), "Canceled request identity was reused.");
        await f.Native.Connection.HandlePlainAsync(Catalog(fresh)); await current;
        await Fails(f.Native.Connection.HandlePlainAsync(Catalog(old)));
        TestAssert.That(f.Owner.Binding(f.Destination.DestinationToken) is null, "Retired catalog reply revived the old route.");
    }

    internal static async Task WindowsSupersededVideoAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var path = Path.Combine(f.Native.Paths.Root, "video"); Directory.CreateDirectory(path);
        using (var directory = DeviceFileNativeDirectory.OpenExistingForReceive(path)) f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, directory);
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, true, true, false);
        Clear(f); var enabling = f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "video", true); var request = Request(f);
        await Fails(f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "video", false));
        TestAssert.That(DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Count == 1, "Overlapping video configuration sent another command.");
        await Fails(f.Native.Connection.HandlePlainAsync(Configuration(request, true))); await Fails(enabling);
        try { _ = f.Native.Connection.CaptureNativeMediaReceiveBinding(SourceVersion, "video"); throw new InvalidOperationException("Superseded positive command armed a native video binding."); }
        catch (InvalidDataException) { }
    }

    internal static async Task WindowsActualTimeoutAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); Clear(f);
        var watch = System.Diagnostics.Stopwatch.StartNew(); var pending = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion); _ = Request(f);
        await DeviceFileConnectionSourcesTests.FailsAsync<TimeoutException>(pending, "Actual unanswered native media command did not time out.");
        TestAssert.That(watch.Elapsed >= TimeSpan.FromSeconds(58) && watch.Elapsed < TimeSpan.FromSeconds(80), "Native media timeout did not enforce the real 60-second deadline.");
        var ticket = f.Owner.ReceiverCommandTicket(); f.Owner.FinishReceiverCommand(ticket);
    }

    internal static async Task WindowsVideoAfterActualDataAckAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false);
        var path = Path.Combine(f.Native.Paths.Root, "video"); Directory.CreateDirectory(path);
        using (var root = DeviceFileNativeDirectory.OpenExistingForReceive(path)) f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, root);
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, true, true, false);
        Clear(f); await Fails(f.Native.Connection.ConfigureNativeMediaSourceAsync(SourceVersion, "video", true));
        TestAssert.That(f.Native.Stream.Length == 0, "Positive video configuration was issued before the current native data ACK.");
        var photos = f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "images", true); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Configuration(request, false)); await photos;
        f.RemoteLocal = new(new(4, new string('e', 64), true, false), f.RemoteLocal.Owner, true);
        var update = f.Phone.Packet(); f.Phone.MarkSent(update); Clear(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(update, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        TestAssert.That(f.Current() is not null, "Actual post-configure data echo did not become ready.");
        Clear(f); var video = f.Native.Connection.ConfigureNativeMediaSourceAsync(SourceVersion, "video", true); var videoRequest = Request(f);
        await f.Native.Connection.HandlePlainAsync(Configuration(videoRequest, true)); await video;
        TestAssert.That(f.Native.Connection.CaptureNativeMediaReceiveBinding(SourceVersion, "video")() is not null, "Current positive video configuration did not arm its actual data scope.");
        f.Local = new(new(8, new string('f', 64), false, true), f.Local.Owner, true); Clear(f);
        await f.Native.Connection.SendNativeFileControlsAsync();
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        var echoed = f.Phone.Packet(); f.Phone.MarkSent(echoed); Clear(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(echoed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        Clear(f); await Fails(f.Native.Connection.DiscoverNativeMediaAlbumsAsync(SourceVersion, "video"));
        TestAssert.That(f.Native.Stream.Length == 0, "A new data-permission ACK inherited the previous video activation.");
    }
}
