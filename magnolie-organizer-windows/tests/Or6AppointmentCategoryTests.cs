using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6AppointmentCategoryTests
{
    private static string[] Dates(JsonObject item)
    {
        using var input = JsonDocument.Parse(item.ToJsonString());
        return CalendarRecurrence.Expand(input.RootElement, new DateTime(2026, 10, 1), new DateTime(2026, 12, 1), TimeZoneInfo.Utc)
            .Select(value => value.Start.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).ToArray();
    }
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-appointment-categories.json"), "contracts/or6-native-appointment-categories.json")))!;
        var expected = contract["expected"]!; var title = expected["title"]!.GetValue<string>();
        foreach (var pair in contract["files"]!.AsObject())
        {
            var raw = Or6TaskScopeTests.Fixture(pair.Value!); var result = Or6Codec.Read(raw);
            var item = result.Termine.OfType<JsonObject>().Single(item => ContactFields.Text(item, "titel") == title);
            var dates = expected["datesByFile"]![pair.Key]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
            TestAssert.That(result.Uebersprungen == 0 && ContactFields.Text(item, "kategorien") == expected["category"]!.GetValue<string>() &&
                ContactFields.Text(item, "zeit") == expected["startTime"]!.GetValue<string>() && ContactFields.Text(item, "endZeit") == expected["endTime"]!.GetValue<string>() &&
                Dates(item).SequenceEqual(dates) && item["akzentFarbe"] is null, "Original appointment category/date/clock lost or guessed into a color");
            using var input = JsonDocument.Parse(new JsonArray(item.DeepClone()).ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-termine", input.RootElement); var imported = ExchangeCodec.ParseIcs(export.Text).Termine.Single()!.AsObject();
            TestAssert.That(export.Count == 1 && export.Skipped == 0 && JsonNode.DeepEquals(item["kategorien"], imported["kategorien"]) && Dates(imported).SequenceEqual(dates), "Actual calendar export lost original category or dates");
            var basis = Or6Codec.Read(Or6CodecTests.Fixture());
            TestAssert.That(JsonNode.DeepEquals(basis.Aufgaben, result.Aufgaben) && JsonNode.DeepEquals(basis.Kontakte, result.Kontakte) && JsonNode.DeepEquals(basis.Notizen, result.Notizen), "Calendar category mapping changed another collection");
        }
        var ordinary = Or6Codec.Read(Or6CodecTests.Fixture()).Termine.Single()!;
        TestAssert.That(ordinary["kategorien"] is null && ordinary["akzentFarbe"] is null, "Empty source category acquired guessed metadata");
        var decoded = Rotate(Or6TaskScopeTests.Fixture(contract["files"]!["appointment-category-final-v1-613.or6"]!), true);
        var owner = Blocks(decoded).Where(at => U32(decoded, at) == 0x100 && FieldTextIfPresent(decoded, at, 9) == title).OrderBy(at => decoded[Field(decoded, at, 7).Value + 2]).ThenBy(at => decoded[Field(decoded, at, 7).Value + 3]).Last();
        var field = Field(decoded, owner, 3); var source = Encoding.Unicode.GetString(decoded, field.Value, field.Length); var changed = source.Replace("Work", "Home", StringComparison.Ordinal);
        TestAssert.That(changed != source && changed.Length == source.Length, "Independent category field changed");
        Encoding.Unicode.GetBytes(changed).CopyTo(decoded, field.Value);
        var held = Or6Codec.Read(Rotate(decoded, false));
        var selected = held.Termine.OfType<JsonObject>().Where(item => ContactFields.Text(item, "titel") == title).ToArray();
        TestAssert.That(held.Uebersprungen == 0 && selected.Length == 2 &&
            selected.Count(item => ContactFields.Text(item, "kategorien") == "OR6-613 Work") == 1 &&
            selected.Count(item => ContactFields.Text(item, "kategorien") == "OR6-613 Home" && item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == "RECURRENCE-ID:20261107T101500")) == 1,
            "One occurrence category spread to the entire series rather than a bound override");
    }
}
