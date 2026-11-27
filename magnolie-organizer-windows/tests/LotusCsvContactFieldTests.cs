using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class LotusCsvContactFieldTests
{
    private static string[] Rows(JsonArray values, params string[] fields) => values.OfType<JsonObject>()
        .Select(value => JsonSerializer.Serialize(fields.Select(field => value[field]?.ToString() ?? "")
            .Append(string.Join(',', (value["typen"] as JsonArray ?? []).Select(type => type!.ToString()).Order(StringComparer.Ordinal)))))
        .Order(StringComparer.Ordinal).ToArray();

    internal static Task RunAsync()
    {
        const string relative = "contracts/lotus-csv-contact-fields.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!["cases"]!.AsArray();
        var failures = new List<string>();
        foreach (var vector in vectors.OfType<JsonObject>())
        {
            var id = vector["id"]!.ToString();
            void Check(bool passed, string message) { if (!passed) failures.Add(id + ": " + message); }
            string Csv(JsonNode? field) => "\"" + field!.ToString().Replace("\"", "\"\"") + "\"";
            var raw = Encoding.UTF8.GetBytes(string.Join(';', vector["headers"]!.AsArray().Select(Csv)) + "\r\n" +
                string.Join(';', vector["row"]!.AsArray().Select(Csv)) + "\r\n");
            var result = ExchangeCodec.ParseImport(raw, "lotus", "owned-contacts.csv");
            Check(result.Uebersprungen == 0 && result.Kontakte.Count == 1, "CSV record count changed");
            if (result.Kontakte.Count != 1) continue;
            Check(JsonNode.DeepEquals(result.Kontakte, ExchangeCodec.ParseImport(raw, "vcf", "owned-contacts.csv").Kontakte), "Contact-file import disagrees with Lotus import");
            var contact = result.Kontakte[0]!.AsObject();
            for (var cycle = 0; cycle < 3; cycle++)
            {
                Check(contact["vorname"]!.ToString() == "Synthetic" && contact["nachname"]!.ToString() == "CSV", "Contact name changed");
                Check(Rows(contact["telefone"]!.AsArray(), "wert").SequenceEqual(Rows(vector["phones"]!.AsArray(), "wert")), "Phone values or roles changed");
                var addresses = contact["anschriften"]!.AsArray();
                Check(Rows(addresses, "strasse", "plz", "ort", "land").SequenceEqual(Rows(vector["addresses"]!.AsArray(), "strasse", "plz", "ort", "land")), "Address lost, fabricated or assigned to another role");
                if (addresses.Count > 0)
                    Check(new[] { "strasse", "plz", "ort" }.All(field => contact[field]!.ToString() == addresses[0]![field]!.ToString()), "Legacy address fields combine different locations");
                var exported = RecordExportFile.Convert("vcf-adressen", JsonSerializer.SerializeToElement(new JsonArray(contact.DeepClone())));
                Check(exported.Count == 1 && exported.Skipped == 0, "VCF export lost the contact");
                var reread = ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(exported.Text), "vcf", "owned.vcf");
                Check(reread.Kontakte.Count == 1 && reread.Uebersprungen == 0, "VCF import lost the contact");
                contact = reread.Kontakte.Single()!.AsObject();
            }
        }
        TestAssert.That(failures.Count == 0, string.Join("\n", failures));
        return Task.CompletedTask;
    }
}
