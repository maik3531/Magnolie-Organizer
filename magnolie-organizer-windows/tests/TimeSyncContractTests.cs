using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeSyncContractTests
{
    internal static Task RunAsync()
    {
        JsonObject Settings(bool enabled = true, long revision = 1) => new()
        {
            ["format"] = 7, ["scope"] = "time_tracking", ["enabled"] = enabled,
            ["revision"] = revision, ["epoch"] = Guid.NewGuid().ToString("D")
        };
        var local = Settings(); var remote = Settings();
        var body = new JsonObject
        {
            ["format"] = 7, ["trigger"] = "manual",
            ["sender_epoch"] = remote["epoch"]!.DeepClone(), ["receiver_epoch"] = local["epoch"]!.DeepClone(),
            ["sender_revision"] = 1, ["receiver_revision"] = 1
        };
        TimeSyncContract.Validate(TimeSyncContract.Request, body, true);
        TestAssert.That(TimeSyncContract.Allowed(body, local, remote, true, true, true, [7], [7]), "Current own-device consent should authorize time data.");
        foreach (var flags in new[] { (false, true, true), (true, false, true), (true, true, false) })
            TestAssert.That(!TimeSyncContract.Allowed(body, local, remote, flags.Item1, flags.Item2, flags.Item3, [7], [7]), "Stale or non-own controls authorized time data.");
        TestAssert.That(!TimeSyncContract.Allowed(body, local, remote, true, true, true, [7], [6]), "Version seven must be negotiated.");
        TestAssert.That(!TimeSyncContract.Allowed(body, Settings(false, 2), remote, true, true, true, [7], [7]), "Disabled consent authorized a queued request.");
        TestAssert.That(!TimeSyncContract.Allowed(body, Settings(true, 3), remote, true, true, true, [7], [7]), "Re-enabling revived an old request.");
        var newer = Settings(revision: 2);
        TimeSyncContract.AcceptSettings(local, newer);
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.AcceptSettings(newer, local), "Old consent revision accepted.");
        var sameEpoch = newer.DeepClone().AsObject(); sameEpoch["epoch"] = local["epoch"]!.DeepClone();
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.AcceptSettings(local, sameEpoch), "Changed consent reused an epoch.");
        var record = new JsonObject
        {
            ["id"] = Guid.NewGuid().ToString("D"), ["startMinute"] = 1000, ["endMinute"] = 1060,
            ["pauseMinute"] = null, ["pauseMinutes"] = 15, ["zone"] = "Europe/Berlin", ["type"] = "Synthetic",
            ["note"] = "", ["modifiedMs"] = 1000, ["deleted"] = false,
            ["clock"] = new JsonObject { [Guid.NewGuid().ToString("D")] = 1 }
        };
        body["entries"] = new JsonArray(record);
        TimeSyncContract.Validate(TimeSyncContract.Batch, body, true);
        foreach (var (field, value) in new (string, JsonNode?)[] {
            ("startMinute", JsonValue.Create("1000")), ("startMinute", JsonValue.Create(true)),
            ("deleted", JsonValue.Create(true)), ("pauseMinutes", JsonValue.Create(61)), ("pauseMinute", JsonValue.Create(1010)) })
        {
            var bad = record.DeepClone().AsObject(); bad[field] = value;
            TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.ValidateRecord(bad), "Malformed or deleting time record accepted.");
        }
        body["calendar"] = new JsonObject { ["enabled"] = false, ["country"] = "DE", ["regions"] = new JsonArray(), ["holidays"] = new JsonArray() };
        TimeSyncContract.Validate(TimeSyncContract.Batch, body, true);
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.Validate(TimeSyncContract.Batch, body, false), "Phone supplied authoritative Organizer calendar settings.");
        var open = record.DeepClone().AsObject();
        open["endMinute"] = null;
        open["pausePlan"] = new JsonObject
        {
            ["fixed"] = new JsonArray(new JsonObject { ["start"] = 720, ["end"] = 750 }),
            ["manual"] = new JsonArray(new JsonObject { ["start"] = 1000, ["end"] = 1015 }),
            ["replaced"] = new JsonArray(), ["fixedEnds"] = new JsonObject(), ["baseMinutes"] = 0
        };
        TimeSyncContract.ValidateRecord(open);
        foreach (var mutate in new Action<JsonObject>[] {
            plan => plan["endAlarm"] = new JsonObject(),
            plan => plan["fixed"] = new JsonArray(new JsonObject { ["start"] = "720", ["end"] = 750 }),
            plan => plan["fixed"] = new JsonArray(new JsonObject { ["start"] = 720, ["end"] = 720 }),
            plan => plan["replaced"] = new JsonArray(1000, 1000),
            plan => plan["replaced"] = new JsonArray(1001, 1000),
            plan => plan["fixedEnds"] = new JsonObject { ["01000"] = 1005 },
            plan => plan["manual"] = new JsonArray(new JsonObject { ["start"] = 1000, ["end"] = 1030 },
                new JsonObject { ["start"] = 1020, ["end"] = 1040 }) })
        {
            var bad = open.DeepClone().AsObject(); mutate(bad["pausePlan"]!.AsObject());
            TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.ValidateRecord(bad), "Private or malformed pause plan accepted.");
        }
        var finishedWithPlan = open.DeepClone().AsObject(); finishedWithPlan["endMinute"] = 1060;
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.ValidateRecord(finishedWithPlan), "Finished time record still recalculates a live pause plan.");
        var tombstone = record.DeepClone().AsObject();
        tombstone["startMinute"] = 0; tombstone["endMinute"] = 0; tombstone["pauseMinute"] = null;
        tombstone["pauseMinutes"] = 0; tombstone["zone"] = "UTC"; tombstone["type"] = ""; tombstone["note"] = "";
        tombstone["deleted"] = true; tombstone["pausePlan"] = null;
        TimeSyncContract.ValidateRecord(tombstone, allowDeletion: true);
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.ValidateRecord(tombstone), "A Notes message introduced an Organizer deletion.");
        tombstone["note"] = "Removed private contents";
        TestAssert.Throws<InvalidDataException>(() => TimeSyncContract.ValidateRecord(tombstone, allowDeletion: true), "Deletion marker retained private contents.");
        return Task.CompletedTask;
    }
}
