using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeContactImportTests
{
    private const string Card = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:untrusted-vcard-uid\r\n" +
        "FN:Sample Person\r\nN:Person;Sample;;;\r\nORG:Example\r\n" +
        "ADR;TYPE=HOME:;;Example Street;Example City;;12345;Germany\r\n" +
        "TEL:+491701234567\r\nEMAIL:fixture@example.org\r\nNOTE:Keep this note\r\nBDAY:2000-02-29\r\n" +
        "PHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgo=\r\nX-CUSTOM:Preserve extension\r\nEND:VCARD\r\n";

    private static JsonObject Batch() => new()
    {
        ["device_id"] = "paired", ["fingerprint"] = new string('a', 64),
        ["contacts"] = new JsonArray(new JsonObject { ["uid"] = "card", ["vcard"] = Card })
    };

    internal static Task RunAsync()
    {
        var fingerprint = new string('a', 64);
        var expected = "urn:magnolie:import:kde:" + Convert.ToHexString(SHA256.HashData(
            Encoding.UTF8.GetBytes("kde-contact-v1\0paired\0" + fingerprint + "\0card"))).ToLowerInvariant();
        TestAssert.That(KdeContactImport.Binding("paired", fingerprint.ToUpperInvariant(), "card") == expected,
            "Certificate casing changed the source binding.");
        TestAssert.That(new[] { expected, KdeContactImport.Binding("other", fingerprint, "card"),
            KdeContactImport.Binding("paired", new string('b', 64), "card"),
            KdeContactImport.Binding("paired", fingerprint, "other") }.Distinct().Count() == 4,
            "Distinct contact sources shared a binding.");
        foreach (var (pin, uid) in new[] { (fingerprint + "\n", "card"), (fingerprint, "card\0other"),
            (fingerprint, string.Concat(Enumerable.Repeat("😀", 513))) })
            Reject(() => KdeContactImport.Binding("paired", pin, uid));

        var result = Batch();
        KdeContactImport.Project(result, "paired", ["card"]);
        var item = result["contacts"]![0]!.AsObject();
        var contact = item["kontakt"]!.AsObject();
        TestAssert.That(contact["vorname"]!.GetValue<string>() == "Sample" &&
            contact["nachname"]!.GetValue<string>() == "Person" &&
            contact["firma"]!.GetValue<string>() == "Example" &&
            contact["notiz"]!.GetValue<string>() == "Keep this note" &&
            contact["geburtstag"]!.GetValue<string>() == "2000-02-29" &&
            contact["anschriften"]![0]!["land"]!.GetValue<string>() == "Germany", "Contact fields were lost.");
        TestAssert.That(!new[] { "foto", "fotoManuell", "uid", "id", "importBindungen" }.Any(contact.ContainsKey) &&
            !item.ContainsKey("vcard") && item["bindung"]!.GetValue<string>() == expected, "Photo or foreign identity escaped projection.");
        var roundtrip = contact["vcardRoundtrip"]!.AsArray().Select(line => line!.GetValue<string>()).ToArray();
        TestAssert.That(roundtrip.Any(line => line.Contains("X-CUSTOM:Preserve extension")) &&
            roundtrip.All(line => !line.Contains("PHOTO") && !line.Contains("UID:")), "Roundtrip projection lost extensions or retained transport data.");

        foreach (var kind in new[] { "missing", "duplicate", "unexpected", "device", "vcard", "fingerprint" })
        {
            result = Batch();
            var requested = new List<string> { "card" };
            if (kind == "missing") requested.Add("missing");
            if (kind == "duplicate") { requested.Add("other"); result["contacts"]!.AsArray().Add(result["contacts"]![0]!.DeepClone()); }
            if (kind == "unexpected") result["contacts"]![0]!["uid"] = "other";
            if (kind == "device") result["device_id"] = "other";
            if (kind == "vcard") result["contacts"]![0]!["vcard"] = Card + Card;
            if (kind == "fingerprint") result["fingerprint"] = "invalid";
            Reject(() => KdeContactImport.Project(result, "paired", requested));
        }
        return Task.CompletedTask;
    }

    private static void Reject(Action action)
    {
        try { action(); }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("Invalid contact source/batch was accepted.");
    }
}
