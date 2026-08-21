using System.Diagnostics;

namespace MagnolieOrganizer.Windows.Tests;

internal sealed class TestRunner
{
    private readonly List<(string Name, Func<Task> Test)> tests = new();

    internal void Add(string name, Func<Task> test) => tests.Add((name, test));

    internal async Task<int> RunAsync(string? filter = null)
    {
        var selected = string.IsNullOrWhiteSpace(filter) ? tests : tests.Where(test =>
            test.Name.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();
        if (selected.Count == 0) throw new InvalidOperationException($"Keine Testgruppe entspricht '{filter}'.");
        var failed = 0;
        Console.WriteLine($"Magnolie CoreTests: {selected.Count} Gruppen");
        foreach (var (name, test) in selected)
        {
            var watch = Stopwatch.StartNew();
            try
            {
                await test();
                Console.WriteLine($"  OK     {name} ({watch.Elapsed.TotalSeconds:F2} s)");
            }
            catch (Exception error)
            {
                failed++;
                Console.Error.WriteLine($"  FEHLER {name} ({watch.Elapsed.TotalSeconds:F2} s)\n         {error}");
            }
        }
        Console.WriteLine($"CoreTests: {selected.Count - failed}/{selected.Count} Gruppen bestanden.");
        return failed == 0 ? 0 : 1;
    }
}

internal static class TestAssert
{
    internal static void That(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    internal static async Task ThrowsAsync<T>(Func<Task> action, string message) where T : Exception
    {
        try { await action(); }
        catch (T) { return; }
        throw new InvalidOperationException(message);
    }

    internal static void Throws<T>(Action action, string message) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new InvalidOperationException(message);
    }
}
