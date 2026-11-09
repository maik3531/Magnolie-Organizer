using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileCollectionSourceTests
{
    private const string Book = "{\"syncEpoch\":\"collection-source-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    internal static async Task WindowsNativeFolderChoiceAsync()
        => await NativeFolderChoices(["accept", "cancel", "repeat"]);

    internal static async Task WindowsNativeFolderChoiceGuardsAsync()
        => await NativeFolderChoices(["book", "connection", "intent", "consent", "control", "catalog", "stale", "import-only", "receive-only", "module-off", "photos-off"]);

    private static async Task NativeFolderChoices(string[] scenarios)
    {
        foreach (var scenario in scenarios)
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false, sharedMedia: true);
            void Set(string field, JsonNode value) => f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey,
                field, value, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, field));
            Set("enabled", JsonValue.Create(true)!); Set("direction", JsonValue.Create("pc_to_phone")!);
            Set("collection_mode", JsonValue.Create("entire_collection")!);
            if (scenario == "import-only") Set("collection_mode", JsonValue.Create("import_only")!);
            if (scenario == "receive-only") Set("direction", JsonValue.Create("phone_to_pc")!);
            if (scenario == "module-off") Set("enabled", JsonValue.Create(false)!);
            if (scenario == "photos-off") Set("photos_enabled", JsonValue.Create(false)!);
            await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            var send = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
            send = f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, send.Version, true, false);
            f.Local = new(new(8, new string('c', 64), false, false), f.Local.Owner, true);
            TestAssert.That(f.Owner.Binding(new string('f', 64), true) is null && f.Current() is null,
                "Folder metadata fixture accidentally required positive SEND/RECEIVE data authority.");
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "folder-choice-book"), Book);
            using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
            coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online.Add(f.Native.Peer.Id, f.Native.Connection);
            var receiving = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
            var preference = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
            var path = Path.Combine(f.Native.Paths.Root, "explicit-native-source"); Directory.CreateDirectory(path);
            var bytes = DeviceFileSourceSendTests.PaddedPng(length: 256); var file = Path.Combine(path, "original.png"); File.WriteAllBytes(file, bytes);
            var intent = f.Native.Store.ReadNativeMediaSharedSettings(f.Native.Peer.Id, f.Native.Peer.PublicKey)!;
            var version = f.Native.Connection.NativeMediaSharedUiVersion(intent);
            var initial = coordinator.NativeMediaUiStatus(f.Native.Peer.Id);
            TestAssert.That(initial["collection_sources"]!.AsArray().Count == 0 &&
                (scenario == "import-only" ? initial["collection_sources_version"] is null : initial["collection_sources_version"]!.GetValue<string>() == version),
                "Passive native status invented roots or lost channel/full-intent binding.");
            DeviceFileConnectionRunsTests.Clear(f); DeviceFileNativeDirectory? held = null; var calls = 0;
            DeviceFileNativeDirectory? Picker(Action current)
            {
                calls++; current();
                TestAssert.Throws<InvalidDataException>(() => coordinator.ChooseNativeMediaCollectionFolder(f.Native.Peer.Id, "images", version,
                    _ => throw new Exception("Nested source dialog must never open.")), "Pending native source owner did not retain its slot.");
                TestAssert.Throws<InvalidDataException>(() => coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, send.Version, true, false,
                    () => throw new Exception("Competing send dialog must never open.")), "Source selection overlapped native SEND consent.");
                TestAssert.That(f.Native.Store.NativeMediaCollectionRoots(f.Native.Peer.Id).Count == 0,
                    "Source folder was registered before the real native selection.");
                if (scenario == "cancel") return null;
                if (scenario == "book") typeof(PersonalActorNativeSaveHost).GetProperty("currentPlainTextAvailable",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(host, false);
                if (scenario == "connection") online.Remove(f.Native.Peer.Id);
                if (scenario == "intent") Set("auto_mode", JsonValue.Create("wifi")!);
                if (scenario == "consent") f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, send.Version, false, false);
                if (scenario == "control")
                {
                    var packet = f.Phone.Packet(); f.Phone.MarkSent(packet);
                    f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(packet, Now())).GetAwaiter().GetResult();
                }
                if (scenario == "catalog")
                {
                    var other = Path.Combine(f.Native.Paths.Root, "other-explicit-native-source"); Directory.CreateDirectory(other);
                    using var owner = DeviceFileNativeDirectory.OpenExisting(other);
                    f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", owner, () => { });
                }
                return held = DeviceFileNativeDirectory.OpenExisting(path);
            }
            if (scenario is "accept" or "cancel" or "repeat")
            {
                var reply = coordinator.ChooseNativeMediaCollectionFolder(f.Native.Peer.Id, "images", version, Picker);
                TestAssert.That(reply["collection_sources"]!.AsArray().Count == (scenario == "cancel" ? 0 : 1) &&
                    (reply["canceled"]?.GetValue<bool>() == true) == (scenario == "cancel"), "Native picker result did not control append-only selection.");
                if (scenario == "repeat") coordinator.ChooseNativeMediaCollectionFolder(f.Native.Peer.Id, "images", version,
                    current => { current(); return held = DeviceFileNativeDirectory.OpenExisting(path); });
            }
            else TestAssert.Throws<InvalidDataException>(() => coordinator.ChooseNativeMediaCollectionFolder(f.Native.Peer.Id, "images",
                scenario == "stale" ? new string('e', 64) : version, Picker), "Late folder selection adopted a changed original context: " + scenario);
            TestAssert.That(calls == (scenario is "stale" or "import-only" or "receive-only" or "module-off" or "photos-off" ? 0 : 1), "A stale/disabled request reached the native dialog or a native dialog was replayed.");
            if (held is not null) TestAssert.Throws<ObjectDisposedException>(() => held.CurrentIdentity(), "Selected native directory survived result/failed commit.");
            var roots = f.Native.Store.NativeMediaCollectionRoots(f.Native.Peer.Id);
            TestAssert.That(roots.Count == (scenario is "accept" or "repeat" or "catalog" ? 1 : 0) &&
                File.ReadAllBytes(file).SequenceEqual(bytes) && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0 &&
                f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id) == receiving && f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id) == preference,
                "Source choice read/sent/mutated originals or changed receiving/preferences/history: " + scenario);
            if (scenario != "control") TestAssert.That(f.Native.Stream.Length == 0, "Folder configuration sent a packet or started transfer.");
        }
    }
    private static async Task<DeviceFileReceiveJobTests.Fixture> Fixture()
    {
        var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false, sharedMedia: true);
        try
        {
            void Set(string field, JsonNode value) => f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, field,
                value, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, field));
            Set("enabled", JsonValue.Create(true)!); Set("direction", JsonValue.Create("pc_to_phone")!);
            Set("collection_mode", JsonValue.Create("entire_collection")!); Set("photos_only", JsonValue.Create(false)!);
            await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            await DeviceFileMappedSourceTests.AllowSending(f, pcReceive: false, phoneRead: false);
            TestAssert.That(f.Current() is null && f.Owner.Binding(new string('f', 64), true) is not null,
                "Independent PC source fixture still depends on PC RECEIVE or phone READ.");
            return f;
        }
        catch { f.Dispose(); throw; }
    }

    private static NativeMediaCollectionRoot Select(DeviceFileReceiveJobTests.Fixture f, byte[] bytes)
    {
        var path = Path.Combine(f.Native.Paths.Root, "selected-pc-source"); Directory.CreateDirectory(path);
        File.WriteAllBytes(Path.Combine(path, "new-pc.png"), bytes);
        using var root = DeviceFileNativeDirectory.OpenExisting(path);
        return f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
    }

    private static DeviceFileNativeDirectory.CollectionMember Member(NativeMediaCollectionRoot selection)
    {
        using var root = selection.OpenNative(); return root.InventoryCollection(() => { }, CancellationToken.None).Members.Single();
    }

    private static JsonObject Record(DeviceFileReceiveJobTests.Fixture f, string job)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; read.Parameters.AddWithValue("$job", job);
        var clear = f.Native.Store.Open("native_media_source_job", f.Native.Peer.Id + "/" + job, (byte[])read.ExecuteScalar()!);
        try { return JsonNode.Parse(clear)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(clear); }
    }

    private static async Task SendToEnd(DeviceFileReceiveJobTests.Fixture f, TelefonStore.NativePreparedMediaSource cache, byte[] expected, string? expectedPrevious = null,
        Task? production = null, int offerIndex = 0, bool mapped = false)
    {
        if (production is null) DeviceFileConnectionRunsTests.Clear(f);
        using var stop = new CancellationTokenSource();
        var send = production ?? f.Native.Connection.SendNativeMappedMediaSourceToSourceEndAsync(cache, stop.Token);
        try
        {
            var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind, offerIndex);
            var media = MediaOfferEnvelope.Validate(offer, cache.Manifest.SenderId, cache.Manifest.ReceiverId, Now());
            TestAssert.That(media.Originals.Count == (mapped ? 1 : 0) && media.MimeTypes[cache.Manifest.Files[0].Id]!.GetValue<string>() == "image/png",
                "Independent PC source invented a phone reference or lost actual byte-derived MIME.");
            if (mapped) TestAssert.That(media.PcOrigins.Count == 0 && Record(f, cache.JobId)["local_origin"] is null,
                "Mapped source was silently relabelled as an independent PC origin.");
            else
            {
                var origin = media.PcOrigins[cache.Manifest.Files[0].Id]!.AsObject();
            TestAssert.That(offer["body"]!["format"]!.GetValue<int>() == 2 && media.PcOrigins.Count == 1 &&
                origin["origin_sha256"]!.GetValue<string>() == DeviceFileControl.Digest("magnolie-pc-media-origin-v1\0", Record(f, cache.JobId)["local_origin"]!) &&
                origin["previous_publication_sha256"]?.GetValue<string>() == expectedPrevious,
                "Actual wire did not bind opaque PC origin and exact previously completed publication without leaking native identity/path.");
            }
            var acceptance = DeviceFileSourceSendTests.Accept(f, cache, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
            var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Now()); var chunks = (expected.Length + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes;
            for (var index = 0; index < chunks; index++)
            {
                var request = DeviceFileSourceSendTests.Chunk(cache, acceptance, offer, index); await f.Native.Connection.HandlePlainAsync(request);
                var response = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.ResultKind, offerIndex * chunks + index);
                var bytes = DeviceFileChunkEnvelope.ParseResponse(response, request, cache.Manifest, accepted, Now());
                try { TestAssert.That(bytes.SequenceEqual(expected.Skip(index * DeviceFileManifest.ChunkBytes).Take(DeviceFileManifest.ChunkBytes)), "Actual encrypted output lost independent original PC bytes."); }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            await f.Native.Connection.HandlePlainAsync(DeviceFileSourceSendTests.Saved(cache, acceptance, offer));
            TestAssert.That(!send.IsCompleted && DeviceFileSourceSendTests.Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "peer_saved",
                "Peer Saved alone became own source-END.");
            TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded, "Peer Saved manufactured independent source END.");
            var file = cache.Manifest.Files.Single();
            var context = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(),
                ["manifest_sha256"] = cache.Manifest.Fingerprint, ["transfer_id"] = cache.Manifest.TransferId, ["source_id"] = cache.Manifest.SourceId,
                ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["media_type"] = "images", ["mime_type"] = "image/png",
                ["publication_sha256"] = new string('b', 64), ["row_sha256"] = new string('d', 64),
                ["permission_epoch"] = acceptance["body"]!["permission_epoch"]!.DeepClone(), ["readback_nonce"] = new string('e', 64) };
            var binding = f.Owner.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), true)!;
            var readback = DeviceFileSourceSendTests.Message(DevicePublishedReadbackEnvelope.Kind, DevicePublishedReadbackEnvelope.EncodeBody(context, binding), offer);
            await f.Native.Connection.HandlePlainAsync(readback);
            if (production is null) await send;
            else
            {
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
                while (true)
                {
                    try { cache.RequireIoEnded(); break; }
                    catch (InvalidDataException) when (!production.IsCompleted) { await Task.Delay(10, deadline.Token); }
                }
            }
            cache.RequireIoEnded();
            TestAssert.That(DeviceFileSourceSendTests.Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "source_ended" &&
                DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]!.GetValue<string>() != DeviceFileSources.RequestKind),
                "Independent source did not reach actual native END or requested phone source READ/discovery.");
        }
        finally { stop.Cancel(); if (production is null) try { await send; } catch { } }
    }

    internal static async Task WindowsCollectionProducerAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        File.WriteAllBytes(Path.Combine(selection.NativePath, "second.png"), data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "collection-producer-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var controls = f.Owner.Binding(new string('0', 64), true); var receiving = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(180)); // Test management only; each actual sender retains its own original60s.
        DeviceFileConnectionRunsTests.Clear(f);
        var clock = System.Diagnostics.Stopwatch.StartNew();
        var production = f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, stop.Token, automatic: false);
        var ended = new List<string>();
        try
        {
            for (var index = 0; index < 2; index++)
            {
                for (var attempt = 0; ; attempt++)
                {
                    try { await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind, index); break; }
                    catch (TimeoutException) when (!production.IsCompleted && attempt < 3) { }
                    catch (TimeoutException) { if (production.IsCompleted) await production; throw; }
                }
                Console.WriteLine("Collection producer actual offer " + index + " at " + clock.ElapsedMilliseconds + "ms");
                foreach (var previous in ended)
                    TestAssert.That(DeviceFileSourceSendTests.Exchange(f, previous)["phase"]!.GetValue<string>() == "source_ended",
                        "A following original was offered before actual independent backup/source END.");
                var run = (TelefonConnection.NativeMediaSendRun)typeof(TelefonConnection).GetField("nativeMediaSend",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(f.Native.Connection)!;
                await SendToEnd(f, run.Cache, data, production: production, offerIndex: index);
                Console.WriteLine("Collection producer actual END " + index + " at " + clock.ElapsedMilliseconds + "ms");
                ended.Add(run.Cache.JobId);
            }
            var result = await production;
            TestAssert.That(result.Sent == 2 && !result.NeedsReview && ended.Distinct().Count() == 2,
                "Selected native roots were not composed into complete independent originals.");
            var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
            DeviceFileConnectionRunsTests.Clear(f);
            result = await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, stop.Token, automatic: false);
            TestAssert.That(result.Sent == 0 && !result.NeedsReview && f.Native.Stream.Length == 0 &&
                before.SequenceEqual(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id)), "Fresh unchanged collection resent payload or changed old history.");
            TestAssert.That(f.Current() is null && f.Owner.Binding(new string('0', 64), true) == controls &&
                f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id) == receiving, "Collection producer acquired PC RECEIVE/phone READ or changed consent.");
        }
        finally { stop.Cancel(); try { await production; } catch { } }
    }

    internal static async Task WindowsCollectionProducerGuardsAsync()
    {
        foreach (var scenario in new[] { "automatic", "no_roots", "catalog", "same_size", "book", "local_send", "control" })
        {
            using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256);
            var selection = scenario == "no_roots" ? null : Select(f, data);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "collection-guard-book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); var changed = false;
            void Current()
            {
                if (changed || selection is null || scenario is "automatic" or "no_roots") return;
                // First source admission occurs only after the pass froze its
                // inventory; change from its subsequent native source callback.
                if (!new System.Diagnostics.StackTrace().GetFrames().Any(frame => frame.GetMethod()?.Name == "OpenNativeCollectionMediaSource")) return;
                changed = true;
                if (scenario == "book") typeof(PersonalActorNativeSaveHost).GetProperty("currentPlainTextAvailable",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(host, false);
                else if (scenario == "local_send")
                {
                    var consent = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                    f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, consent.Version, false, false);
                }
                else if (scenario == "control")
                    f.Local = new(new(99, new string('e', 64), false, false), f.Local.Owner, true);
                else if (scenario == "same_size")
                { var raw = data.ToArray(); raw[^1] ^= 1; File.WriteAllBytes(Path.Combine(selection.NativePath, "new-pc.png"), raw); }
                else
                {
                    var path = Path.Combine(f.Native.Paths.Root, "other-source"); Directory.CreateDirectory(path);
                    using var root = DeviceFileNativeDirectory.OpenExisting(path);
                    f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
                }
            }
            try
            {
                await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, Current, CancellationToken.None, automatic: scenario == "automatic");
                throw new Exception("Changed/unsupported collection scope completed: " + scenario);
            }
            catch (InvalidDataException error)
            {
                TestAssert.That(scenario switch {
                    "automatic" => error.Message == "media_source_entire_collection_automatic_acceptance_required",
                    "no_roots" => error.Message == "media_collection_explicit_source_roots_required",
                    "catalog" => error.Message == "media_collection_original_catalog_changed",
                    "book" => error.Message == "file_media_current_saved_book_required",
                    "local_send" => error.Message == "media_source_local_consent_required" || error.Message == "media_collection_current_owner_required",
                    "control" => error.Message == "media_collection_original_send_binding_required" || error.Message == "media_source_current_sending_owner_required",
                    _ => error.Message == "media_collection_original_inventory_changed" || error.Message == "media_collection_original_content_changed"
                }, "Collection guard held for unexpected reason: " + error.Message);
            }
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
                "Unaccepted/changed inventory created a source job.");
        }
    }

    internal static async Task WindowsCollectionProducerSuccessorAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "collection-successor-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var original = Member(selection);
        var before = Array.Empty<(string JobId, string Version, string Phase)>();
        for (var pass = 0; pass < 2; pass++)
        {
            if (pass == 1)
            {
                before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
                data = DeviceFileSourceSendTests.PaddedPng(1, 256); File.WriteAllBytes(Path.Combine(selection.NativePath, "new-pc.png"), data);
                var changed = Member(selection);
                TestAssert.That(changed.Identity == original.Identity && changed.CreationFileTime == original.CreationFileTime,
                    "Changed collection test replaced the original generation.");
            }
            DeviceFileConnectionRunsTests.Clear(f); using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(100));
            var production = f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, stop.Token, automatic: false);
            try
            {
                await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
                var run = (TelefonConnection.NativeMediaSendRun)typeof(TelefonConnection).GetField("nativeMediaSend",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(f.Native.Connection)!;
                await SendToEnd(f, run.Cache, data, expectedPrevious: pass == 0 ? null : new string('b', 64), production: production);
                var result = await production;
                TestAssert.That(result.Sent == 1 && !result.NeedsReview, "Changed collection original did not complete through real successor END.");
                if (pass == 1) TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 2 &&
                    before.All(previous => f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Contains(previous)), "Collection successor changed or evicted its actual predecessor.");
            }
            finally { stop.Cancel(); try { await production; } catch { } }
        }
    }

    internal static async Task WindowsCollectionProducerLateInventoryAsync()
    {
        foreach (var fault in new[] { "same_size_after_end", "added_after_end" })
        {
            using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "collection-late-book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); var changed = false;
            string? completed = null;
            void Current()
            {
                if (changed || completed is null || DeviceFileSourceSendTests.Exchange(f, completed)["phase"]!.GetValue<string>() != "source_ended") return;
                changed = true;
                var raw = data.ToArray(); raw[^1] ^= 1;
                File.WriteAllBytes(Path.Combine(selection.NativePath, fault == "same_size_after_end" ? "new-pc.png" : "later.png"), raw);
            }
            DeviceFileConnectionRunsTests.Clear(f); using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(100));
            var production = f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, Current, stop.Token, automatic: false);
            try
            {
                await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
                var run = (TelefonConnection.NativeMediaSendRun)typeof(TelefonConnection).GetField("nativeMediaSend",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(f.Native.Connection)!;
                completed = run.Cache.JobId;
                await SendToEnd(f, run.Cache, data, production: production);
                try { await production; throw new Exception("Late native inventory change became whole-collection completion."); }
                catch (InvalidDataException error)
                { TestAssert.That(error.Message == "media_collection_original_inventory_changed", "Late change held for the wrong cause: " + error.Message); }
                TestAssert.That(changed && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 1 &&
                    DeviceFileSourceSendTests.Exchange(f, completed)["phase"]!.GetValue<string>() == "source_ended",
                    "Whole-pass HOLD erased a genuine completed individual source.");
            }
            finally { stop.Cancel(); try { await production; } catch { } }
        }
    }

    internal static async Task WindowsCollectionMappedOverlapAsync()
        => await CollectionMappedOverlap(changed: false);

    internal static async Task WindowsCollectionChangedMappedOverlapAsync()
        => await CollectionMappedOverlap(changed: true);

    internal static async Task WindowsCollectionPreviousDestinationAsync()
        => await CollectionMappedOverlap(changed: false, previousDestination: true);

    private static async Task CollectionMappedOverlap(bool changed, bool previousDestination = false)
    {
        using var f = await DeviceFileMappedSourceTests.Established();
        foreach (var (field, value) in new[] { ("direction", "pc_to_phone"), ("collection_mode", "entire_collection") })
            f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, field,
                JsonValue.Create(value)!, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, field));
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        await DeviceFileMappedSourceTests.AllowSending(f, pcReceive: false, phoneRead: false);
        using (var root = DeviceFileNativeDirectory.OpenExisting(f.Root))
            f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
        if (previousDestination)
        {
            var path = Path.Combine(f.Native.Paths.Root, "new-receive-destination"); Directory.CreateDirectory(path);
            using var root = DeviceFileNativeDirectory.OpenExistingForReceive(path);
            var destination = f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images");
            var receiveHistory = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
            try
            {
                f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "images", f.Destination.Version, root);
                throw new Exception("Unimplemented destination migration silently replaced the original mapping root.");
            }
            catch (InvalidDataException error)
            { TestAssert.That(error.Message == "file_destination_existing_history_required", "Destination change held for unrelated reason."); }
            TestAssert.That(f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == destination &&
                receiveHistory.SequenceEqual(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id)) && !Directory.EnumerateFileSystemEntries(path).Any(),
                "Refused destination migration changed old tokens/history or wrote to unselected root.");
        }
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "mapped-overlap-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        if (changed) File.WriteAllBytes(Path.Combine(f.Root, "first.jpg"), DeviceFileSourceSendTests.PaddedPng(length: 256));
        var first = File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")); var second = File.ReadAllBytes(Path.Combine(f.Root, "second.jpg"));
        DeviceFileConnectionRunsTests.Clear(f);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var production = f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, deadline.Token, automatic: false);
        try
        {
            if (changed)
            {
                await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
                var run = (TelefonConnection.NativeMediaSendRun)typeof(TelefonConnection).GetField("nativeMediaSend",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(f.Native.Connection)!;
                await SendToEnd(f, run.Cache, first, production: production, mapped: true);
            }
            var result = await production;
            TestAssert.That(result.Sent == (changed ? 1 : 0) && !result.NeedsReview && (changed || f.Native.Stream.Length == 0) &&
                f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == (changed ? 1 : 0) && history.SequenceEqual(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id)) &&
                File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(first) && File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(second),
                "Actual fully compared mapped originals inside selected root were duplicated, relabelled or mutated.");
            if (changed) TestAssert.That(DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Count(frame => frame["kind"]!.GetValue<string>() == MediaOfferEnvelope.Kind) == 1,
                "A completed mapped original was offered a second time as a PC source.");
        }
        finally { deadline.Cancel(); try { await production; } catch { } }
    }

    internal static async Task WindowsCollectionOverlapGuardsAsync()
    {
        foreach (var scenario in new[] { "late_edit", "filtered_no_witness", "unprepared", "foreign_owner", "historical_source" })
        {
            using var f = await DeviceFileMappedSourceTests.Established();
            f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode",
                JsonValue.Create("entire_collection")!, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode"));
            if (scenario == "filtered_no_witness") f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only",
                JsonValue.Create(true)!, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only"));
            await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            await DeviceFileMappedSourceTests.AllowSending(f, pcReceive: false, phoneRead: false);
            using (var root = DeviceFileNativeDirectory.OpenExisting(f.Root))
                f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "overlap-guards-book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
            if (scenario is "unprepared" or "foreign_owner" or "historical_source")
            {
                var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
                using var source = f.Native.Connection.OpenNativeMappedMediaSource("images", history.JobId, history.Version, 1.ToString("x32"), new string('f', 64), book);
                if (scenario != "unprepared") source.PrepareManifest();
                if (scenario == "historical_source") source.Dispose();
                var passType = typeof(TelefonConnection).GetNestedType("NativeCollectionMediaPass", System.Reflection.BindingFlags.NonPublic)!;
                using var pass = (IDisposable)Activator.CreateInstance(passType, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                    null, [f.Native.Store, f.Native.Peer.Id, "images", (Action)(() => { }), CancellationToken.None,
                        scenario == "foreign_owner" ? new object() : f.Native.Connection], null)!;
                try
                {
                    if (scenario == "unprepared") passType.GetMethod("AdmitMapping", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.Invoke(pass, [source]);
                    passType.GetMethod("NoteCheckedMapping", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.Invoke(pass, [source]);
                    throw new Exception("Foreign/unprepared native source became an original mapping comparison witness.");
                }
                catch (System.Reflection.TargetInvocationException error)
                {
                    TestAssert.That(error.InnerException is InvalidDataException rejected && rejected.Message ==
                        (scenario == "unprepared" ? "media_collection_actual_mapping_comparison_required" : "media_collection_original_mapping_observation_required"),
                        "Mapping witness rejected for an unrelated reason.");
                }
                continue;
            }
            var edited = false;
            void Current()
            {
                if (scenario != "late_edit" || edited || !new System.Diagnostics.StackTrace().GetFrames().Any(frame =>
                    frame.GetMethod()?.DeclaringType?.Name == "NativeCollectionMediaPass" && frame.GetMethod()?.Name == "Check")) return;
                var path = Path.Combine(f.Root, "first.jpg"); var bytes = File.ReadAllBytes(path); bytes[^1] ^= 1;
                File.WriteAllBytes(path, bytes); edited = true;
            }
            DeviceFileConnectionRunsTests.Clear(f);
            try
            {
                await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, Current, CancellationToken.None, automatic: false);
                throw new Exception("Late or absent mapped comparison became complete collection: " + scenario);
            }
            catch (InvalidDataException error)
            {
                TestAssert.That(error.Message == (scenario == "late_edit" ? "media_collection_original_inventory_changed" : "media_collection_existing_mapping_required"),
                    "Overlap witness held for an unrelated reason: " + error.Message);
            }
            TestAssert.That((scenario != "late_edit" || edited) && f.Native.Stream.Length == 0 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
                "Invalid overlap proof manufactured an offer/history entry.");
        }
    }

    internal static async Task WindowsCollectionKnownOppositeTypeAsync()
    {
        using var f = await Fixture();
        var data = new byte[] { 0,0,0,16, 102,116,121,112, 105,115,111,109, 0,0,0,0 };
        var selection = Select(f, data); // Deliberately named .png: extensions are not classification.
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "known-opposite-type-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var consent = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
        DeviceFileConnectionRunsTests.Clear(f);
        var result = await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, CancellationToken.None, automatic: false);
        TestAssert.That(result.Sent == 0 && !result.NeedsReview && !consent.Videos &&
            f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id) == consent && f.Native.Stream.Length == 0 &&
            f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0 && File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data),
            "Known opposite container was exported, relabelled, granted video SEND or treated as unknown incomplete inventory.");
    }

    internal static async Task WindowsCollectionKindGuardsAsync()
    {
        foreach (var scenario in new[] { "unknown", "broken_dimensions", "photos_only_mixed" })
        {
            using var f = await Fixture(); var bytes = DeviceFileSourceSendTests.PaddedPng(length: 256);
            if (scenario == "unknown") bytes = "not a media file"u8.ToArray();
            if (scenario == "broken_dimensions") System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(bytes.AsSpan(16), 40000);
            var selection = Select(f, bytes);
            if (scenario == "photos_only_mixed")
            {
                File.WriteAllBytes(Path.Combine(selection.NativePath, "not-an-image.jpg"), [0,0,0,16,102,116,121,112,105,115,111,109,0,0,0,0]);
                f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only", JsonValue.Create(true)!,
                    f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only"));
                await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            }
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "collection-kind-guard-book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); DeviceFileConnectionRunsTests.Clear(f);
            try
            {
                var result = await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, () => { }, CancellationToken.None, automatic: false);
                TestAssert.That(scenario == "photos_only_mixed" && result.Sent == 0 && !result.NeedsReview, "Unknown/malformed bytes became a known media exclusion.");
            }
            catch (InvalidDataException error)
            {
                TestAssert.That(scenario != "photos_only_mixed" && error.Message ==
                    (scenario == "unknown" ? "media_source_mime_unknown" : "media_source_mime_dimensions"), "Unknown kind held for wrong cause: " + error.Message);
            }
            TestAssert.That(f.Native.Stream.Length == 0 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
                "Excluded/unknown source created an offer or publication history.");
        }
    }

    internal static async Task WindowsActualSourceAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); var original = Member(selection);
        TelefonStore.NativeCollectionMediaSource Open() => f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using (var source = Open())
        using (var cache = source.Freeze())
        {
            var record = Record(f, cache.JobId);
            TestAssert.That(record["format"]!.GetValue<int>() == 3 && record["originals"]!.AsObject().Count == 0 &&
                record["local_origin"]!["root_id"]!.GetValue<string>() == selection.Id && !record["provenance"]!.AsObject().ContainsKey("mapping_job") &&
                !f.Native.Store.HasNativeMediaSourceReference(f.Native.Peer.Id, new JsonObject { ["not"] = "a phone reference" }),
                "Protected PC-origin cache invented/claimed a phone mapping or used the legacy cache schema.");
            await SendToEnd(f, cache, data);
        }
        var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        using (var unchanged = Open()) TestAssert.Throws<InvalidDataException>(() => unchanged.FreezeCompletedSuccessor(), "Already-completed unchanged PC payload was resent.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == before, "Unchanged source appended or discarded history.");
        data = DeviceFileSourceSendTests.PaddedPng(1, 256); File.WriteAllBytes(Path.Combine(selection.NativePath, "new-pc.png"), data);
        var changed = Member(selection);
        TestAssert.That(changed.Identity == original.Identity && changed.CreationFileTime == original.CreationFileTime, "Version fixture accidentally replaced its source generation.");
        // Older internal local caches could have ended with v1 (no stable wire
        // association). Preserve them, but never infer a receiver association.
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT value FROM native_media_source_exchanges WHERE job_id=$job";
            query.Parameters.AddWithValue("$job", before.JobId); var originalExchange = (byte[])query.ExecuteScalar()!;
            var old = DeviceFileSourceSendTests.Exchange(f, before.JobId); old["offer"]!["body"]!["format"] = 1; old["offer"]!["body"]!.AsObject().Remove("pc_origins");
            var bytes = TelefonCrypto.Canonical(old); byte[] cipher;
            try { cipher = f.Native.Store.Seal("native_media_source_exchange", f.Native.Peer.Id + "/" + before.JobId, bytes); }
            finally { CryptographicOperations.ZeroMemory(bytes); }
            using var update = db.CreateCommand(); update.CommandText = "UPDATE native_media_source_exchanges SET value=$value WHERE job_id=$job";
            update.Parameters.AddWithValue("$job", before.JobId); var value = update.Parameters.Add("$value", Microsoft.Data.Sqlite.SqliteType.Blob); value.Value = cipher; update.ExecuteNonQuery();
            try
            {
                using var unbound = Open(); TestAssert.Throws<InvalidDataException>(() => unbound.FreezeCompletedSuccessor(), "Old v1 local predecessor acquired an inferred stable phone publication association.");
                TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == before, "Unbound predecessor HOLD changed local source history.");
            }
            finally { value.Value = originalExchange; update.ExecuteNonQuery(); }
        }
        using (var source = Open())
        using (var cache = source.FreezeCompletedSuccessor())
        {
            var record = Record(f, cache.JobId);
            TestAssert.That(record["format"]!.GetValue<int>() == 4 && record["previous"]!["job_id"]!.GetValue<string>() == before.JobId,
                "Changed independent PC payload lost its latest completed source lineage.");
            await SendToEnd(f, cache, data, new string('b', 64));
        }
        var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        File.SetCreationTimeUtc(Path.Combine(selection.NativePath, "new-pc.png"), DateTime.FromFileTimeUtc((long)original.CreationFileTime).AddSeconds(-5));
        using (var changedGeneration = Open())
            TestAssert.Throws<InvalidDataException>(() => changedGeneration.FreezeCompletedSuccessor(), "Known native file ID with a different creation witness silently inherited/replaced source history.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
            File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data),
            "Independent source versions altered incoming history, original bytes or existing source records.");
        File.SetCreationTimeUtc(Path.Combine(selection.NativePath, "new-pc.png"), DateTime.FromFileTimeUtc((long)original.CreationFileTime));
        var secondPath = Path.Combine(f.Native.Paths.Root, "second-pc-source"); Directory.CreateDirectory(secondPath);
        NativeMediaCollectionRoot second;
        using (var selected = DeviceFileNativeDirectory.OpenExisting(secondPath))
            second = f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", selected, () => { });
        File.Move(Path.Combine(selection.NativePath, "new-pc.png"), Path.Combine(secondPath, "new-pc.png"));
        var moved = Member(second);
        TestAssert.That(moved.Identity == original.Identity && moved.CreationFileTime == original.CreationFileTime,
            "Cross-root relocation fixture did not retain actual native file identity and generation.");
        using (var relocated = f.Native.Connection.OpenNativeCollectionMediaSource("images", second.Id, second.Version, moved, new string('f', 64), book))
            TestAssert.Throws<InvalidDataException>(() => relocated.FreezeCompletedSuccessor(),
                "Moving the same known native file to another selected root minted an independent PC origin.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            File.ReadAllBytes(Path.Combine(secondPath, "new-pc.png")).SequenceEqual(data),
            "Cross-root HOLD changed retained source history or original bytes.");
        File.Move(Path.Combine(secondPath, "new-pc.png"), Path.Combine(selection.NativePath, "retained-original.png"));
        var replacementPath = Path.Combine(selection.NativePath, "new-pc.png"); File.WriteAllBytes(replacementPath, data);
        DeviceFileNativeDirectory.CollectionMember replacement;
        using (var selected = selection.OpenNative())
            replacement = selected.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "new-pc.png");
        TestAssert.That(replacement.Identity != original.Identity,
            "Known-path reassociation fixture did not create a genuinely different native file ID.");
        using (var replacedPath = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, replacement, new string('f', 64), book))
            TestAssert.Throws<InvalidDataException>(() => replacedPath.FreezeCompletedSuccessor(),
                "A new native file ID at a known PC source path minted a second initial origin.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            File.ReadAllBytes(replacementPath).SequenceEqual(data) && File.ReadAllBytes(Path.Combine(selection.NativePath, "retained-original.png")).SequenceEqual(data),
            "Known-path HOLD changed retained history or either native file.");
    }

    internal static async Task WindowsPreparedBackupAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: DeviceFileManifest.ChunkBytes * 2 + 7);
        var selection = Select(f, data); var member = Member(selection);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "backup-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var outputPath = Path.Combine(f.Native.Paths.Root, "explicit-pc-backup-output"); Directory.CreateDirectory(outputPath);
        NativeMediaBackupVersion saved; NativeMediaBackupParent outputChoice;
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, member, new string('f', 64), book))
        using (var cache = source.Freeze())
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(outputPath))
        {
            var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
            using (var readOnly = selection.OpenNative())
                TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, readOnly, () => true, true),
                    "A read-only source selection granted implicit backup writes.");
            TestAssert.That(!Directory.Exists(Path.Combine(selection.NativePath, "Backup")), "Rejected read-only source output created a Backup folder.");
            outputChoice = NativeMediaBackupParent.Capture(output);
            saved = f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true, true);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaBackupToDestination(f.Destination, saved, () => true, outputChoice),
                "A prepared PC backup acquired synchronized publication through the incoming restore owner.");
            var files = Directory.GetFiles(Path.Combine(outputPath, "Backup")).Order().ToArray();
            TestAssert.That(f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true) == saved &&
                Directory.GetFiles(Path.Combine(outputPath, "Backup")).Order().SequenceEqual(files), "Identical prepared backup renewed its version or copied again.");
            TestAssert.That(f.Current() is null && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 && File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data),
                "PC backup required RECEIVE, forged incoming history or modified the read-only source.");
            File.WriteAllBytes(Path.Combine(selection.NativePath, "another-pc.png"), data);
            DeviceFileNativeDirectory.CollectionMember another;
            using (var root = selection.OpenNative()) another = root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "another-pc.png");
            using var second = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, another, new string('f', 64), book);
            using var secondCache = second.Freeze();
            var other = f.Native.Store.SaveNativePreparedPcBackup(secondCache, output, () => true);
            TestAssert.That(other.Id != saved.Id && other.ObjectKey == saved.ObjectKey && Directory.GetFiles(Path.Combine(outputPath, "Backup"), "object-*.raw").Length == 1,
                "Independent source versions lost distinct provenance or failed content deduplication.");
        }
        f.Native.Connection.Dispose();
        File.Move(Path.Combine(selection.NativePath, "new-pc.png"), Path.Combine(selection.NativePath, "retained-original.png"));
        // Make the encrypted transfer cache genuinely unavailable without
        // deleting it or modifying backup bytes/anchors. Recovery must not read it.
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var query = db.CreateCommand(); query.CommandText = "ALTER TABLE native_media_source_chunks RENAME TO retained_offline_source_chunks"; query.ExecuteNonQuery();
        }
        var snapshots = Directory.GetFiles(Path.Combine(outputPath, "Backup")).ToDictionary(path => path, File.ReadAllBytes);
        TestAssert.That(f.Native.Store.NativeIndependentBackupVersions(outputChoice, () => true).Count == 2, "Offline source recovery still needed a live peer/cache/source file.");
        using (var output = outputChoice.OpenNative())
        using (var target = output.CreateStagedFile("restored-offline.png"))
        {
            _ = f.Native.Store.RestoreNativeIndependentBackup(outputChoice, saved, target, () => true);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeIndependentBackup(outputChoice, saved, target, () => true), "Offline restore overwrote a nonempty candidate.");
        }
        TestAssert.That(File.ReadAllBytes(Path.Combine(outputPath, "restored-offline.png")).SequenceEqual(data) &&
            snapshots.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)), "Offline recovery altered backup bytes/snapshots or lost original content.");
    }

    internal static Task WindowsPreparedBackupInterruptedAsync() => PreparedBackupInterrupted(false);
    internal static Task WindowsPreparedBackupCorruptAsync() => PreparedBackupInterrupted(true);
    private static async Task PreparedBackupInterrupted(bool corrupt)
    {
        {
            using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: DeviceFileManifest.ChunkBytes * 2 + 7);
            var selection = Select(f, data); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "backup-book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
            using var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
            using var cache = source.Freeze(); var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
            var outputPath = Path.Combine(f.Native.Paths.Root, "explicit-output"); Directory.CreateDirectory(outputPath);
            using var output = DeviceFileNativeDirectory.OpenExistingForReceive(outputPath); var parent = NativeMediaBackupParent.Capture(output);
            var key = NativeMediaBackupPolicy.ContentKey(data.Length, Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant());
            var payload = Path.Combine(outputPath, "Backup", "object-" + key + ".raw");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output,
                () => !File.Exists(payload) || new FileInfo(payload).Length == 0, true), "Withdrawn local output owner falsely completed a prepared source backup.");
            TestAssert.That(new FileInfo(payload).Length is > 0 && new FileInfo(payload).Length < data.Length &&
                f.Native.Store.NativeIndependentBackupVersions(parent, () => true).Count == 0, "Partial source backup was lost or falsely recoverable as complete.");
            DeviceFileNativeDirectory.Identity identity;
            using (var folder = DeviceFileNativeDirectory.OpenExistingForReceive(Path.Combine(outputPath, "Backup"))) identity = folder.FileIdentityAt(Path.GetFileName(payload));
            if (corrupt)
            {
                using (var stream = new FileStream(payload, FileMode.Open, FileAccess.Write)) { stream.WriteByte(42); stream.Flush(true); }
                var before = File.ReadAllBytes(payload);
                TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true), "A corrupted prepared-source backup prefix was silently replaced/truncated.");
                TestAssert.That(File.ReadAllBytes(payload).SequenceEqual(before), "Prefix HOLD changed retained candidate bytes.");
            }
            else
            {
                // Model an interrupted partial filesystem write. Only this
                // private fixture shortens its own candidate, never product IO.
                using (var stream = new FileStream(payload, FileMode.Open, FileAccess.Write)) { stream.SetLength(17); stream.Flush(true); }
                var saved = f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true);
                using var folder = DeviceFileNativeDirectory.OpenExistingForReceive(Path.Combine(outputPath, "Backup"));
                TestAssert.That(folder.FileIdentityAt(Path.GetFileName(payload)) == identity && File.ReadAllBytes(payload).SequenceEqual(data) &&
                    f.Native.Store.NativeIndependentBackupVersions(parent, () => true).Single() == saved, "Prepared-source resume changed candidate FID or original content/provenance.");
            }
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history), "Backup resume/HOLD altered original source history.");
        }
    }

    internal static async Task WindowsPreparedBackupWithdrawalAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: DeviceFileManifest.ChunkBytes + 7);
        var selection = Select(f, data); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "backup-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        using var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using var cache = source.Freeze(); var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        var outputPath = Path.Combine(f.Native.Paths.Root, "explicit-output"); Directory.CreateDirectory(outputPath);
        using var output = DeviceFileNativeDirectory.OpenExistingForReceive(outputPath); var parent = NativeMediaBackupParent.Capture(output);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => false, true), "Missing output consent created a catalog.");
        TestAssert.That(!Directory.Exists(Path.Combine(outputPath, "Backup")), "Output opt-out was ignored before catalog creation.");
        var withdrawn = false;
        bool Permit()
        {
            var payload = Directory.Exists(Path.Combine(outputPath, "Backup")) ? Directory.GetFiles(Path.Combine(outputPath, "Backup"), "object-*.raw").SingleOrDefault() : null;
            if (!withdrawn && payload is not null && new FileInfo(payload).Length > 0)
            {
                var consent = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, consent.Version, false, false); withdrawn = true;
            }
            return true; // Local output consent alone cannot renew source READ.
        }
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, Permit, true), "Output WRITE consent renewed withdrawn original source READ.");
        var bytes = Directory.GetFiles(Path.Combine(outputPath, "Backup"), "object-*.raw").Single(); var retained = File.ReadAllBytes(bytes);
        TestAssert.That(withdrawn && retained.Length is > 0 && retained.Length < data.Length, "Actual source withdrawal was not exercised during payload IO.");
        var off = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
        f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, off.Version, true, false);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true), "Later source opt-in revived the old prepared source owner.");
        TestAssert.That(f.Native.Store.NativeIndependentBackupVersions(parent, () => true).Count == 0 && File.ReadAllBytes(bytes).SequenceEqual(retained) &&
            f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history), "Source withdrawal altered history, resumed bytes or falsely completed a backup.");
    }

    internal static async Task WindowsPreparedBackupPendingOfflineAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "backup-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var outputPath = Path.Combine(f.Native.Paths.Root, "explicit-output"); Directory.CreateDirectory(outputPath); NativeMediaBackupParent parent;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(outputPath))
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book))
        using (var cache = source.Freeze())
        {
            parent = NativeMediaBackupParent.Capture(output);
            bool Permit()
            {
                var payload = Directory.Exists(Path.Combine(outputPath, "Backup")) ? Directory.GetFiles(Path.Combine(outputPath, "Backup"), "object-*.raw").SingleOrDefault() : null;
                return payload is null || new FileInfo(payload).Length < data.Length;
            }
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, Permit, true), "Complete bytes were published as a completed backup after withdrawal.");
        }
        f.Native.Connection.Dispose(); File.Move(Path.Combine(selection.NativePath, "new-pc.png"), Path.Combine(selection.NativePath, "retained-source.png"));
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var command = db.CreateCommand(); command.CommandText = "ALTER TABLE native_media_source_chunks RENAME TO retained_pending_source_chunks"; command.ExecuteNonQuery();
        }
        var before = Directory.GetFiles(Path.Combine(outputPath, "Backup")).ToDictionary(path => path, File.ReadAllBytes);
        var selected = f.Native.Store.NativeIndependentBackupVersions(parent, () => true).Single();
        var scope = DeviceFileControl.Digest("magnolie-native-media-backup-root-v1\0", new JsonObject
            { ["volume_path"] = parent.VolumePath, ["identity"] = TelefonStore.NativeMediaReceiveJob.NativeIdentity(parent.Identity) });
        JsonObject? retainedVersion = null;
        foreach (var path in before.Keys.Where(path => path.EndsWith(".seal", StringComparison.Ordinal)))
        {
            var plain = f.Native.Store.Open("native_media_backup_catalog", scope, before[path]);
            try
            {
                var body = JsonNode.Parse(plain)!.AsObject();
                retainedVersion ??= body["pending"]?.AsArray().OfType<JsonObject>().SingleOrDefault(value => value["id"]!.GetValue<string>() == selected.Id)?.DeepClone().AsObject();
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        TestAssert.That(retainedVersion is not null, "Complete interrupted backup lost its distinct retained source provenance.");
        var validate = (Action<JsonObject, JsonObject>)typeof(TelefonStore).GetMethod("ValidatePreparedPcBackup",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!.CreateDelegate(typeof(Action<JsonObject, JsonObject>));
        validate(retainedVersion!, retainedVersion!["provenance"]!.AsObject());
        foreach (Action<JsonObject> mutate in new Action<JsonObject>[]
        {
            value => value["provenance"]!["nonce"] = "bad",
            value => value["provenance"]!["local_origin"]!["relative_path"] = "Album/other.png",
            value => value["provenance"]!["scope"]!["peer_key"] = new string('a', 64),
            value => value["provenance"]!["source_provenance"]!.AsObject().Remove("book_version"),
            value => value["provenance"]!["kind"] = "incoming",
            value => value["provenance"]!["receipt"] = new JsonObject(),
            value => value["provenance"]!["manifest"]!["files"]![0]!["sha256"] = new string('a', 64),
            value => value["name"] = "other.png"
        })
        {
            var changed = retainedVersion.DeepClone().AsObject(); mutate(changed);
            TestAssert.Throws<InvalidDataException>(() => validate(changed, changed["provenance"]!.AsObject()), "Malformed PC backup provenance passed the actual strict decoder.");
        }
        using (var output = parent.OpenNative())
        using (var target = output.CreateStagedFile("restored-pending.png"))
            _ = f.Native.Store.RestoreNativeIndependentBackup(parent, selected, target, () => true);
        TestAssert.That(File.ReadAllBytes(Path.Combine(outputPath, "restored-pending.png")).SequenceEqual(data) &&
            before.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)) && Directory.GetFiles(Path.Combine(outputPath, "Backup")).Length == before.Count,
            "Offline pending recovery rewrote a catalog, needed source/cache or lost original bytes.");
    }

    internal static async Task WindowsPreparedBackupDrainAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: DeviceFileManifest.ChunkBytes + 7);
        var selection = Select(f, data); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "backup-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        using var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using var cache = source.Freeze(); var outputPath = Path.Combine(f.Native.Paths.Root, "explicit-output"); Directory.CreateDirectory(outputPath);
        using var output = DeviceFileNativeDirectory.OpenExistingForReceive(outputPath); var parent = NativeMediaBackupParent.Capture(output);
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim(); using var closing = new ManualResetEventSlim(); var blocked = false;
        bool Permit()
        {
            var payload = Directory.Exists(Path.Combine(outputPath, "Backup")) ? Directory.GetFiles(Path.Combine(outputPath, "Backup"), "object-*.raw").SingleOrDefault() : null;
            if (!blocked && payload is not null && new FileInfo(payload).Length > 0)
            {
                blocked = true; entered.Set();
                if (!release.Wait(TimeSpan.FromSeconds(10))) throw new InvalidDataException("Bounded backup drain fixture release missing.");
            }
            return true;
        }
        var copying = Task.Run(() =>
        {
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SaveNativePreparedPcBackup(cache, output, Permit, true), "Retired prepared owner completed a pending local copy.");
        });
        Task? disposal = null;
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(40)), "Actual payload IO did not reach the bounded drain checkpoint.");
            disposal = Task.Run(() => { closing.Set(); cache.Dispose(); });
            var retired = typeof(TelefonStore.NativePreparedMediaSource).GetField("retired", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!;
            TestAssert.That(closing.Wait(TimeSpan.FromSeconds(2)) && SpinWait.SpinUntil(() => (bool)retired.GetValue(cache)!, TimeSpan.FromSeconds(2)) &&
                !disposal.IsCompleted, "Source disposal released its owner while backup IO was outstanding.");
            TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded, "Outstanding local-copy IO was mistaken for source END.");
        }
        finally
        {
            release.Set(); await copying.WaitAsync(TimeSpan.FromSeconds(15));
            if (disposal is not null) await disposal.WaitAsync(TimeSpan.FromSeconds(15));
        }
        cache.RequireIoEnded();
        TestAssert.That(f.Native.Store.NativeIndependentBackupVersions(parent, () => true).Count == 0 &&
            File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data), "Drain manufactured a complete version or modified source bytes.");
    }

    internal static async Task WindowsIndependentRecoveryChoiceAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "recovery-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var storagePath = Path.Combine(f.Native.Paths.Root, "pc-backups"); Directory.CreateDirectory(storagePath);
        NativeMediaBackupParent storage; NativeMediaBackupVersion saved;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(storagePath))
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book))
        using (var cache = source.Freeze())
        { storage = NativeMediaBackupParent.Capture(output); saved = f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true, true); }
        f.Native.Connection.Dispose();
        File.Move(Path.Combine(selection.NativePath, "new-pc.png"), Path.Combine(selection.NativePath, "retained-source.png"));
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var command = db.CreateCommand(); command.CommandText = "ALTER TABLE native_media_source_chunks RENAME TO retained_recovery_source_chunks"; command.ExecuteNonQuery();
        }
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        TestAssert.Throws<InvalidDataException>(() => coordinator.ReadNativeIndependentPcBackupChoices(storage), "Independent recovery bypassed an unlocked saved book.");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        TestAssert.That(coordinator.ReadNativeIndependentPcBackupChoices(storage).Single() == saved, "Native independent recovery required a peer, source cache or receive destination.");
        var targetPath = Path.Combine(f.Native.Paths.Root, "explicit-local-recovery"); Directory.CreateDirectory(targetPath);
        NativeIndependentPcBackupRestoreChoice choice;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(targetPath))
        {
            TestAssert.Throws<InvalidDataException>(() => coordinator.PrepareNativeIndependentPcBackupRestore(storage, saved.Id, new string('a', 64), output), "Stale backup selection became a native confirmation.");
            choice = coordinator.PrepareNativeIndependentPcBackupRestore(storage, saved.Id, saved.RecordSha256, output);
        }
        using (var readOnly = DeviceFileNativeDirectory.OpenExisting(targetPath))
            TestAssert.Throws<InvalidDataException>(() => coordinator.PrepareNativeIndependentPcBackupRestore(storage, saved.Id, saved.RecordSha256, readOnly), "A read-only native folder granted recovery WRITE.");
        TestAssert.That(Directory.GetFiles(targetPath).Length == 0, "Preparing a recovery choice created output before confirmation.");
        var lane = typeof(TelefonCoordinator).GetField("nativeMediaWorker", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!;
        lane.SetValue(coordinator, 1);
        try { TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreConfirmedNativeIndependentPcBackup(choice), "Independent recovery overlapped the native media worker."); }
        finally { lane.SetValue(coordinator, 0); }
        var result = coordinator.RestoreConfirmedNativeIndependentPcBackup(choice);
        TestAssert.That(result.Operation == choice.Operation && !result.IsRemoteSavedReceipt && File.ReadAllBytes(Path.Combine(targetPath, result.Name)).SequenceEqual(data), "Independent native choice lost bytes or became remote Saved.");
        var files = Directory.GetFiles(targetPath).Order().ToArray();
        TestAssert.That(coordinator.RestoreConfirmedNativeIndependentPcBackup(choice) == result && Directory.GetFiles(targetPath).Order().SequenceEqual(files), "Retrying the same confirmed recovery minted a second file/operation.");
        var retainedPath = targetPath + "-retained"; Directory.Move(targetPath, retainedPath); Directory.CreateDirectory(targetPath);
        TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreConfirmedNativeIndependentPcBackup(choice), "A replacement output root inherited an earlier native recovery confirmation.");
        TestAssert.That(Directory.GetFiles(targetPath).Length == 0 && File.ReadAllBytes(Path.Combine(retainedPath, result.Name)).SequenceEqual(data), "Output-root HOLD wrote a substitute or modified retained recovery bytes.");
        Directory.Move(targetPath, targetPath + "-foreign-preserved"); Directory.Move(retainedPath, targetPath);
        host.FailAfterPrimary = true;
        var originalSaved = host.Saved(); var changedBook = JsonNode.Parse(Book)!.AsObject(); changedBook["changed"] = true;
        using (var message = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = changedBook.ToJsonString() }.ToJsonString()))
            await host.SaveAsync(message.RootElement);
        TestAssert.That(host.Saved() != originalSaved, "Saved-book withdrawal fixture was rejected before the original book witness changed.");
        TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreConfirmedNativeIndependentPcBackup(choice), "A later book save renewed the old independent recovery confirmation.");
        TestAssert.That(Directory.GetFiles(targetPath).Order().SequenceEqual(files), "Revoked book confirmation changed local recovery output.");
    }

    internal static async Task WindowsIndependentRecoveryResumeAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "recovery-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var storagePath = Path.Combine(f.Native.Paths.Root, "pc-backups"); Directory.CreateDirectory(storagePath);
        NativeMediaBackupParent storage; NativeMediaBackupVersion saved;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(storagePath))
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book))
        using (var cache = source.Freeze())
        { storage = NativeMediaBackupParent.Capture(output); saved = f.Native.Store.SaveNativePreparedPcBackup(cache, output, () => true, true); }
        var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var targetPath = Path.Combine(f.Native.Paths.Root, "local-recovery"); Directory.CreateDirectory(targetPath);
        NativeIndependentPcBackupRestoreChoice choice;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(targetPath))
            choice = coordinator.PrepareNativeIndependentPcBackupRestore(storage, saved.Id, saved.RecordSha256, output);
        var collision = Path.Combine(targetPath, "new-pc - restored " + choice.Operation + ".png"); File.WriteAllText(collision, "foreign occupied output survives");
        TestAssert.Throws<IOException>(() => coordinator.RestoreConfirmedNativeIndependentPcBackup(choice), "Recovery overwrote an occupied publication name.");
        var stage = Directory.GetFiles(targetPath, ".magnolie-restore-*.part").Single(); DeviceFileNativeDirectory.Identity identity;
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(targetPath)) identity = output.FileIdentityAt(Path.GetFileName(stage));
        TestAssert.That(File.ReadAllText(collision) == "foreign occupied output survives" && File.ReadAllBytes(stage).SequenceEqual(data), "Collision HOLD modified the foreign file or lost the owned candidate.");
        File.Move(collision, Path.Combine(targetPath, "retained-foreign.txt"));
        var restored = coordinator.RestoreConfirmedNativeIndependentPcBackup(choice);
        using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(targetPath))
            TestAssert.That(output.FileIdentityAt(restored.Name) == identity, "Retry changed the original journaled candidate FID.");
        using (var root = DeviceFileNativeDirectory.OpenExisting(targetPath))
        {
            var record = f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
            var member = root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == restored.Name);
            try
            {
                using var unexpected = f.Native.Connection.OpenNativeCollectionMediaSource("images", record.Id, record.Version, member, new string('f', 64), book);
                throw new InvalidOperationException("A locally restored FID was relabelled as a fresh independent PC source.");
            }
            catch (InvalidDataException error) when (error.Message == "media_collection_existing_recovery_required") { }
        }
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) && File.ReadAllText(Path.Combine(targetPath, "retained-foreign.txt")) == "foreign occupied output survives",
            "Local recovery rewrote original source lineage or foreign data.");
        // Synthetic private-fixture rows exercise the deny-only admission
        // budget before any attempt to decode/adopt an overlarge history.
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var command = db.CreateCommand(); var syntheticScope = new string('f', 64);
            command.CommandText = "WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<8193) " +
                "INSERT INTO native_media_backup_restore_events(scope,operation,sequence,value) SELECT $scope,printf('%032x',i),1,X'00' FROM n";
            command.Parameters.AddWithValue("$scope", syntheticScope); command.ExecuteNonQuery();
            try
            {
                try
                {
                    using var unexpected = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
                    throw new InvalidOperationException("An over-budget recovery history admitted a new source read.");
                }
                catch (InvalidDataException error) when (error.Message == "media_collection_recovery_history_held") { }
            }
            finally
            {
                command.CommandText = "DELETE FROM native_media_backup_restore_events WHERE scope=$scope AND value=X'00'"; command.ExecuteNonQuery();
            }
        }
    }

    internal static async Task WindowsPathHistoryAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        foreach (var folder in new[] { "Album A", "Album B" })
        {
            var path = Path.Combine(selection.NativePath, folder); Directory.CreateDirectory(path);
            File.WriteAllBytes(Path.Combine(path, "same.png"), data);
        }
        DeviceFileNativeDirectory.CollectionMember Pick(string folder)
        {
            using var root = selection.OpenNative();
            return root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "same.png" && item.Parents.Single().Name == folder);
        }
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); var first = Pick("Album A"); var second = Pick("Album B");
        TestAssert.That(first.Identity != second.Identity, "Distinct native subfolder fixture shared a file identity.");
        string firstJob;
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, first, new string('f', 64), book))
        using (var cache = source.Freeze())
        {
            firstJob = cache.JobId;
            TestAssert.That(Record(f, cache.JobId)["local_origin"]!["relative_path"]!.GetValue<string>() == "Album A/same.png",
                "Protected origin did not retain the full actual native relative path.");
        }
        using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, second, new string('f', 64), book))
        using (var cache = source.Freeze())
            TestAssert.That(Record(f, cache.JobId)["local_origin"]!["relative_path"]!.GetValue<string>() == "Album B/same.png",
                "Distinct subfolders with identical leaf names were collapsed by basename.");
        var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        TestAssert.That(before.Length == 2, "Distinct native paths did not retain both independent source records.");
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; query.Parameters.AddWithValue("$job", firstJob);
        var originalCipher = (byte[])query.ExecuteScalar()!; var legacy = Record(f, firstJob);
        legacy["local_origin"]!["format"] = 1; legacy["local_origin"]!.AsObject().Remove("relative_path");
        var clear = TelefonCrypto.Canonical(legacy); byte[] cipher;
        try { cipher = f.Native.Store.Seal("native_media_source_job", f.Native.Peer.Id + "/" + firstJob, clear); }
        finally { CryptographicOperations.ZeroMemory(clear); }
        using var write = db.CreateCommand(); write.CommandText = "UPDATE native_media_source_jobs SET value=$value WHERE job_id=$job";
        write.Parameters.AddWithValue("$job", firstJob); var value = write.Parameters.Add("$value", Microsoft.Data.Sqlite.SqliteType.Blob);
        value.Value = cipher; write.ExecuteNonQuery();
        try
        {
            var historical = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
            TestAssert.That(historical.Length == 2 && Record(f, firstJob)["local_origin"]!["format"]!.GetValue<int>() == 1,
                "Legacy origin without path was discarded, upgraded or made unreadable.");
            using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, first, new string('f', 64), book))
                TestAssert.Throws<InvalidDataException>(() => source.FreezeCompletedSuccessor(), "Legacy full-path association was inferred from today's file tree.");
            DeviceFileNativeDirectory.CollectionMember unknown;
            using (var root = selection.OpenNative()) unknown = root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "new-pc.png");
            using (var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, unknown, new string('f', 64), book))
                TestAssert.Throws<InvalidDataException>(() => source.Freeze(), "Unknown path was adopted beside legacy origins with unavailable path witnesses.");
            TestAssert.That(((byte[])query.ExecuteScalar()!).SequenceEqual(cipher) && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(historical),
                "Legacy path HOLD altered original ciphertext or retained history.");
        }
        finally { value.Value = originalCipher; write.ExecuteNonQuery(); }
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(before), "Exact legacy fixture restoration changed either retained source history.");
    }

    internal static async Task WindowsOwnerGuardsAsync()
    {
        foreach (var fault in new[] { "consent", "book", "intent" })
        {
            using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
            using var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
            using var cache = source.Freeze(); var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
            var frames = f.Native.Stream.ToArray();
            if (fault == "consent")
            {
                var before = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                var off = f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, before.Version, false, false);
                f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, off.Version, true, false);
            }
            if (fault == "book")
            {
                var changed = JsonNode.Parse(Book)!.AsObject(); changed["notizen"] = new JsonArray(new JsonObject { ["id"] = "new", ["titel"] = "Changed" });
                using var message = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = changed.ToJsonString() }.ToJsonString());
                await host.SaveAsync(message.RootElement);
                TestAssert.That(host.Responses.Last().Value["ok"]!.GetValue<bool>(), "Actual changed-book fixture save was not accepted.");
            }
            if (fault == "intent")
            {
                var version = f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode");
                f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("phone_inventory")!, version);
                await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            }
            TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Independent PC cache ignored original owner withdrawal: " + fault);
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Independent PC source retained rights after withdrawal: " + fault);
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == history &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
                File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data) &&
                (fault == "intent" || f.Native.Stream.ToArray().SequenceEqual(frames)) &&
                DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]?.GetValue<string>() is not (MediaOfferEnvelope.Kind or DeviceFileChunkEnvelope.ResultKind or DeviceFileSources.RequestKind)),
                "Owner rejection changed original bytes/cache/history or sent unauthorized data: " + fault);
        }
    }

    internal static async Task WindowsMixedHistoryAndSchemaAsync()
    {
        var data = DeviceFileSourceSendTests.PaddedPng(length: 256);
        using var f = await DeviceFileSourceCacheTests.Fixture(data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); JsonObject reference;
        using (var mapped = DeviceFileSourceCacheTests.Open(f, book))
        using (var cache = mapped.Freeze())
        {
            reference = mapped.OriginalReference;
            TestAssert.That(Record(f, cache.JobId)["format"]!.GetValue<int>() == 1, "Existing mapped preparation was rewritten to a local-origin schema.");
        }
        var field = f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode");
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("entire_collection")!, field);
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        var selection = Select(f, data);
        using var local = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using var prepared = local.Freeze(); var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        TestAssert.That(before.Length == 2 && f.Native.Store.HasNativeMediaSourceReference(f.Native.Peer.Id, reference),
            "Mixed local/mapped histories lost old records or misclassified an independent PC origin as a phone reference.");
        using (var root = DeviceFileNativeDirectory.OpenExisting(f.Root))
        {
            var mappedRoot = f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
            var mappedMember = root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "first.jpg");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Connection.OpenNativeCollectionMediaSource("images", mappedRoot.Id, mappedRoot.Version,
                mappedMember, new string('f', 64), book), "An existing native phone mapping was relabelled as an independent PC origin.");
        }
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; query.Parameters.AddWithValue("$job", prepared.JobId);
        var originalCipher = (byte[])query.ExecuteScalar()!; var original = Record(f, prepared.JobId);
        void Replace(JsonObject body)
        {
            var bytes = TelefonCrypto.Canonical(body); byte[] cipher;
            try { cipher = f.Native.Store.Seal("native_media_source_job", f.Native.Peer.Id + "/" + prepared.JobId, bytes); }
            finally { CryptographicOperations.ZeroMemory(bytes); }
            using var update = db.CreateCommand(); update.CommandText = "UPDATE native_media_source_jobs SET value=$value WHERE job_id=$job";
            update.Parameters.AddWithValue("$value", cipher); update.Parameters.AddWithValue("$job", prepared.JobId); update.ExecuteNonQuery();
        }
        foreach (var mutate in new Action<JsonObject>[] {
            body => body["format"] = 1,
            body => body["local_origin"]!.AsObject().Remove("file_creation_filetime"),
            body => body["local_origin"]!["file_creation_filetime"] = "0000000000000000",
            body => body["local_origin"]!["root_id"] = new string('f', 32),
            body => body["local_origin"]!["format"] = 1,
            body => body["local_origin"]!.AsObject().Remove("relative_path"),
            body => body["local_origin"]!["relative_path"] = "../same.png",
            body => body["local_origin"]!["relative_path"] = "/same.png",
            body => body["local_origin"]!["relative_path"] = "Album\\same.png",
            body => body["local_origin"]!["relative_path"] = "Album/other-name.png",
            body => body["local_origin"]!["root_identity"] = new JsonObject(),
            body => body["local_origin"]!["file_identity"] = "not a native identity",
            body => body["originals"] = new JsonObject { ["fake"] = reference.DeepClone() } })
        {
            var changed = original.DeepClone().AsObject(); mutate(changed); Replace(changed);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id), "Malformed authenticated local-origin source record was adopted or relaxed into the legacy schema.");
        }
        using (var restore = db.CreateCommand())
        {
            restore.CommandText = "UPDATE native_media_source_jobs SET value=$value WHERE job_id=$job";
            restore.Parameters.AddWithValue("$value", originalCipher); restore.Parameters.AddWithValue("$job", prepared.JobId); restore.ExecuteNonQuery();
        }
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(before) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 1, "Schema rejection discarded/restored source or receive history.");
    }
}
