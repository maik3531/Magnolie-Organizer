using System.Diagnostics;
using System.Reflection;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarUnfoldingTests
{
    private static readonly MethodInfo Unfold = typeof(ExchangeCodec).GetMethod("Unfold", BindingFlags.Static | BindingFlags.NonPublic)!;
    private static string[] Actual(string text) => ((IEnumerable<string>)Unfold.Invoke(null, [text])!).ToArray();
    private static string[] Legacy(string text)
    {
        var result = new List<string>();
        foreach (var line in text.ReplaceLineEndings("\n").Split('\n'))
            if ((line.StartsWith(' ') || line.StartsWith('\t')) && result.Count > 0) result[^1] += line[1..]; else result.Add(line.TrimEnd('\r'));
        return result.ToArray();
    }
    private static string Calendar(int count)
    {
        var text = new StringBuilder("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-folds\r\nDTSTART:20261108T090000Z\r\nDTEND:20261108T100000Z\r\nSUMMARY:Folded\r\nDESCRIPTION:");
        text.Append('x', 63).Append("\r\n");
        for (var i = 0; i < count; i++) text.Append(' ').Append('x', 74).Append("\r\n");
        return text.Append("END:VEVENT\r\nEND:VCALENDAR\r\n").ToString();
    }
    internal static Task SemanticsAsync()
    {
        var examples = new List<string> { "", " ", "\t", "\r\n hello", "\tfirst\r\n second", "a\r\n\t\r\n b\r\n\r\n c", "a\rb\n c\r\n\td", " ä\r\n\t中\r\n  🙂", "a\u0085 b\u2028\tc\u2029d" };
        var random = new Random(442); const string letters = "abä中 :;\t";
        for (var i = 0; i < 1000; i++)
        {
            var lines = Enumerable.Range(0, random.Next(20)).Select(_ => new string(Enumerable.Range(0, random.Next(24)).Select(_ => letters[random.Next(letters.Length)]).ToArray()));
            examples.Add(string.Join(new[] { "\r\n", "\r", "\n" }[random.Next(3)], lines));
        }
        foreach (var text in examples) TestAssert.That(Actual(text).SequenceEqual(Legacy(text)), "ICS unfolding changed leading-fold/blank/newline semantics.");
        foreach (var count in new[] { 0, 1, 2, 64, 512, 2048, 8192 })
        {
            var imported = ExchangeCodec.ParseIcs(Calendar(count), "fold-fixture", TimeZoneInfo.Utc);
            TestAssert.That(imported.Termine.Count == 1 && imported.Termine[0]!["notiz"]!.GetValue<string>() == new string('x', 63 + 74 * count), "Actual ICS codec truncated or changed a folded description.");
        }
        return Task.CompletedTask;
    }
    internal static Task AllocationsAsync()
    {
        _ = ExchangeCodec.ParseIcs(Calendar(32), "fold-fixture", TimeZoneInfo.Utc);
        var allocations = new List<long>();
        foreach (var count in new[] { 512, 1024, 2048 })
        {
            var text = Calendar(count); var before = GC.GetAllocatedBytesForCurrentThread(); var elapsed = Stopwatch.StartNew();
            var imported = ExchangeCodec.ParseIcs(text, "fold-fixture", TimeZoneInfo.Utc);
            var bytes = GC.GetAllocatedBytesForCurrentThread() - before; allocations.Add(bytes);
            TestAssert.That(imported.Termine.Count == 1 && imported.Termine[0]!["notiz"]!.GetValue<string>() == new string('x', 63 + 74 * count), "Allocation probe lost input content.");
            Console.WriteLine($"ICS folds {count}: allocated={bytes} elapsed_ms={elapsed.Elapsed.TotalMilliseconds:F2}");
        }
        TestAssert.That(allocations[^1] < 128L * 1024 * 1024 && allocations[2] <= allocations[1] * 2.75,
            "#442: actual ICS import allocates quadratically for valid folded lines.");
        return Task.CompletedTask;
    }
}
