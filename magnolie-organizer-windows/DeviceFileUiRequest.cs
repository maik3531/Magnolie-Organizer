using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaUiRequest(string RequestId, string PeerId, string Action, string MediaType, string? Version,
    string? Catalog, string? Album, int After, bool Photos, bool Videos, bool SkipDeletions, bool Automatic = false)
{
    internal static NativeMediaUiRequest Parse(JsonObject value)
    {
        string Text(string key) => TelefonMessagingContract.String(value, key);
        var action = Text("action"); var fields = new List<string> { "cmd", "requestId", "device_id", "action" };
        if (action is "pick_destination" or "discover" or "page" or "sync" or "request_read") fields.Add("media_type");
        if (action is "mode" or "settings" or "pick_destination" or "page" or "sync" or "request_read") fields.Add("version");
        if (action == "mode") fields.Add("automatic");
        if (action is "page" or "sync") fields.Add("catalog_id");
        if (action == "page") fields.Add("after");
        if (action == "sync") fields.Add("album_id");
        if (action == "settings") fields.AddRange(["photos", "videos", "skip_deletions"]);
        TelefonProtocolContract.ExactObject(value, fields.ToArray());
        if (Text("cmd") != "telefon_medien" || action is not ("status" or "mode" or "settings" or "pick_destination" or "discover" or "page" or "sync" or "cancel" or "request_read") ||
            !Regex.IsMatch(Text("requestId"), "\\A[A-Za-z0-9_-]{8,80}\\z") || !DeviceFileControl.Identity(Text("device_id")))
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var kind = value.ContainsKey("media_type") ? Text("media_type") : "images";
        if (kind is not ("images" or "video")) throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var version = value["version"] is null ? null : Text("version");
        if (version is not null && !DeviceFileControl.Hash(version) || action is "page" or "sync" or "request_read" && version is null)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        var catalog = value.ContainsKey("catalog_id") ? Text("catalog_id") : null;
        var album = value.ContainsKey("album_id") ? Text("album_id") : null;
        var after = value.ContainsKey("after") ? TelefonProtocolContract.Integer(value["after"]) : 0;
        if (catalog is not null && !TelefonProtocolContract.IsUuidV4(catalog) || album is not null && !TelefonProtocolContract.IsUuidV4(album) || after is < 0 or > 50000)
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        bool Flag(string key) => value[key] is JsonValue item && item.TryGetValue<bool>(out var flag) ? flag : throw DeviceFileControl.Error("file_media_ui_request_invalid");
        return new(Text("requestId"), Text("device_id"), action, kind, version, catalog, album, (int)after,
            action == "settings" && Flag("photos"), action == "settings" && Flag("videos"), action != "settings" || Flag("skip_deletions"), action == "mode" && Flag("automatic"));
    }
}
