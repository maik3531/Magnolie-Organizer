using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class WindowsContactStore : IContactRemote
{
    private sealed record ContactPhone(string Value, bool Mobile);
    private const int MaxContactBytes = 2 * 1024 * 1024;
    private static readonly XNamespace ContactNs = "http://schemas.microsoft.com/Contact";
    private static readonly XNamespace MagnolieNs = "https://magnolie-organizer.invalid/contact-sync/1";
    private readonly string directory;

    internal WindowsContactStore(string directory) => this.directory = directory;

    internal static string SafeFileStem(string value)
    {
        var invalid = Path.GetInvalidFileNameChars().Concat(new[] { '<', '>', ':', '"', '/', '\\', '|', '?', '*' }).ToHashSet();
        var clean = new string(value.Normalize().Where(character => !char.IsControl(character) && !invalid.Contains(character)).ToArray()).Trim().Trim('.');
        while (clean.Contains("  ", StringComparison.Ordinal)) clean = clean.Replace("  ", " ", StringComparison.Ordinal);
        return clean.Length == 0 ? "Kontakt" : clean[..Math.Min(clean.Length, 80)];
    }

    internal static JsonObject Parse(string xml)
    {
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaxContactBytes };
        using var reader = XmlReader.Create(new StringReader(xml), settings);
        var document = XDocument.Load(reader, LoadOptions.None);
        string First(string name) => document.Descendants().FirstOrDefault(node => node.Name.LocalName == name)?.Value.Trim() ?? "";
        var emails = document.Descendants().Where(node => node.Name.LocalName == "EmailAddress")
            .Select(node => node.Descendants().FirstOrDefault(child => child.Name.LocalName == "Address")?.Value.Trim() ?? "").Where(value => value.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        var phones = document.Descendants().Where(node => node.Name.LocalName == "PhoneNumber").Select(node => new
        {
            Value = node.Descendants().FirstOrDefault(child => child.Name.LocalName == "Number")?.Value.Trim() ?? "",
            Label = node.Descendants().FirstOrDefault(child => child.Name.LocalName is "Label" or "PhoneNumberType")?.Value.Trim() ?? ""
        }).Where(phone => phone.Value.Length > 0).ToArray();
        var addresses = document.Descendants().Where(node => node.Name.LocalName == "PhysicalAddress").Select(address =>
        {
            string Field(string name) => address.Descendants().FirstOrDefault(node => node.Name.LocalName == name)?.Value.Trim() ?? "";
            return new JsonObject { ["strasse"] = Field("Street"), ["plz"] = Field("PostalCode"), ["ort"] = Field("Locality"),
                ["land"] = Field("Country"), ["typen"] = new JsonArray(JsonValue.Create("HOME")) };
        }).Where(address => address.Any(pair => pair.Key != "typen" && pair.Value?.GetValue<string>().Length > 0)).ToArray();
        var firstAddress = addresses.FirstOrDefault() ?? new JsonObject();
        var birthday = document.Descendants().FirstOrDefault(node => node.Name.LocalName == "Date" &&
            node.Descendants().Any(child => child.Name.LocalName == "Label" && child.Value.Contains("Birthday", StringComparison.OrdinalIgnoreCase)))?
            .Descendants().FirstOrDefault(node => node.Name.LocalName == "Value")?.Value ?? First("Birthday");
        var result = new JsonObject
        {
            ["vorname"] = First("GivenName"), ["nachname"] = First("FamilyName"), ["firma"] = First("Company").Length > 0 ? First("Company") : First("CompanyName"),
            ["strasse"] = ContactFields.Text(firstAddress, "strasse"), ["plz"] = ContactFields.Text(firstAddress, "plz"), ["ort"] = ContactFields.Text(firstAddress, "ort"), ["land"] = ContactFields.Text(firstAddress, "land"),
            ["anschriften"] = new JsonArray(addresses.Select(address => (JsonNode)address).ToArray()),
            ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(value => JsonValue.Create(value)).ToArray()),
            ["telefon"] = phones.FirstOrDefault(phone => !phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase))?.Value ?? "",
            ["mobil"] = phones.FirstOrDefault(phone => phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase))?.Value ?? "",
            ["telefone"] = new JsonArray(phones.Select(phone => (JsonNode)new JsonObject { ["wert"] = phone.Value,
                ["typen"] = new JsonArray(JsonValue.Create(phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase) ? "CELL" : "VOICE")) }).ToArray()),
            ["geburtstag"] = NormalizeBirthday(birthday), ["notiz"] = First("Notes")
        };
        return result;
    }

    internal static string Serialize(JsonObject contact, string uid)
    {
        var emails = contact["emails"] is JsonArray emailArray ? emailArray.Select(node => node?.GetValue<string>() ?? "").Where(value => value.Length > 0) : new[] { ContactFields.Text(contact, "email") }.Where(value => value.Length > 0);
        var phones = contact["telefone"] is JsonArray phoneArray ? phoneArray.OfType<JsonObject>().Select(phone => new ContactPhone(
            ContactFields.Text(phone, "wert"), phone["typen"] is JsonArray types && types.Any(type => (type?.GetValue<string>() ?? "").Equals("CELL", StringComparison.OrdinalIgnoreCase))))
            .Where(phone => phone.Value.Length > 0).ToList() : new List<ContactPhone>();
        if (!phones.Any(phone => phone.Value == ContactFields.Text(contact, "telefon")) && ContactFields.Text(contact, "telefon").Length > 0) phones.Add(new ContactPhone(ContactFields.Text(contact, "telefon"), false));
        if (!phones.Any(phone => phone.Value == ContactFields.Text(contact, "mobil")) && ContactFields.Text(contact, "mobil").Length > 0) phones.Add(new ContactPhone(ContactFields.Text(contact, "mobil"), true));
        var addresses = contact["anschriften"] is JsonArray addressArray ? addressArray.OfType<JsonObject>().ToList() : new List<JsonObject>();
        if (addresses.Count == 0) addresses.Add(contact);
        var fullName = (ContactFields.Text(contact, "vorname") + " " + ContactFields.Text(contact, "nachname")).Trim();
        var birthday = ContactFields.Text(contact, "geburtstag");
        var root = new XElement(ContactNs + "Contact", new XAttribute(XNamespace.Xmlns + "c", ContactNs), new XAttribute(XNamespace.Xmlns + "m", MagnolieNs), new XAttribute(ContactNs + "Version", "1"),
            new XElement(ContactNs + "Extended", new XElement(MagnolieNs + "MagnolieUid", uid)),
            new XElement(ContactNs + "NameCollection", new XElement(ContactNs + "Name",
                new XElement(ContactNs + "FormattedName", fullName), new XElement(ContactNs + "GivenName", ContactFields.Text(contact, "vorname")), new XElement(ContactNs + "FamilyName", ContactFields.Text(contact, "nachname")))),
            new XElement(ContactNs + "PositionCollection", new XElement(ContactNs + "Position", new XElement(ContactNs + "Company", ContactFields.Text(contact, "firma")))),
            new XElement(ContactNs + "EmailAddressCollection", emails.Select(email => new XElement(ContactNs + "EmailAddress", new XElement(ContactNs + "Address", email)))),
            new XElement(ContactNs + "PhoneNumberCollection", phones.Select(phone => new XElement(ContactNs + "PhoneNumber", new XElement(ContactNs + "Number", phone.Value), new XElement(ContactNs + "Label", phone.Mobile ? "Mobile" : "Personal")))),
            new XElement(ContactNs + "PhysicalAddressCollection", addresses.Select(address => new XElement(ContactNs + "PhysicalAddress",
                new XElement(ContactNs + "Street", ContactFields.Text(address, "strasse")), new XElement(ContactNs + "PostalCode", ContactFields.Text(address, "plz")),
                new XElement(ContactNs + "Locality", ContactFields.Text(address, "ort")), new XElement(ContactNs + "Country", ContactFields.Text(address, "land"))))),
            birthday.Length > 0 ? new XElement(ContactNs + "DateCollection", new XElement(ContactNs + "Date", new XElement(ContactNs + "Value", birthday),
                new XElement(ContactNs + "LabelCollection", new XElement(ContactNs + "Label", "Birthday")))) : null,
            new XElement(ContactNs + "Notes", ContactFields.Text(contact, "notiz")));
        return new XDocument(new XDeclaration("1.0", "utf-8", null), root).ToString();
    }

    public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(directory);
        var result = new List<RemoteContact>();
        foreach (var path in Directory.EnumerateFiles(directory, "*.contact", SearchOption.TopDirectoryOnly))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var info = new FileInfo(path); if (info.Length > MaxContactBytes || (info.Attributes & FileAttributes.ReparsePoint) != 0) continue;
                var xml = File.ReadAllText(path, Encoding.UTF8); var data = Parse(xml);
                var uid = ReadMagnolieUid(xml); var id = Path.GetFileName(path);
                result.Add(new RemoteContact(id, $"{info.LastWriteTimeUtc.Ticks:x}-{info.Length:x}", new DateTimeOffset(info.LastWriteTimeUtc).ToUnixTimeMilliseconds(), data, uid.Length > 0));
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or XmlException) { }
        }
        return Task.FromResult<IReadOnlyList<RemoteContact>>(result);
    }

    public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(directory);
        var display = (ContactFields.Text(contact, "vorname") + " " + ContactFields.Text(contact, "nachname")).Trim();
        if (display.Length == 0) display = ContactFields.Text(contact, "firma");
        var suffix = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(uid)))[..10].ToLowerInvariant();
        var path = Path.Combine(directory, $"{SafeFileStem(display)}-{suffix}.contact");
        WriteAtomic(path, Serialize(contact, uid));
        return Task.FromResult(Describe(path, contact, true));
    }

    public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        var path = SafeMappedPath(remote.Id);
        if (!File.Exists(path)) throw new FileNotFoundException("Die zugeordnete Windows-Kontaktdatei fehlt.", path);
        WriteAtomic(path, Serialize(contact, uid));
        return Task.FromResult(Describe(path, contact, true));
    }

    public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken)
    {
        var path = SafeMappedPath(remote.Id);
        if (!File.Exists(path)) return Task.CompletedTask;
        if (ReadMagnolieUid(File.ReadAllText(path, Encoding.UTF8)) != uid) throw new IOException("Eine fremde Windows-Kontaktdatei wird nicht gelöscht.");
        File.Delete(path); return Task.CompletedTask;
    }

    private string SafeMappedPath(string id)
    {
        if (Path.GetFileName(id) != id || !id.EndsWith(".contact", StringComparison.OrdinalIgnoreCase)) throw new IOException("Ungültige Kontaktdatei-Zuordnung.");
        return Path.Combine(directory, id);
    }
    private static string NormalizeBirthday(string value) => DateTimeOffset.TryParse(value, out var date) ? date.ToString("yyyy-MM-dd") : "";
    private static string ReadMagnolieUid(string xml)
    {
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaxContactBytes };
        using var reader = XmlReader.Create(new StringReader(xml), settings); var document = XDocument.Load(reader, LoadOptions.None);
        return document.Descendants(MagnolieNs + "MagnolieUid").FirstOrDefault()?.Value ?? "";
    }
    private static RemoteContact Describe(string path, JsonObject data, bool owned) { var info = new FileInfo(path); return new RemoteContact(Path.GetFileName(path), $"{info.LastWriteTimeUtc.Ticks:x}-{info.Length:x}", new DateTimeOffset(info.LastWriteTimeUtc).ToUnixTimeMilliseconds(), data.DeepClone().AsObject(), owned); }
    private static void WriteAtomic(string path, string content)
    {
        if (Encoding.UTF8.GetByteCount(content) > MaxContactBytes) throw new IOException("Die Kontaktdatei ist größer als 2 MiB.");
        new AtomicStore().Write(path, content);
    }
}
