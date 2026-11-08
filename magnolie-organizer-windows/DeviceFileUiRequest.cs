using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaUiRequest(string RequestId, string PeerId, string Action, string MediaType, string? Version,
    string? Catalog, string? Album, int After, bool Photos, bool Videos, bool SkipDeletions, bool Automatic = false, string? TrashOperation = null, string? BackupId = null,
    string? SharedField = null, JsonNode? SharedValue = null, bool ReceiveConsent = false, string? BackupLocation = null)
{
    internal static NativeMediaUiRequest Parse(JsonObject value)
    {
        string Text(string key) => TelefonMessagingContract.String(value, key);
        var action = Text("action"); var fields = new List<string> { "cmd", "requestId", "device_id", "action" };
        if (action is "pick_backup_parent" or "backup_default" or "backup_list" or "backup_restore" or "pick_destination" or "default_destination" or "discover" or "page" or "sync" or "request_read") fields.Add("media_type");
        if (action is "pick_backup_parent" or "backup_default" or "backup_restore" or "trash_restore" or "trash_purge" or "mode" or "settings" or "pick_destination" or "default_destination" or "page" or "sync" or "request_read") fields.Add("version");
        if (action is "backup_list" or "backup_restore" && value.ContainsKey("location_id")) fields.Add("location_id");
        if (action == "backup_restore") fields.Add("backup_id");
        if (action is "trash_restore" or "trash_purge") fields.Add("operation_id");
        if (action == "mode") fields.Add("automatic");
        if (action is "page" or "sync") fields.Add("catalog_id");
        if (action is "backup_list" or "page" or "trash_list") fields.Add("after");
        if (action == "sync") fields.Add("album_id");
        if (action == "settings") fields.AddRange(["photos", "videos", "skip_deletions"]);
        if (action == "shared_setting") fields.AddRange(["field", "value", "version"]);
        if (action == "receive_consent") fields.AddRange(["granted", "version"]);
        TelefonProtocolContract.ExactObject(value, fields.ToArray());
        if (Text("cmd") != "telefon_medien" || action is not ("pick_backup_parent" or "backup_default" or "shared_setting" or "receive_consent" or "activate" or "backup_list" or "backup_restore" or "trash_list" or "trash_restore" or "trash_purge" or "status" or "mode" or "settings" or "pick_destination" or "default_destination" or "discover" or "page" or "sync" or "cancel" or "request_read") ||
            !Regex.IsMatch(Text("requestId"), "\\A[A-Za-z0-9_-]{8,80}\\z") || !DeviceFileControl.Identity(Text("device_id")))
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var kind = value.ContainsKey("media_type") ? Text("media_type") : "images";
        if (kind is not ("images" or "video")) throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var version = value["version"] is null ? null : Text("version");
        if (version is not null && !DeviceFileControl.Hash(version) || action is "shared_setting" or "receive_consent" or "backup_restore" or "trash_restore" or "trash_purge" or "page" or "sync" && version is null)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var catalog = value.ContainsKey("catalog_id") ? Text("catalog_id") : null;
        var album = value.ContainsKey("album_id") ? Text("album_id") : null;
        var after = value.ContainsKey("after") ? TelefonProtocolContract.Integer(value["after"]) : 0;
        if (catalog is not null && !TelefonProtocolContract.IsUuidV4(catalog) || album is not null && !TelefonProtocolContract.IsUuidV4(album) || after is < 0 or > 50000)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var trash = value.ContainsKey("operation_id") ? Text("operation_id") : null;
        if (trash is not null && (trash.Length != 32 || trash.Any(c => !char.IsAsciiHexDigitLower(c))) || action == "trash_list" && after > 2048)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var backup = value.ContainsKey("backup_id") ? Text("backup_id") : null;
        var location = value.ContainsKey("location_id") ? Text("location_id") : null;
        if (location is not null && !DeviceFileControl.Hash(location)) throw DeviceFileControl.Error("file_media_ui_request_invalid");
        if (backup is not null && !DeviceFileControl.Hash(backup) || action == "backup_list" && after > 4096)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        bool Flag(string key) => value[key] is JsonValue item && item.TryGetValue<bool>(out var flag) ? flag : throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var sharedField = action == "shared_setting" ? Text("field") : null;
        if (sharedField is not null)
        {
            // Pure validation only; the real current per-field CAS remains native.
            var actor = "11111111-1111-4111-8111-111111111111";
            _ = MediaSyncSettings.Change(MediaSyncSettings.Create(actor), actor, "22222222-2222-4222-8222-222222222222", sharedField,
                value["value"] ?? throw DeviceFileControl.Error("file_media_ui_request_invalid"));
        }
        return new(Text("requestId"), Text("device_id"), action, kind, version, catalog, album, (int)after,
            action == "settings" && Flag("photos"), action == "settings" && Flag("videos"), action != "settings" || Flag("skip_deletions"), action == "mode" && Flag("automatic"), trash, backup,
            sharedField, action == "shared_setting" ? value["value"]!.DeepClone() : null, action == "receive_consent" && Flag("granted"), location);
    }
}
