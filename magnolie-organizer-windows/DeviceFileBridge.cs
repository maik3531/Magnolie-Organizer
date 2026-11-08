using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly ConcurrentDictionary<string, CancellationTokenSource> nativeMediaUiRuns = new(StringComparer.Ordinal);

    partial void HandleNativeMediaUi(JsonElement message, ref Task? handling)
        => handling = HandleNativeMediaUiAsync(message);

    private async Task HandleNativeMediaUiAsync(JsonElement message)
    {
        var requestId = Text(message, "requestId"); var peerId = Text(message, "device_id");
        Task Reply(object result) => form.SendAsync("MagnolieMedia.receive", result);
        try
        {
            var request = NativeMediaUiRequest.Parse(JsonNode.Parse(message.GetRawText())!.AsObject());
            switch (request.Action)
            {
                case "shared_setting":
                    var shared = await telefon.ChangeNativeMediaUiSharedSettingAsync(peerId, request.SharedField!, request.SharedValue!, request.Version!);
                    shared["requestId"] = requestId; shared["device_id"] = peerId; shared["ok"] = true;
                    await Reply(shared); return;
                case "receive_consent":
                    var receiving = telefon.ChangeNativeMediaUiReceiveConsent(peerId, request.Version!, request.ReceiveConsent);
                    receiving["requestId"] = requestId; receiving["device_id"] = peerId; receiving["ok"] = true;
                    await Reply(receiving); return;
                case "activate":
                    if (MessageBox.Show(form, T("Photos and videos") + " — " + T("Enable") + "?", T("Photos and videos"),
                        MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                    { await Reply(new { requestId, device_id = peerId, ok = true, canceled = true }); return; }
                    telefon.ActivateLegacyNativeMediaUi(peerId);
                    await Reply(new { requestId, device_id = peerId, ok = true, supported = true, activation_required = true }); return;
                case "backup_list":
                    var backupPage = telefon.ReadNativeMediaBackupUiPage(peerId, request.MediaType, request.BackupLocation);
                    var backups = backupPage.Versions;
                    if (request.After > backups.Count) throw DeviceFileControl.Error("media_backup_stale_selection");
                    await Reply(new { requestId, device_id = peerId, ok = true, media_type = request.MediaType,
                        location_id = backupPage.Source?.Id,
                        backup_location = backupPage.Locations is { } locations ? new { version = locations.Version,
                            display_path = Path.Combine(locations.Current.NativePath, "Backup"), is_default = locations.SelectedId is null,
                            sources = locations.Parents.Select(value => new { location_id = value.Id, display_path = Path.Combine(value.NativePath, "Backup") }) } : null,
                        next_cursor = request.After + 128 < backups.Count ? (int?)(request.After + 128) : null,
                        backups = backups.Skip(request.After).Take(128).Select(item => new { backup_id = item.Id, version = item.RecordSha256, display_name = item.Name, saved_ms = item.SavedMs }) });
                    return;
                case "pick_backup_parent":
                    var backupBook = NativeActorSavedBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
                    var backupLocations = telefon.NativeMediaBackupUiLocations(peerId, request.MediaType);
                    if (backupLocations.Version != request.Version) throw DeviceFileControl.Error("media_backup_locations_stale_choice");
                    using (var dialog = new FolderBrowserDialog { Description = T("Backups") + " · " + T("Choose folder …"),
                        UseDescriptionForTitle = true, ShowNewFolderButton = true, SelectedPath = backupLocations.Current.NativePath })
                    {
                        if (dialog.ShowDialog(form) != DialogResult.OK)
                        { await Reply(new { requestId, device_id = peerId, ok = true, canceled = true }); return; }
                        if (NativeActorSavedBook() != backupBook) throw DeviceFileControl.Error("file_media_current_saved_book_required");
                        using var backupParentOwner = DeviceFileNativeDirectory.OpenExistingForReceive(dialog.SelectedPath);
                        telefon.SetNativeMediaBackupUiParent(peerId, request.MediaType, request.Version, backupParentOwner);
                    }
                    await Reply(new { requestId, device_id = peerId, ok = true }); return;
                case "backup_default":
                    telefon.SetNativeMediaBackupUiParent(peerId, request.MediaType, request.Version, null);
                    await Reply(new { requestId, device_id = peerId, ok = true }); return;
                case "backup_restore":
                    var backupChoice = telefon.PrepareNativeMediaBackupRestore(peerId, request.MediaType, request.BackupId!, request.Version!, request.BackupLocation);
                    if (MessageBox.Show(form, T("Restore") + ":\n\n" + backupChoice.Selected.Name, T("Restore backup …"),
                        MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                    { await Reply(new { requestId, device_id = peerId, ok = true, canceled = true }); return; }
                    var recovered = await Task.Run(() => telefon.RestoreConfirmedNativeMediaBackup(backupChoice));
                    await Reply(new { requestId, device_id = peerId, ok = true, state = recovered.State, display_name = recovered.Name }); return;
                case "trash_list":
                    var items = telefon.ReadNativeMediaTrashUi(peerId).Where(item => item.Entry.State is not ("purged" or "restored")).ToArray();
                    if (request.After > items.Length) throw DeviceFileControl.Error("media_trash_stale_selection");
                    await Reply(new { requestId, device_id = peerId, ok = true, after = request.After,
                        next_cursor = request.After + 128 < items.Length ? (int?)(request.After + 128) : null,
                        trash = items.Skip(request.After).Take(128).Select(item => new { operation_id = item.Entry.Operation, version = item.Entry.Version,
                            state = item.Entry.State, changed_ms = item.Entry.ChangedMs, display_name = item.DisplayName, media_type = item.MediaType }) });
                    return;
                case "trash_restore":
                    var restored = telefon.RestoreNativeMediaTrashUi(peerId, request.TrashOperation!, request.Version!);
                    await Reply(new { requestId, device_id = peerId, ok = true, state = restored.State }); return;
                case "trash_purge":
                    var removal = telefon.PrepareNativeMediaRemovalChoice(peerId, request.TrashOperation!, request.Version!);
                    var question = removal.Permit.TrashEnabled ? "Permanently delete the one item? This cannot be undone."
                        : "Recycle bin disabled: Delete the selected items permanently?";
                    // The real native dialog, never a browser-confirmed flag.
                    // The saved-book permit and selection are rechecked after it.
                    if (MessageBox.Show(form, T(question) + "\n\n" + removal.Item.DisplayName, T("Delete permanently"),
                        MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                    { await Reply(new { requestId, device_id = peerId, ok = true, canceled = true }); return; }
                    var consent = NativeMediaPermanentConsent.FromConfirmedNativeChoice(removal.Permit, removal.Item.Entry);
                    var purged = await Task.Run(() => telefon.RemoveConfirmedNativeMediaTrash(removal, consent));
                    await Reply(new { requestId, device_id = peerId, ok = true, state = purged.State }); return;
                case "status":
                    var status = telefon.NativeMediaUiStatus(peerId); status["requestId"] = requestId; status["device_id"] = peerId; status["ok"] = true;
                    status["transfer_busy"] = nativeMediaUiRuns.ContainsKey(peerId) || status["automatic_busy"]?.GetValue<bool>() == true;
                    await Reply(status); return;
                case "mode":
                    var mode = telefon.SetNativeMediaUiAutomaticMode(peerId, request.Version, request.Automatic);
                    mode["requestId"] = requestId; mode["device_id"] = peerId; mode["ok"] = true;
                    await Reply(mode); return;
                case "settings":
                    var settings = telefon.SetNativeMediaUiChoices(peerId, request.Version, request.Photos, request.Videos, request.SkipDeletions);
                    settings["requestId"] = requestId; settings["device_id"] = peerId; settings["ok"] = true;
                    await Reply(settings); return;
                case "default_destination":
                    telefon.ResetNativeMediaUiDestination(peerId, request.MediaType, request.Version);
                    var defaultDestination = telefon.NativeMediaUiStatus(peerId);
                    defaultDestination["requestId"] = requestId; defaultDestination["device_id"] = peerId; defaultDestination["ok"] = true;
                    await Reply(defaultDestination); return;
                case "pick_destination":
                    telefon.RequireNativeMediaUiDestinationConsent(peerId);
                    // Only the actual native picker supplies a path. Request
                    // grammar has no path, root identity or destination token.
                    var book = NativeActorSavedBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
                    var peer = telefon.Peers.Single(value => value.Id == peerId);
                    var parent = request.MediaType == "video" ? VideoDestinationPaths.NativeVideosDirectory() : PhotoDestinationPaths.NativePicturesDirectory();
                    var leaf = request.MediaType == "video" ? VideoDestinationPaths.NativeFolderComponent(peer.Name) : PhotoDestinationPaths.NativeFolderComponent(peer.Name);
                    var local = telefon.NativeMediaUiStatus(peerId);
                    var destinationKey = request.MediaType == "video" ? "video_destination" : "pictures";
                    if (local[destinationKey]?["version"]?.GetValue<string>() != request.Version) throw DeviceFileControl.Error("file_destination_stale_choice");
                    var proposed = Path.Combine(parent, leaf);
                    using (var dialog = new FolderBrowserDialog { Description = T("Choose folder …") + " · " + leaf,
                        UseDescriptionForTitle = true, ShowNewFolderButton = true,
                        SelectedPath = local[destinationKey]?["display_path"]?.GetValue<string>() ?? (Directory.Exists(proposed) ? proposed : parent) })
                    {
                        if (dialog.ShowDialog(form) != DialogResult.OK)
                        { await Reply(new { requestId, device_id = peerId, ok = true, canceled = true }); return; }
                        if (NativeActorSavedBook() != book) throw DeviceFileControl.Error("file_media_current_saved_book_required");
                        if (request.Version is null && string.Equals(Path.GetFullPath(dialog.SelectedPath).TrimEnd('\\'), Path.GetFullPath(parent).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                        {
                            // Explicit first choice of the native Pictures/Videos
                            // base creates its proposed phone child with NT
                            // CREATE_ONLY. Never recreate an existing mapping.
                            using var baseOwner = DeviceFileNativeDirectory.OpenExistingForReceive(parent);
                            using var owner = baseOwner.CreateChild(leaf);
                            telefon.SetNativeMediaUiDestination(peerId, request.MediaType, null, owner);
                        }
                        else
                        {
                            using var owner = DeviceFileNativeDirectory.OpenExistingForReceive(dialog.SelectedPath);
                            telefon.SetNativeMediaUiDestination(peerId, request.MediaType, request.Version, owner);
                        }
                    }
                    var picked = telefon.NativeMediaUiStatus(peerId); picked["requestId"] = requestId; picked["device_id"] = peerId; picked["ok"] = true;
                    await Reply(picked); return;
                case "cancel":
                    var stopping = nativeMediaUiRuns.TryGetValue(peerId, out var running);
                    if (stopping) { try { running!.Cancel(); } catch (ObjectDisposedException) { stopping = false; } }
                    stopping |= telefon.StopNativeMediaAutomatic(peerId);
                    await Reply(new { requestId, device_id = peerId, ok = true, state = stopping ? "stopping" : "idle" }); return;
                case "discover":
                case "page":
                    using (var deadline = NetworkDeadline(TimeSpan.FromMinutes(2)))
                    {
                        var catalog = request.Action == "discover"
                            ? await telefon.DiscoverNativeMediaUiAsync(peerId, request.MediaType, deadline.Token)
                            : await telefon.PageNativeMediaUiAsync(peerId, request.MediaType, request.Version!, request.Catalog!, request.After, deadline.Token);
                        var page = catalog.Page;
                        await Reply(new { requestId, device_id = peerId, ok = true, media_type = request.MediaType, version = catalog.Version, catalog_id = page.CatalogId,
                            after = page.After, next_cursor = page.NextCursor, coverage = page.Coverage, albums = page.Albums.Select(album => new {
                                album_id = album.AlbumId, display_name = album.DisplayName, needs_choice = album.NeedsChoice }) });
                    }
                    return;
                case "request_read":
                    using (var deadline = NetworkDeadline(TimeSpan.FromMinutes(1)))
                    {
                        var permission = await telefon.RequestNativeMediaUiReadAsync(peerId, request.MediaType, request.Version!, deadline.Token);
                        await Reply(new { requestId, device_id = peerId, ok = true, state = "permission_requested", permission = permission.State, version = permission.Version });
                    }
                    return;
                case "sync":
                    using (var lifetime = NetworkDeadline(TimeSpan.FromHours(2)))
                    {
                        if (!nativeMediaUiRuns.TryAdd(peerId, lifetime)) throw DeviceFileControl.Error("file_media_native_worker_busy");
                        try
                        {
                            await Reply(new { requestId, device_id = peerId, ok = true, state = "running" });
                            var outcome = await telefon.SynchronizeNativeMediaUiAsync(peerId, request.MediaType, request.Version!, request.Catalog!, request.Album!, lifetime.Token);
                            await Reply(new { requestId, device_id = peerId, ok = true, state = outcome.NeedsReview ? "review" : "content_complete",
                                received_jobs = outcome.ReceivedJobs.Count, processed = outcome.Members.Count,
                                copied = outcome.Members.Count(item => item.Action == "copy_phone_new"), replaced = outcome.Members.Count(item => item.Action == "replace_managed_desktop"),
                                unchanged = outcome.Members.Count(item => item.Action == "unchanged"), kept_edits = outcome.Members.Count(item => item.Action == "keep_local_edit"),
                                coverage_uncertain = outcome.CoverageUncertain,
                                review = outcome.Members.Where(item => item.Action is not ("copy_phone_new" or "replace_managed_desktop" or "unchanged" or "keep_local_edit"))
                                    .Take(128).Select(item => new { name = item.Target, reason = item.Action }), deletions_ready = false });
                        }
                        finally { nativeMediaUiRuns.TryRemove(peerId, out _); }
                    }
                    return;
            }
        }
        catch (OperationCanceledException) { await Reply(new { requestId, device_id = peerId, ok = false, state = "partial", error = "canceled" }); }
        catch (Exception error)
        {
            await ReportErrorAsync("telefon_medien", error.ToString());
            await Reply(new { requestId, device_id = peerId, ok = false, supported = Text(message, "action") == "status" ? false : (bool?)null,
                state = "held", error = error is InvalidDataException ? error.Message : "file_media_native_operation_failed" });
        }
    }
}
