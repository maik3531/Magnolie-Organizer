using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class KdeContactImport
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static readonly Regex Fingerprint = new("^[a-fA-F0-9]{64}$", RegexOptions.CultureInvariant);
    private static readonly Regex TransportProperty = new("^(?:[^:;.]+\\.)?(?:PHOTO|UID|REV|VERSION|BEGIN|END|PRODID)[;:]", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    internal static string Binding(string deviceId, string fingerprint, string uid, string provider = "kde")
    {
        if (provider is not ("kde" or "notes")) throw new InvalidDataException("invalid_contact_source");
        if (deviceId.Length is < 1 or > 200 || deviceId.Any(char.IsControl) || fingerprint.Length != 64 || !Fingerprint.IsMatch(fingerprint) ||
            uid.Length is < 1 or > 1024 || uid.Any(char.IsControl)) throw new InvalidDataException("invalid_contact_source");
        var bytes = Utf8.GetBytes(provider + "-contact-v1\0" + deviceId + "\0" + fingerprint.ToLowerInvariant() + "\0" + uid);
        return "urn:magnolie:import:" + provider + ":" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    internal static void Project(JsonObject result, string expectedDevice, IReadOnlyCollection<string> requested, string provider = "kde")
    {
        var device = result["device_id"]!.GetValue<string>();
        var fingerprint = result["fingerprint"]!.GetValue<string>();
        if (device != expectedDevice || result["contacts"] is not JsonArray cards || cards.Count != requested.Count)
            throw new InvalidDataException("incomplete_contact_batch");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in cards)
        {
            var item = node!.AsObject();
            var uid = item["uid"]!.GetValue<string>();
            if (!requested.Contains(uid) || !seen.Add(uid)) throw new InvalidDataException("invalid_contact_batch");
            var parsed = ExchangeCodec.ParseVCard(item["vcard"]!.GetValue<string>());
            if (parsed.Kontakte.Count != 1 || parsed.Uebersprungen != 0) throw new InvalidDataException("invalid_contact_vcard");
            var contact = parsed.Kontakte[0]!.AsObject();
            var selected = new JsonObject();
            foreach (var field in ContactFields.Names.Concat(["vcardParameter"]).Distinct())
                if (field != "foto" && contact.ContainsKey(field)) selected[field] = contact[field]?.DeepClone();
            selected["vcardRoundtrip"] = new JsonArray((selected["vcardRoundtrip"] as JsonArray ?? [])
                .Select(value => value!.GetValue<string>()).Where(line => !TransportProperty.IsMatch(line))
                .Select(line => JsonValue.Create(line)).ToArray());
            if (selected["vcardParameter"] is JsonObject parameters)
                foreach (var name in parameters.Select(pair => pair.Key).Where(name => TransportProperty.IsMatch(name + ":")).ToArray())
                    parameters.Remove(name);
            item.Remove("vcard");
            item["kontakt"] = selected;
            item["bindung"] = Binding(device, fingerprint, uid, provider);
        }
    }
}
