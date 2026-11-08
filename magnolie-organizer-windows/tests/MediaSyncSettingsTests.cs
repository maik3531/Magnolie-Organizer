using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class MediaSyncSettingsTests
{
    private const string Pc = "11111111-1111-4111-8111-111111111111", Phone = "22222222-2222-4222-8222-222222222222";
    internal static Task RunAsync()
    {
        var initial = MediaSyncSettings.Create(Pc); var original = initial.ToJsonString();
        var start = new JsonObject { ["format"] = 1, ["settings"] = initial.DeepClone() };
        MediaSyncSettings.ValidateStart(start);
        var partial = start.DeepClone().AsObject(); partial["settings"]!["settings"]!.AsObject().Remove("enabled");
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.ValidateStart(partial), "Manual start accepted an incomplete settings snapshot.");
        var pathStart = start.DeepClone().AsObject(); pathStart["path"] = "C:\\foreign";
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.ValidateStart(pathStart), "Manual request accepted a native filesystem path.");
        var report = new JsonObject { ["format"] = 1, ["request_id"] = Guid.NewGuid().ToString("D"), ["state"] = "content_pass" };
        MediaSyncSettings.ValidateResult(report); report["state"] = "complete";
        TestAssert.Throws<InvalidDataException>(() => MediaSyncSettings.ValidateResult(report), "Content pass report claimed complete bilateral/deletion synchronization.");
        var defaults = MediaSyncSettings.Effective(initial);
        TestAssert.That(defaults.Count == 7 && !defaults["enabled"]!.GetValue<bool>() && defaults["photos_enabled"]!.GetValue<bool>() && !defaults["videos_enabled"]!.GetValue<bool>() &&
            defaults["auto_mode"]!.GetValue<string>() == "manual" && !defaults["skip_deletions"]!.GetValue<bool>() &&
            defaults["collection_mode"]!.GetValue<string>() == "phone_inventory" && defaults["direction"]!.GetValue<string>() == "phone_to_pc",
            "Media intent did not preserve the requested new defaults or enabled a data permission.");
        TestAssert.That(!MediaSyncSettings.RequestedFor(initial, "images") && !MediaSyncSettings.RequestedFor(initial, "video"), "The disabled master switch left a media domain requested.");
        foreach (var scope in new[] { "phone_inventory", "entire_collection", "import_only" })
        foreach (var direction in new[] { "phone_to_pc", "two_way", "pc_to_phone" })
        {
            var choices = MediaSyncSettings.Change(initial, Pc, Phone, "enabled", JsonValue.Create(true)!);
            choices = MediaSyncSettings.Change(choices, Pc, Phone, "collection_mode", JsonValue.Create(scope)!);
            choices = MediaSyncSettings.Change(choices, Pc, Phone, "direction", JsonValue.Create(direction)!);
            var before = choices.ToJsonString(); var activeDirection = scope == "import_only" ? "phone_to_pc" : direction;
            TestAssert.That(MediaSyncSettings.Effective(choices)["direction"]!.GetValue<string>() == activeDirection &&
                MediaSyncSettings.TransferRequestedFor(choices, "images", false) == (activeDirection is "phone_to_pc" or "two_way") &&
                MediaSyncSettings.TransferRequestedFor(choices, "images", true) == (activeDirection is "pc_to_phone" or "two_way"),
                "Scope/direction transfer matrix changed: " + scope + "/" + direction);
            TestAssert.That(choices.ToJsonString() == before && choices["settings"]!["direction"]![Pc]!["value"]!.GetValue<string>() == direction,
                "Effective import mode overwrote the saved direction choice.");
            var restored = MediaSyncSettings.Change(choices, Pc, Phone, "collection_mode", JsonValue.Create("phone_inventory")!);
            TestAssert.That(MediaSyncSettings.Effective(restored)["direction"]!.GetValue<string>() == direction &&
                JsonNode.DeepEquals(restored["settings"]!["direction"], choices["settings"]!["direction"]),
                "Changing scope rewrote the independent direction clock.");
        }
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
