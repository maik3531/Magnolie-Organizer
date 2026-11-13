using System.Text.Json;
using System.Text.Json.Nodes;
using System.Buffers.Binary;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6AppointmentOverrideTests
{
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-appointment-overrides.json"), "contracts/or6-native-appointment-overrides.json")))!;
        foreach (var pair in contract["files"]!.AsObject())
        {
            var result = Or6Codec.Read(Or6TaskScopeTests.Fixture(pair.Value!));
            if (pair.Key == "appointment-overrides-reopened-v1-614.or6")
            {
                TestAssert.That(result.Termine.Count == 0 && result.Uebersprungen == 3, "Unknown native Pencil/Busy semantics discarded");
                continue;
            }
            var expected = contract["expected"]!;
            var master = result.Termine.OfType<JsonObject>().Single(item => ContactFields.Text(item, "uid") == expected["definitionUid"]!.GetValue<string>());
            var child = result.Termine.OfType<JsonObject>().Single(item => ContactFields.Text(item, "uid") == expected["movedUid"]!.GetValue<string>());
            bool Has(JsonObject item, string line) => item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == line);
            TestAssert.That(result.Uebersprungen == 0 && Has(master, "EXDATE:" + expected["originalSlot"]!.GetValue<string>()) &&
                Has(child, "RECURRENCE-ID:" + expected["originalSlot"]!.GetValue<string>()) &&
                Has(child, "DTSTART:" + expected["movedStart"]!.GetValue<string>()) && Has(child, "DTEND:" + expected["movedEnd"]!.GetValue<string>()) &&
                ContactFields.Text(child, "datum") == "2026-11-01" && ContactFields.Text(child, "zeit") == "14:30" && ContactFields.Text(child, "endZeit") == "16:00",
                "Original slot identity replaced by actual moved datetime");
            if (pair.Key.Contains("clock-content", StringComparison.Ordinal))
            {
                var changed = result.Termine.OfType<JsonObject>().Single(item => ContactFields.Text(item, "uid") == expected["changedUid"]!.GetValue<string>());
                TestAssert.That(ContactFields.Text(changed, "titel") == expected["changedTitle"]!.GetValue<string>() &&
                    ContactFields.Text(changed, "kategorien") == expected["changedCategory"]!.GetValue<string>() && Has(changed, "RECURRENCE-ID:20261107T101500"), "Native content exception lost");
            }
            using var input = JsonDocument.Parse(result.Termine.ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-termine", input.RootElement);
            var imported = ExchangeCodec.ParseIcs(export.Text).Termine.OfType<JsonObject>().Single(item => Has(item, "RECURRENCE-ID:" + expected["originalSlot"]!.GetValue<string>()));
            TestAssert.That(export.Skipped == 0 && ContactFields.Text(imported, "datum") == "2026-11-01" && ContactFields.Text(imported, "zeit") == "14:30" &&
                Has(imported, "X-MAGNOLIE-OR6-OBJECT-UID:" + expected["movedUid"]!.GetValue<string>()), "Actual ICS roundtrip lost moved/native identity");
        }
        var decoded = Rotate(Or6TaskScopeTests.Fixture(contract["files"]!["appointment-overrides-clock-content-reopened-v1-614.or6"]!), true);
        var owner = Blocks(decoded).Single(at => U32(decoded, at) == 0x100 && FieldTextIfPresent(decoded, at, 9) == "OR6-614 Changed");
        foreach (var mutation in new[] { "bad-index-width", "duplicate-index", "unknown-busy", "empty-category", "wrong-index-kind" })
        {
            var data = decoded.ToArray();
            if (mutation == "bad-index-width") BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(Field(data, owner, 14).Entry + 2), 2);
            else if (mutation == "duplicate-index") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(Field(data, owner, 14).Value), 1);
            else if (mutation == "unknown-busy") data[Field(data, owner, 15).Value] = 0;
            else if (mutation == "empty-category") { var field = Field(data, owner, 3); data.AsSpan(field.Value, field.Length).Clear(); }
            else
            {
                var changed = false;
                foreach (var at in Blocks(data).Where(at => U32(data, at) == 0xfffffffd))
                    if (U32(data, at + 0x18) == U32(data, owner + 0x18) && U32(data, at + 0x1c) == U32(data, owner + 0x1c) &&
                        BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(at + 0x24)) == 14)
                    { BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(at + 0x26), 3); changed = true; }
                TestAssert.That(changed, "Original calendar index declaration not found");
            }
            var held = Or6Codec.Read(Rotate(data, false));
            TestAssert.That(held.Termine.Count == 0 && held.Uebersprungen == 3, "Unknown/ambiguous calendar override normalized away: " + mutation);
        }
    }
}
