using MagnolieOrganizer.Windows;
using System.Text.Json;
using System.Reflection;
using System.Runtime.Loader;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NormativeTimezoneTests
{
    internal static void Points()
    {
        static NormativeTimezones.Zone Zone(string id)
        {
            TestAssert.That(NormativeTimezones.TryGet(id, out var value) && value is not null, "Bound named zone is missing: " + id);
            return value!;
        }
        var casablanca = Zone("Africa/Casablanca");
        TestAssert.That(casablanca.ToUtc(new DateTime(2026, 1, 15, 12, 30, 0)) == new DateTime(2026, 1, 15, 11, 30, 0), "Casablanca normative winter point differs.");
        var almaty = Zone("Asia/Almaty");
        foreach (var year in new[] { 2026, 2400, 9998 })
            foreach (var month in new[] { 1, 7 })
                TestAssert.That(almaty.ToUtc(new DateTime(year, month, 15, 12, 30, 0)) == new DateTime(year, month, 15, 7, 30, 0), "Almaty future rules differ.");
        var berlin = Zone("Europe/Berlin");
        var gap = new DateTime(2026, 3, 29, 2, 30, 17).AddTicks(1234);
        TestAssert.That(berlin.IsGap(gap) && berlin.ToUtc(gap) == new DateTime(2026, 3, 29, 1, 30, 17).AddTicks(1234), "Gap lost pre-transition offset or fractional seconds.");
        var fold = new DateTime(2026, 10, 25, 2, 30, 17);
        TestAssert.That(berlin.FoldSpan(fold) == TimeSpan.FromHours(1) && berlin.ToUtc(fold) == new DateTime(2026, 10, 25, 0, 30, 17), "Fold did not select the earlier instant.");
        var monrovia = Zone("Africa/Monrovia");
        TestAssert.That(monrovia.ToUtc(new DateTime(1970, 1, 1, 2, 0, 0)) == new DateTime(1970, 1, 1, 2, 44, 30), "Historical offset seconds were rounded.");
        foreach (var id in new[] { "UTC", "Etc/UTC", "America/New_York", "Australia/Sydney", "Pacific/Apia", "Europe/Berlin" })
            foreach (var year in new[] { 1, 4, 1900, 2000, 2400, 9999 })
                foreach (var month in new[] { 1, 7, 12 })
                {
                    var zone = Zone(id); var utc = new DateTime(year, month, 15, 12, 30, 17, DateTimeKind.Utc).AddTicks(9876);
                    TestAssert.That(zone.ToUtc(zone.FromUtc(utc)) == utc, "Named-zone boundary/future roundtrip differs: " + id);
                }
        TestAssert.Throws<InvalidDataException>(() => Zone("Etc/GMT-14").FromUtc(DateTime.MaxValue), "Overflowing civil result was clamped.");
        TestAssert.That(!NormativeTimezones.TryGet("Mars/Olympus", out _), "Unknown named zone silently resolved.");
        FutureSelectors();
        RejectChangedResources();
    }

    private static void FutureSelectors()
    {
        // Bounded synthetic rule rows exercise the evaluator's complete schema,
        // including POSIX forms not necessarily selected by today's real zones.
        static NormativeTimezones.Zone Synthetic(string from, string through, int standard = 0, int daylight = 3600)
        {
            using var row = JsonDocument.Parse("[0,[[" + standard + ",0,\"STD\",0,0],[" + daylight +
                ",1,\"DST\",0,0]],[],[" + standard + ",\"STD\"," + daylight + ",\"DST\"," + from + "," + through + ",\"synthetic-only\"]]");
            return new NormativeTimezones.Zone(row.RootElement);
        }
        var julian = Synthetic("[\"J\",60,0,0,0]", "[\"J\",300,0,0,0]");
        var ordinal = Synthetic("[\"N\",59,0,0,0]", "[\"N\",300,0,0,0]");
        var leapDay = new DateTime(2400, 2, 29, 12, 0, 0);
        TestAssert.That(julian.FromUtc(leapDay) == leapDay && ordinal.FromUtc(leapDay) == leapDay.AddHours(1), "POSIX J and zero-based N rules confused leap day.");
        var month = Synthetic("[\"M\",3,5,0,-7200]", "[\"M\",10,5,0,90000]");
        var before = new DateTime(2026, 3, 28, 21, 59, 59); var after = before.AddSeconds(1);
        TestAssert.That(month.FromUtc(before) == before && month.FromUtc(after) == after.AddHours(1), "M last-weekday/negative transition clock differs.");
        before = new DateTime(2026, 10, 26); after = before.AddTicks(-1);
        TestAssert.That(month.FromUtc(before) == before && month.FromUtc(after) == after.AddHours(1), "POSIX transition clock beyond 24 hours was truncated.");
        var wide = Synthetic("[\"M\",3,5,0,7200]", "[\"M\",10,5,0,7200]", 90000, 93599);
        var point = new DateTime(2400, 1, 15, 12, 30, 17).AddTicks(2468);
        TestAssert.That(wide.FromUtc(point) == point.AddSeconds(90000) && wide.ToUtc(wide.FromUtc(point)) == point, "Complete schema offset range/precision was limited to TimeZoneInfo.");
        // Southern rules need the previous year's transition; a signed rule
        // clock near New Year can also put next year's event in year 9999.
        var southern = Synthetic("[\"M\",10,1,0,7200]", "[\"M\",4,1,0,7200]");
        point = new DateTime(1, 1, 2, 12, 0, 0);
        TestAssert.That(southern.FromUtc(point) == point.AddHours(1), "Proleptic neighbor year zero was lost.");
        var yearEnd = Synthetic("[\"J\",1,0,0,-86400]", "[\"J\",2,0,0,0]");
        point = new DateTime(9999, 12, 31, 12, 0, 0);
        TestAssert.That(yearEnd.FromUtc(point) == point.AddHours(1), "Proleptic neighbor year 10000 was clamped.");
    }

    private static void RejectChangedResources()
    {
        var original = File.ReadAllBytes(typeof(NormativeTimezones).Assembly.Location);
        foreach (var name in new[] { "tzdb-2026egtz.json", "provenance.json", "LICENSE-tzdb.txt" })
        {
            using var resource = typeof(NormativeTimezones).Assembly.GetManifestResourceStream("Magnolie.Timezones." + name)!;
            using var buffer = new MemoryStream(); resource.CopyTo(buffer); var data = buffer.ToArray();
            var index = original.AsSpan().IndexOf(data);
            TestAssert.That(index >= 0 && original.AsSpan(index + data.Length).IndexOf(data) < 0, "Exact embedded resource is not unique.");
            var changed = (byte[])original.Clone(); changed[index] ^= 1;
            var context = new AssemblyLoadContext("synthetic-timezone-resource-" + name, isCollectible: true);
            try
            {
                using var image = new MemoryStream(changed);
                var assembly = context.LoadFromStream(image);
                var type = assembly.GetType(typeof(NormativeTimezones).FullName!, throwOnError: true)!;
                var lookup = type.GetMethod("TryGet", BindingFlags.NonPublic | BindingFlags.Static)!;
                var refused = false;
                try { lookup.Invoke(null, ["UTC", null]); }
                catch (TargetInvocationException error) when (error.InnerException is InvalidDataException failure && failure.Message.Contains("identity differs", StringComparison.Ordinal)) { refused = true; }
                TestAssert.That(refused, "Changed embedded rules/provenance/license fell back to an OS provider: " + name);
            }
            finally { context.Unload(); }
        }
    }
}
