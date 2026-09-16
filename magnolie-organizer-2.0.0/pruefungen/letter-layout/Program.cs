using System.Globalization;
using System.Text.Json;
using MagnolieOrganizer.Windows;

// Isolated exporter host: no application startup, user settings or file opening.
using var input = JsonDocument.Parse(File.ReadAllText(args[0]));
using (var oversized = JsonDocument.Parse(JsonSerializer.Serialize(new { anzeigename = new string('W', 160) })))
{
    try
    {
        DocumentExportService.CreateLetter(oversized.RootElement);
        throw new InvalidOperationException("Oversized recipient was accepted.");
    }
    catch (ArgumentException) { }
}
foreach (var (contactJson, sender) in new[]
{
    (JsonSerializer.Serialize(new { firma = string.Join("\n", Enumerable.Repeat("Organization", 7)) }), ""),
    ("{\"firma\":\"Recipient\"}", string.Join("\n", Enumerable.Repeat("Sender", 6)))
})
{
    using var oversized = JsonDocument.Parse(contactJson);
    try
    {
        DocumentExportService.CreateLetter(oversized.RootElement, sender);
        throw new InvalidOperationException("Oversized multiline address was accepted.");
    }
    catch (ArgumentException) { }
    DocumentExportService.CreateLetter(oversized.RootElement, sender, "compact");
}
foreach (var item in input.RootElement.EnumerateArray())
{
    var culture = item.GetProperty("culture").GetString()!;
    CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
    NativeLocalization.SetLanguage(culture);
    var contact = item.GetProperty("contact");
    var sender = item.GetProperty("sender").GetString()!;
    var bytes = item.TryGetProperty("layout", out var layout)
        ? DocumentExportService.CreateLetter(contact, sender, layout.GetString()!)
        : DocumentExportService.CreateLetter(contact, sender);
    File.WriteAllBytes(Path.Combine(args[1], item.GetProperty("id").GetString()! + "-windows.odt"), bytes);
}

namespace MagnolieOrganizer.Windows
{
    internal static class RegionalSettings
    {
        internal static string LanguagePreference() => "en";
    }
}
