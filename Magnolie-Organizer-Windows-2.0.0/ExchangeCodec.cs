using System.Globalization;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal sealed record ExchangeImportResult(
    JsonArray Termine,
    JsonArray Jahrestage,
    JsonArray Geburtstage,
    JsonArray Aufgaben,
    JsonArray Kontakte,
    int Uebersprungen = 0,
    int Wiederholend = 0,
    string Bericht = "",
    JsonArray? Notizen = null)
{
    internal JsonObject ToPayload(string art, string fileName) => new()
    {
        ["art"] = art,
        ["abgebrochen"] = false,
        ["datei"] = fileName,
        ["termine"] = Termine,
        ["jahrestage"] = Jahrestage,
        ["geburtstage"] = Geburtstage,
        ["aufgaben"] = Aufgaben,
        ["kontakte"] = Kontakte,
        ["notizen"] = Notizen?.DeepClone(),
        ["uebersprungen"] = Uebersprungen,
        ["wiederholend"] = Wiederholend,
        ["bericht"] = Bericht
    };
}

internal sealed record ExchangeExportResult(string Text, int Count, int Skipped, string Bericht = "",
    int PhotoOmitted = 0, int RawOmitted = 0);

internal static partial class ExchangeCodec
{
    internal const long MaxImportBytes = 32L * 1024 * 1024;
    internal const int MaxArchiveEntries = 128;
    internal const long MaxArchiveEntryBytes = 16L * 1024 * 1024;
    internal const int MaxArchiveRatio = 200;

    internal static ExchangeImportResult ParseImport(byte[] bytes, string art, string fileName)
    {
        if (bytes.LongLength > MaxImportBytes) throw new IOException("Die Importdatei ist größer als 32 Megabyte.");
        if (bytes.Length < 4 || bytes[0] != (byte)'P' || bytes[1] != (byte)'K')
            return ParseImportEntry(bytes, art, fileName);
        var result = EmptyImport() with { Notizen = new JsonArray() }; var reports = new List<string>(); var read = 0; long total = 0;
        using var stream = new MemoryStream(bytes, false);
        using var archive = new ZipArchive(stream, ZipArchiveMode.Read, false);
        var files = archive.Entries.Where(entry => entry.Name.Length > 0).ToArray();
        if (files.Length > MaxArchiveEntries) throw new InvalidDataException("Das Archiv enthält zu viele Dateien.");
        foreach (var entry in files)
        {
            if (!SupportedArchiveEntry(art, entry.FullName)) continue;
            if (entry.Length > MaxArchiveEntryBytes) throw new InvalidDataException("Ein Archiveintrag ist zu groß.");
            if (entry.Length > 0 && (entry.CompressedLength == 0 || entry.Length > entry.CompressedLength * MaxArchiveRatio))
                throw new InvalidDataException("Das Archiv hat ein unsicheres Kompressionsverhältnis.");
            total += entry.Length;
            if (total > MaxImportBytes) throw new InvalidDataException("Der Archivinhalt ist größer als 32 Megabyte.");
            using var source = entry.Open(); using var data = new MemoryStream();
            var buffer = new byte[81920]; int count;
            while ((count = source.Read(buffer, 0, buffer.Length)) > 0)
            {
                if (data.Length + count > MaxArchiveEntryBytes) throw new InvalidDataException("Ein Archiveintrag ist zu groß.");
                data.Write(buffer, 0, count);
            }
            total += data.Length - entry.Length;
            if (total > MaxImportBytes) throw new InvalidDataException("Der Archivinhalt ist größer als 32 Megabyte.");
            var part = ParseImportEntry(data.ToArray(), art, entry.FullName);
            Append(result.Termine, part.Termine); Append(result.Jahrestage, part.Jahrestage);
            Append(result.Geburtstage, part.Geburtstage); Append(result.Aufgaben, part.Aufgaben);
            Append(result.Kontakte, part.Kontakte); if (result.Notizen is not null && part.Notizen is not null) Append(result.Notizen, part.Notizen);
            if (part.Bericht.Length > 0) reports.Add(part.Bericht); read++;
            result = result with { Uebersprungen = result.Uebersprungen + part.Uebersprungen,
                Wiederholend = result.Wiederholend + part.Wiederholend };
        }
        if (read == 0) throw new InvalidDataException("Das Archiv enthält keine unterstützten Importdateien.");
        return result with { Bericht = string.Join(' ', reports) };
    }

    private static ExchangeImportResult ParseImportEntry(byte[] bytes, string art, string fileName)
    {
        var text = DecodeText(bytes); var extension = Path.GetExtension(fileName).ToLowerInvariant();
        return art switch
        {
            "ics" => ParseIcs(text),
            "vcf" when extension == ".csv" => ParseLotusCsv(text),
            "vcf" => ParseVCard(text),
            "lotus" => ParseLotusCsv(text),
            "claws" when text.TrimStart().StartsWith("<?xml", StringComparison.OrdinalIgnoreCase) || text.Contains("<address-book", StringComparison.OrdinalIgnoreCase) => ParseClawsXml(text),
            "claws" => ParseLdif(text),
            _ => throw new InvalidDataException("Unbekanntes Importformat.")
        };
    }

    private static bool SupportedArchiveEntry(string art, string name)
    {
        var extension = Path.GetExtension(name).ToLowerInvariant();
        return art switch { "ics" => extension is ".ics" or ".vcs" or ".lcs", "vcf" => extension is ".vcf" or ".csv",
            "lotus" => extension == ".csv", "claws" => extension is ".xml" or ".ldif" or ".ldi", _ => false };
    }

    private static void Append(JsonArray target, JsonArray source)
    {
        foreach (var node in source) target.Add(node?.DeepClone());
    }

    internal static string DecodeText(byte[] bytes)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        if (bytes.AsSpan().StartsWith(new byte[] { 0xff, 0xfe })) return Encoding.Unicode.GetString(bytes, 2, bytes.Length - 2);
        if (bytes.AsSpan().StartsWith(new byte[] { 0xfe, 0xff })) return Encoding.BigEndianUnicode.GetString(bytes, 2, bytes.Length - 2);
        try { return new UTF8Encoding(false, true).GetString(bytes).TrimStart('\ufeff'); }
        catch (DecoderFallbackException) { return Encoding.GetEncoding(1252).GetString(bytes); }
    }

    internal static ExchangeImportResult ParseIcs(string text)
    {
        if (text.IndexOf('\0') >= 0 || !IcsMarker().IsMatch(text))
            throw new InvalidDataException("Die Datei ist kein lesbarer iCalendar-Kalender.");

        var appointments = new JsonArray();
        var anniversaries = new JsonArray();
        var tasks = new JsonArray();
        var skipped = 0;
        var complex = 0;
        string? component = null;
        var componentDepth = 0;
        var components = new List<string>();
        var properties = new List<IcsProperty>();
        foreach (var line in Unfold(text))
        {
            var property = ParseIcsProperty(line);
            if (property?.Name == "BEGIN")
            {
                var value = property.Value.Trim().ToUpperInvariant();
                var parent = components.Count > 0 ? components[^1] : null;
                components.Add(value);
                if (component is null && (value is "VEVENT" or "VTODO") &&
                    (parent is null or "VCALENDAR"))
                {
                    component = value;
                    componentDepth = components.Count;
                    properties.Clear();
                }
                else if (component is not null) properties.Add(property);
                continue;
            }
            if (property?.Name == "END")
            {
                var value = property.Value.Trim().ToUpperInvariant();
                if (components.Count == 0 || components[^1] != value)
                    throw new InvalidDataException("Die iCalendar-Datei ist unvollständig.");
                var parent = components.Count > 1 ? components[^2] : null;
                if (component is not null && components.Count != componentDepth) properties.Add(property);
                else if (component == value)
                {
                    try
                    {
                        if (component == "VEVENT")
                        {
                            var result = ParseEvent(properties);
                            if (result.Anniversary) anniversaries.Add(result.Value);
                            else appointments.Add(result.Value);
                            if (result.Complex) complex++;
                        }
                        else tasks.Add(ParseTask(properties));
                    }
                    catch (Exception) { skipped++; }
                    component = null;
                    componentDepth = 0;
                }
                else if (parent == "VCALENDAR" && value != "VTIMEZONE") skipped++;
                components.RemoveAt(components.Count - 1);
                continue;
            }
            if (component is not null && property is not null) properties.Add(property);
        }
        if (component is not null || components.Count > 0)
            throw new InvalidDataException("Die iCalendar-Datei ist unvollständig.");
        return new ExchangeImportResult(appointments, anniversaries, new JsonArray(), tasks,
            new JsonArray(), skipped, complex,
            complex > 0 ? $"{complex} komplexe Serien wurden als einzelner Eintrag übernommen." : "");
    }

    internal static ExchangeExportResult WriteIcs(string art, JsonElement data)
    {
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        var lines = new List<string>
        {
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie Organizer//DE", "CALSCALE:GREGORIAN"
        };
        var count = 0;
        var skipped = 0;
        var rawOmitted = 0;
        foreach (var item in data.EnumerateArray())
        {
            try
            {
                rawOmitted += CountRejectedIcsRoundtrip(item);
                var generated = art switch
                {
                    "ics-termine" => AppointmentLines(item),
                    "ics-jahrestage" => AnniversaryLines(item),
                    "ics-aufgaben" => TaskLines(item),
                    _ => throw new ArgumentException("Diese Kalender-Exportart wird nicht unterstützt.")
                };
                lines.AddRange(generated);
                count++;
            }
            catch (Exception) { skipped++; }
        }
        lines.Add("END:VCALENDAR");
        var report = rawOmitted > 0
            ? $"{rawOmitted} ungültige ICS-Rohzeilen wurden beim Export verworfen."
            : "";
        return new ExchangeExportResult(string.Join("\r\n", lines.Select(FoldUtf8)) + "\r\n", count, skipped,
            report, RawOmitted: rawOmitted);
    }

    internal static ExchangeImportResult ParseVCard(string text)
    {
        var contacts = new JsonArray();
        var birthdays = new JsonArray();
        var skipped = 0;
        foreach (Match match in VCardBlock().Matches(text.ReplaceLineEndings("\n")))
        {
            try
            {
                var lines = UnfoldVCard(match.Value).ToArray();
                var values = ParseVCardProperties(lines);
                var names = SplitVCard(RawValue(values, "N"));
                var fullName = Value(values, "FN");
                var lastName = names.ElementAtOrDefault(0) ?? "";
                var firstName = names.ElementAtOrDefault(1) ?? "";
                if (firstName.Length == 0 && lastName.Length == 0) firstName = fullName;
                var phones = Entries(values, "TEL").Select(entry => new JsonObject
                {
                    ["wert"] = CleanUri(entry.Value, "tel:"),
                    ["typen"] = new JsonArray(entry.Types.Select(type => JsonValue.Create(type)).ToArray()),
                    ["vcardParameter"] = PreservedParameters(entry)
                }).Where(entry => entry["wert"]?.GetValue<string>().Length > 0).ToArray();
                var emailEntries = Entries(values, "EMAIL").Select(entry => new JsonObject
                {
                    ["wert"] = CleanUri(entry.Value, "mailto:"),
                    ["typen"] = new JsonArray(entry.Types.Select(type => JsonValue.Create(type)).ToArray()),
                    ["label"] = entry.Label, ["vcardParameter"] = PreservedParameters(entry)
                }).Where(entry => ValidEmail(entry["wert"]?.ToString() ?? "")).ToArray();
                var emails = emailEntries.Select(entry => entry["wert"]!.ToString()).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
                var addresses = Entries(values, "ADR").Select(entry =>
                {
                    var parts = SplitVCard(entry.Raw);
                    return new JsonObject
                    {
                        ["strasse"] = parts.ElementAtOrDefault(2) ?? "",
                        ["ort"] = parts.ElementAtOrDefault(3) ?? "",
                        ["plz"] = parts.ElementAtOrDefault(5) ?? "",
                        ["land"] = parts.ElementAtOrDefault(6) ?? "",
                        ["typen"] = new JsonArray(entry.Types.Select(type => JsonValue.Create(type)).ToArray()),
                        ["vcardParameter"] = PreservedParameters(entry)
                    };
                }).ToArray();
                var firstAddress = addresses.FirstOrDefault();
                var firstPhone = phones.FirstOrDefault(entry =>
                    entry["typen"]?.AsArray().Any(type => type?.ToString().Equals("CELL", StringComparison.OrdinalIgnoreCase) == false) == true);
                var mobile = phones.FirstOrDefault(entry =>
                    entry["typen"]?.AsArray().Any(type => type?.ToString().Equals("CELL", StringComparison.OrdinalIgnoreCase) == true) == true);
                var contact = new JsonObject
                {
                    ["uid"] = Value(values, "UID"), ["nachname"] = lastName, ["vorname"] = firstName,
                    ["firma"] = SplitVCard(RawValue(values, "ORG")).FirstOrDefault() ?? "",
                    ["strasse"] = firstAddress?["strasse"]?.ToString() ?? "",
                    ["plz"] = firstAddress?["plz"]?.ToString() ?? "", ["ort"] = firstAddress?["ort"]?.ToString() ?? "",
                    ["anschriften"] = new JsonArray(addresses),
                    ["telefon"] = firstPhone?["wert"]?.ToString() ?? "", ["mobil"] = mobile?["wert"]?.ToString() ?? "",
                    ["telefone"] = new JsonArray(phones), ["email"] = emails.FirstOrDefault() ?? "",
                    ["emails"] = new JsonArray(emails.Select(email => JsonValue.Create(email)).ToArray()),
                    ["emailEintraege"] = new JsonArray(emailEntries),
                    ["notiz"] = Value(values, "NOTE"), ["foto"] = Photo(values),
                    ["kontaktpersonName"] = Value(values, "X-MAGNOLIE-KONTAKTPERSON-NAME"),
                    ["kontaktpersonTelefon"] = Value(values, "X-MAGNOLIE-KONTAKTPERSON-TELEFON"),
                    ["kontaktpersonStatus"] = Value(values, "X-MAGNOLIE-KONTAKTPERSON-STATUS"),
                    ["kontaktpersonen"] = MagnolieJsonEntries(values, "X-MAGNOLIE-NOTFALLKONTAKT"),
                    ["sozialeMedien"] = MagnolieJsonEntries(values, "X-MAGNOLIE-SOZIALES-MEDIUM"),
                    ["vcardRoundtrip"] = UnknownVCardLines(lines),
                    ["geaendert"] = ParseTimestamp(Value(values, "REV"))
                };
                if (firstName.Length + lastName.Length + contact["firma"]!.ToString().Length > 0) contacts.Add(contact);
                else { skipped++; continue; }
                var birthday = ParseBirthday(Value(values, "BDAY"));
                if (birthday.Length > 0)
                {
                    var unknownYear = birthday.StartsWith("--", StringComparison.Ordinal);
                    contact["geburtstag"] = birthday;
                    contact["geburtstagJahrUnbekannt"] = unknownYear;
                    birthdays.Add(new JsonObject { ["name"] = fullName.Length > 0 ? fullName : $"{firstName} {lastName}".Trim(), ["datum"] = birthday, ["jahrUnbekannt"] = unknownYear });
                }
            }
            catch (Exception) { skipped++; }
        }
        if (contacts.Count == 0) throw new InvalidDataException("Die Datei enthält keine verwendbaren vCard-Kontakte.");
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeExportResult WriteVCard(JsonElement data)
    {
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        var cards = new List<string>();
        var skipped = 0;
        foreach (var contact in data.EnumerateArray())
        {
            try
            {
                var first = J(contact, "vorname");
                var last = J(contact, "nachname");
                var company = J(contact, "firma");
                if (first.Length + last.Length + company.Length == 0) throw new InvalidDataException();
                var lines = new List<string> { "BEGIN:VCARD", "VERSION:3.0", $"N:{V(last)};{V(first)};;;", $"FN:{V(($"{first} {last}").Trim().Length > 0 ? $"{first} {last}".Trim() : company)}" };
                if (company.Length > 0) lines.Add($"ORG:{V(company)}");
                AddTypedEntries(lines, contact, "telefone", "TEL", "wert", J(contact, "telefon"), J(contact, "mobil"));
                AddTypedEntries(lines, contact, "emailEintraege", "EMAIL", "wert", J(contact, "email"));
                if (contact.TryGetProperty("anschriften", out var addressArray) && addressArray.ValueKind == JsonValueKind.Array)
                    foreach (var address in addressArray.EnumerateArray()) AddAddress(lines, address);
                else AddAddress(lines, contact);
                if (J(contact, "notiz") is { Length: > 0 } note) lines.Add($"NOTE:{V(note)}");
                foreach (var pair in new[] { ("kontaktpersonName", "X-MAGNOLIE-KONTAKTPERSON-NAME"), ("kontaktpersonTelefon", "X-MAGNOLIE-KONTAKTPERSON-TELEFON"), ("kontaktpersonStatus", "X-MAGNOLIE-KONTAKTPERSON-STATUS") })
                    if (J(contact, pair.Item1) is { Length: > 0 } value) lines.Add(pair.Item2 + ":" + V(value));
                AddMagnolieJsonEntries(lines, contact, "kontaktpersonen", "X-MAGNOLIE-NOTFALLKONTAKT");
                AddMagnolieJsonEntries(lines, contact, "sozialeMedien", "X-MAGNOLIE-SOZIALES-MEDIUM");
                if (J(contact, "uid") is { Length: > 0 } uid) lines.Add($"UID:{V(uid)}");
                if (J(contact, "geburtstag") is { Length: > 0 } birthday && TryParseCanonicalDate(birthday, out _, out _, out _))
                    lines.Add("BDAY:" + birthday);
                if (J(contact, "foto") is { Length: > 0 } photo && TryPhotoData(photo, out var mediaType, out var base64))
                    lines.Add($"PHOTO;ENCODING=b;TYPE={mediaType}:{base64}");
                if (contact.TryGetProperty("vcardRoundtrip", out var roundtrip) && roundtrip.ValueKind == JsonValueKind.Array)
                    foreach (var raw in roundtrip.EnumerateArray())
                        if (raw.ValueKind == JsonValueKind.String && SafeUnknownVCardLine(raw.GetString() ?? "")) lines.Add(raw.GetString()!);
                var modified = JLong(contact, "geaendert");
                if (modified > 0) lines.Add($"REV:{DateTimeOffset.FromUnixTimeMilliseconds(modified).UtcDateTime:yyyyMMdd'T'HHmmss'Z'}");
                lines.Add("END:VCARD");
                cards.Add(string.Join("\r\n", lines.Select(FoldUtf8)));
            }
            catch (Exception) { skipped++; }
        }
        return new ExchangeExportResult(string.Join("\r\n", cards) + (cards.Count > 0 ? "\r\n" : ""), cards.Count, skipped);
    }

    internal static ExchangeExportResult WriteLdif(JsonElement data)
    {
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        var records = new List<string>(); var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var skipped = 0; var photoOmitted = 0;
        foreach (var contact in data.EnumerateArray())
        {
            if (contact.ValueKind != JsonValueKind.Object) { skipped++; continue; }
            var first = J(contact, "vorname").Trim(); var last = J(contact, "nachname").Trim();
            var company = J(contact, "firma").Trim(); var emails = LdifEmails(contact).ToArray();
            var cn = string.Join(' ', new[] { first, last }.Where(value => value.Length > 0));
            if (cn.Length == 0) cn = company.Length > 0 ? company : emails.FirstOrDefault() ?? "";
            if (cn.Length == 0) { skipped++; continue; }
            var uid = LdifUid(contact, used);
            var lines = new List<string>
            {
                LdifLine("dn", "uid=" + EscapeDn(uid)), LdifLine("objectClass", "top"),
                LdifLine("objectClass", "person"), LdifLine("objectClass", "organizationalPerson"),
                LdifLine("objectClass", "inetOrgPerson"), LdifLine("uid", uid), LdifLine("cn", cn)
            };
            if (first.Length > 0) lines.Add(LdifLine("givenName", first));
            lines.Add(LdifLine("sn", last.Length > 0 ? last : company.Length > 0 ? company : cn));
            lines.AddRange(emails.Select(email => LdifLine("mail", email)));
            foreach (var phone in LdifPhones(contact)) lines.Add(LdifLine(phone.Attribute, phone.Value));
            foreach (var address in LdifAddresses(contact))
            {
                var parts = new[] { J(address, "strasse").Trim(),
                    string.Join(' ', new[] { J(address, "plz").Trim(), J(address, "ort").Trim() }.Where(value => value.Length > 0)),
                    J(address, "land").Trim() }.Where(value => value.Length > 0)
                    .Select(value => Regex.Replace(value, "[\\r\\n\\0]+", " ").Replace("$", "\\24"));
                var postal = string.Join('$', parts); if (postal.Length > 0) lines.Add(LdifLine("postalAddress", postal));
            }
            if (company.Length > 0) lines.Add(LdifLine("o", company));
            if (J(contact, "notiz") is { Length: > 0 } note) lines.Add(LdifLine("description", note));
            if (J(contact, "geburtstag") is { Length: > 0 } birthday &&
                TryParseCanonicalDate(birthday, out var fullBirthday, out _, out _) && fullBirthday is not null)
                lines.Add(LdifLine("dateOfBirth", birthday));
            if (J(contact, "foto") is { Length: > 0 } photo)
            {
                if (TryLdifJpeg(photo, out var jpeg)) lines.Add(LdifBinaryLine("jpegPhoto", jpeg));
                else photoOmitted++;
            }
            records.Add(string.Join("\r\n", lines));
        }
        var text = "version: 1\r\n" + (records.Count > 0 ? "\r\n" + string.Join("\r\n\r\n", records) + "\r\n" : "");
        return new ExchangeExportResult(text, records.Count, skipped, "", photoOmitted);
    }

    internal static ExchangeImportResult ParseLdif(string text)
    {
        var contacts = new JsonArray(); var birthdays = new JsonArray(); var skipped = 0;
        var unfolded = new List<string>();
        foreach (var line in text.ReplaceLineEndings("\n").Split('\n'))
            if (line.StartsWith(' ') && unfolded.Count > 0) unfolded[^1] += line[1..]; else unfolded.Add(line);
        foreach (var block in string.Join("\n", unfolded).Split("\n\n", StringSplitOptions.RemoveEmptyEntries))
        {
            var fields = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            var photo = "";
            foreach (var line in block.Split('\n'))
            {
                var match = Regex.Match(line, "^([A-Za-z][A-Za-z0-9-]*)(?:;[^:]*)?(::?)\\s?(.*)$");
                if (!match.Success) { if (!line.TrimStart().StartsWith('#')) skipped++; continue; }
                var name = match.Groups[1].Value; if (name is "dn" or "objectClass" or "version") continue;
                var value = match.Groups[3].Value;
                if (match.Groups[2].Value == "::")
                {
                    try
                    {
                        var bytes = Convert.FromBase64String(value);
                        if (name.Equals("jpegPhoto", StringComparison.OrdinalIgnoreCase) && bytes.Length <= 2_700_000)
                            photo = "data:image/jpeg;base64," + Convert.ToBase64String(bytes);
                        else value = Encoding.UTF8.GetString(bytes);
                    }
                    catch (FormatException) { skipped++; continue; }
                }
                if (!fields.TryGetValue(name, out var list)) fields[name] = list = new List<string>();
                list.Add(value.Trim());
            }
            var parsed = ContactFromFields(fields, photo);
            if (parsed is null) continue;
            var contact = parsed.Value.Contact; var birthday = parsed.Value.Birthday; var unknownYear = parsed.Value.UnknownYear;
            var addresses = LdifPostalAddresses(fields);
            if (addresses.Count > 0)
            {
                contact["anschriften"] = addresses;
                contact["strasse"] = addresses[0]?["strasse"]?.ToString() ?? "";
                contact["plz"] = addresses[0]?["plz"]?.ToString() ?? "";
                contact["ort"] = addresses[0]?["ort"]?.ToString() ?? "";
            }
            contacts.Add(contact);
            if (birthday.Length > 0) birthdays.Add(BirthdayNode(parsed.Value.Name, birthday, unknownYear));
        }
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeImportResult ParseClawsXml(string text)
    {
        if (text.Contains("<!DOCTYPE", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("DOCTYPE ist in einem Claws-Mail-Adressbuch nicht erlaubt.");
        var document = XDocument.Parse(text, LoadOptions.None);
        if (document.Root?.Name.LocalName != "address-book") throw new InvalidDataException("Kein Claws-Mail-Adressbuch erkannt.");
        var contacts = new JsonArray(); var birthdays = new JsonArray(); var skipped = 0;
        foreach (var person in document.Root.Elements("person"))
        {
            var fields = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            void Add(string name, string? value) { if (string.IsNullOrWhiteSpace(value)) return; if (!fields.TryGetValue(name, out var list)) fields[name] = list = new(); list.Add(value.Trim()); }
            Add("givenName", (string?)person.Attribute("first-name")); Add("sn", (string?)person.Attribute("last-name"));
            Add("cn", (string?)person.Attribute("cn")); Add("uid", (string?)person.Attribute("uid"));
            foreach (var address in person.Element("address-list")?.Elements("address") ?? Enumerable.Empty<XElement>())
            { Add("mail", (string?)address.Attribute("email")); Add("remarks", (string?)address.Attribute("remarks")); }
            foreach (var attribute in person.Element("attribute-list")?.Elements("attribute") ?? Enumerable.Empty<XElement>()) Add((string?)attribute.Attribute("name") ?? "", attribute.Value);
            var parsed = ContactFromFields(fields, Field(fields, "photo", "jpegPhoto"));
            if (parsed is null) { skipped++; continue; }
            contacts.Add(parsed.Value.Contact);
            if (parsed.Value.Birthday is { Length: > 0 } birthday) birthdays.Add(BirthdayNode(parsed.Value.Name, birthday, parsed.Value.UnknownYear));
        }
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeImportResult ParseLotusCsv(string text)
    {
        var rows = ParseCsv(text); if (rows.Count == 0) return EmptyImport();
        var header = rows[0].Select(NormalizeHeader).ToArray();
        int Find(params string[] names) { for (var index = 0; index < header.Length; index++) if (names.Any(candidate => header[index].Contains(candidate, StringComparison.Ordinal))) return index; return -1; }
        var startIndex = Find("ANFANGSDATUMZEIT", "STARTDATUMZEIT", "STARTDATE", "DATUMZEIT");
        var descriptionIndex = Find("BESCHREIBUNG", "BETREFF", "SUMMARY", "SUBJECT");
        if (startIndex < 0 || descriptionIndex < 0)
        {
            var contacts = new JsonArray(); var tasks = new JsonArray(); var anniversaries = new JsonArray(); var notes = new JsonArray(); var omitted = 0;
            var lastIndex = Find("NACHNAME", "LASTNAME", "FAMILIENNAME", "FAMILYNAME"); var firstIndex = Find("VORNAME", "FIRSTNAME", "GIVENNAME"); var companyIndex = Find("FIRMA", "COMPANY", "ORGANISATION");
            var dueIndex = Find("FAELLIG", "DUE"); var anniversaryIndex = Find("JAHRESTAG", "GEBURTSTAG"); var noteTextIndex = Find("TEXT", "INHALT", "BODY", "NOTIZ");
            foreach (var row in rows.Skip(1))
            {
                string Cell(int index) => index >= 0 && index < row.Count ? row[index].Trim() : "";
                if (lastIndex >= 0 || firstIndex >= 0 || companyIndex >= 0)
                {
                    var phones = header.Select((name, index) => (name, index)).Where(pair => pair.name.Contains("TELEFON") || pair.name.Contains("PHONE") || pair.name.Contains("MOBIL") || pair.name.Contains("CELL") || pair.name.Contains("FAX")).Where(pair => Cell(pair.index).Length > 0)
                        .Select(pair => new JsonObject { ["wert"] = Cell(pair.index), ["typen"] = new JsonArray(pair.name.Contains("MOBIL") || pair.name.Contains("CELL") ? "CELL" : pair.name.Contains("FAX") ? "FAX" : "VOICE") }).ToArray();
                    var emails = header.Select((name, index) => (name, index)).Where(pair => pair.name.Contains("EMAIL") || pair.name.Contains("MAIL")).Select(pair => Cell(pair.index)).Where(ValidEmail).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
                    var street = Cell(Find("STRASSE", "STREET", "ANSCHRIFT")); var city = Cell(Find("ORT", "CITY", "STADT")); var postal = Cell(Find("PLZ", "POSTLEITZAHL", "ZIP")); var country = Cell(Find("LAND", "COUNTRY"));
                    if (Cell(lastIndex).Length + Cell(firstIndex).Length + Cell(companyIndex).Length + emails.Sum(value => value.Length) == 0) { omitted++; continue; }
                    contacts.Add(new JsonObject { ["nachname"] = Cell(lastIndex), ["vorname"] = Cell(firstIndex), ["firma"] = Cell(companyIndex), ["strasse"] = street, ["plz"] = postal, ["ort"] = city,
                        ["anschriften"] = new JsonArray(new JsonObject { ["strasse"] = street, ["plz"] = postal, ["ort"] = city, ["land"] = country }), ["telefone"] = new JsonArray(phones), ["telefon"] = phones.FirstOrDefault()?["wert"]?.ToString() ?? "", ["mobil"] = phones.FirstOrDefault(phone => phone["typen"]?.AsArray().Any(type => type?.ToString() == "CELL") == true)?["wert"]?.ToString() ?? "",
                        ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(email => JsonValue.Create(email)).ToArray()), ["notiz"] = Cell(Find("BEMERKUNG", "NOTIZ", "NOTES")), ["uid"] = "", ["geaendert"] = 0 });
                }
                else if (dueIndex >= 0)
                {
                    var title = Cell(descriptionIndex >= 0 ? descriptionIndex : Find("AUFGABE", "TITEL")); if (title.Length == 0) { omitted++; continue; }
                    tasks.Add(new JsonObject { ["titel"] = title, ["faellig"] = ParseLotusDate(Cell(dueIndex)).Date, ["prio"] = Cell(Find("PRIORITAET", "PRIORITY")).StartsWith('1') ? 1 : 2,
                        ["erledigt"] = IsYes(Cell(Find("ERLEDIGT", "COMPLETED", "STATUS"))), ["notiz"] = Cell(noteTextIndex), ["uid"] = "", ["geaendert"] = 0 });
                }
                else if (anniversaryIndex >= 0)
                {
                    var name = Cell(Find("NAME", "ANLASS", "BESCHREIBUNG")); var date = ParseLotusDate(Cell(anniversaryIndex)).Date; if (name.Length == 0 || date.Length == 0) { omitted++; continue; }
                    anniversaries.Add(new JsonObject { ["name"] = name, ["datum"] = date, ["typ"] = header[anniversaryIndex].Contains("GEBURT") ? "birthday" : "other" });
                }
                else if (noteTextIndex >= 0)
                {
                    var title = Cell(Find("TITEL", "BETREFF", "NAME")); var body = Cell(noteTextIndex); if (title.Length + body.Length == 0) { omitted++; continue; }
                    notes.Add(new JsonObject { ["titel"] = title.Length > 0 ? title : body.Split('\n')[0], ["text"] = body });
                }
            }
            if (contacts.Count + tasks.Count + anniversaries.Count + notes.Count == 0) throw new InvalidDataException("Die Lotus-CSV-Spalten wurden nicht erkannt.");
            return new ExchangeImportResult(new JsonArray(), anniversaries, new JsonArray(), tasks, contacts, omitted, 0, "", notes);
        }
        var appointments = new JsonArray(); var skipped = 0; var ambiguous = 0;
        foreach (var row in rows.Skip(1))
        {
            string Cell(int index) => index >= 0 && index < row.Count ? row[index].Trim() : "";
            var start = ParseLotusDate(Cell(startIndex));
            if (start.Ambiguous) { ambiguous++; skipped++; continue; }
            if (start.Date.Length == 0) { skipped++; continue; }
            var end = ParseLotusDate(Cell(Find("ENDDATUMZEIT", "ENDEDATUMZEIT", "ENDDATE")));
            var description = Cell(descriptionIndex).ReplaceLineEndings("\n"); var split = description.IndexOf('\n');
            appointments.Add(new JsonObject
            {
                ["datum"] = start.Date, ["zeit"] = start.Time, ["endDatum"] = end.Date != start.Date ? end.Date : "", ["endZeit"] = end.Time,
                ["titel"] = (split < 0 ? description : description[..split]).Trim(), ["notiz"] = split < 0 ? "" : description[(split + 1)..],
                ["kategorien"] = Cell(Find("KATEGORIEN", "CATEGORY")), ["vertraulich"] = IsYes(Cell(Find("VERTRAULICH", "PRIVATE"))),
                ["vorlaeufig"] = IsYes(Cell(Find("VORLAEUFIG", "TENTATIVE"))), ["kostenstelle"] = Cell(Find("KOSTENSTELLE", "COSTCENTER")),
                ["kunde"] = Cell(Find("KUNDENNUMMER", "KUNDE", "CUSTOMER")), ["uid"] = "", ["geaendert"] = 0
            });
        }
        var report = ambiguous > 0 ? $"{ambiguous} mehrdeutige US-/EU-Datumswerte wurden nicht geraten und ausgelassen." : "";
        return new ExchangeImportResult(appointments, new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray(), skipped, 0, report);
    }

    internal static ExchangeExportResult WriteLotusCsv(JsonElement data)
    {
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        var output = new StringBuilder();
        WriteCsvRow(output, new[] { "VERTRAULICH", "KATEGORIEN", "ANFANGSDATUMZEIT", "ENDDATUMZEIT", "BESCHREIBUNG", "KOSTENSTELLENCODE", "KUNDENNUMMER", "VORLAEUFIGZUSAGEN" });
        var count = 0; var skipped = 0; var lossy = 0;
        foreach (var item in data.EnumerateArray())
        {
            if (!DateOnly.TryParseExact(J(item, "datum"), "yyyy-MM-dd", out _)) { skipped++; continue; }
            if (item.TryGetProperty("wiederholung", out var recurrence) && recurrence.ValueKind == JsonValueKind.Object && J(recurrence, "art") is not ("" or "none") ||
                JInt(item, "individuelleErinnerungTage") > 0 || item.TryGetProperty("standardErinnerung", out var standardReminder) && standardReminder.ValueKind == JsonValueKind.False ||
                item.TryGetProperty("icsRoundtrip", out var roundtrip) && roundtrip.ValueKind == JsonValueKind.Array && roundtrip.GetArrayLength() > 0) lossy++;
            var description = J(item, "titel") + (J(item, "notiz") is { Length: > 0 } note ? "\n" + note : "");
            WriteCsvRow(output, new[] { JBool(item, "vertraulich") ? "Ja" : "Nein", J(item, "kategorien"), LotusDate(J(item, "datum"), J(item, "zeit")),
                LotusDate(J(item, "endDatum").Length > 0 ? J(item, "endDatum") : J(item, "datum"), J(item, "endZeit").Length > 0 ? J(item, "endZeit") : J(item, "zeit")),
                description, J(item, "kostenstelle"), J(item, "kunde"), JBool(item, "vorlaeufig") ? "Ja" : "Nein" }); count++;
        }
        var report = skipped > 0 ? $"{skipped} Termine hatten kein gültiges Datum und wurden ausgelassen. " : "";
        if (lossy > 0) report += $"{lossy} Termine enthalten Serien-, Erinnerungs- oder ICS-Zusatzdaten, die Lotus CSV standardbedingt nicht darstellen kann.";
        return new ExchangeExportResult(output.ToString(), count, skipped, report.Trim());
    }

    private static (JsonObject Value, bool Anniversary, bool Complex) ParseEvent(List<IcsProperty> values)
    {
        var roundtripValues = values;
        values = TopLevelProperties(values);
        var startProperty = First(values, "DTSTART") ?? throw new InvalidDataException();
        var start = ParseIcsDate(startProperty);
        var endProperty = First(values, "DTEND");
        (DateTime DateTime, bool AllDay)? end = endProperty is null ? null : ParseIcsDate(endProperty);
        if (start.AllDay && end is not null && end.Value.AllDay) end = (end.Value.DateTime.AddDays(-1), true);
        var recurrence = First(values, "RRULE")?.Value ?? "";
        var rdateProperties = values.Where(value => value.Name == "RDATE").ToArray();
        var customDates = new SortedSet<DateOnly>();
        var invalidRdate = false;
        foreach (var property in rdateProperties)
            foreach (var rawDate in property.Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                try
                {
                    var parsed = ParseIcsDate(property with { Value = rawDate });
                    var date = DateOnly.FromDateTime(parsed.DateTime);
                    if (parsed.AllDay != start.AllDay || !parsed.AllDay && TimeOnly.FromDateTime(parsed.DateTime) != TimeOnly.FromDateTime(start.DateTime) ||
                        date <= DateOnly.FromDateTime(start.DateTime)) invalidRdate = true;
                    else customDates.Add(date);
                }
                catch (Exception) when (rawDate.Length > 0) { invalidRdate = true; }
        var monthlyWeekday = MonthlyWeekday(recurrence);
        var simpleRdate = recurrence.Length == 0 && rdateProperties.Length > 0 && !invalidRdate && customDates.Count > 0;
        var recurrenceKind = simpleRdate ? "custom" : monthlyWeekday.Form.Length > 0 ? "monthly" : RecurrenceKind(recurrence);
        var complex = recurrence.Length > 0 && recurrenceKind.Length == 0 ||
                       values.Count(value => value.Name == "RRULE") > 1 ||
                       values.Any(value => value.Name is "EXDATE" or "EXRULE" or "RECURRENCE-ID") ||
                       rdateProperties.Length > 0 && !simpleRdate;
        if (recurrence.Length > 0 && !start.AllDay &&
            (startProperty.Value.EndsWith('Z') || startProperty.Parameters.Any(parameter =>
                parameter.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase)))) complex = true;
        if (recurrenceKind == "monthly" && monthlyWeekday.Form.Length == 0 && start.DateTime.Day > 28 ||
            recurrenceKind == "yearly" && start.DateTime.Month == 2 && start.DateTime.Day == 29)
            complex = true;
        var title = IcsText(First(values, "SUMMARY")?.Value ?? "");
        var category = IcsText(First(values, "CATEGORIES")?.Value ?? "");
        var anniversaryType = IcsText(First(values, "X-MAGNOLIE-TYPE-ID")?.Value ??
                                      First(values, "X-MAGNOLIE-TYP")?.Value ??
                                      First(values, "X-MAGNOLIE-JAHRESTAG-TYP")?.Value ?? "");
        var anniversary = start.AllDay && recurrenceKind == "yearly" &&
                          (anniversaryType.Length > 0 || category.Contains("birthday", StringComparison.OrdinalIgnoreCase) || category.Contains("Geburtstag", StringComparison.OrdinalIgnoreCase));
        if (anniversary)
        {
            var date = start.DateTime.ToString("yyyy-MM-dd");
            var magnolieDate = First(values, "X-MAGNOLIE-DATE")?.Value.Trim() ?? "";
            if (TryParseCanonicalDate(magnolieDate, out var fullDate, out _, out _) && fullDate is null)
                date = magnolieDate;
            return (new JsonObject { ["uid"] = First(values, "UID")?.Value ?? "", ["name"] = title,
                ["datum"] = date, ["typ"] = anniversaryType.Length > 0 ? anniversaryType : "birthday",
                ["icsRoundtrip"] = IcsRoundtrip(roundtripValues, complex), ["geaendert"] = IcsModified(values) }, true, complex);
        }
        var until = RRuleValue(recurrence, "UNTIL");
        var interval = int.TryParse(RRuleValue(recurrence, "INTERVAL"), out var parsedInterval)
            ? Math.Clamp(parsedInterval, 1, 3660) : 1;
        var uid = First(values, "UID")?.Value ?? "";
        if (First(values, "RECURRENCE-ID") is { } recurrenceId) uid += "#" + recurrenceId.Value;
        var recurrenceObject = new JsonObject { ["art"] = recurrenceKind.Length > 0 && !complex ? recurrenceKind : "none",
            ["bis"] = ParseCompactDate(until), ["intervall"] = interval > 1 && !complex ? interval : 1,
            ["ordinal"] = monthlyWeekday.Form.Length > 0 && !complex ? monthlyWeekday.Ordinal : 0,
            ["wochentag"] = monthlyWeekday.Form.Length > 0 && !complex ? monthlyWeekday.Weekday : "",
            ["rruleForm"] = monthlyWeekday.Form.Length > 0 && !complex ? monthlyWeekday.Form : "" };
        if (simpleRdate) recurrenceObject["daten"] = new JsonArray(customDates
            .Select(date => (JsonNode?)date.ToString("yyyy-MM-dd")).ToArray());
        var result = new JsonObject
        {
            ["uid"] = uid, ["datum"] = start.DateTime.ToString("yyyy-MM-dd"),
            ["endDatum"] = end?.DateTime.ToString("yyyy-MM-dd") ?? "", ["zeit"] = start.AllDay ? "" : start.DateTime.ToString("HH:mm"),
            ["endZeit"] = end is null || end.Value.AllDay ? "" : end.Value.DateTime.ToString("HH:mm"), ["titel"] = title,
            ["notiz"] = IcsText(First(values, "DESCRIPTION")?.Value ?? ""), ["kategorien"] = category,
            ["vertraulich"] = (First(values, "CLASS")?.Value ?? "").Equals("PRIVATE", StringComparison.OrdinalIgnoreCase),
            ["vorlaeufig"] = (First(values, "STATUS")?.Value ?? "").Equals("TENTATIVE", StringComparison.OrdinalIgnoreCase),
            ["kostenstelle"] = IcsText(First(values, "X-MAGNOLIE-KOSTENSTELLE")?.Value ?? ""), ["kunde"] = IcsText(First(values, "X-MAGNOLIE-KUNDE")?.Value ?? ""),
            ["standardErinnerung"] = (First(values, "X-MAGNOLIE-STANDARDERINNERUNG")?.Value ?? "1") != "0",
            ["individuelleErinnerungTage"] = int.TryParse(First(values, "X-MAGNOLIE-ERINNERUNG-TAGE")?.Value, out var days) ? Math.Clamp(days, 0, 7) : 0,
            ["wiederholung"] = recurrenceObject,
            ["icsKomplex"] = complex, ["icsSerienUid"] = complex ? First(values, "UID")?.Value ?? "" : "",
            ["icsRoundtrip"] = IcsRoundtrip(roundtripValues, complex), ["geaendert"] = IcsModified(values)
        };
        return (result, false, complex);
    }

    private static JsonObject ParseTask(List<IcsProperty> values)
    {
        var due = First(values, "DUE");
        var dueValue = due is null ? default : ParseIcsDate(due);
        var start = First(values, "DTSTART");
        var startValue = start is null ? default : ParseIcsDate(start);
        return new JsonObject
        {
            ["uid"] = First(values, "UID")?.Value ?? "", ["titel"] = IcsText(First(values, "SUMMARY")?.Value ?? ""),
            ["faellig"] = due is null ? "" : dueValue.DateTime.ToString("yyyy-MM-dd"),
            ["faelligZeit"] = due is null || dueValue.AllDay ? "" : dueValue.DateTime.ToString("HH:mm"),
            ["startZeit"] = start is null || startValue.AllDay ? "" : startValue.DateTime.ToString("HH:mm"),
            ["prio"] = TaskPriority(First(values, "PRIORITY")?.Value),
            ["erledigt"] = (First(values, "STATUS")?.Value ?? "").Equals("COMPLETED", StringComparison.OrdinalIgnoreCase) || First(values, "PERCENT-COMPLETE")?.Value == "100",
            ["notiz"] = IcsText(First(values, "DESCRIPTION")?.Value ?? ""),
            ["erinnern"] = First(values, "X-MAGNOLIE-ERINNERUNG-AM-TAG")?.Value == "1",
            ["individuelleErinnerungTage"] = int.TryParse(First(values, "X-MAGNOLIE-ERINNERUNG-TAGE")?.Value, out var reminderDays) ? Math.Clamp(reminderDays, 0, 7) : 0,
            ["icsRoundtrip"] = IcsRoundtrip(values, false), ["geaendert"] = IcsModified(values)
        };
    }

    private static IEnumerable<string> AppointmentLines(JsonElement item)
    {
        var date = RequiredDate(J(item, "datum"));
        var time = J(item, "zeit");
        var sourceUid = J(item, "icsSerienUid");
        var lines = new List<string> { "BEGIN:VEVENT", $"UID:{V(sourceUid.Length > 0 ? sourceUid : Uid(item))}", $"DTSTAMP:{DateTime.UtcNow:yyyyMMdd'T'HHmmss'Z'}" };
        if (time.Length == 0)
        {
            lines.Add($"DTSTART;VALUE=DATE:{date:yyyyMMdd}");
            var end = DateOnly.TryParse(J(item, "endDatum"), out var parsedEnd) ? parsedEnd : date;
            lines.Add($"DTEND;VALUE=DATE:{end.AddDays(1):yyyyMMdd}");
        }
        else
        {
            var start = RequiredTime(date, time); var endDate = DateOnly.TryParse(J(item, "endDatum"), out var parsedEnd) ? parsedEnd : date;
            var end = J(item, "endZeit").Length > 0 ? RequiredTime(endDate, J(item, "endZeit")) : start.AddMinutes(30);
            lines.Add($"DTSTART:{start:yyyyMMdd'T'HHmmss}"); lines.Add($"DTEND:{end:yyyyMMdd'T'HHmmss}");
        }
        AddCommonEvent(lines, item);
        if (J(item, "kostenstelle") is { Length: > 0 } cost) lines.Add($"X-MAGNOLIE-KOSTENSTELLE:{V(cost)}");
        if (J(item, "kunde") is { Length: > 0 } customer) lines.Add($"X-MAGNOLIE-KUNDE:{V(customer)}");
        if (JInt(item, "individuelleErinnerungTage") is > 0 and <= 7) lines.Add($"X-MAGNOLIE-ERINNERUNG-TAGE:{JInt(item, "individuelleErinnerungTage")}");
        if (item.TryGetProperty("standardErinnerung", out var standard) && standard.ValueKind == JsonValueKind.False) lines.Add("X-MAGNOLIE-STANDARDERINNERUNG:0");
        if (item.TryGetProperty("wiederholung", out var recurrence) && recurrence.ValueKind == JsonValueKind.Object)
        {
            var kind = J(recurrence, "art").ToUpperInvariant();
            if (kind is ("MONTHLY" or "MONTHLY_WEEKDAY") && JInt(recurrence, "ordinal") is (-1 or 1 or 2 or 3 or 4) &&
                Regex.IsMatch(J(recurrence, "wochentag"), "^(MO|TU|WE|TH|FR|SA|SU)$"))
            {
                var until = J(recurrence, "bis") is { Length: > 0 } value ? $";UNTIL={value.Replace("-", "")}T235959" : "";
                lines.Add(J(recurrence, "rruleForm") == "bysetpos"
                    ? $"RRULE:FREQ=MONTHLY;BYDAY={J(recurrence, "wochentag")};BYSETPOS={JInt(recurrence, "ordinal")}{until}"
                    : $"RRULE:FREQ=MONTHLY;BYDAY={JInt(recurrence, "ordinal")}{J(recurrence, "wochentag")}{until}");
            }
            else if (kind is "DAILY" or "WEEKLY" or "MONTHLY" or "YEARLY")
            {
                var interval = Math.Clamp(JInt(recurrence, "intervall"), 1, 3660);
                lines.Add("RRULE:FREQ=" + kind +
                    (kind is "DAILY" or "WEEKLY" && interval > 1 ? $";INTERVAL={interval}" : "") +
                    (J(recurrence, "bis") is { Length: > 0 } until ? $";UNTIL={until.Replace("-", "")}T235959" : ""));
            }
            else if (kind == "CUSTOM" && recurrence.TryGetProperty("daten", out var dates) &&
                dates.ValueKind == JsonValueKind.Array)
            {
                var dateValues = dates.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String &&
                    DateOnly.TryParseExact(value.GetString(), "yyyy-MM-dd", out _))
                    .Select(value => value.GetString()!.Replace("-", "") +
                        (time.Length > 0 ? "T" + time.Replace(":", "") + "00" : ""))
                    .Distinct().Order().ToArray();
                if (dateValues.Length > 0) lines.Add((time.Length > 0 ? "RDATE:" : "RDATE;VALUE=DATE:") +
                    string.Join(',', dateValues));
            }
        }
        ApplyIcsRoundtrip(lines, item);
        lines.Add("END:VEVENT"); return lines;
    }

    private static IEnumerable<string> AnniversaryLines(JsonElement item)
    {
        var value = J(item, "datum");
        if (!TryParseCanonicalDate(value, out var fullDate, out var month, out var day)) throw new InvalidDataException();
        var date = fullDate ?? new DateOnly(2000, month, day);
        var lines = new List<string> { "BEGIN:VEVENT", $"UID:{V(Uid(item))}", $"DTSTAMP:{DateTime.UtcNow:yyyyMMdd'T'HHmmss'Z'}", $"DTSTART;VALUE=DATE:{date:yyyyMMdd}", $"SUMMARY:{V(J(item, "name"))}",
            $"X-MAGNOLIE-TYPE-ID:{V(J(item, "typ"))}", $"X-MAGNOLIE-TYP:{V(J(item, "typ"))}",
            $"X-MAGNOLIE-JAHRESTAG-TYP:{V(J(item, "typ"))}", "RRULE:FREQ=YEARLY" };
        if (fullDate is null) lines.Add($"X-MAGNOLIE-DATE:{value}");
        ApplyIcsRoundtrip(lines, item);
        lines.Add("END:VEVENT");
        return lines;
    }

    private static IEnumerable<string> TaskLines(JsonElement item)
    {
        var lines = new List<string> { "BEGIN:VTODO", $"UID:{V(Uid(item))}", $"DTSTAMP:{DateTime.UtcNow:yyyyMMdd'T'HHmmss'Z'}", $"SUMMARY:{V(J(item, "titel"))}", $"PRIORITY:{(JInt(item, "prio") switch { 1 => 1, 3 => 9, _ => 5 })}" };
        if (DateOnly.TryParse(J(item, "faellig"), out var due))
        {
            if (TimeOnly.TryParseExact(J(item, "startZeit"), "HH:mm", out var start))
                lines.Add($"DTSTART:{due:yyyyMMdd'T'}{start:HHmmss}");
            if (TimeOnly.TryParseExact(J(item, "faelligZeit"), "HH:mm", out var dueTime))
                lines.Add($"DUE:{due:yyyyMMdd'T'}{dueTime:HHmmss}");
            else lines.Add($"DUE;VALUE=DATE:{due:yyyyMMdd}");
        }
        if (JBool(item, "erledigt")) lines.AddRange(new[] { "STATUS:COMPLETED", "PERCENT-COMPLETE:100" });
        if (J(item, "notiz") is { Length: > 0 } note) lines.Add($"DESCRIPTION:{V(note)}");
        if (JBool(item, "erinnern")) lines.Add("X-MAGNOLIE-ERINNERUNG-AM-TAG:1");
        if (JInt(item, "individuelleErinnerungTage") is > 0 and <= 7) lines.Add($"X-MAGNOLIE-ERINNERUNG-TAGE:{JInt(item, "individuelleErinnerungTage")}");
        ApplyIcsRoundtrip(lines, item);
        lines.Add("END:VTODO"); return lines;
    }

    private static void AddCommonEvent(List<string> lines, JsonElement item)
    {
        lines.Add($"SUMMARY:{V(J(item, "titel"))}");
        if (J(item, "notiz") is { Length: > 0 } note) lines.Add($"DESCRIPTION:{V(note)}");
        if (J(item, "kategorien") is { Length: > 0 } category) lines.Add($"CATEGORIES:{V(category)}");
        if (JBool(item, "vertraulich")) lines.Add("CLASS:PRIVATE");
        if (JBool(item, "vorlaeufig")) lines.Add("STATUS:TENTATIVE");
    }

    private static IEnumerable<string> Unfold(string text)
    {
        var result = new List<string>();
        foreach (var line in text.ReplaceLineEndings("\n").Split('\n'))
            if ((line.StartsWith(' ') || line.StartsWith('\t')) && result.Count > 0) result[^1] += line[1..]; else result.Add(line.TrimEnd('\r'));
        return result;
    }

    private static IEnumerable<string> UnfoldVCard(string text)
    {
        var result = new List<string>();
        foreach (var line in text.ReplaceLineEndings("\n").Split('\n'))
        {
            if ((line.StartsWith(' ') || line.StartsWith('\t')) && result.Count > 0) result[^1] += line[1..];
            else if (result.Count > 0 && result[^1].EndsWith('=') && result[^1].Contains("QUOTED-PRINTABLE", StringComparison.OrdinalIgnoreCase)) result[^1] = result[^1][..^1] + line;
            else if (result.Count > 0 && result[^1].StartsWith("PHOTO", StringComparison.OrdinalIgnoreCase) &&
                     result[^1].Contains("ENCODING=", StringComparison.OrdinalIgnoreCase) && Regex.IsMatch(line.Trim(), "^[A-Za-z0-9+/=]+$")) result[^1] += line.Trim();
            else result.Add(line.TrimEnd('\r'));
        }
        return result;
    }

    private static JsonArray IcsRoundtrip(IEnumerable<IcsProperty> values, bool complex)
    {
        var names = new HashSet<string>(new[] { "RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID", "DURATION", "LOCATION", "URL", "ORGANIZER", "ATTENDEE", "ATTACH", "X-ALT-DESC", "TRANSP", "BEGIN", "END", "ACTION", "TRIGGER", "REPEAT" });
        var generated = new HashSet<string>(new[] { "UID", "DTSTAMP", "LAST-MODIFIED", "DTSTART", "DTEND", "SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "X-MAGNOLIE-KOSTENSTELLE", "X-MAGNOLIE-KUNDE", "X-MAGNOLIE-ERINNERUNG-TAGE", "X-MAGNOLIE-STANDARDERINNERUNG", "X-MAGNOLIE-TYPE-ID", "X-MAGNOLIE-TYP", "X-MAGNOLIE-JAHRESTAG-TYP", "X-MAGNOLIE-DATE" });
        if (complex) { names.Add("DTSTART"); names.Add("DTEND"); }
        var result = new JsonArray(); var depth = 0;
        foreach (var value in values)
        {
            if (value.Name == "BEGIN") depth++;
            if (depth > 0 || names.Contains(value.Name) || !generated.Contains(value.Name)) result.Add(value.Raw);
            if (value.Name == "END" && depth > 0) depth--;
        }
        return result;
    }

    private static List<IcsProperty> TopLevelProperties(IEnumerable<IcsProperty> values)
    {
        var result = new List<IcsProperty>(); var depth = 0;
        foreach (var value in values)
        {
            if (value.Name == "BEGIN") depth++;
            else if (value.Name == "END" && depth > 0) depth--;
            else if (depth == 0) result.Add(value);
        }
        return result;
    }

    internal static string ReplaceCalendarEvent(string resource, JsonObject appointment)
    {
        using var item = JsonDocument.Parse(new JsonArray(appointment.DeepClone()).ToJsonString());
        var replacementCalendar = WriteIcs("ics-termine", item.RootElement).Text;
        var replacement = EventBlock().Match(replacementCalendar);
        if (!replacement.Success) throw new InvalidDataException("Der Termin konnte nicht geschrieben werden.");
        var matches = EventBlock().Matches(resource).Cast<Match>().Where(match =>
        {
            try
            {
                var parsed = ParseIcs(match.Value);
                return parsed.Termine.Count == 1 && parsed.Termine[0]?["uid"]?.GetValue<string>() == appointment["uid"]?.GetValue<string>();
            }
            catch (Exception) { return false; }
        }).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("Die Kalenderressource enthält nicht genau einen passenden Termin.");
        var target = matches[0];
        return resource[..target.Index] + replacement.Value.TrimEnd('\r', '\n') + resource[(target.Index + target.Length)..];
    }

    private static void ApplyIcsRoundtrip(List<string> lines, JsonElement item)
    {
        if (!item.TryGetProperty("icsRoundtrip", out var metadata) || metadata.ValueKind != JsonValueKind.Array) return;
        var raw = metadata.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String).Select(value => value.GetString() ?? "")
            .Where(ValidIcsRoundtripLine).ToArray();
        var replace = raw.Select(PropertyName).Where(name => name is "DTSTART" or "DTEND" or "DUE" or "DURATION" or "RRULE" or "RDATE" or "EXDATE" or "EXRULE" or "RECURRENCE-ID").ToHashSet();
        lines.RemoveAll(line => replace.Contains(PropertyName(line)));
        lines.AddRange(raw);
    }

    private static int CountRejectedIcsRoundtrip(JsonElement item)
    {
        if (!item.TryGetProperty("icsRoundtrip", out var metadata) || metadata.ValueKind != JsonValueKind.Array) return 0;
        return metadata.EnumerateArray().Count(value => value.ValueKind != JsonValueKind.String ||
            !ValidIcsRoundtripLine(value.GetString() ?? ""));
    }

    private static bool ValidIcsRoundtripLine(string value) => value.Length <= 32768 &&
        Regex.IsMatch(value, "^[A-Za-z0-9-]+(?:;[^\\r\\n:]*)?:[^\\r\\n]*$");

    internal static void RejectLocalIcsAttachments(string text)
    {
        foreach (var line in Unfold(text))
        {
            if (PropertyName(line) != "ATTACH") continue;
            var quoted = false; var colon = -1;
            for (var index = 0; index < line.Length; index++)
            {
                if (line[index] == '"') quoted = !quoted;
                else if (line[index] == ':' && !quoted) { colon = index; break; }
            }
            if (colon < 0) continue;
            var value = line[(colon + 1)..].Trim();
            if (value.StartsWith("file:", StringComparison.OrdinalIgnoreCase) ||
                Regex.IsMatch(value, "^(?:[A-Za-z]:[\\\\/]|\\\\\\\\|/)") ||
                value.StartsWith("~/", StringComparison.Ordinal) || value.StartsWith("~\\", StringComparison.Ordinal))
                throw new InvalidOperationException("CalDAV-Synchronisierung gesperrt: Ein ICS-Anhang verweist auf einen lokalen Dateipfad. Die lokalen Rohdaten bleiben erhalten.");
        }
    }

    private static string PropertyName(string line) => line.Split(':', 2)[0].Split(';', 2)[0].ToUpperInvariant();
    private static long IcsModified(IEnumerable<IcsProperty> values) => ParseTimestamp(First(values, "LAST-MODIFIED")?.Value ?? First(values, "DTSTAMP")?.Value ?? "");

    private static IcsProperty? ParseIcsProperty(string line)
    {
        var colon = line.IndexOf(':'); if (colon < 1) return null;
        var head = line[..colon].Split(';');
        return new IcsProperty(head[0].ToUpperInvariant(), line[(colon + 1)..], head.Skip(1).ToArray());
    }

    private static IcsProperty? First(IEnumerable<IcsProperty> values, string name) => values.FirstOrDefault(value => value.Name == name);
    private static (DateTime DateTime, bool AllDay) ParseIcsDate(IcsProperty property)
    {
        var allDay = property.Parameters.Any(value => value.Equals("VALUE=DATE", StringComparison.OrdinalIgnoreCase)) || property.Value.Length == 8;
        var formats = allDay ? new[] { "yyyyMMdd" } : new[] { "yyyyMMdd'T'HHmmss'Z'", "yyyyMMdd'T'HHmmss", "yyyyMMdd'T'HHmm" };
        if (!DateTime.TryParseExact(property.Value, formats, CultureInfo.InvariantCulture,
                property.Value.EndsWith('Z') ? DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal : DateTimeStyles.None, out var value)) throw new InvalidDataException();
        if (property.Value.EndsWith('Z')) value = value.ToLocalTime();
        else if (property.Parameters.FirstOrDefault(parameter => parameter.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase)) is { } zoneParameter)
        {
            var zoneId = zoneParameter[5..].Trim('"');
            TimeZoneInfo zone;
            try { zone = TimeZoneInfo.FindSystemTimeZoneById(zoneId); }
            catch (TimeZoneNotFoundException)
            {
                if (!TimeZoneInfo.TryConvertIanaIdToWindowsId(zoneId, out var windowsId)) throw new InvalidDataException($"Unbekannte Zeitzone: {zoneId}");
                zone = TimeZoneInfo.FindSystemTimeZoneById(windowsId);
            }
            value = TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(value, DateTimeKind.Unspecified), zone).ToLocalTime();
        }
        return (value, allDay);
    }

    private static string RecurrenceKind(string rule)
    {
        if (rule.Length == 0) return "none";
        if (RRuleValue(rule, "INTERVAL") is { Length: > 0 } interval &&
            (!int.TryParse(interval, out var parsed) || parsed < 1 || parsed > 3660)) return "";
        if (rule.Split(';').Select(part => part.Split('=', 2)[0].ToUpperInvariant()).Any(name => name is not ("FREQ" or "INTERVAL" or "UNTIL"))) return "";
        var frequency = RRuleValue(rule, "FREQ").ToUpperInvariant();
        if (RRuleValue(rule, "INTERVAL") is { Length: > 0 } value && value != "1" &&
            frequency is not ("DAILY" or "WEEKLY")) return "";
        return frequency switch { "DAILY" => "daily", "WEEKLY" => "weekly", "MONTHLY" => "monthly", "YEARLY" => "yearly", _ => "" };
    }
    private static (string Form, int Ordinal, string Weekday) MonthlyWeekday(string rule)
    {
        if (rule.Length == 0) return ("", 0, "");
        var parts = rule.Split(';').Select(value => value.Split('=', 2)).ToArray();
        if (parts.Any(part => part.Length != 2) || parts.Select(part => part[0].ToUpperInvariant()).Distinct().Count() != parts.Length ||
            parts.Any(part => part[0].ToUpperInvariant() is not ("FREQ" or "INTERVAL" or "UNTIL" or "BYDAY" or "BYSETPOS")) ||
            !RRuleValue(rule, "FREQ").Equals("MONTHLY", StringComparison.OrdinalIgnoreCase) ||
            RRuleValue(rule, "INTERVAL") is { Length: > 0 } interval && interval != "1") return ("", 0, "");
        var byDay = RRuleValue(rule, "BYDAY").ToUpperInvariant();
        var bySetPos = RRuleValue(rule, "BYSETPOS");
        var ordinalDay = Regex.Match(byDay, "^(-1|[1-4])(MO|TU|WE|TH|FR|SA|SU)$");
        if (ordinalDay.Success && bySetPos.Length == 0)
            return ("byday", int.Parse(ordinalDay.Groups[1].Value), ordinalDay.Groups[2].Value);
        if (Regex.IsMatch(byDay, "^(MO|TU|WE|TH|FR|SA|SU)$") && Regex.IsMatch(bySetPos, "^(-1|[1-4])$"))
            return ("bysetpos", int.Parse(bySetPos), byDay);
        return ("", 0, "");
    }
    private static string RRuleValue(string rule, string name) => rule.Split(';').Select(value => value.Split('=', 2)).FirstOrDefault(parts => parts.Length == 2 && parts[0].Equals(name, StringComparison.OrdinalIgnoreCase))?.ElementAt(1) ?? "";
    private static string ParseCompactDate(string value) => value.Length >= 8 && DateOnly.TryParseExact(value[..8], "yyyyMMdd", out var date) ? date.ToString("yyyy-MM-dd") : "";
    private static string IcsText(string value) => value.Replace("\\n", "\n", StringComparison.OrdinalIgnoreCase).Replace("\\,", ",").Replace("\\;", ";").Replace("\\\\", "\\");
    private static int TaskPriority(string? value) => int.TryParse(value, out var priority) ? priority <= 3 ? 1 : priority >= 7 ? 3 : 2 : 2;

    private static Dictionary<string, List<VCardEntry>> ParseVCardProperties(IEnumerable<string> lines)
    {
        var result = new Dictionary<string, List<VCardEntry>>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in lines)
        {
            var colon = line.IndexOf(':'); if (colon < 1) continue;
            var head = SplitVCardHeader(line[..colon]); var name = head[0].Split('.').Last().ToUpperInvariant();
            var types = head.Skip(1).SelectMany(value => value.StartsWith("TYPE=", StringComparison.OrdinalIgnoreCase) ? value[5..].Split(',') : new[] { value }).Select(value => value.ToUpperInvariant()).ToArray();
            if (!result.TryGetValue(name, out var list)) result[name] = list = new List<VCardEntry>();
            list.Add(new VCardEntry(line[(colon + 1)..], types, head.Skip(1).ToArray(), ""));
        }
        return result;
    }
    private static string[] SplitVCardHeader(string value)
    {
        var result = new List<string>(); var current = new StringBuilder(); var quoted = false;
        foreach (var character in value)
        {
            if (character == '"') quoted = !quoted;
            if (character == ';' && !quoted) { result.Add(current.ToString()); current.Clear(); }
            else current.Append(character);
        }
        result.Add(current.ToString()); return result.ToArray();
    }
    private static JsonArray PreservedParameters(VCardEntry entry) => new(entry.Parameters
        .Where(parameter => !parameter.StartsWith("TYPE=", StringComparison.OrdinalIgnoreCase) &&
            !parameter.Equals("TYPE", StringComparison.OrdinalIgnoreCase) &&
            !parameter.StartsWith("ENCODING=", StringComparison.OrdinalIgnoreCase) &&
            !parameter.Equals("QUOTED-PRINTABLE", StringComparison.OrdinalIgnoreCase) &&
            !parameter.StartsWith("CHARSET=", StringComparison.OrdinalIgnoreCase) &&
            !parameter.StartsWith("VALUE=", StringComparison.OrdinalIgnoreCase) && SafeParameter(parameter))
        .Where(parameter => !new[] { "HOME", "WORK", "CELL", "VOICE", "FAX", "PAGER", "PREF", "INTERNET" }
            .Contains(parameter, StringComparer.OrdinalIgnoreCase))
        .Select(parameter => JsonValue.Create(parameter)).ToArray());
    private static JsonArray UnknownVCardLines(IEnumerable<string> lines) => new(lines
        .Where(SafeUnknownVCardLine).Select(line => JsonValue.Create(line)).ToArray());
    private static bool SafeParameter(string value) => value.Length <= 1024 &&
        Regex.IsMatch(value, "^[A-Za-z0-9-]+(?:=(?:[^\\r\\n\\\";:,]+|\\\"[^\\r\\n\\\"]*\\\"))?$");
    private static bool SafeUnknownVCardLine(string line)
    {
        if (line.Length is < 3 or > 65536 || line.IndexOfAny(['\r', '\n']) >= 0) return false;
        var colon = line.IndexOf(':'); if (colon < 1) return false;
        var name = line[..colon].Split(';')[0].Split('.').Last().ToUpperInvariant();
        return name is not ("BEGIN" or "END" or "VERSION" or "N" or "FN" or "ORG" or "TEL" or "EMAIL" or "ADR" or "NOTE" or "PHOTO" or "BDAY" or "UID" or "REV" or "X-ABLABEL" or "X-MAGNOLIE-KONTAKTPERSON-NAME" or "X-MAGNOLIE-KONTAKTPERSON-TELEFON" or "X-MAGNOLIE-KONTAKTPERSON-STATUS" or "X-MAGNOLIE-NOTFALLKONTAKT" or "X-MAGNOLIE-SOZIALES-MEDIUM");
    }
    private static string Value(Dictionary<string, List<VCardEntry>> values, string name) => VCardText(RawValue(values, name));
    private static string RawValue(Dictionary<string, List<VCardEntry>> values, string name) => values.TryGetValue(name, out var list) ? list.FirstOrDefault()?.Raw ?? "" : "";
    private static IEnumerable<VCardEntry> Entries(Dictionary<string, List<VCardEntry>> values, string name) => values.TryGetValue(name, out var list) ? list : Enumerable.Empty<VCardEntry>();
    private static string[] SplitVCard(string value)
    {
        var parts = new List<string>(); var current = new StringBuilder(); var escaped = false;
        foreach (var character in value)
        {
            if (character == ';' && !escaped) { parts.Add(VCardText(current.ToString())); current.Clear(); continue; }
            current.Append(character);
            escaped = character == '\\' && !escaped;
            if (character != '\\') escaped = false;
        }
        parts.Add(VCardText(current.ToString())); return parts.ToArray();
    }
    private static string VCardText(string value) => value.Replace("\\n", "\n", StringComparison.OrdinalIgnoreCase).Replace("\\,", ",").Replace("\\;", ";").Replace("\\\\", "\\");
    private static string CleanUri(string value, string prefix) => value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ? value[prefix.Length..] : value;
    private static bool ValidEmail(string value) => value.Length is > 2 and <= 254 && value.Contains('@') && !value.EndsWith(".invalid", StringComparison.OrdinalIgnoreCase);
    private static string ParseBirthday(string value)
    {
        value = value.Trim();
        if (Regex.IsMatch(value, "^--\\d{4}$")) value = "--" + value[2..4] + "-" + value[4..];
        if (TryParseCanonicalDate(value, out _, out _, out _)) return value;
        if (Regex.IsMatch(value, "^\\d{8}$") && DateOnly.TryParseExact(value, "yyyyMMdd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var compact)) return compact.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        return "";
    }

    internal static bool TryParseCanonicalDate(string value, out DateOnly? fullDate, out int month, out int day)
    {
        fullDate = null; month = day = 0;
        if (value.Length == 10 && DateOnly.TryParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var parsed) && parsed.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) == value)
        {
            fullDate = parsed; month = parsed.Month; day = parsed.Day; return true;
        }
        if (!Regex.IsMatch(value, "^--\\d{2}-\\d{2}$") || !int.TryParse(value.AsSpan(2, 2), out month) ||
            !int.TryParse(value.AsSpan(5, 2), out day) || month is < 1 or > 12) return false;
        var maximum = month switch { 2 => 29, 4 or 6 or 9 or 11 => 30, _ => 31 };
        return day >= 1 && day <= maximum;
    }
    private static string Photo(Dictionary<string, List<VCardEntry>> values)
    {
        var entry = Entries(values, "PHOTO").FirstOrDefault(); if (entry is null) return "";
        var photo = entry.Value.Trim();
        if (photo.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase) && TryPhotoData(photo, out _, out _)) return photo;
        if (photo.Length <= 3_600_000 && Regex.IsMatch(photo, "^[A-Za-z0-9+/=\\s]+$"))
        {
            try
            {
                var bytes = Convert.FromBase64String(Regex.Replace(photo, "\\s", "")); if (bytes.Length > 2_700_000) return "";
                var type = entry.Types.FirstOrDefault(type => type is "JPEG" or "JPG" or "PNG" or "GIF" or "WEBP") ?? "JPEG";
                return $"data:image/{(type == "JPG" ? "jpeg" : type.ToLowerInvariant())};base64,{Convert.ToBase64String(bytes)}";
            }
            catch (FormatException) { }
        }
        return "";
    }
    private static JsonArray MagnolieJsonEntries(Dictionary<string, List<VCardEntry>> values, string name)
    {
        var result = new JsonArray();
        foreach (var entry in Entries(values, name))
            try { if (JsonNode.Parse(entry.Value) is JsonObject value) result.Add(value); } catch (JsonException) { }
        return result;
    }
    private static void AddMagnolieJsonEntries(List<string> lines, JsonElement contact, string field, string property)
    {
        if (!contact.TryGetProperty(field, out var entries) || entries.ValueKind != JsonValueKind.Array) return;
        foreach (var entry in entries.EnumerateArray()) if (entry.ValueKind == JsonValueKind.Object) lines.Add(property + ":" + V(entry.GetRawText()));
    }

    private static (JsonObject Contact, string Name, string Birthday, bool UnknownYear)? ContactFromFields(Dictionary<string, List<string>> fields, string photo)
    {
        string One(params string[] names) => Field(fields, names);
        IEnumerable<string> Many(params string[] names) => names.SelectMany(name => fields.TryGetValue(name, out var values) ? values : Enumerable.Empty<string>()).Where(value => value.Length > 0);
        var first = One("givenName", "first-name"); var last = One("sn", "surname", "last-name"); var display = One("cn", "displayName");
        if (first.Length + last.Length == 0 && display.Length > 0) { var split = display.LastIndexOf(' '); if (split > 0) { first = display[..split]; last = display[(split + 1)..]; } else last = display; }
        var emails = Many("mail", "email", "primaryEmail", "secondEmail", "mozillaSecondEmail").Where(ValidEmail).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        var phones = new JsonArray();
        void Phones(string[] names, params string[] types) { foreach (var value in Many(names)) phones.Add(new JsonObject { ["wert"] = value, ["typen"] = new JsonArray(types.Select(type => JsonValue.Create(type)).ToArray()) }); }
        Phones(new[] { "telephoneNumber", "phone" }, "VOICE"); Phones(new[] { "homePhone" }, "HOME", "VOICE"); Phones(new[] { "workPhone" }, "WORK", "VOICE"); Phones(new[] { "mobile", "cell", "cellphone" }, "CELL"); Phones(new[] { "facsimileTelephoneNumber", "fax" }, "FAX"); Phones(new[] { "pager", "pagerTelephoneNumber" }, "PAGER");
        var street = One("street", "streetAddress", "homeStreet", "mozillaHomeStreet"); var city = One("l", "locality", "city", "homeLocalityName", "mozillaHomeLocalityName");
        var postal = One("postalCode", "zip", "homePostalCode", "mozillaHomePostalCode"); var country = One("c", "countryName", "homeCountryName", "mozillaHomeCountryName");
        var birthdayRaw = One("dateOfBirth", "birthDate"); var unknown = false;
        if (birthdayRaw.Length == 0 && int.TryParse(One("birthMonth", "mozillaBirthMonth"), out var month) && int.TryParse(One("birthDay", "mozillaBirthDay"), out var day))
        {
            var yearText = One("birthYear", "mozillaBirthYear");
            unknown = yearText.Length == 0;
            birthdayRaw = unknown ? $"--{month:00}-{day:00}" : Regex.IsMatch(yearText, "^\\d{4}$")
                ? $"{yearText}-{month:00}-{day:00}" : "";
        }
        var birthday = ParseBirthday(birthdayRaw); unknown |= birthdayRaw.StartsWith("--", StringComparison.Ordinal);
        var name = (first + " " + last).Trim(); var company = One("o", "organization", "company"); if (name.Length == 0) name = display.Length > 0 ? display : company;
        if (name.Length == 0 && emails.Length == 0) return null;
        var notes = Many("description", "info", "notes", "remarks", "custom1", "custom2", "custom3", "custom4", "mozillaCustom1", "mozillaCustom2", "mozillaCustom3", "mozillaCustom4", "homeUrl", "workUrl").Distinct().ToArray();
        var contact = new JsonObject { ["uid"] = One("entryUUID", "uid"), ["vorname"] = first, ["nachname"] = last, ["firma"] = company,
            ["strasse"] = street, ["plz"] = postal, ["ort"] = city, ["anschriften"] = new JsonArray(new JsonObject { ["strasse"] = street, ["plz"] = postal, ["ort"] = city, ["land"] = country, ["typen"] = new JsonArray("HOME") }),
            ["telefon"] = phones.FirstOrDefault()?["wert"]?.ToString() ?? "", ["mobil"] = phones.FirstOrDefault(node => node?["typen"]?.AsArray().Any(type => type?.ToString() == "CELL") == true)?["wert"]?.ToString() ?? "",
            ["telefone"] = phones, ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(email => JsonValue.Create(email)).ToArray()), ["notiz"] = string.Join("\n", notes),
            ["foto"] = NormalizePhoto(photo), ["geburtstag"] = birthday, ["geburtstagJahrUnbekannt"] = unknown, ["geaendert"] = 0 };
        return (contact, name, birthday, unknown);
    }

    private static JsonObject BirthdayNode(string name, string date, bool unknown) => new() { ["name"] = name, ["datum"] = date, ["jahrUnbekannt"] = unknown };
    private static string Field(Dictionary<string, List<string>> fields, params string[] names) => names.SelectMany(name => fields.TryGetValue(name, out var values) ? values : Enumerable.Empty<string>()).FirstOrDefault(value => !string.IsNullOrWhiteSpace(value))?.Trim() ?? "";
    private static string NormalizePhoto(string value) => value.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase) && TryPhotoData(value, out _, out _) ? value : "";

    private static IEnumerable<string> LdifEmails(JsonElement contact)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var fallback = J(contact, "email").Trim(); if (ValidEmail(fallback) && seen.Add(fallback)) yield return fallback;
        if (contact.TryGetProperty("emailEintraege", out var entries) && entries.ValueKind == JsonValueKind.Array)
            foreach (var entry in entries.EnumerateArray()) { var value = J(entry, "wert").Trim(); if (ValidEmail(value) && seen.Add(value)) yield return value; }
        if (contact.TryGetProperty("emails", out var values) && values.ValueKind == JsonValueKind.Array)
            foreach (var entry in values.EnumerateArray()) { var value = entry.ValueKind == JsonValueKind.String ? entry.GetString()?.Trim() ?? "" : ""; if (ValidEmail(value) && seen.Add(value)) yield return value; }
    }

    private static IEnumerable<(string Attribute, string Value)> LdifPhones(JsonElement contact)
    {
        var entries = new List<JsonElement>();
        if (contact.TryGetProperty("telefone", out var phones) && phones.ValueKind == JsonValueKind.Array) entries.AddRange(phones.EnumerateArray());
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries)
        {
            var value = J(entry, "wert").Trim(); if (value.Length == 0 || !seen.Add(value)) continue;
            var types = entry.TryGetProperty("typen", out var array) && array.ValueKind == JsonValueKind.Array
                ? array.EnumerateArray().Select(type => type.GetString()?.ToUpperInvariant() ?? "").ToHashSet() : new HashSet<string>();
            var attribute = types.Contains("FAX") ? "facsimileTelephoneNumber" : types.Contains("PAGER") ? "pager" :
                types.Contains("CELL") || types.Contains("MOBILE") ? "mobile" : types.Contains("HOME") ? "homePhone" :
                types.Contains("WORK") ? "workPhone" : "telephoneNumber";
            yield return (attribute, value);
        }
        foreach (var fallback in new[] { ("telephoneNumber", J(contact, "telefon")), ("mobile", J(contact, "mobil")) })
            if (fallback.Item2.Trim() is { Length: > 0 } value && seen.Add(value)) yield return (fallback.Item1, value);
    }

    private static IEnumerable<JsonElement> LdifAddresses(JsonElement contact)
    {
        var legacy = new[] { "strasse", "plz", "ort" }.Any(field => J(contact, field).Trim().Length > 0);
        var legacyPresent = false;
        if (contact.TryGetProperty("anschriften", out var addresses) && addresses.ValueKind == JsonValueKind.Array)
            foreach (var address in addresses.EnumerateArray()) if (address.ValueKind == JsonValueKind.Object &&
                new[] { "strasse", "plz", "ort", "land" }.Any(field => J(address, field).Trim().Length > 0))
            {
                legacyPresent |= legacy && new[] { "strasse", "plz", "ort" }.All(field =>
                    J(address, field).Trim() == J(contact, field).Trim());
                yield return address;
            }
        if (legacy && !legacyPresent) yield return contact;
    }

    private static string LdifUid(JsonElement contact, HashSet<string> used)
    {
        var raw = J(contact, "uid").Trim(); var fingerprint = LdifFingerprint(contact);
        var basis = Regex.IsMatch(raw, "^[A-Za-z0-9._-]{1,64}$") ? raw : raw.Length > 0
            ? "magnolie-" + Sha256(raw)[..24] : "magnolie-" + fingerprint[..24];
        var uid = basis;
        if (used.Contains(uid))
        {
            uid = basis[..Math.Min(53, basis.Length)] + "-" + fingerprint[..10]; var number = 2;
            while (used.Contains(uid)) { var suffix = "-" + number++; uid = basis[..Math.Min(64 - suffix.Length, basis.Length)] + suffix; }
        }
        used.Add(uid); return uid;
    }

    private static string LdifFingerprint(JsonElement contact)
    {
        var parts = new List<string> { J(contact, "vorname"), J(contact, "nachname"), J(contact, "firma"), J(contact, "notiz"), J(contact, "geburtstag") };
        parts.AddRange(LdifEmails(contact));
        if (contact.TryGetProperty("telefone", out var phones) && phones.ValueKind == JsonValueKind.Array)
            foreach (var phone in phones.EnumerateArray())
            {
                var types = phone.TryGetProperty("typen", out var typeArray) && typeArray.ValueKind == JsonValueKind.Array
                    ? typeArray.EnumerateArray().Select(type => Regex.Replace((type.GetString() ?? "").ToUpperInvariant(), "[^A-Z0-9-]", "")).Where(type => type.Length > 0).OrderBy(type => type) : Enumerable.Empty<string>();
                parts.AddRange(new[] { J(phone, "wert"), string.Join(',', types) });
            }
        else foreach (var phone in LdifPhones(contact)) parts.AddRange(new[] { phone.Value, phone.Attribute == "mobile" ? "CELL" : "VOICE" });
        foreach (var address in LdifAddresses(contact)) parts.AddRange(new[] { J(address, "strasse"), J(address, "plz"), J(address, "ort"), J(address, "land") });
        return Sha256(string.Join('\u001f', parts));
    }

    private static string Sha256(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();

    private static string EscapeDn(string value)
    {
        var result = new StringBuilder(); var runes = value.EnumerateRunes().ToArray();
        for (var index = 0; index < runes.Length; index++)
        {
            var rune = runes[index]; var text = rune.ToString();
            if (rune.Value == 0) result.Append("\\00");
            else if (",+\"\\<>;=".Contains(text, StringComparison.Ordinal) || index == 0 && text is " " or "#" || index == runes.Length - 1 && text == " ") result.Append('\\').Append(text);
            else if (rune.Value < 32 || rune.Value == 127) foreach (var octet in Encoding.UTF8.GetBytes(text)) result.Append('\\').Append(octet.ToString("X2"));
            else result.Append(text);
        }
        return result.ToString();
    }

    private static string LdifLine(string name, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value); var base64 = value.StartsWith(' ') || value.StartsWith(':') || value.StartsWith('<') || value.EndsWith(' ') ||
            bytes.Any(octet => octet is 0 or 10 or 13 || octet >= 128);
        return FoldLdif(name + (base64 ? ":: " + Convert.ToBase64String(bytes) : ": " + value));
    }
    private static string LdifBinaryLine(string name, byte[] value) => FoldLdif(name + ":: " + Convert.ToBase64String(value));
    private static string FoldLdif(string line)
    {
        var result = new StringBuilder(); var bytes = 0; var limit = 76;
        foreach (var rune in line.EnumerateRunes())
        {
            var length = rune.Utf8SequenceLength;
            if (bytes > 0 && bytes + length > limit) { result.Append("\r\n "); bytes = 0; limit = 75; }
            result.Append(rune); bytes += length;
        }
        return result.ToString();
    }
    private static bool TryLdifJpeg(string value, out byte[] jpeg)
    {
        jpeg = Array.Empty<byte>(); var match = Regex.Match(value, "^data:image/(?:jpeg|jpg|png|gif|webp);base64,([A-Za-z0-9+/=]+)$", RegexOptions.IgnoreCase);
        if (!match.Success) return false;
        try { jpeg = Convert.FromBase64String(match.Groups[1].Value); }
        catch (FormatException) { return false; }
        return jpeg.Length <= 2_700_000 && jpeg.AsSpan().StartsWith(new byte[] { 0xff, 0xd8, 0xff });
    }

    private static JsonArray LdifPostalAddresses(Dictionary<string, List<string>> fields)
    {
        var result = new JsonArray();
        foreach (var value in new[] { "postalAddress", "homePostalAddress" }.SelectMany(name => fields.TryGetValue(name, out var values) ? values : Enumerable.Empty<string>()))
        {
            const string marker = "\0MAGNOLIE-DOLLAR\0"; var parts = value.Replace("\\24", marker).Split('$').Select(part => part.Replace(marker, "$" ).Trim()).Where(part => part.Length > 0).ToArray();
            if (parts.Length == 0) continue;
            var street = parts[0]; var postal = ""; var city = ""; var country = "";
            foreach (var part in parts.Skip(1))
            {
                var match = Regex.Match(part, "^(\\d{4,6})\\s+(.+)$");
                if (match.Success) { postal = match.Groups[1].Value; city = match.Groups[2].Value; }
                else if (city.Length == 0 && !Regex.IsMatch(part, "^[A-Z]{2}$", RegexOptions.IgnoreCase)) city = part;
                else if (country.Length == 0) country = part;
            }
            result.Add(new JsonObject { ["strasse"] = street, ["plz"] = postal, ["ort"] = city, ["land"] = country, ["typen"] = new JsonArray("HOME") });
        }
        return result;
    }

    private static List<List<string>> ParseCsv(string text)
    {
        var firstLine = text.Split('\n').FirstOrDefault(line => line.Trim().Length > 0) ?? "";
        var delimiter = firstLine.Count(character => character == ';') > firstLine.Count(character => character == ',') ? ';' : ',';
        var rows = new List<List<string>>(); var row = new List<string>(); var field = new StringBuilder(); var quoted = false;
        for (var index = 0; index <= text.Length; index++)
        {
            var character = index < text.Length ? text[index] : '\n';
            if (character == '"') { if (quoted && index + 1 < text.Length && text[index + 1] == '"') { field.Append('"'); index++; } else quoted = !quoted; }
            else if (character == delimiter && !quoted) { row.Add(field.ToString()); field.Clear(); }
            else if ((character == '\n' || character == '\r') && !quoted) { if (character == '\r' && index + 1 < text.Length && text[index + 1] == '\n') index++; row.Add(field.ToString()); field.Clear(); if (row.Any(value => value.Trim().Length > 0)) rows.Add(row); row = new(); }
            else field.Append(character);
        }
        return rows;
    }

    private static string NormalizeHeader(string value) => Regex.Replace(value.Trim().ToUpperInvariant().Replace("Ä", "AE").Replace("Ö", "OE").Replace("Ü", "UE").Replace("ß", "SS"), "[^A-Z]", "");
    private static (string Date, string Time, bool Ambiguous) ParseLotusDate(string value)
    {
        value = value.Trim(); if (value.Length == 0) return ("", "", false);
        var slash = Regex.Match(value, "^(\\d{1,2})/(\\d{1,2})/(\\d{2,4})(?:[ ,]+(\\d{1,2}):(\\d{2})(?::\\d{2})?\\s*([AP]M)?)?$", RegexOptions.IgnoreCase);
        if (slash.Success)
        {
            var first = int.Parse(slash.Groups[1].Value); var second = int.Parse(slash.Groups[2].Value); var ampm = slash.Groups[6].Value;
            if (ampm.Length == 0 && first <= 12 && second <= 12 && first != second) return ("", "", true);
            var month = ampm.Length > 0 || second > 12 ? first : second; var day = ampm.Length > 0 || second > 12 ? second : first;
            var year = int.Parse(slash.Groups[3].Value); if (year < 100) year += year >= 70 ? 1900 : 2000;
            if (!DateOnly.TryParseExact($"{year:0000}-{month:00}-{day:00}", "yyyy-MM-dd", out var date)) return ("", "", false);
            var hour = slash.Groups[4].Success ? int.Parse(slash.Groups[4].Value) : 0; if (ampm.Equals("PM", StringComparison.OrdinalIgnoreCase) && hour < 12) hour += 12; if (ampm.Equals("AM", StringComparison.OrdinalIgnoreCase) && hour == 12) hour = 0;
            return (date.ToString("yyyy-MM-dd"), slash.Groups[4].Success ? $"{hour:00}:{slash.Groups[5].Value}" : "", false);
        }
        foreach (var format in new[] { "dd.MM.yyyy HH:mm", "dd.MM.yyyy", "yyyy-MM-dd HH:mm", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd" })
            if (DateTime.TryParseExact(value, format, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed)) return (parsed.ToString("yyyy-MM-dd"), format.Contains("HH") ? parsed.ToString("HH:mm") : "", false);
        return ("", "", false);
    }

    private static bool IsYes(string value) => new[] { "JA", "J", "YES", "Y", "TRUE", "WAHR", "1", "X" }.Contains(value.Trim().ToUpperInvariant());
    private static string LotusDate(string date, string time) => DateOnly.TryParseExact(date, "yyyy-MM-dd", out var parsed) ? parsed.ToString("dd.MM.yyyy") + (time.Length > 0 ? " " + time : "") : "";
    private static void WriteCsvRow(StringBuilder output, IEnumerable<string> values) => output.Append(string.Join(",",
        values.Select(value => "\"" + SafeCsv(value).Replace("\"", "\"\"") + "\""))).Append("\r\n");
    private static string SafeCsv(string value)
    {
        var trimmed = value.TrimStart();
        return trimmed.Length > 0 && "=+-@".Contains(trimmed[0]) ? "'" + value : value;
    }
    private static ExchangeImportResult EmptyImport() => new(new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray());

    private static IEnumerable<string> TextValues(JsonElement item, string arrayName, string field, params string[] fallback)
    {
        var values = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (item.TryGetProperty(arrayName, out var array) && array.ValueKind == JsonValueKind.Array)
            foreach (var entry in array.EnumerateArray()) { var value = J(entry, field); if (value.Length > 0) values.Add(value); }
        foreach (var value in fallback) if (value.Length > 0) values.Add(value);
        return values;
    }
    private static void AddTypedEntries(List<string> lines, JsonElement item, string arrayName, string property, string field, params string[] fallback)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (item.TryGetProperty(arrayName, out var array) && array.ValueKind == JsonValueKind.Array)
            foreach (var entry in array.EnumerateArray())
            {
                var value = J(entry, field); if (value.Length == 0 || !seen.Add(value) || property == "EMAIL" && !ValidEmail(value)) continue;
                var types = entry.TryGetProperty("typen", out var typeArray) && typeArray.ValueKind == JsonValueKind.Array ? typeArray.EnumerateArray().Select(type => type.GetString() ?? "").Where(type => Regex.IsMatch(type, "^[A-Za-z0-9-]+$")).ToArray() : Array.Empty<string>();
                lines.Add(property + (types.Length > 0 ? ";TYPE=" + string.Join(',', types) : "") + ExtraParameters(entry) + ":" + V(value));
            }
        foreach (var value in fallback) if (value.Length > 0 && seen.Add(value) && (property != "EMAIL" || ValidEmail(value))) lines.Add($"{property}:{V(value)}");
    }
    private static void AddAddress(List<string> lines, JsonElement address)
    {
        var street = J(address, "strasse"); var city = J(address, "ort"); var postal = J(address, "plz"); var country = J(address, "land");
        if (street.Length + city.Length + postal.Length + country.Length == 0) return;
        var types = address.TryGetProperty("typen", out var typeArray) && typeArray.ValueKind == JsonValueKind.Array ? typeArray.EnumerateArray().Select(type => type.GetString() ?? "").Where(type => Regex.IsMatch(type, "^[A-Za-z0-9-]+$")).ToArray() : Array.Empty<string>();
        lines.Add("ADR" + (types.Length > 0 ? ";TYPE=" + string.Join(',', types) : "") + ExtraParameters(address) + $":;;{V(street)};{V(city)};;{V(postal)};{V(country)}");
    }
    private static string ExtraParameters(JsonElement entry) => entry.TryGetProperty("vcardParameter", out var values) && values.ValueKind == JsonValueKind.Array
        ? string.Concat(values.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String && SafeParameter(value.GetString() ?? "")).Select(value => ";" + value.GetString())) : "";
    private static bool TryPhotoData(string value, out string mediaType, out string base64)
    {
        mediaType = base64 = ""; var match = Regex.Match(value, "^data:image/(jpeg|jpg|png|gif|webp);base64,([A-Za-z0-9+/=]+)$", RegexOptions.IgnoreCase);
        if (!match.Success) return false;
        try { var bytes = Convert.FromBase64String(match.Groups[2].Value); if (bytes.Length > 2_700_000) return false; }
        catch (FormatException) { return false; }
        mediaType = match.Groups[1].Value.Equals("jpg", StringComparison.OrdinalIgnoreCase) ? "JPEG" : match.Groups[1].Value.ToUpperInvariant(); base64 = match.Groups[2].Value; return true;
    }
    private static long ParseTimestamp(string value)
    {
        foreach (var format in new[] { "yyyyMMdd'T'HHmmss'Z'", "yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm:ssK" })
            if (DateTimeOffset.TryParseExact(value, format, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var parsed)) return parsed.ToUnixTimeMilliseconds();
        return 0;
    }
    private static string J(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    private static int JInt(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : 0;
    private static long JLong(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.TryGetInt64(out var number) ? number : 0;
    private static bool JBool(JsonElement item, string name) => item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
    private static DateOnly RequiredDate(string value) => DateOnly.TryParseExact(value, "yyyy-MM-dd", out var date) ? date : throw new InvalidDataException();
    private static DateTime RequiredTime(DateOnly date, string value) => TimeOnly.TryParseExact(value, "HH:mm", out var time) ? date.ToDateTime(time) : throw new InvalidDataException();
    private static string Uid(JsonElement item) => J(item, "uid") is { Length: > 0 } uid ? uid : Guid.NewGuid().ToString("N") + "@magnolie";
    private static string V(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n").Replace("\n", "\\n").Replace(";", "\\;").Replace(",", "\\,");
    private static string FoldUtf8(string line)
    {
        var result = new StringBuilder(); var bytes = 0;
        foreach (var rune in line.EnumerateRunes())
        {
            var length = rune.Utf8SequenceLength;
            if (bytes + length > 75) { result.Append("\r\n "); bytes = 1; }
            result.Append(rune); bytes += length;
        }
        return result.ToString();
    }

    private sealed record IcsProperty(string Name, string Value, string[] Parameters)
    {
        internal string Raw => Name + (Parameters.Length > 0 ? ";" + string.Join(';', Parameters) : "") + ":" + Value;
    }
    private sealed record VCardEntry(string Raw, string[] Types, string[] Parameters, string Label)
    {
        internal string Value
        {
            get
            {
                if (!Parameters.Any(parameter => parameter.Contains("QUOTED-PRINTABLE", StringComparison.OrdinalIgnoreCase))) return VCardText(Raw);
                try
                {
                    var bytes = new List<byte>();
                    for (var index = 0; index < Raw.Length; index++)
                        if (Raw[index] == '=' && index + 2 < Raw.Length && byte.TryParse(Raw.AsSpan(index + 1, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var octet)) { bytes.Add(octet); index += 2; } else bytes.Add((byte)Raw[index]);
                    var charset = Parameters.FirstOrDefault(parameter => parameter.StartsWith("CHARSET=", StringComparison.OrdinalIgnoreCase))?[8..] ?? "UTF-8";
                    Encoding.RegisterProvider(CodePagesEncodingProvider.Instance); return VCardText(Encoding.GetEncoding(charset).GetString(bytes.ToArray()));
                }
                catch (ArgumentException) { return VCardText(Raw); }
            }
        }
    }
    [GeneratedRegex("BEGIN:(VCALENDAR|VEVENT|VTODO)", RegexOptions.IgnoreCase)] private static partial Regex IcsMarker();
    [GeneratedRegex("^BEGIN:VEVENT\\s*$.*?^END:VEVENT\\s*$", RegexOptions.IgnoreCase | RegexOptions.Multiline | RegexOptions.Singleline)] private static partial Regex EventBlock();
    [GeneratedRegex("BEGIN:VCARD.*?END:VCARD", RegexOptions.IgnoreCase | RegexOptions.Singleline)] private static partial Regex VCardBlock();
}
