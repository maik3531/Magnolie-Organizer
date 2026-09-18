using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

internal sealed class WindowsContactStore : IContactRemote
{
    private sealed record ContactPhone(string Value, bool Mobile);
    private const int MaxContactBytes = 2 * 1024 * 1024;
    private static readonly XNamespace ContactNs = "http://schemas.microsoft.com/Contact";
    private static readonly XNamespace MagnolieNs = "https://magnolie-organizer.invalid/contact-sync/1";
    private readonly string directory;
    private readonly Action<string>? mutationCheckpoint;

    internal WindowsContactStore(string directory, Action<string>? mutationCheckpoint = null)
    { this.directory = directory; this.mutationCheckpoint = mutationCheckpoint; }

    internal static string SafeFileStem(string value)
    {
        var invalid = Path.GetInvalidFileNameChars().Concat(new[] { '<', '>', ':', '"', '/', '\\', '|', '?', '*' }).ToHashSet();
        var clean = new string(value.Normalize().Where(character => !char.IsControl(character) && !invalid.Contains(character)).ToArray()).Trim().Trim('.');
        while (clean.Contains("  ", StringComparison.Ordinal)) clean = clean.Replace("  ", " ", StringComparison.Ordinal);
        return clean.Length == 0 ? "Kontakt" : clean[..Math.Min(clean.Length, 80)];
    }

    internal static string StableImportUid(string sourceId, string embeddedUid)
    {
        if (ValidUid(embeddedUid)) return embeddedUid;
        var source = "windows-contact\0" + sourceId.Normalize(NormalizationForm.FormC).ToUpperInvariant();
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(source))).ToLowerInvariant();
        return $"urn:magnolie:import:windows-contact:{digest}";
    }

    internal string ImportUid(RemoteContact contact)
    {
        _ = SafeMappedPath(contact.Id);
        return StableImportUid(contact.Id, ContactFields.Text(contact.Data, "uid"));
    }

    internal static JsonObject Parse(string xml)
    {
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaxContactBytes };
        using var reader = XmlReader.Create(new StringReader(xml), settings);
        var document = XDocument.Load(reader, LoadOptions.None);
        if (document.Root?.Name != ContactNs + "Contact") throw new XmlException();
        string First(string name) => document.Descendants().FirstOrDefault(node => node.Name.LocalName == name)?.Value.Trim() ?? "";
        var nameNode = document.Descendants(ContactNs + "Name").FirstOrDefault();
        string Name(string name) => nameNode?.Element(ContactNs + name)?.Value.Trim() ?? "";
        var nameParts = new[] { Name("FamilyName"), Name("GivenName"), Name("MiddleName"),
            Name("Title").Length > 0 ? Name("Title") : Name("Prefix"), Name("Suffix") };
        var rawNames = document.Descendants(MagnolieNs + "VCardName").Select(node => node.Value).ToArray();
        if (!ExchangeCodec.VCardNameParts(rawNames).SequenceEqual(nameParts))
            rawNames = ["N:" + string.Join(';', nameParts.Select(NameEscape))];
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
                ["region"] = Field("Region"), ["land"] = Field("Country"), ["typen"] = new JsonArray(JsonValue.Create("HOME")) };
        }).Where(address => address.Any(pair => pair.Key != "typen" && pair.Value?.GetValue<string>().Length > 0)).ToArray();
        var firstAddress = addresses.FirstOrDefault() ?? new JsonObject();
        var birthday = document.Descendants().FirstOrDefault(node => node.Name.LocalName == "Date" &&
            node.Descendants().Any(child => child.Name.LocalName == "Label" && child.Value.Contains("Birthday", StringComparison.OrdinalIgnoreCase)))?
            .Descendants().FirstOrDefault(node => node.Name.LocalName == "Value")?.Value ?? First("Birthday");
        var magnolieBirthday = document.Descendants(MagnolieNs + "Birthday").FirstOrDefault()?.Value.Trim() ?? "";
        var anniversary = document.Descendants(MagnolieNs + "Anniversary").FirstOrDefault()?.Value.Trim() ?? "";
        var birthdayValue = NormalizeDate(magnolieBirthday.Length > 0 ? magnolieBirthday : birthday);
        var anniversaryValue = NormalizeDate(anniversary);
        var result = new JsonObject
        {
            ["vorname"] = nameParts[1], ["nachname"] = nameParts[0], ["firma"] = First("Company").Length > 0 ? First("Company") : First("CompanyName"),
            ["anzeigename"] = Name("FormattedName"),
            ["vcardRoundtrip"] = new JsonArray(rawNames.Select(line => (JsonNode?)line).ToArray()),
            ["strasse"] = ContactFields.Text(firstAddress, "strasse"), ["plz"] = ContactFields.Text(firstAddress, "plz"), ["ort"] = ContactFields.Text(firstAddress, "ort"), ["land"] = ContactFields.Text(firstAddress, "land"),
            ["anschriften"] = new JsonArray(addresses.Select(address => (JsonNode)address).ToArray()),
            ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(value => JsonValue.Create(value)).ToArray()),
            ["telefon"] = phones.FirstOrDefault(phone => !phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase))?.Value ?? "",
            ["mobil"] = phones.FirstOrDefault(phone => phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase))?.Value ?? "",
            ["telefone"] = new JsonArray(phones.Select(phone => (JsonNode)new JsonObject { ["wert"] = phone.Value,
                ["typen"] = new JsonArray(JsonValue.Create(phone.Label.Contains("mobile", StringComparison.OrdinalIgnoreCase) ? "CELL" : "VOICE")) }).ToArray()),
            ["geburtstag"] = birthdayValue, ["geburtstagJahrUnbekannt"] = birthdayValue.StartsWith("--", StringComparison.Ordinal),
            ["jubilaeum"] = anniversaryValue, ["jubilaeumJahrUnbekannt"] = anniversaryValue.StartsWith("--", StringComparison.Ordinal),
            ["notiz"] = First("Notes")
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
        var fullName = ContactFields.Text(contact, "anzeigename");
        if (!contact.ContainsKey("anzeigename")) fullName = (ContactFields.Text(contact, "vorname") + " " + ContactFields.Text(contact, "nachname")).Trim();
        var rawNames = (contact["vcardRoundtrip"] as JsonArray ?? []).OfType<JsonValue>()
            .Select(value => value.ToString()).Where(line => Regex.IsMatch(line, @"^(?:[A-Za-z0-9-]+\.)?(?:N|FN)[;:]", RegexOptions.IgnoreCase)).ToArray();
        var nameParts = ExchangeCodec.VCardNameParts(rawNames);
        var birthday = NormalizeDate(ContactFields.Text(contact, "geburtstag"), contact["geburtstagJahrUnbekannt"]?.GetValue<bool>() == true);
        var anniversary = NormalizeDate(ContactFields.Text(contact, "jubilaeum"), contact["jubilaeumJahrUnbekannt"]?.GetValue<bool>() == true);
        var canonicalBirthday = ExchangeCodec.TryParseCanonicalDate(birthday, out var fullBirthday, out _, out _);
        var root = new XElement(ContactNs + "Contact", new XAttribute(XNamespace.Xmlns + "c", ContactNs), new XAttribute(XNamespace.Xmlns + "m", MagnolieNs), new XAttribute(ContactNs + "Version", "1"),
            new XElement(ContactNs + "Extended", new XElement(MagnolieNs + "MagnolieUid", uid),
                rawNames.Select(line => new XElement(MagnolieNs + "VCardName", line)),
                canonicalBirthday && fullBirthday is null ? new XElement(MagnolieNs + "Birthday", birthday) : null,
                anniversary.Length > 0 ? new XElement(MagnolieNs + "Anniversary", anniversary) : null),
            new XElement(ContactNs + "NameCollection", new XElement(ContactNs + "Name",
                new XElement(ContactNs + "FormattedName", fullName), new XElement(ContactNs + "GivenName", ContactFields.Text(contact, "vorname")), new XElement(ContactNs + "FamilyName", ContactFields.Text(contact, "nachname")),
                new XElement(ContactNs + "MiddleName", nameParts[2]), new XElement(ContactNs + "Title", nameParts[3]), new XElement(ContactNs + "Suffix", nameParts[4]))),
            new XElement(ContactNs + "PositionCollection", new XElement(ContactNs + "Position", new XElement(ContactNs + "Company", ContactFields.Text(contact, "firma")))),
            new XElement(ContactNs + "EmailAddressCollection", emails.Select(email => new XElement(ContactNs + "EmailAddress", new XElement(ContactNs + "Address", email)))),
            new XElement(ContactNs + "PhoneNumberCollection", phones.Select(phone => new XElement(ContactNs + "PhoneNumber", new XElement(ContactNs + "Number", phone.Value), new XElement(ContactNs + "Label", phone.Mobile ? "Mobile" : "Personal")))),
            new XElement(ContactNs + "PhysicalAddressCollection", addresses.Select(address => new XElement(ContactNs + "PhysicalAddress",
                new XElement(ContactNs + "Street", ContactFields.Text(address, "strasse")), new XElement(ContactNs + "PostalCode", ContactFields.Text(address, "plz")),
                new XElement(ContactNs + "Locality", ContactFields.Text(address, "ort")), new XElement(ContactNs + "Region", ContactFields.Text(address, "region")), new XElement(ContactNs + "Country", ContactFields.Text(address, "land"))))),
            canonicalBirthday && fullBirthday is not null ? new XElement(ContactNs + "DateCollection", new XElement(ContactNs + "Date", new XElement(ContactNs + "Value", birthday),
                new XElement(ContactNs + "LabelCollection", new XElement(ContactNs + "Label", "Birthday")))) : null,
            new XElement(ContactNs + "Notes", ContactFields.Text(contact, "notiz")));
        return new XDocument(new XDeclaration("1.0", "utf-8", null), root).ToString();
    }

    public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(directory);
        RecoverUpdates();
        var result = new List<RemoteContact>();
        var files = Directory.GetFiles(directory, "*.contact", SearchOption.TopDirectoryOnly).Order(StringComparer.Ordinal).ToArray();
        foreach (var path in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException();
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            var xml = ReadContact(stream);
            var data = Parse(xml);
            var uid = ReadMagnolieUid(xml); var id = Path.GetFileName(path);
            data["uid"] = StableImportUid(id, uid);
            result.Add(new RemoteContact(id, Revision(xml), new DateTimeOffset(File.GetLastWriteTimeUtc(path)).ToUnixTimeMilliseconds(), data, uid.Length > 0));
        }
        // Never expose the publication gap of another writer as a remote deletion.
        if (!files.SequenceEqual(Directory.GetFiles(directory, "*.contact", SearchOption.TopDirectoryOnly).Order(StringComparer.Ordinal)) ||
            Directory.EnumerateFiles(directory, "*.contact.magnolie-update").Any()) throw new IOException();
        return Task.FromResult<IReadOnlyList<RemoteContact>>(result);
    }

    public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(directory);
        RecoverUpdates();
        var display = (ContactFields.Text(contact, "vorname") + " " + ContactFields.Text(contact, "nachname")).Trim();
        if (display.Length == 0) display = ContactFields.Text(contact, "anzeigename");
        if (display.Length == 0) display = ContactFields.Text(contact, "firma");
        var suffix = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(uid)))[..10].ToLowerInvariant();
        var path = Path.Combine(directory, $"{SafeFileStem(display)}-{suffix}.contact");
        cancellationToken.ThrowIfCancellationRequested();
        var xml = Serialize(contact, uid);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".prepared";
        try { WriteAtomic(temporary, xml); File.Move(temporary, path, false); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
        return Task.FromResult(Describe(path, xml, true));
    }

    public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        var path = SafeMappedPath(remote.Id);
        cancellationToken.ThrowIfCancellationRequested();
        RecoverUpdates();
        var xml = Serialize(contact, uid);
        Mutate(path, remote.ETag, uid, xml);
        return Task.FromResult(Describe(path, xml, true));
    }

    public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken)
    {
        var path = SafeMappedPath(remote.Id);
        cancellationToken.ThrowIfCancellationRequested();
        RecoverUpdates();
        if (!File.Exists(path))
        {
            if (File.Exists(path + ".magnolie-update") || File.Exists(path)) throw new IOException();
            return Task.CompletedTask;
        }
        Mutate(path, remote.ETag, uid, null);
        return Task.CompletedTask;
    }

    private string SafeMappedPath(string id)
    {
        if (Path.GetFileName(id) != id || !id.EndsWith(".contact", StringComparison.OrdinalIgnoreCase)) throw new IOException("Ungültige Kontaktdatei-Zuordnung.");
        return Path.Combine(directory, id);
    }
    private static string NormalizeDate(string value, bool unknownYear = false)
    {
        if (ExchangeCodec.TryParseCanonicalDate(value, out var full, out var month, out var day))
            return full is null || unknownYear ? $"--{month:00}-{day:00}" : full.Value.ToString("yyyy-MM-dd");
        return DateTimeOffset.TryParse(value, out var date)
            ? unknownYear ? $"--{date.Month:00}-{date.Day:00}" : date.ToString("yyyy-MM-dd") : "";
    }
    private static string ReadMagnolieUid(string xml)
    {
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaxContactBytes };
        using var reader = XmlReader.Create(new StringReader(xml), settings); var document = XDocument.Load(reader, LoadOptions.None);
        return document.Descendants(MagnolieNs + "MagnolieUid").FirstOrDefault()?.Value ?? "";
    }
    private static bool ValidUid(string value) => value.Length > 0 && value.EnumerateRunes().Count() <= 128 &&
        !value.EnumerateRunes().Any(rune => rune.Value < 32);
    private static string NameEscape(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n")
        .Replace("\n", "\\n").Replace(";", "\\;").Replace(",", "\\,");
    private static string Revision(string xml) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(xml)));
    private static string ReadContact(FileStream stream)
    {
        if (stream.Length > MaxContactBytes) throw new IOException();
        using var reader = new StreamReader(stream, Encoding.UTF8, true, 4096, leaveOpen: true);
        return reader.ReadToEnd();
    }
    private static RemoteContact Describe(string path, string xml, bool owned)
    {
        var data = Parse(xml);
        data["uid"] = StableImportUid(Path.GetFileName(path), ReadMagnolieUid(xml));
        return new RemoteContact(Path.GetFileName(path), Revision(xml),
            new DateTimeOffset(File.GetLastWriteTimeUtc(path)).ToUnixTimeMilliseconds(), data, owned);
    }

    // Park the exact locked file, then publish without replacement. An external
    // creator in the name gap wins; its file is never overwritten. The parked
    // preimage is also the recovery record if publication is interrupted.
    private void Mutate(string path, string expected, string uid, string? xml)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException();
        var parked = path + (xml is null ? ".magnolie-delete" : ".magnolie-update");
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".prepared";
        using var handle = OperatingSystem.IsWindows()
            ? CreateFile(path, 0x80010000, 1, IntPtr.Zero, 3, 128, IntPtr.Zero)
            : File.OpenHandle(path, FileMode.Open, FileAccess.Read, FileShare.None);
        if (handle.IsInvalid) throw new IOException();
        using var stream = new FileStream(handle, FileAccess.Read);
        var previous = ReadContact(stream);
        if (expected.Length == 0 || Revision(previous) != expected) throw new IOException();
        if (xml is null && ReadMagnolieUid(previous) != uid) throw new IOException();
        mutationCheckpoint?.Invoke("validated");
        try
        {
            if (xml is not null) WriteAtomic(temporary, xml);
            if (OperatingSystem.IsWindows())
            {
                var name = Encoding.Unicode.GetBytes(Path.GetFullPath(parked));
                var lengthOffset = IntPtr.Size * 2;
                var nameOffset = lengthOffset + 4;
                var infoSize = nameOffset + name.Length + 2;
                var info = Marshal.AllocHGlobal(infoSize);
                try
                {
                    Marshal.WriteInt32(info, 0, 0);
                    Marshal.WriteIntPtr(info, IntPtr.Size, IntPtr.Zero);
                    Marshal.WriteInt32(info, lengthOffset, name.Length);
                    Marshal.Copy(name, 0, info + nameOffset, name.Length);
                    // Win32 path conversion needs a NUL even though FileNameLength excludes it.
                    Marshal.WriteInt16(info, nameOffset + name.Length, 0);
                    if (!SetFileInformationByHandle(handle, 3, info, (uint)infoSize))
                        throw new IOException(null, new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()));
                }
                finally { Marshal.FreeHGlobal(info); }
            }
            else File.Move(path, parked, false);
            mutationCheckpoint?.Invoke("parked");
            if (xml is not null) File.Move(temporary, path, false);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
        stream.Dispose();
        File.Delete(parked);
    }

    private void RecoverUpdates()
    {
        if (!Directory.Exists(directory)) return;
        foreach (var parked in Directory.EnumerateFiles(directory, "*.contact.magnolie-update"))
        {
            var path = parked[..^".magnolie-update".Length];
            // A live Windows mutation denies delete sharing on the parked file.
            if (!File.Exists(path)) File.Move(parked, path, false);
            else File.Delete(parked);
        }
        foreach (var parked in Directory.EnumerateFiles(directory, "*.contact.magnolie-delete")) File.Delete(parked);
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateFileW")]
    private static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetFileInformationByHandle(SafeFileHandle file, int kind, IntPtr info, uint size);
    private static void WriteAtomic(string path, string content)
    {
        if (Encoding.UTF8.GetByteCount(content) > MaxContactBytes) throw new IOException("Die Kontaktdatei ist größer als 2 MiB.");
        new AtomicStore().Write(path, content);
    }
}
