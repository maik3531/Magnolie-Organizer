using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private sealed record NativeSourceChoice(NativeFileControlSession Owner, string MediaType,
        NativeMediaPreferences Preferences, NativeMediaDestination? Destination, bool Positive, bool DataReady, DeviceTransferBinding? DataBinding,
        JsonObject? SharedIntent, string ReceiveConsentVersion);
    private sealed record NativeVideoSourceActivation(NativeSourceChoice Choice, string SourceVersion, string RemoteEpoch);
    private NativeVideoSourceActivation? nativeVideoSourceActivation;
    private object? nativeVideoConfigurationAttempt;
    private sealed class NativeSourceCommandPending(NativeSourceChoice choice, NativeReceiverCommandTicket ticket,
        JsonObject message, (string SessionEpoch, long Sequence) witness, string resultKind, Func<JsonObject, object> parse,
        Action require, Action<NativeReceiverCommandTicket, object>? accept)
    {
        internal readonly NativeSourceChoice Choice = choice;
        internal readonly NativeReceiverCommandTicket Ticket = ticket;
        internal readonly JsonObject Message = message;
        internal readonly (string SessionEpoch, long Sequence) Witness = witness;
        internal readonly string ResultKind = resultKind;
        internal readonly Func<JsonObject, object> Parse = parse;
        internal readonly Action RequireChoice = require;
        internal readonly Action<NativeReceiverCommandTicket, object>? Accept = accept;
        internal readonly TaskCompletionSource<object> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool OutputConfirmed;
        internal readonly long Issued = Environment.TickCount64;
        internal JsonObject? SourceOffer;
        internal DeviceFileManifest? SourceOfferManifest;
    }
    private NativeSourceCommandPending? nativeSourceCommand;
    private NativeSourceCommandPending? nativeRetiredAlbumStatus;
    private sealed class NativeKnownCatalog(NativeFileControlSession owner, string version, string catalogId)
    {
        internal readonly NativeFileControlSession Owner = owner;
        internal readonly string Version = version, CatalogId = catalogId;
        internal int? NextCursor = 0;
        internal readonly Dictionary<string, DeviceFileAlbumMetadata> Albums = new(StringComparer.Ordinal);
    }
    private readonly Dictionary<string, NativeKnownCatalog> nativeKnownCatalogs = new(StringComparer.Ordinal);

    private DeviceFileAlbumMetadata? KnownNativeAlbum(NativeFileControlSession owner, string mediaType, string version, string catalogId, string albumId)
    {
        lock (fileRouteGate) return nativeKnownCatalogs.TryGetValue(mediaType, out var catalog) && ReferenceEquals(catalog.Owner, owner) &&
            catalog.Version == version && catalog.CatalogId == catalogId && catalog.Albums.TryGetValue(albumId, out var album) ? album : null;
    }

    private NativeSourceChoice CaptureNativeSourceChoice(string mediaType, bool positive, bool dataReady)
    {
        if (mediaType is not ("images" or "video")) throw DeviceFileControl.Error("file_sources_native_media_invalid");
        var owner = RequireNativeFileControls(); var destination = store.ReadNativeMediaDestination(peer.Id, mediaType);
        var choice = new NativeSourceChoice(owner, mediaType, store.ReadNativeMediaPreferences(peer.Id), destination, positive, dataReady,
            dataReady && destination is not null ? owner.Binding(destination.DestinationToken) : null,
            store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey), store.ReadNativeMediaReceiveConsent(peer.Id).Version);
        RequireNativeSourceChoice(choice); return choice;
    }

    private void RequireNativeSourceChoice(NativeSourceChoice choice)
    {
        RequireNativeFileControls(choice.Owner);
        try { store.RequireNativeMediaStorageKey(); }
        catch { CloseNativeSourceCommands("file_sources_native_storage_key_changed"); throw; }
        if (choice.MediaType == "video" && !FileMetadataReady(videos: true)) throw DeviceFileControl.Error("file_sources_native_video_metadata_changed");
        if (store.ReadNativeMediaPreferences(peer.Id) != choice.Preferences || store.ReadNativeMediaDestination(peer.Id, choice.MediaType) != choice.Destination)
            throw DeviceFileControl.Error("file_sources_native_choice_changed");
        if (choice.Positive)
        {
            var receiving = store.ReadNativeMediaReceiveConsent(peer.Id);
            if (!receiving.Granted || receiving.Version != choice.ReceiveConsentVersion)
                throw DeviceFileControl.Error("file_sources_local_receive_consent_changed");
            var intent = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
            if (intent is not null || choice.SharedIntent is not null || MediaSharedControlsReady)
            {
                if (intent is null || !JsonNode.DeepEquals(intent, choice.SharedIntent) || !MediaSharedSettingsReady ||
                    !MediaSyncSettings.RequestedFor(intent, choice.MediaType))
                    throw DeviceFileControl.Error("file_sources_shared_media_intent_changed");
            }
            if (!(choice.MediaType == "video" ? choice.Preferences.VideosEnabled : choice.Preferences.PhotosEnabled) || choice.Destination is null)
                throw DeviceFileControl.Error("file_sources_native_positive_choice_required");
            using var root = choice.Destination.OpenNative(); _ = root.CurrentIdentity();
        }
        if (choice.DataReady && (choice.Destination is null || choice.DataBinding is null || choice.Owner.Binding(choice.Destination.DestinationToken) != choice.DataBinding))
            throw DeviceFileControl.Error("file_sources_native_data_echo_required");
    }

    internal async Task<DeviceFileSourceStatus> ConfigureNativeMediaSourceAsync(string expectedVersion, string mediaType,
        bool enabled, CancellationToken token = default)
    {
        object? attempt = null;
        if (mediaType == "video") lock (fileRouteGate)
        { attempt = new object(); nativeVideoConfigurationAttempt = attempt; nativeVideoSourceActivation = null; }
        var choice = CaptureNativeSourceChoice(mediaType, enabled, mediaType == "video" && enabled);
        void Require()
        {
            RequireNativeSourceChoice(choice);
            if (mediaType == "video") lock (fileRouteGate)
                if (!ReferenceEquals(nativeVideoConfigurationAttempt, attempt)) throw DeviceFileControl.Error("file_sources_native_video_configuration_superseded");
        }
        var expectVideos = FileMetadataReady(videos: true);
        var operation = mediaType == "video" ? "configure_videos" : "configure";
        var message = DeviceFileSources.CreateRequest(operation, Now(), expectedVersion, enabled,
            mediaType == "images" ? new[] { "camera", "downloads", "screenshots", "whatsapp_received" } : null);
        var result = await ExchangeNativeSourceCommandAsync<DeviceFileSourceStatus>(choice, message, DeviceFileSources.ResultKind, raw =>
        {
            var status = DeviceFileSources.ParseResult(raw, message["message_id"]!.GetValue<string>(), operation, Now(), expectVideos);
            if (status.RepairPending || (mediaType == "video" ? status.Videos?.Enabled : status.Enabled) != enabled || enabled && !status.Associated)
                throw DeviceFileControl.Error("file_sources_native_configuration_unconfirmed");
            if (mediaType == "images" && enabled && !status.Kinds.SequenceEqual(new[] { "camera", "downloads", "screenshots", "whatsapp_received" }))
                throw DeviceFileControl.Error("file_sources_native_configuration_unconfirmed");
            return status;
        }, Require, token);
        Require();
        if (mediaType == "video" && enabled)
        {
            var witness = choice.Owner.RemoteControlWitness() ?? throw DeviceFileControl.Error("file_sources_native_control_changed");
            lock (fileRouteGate)
            {
                if (!ReferenceEquals(nativeVideoConfigurationAttempt, attempt)) throw DeviceFileControl.Error("file_sources_native_video_configuration_superseded");
                nativeVideoSourceActivation = new(choice, result.Version, witness.SessionEpoch);
            }
        }
        return result;
    }

    private Action NativeSourceReadGuard(NativeSourceChoice choice, string sourceVersion)
    {
        NativeVideoSourceActivation? activation;
        lock (fileRouteGate) activation = nativeVideoSourceActivation;
        void Require()
        {
            RequireNativeSourceChoice(choice);
            if (choice.MediaType != "video") return;
            var witness = choice.Owner.RemoteControlWitness();
            lock (fileRouteGate)
                if (activation is null || !ReferenceEquals(nativeVideoSourceActivation, activation) ||
                    !ReferenceEquals(activation.Choice.Owner, choice.Owner) || activation.Choice.Preferences != choice.Preferences ||
                    activation.Choice.Destination != choice.Destination || activation.SourceVersion != sourceVersion ||
                    activation.Choice.ReceiveConsentVersion != choice.ReceiveConsentVersion ||
                    !JsonNode.DeepEquals(activation.Choice.SharedIntent, choice.SharedIntent) ||
                    activation.Choice.DataBinding != choice.DataBinding ||
                    witness is null || witness.Value.SessionEpoch != activation.RemoteEpoch)
                    throw DeviceFileControl.Error("file_sources_native_fresh_video_configuration_required");
        }
        Require(); return Require;
    }

    internal Func<DeviceTransferBinding?> CaptureNativeMediaReceiveBinding(string sourceVersion, string mediaType = "images")
    {
        var choice = CaptureNativeSourceChoice(mediaType, true, true); var require = NativeSourceReadGuard(choice, sourceVersion);
        var original = choice.Owner.Binding(choice.Destination!.DestinationToken) ?? throw DeviceFileControl.Error("file_sources_native_data_echo_required");
        var bindingGate = new object(); var revoked = false;
        return () =>
        {
            lock (bindingGate)
            {
                if (revoked) return null;
                try
                {
                    require(); var current = choice.Owner.Binding(choice.Destination.DestinationToken);
                    if (current == original) return current;
                }
                catch { revoked = true; throw; }
                revoked = true; return null;
            }
        };
    }

    internal async Task<DeviceFileCatalogPage> DiscoverNativeMediaAlbumsAsync(string expectedVersion, string mediaType = "images",
        string? catalogId = null, int after = 0, CancellationToken token = default)
    {
        var choice = CaptureNativeSourceChoice(mediaType, true, true); var current = NativeSourceReadGuard(choice, expectedVersion);
        var operation = catalogId is null ? "discover" : "catalog_page";
        if (catalogId is null && after != 0) throw DeviceFileControl.Error("file_sources_native_catalog_invalid");
        var message = DeviceFileSources.CreateRequest(operation, Now(), expectedVersion, catalogId: catalogId,
            after: catalogId is null ? null : after, mediaType: mediaType);
        return await ExchangeNativeSourceCommandAsync<DeviceFileCatalogPage>(choice, message, DeviceFileSources.CatalogKind,
            raw => DeviceFileSources.ParseCatalog(raw, message["message_id"]!.GetValue<string>(), operation, expectedVersion, Now(), catalogId, after, mediaType), current, token,
            accept: (_, value) =>
            {
                var page = (DeviceFileCatalogPage)value;
                lock (fileRouteGate)
                {
                    if (operation == "discover") nativeKnownCatalogs[mediaType] = new(choice.Owner, expectedVersion, page.CatalogId);
                    if (!nativeKnownCatalogs.TryGetValue(mediaType, out var known) || !ReferenceEquals(known.Owner, choice.Owner) ||
                        known.Version != expectedVersion || known.CatalogId != page.CatalogId || known.NextCursor != page.After ||
                        page.Albums.Any(album => known.Albums.ContainsKey(album.AlbumId)))
                        throw DeviceFileControl.Error("file_sources_native_catalog_changed");
                    foreach (var album in page.Albums) known.Albums.Add(album.AlbumId, album);
                    known.NextCursor = page.NextCursor;
                }
            });
    }

    internal async Task<DeviceFilePermissionResult> RequestNativeMediaReadAsync(string expectedVersion, string mediaType = "images", CancellationToken token = default)
    {
        var choice = CaptureNativeSourceChoice(mediaType, true, true); var current = NativeSourceReadGuard(choice, expectedVersion);
        var message = DeviceFileSources.CreateRequest("request_read", Now(), expectedVersion, mediaType: mediaType);
        return await ExchangeNativeSourceCommandAsync<DeviceFilePermissionResult>(choice, message, DeviceFileSources.PermissionResultKind,
            raw => DeviceFileSources.ParsePermissionResult(raw, message["message_id"]!.GetValue<string>(), expectedVersion, Now(), mediaType), current, token);
    }

    private async Task<T> ExchangeNativeSourceCommandAsync<T>(NativeSourceChoice choice, JsonObject message, string resultKind,
        Func<JsonObject, object> parse, Action require, CancellationToken callerCancellation,
        NativeFileControlSession.SourceRunLease? cleanup = null, Action<NativeReceiverCommandTicket, object>? accept = null)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, callerCancellation);
        lifetime.CancelAfter(TimeSpan.FromMilliseconds(DeviceFileControl.MaximumTtlMs)); lifetime.Token.ThrowIfCancellationRequested();
        require(); var ticket = cleanup is null ? choice.Owner.ReceiverCommandTicket() : choice.Owner.CleanupCommandTicket(cleanup);
        NativeSourceCommandPending? pending = null;
        try
        {
            pending = new(choice, ticket, message, choice.Owner.ReceiverCommandWitness(ticket), resultKind, parse, require, accept);
            lock (fileRouteGate)
            {
                if (fileRouteFaulted || !ReferenceEquals(fileControls, choice.Owner) || nativeSourceCommand is not null || nativeSourceStatus is not null)
                    throw DeviceFileControl.Error("file_sources_native_command_busy");
                nativeSourceCommand = pending;
            }
            await fileControlIo.WaitAsync(lifetime.Token);
            try { await SendNativeSourceCommandAsync(pending, lifetime.Token); }
            finally { fileControlIo.Release(); }
            return (T)await pending.Completion.Task.WaitAsync(lifetime.Token);
        }
        catch (OperationCanceledException error) when (!cancellation.IsCancellationRequested && !callerCancellation.IsCancellationRequested)
        { throw new TimeoutException("file_sources_native_command_timeout", error); }
        finally
        {
            lock (fileRouteGate)
            {
                var run = nativeMediaSourceRun;
                if (pending is not null && !pending.Completion.Task.IsCompletedSuccessfully && run?.AlbumOperation is not null &&
                    (pending.Message["body"]?["operation"]?.GetValue<string>() is "run_status" or "resume_status") &&
                    pending.Message["body"]?["run_id"]?.GetValue<string>() == run.Lease.RunId)
                    nativeRetiredAlbumStatus = pending;
                if (ReferenceEquals(nativeSourceCommand, pending)) nativeSourceCommand = null;
            }
            if (pending is not null)
            {
                pending.Completion.TrySetCanceled();
                if (pending.Completion.Task.IsFaulted) _ = pending.Completion.Task.Exception;
            }
            choice.Owner.FinishReceiverCommand(ticket);
        }
    }

    private void RequireNativeSourceCommand(NativeSourceCommandPending pending)
    {
        pending.RequireChoice(); RequireNativeFileControls(pending.Choice.Owner);
        lock (fileRouteGate) if (!ReferenceEquals(nativeSourceCommand, pending)) throw DeviceFileControl.Error("file_sources_native_command_changed");
        if (!pending.Choice.Owner.ReceiverCommandCurrent(pending.Ticket)) throw DeviceFileControl.Error("file_sources_native_command_expired");
        var witness = pending.Choice.Owner.RemoteControlWitness();
        if (witness is null || witness.Value.SessionEpoch != pending.Witness.SessionEpoch || witness.Value.Sequence < pending.Witness.Sequence)
            throw DeviceFileControl.Error("file_sources_native_control_changed");
        _ = DeviceFileSources.ParseRequest(pending.Message, Now());
    }

    private async Task SendNativeSourceCommandAsync(NativeSourceCommandPending pending, CancellationToken token)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token); var started = false;
        try
        {
            RequireNativeSourceCommand(pending); var envelope = Seal(pending.Message); started = true;
            await TelefonCoordinator.WriteFrameAsync(stream, envelope, deadline.Token); lastSentMs = Now();
            RequireNativeSourceCommand(pending);
            lock (fileRouteGate)
            {
                if (!ReferenceEquals(nativeSourceCommand, pending)) throw DeviceFileControl.Error("file_sources_native_command_changed");
                pending.OutputConfirmed = true;
            }
        }
        catch { CloseNativeFileRoute(); if (started) stream.Dispose(); throw; }
        finally { writer.Release(); }
    }

    private async Task ReceiveNativeSourceCommandAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        try
        {
            NativeSourceCommandPending? retired;
            lock (fileRouteGate) retired = nativeRetiredAlbumStatus;
            if (retired is not null && message["kind"]?.GetValue<string>() == DeviceFileSources.RunResultKind &&
                message["body"]?["request_id"]?.GetValue<string>() == retired.Message["message_id"]!.GetValue<string>())
            {
                RequireNativeFileControls(retired.Choice.Owner);
                var witness = retired.Choice.Owner.RemoteControlWitness(); var tick = Environment.TickCount64;
                if (witness?.SessionEpoch != retired.Witness.SessionEpoch || tick < retired.Issued || tick - retired.Issued >= DeviceFileControl.MaximumTtlMs ||
                    Now() >= TelefonProtocolContract.Integer(retired.Message["expires_ms"]) || TelefonProtocolContract.Integer(message["expires_ms"]) > TelefonProtocolContract.Integer(retired.Message["expires_ms"]))
                    throw DeviceFileControl.Error("file_sources_native_retired_status_changed");
                _ = retired.Parse(message); // Pure exact correlation; no Accept callback, state update, lease or READ.
                lock (fileRouteGate) if (ReferenceEquals(nativeRetiredAlbumStatus, retired)) nativeRetiredAlbumStatus = null;
                return;
            }
            NativeSourceCommandPending pending;
            lock (fileRouteGate)
            {
                pending = nativeSourceCommand ?? throw DeviceFileControl.Error("file_sources_native_unsolicited_result");
                if (!pending.OutputConfirmed || message["kind"]?.GetValue<string>() != pending.ResultKind)
                    throw DeviceFileControl.Error("file_sources_native_unconfirmed_or_wrong_result");
            }
            RequireNativeSourceCommand(pending); var result = pending.Parse(message); RequireNativeSourceCommand(pending);
            if (pending.SourceOffer is not null)
            {
                if (result is not DeviceFileRunResult run || run.OfferId != pending.SourceOffer["message_id"]!.GetValue<string>() ||
                    run.ManifestSha256 != pending.SourceOfferManifest?.Fingerprint || Now() >= TelefonProtocolContract.Integer(pending.SourceOffer["expires_ms"]))
                    throw DeviceFileControl.Error("file_sources_native_offer_correlation_changed");
            }
            pending.Accept?.Invoke(pending.Ticket, result);
            if (!pending.Completion.TrySetResult(result)) throw DeviceFileControl.Error("file_sources_native_duplicate_result");
        }
        catch { CloseNativeFileRoute(); throw; }
        finally { fileControlIo.Release(); }
    }

    // Android sends the sealed offer BEFORE the correlated offer_run result.
    // Retain one bounded envelope only; this is not native acceptance/staging.
    private async Task ReceiveNativeSourceOfferAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        try
        {
            NativeSourceCommandPending pending;
            lock (fileRouteGate)
            {
                pending = nativeSourceCommand ?? throw DeviceFileControl.Error("file_sources_native_unsolicited_offer");
                if (!pending.OutputConfirmed || pending.ResultKind != DeviceFileSources.RunResultKind || pending.SourceOffer is not null)
                    throw DeviceFileControl.Error("file_sources_native_offer_not_requested");
            }
            RequireNativeSourceCommand(pending);
            var request = DeviceFileSources.ParseRequest(pending.Message, Now());
            if (request.Operation is not ("offer_run" or "offer_resume")) throw DeviceFileControl.Error("file_sources_native_offer_not_requested");
            var binding = pending.Choice.DataBinding ?? throw DeviceFileControl.Error("file_sources_native_data_echo_required");
            var manifest = DeviceFileOfferEnvelope.Validate(message, binding.SenderId, binding.ReceiverId, Now());
            if (Now() >= TelefonProtocolContract.Integer(message["expires_ms"]) ||
                TelefonProtocolContract.Integer(message["expires_ms"]) > TelefonProtocolContract.Integer(pending.Message["expires_ms"]))
                throw DeviceFileControl.Error("file_sources_native_offer_expired");
            RequireNativeSourceCommand(pending);
            lock (fileRouteGate)
            {
                if (!ReferenceEquals(nativeSourceCommand, pending)) throw DeviceFileControl.Error("file_sources_native_command_changed");
                pending.SourceOffer = message.DeepClone().AsObject(); pending.SourceOfferManifest = manifest;
            }
        }
        catch { CloseNativeFileRoute(); throw; }
        finally { fileControlIo.Release(); }
    }

    private (DeviceFileManifest Manifest, long Expires)? NativeSourceOfferedManifest(NativeReceiverCommandTicket ticket)
    {
        lock (fileRouteGate)
        {
            if (nativeSourceCommand is null || !ReferenceEquals(nativeSourceCommand.Ticket, ticket))
                throw DeviceFileControl.Error("file_sources_native_command_changed");
            return nativeSourceCommand.SourceOfferManifest is DeviceFileManifest manifest && nativeSourceCommand.SourceOffer is JsonObject message
                ? (manifest, TelefonProtocolContract.Integer(message["expires_ms"])) : null;
        }
    }

    private void CheckNativeSourceCommandControl(NativeFileControlSession owner)
    {
        NativeSourceCommandPending? pending;
        lock (fileRouteGate) pending = nativeSourceCommand;
        if (pending is not null && ReferenceEquals(pending.Choice.Owner, owner) && !owner.ReceiverCommandCurrent(pending.Ticket))
            CloseNativeSourceCommands("file_sources_native_control_changed", pending);
    }

    private void CloseNativeSourceCommands(string reason = "file_sources_native_owner_closed", NativeSourceCommandPending? expected = null)
    {
        NativeSourceCommandPending? pending;
        lock (fileRouteGate)
        {
            if (expected is not null && !ReferenceEquals(nativeSourceCommand, expected)) return;
            pending = nativeSourceCommand; nativeSourceCommand = null; nativeVideoSourceActivation = null; nativeVideoConfigurationAttempt = null;
            nativeKnownCatalogs.Clear();
            nativeRetiredAlbumStatus = null;
        }
        pending?.Completion.TrySetException(DeviceFileControl.Error(reason));
    }
}
