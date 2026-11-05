using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class MediaSyncSettingsTests
{
    private const string Pc = "11111111-1111-4111-8111-111111111111", Phone = "22222222-2222-4222-8222-222222222222";
    internal static Task RunAsync()
    {
        var initial = MediaSyncSettings.Create(Pc); var original = initial.ToJsonString();
        var defaults = MediaSyncSettings.Effective(initial);
        TestAssert.That(defaults.Count == 7 && !defaults["enabled"]!.GetValue<bool>() && defaults["photos_enabled"]!.GetValue<bool>() && !defaults["videos_enabled"]!.GetValue<bool>() &&
            defaults["auto_mode"]!.GetValue<string>() == "manual" && !defaults["skip_deletions"]!.GetValue<bool>() &&
            defaults["collection_mode"]!.GetValue<string>() == "phone_inventory" && defaults["direction"]!.GetValue<string>() == "phone_to_pc",
            "Media intent did not preserve the requested new defaults or enabled a data permission.");
        TestAssert.That(!MediaSyncSettings.RequestedFor(initial, "images") && !MediaSyncSettings.RequestedFor(initial, "video"), "The disabled master switch left a media domain requested.");
        var activated = MediaSyncSettings.Change(initial, Pc, Phone, "enabled", JsonValue.Create(true)!);
        TestAssert.That(MediaSyncSettings.RequestedFor(activated, "images") && !MediaSyncSettings.RequestedFor(activated, "video") &&
            activated["settings"]!["photos_enabled"]![Pc]!["counter"]!.GetValue<int>() == 0,
            "Module activation changed photo selection's independent clock or enabled video.");
        var left = MediaSyncSettings.Change(initial, Pc, Phone, "photos_enabled", JsonValue.Create(true)!);
        var right = MediaSyncSettings.Change(MediaSyncSettings.Create(Phone), Phone, Pc, "videos_enabled", JsonValue.Create(true)!);
        var merged = MediaSyncSettings.Merge(left, right, Pc, Phone);
        TestAssert.That(MediaSyncSettings.Effective(merged)["photos_enabled"]!.GetValue<bool>() && MediaSyncSettings.Effective(merged)["videos_enabled"]!.GetValue<bool>() &&
            JsonNode.DeepEquals(merged, MediaSyncSettings.Merge(right, left, Phone, Pc)) && initial.ToJsonString() == original,
            "An offline media edit overwrote an independent field, depended on merge order, or mutated its input.");
        var off = MediaSyncSettings.Change(MediaSyncSettings.Create(Phone), Phone, Pc, "photos_enabled", JsonValue.Create(false)!);
        TestAssert.That(!MediaSyncSettings.Effective(MediaSyncSettings.Merge(left, off, Pc, Phone))["photos_enabled"]!.GetValue<bool>(), "Concurrent photo choices did not resolve safely to off.");
        left = MediaSyncSettings.Change(initial, Pc, Phone, "auto_mode", JsonValue.Create("wifi")!);
        right = MediaSyncSettings.Change(MediaSyncSettings.Create(Phone), Phone, Pc, "auto_mode", JsonValue.Create("manual")!);
        TestAssert.That(MediaSyncSettings.Effective(MediaSyncSettings.Merge(left, right, Pc, Phone))["auto_mode"]!.GetValue<string>() == "manual", "Concurrent media modes did not keep manual operation.");
        var invalid = initial.DeepClone().AsObject(); invalid["settings"]!["path"] = new JsonObject();
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.Validate(invalid), "A native path entered shared media intent.");
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.Change(initial, Pc, Phone, "auto_mode", JsonValue.Create("connection")!), "Personal automatic-on-connection mode entered media preferences.");
        var forged = MediaSyncSettings.Change(initial, Pc, Phone, "photos_enabled", JsonValue.Create(true)!);
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.Merge(initial, forged, Pc, Phone), "Remote media intent forged a new local edit.");
        var foreign = MediaSyncSettings.Create("33333333-3333-4333-8333-333333333333");
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.Merge(initial, foreign, Pc, Phone), "A foreign actor entered the media relationship.");
        var own = MediaSyncSettings.Merge(initial, off, Pc, Phone);
        var conflicting = off.DeepClone().AsObject(); conflicting["settings"]!["photos_enabled"]![Phone]!["value"] = true;
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.Merge(own, conflicting, Pc, Phone), "Equal media clocks silently replaced conflicting values.");
        TestAssert.That(JsonNode.DeepEquals(own, MediaSyncSettings.Merge(own, MediaSyncSettings.Create(Phone), Pc, Phone)), "An old media snapshot replayed an earlier field value.");
        return Task.CompletedTask;
    }
}
