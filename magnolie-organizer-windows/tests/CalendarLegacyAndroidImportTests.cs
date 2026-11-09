using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarLegacyAndroidImportTests
{
    internal static Task RunAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        const string marker = "tests/fixtures/caldav-series-resource.ics";
        // Python's public file-import source qualifier hashes source path and
        // X-WR-CALNAME. Feed that same qualified identity to the native codec.
        var source = "ics:" + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes("ics:" + new string('a', 64) + "\nTeam Calendar"))).ToLowerInvariant();
        var result = ExchangeCodec.ParseIcs(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)), source, TimeZoneInfo.Utc);
        var exception = result.Termine.OfType<JsonObject>().Single(item => item["icsRoundtrip"]!.AsArray()
            .Any(line => line!.GetValue<string>().StartsWith("RECURRENCE-ID", StringComparison.OrdinalIgnoreCase)));
        TestAssert.That(result.Termine.Count == 2 && result.Uebersprungen == 0 &&
            exception["uid"]!.GetValue<string>() == "caldav-series-1#20261102T100000" &&
            exception["icsSerienUid"]!.GetValue<string>() == "caldav-series-1" && exception["icsQuelleId"]!.GetValue<string>() == source &&
            exception["icsRoundtrip"]!.AsArray().Any(line => line!.GetValue<string>() == "RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000"),
            "Native Windows fixture no longer supplies the exact source/wire/full-RID identity used for the old Android alias probe.");
        // Public synthetic fixture only. Consumed by the full-desktop JS probe;
        // not a substitute for native persistence or installed GUI acceptance.
        Console.WriteLine("LEGACY462_NATIVE_PAYLOAD=" + result.ToPayload("ics", "caldav-series-resource.ics").ToJsonString());
        return Task.CompletedTask;
    }
}
