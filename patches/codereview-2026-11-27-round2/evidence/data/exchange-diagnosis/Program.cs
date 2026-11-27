using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

var fixturePath = Path.GetFullPath(args[0]);
var assemblyPath = typeof(ExchangeCodec).Assembly.Location;
var result = new JsonObject {
    ["fixturePath"] = fixturePath,
    ["fixtureSha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(fixturePath))),
    ["assemblyPath"] = assemblyPath,
    ["assemblySha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))),
    ["TZ"] = Environment.GetEnvironmentVariable("TZ"),
    ["TZDIR"] = Environment.GetEnvironmentVariable("TZDIR"),
    ["localZoneId"] = TimeZoneInfo.Local.Id,
    ["localZoneDisplay"] = TimeZoneInfo.Local.DisplayName,
    ["currentCulture"] = CultureInfo.CurrentCulture.Name
};
try { result["normativeSystemZone"] = CalendarRecurrence.Zone("system").Id; }
catch (Exception error) { result["normativeSystemZoneError"] = error.ToString(); }
var text = JsonNode.Parse(File.ReadAllText(fixturePath))!["ics"]!.ToString();
var bytes = Encoding.UTF8.GetBytes(text);
var waste = ExchangeCodec.ParseWasteImport(bytes, "waste.ics");
var before = waste.ToJsonString();
var again = ExchangeCodec.ParseWasteImport(bytes, "waste (2).ics");
result["firstPayloadUnchangedAfterSecondCall"] = waste.ToJsonString() == before;
result["sameSourceIdentity"] = waste["muellQuelle"]!.ToString() == again["muellQuelle"]!.ToString();
var hazardous = waste["termine"]!.AsArray().OfType<JsonObject>().Where(t => t["titel"]!.ToString() == "Schadstoffe").ToArray();
result["wasteHazardous"] = new JsonArray(hazardous.Select(t => t.DeepClone()).ToArray());
result["hazardousCountEqualsTwo"] = hazardous.Length == 2;
try { result["allHaveEmptyTime"] = hazardous.All(t => t["zeit"]!.ToString() == ""); }
catch (Exception error) { result["allHaveEmptyTimeError"] = error.ToString(); }
try { result["firstHas1430Note"] = hazardous[0]["notiz"]!.ToString().Contains("14:30", StringComparison.Ordinal); }
catch (Exception error) { result["firstHas1430NoteError"] = error.ToString(); }
var imported = ExchangeCodec.ParseImport(bytes, "ics", "waste.ics");
result["directImportHazardous"] = new JsonArray(imported.Termine.OfType<JsonObject>()
    .Where(t => t["titel"]!.ToString() == "Schadstoffe").Select(t => t.DeepClone()).ToArray());
Console.WriteLine(result.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
