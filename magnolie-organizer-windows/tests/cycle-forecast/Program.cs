using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;
using MagnolieOrganizer.Windows.Tests;
if (args.Length == 2 && args[0] == "--vectors") {
    var vectors = JsonNode.Parse(File.ReadAllText(args[1]))!["cases"]!.AsArray();
    var output = new JsonArray();
    foreach (var item in vectors) {
        using var doc = JsonDocument.Parse(item!["data"]!.ToJsonString());
        var stats = CycleCalendar.Estimate(doc.RootElement, item["asOf"]!.GetValue<string>());
        var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
        output.Add(new JsonObject { ["name"] = item["name"]!.DeepClone(), ["stats"] = JsonSerializer.SerializeToNode(stats, options) });
    }
    Console.WriteLine(output.ToJsonString());
} else {
    await CycleForecastTests.RunAsync();
}
namespace MagnolieOrganizer.Windows {
    // The portable probe only supplies preference selection; all date/estimate/
    // reminder calculations and gettext resolution compile from product source.
    internal static class RegionalSettings { internal static string LanguagePreference() => "en"; }
}
