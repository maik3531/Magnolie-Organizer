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
    JsonArray? Notizen = null,
    int FehlerhafteTermine = 0,
    int FehlerhafteAufgaben = 0)
{
    internal HashSet<string> BirthdayRepairs { get; init; } = new(StringComparer.Ordinal);
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
        using var culture = new CalendarRecurrence.WireCulture();
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
            var part = ParseImportEntry(data.ToArray(), art, fileName + "!/" + entry.FullName);
            Append(result.Termine, part.Termine); Append(result.Jahrestage, part.Jahrestage);
            Append(result.Geburtstage, part.Geburtstage); Append(result.Aufgaben, part.Aufgaben);
            Append(result.Kontakte, part.Kontakte); if (result.Notizen is not null && part.Notizen is not null) Append(result.Notizen, part.Notizen);
            if (part.Bericht.Length > 0) reports.Add(part.Bericht); read++;
            result = result with { Uebersprungen = result.Uebersprungen + part.Uebersprungen,
                Wiederholend = result.Wiederholend + part.Wiederholend,
                FehlerhafteTermine = result.FehlerhafteTermine + part.FehlerhafteTermine,
                FehlerhafteAufgaben = result.FehlerhafteAufgaben + part.FehlerhafteAufgaben };
        }
        if (read == 0) throw new InvalidDataException("Das Archiv enthält keine unterstützten Importdateien.");
        return result with { Bericht = string.Join(' ', reports) };
    }

    private static ExchangeImportResult ParseImportEntry(byte[] bytes, string art, string fileName)
    {
        var text = DecodeText(bytes); var extension = Path.GetExtension(fileName).ToLowerInvariant();
        return art switch
        {
            "ics" => ParseIcs(text, "ics:" + Sha256(fileName.Replace('\\', '/'))),
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

    internal static ExchangeImportResult ParseIcs(string text, string sourceId = "", TimeZoneInfo? timeZone = null)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        if (text.IndexOf('\0') >= 0 || !IcsMarker().IsMatch(text))
            throw new InvalidDataException("Die Datei ist kein lesbarer iCalendar-Kalender.");

        var appointments = new JsonArray();
        var anniversaries = new JsonArray();
        var birthdayRepairs = new HashSet<string>(StringComparer.Ordinal);
        var tasks = new JsonArray();
        var skipped = 0;
        var complex = 0;
        var invalidEvents = 0;
        var invalidTasks = 0;
        string? component = null;
        var componentDepth = 0;
        var components = new List<string>();
        var properties = new List<IcsProperty>();
        var timezoneBlocks = Regex.Matches(string.Join("\n", Unfold(text)), @"(?ims)^BEGIN:VTIMEZONE\s*\n.*?^END:VTIMEZONE\s*$")
            .Select(match => match.Value.TrimEnd().Split('\n')).ToArray();
        var zones = CalendarRecurrence.CalendarZones(timezoneBlocks);
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
                            var result = ParseEvent(properties, timeZone, zones, birthdayRepairs);
                            if (result.Anniversary) anniversaries.Add(result.Value);
                            else appointments.Add(result.Value);
                            if (result.Complex && !CalendarRecurrence.SupportsRules(properties.Select(value => value.Raw))) complex++;
                        }
                        else tasks.Add(ParseTask(properties, timeZone, zones));
                    }
                    catch (TimeZoneNotFoundException)
                    {
                        // Keep the source component unresolved, not skipped or scheduled
                        // in the machine zone. These civil fields are only editor metadata.
                        var top = TopLevelProperties(properties);
                        var start = First(top, "DTSTART") ?? First(top, "DUE") ??
                            (component == "VEVENT" && First(top, "STATUS")?.Value.Equals("CANCELLED", StringComparison.OrdinalIgnoreCase) == true
                                ? First(top, "RECURRENCE-ID") : null) ?? throw new InvalidDataException("Invalid calendar date.");
                        var wall = CalendarRecurrence.ParseStamp(new CalendarRecurrence.Property(start.Name, start.Value,
                            start.Parameters.Where(value => !value.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase)).ToArray()));
                        var id = First(top, "RECURRENCE-ID"); var uid = IcsText(First(top, "UID")?.Value ?? "");
                        var deferred = new JsonObject { ["uid"] = id is null ? uid : InstanceUid(uid, id), ["icsSerienUid"] = id is null ? "" : uid,
                            ["titel"] = IcsText(First(top, "SUMMARY")?.Value ?? ""), ["icsKomplex"] = true, ["icsReadOnly"] = true,
                            ["icsRoundtrip"] = IcsRoundtrip(properties, true), [component == "VEVENT" ? "datum" : "startDatum"] = wall.Wall.ToString("yyyy-MM-dd"),
                            [component == "VEVENT" ? "zeit" : "startZeit"] = wall.AllDay ? "" : wall.Wall.ToString("HH:mm") };
                        if (component == "VEVENT") appointments.Add(deferred); else tasks.Add(deferred);
                        complex++;
                    }
                    catch (Exception)
                    {
                        skipped++;
                        if (component == "VEVENT") invalidEvents++;
                        else invalidTasks++;
                    }
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
        foreach (var item in appointments.Concat(anniversaries).Concat(tasks).OfType<JsonObject>())
            if (sourceId.Length > 0) item["icsQuelleId"] = sourceId;
        foreach (var task in tasks.OfType<JsonObject>())
        {
            if (task.Remove("_icsTaskSource", out var source)) task["icsQuelleId"] = source;
            if (!task.ContainsKey("icsElternQuelleId")) task["icsElternQuelleId"] = TextField(task, "icsQuelleId");
        }
        var timezones = timezoneBlocks.Select(block => new JsonArray(block.Select(line => (JsonNode?)line).ToArray())).ToArray();
        if (timezones.Length > 0)
        {
            foreach (var item in appointments.Concat(anniversaries).Concat(tasks).OfType<JsonObject>())
            {
                item["icsTimezones"] = new JsonArray(timezones.Select(value => value.DeepClone()).ToArray());
            }
        }
        ReconcileRecurrences(appointments, timeZone);
        ReconcileRecurrences(tasks, timeZone);
        return new ExchangeImportResult(appointments, anniversaries, new JsonArray(), tasks,
            new JsonArray(), skipped, complex,
            complex > 0 ? NativeLocalization.Gettext("Some recurrence rules cannot be expanded. Their original calendar data was preserved.") : "",
            FehlerhafteTermine: invalidEvents, FehlerhafteAufgaben: invalidTasks) { BirthdayRepairs = birthdayRepairs };
    }

    internal static ExchangeExportResult WriteIcs(string art, JsonElement data)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        if (art == "ics-aufgaben") data = JsonSerializer.SerializeToElement(PrepareTaskExport(data));
        var lines = new List<string>
        {
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie Organizer//DE", "CALSCALE:GREGORIAN"
        };
        var count = 0;
        var skipped = 0;
        var rawOmitted = 0;
        var calendarComponents = new List<(string[] Component, string[][] Zones)>();
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
                var definitions = item.TryGetProperty("icsTimezones", out var zones) && zones.ValueKind == JsonValueKind.Array ?
                    zones.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.Array).Select(block => block.EnumerateArray().Select(value => value.GetString() ?? "").ToArray())
                        .Where(raw => raw.Length > 1 && raw[0].Equals("BEGIN:VTIMEZONE", StringComparison.OrdinalIgnoreCase) && raw[^1].Equals("END:VTIMEZONE", StringComparison.OrdinalIgnoreCase)).ToArray() : [];
                calendarComponents.Add((generated.ToArray(), definitions));
                count++;
            }
            catch (Exception) { skipped++; }
        }
        lines.AddRange(CalendarRecurrence.ExportCalendar(calendarComponents));
        lines.Add("END:VCALENDAR");
        var report = rawOmitted > 0
            ? $"{rawOmitted} ungültige ICS-Rohzeilen wurden beim Export verworfen."
            : "";
        return new ExchangeExportResult(string.Join("\r\n", lines.Select(FoldUtf8)) + "\r\n", count, skipped,
            report, RawOmitted: rawOmitted);
    }

    internal static JsonArray UnrepresentedContactProperties(JsonObject contact)
    {
        var lines = (contact["vcardRoundtrip"] as JsonArray ?? []).Select(node => node?.GetValue<string>() ?? "").ToArray();
        var counts = lines.GroupBy(VCardPropertyName).ToDictionary(group => group.Key, group => group.Count());
        var result = new JsonArray();
        foreach (var line in lines)
        {
            var name = VCardPropertyName(line);
            var entries = ParseVCardProperties([line]);
            var entry = Entries(entries, name).FirstOrDefault();
            var represented = name == "PRODID";
            if (entry is not null && counts[name] == 1 && PreservedParameters(entry).Count == 0)
            {
                if (name == "N" && entry.Types.Length == 0)
                    represented = SplitEscaped(entry.Raw, ';').Skip(2).Select(NameComponent).All(string.IsNullOrEmpty);
                else if (name == "ORG" && entry.Types.Length == 0)
                    represented = SplitEscaped(entry.Raw, ';').Skip(1).Select(VCardText).All(string.IsNullOrEmpty);
                else if (name == "FN" && entry.Types.Length == 0)
                {
                    var derived = string.Join(' ', new[] { ContactFields.Text(contact, "vorname"), ContactFields.Text(contact, "nachname") }.Where(value => value.Length > 0));
                    represented = contact.ContainsKey("anzeigename") || entry.Value == derived ||
                        derived.Length == 0 && entry.Value == ContactFields.Text(contact, "firma");
                }
                else if (name is "BDAY" or "ANNIVERSARY")
                {
                    var date = VCardDate(entry);
                    if (name == "BDAY" && date.StartsWith("1604-", StringComparison.Ordinal)) date = "--" + date[5..];
                    represented = (date.Length > 0 || entry.Value.Length == 0) &&
                        date == ContactFields.Text(contact, name == "BDAY" ? "geburtstag" : "jubilaeum");
                }
                else if (name == "PHOTO") represented = Photo(entries) is { Length: > 0 } photo && photo == ContactFields.Text(contact, "foto");
            }
            if (!represented) result.Add(line);
        }
        return result;
    }

    internal static ExchangeImportResult ParseVCard(string text)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        if (Encoding.UTF8.GetByteCount(text) > MaxImportBytes)
            throw new IOException(NativeLocalization.Gettext("The import file is larger than 32 megabytes."));
        var contacts = new JsonArray();
        var birthdays = new JsonArray();
        var skipped = 0;
        foreach (Match match in VCardBlock().Matches(text.ReplaceLineEndings("\n")))
        {
            var lines = UnfoldVCard(match.Value).ToArray();
            if (lines.Any(line => line.Length > 65536 && VCardPropertyName(line) != "PHOTO" &&
                SafeUnknownVCardLine(line, checkLength: false)))
                throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
            try
            {
                var values = ParseVCardProperties(lines);
                var names = SplitEscaped(RawValue(values, "N"), ';').Select(NameComponent).ToArray();
                var fullName = Value(values, "FN");
                var company = SplitVCard(RawValue(values, "ORG")).FirstOrDefault()?.Trim() ?? "";
                var lastName = names.ElementAtOrDefault(0) ?? "";
                var firstName = names.ElementAtOrDefault(1) ?? "";
                var phones = Entries(values, "TEL").Select(entry => new JsonObject
                {
                    ["wert"] = CleanUri(entry.Value, "tel:"),
                    ["typen"] = new JsonArray(entry.Types.Select(type => JsonValue.Create(type)).ToArray()),
                    ["label"] = entry.Label,
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
                    var address = new JsonObject
                    {
                        ["postfach"] = parts.ElementAtOrDefault(0) ?? "",
                        ["zusatz"] = parts.ElementAtOrDefault(1) ?? "",
                        ["strasse"] = parts.ElementAtOrDefault(2) ?? "",
                        ["ort"] = parts.ElementAtOrDefault(3) ?? "",
                        ["region"] = parts.ElementAtOrDefault(4) ?? "",
                        ["plz"] = parts.ElementAtOrDefault(5) ?? "",
                        ["land"] = parts.ElementAtOrDefault(6) ?? "",
                        ["typen"] = new JsonArray(entry.Types.Select(type => JsonValue.Create(type)).ToArray()),
                        ["label"] = entry.Label,
                        ["vcardParameter"] = PreservedParameters(entry)
                    };
                    if (address["region"]?.ToString().Length == 0) address.Remove("region");
                    return address;
                }).ToArray();
                var firstAddress = addresses.FirstOrDefault();
                var firstPhone = phones.FirstOrDefault(entry =>
                    entry["typen"]?.AsArray().Any(type => type?.ToString().Equals("CELL", StringComparison.OrdinalIgnoreCase) == false) == true);
                var mobile = phones.FirstOrDefault(entry =>
                    entry["typen"]?.AsArray().Any(type => type?.ToString().Equals("CELL", StringComparison.OrdinalIgnoreCase) == true) == true);
                var contact = new JsonObject
                {
                    ["uid"] = Value(values, "UID"), ["nachname"] = lastName, ["vorname"] = firstName,
                    ["anzeigename"] = fullName,
                    ["firma"] = company,
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
                if (firstName.Length + lastName.Length + fullName.Length + company.Length + emails.Length + phones.Length > 0) contacts.Add(contact);
                else { skipped++; continue; }
                var birthday = VCardDate(Entries(values, "BDAY").FirstOrDefault());
                var anniversaryDate = VCardDate(Entries(values, "ANNIVERSARY").FirstOrDefault()
                    ?? Entries(values, "X-ANNIVERSARY").FirstOrDefault()
                    ?? Entries(values, "X-ABDATE").FirstOrDefault(entry =>
                        entry.Label.Trim().Equals("anniversary", StringComparison.OrdinalIgnoreCase) ||
                        entry.Label.Trim().Equals("_$!<Anniversary>!$_", StringComparison.OrdinalIgnoreCase)));
                if (anniversaryDate.Length > 0) contact["jubilaeum"] = anniversaryDate;
                if (birthday.Length > 0)
                {
                    var unknownYear = birthday.StartsWith("--", StringComparison.Ordinal);
                    contact["geburtstag"] = birthday;
                    contact["geburtstagJahrUnbekannt"] = unknownYear;
                    // The web importer derives the linked birthday from this contact.
                }
            }
            catch (Exception) { skipped++; }
        }
        if (contacts.Count == 0) throw new InvalidDataException("Die Datei enthält keine verwendbaren vCard-Kontakte.");
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeExportResult WriteVCard(JsonElement data)
    {
        using var culture = new CalendarRecurrence.WireCulture();
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
                var v4 = J(contact, "geburtstag").StartsWith("--", StringComparison.Ordinal) || J(contact, "jubilaeum").Length > 0;
                var rawNames = contact.TryGetProperty("vcardRoundtrip", out var rawFields) && rawFields.ValueKind == JsonValueKind.Array
                    ? ParseVCardProperties(rawFields.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String).Select(value => value.GetString()!))
                    : new Dictionary<string, List<VCardEntry>>(StringComparer.OrdinalIgnoreCase);
                var display = J(contact, "anzeigename");
                if (!contact.TryGetProperty("anzeigename", out _) || display.Length == 0 && !rawNames.ContainsKey("FN"))
                {
                    display = Value(rawNames, "FN");
                    if (display.Length == 0) display = ($"{first} {last}").Trim();
                    if (display.Length == 0) display = company;
                    if (display.Length == 0) display = TextValues(contact, "telefone", "wert", J(contact, "telefon"), J(contact, "mobil")).FirstOrDefault() ?? "";
                    if (display.Length == 0) display = TextValues(contact, "emails", "", J(contact, "email")).FirstOrDefault() ?? "";
                }
                if (display.Length + first.Length + last.Length + company.Length == 0 && !TextValues(contact, "emails", "", J(contact, "email")).Any() &&
                    !TextValues(contact, "telefone", "wert", J(contact, "telefon"), J(contact, "mobil")).Any()) throw new InvalidDataException();
                var nameParts = SplitEscaped(RawValue(rawNames, "N"), ';').ToList();
                while (nameParts.Count < 5) nameParts.Add("");
                if (NameComponent(nameParts[0]) != last) nameParts[0] = V(last);
                if (NameComponent(nameParts[1]) != first) nameParts[1] = V(first);
                string NameParameters(string name) => Entries(rawNames, name).FirstOrDefault() is { } entry
                    ? string.Concat(PreservedParameters(entry).Select(parameter => ";" + parameter!.ToString())) : "";
                var lines = new List<string> { "BEGIN:VCARD", v4 ? "VERSION:4.0" : "VERSION:3.0", "N" + NameParameters("N") + ":" + string.Join(';', nameParts), "FN" + NameParameters("FN") + ":" + V(display) };
                var organization = SplitEscaped(RawValue(rawNames, "ORG"), ';').ToList();
                if (VCardText(organization[0]) != company) organization[0] = V(company);
                if (organization.Any(value => value.Length > 0))
                {
                    lines.Add("ORG" + NameParameters("ORG") + ":" + string.Join(';', organization));
                }
                if (rawFields.ValueKind == JsonValueKind.Array)
                {
                    var nameCounts = new Dictionary<string, int>(StringComparer.Ordinal);
                    foreach (var value in rawFields.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String))
                    {
                        var line = value.GetString()!; var name = VCardPropertyName(line);
                        if (name is not ("N" or "FN" or "ORG") || !SafeUnknownVCardLine(line)) continue;
                        var count = nameCounts.GetValueOrDefault(name); nameCounts[name] = count + 1;
                        if (count > 0) lines.Add(line);
                    }
                }
                AddTypedEntries(lines, contact, "telefone", "TEL", "wert", J(contact, "telefon"), J(contact, "mobil"));
                if (v4)
                    for (var index = 0; index < lines.Count; index++)
                        if (VCardPropertyName(lines[index]) == "TEL")
                        {
                            var separator = lines[index].IndexOfAny([';', ':']);
                            lines[index] = lines[index].Insert(separator, ";VALUE=text");
                        }
                AddTypedEntries(lines, contact, "emailEintraege", "EMAIL", "wert", J(contact, "email"));
                if (contact.TryGetProperty("anschriften", out var addressArray) && addressArray.ValueKind == JsonValueKind.Array)
                    foreach (var address in addressArray.EnumerateArray()) AddAddress(lines, address);
                else AddAddress(lines, contact);
                if (J(contact, "notiz") is { Length: > 0 } note) lines.Add($"NOTE:{V(note)}");
                foreach (var pair in new[] { ("kontaktpersonName", "X-MAGNOLIE-KONTAKTPERSON-NAME"), ("kontaktpersonTelefon", "X-MAGNOLIE-KONTAKTPERSON-TELEFON"), ("kontaktpersonStatus", "X-MAGNOLIE-KONTAKTPERSON-STATUS") })
                    if (J(contact, pair.Item1) is { Length: > 0 } value) lines.Add(pair.Item2 + ":" + V(value));
                AddMagnolieJsonEntries(lines, contact, "kontaktpersonen", "X-MAGNOLIE-NOTFALLKONTAKT");
                AddMagnolieJsonEntries(lines, contact, "sozialeMedien", "X-MAGNOLIE-SOZIALES-MEDIUM");
                if (J(contact, "uid") is { Length: > 0 } uid) lines.Add((v4 ? "UID;VALUE=text:" : "UID:") + V(uid));
                string WireDate(string value) => value.StartsWith("--", StringComparison.Ordinal)
                    ? "--" + value[2..].Replace("-", "") : value.Replace("-", "");
                if (J(contact, "geburtstag") is { Length: > 0 } birthday && TryParseCanonicalDate(birthday, out _, out _, out _))
                    lines.Add("BDAY:" + (v4 ? WireDate(birthday) : birthday));
                if (J(contact, "jubilaeum") is { Length: > 0 } anniversary && TryParseCanonicalDate(anniversary, out _, out _, out _))
                    lines.Add("ANNIVERSARY:" + WireDate(anniversary));
                if (J(contact, "foto") is { Length: > 0 } photo && TryPhotoData(photo, out var mediaType, out var base64))
                    lines.Add(v4 ? "PHOTO:" + photo : $"PHOTO;ENCODING=b;TYPE={mediaType}:{base64}");
                if (contact.TryGetProperty("vcardRoundtrip", out var roundtrip) && roundtrip.ValueKind == JsonValueKind.Array)
                    foreach (var raw in roundtrip.EnumerateArray())
                        if (raw.ValueKind == JsonValueKind.String && SafeUnknownVCardLine(raw.GetString() ?? "") &&
                            !new[] { "N", "FN", "ORG" }.Contains(VCardPropertyName(raw.GetString()!)) &&
                            !(VCardPropertyName(raw.GetString()!) == "PHOTO" && TryPhotoData(J(contact, "foto"), out _, out _)) &&
                            !(VCardPropertyName(raw.GetString()!) == "BDAY" && TryParseCanonicalDate(J(contact, "geburtstag"), out _, out _, out _)) &&
                            !(VCardPropertyName(raw.GetString()!) == "ANNIVERSARY" && TryParseCanonicalDate(J(contact, "jubilaeum"), out _, out _, out _))) lines.Add(raw.GetString()!);
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
        using var culture = new CalendarRecurrence.WireCulture();
        if (data.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Exportdaten fehlen.");
        var records = new List<string>(); var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var skipped = 0; var photoOmitted = 0;
        foreach (var contact in data.EnumerateArray())
        {
            if (contact.ValueKind != JsonValueKind.Object) { skipped++; continue; }
            var first = J(contact, "vorname").Trim(); var last = J(contact, "nachname").Trim();
            var company = J(contact, "firma").Trim(); var emails = LdifEmails(contact).ToArray();
            var cn = J(contact, "anzeigename");
            if (cn.Length == 0) cn = string.Join(' ', new[] { first, last }.Where(value => value.Length > 0));
            if (cn.Length == 0) cn = company.Length > 0 ? company : emails.FirstOrDefault() ?? "";
            if (cn.Length == 0) cn = LdifPhones(contact).Select(phone => phone.Value).FirstOrDefault() ?? "";
            if (cn.Length == 0) { skipped++; continue; }
            var uid = LdifUid(contact, used);
            var lines = new List<string>
            {
                LdifLine("dn", "uid=" + EscapeDn(uid)), LdifLine("objectClass", "top"),
                LdifLine("objectClass", last.Length > 0 ? "inetOrgPerson" : "organizationalRole"),
                LdifLine("objectClass", "extensibleObject"), LdifLine("uid", uid), LdifLine("cn", cn)
            };
            if (first.Length > 0) lines.Add(LdifLine("givenName", first));
            if (last.Length > 0) lines.Add(LdifLine("sn", last));
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
            foreach (var (field, property, prefix) in new[] { ("geburtstag", "dateOfBirth", "birth"), ("jubilaeum", "anniversary", "anniversary") })
                if (TryParseCanonicalDate(J(contact, field), out var fullDate, out var month, out var day))
                {
                    if (fullDate is not null) lines.Add(LdifLine(property, J(contact, field)));
                    else { lines.Add(LdifLine(prefix + "Month", month.ToString(CultureInfo.InvariantCulture))); lines.Add(LdifLine(prefix + "Day", day.ToString(CultureInfo.InvariantCulture))); }
                }
            // Standard LDAP attributes cannot express all vCard name/list fields.
            var complete = JsonNode.Parse(contact.GetRawText())!.AsObject();
            if (TextField(complete, "uid").Length == 0) complete["uid"] = uid;
            using (var completeDocument = JsonDocument.Parse(new JsonArray(complete).ToJsonString()))
            {
                var vcard = WriteVCard(completeDocument.RootElement);
                if (vcard.Count == 1) lines.Add(LdifLine("magnolieVCard", vcard.Text));
            }
            if (J(contact, "foto") is { Length: > 0 } photo)
            {
                if (TryLdifJpeg(photo, out var jpeg)) lines.Add(LdifBinaryLine("jpegPhoto", jpeg));
                else if (!TryPhotoData(photo, out _, out _)) photoOmitted++;
            }
            records.Add(string.Join("\r\n", lines));
        }
        var text = "version: 1\r\n" + (records.Count > 0 ? "\r\n" + string.Join("\r\n\r\n", records) + "\r\n" : "");
        return new ExchangeExportResult(text, records.Count, skipped, "", photoOmitted);
    }

    internal static ExchangeImportResult ParseLdif(string text)
    {
        using var culture = new CalendarRecurrence.WireCulture();
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
                        else value = name.Equals("magnolieVCard", StringComparison.OrdinalIgnoreCase)
                            ? new UTF8Encoding(false, true).GetString(bytes) : Encoding.UTF8.GetString(bytes);
                    }
                    catch (Exception error) when (error is FormatException or DecoderFallbackException)
                    {
                        if (name.Equals("magnolieVCard", StringComparison.OrdinalIgnoreCase))
                            throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."), error);
                        skipped++; continue;
                    }
                }
                if (!fields.TryGetValue(name, out var list)) fields[name] = list = new List<string>();
                list.Add(value.Trim());
            }
            var parsed = ContactFromFields(fields, photo);
            if (parsed is null) continue;
            var contact = parsed.Value.Contact; var birthday = parsed.Value.Birthday; var unknownYear = parsed.Value.UnknownYear;
            if (Field(fields, "magnolieVCard") is { Length: > 0 } complete)
            {
                if (fields["magnolieVCard"].Count != 1) throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
                var parsedCard = ParseVCard(complete);
                if (parsedCard.Uebersprungen > 0) throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
                var restored = parsedCard.Kontakte;
                if (restored.Count == 1 && restored[0] is JsonObject full)
                { contact = full.DeepClone().AsObject(); birthday = TextField(contact, "geburtstag"); unknownYear = birthday.StartsWith("--", StringComparison.Ordinal); }
                else throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
            }
            else if (Field(fields, "magnolieVCardN") is { Length: > 0 } oldName)
                contact["vcardRoundtrip"] = new JsonArray("N:" + oldName);
            var addresses = LdifPostalAddresses(fields);
            if (addresses.Count > 0 && Field(fields, "magnolieVCard").Length == 0)
            {
                contact["anschriften"] = addresses;
                contact["strasse"] = addresses[0]?["strasse"]?.ToString() ?? "";
                contact["plz"] = addresses[0]?["plz"]?.ToString() ?? "";
                contact["ort"] = addresses[0]?["ort"]?.ToString() ?? "";
            }
            contacts.Add(contact);
            // No detached duplicate of a contact occasion in the same payload.
        }
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeImportResult ParseClawsXml(string text)
    {
        using var culture = new CalendarRecurrence.WireCulture();
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
            // Standalone calendar birthdays are handled by their own parser.
        }
        return new ExchangeImportResult(new JsonArray(), new JsonArray(), birthdays, new JsonArray(), contacts, skipped);
    }

    internal static ExchangeImportResult ParseLotusCsv(string text)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        var rows = ParseCsv(text); if (rows.Count == 0) return EmptyImport();
        var header = rows[0].Select(NormalizeHeader).ToArray();
        int Find(params string[] names) { for (var index = 0; index < header.Length; index++) if (names.Any(candidate => header[index].Contains(candidate, StringComparison.Ordinal))) return index; return -1; }
        var startIndex = Find("ANFANGSDATUM", "STARTDATUM", "BEGINNDATUM", "STARTDATE", "DATUMZEIT");
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
            var startTime = Cell(Find("ANFANGSZEIT", "STARTZEIT", "BEGINNZEIT", "STARTTIME"));
            var endTime = Cell(Find("ENDZEIT", "ENDEZEIT", "ENDTIME"));
            var start = ParseLotusDate(Cell(startIndex) + (startTime.Length > 0 ? " " + startTime : ""));
            if (start.Ambiguous) { ambiguous++; skipped++; continue; }
            if (start.Date.Length == 0) { skipped++; continue; }
            var endDate = Cell(Find("ENDDATUM", "ENDEDATUM", "ENDDATE"));
            if (endDate.Length == 0 && endTime.Length > 0) endDate = start.Date;
            var end = ParseLotusDate(endDate + (endTime.Length > 0 ? " " + endTime : ""));
            if (endTime.Length > 0 && end.Date.Length == 0 || end.Ambiguous)
            { if (end.Ambiguous) ambiguous++; skipped++; continue; }
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
        using var culture = new CalendarRecurrence.WireCulture();
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

    private static (JsonObject Value, bool Anniversary, bool Complex) ParseEvent(List<IcsProperty> values, TimeZoneInfo? timeZone = null, IReadOnlyDictionary<string, CalendarRecurrence.SourceZone>? zones = null, ISet<string>? birthdayRepairs = null)
    {
        var roundtripValues = values;
        values = TopLevelProperties(values);
        var startProperty = First(values, "DTSTART") ?? (First(values, "STATUS")?.Value.Equals("CANCELLED", StringComparison.OrdinalIgnoreCase) == true
            ? First(values, "RECURRENCE-ID") : null) ?? throw new InvalidDataException();
        var start = ParseIcsDate(startProperty, timeZone, zones);
        var endProperty = First(values, "DTEND");
        (DateTime DateTime, bool AllDay)? end = endProperty is null ? null : ParseIcsDate(endProperty, timeZone, zones);
        var duration = First(values, "DURATION");
        if (duration is not null)
        {
            if (endProperty is not null) throw new InvalidDataException("VEVENT cannot contain both DTEND and DURATION.");
            var span = CalendarRecurrence.Duration(duration.Value);
            if (start.AllDay && (span <= TimeSpan.Zero || span.Ticks % TimeSpan.TicksPerDay != 0 || duration.Value.Contains("T", StringComparison.OrdinalIgnoreCase)))
                throw new InvalidDataException("An all-day duration must contain whole days or weeks.");
            var stamp = CalendarRecurrence.ParseStamp(new CalendarRecurrence.Property(startProperty.Name, startProperty.Value, startProperty.Parameters), zones);
            var endUtc = CalendarRecurrence.DurationEndUtc(stamp, duration.Value, timeZone ?? TimeZoneInfo.Local);
            end = (stamp.AllDay ? stamp.Wall.Add(span) : TimeZoneInfo.ConvertTimeFromUtc(endUtc, timeZone ?? TimeZoneInfo.Local), start.AllDay);
        }
        if (end is not null && (end.Value.AllDay != start.AllDay || end.Value.DateTime < start.DateTime || start.AllDay && end.Value.DateTime == start.DateTime))
            throw new InvalidDataException("Invalid calendar end.");
        if (start.AllDay && end is not null) end = (end.Value.DateTime.AddDays(-1), true);
        var recurrence = First(values, "RRULE")?.Value ?? "";
        var rdateProperties = values.Where(value => value.Name == "RDATE").ToArray();
        var customDates = new SortedSet<DateOnly>();
        var customOccurrences = new SortedSet<(DateOnly Date, TimeOnly? Time)>();
        var exceptionDates = new SortedSet<DateOnly>();
        var exceptionTimes = new SortedSet<(DateOnly Date, TimeOnly Time)>();
        var invalidRdate = false;
        foreach (var property in rdateProperties)
            foreach (var rawDate in property.Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                try
                {
                    var parsed = ParseIcsDate(property with { Value = rawDate.Split('/', 2)[0] }, timeZone, zones);
                    var date = DateOnly.FromDateTime(parsed.DateTime);
                    TimeOnly? time = parsed.AllDay ? null : TimeOnly.FromDateTime(parsed.DateTime);
                    if (parsed.AllDay != start.AllDay) invalidRdate = true;
                    else
                    {
                        customDates.Add(date);
                        customOccurrences.Add((date, time));
                        if (recurrence.Length == 0 && time != (start.AllDay ? null : TimeOnly.FromDateTime(start.DateTime))) invalidRdate = true;
                    }
                }
                catch (Exception) when (rawDate.Length > 0) { invalidRdate = true; }
        foreach (var property in values.Where(value => value.Name == "EXDATE"))
            foreach (var rawDate in property.Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                try
                {
                    var parsed = ParseIcsDate(property with { Value = rawDate }, timeZone, zones);
                    if (parsed.AllDay) exceptionDates.Add(DateOnly.FromDateTime(parsed.DateTime));
                    else exceptionTimes.Add((DateOnly.FromDateTime(parsed.DateTime), TimeOnly.FromDateTime(parsed.DateTime)));
                }
                catch (Exception) when (rawDate.Length > 0) { }
        var monthlyWeekday = MonthlyWeekday(recurrence);
        var simpleRdate = recurrence.Length == 0 && rdateProperties.Length > 0 && !invalidRdate && customDates.Count > 0;
        var recurrenceKind = simpleRdate ? "custom" : monthlyWeekday.Form.Length > 0 ? "monthly" : RecurrenceKind(recurrence, start.DateTime);
        var complex = recurrence.Length > 0 && recurrenceKind.Length == 0 ||
                       values.Count(value => value.Name == "RRULE") > 1 ||
                       values.Any(value => value.Name is "EXDATE" or "EXRULE" or "RECURRENCE-ID") ||
                       rdateProperties.Length > 0 && !simpleRdate;
        if (recurrence.Length > 0 && !start.AllDay && !RecurrenceZoneIsLocal(startProperty)) complex = true;
        if (recurrenceKind == "monthly" && monthlyWeekday.Form.Length == 0 && start.DateTime.Day > 28 ||
            recurrenceKind == "yearly" && start.DateTime.Month == 2 && start.DateTime.Day == 29)
            complex = true;
        var title = IcsText(First(values, "SUMMARY")?.Value ?? "");
        var category = IcsText(First(values, "CATEGORIES")?.Value ?? "");
        var anniversaryType = IcsText(First(values, "X-MAGNOLIE-TYPE-ID")?.Value ??
                                       First(values, "X-MAGNOLIE-TYP")?.Value ??
                                       First(values, "X-MAGNOLIE-JAHRESTAG-TYP")?.Value ?? "");
        var anniversary = start.AllDay && IsUnboundedAnnualRule(recurrence) && anniversaryType.Length > 0 &&
            !values.Any(value => value.Name is "EXDATE" or "RDATE" or "EXRULE" or "RECURRENCE-ID") &&
            (end is null || end.Value.DateTime.Date == start.DateTime.Date);
        if (anniversary)
        {
            var date = start.DateTime.ToString("yyyy-MM-dd");
            var magnolieDate = First(values, "X-MAGNOLIE-DATE")?.Value.Trim() ?? "";
            if (TryParseCanonicalDate(magnolieDate, out var fullDate, out _, out _) && fullDate is null)
                date = magnolieDate;
            // Keep native synchronization baselines consistent with the web
            // birthday normalization, including legacy exported type names.
            if (date.StartsWith("1604-", StringComparison.Ordinal) &&
                (anniversaryType.Equals("birthday", StringComparison.OrdinalIgnoreCase) ||
                 anniversaryType.Equals("Geburtstag", StringComparison.OrdinalIgnoreCase)))
            {
                date = "--" + date[5..];
                birthdayRepairs?.Add(IcsText(First(values, "UID")?.Value ?? ""));
            }
            return (new JsonObject { ["uid"] = IcsText(First(values, "UID")?.Value ?? ""), ["name"] = title,
                ["datum"] = date, ["typ"] = anniversaryType,
                ["notiz"] = IcsText(First(values, "DESCRIPTION")?.Value ?? ""),
                ["icsRoundtrip"] = IcsRoundtrip(roundtripValues, complex), ["geaendert"] = IcsModified(values) }, true, complex);
        }
        var until = RRuleValue(recurrence, "UNTIL");
        var untilDate = ParseCompactDate(until);
        if (until.Contains('T'))
        {
            var limit = ParseIcsDate(new IcsProperty("UNTIL", until, startProperty.Parameters), timeZone, zones).DateTime;
            if (!start.AllDay && limit.TimeOfDay < start.DateTime.TimeOfDay) limit = limit.AddDays(-1);
            untilDate = limit.ToString("yyyy-MM-dd");
        }
        var interval = int.TryParse(RRuleValue(recurrence, "INTERVAL"), out var parsedInterval)
            ? Math.Clamp(parsedInterval, 1, 3660) : 1;
        var uid = IcsText(First(values, "UID")?.Value ?? "");
        if (First(values, "RECURRENCE-ID") is { } recurrenceId) uid = InstanceUid(uid, recurrenceId);
        var recurrenceObject = new JsonObject { ["art"] = recurrenceKind.Length > 0 ? recurrenceKind : "none",
            ["bis"] = untilDate, ["intervall"] = interval > 1 && recurrenceKind.Length > 0 ? interval : 1,
            ["ordinal"] = monthlyWeekday.Form.Length > 0 ? monthlyWeekday.Ordinal : 0,
            ["wochentag"] = monthlyWeekday.Form.Length > 0 ? monthlyWeekday.Weekday : "",
            ["rruleForm"] = monthlyWeekday.Form.Length > 0 ? monthlyWeekday.Form : "" };
        if (simpleRdate) recurrenceObject["daten"] = new JsonArray(customDates
            .Select(date => (JsonNode?)date.ToString("yyyy-MM-dd")).ToArray());
        var result = new JsonObject
        {
            ["uid"] = uid, ["datum"] = start.DateTime.ToString("yyyy-MM-dd"),
            ["endDatum"] = end is not null && end.Value.DateTime.Date > start.DateTime.Date ? end.Value.DateTime.ToString("yyyy-MM-dd") : "", ["zeit"] = start.AllDay ? "" : start.DateTime.ToString("HH:mm"),
            ["endZeit"] = end is null || end.Value.AllDay ? "" : end.Value.DateTime.ToString("HH:mm"), ["titel"] = title,
            ["notiz"] = IcsText(First(values, "DESCRIPTION")?.Value ?? ""), ["kategorien"] = category,
            ["vertraulich"] = new[] { "PRIVATE", "CONFIDENTIAL" }.Contains((First(values, "CLASS")?.Value ?? "").ToUpperInvariant()),
            ["vorlaeufig"] = (First(values, "STATUS")?.Value ?? "").Equals("TENTATIVE", StringComparison.OrdinalIgnoreCase),
            ["kostenstelle"] = IcsText(First(values, "X-MAGNOLIE-KOSTENSTELLE")?.Value ?? ""), ["kunde"] = IcsText(First(values, "X-MAGNOLIE-KUNDE")?.Value ?? ""),
            ["standardErinnerung"] = (First(values, "X-MAGNOLIE-STANDARDERINNERUNG")?.Value ?? "1") != "0",
            ["individuelleErinnerungTage"] = int.TryParse(First(values, "X-MAGNOLIE-ERINNERUNG-TAGE")?.Value, out var days) ? Math.Clamp(days, 0, 7) : 0,
            ["icsAusnahmen"] = new JsonArray(exceptionDates.Select(value => (JsonNode?)value.ToString("yyyy-MM-dd")).ToArray()),
            ["icsAusnahmeTermine"] = new JsonArray(exceptionTimes.Select(value => (JsonNode?)new JsonObject
                { ["datum"] = value.Date.ToString("yyyy-MM-dd"), ["zeit"] = value.Time.ToString("HH:mm") }).ToArray()),
            ["icsZusatzDaten"] = new JsonArray(customDates.Select(value => (JsonNode?)value.ToString("yyyy-MM-dd")).ToArray()),
            ["icsZusatzTermine"] = new JsonArray(customOccurrences.Select(value => (JsonNode?)new JsonObject
                { ["datum"] = value.Date.ToString("yyyy-MM-dd"), ["zeit"] = value.Time?.ToString("HH:mm") ?? "" }).ToArray()),
            ["wiederholung"] = recurrenceObject,
            ["icsKomplex"] = complex, ["icsSerienUid"] = complex ? IcsText(First(values, "UID")?.Value ?? "") : "",
            ["icsStatus"] = First(values, "STATUS")?.Value.ToUpperInvariant() ?? "",
            ["icsAnzeigeZeitzone"] = (timeZone ?? TimeZoneInfo.Local).Id,
            ["icsEndeFehlt"] = endProperty is null && duration is null,
            ["icsNullDauer"] = end is not null && end.Value.DateTime == start.DateTime && !start.AllDay,
            ["icsRoundtrip"] = IcsRoundtrip(roundtripValues, true), ["geaendert"] = IcsModified(values)
        };
        return (result, false, complex);
    }

    private static JsonObject ParseTask(List<IcsProperty> values, TimeZoneInfo? timeZone = null, IReadOnlyDictionary<string, CalendarRecurrence.SourceZone>? zones = null)
    {
        var original = values;
        values = TopLevelProperties(values);
        var due = First(values, "DUE");
        var dueValue = due is null ? default : ParseIcsDate(due, timeZone, zones);
        var start = First(values, "DTSTART");
        var startValue = start is null ? default : ParseIcsDate(start, timeZone, zones);
        if (First(values, "DURATION") is { } duration)
        {
            if (due is not null || start is null) throw new InvalidDataException("Invalid task duration.");
            var stamp = CalendarRecurrence.ParseStamp(new CalendarRecurrence.Property(start.Name, start.Value, start.Parameters), zones);
            dueValue = (CalendarRecurrence.InZone(new CalendarRecurrence.Stamp(CalendarRecurrence.DurationEndUtc(stamp, duration.Value, timeZone ?? TimeZoneInfo.Local), false, TimeZoneInfo.Utc),
                timeZone ?? TimeZoneInfo.Local), startValue.AllDay);
        }
        var uid = IcsText(First(values, "UID")?.Value ?? "");
        var recurrenceId = First(values, "RECURRENCE-ID");
        var identity = ReadTaskIdentity(values, uid);
        if (identity is not null) uid = TextField(identity, "uid");
        var parent = values.FirstOrDefault(value => value.Name == "RELATED-TO" && value.Parameters.Any(
            parameter => parameter.Equals("RELTYPE=PARENT", StringComparison.OrdinalIgnoreCase)))?.Value ?? "";
        if (identity is not null && IcsText(parent) != TextField(identity, "parent") &&
            (TextField(identity, "parent").Length == 0 || !Regex.IsMatch(IcsText(parent), "^" +
                Regex.Escape(TaskExportAlias(TextField(identity, "parentSource"), TextField(identity, "parent"))) + "(?:-[1-9][0-9]*)?$")))
            throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
        parent = identity is null ? IcsText(parent) : TextField(identity, "parent");
        var order = int.TryParse(First(values, "X-MAGNOLIE-REIHENFOLGE")?.Value, out var parsedOrder)
            ? Math.Max(0, parsedOrder) : 0;
        var result = new JsonObject
        {
            ["uid"] = recurrenceId is null ? uid : InstanceUid(uid, recurrenceId), ["elternUid"] = parent,
            ["icsElternUid"] = parent,
            ["icsSerienUid"] = recurrenceId is null ? "" : uid,
            ["icsStatus"] = First(values, "STATUS")?.Value.ToUpperInvariant() ?? "",
            ["icsAnzeigeZeitzone"] = (timeZone ?? TimeZoneInfo.Local).Id,
            ["reihenfolge"] = order, ["titel"] = IcsText(First(values, "SUMMARY")?.Value ?? ""),
            ["faellig"] = dueValue.DateTime == default ? "" : dueValue.DateTime.ToString("yyyy-MM-dd"),
            ["faelligZeit"] = dueValue.DateTime == default || dueValue.AllDay ? "" : dueValue.DateTime.ToString("HH:mm"),
            ["startDatum"] = start is null ? "" : startValue.DateTime.ToString("yyyy-MM-dd"),
            ["startZeit"] = start is null ? (TimeOnly.TryParseExact(First(values, "X-MAGNOLIE-START-TIME")?.Value, "HH:mm", out var legacyTime) ? legacyTime.ToString("HH:mm") : "") :
                startValue.AllDay ? "" : startValue.DateTime.ToString("HH:mm"),
            ["prio"] = TaskPriority(First(values, "PRIORITY")?.Value),
            ["erledigt"] = (First(values, "STATUS")?.Value ?? "").Equals("COMPLETED", StringComparison.OrdinalIgnoreCase) || First(values, "PERCENT-COMPLETE")?.Value == "100",
            ["notiz"] = IcsText(First(values, "DESCRIPTION")?.Value ?? ""),
            ["erinnern"] = First(values, "X-MAGNOLIE-ERINNERUNG-AM-TAG")?.Value == "1",
            ["individuelleErinnerungTage"] = int.TryParse(First(values, "X-MAGNOLIE-ERINNERUNG-TAGE")?.Value, out var reminderDays) ? Math.Clamp(reminderDays, 0, 7) : 0,
            ["icsRoundtrip"] = IcsRoundtrip(original.Where(property => property.Name != "X-MAGNOLIE-TASK-IDENTITY"), true), ["geaendert"] = IcsModified(values)
        };
        if (identity is not null)
        {
            result["_icsTaskSource"] = identity["source"]!.DeepClone();
            result["icsElternQuelleId"] = identity["parentSource"]!.DeepClone();
        }
        return result;
    }

    internal static bool IsUnboundedAnnualRule(string rule) => Regex.IsMatch(rule, @"^FREQ=YEARLY(?:;INTERVAL=1)?$|^INTERVAL=1;FREQ=YEARLY$", RegexOptions.IgnoreCase);
    // Keep shipped instance IDs stable; timezone-qualified identity remains in RECURRENCE-ID.
    private static string InstanceUid(string uid, IcsProperty recurrenceId) => uid + "#" + recurrenceId.Value;

    internal static void ReconcileRecurrences(JsonArray items, TimeZoneInfo? timeZone = null)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        var masters = items.OfType<JsonObject>().Where(item => !(item["icsRoundtrip"] as JsonArray ?? []).Any(line =>
            line is JsonValue && ParseIcsProperty(line.ToString())?.Name == "RECURRENCE-ID"))
            .GroupBy(item => (Source: TextField(item, "icsQuelleId"), Uid: TextField(item, "uid")))
            .Where(group => group.Count() == 1).ToDictionary(group => group.Key, group => group.Single());
        foreach (var item in items.OfType<JsonObject>())
        {
            var raw = item["icsRoundtrip"] as JsonArray;
            var recurrenceId = raw?.Select(line => ParseIcsProperty(line?.ToString() ?? "")).FirstOrDefault(property => property?.Name == "RECURRENCE-ID");
            if (recurrenceId is null) continue;
            var series = TextField(item, "icsSerienUid");
            if (!masters.TryGetValue((TextField(item, "icsQuelleId"), series), out var master)) continue;
            var original = ParseIcsDate(recurrenceId, timeZone, CalendarRecurrence.CalendarZones(JsonSerializer.SerializeToElement(item)));
            item["icsOriginalDatum"] = original.DateTime.ToString("yyyy-MM-dd");
            item["icsOriginalZeit"] = original.AllDay ? "" : original.DateTime.ToString("HH:mm");
            master["icsKomplex"] = true; master["icsSerienUid"] = series;
            var masterRaw = master["icsRoundtrip"] as JsonArray ?? new JsonArray(); master["icsRoundtrip"] = masterRaw;
            var exclusion = new IcsProperty("EXDATE", recurrenceId.Value, recurrenceId.Parameters.Where(value => !value.StartsWith("RANGE=", StringComparison.OrdinalIgnoreCase)).ToArray()).Raw;
            if (!masterRaw.Any(line => line?.ToString() == exclusion)) masterRaw.Add(exclusion);
            if (recurrenceId.Parameters.Any(parameter => parameter.Equals("RANGE=THISANDFUTURE", StringComparison.OrdinalIgnoreCase)))
            {
                var ranges = master["icsRangeOverrides"] as JsonArray ?? new JsonArray(); master["icsRangeOverrides"] = ranges;
                var definition = new JsonArray(TopLevelProperties(raw!.Select(line => ParseIcsProperty(line?.ToString() ?? "")).OfType<IcsProperty>())
                    .Select(property => (JsonNode?)property.Raw).ToArray());
                if (!ranges.Any(value => JsonNode.DeepEquals(value, definition))) ranges.Add(definition);
            }
            var field = original.AllDay ? "icsAusnahmen" : "icsAusnahmeTermine";
            var excluded = master[field] as JsonArray ?? new JsonArray(); master[field] = excluded;
            JsonNode value = original.AllDay ? JsonValue.Create(original.DateTime.ToString("yyyy-MM-dd"))! :
                new JsonObject { ["datum"] = original.DateTime.ToString("yyyy-MM-dd"), ["zeit"] = original.DateTime.ToString("HH:mm") };
            if (!excluded.Any(existing => JsonNode.DeepEquals(existing, value))) excluded.Add(value);
        }
    }

    private static IEnumerable<string> AppointmentLines(JsonElement item)
    {
        var date = RequiredDate(J(item, "datum"));
        var time = J(item, "zeit");
        var sourceUid = J(item, "icsSerienUid");
        var raw = item.TryGetProperty("icsRoundtrip", out var roundtrip) && roundtrip.ValueKind == JsonValueKind.Array
            ? roundtrip.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String)
                .Select(value => value.GetString() ?? "").Where(ValidIcsRoundtripLine).ToArray()
            : Array.Empty<string>();
        var rawRdates = IcsDates(raw, "RDATE");
        var rawExdates = IcsDates(raw, "EXDATE");
        var exceptions = StructuredDates(item, "icsAusnahmen");
        var additions = StructuredDates(item, "icsZusatzDaten");
        var timedAdditions = StructuredOccurrences(item);
        additions.ExceptWith(exceptions);
        additions.ExceptWith(rawExdates);
        additions.ExceptWith(rawRdates);
        additions.Remove(date);
        timedAdditions.RemoveWhere(value => value.Date == date && value.Time == time);
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
            var end = J(item, "endZeit").Length > 0 ? RequiredTime(endDate, J(item, "endZeit")) : JBool(item, "icsNullDauer") ? start : start.AddMinutes(30);
            lines.Add($"DTSTART:{start:yyyyMMdd'T'HHmmss}");
            if (!JBool(item, "icsEndeFehlt") || J(item, "endZeit").Length > 0 || endDate != date) lines.Add($"DTEND:{end:yyyyMMdd'T'HHmmss}");
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
                var until = J(recurrence, "bis") is { Length: > 0 } value ? $";UNTIL={value.Replace("-", "")}" + (time.Length == 0 ? "" : "T235959") : "";
                lines.Add(J(recurrence, "rruleForm") == "bysetpos"
                    ? $"RRULE:FREQ=MONTHLY;BYDAY={J(recurrence, "wochentag")};BYSETPOS={JInt(recurrence, "ordinal")}{until}"
                    : $"RRULE:FREQ=MONTHLY;BYDAY={JInt(recurrence, "ordinal")}{J(recurrence, "wochentag")}{until}");
            }
            else if (kind is "DAILY" or "WEEKLY" or "MONTHLY" or "YEARLY")
            {
                var interval = Math.Clamp(JInt(recurrence, "intervall"), 1, 3660);
                lines.Add("RRULE:FREQ=" + kind +
                    (interval > 1 ? $";INTERVAL={interval}" : "") +
                    (J(recurrence, "bis") is { Length: > 0 } until ? $";UNTIL={until.Replace("-", "")}" + (time.Length == 0 ? "" : "T235959") : ""));
            }
            else if (kind == "CUSTOM" && recurrence.TryGetProperty("daten", out var dates) &&
                dates.ValueKind == JsonValueKind.Array)
            {
                additions.UnionWith(dates.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String &&
                    DateOnly.TryParseExact(value.GetString(), "yyyy-MM-dd", out _)).Select(value => DateOnly.ParseExact(value.GetString()!, "yyyy-MM-dd")));
            }
        }
        additions.ExceptWith(exceptions);
        additions.ExceptWith(rawExdates);
        additions.ExceptWith(rawRdates);
        additions.Remove(date);
        var timedDates = timedAdditions.Select(value => value.Date).ToHashSet();
        additions.ExceptWith(timedDates);
        foreach (var rawDate in rawRdates) timedAdditions.RemoveWhere(value => value.Date == rawDate);
        if (timedAdditions.Count > 0)
            lines.Add("RDATE:" + string.Join(',', timedAdditions.Select(value =>
                value.Date.ToString("yyyyMMdd") + (value.Time.Length > 0 ? "T" + value.Time.Replace(":", "") + "00" : ""))));
        if (additions.Count > 0) lines.Add(RecurrenceDateLine("RDATE", additions, time));
        exceptions.ExceptWith(rawExdates);
        if (exceptions.Count > 0) lines.Add(RecurrenceDateLine("EXDATE", exceptions, time));
        if (item.TryGetProperty("icsAusnahmeTermine", out var timedExceptions) && timedExceptions.ValueKind == JsonValueKind.Array)
            foreach (var value in timedExceptions.EnumerateArray())
                if (DateOnly.TryParseExact(J(value, "datum"), "yyyy-MM-dd", out var excludedDate) &&
                    TimeOnly.TryParseExact(J(value, "zeit"), "HH:mm", out var excludedTime) && !rawExdates.Contains(excludedDate))
                    lines.Add($"EXDATE:{excludedDate:yyyyMMdd'T'}{excludedTime:HHmmss}");
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
        if (J(item, "notiz") is { Length: > 0 } note) lines.Add("DESCRIPTION:" + V(note));
        ApplyIcsRoundtrip(lines, item, anniversary: true);
        lines.Add("END:VEVENT");
        return lines;
    }

    private static string TaskExternalUid(JsonElement item)
    {
        var original = J(item, "icsImportUid"); var series = J(item, "icsSerienUid");
        if (original.Length > 0 && series.Length > 0)
        {
            var rid = item.TryGetProperty("icsRoundtrip", out var raw) && raw.ValueKind == JsonValueKind.Array
                ? raw.EnumerateArray().Select(line => ParseIcsProperty(line.ToString())).FirstOrDefault(p => p?.Name == "RECURRENCE-ID") : null;
            var suffix = "";
            if (rid is not null)
            {
                var match = Regex.Match(original, "-magnolie-instanz-[0-9a-f]{16}$");
                suffix = match.Success ? match.Value : "#" + rid.Value;
            }
            var basis = suffix.Length > 0 && original.EndsWith(suffix, StringComparison.Ordinal) ? original[..^suffix.Length] : original;
            var source = J(item, "icsQuelleId");
            var local = source.Length > 0 ? GesamtarchivService.StableTaskUid(source + "\0" + basis, "") : basis;
            var oldInstance = source.Length > 0 ? GesamtarchivService.StableTaskUid(source + "\0" + original, "") : original;
            if ((series == local || series == oldInstance) && new[] { local, local + suffix, oldInstance }.Contains(J(item, "uid"))) return basis;
        }
        return series.Length > 0 ? series : original.Length > 0 ? original : J(item, "uid");
    }

    private static string TaskExportAlias(string source, string uid) => "urn:magnolie:task:" + Sha256(source + "\0" + uid);

    private static JsonObject? ReadTaskIdentity(IEnumerable<IcsProperty> values, string wireUid)
    {
        var entries = values.Where(value => value.Name == "X-MAGNOLIE-TASK-IDENTITY").ToArray();
        if (entries.Length == 0) return null;
        if (entries.Length != 1 || JsonNode.Parse(IcsText(entries[0].Value)) is not JsonObject identity ||
            identity.Count != 5 || identity["v"] is not JsonValue version || !version.TryGetValue<int>(out var v) || v != 1 ||
            new[] { "source", "uid", "parent", "parentSource" }.Any(key => identity[key] is not JsonValue value ||
                !value.TryGetValue<string>(out var text) || text.Contains('\0')) || TextField(identity, "uid").Length == 0)
            throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
        var uid = TextField(identity, "uid"); var alias = TaskExportAlias(TextField(identity, "source"), uid);
        if (wireUid != uid && !Regex.IsMatch(wireUid, "^" + Regex.Escape(alias) + "(?:-[1-9][0-9]*)?$"))
            throw new InvalidDataException(NativeLocalization.Gettext("The data is invalid."));
        return identity;
    }

    private static JsonArray PrepareTaskExport(JsonElement data)
    {
        var records = JsonNode.Parse(data.GetRawText())!.AsArray();
        var objects = records.OfType<JsonObject>().ToArray();
        var byUid = objects.GroupBy(a => TextField(a, "uid")).ToDictionary(g => g.Key, g => g.ToArray());
        var owners = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var a in objects)
        {
            var item = JsonSerializer.SerializeToElement(a);
            var source = J(item, "icsQuelleId"); var external = TaskExternalUid(item);
            if (external.Length == 0) external = Uid(item);
            var parent = a.ContainsKey("icsElternUid") ? J(item, "icsElternUid") : J(item, "elternUid");
            var parentSource = a.ContainsKey("icsElternQuelleId") ? J(item, "icsElternQuelleId") : source;
            var matches = byUid.GetValueOrDefault(J(item, "elternUid")) ?? [];
            if (matches.Length > 1) matches = matches.Where(p => TextField(p, "icsQuelleId") == parentSource).ToArray();
            if (matches.Length == 1)
            {
                parent = TaskExternalUid(JsonSerializer.SerializeToElement(matches[0]));
                parentSource = TextField(matches[0], "icsQuelleId");
            }
            a["_icsTaskIdentity"] = new JsonObject { ["v"] = 1, ["source"] = source, ["uid"] = external, ["parent"] = parent, ["parentSource"] = parentSource };
            foreach (var (value, owner) in new[] { (external, source), (parent, parentSource) }.Where(pair => pair.Item1.Length > 0))
            {
                if (!owners.TryGetValue(value, out var sources)) owners[value] = sources = new(StringComparer.Ordinal);
                sources.Add(owner);
            }
        }
        var reserved = owners.Keys.ToHashSet(StringComparer.Ordinal);
        var aliases = new Dictionary<(string Source, string Uid), string>();
        foreach (var value in owners.Keys.OrderBy(value => value, StringComparer.Ordinal))
            if (owners[value].Count > 1)
                foreach (var source in owners[value].OrderBy(value => value, StringComparer.Ordinal))
                {
                    var basis = TaskExportAlias(source, value); var alias = basis; var number = 0;
                    while (!reserved.Add(alias)) alias = basis + "-" + ++number;
                    aliases[(source, value)] = alias;
                }
        foreach (var a in objects)
        {
            var identity = a["_icsTaskIdentity"]!.AsObject(); var source = TextField(identity, "source");
            a["_icsExportUid"] = aliases.GetValueOrDefault((source, TextField(identity, "uid")), TextField(identity, "uid"));
            a["_icsExportParent"] = aliases.GetValueOrDefault((TextField(identity, "parentSource"), TextField(identity, "parent")), TextField(identity, "parent"));
        }
        return records;
    }

    private static IEnumerable<string> TaskLines(JsonElement item)
    {
        var lines = new List<string> { "BEGIN:VTODO", $"UID:{V(J(item, "_icsExportUid"))}", $"DTSTAMP:{DateTime.UtcNow:yyyyMMdd'T'HHmmss'Z'}", $"SUMMARY:{V(J(item, "titel"))}", $"PRIORITY:{(JInt(item, "prio") switch { 1 => 1, 3 => 9, _ => 5 })}" };
        if (DateOnly.TryParseExact(J(item, "startDatum"), "yyyy-MM-dd", out var startDate))
            lines.Add(TimeOnly.TryParseExact(J(item, "startZeit"), "HH:mm", out var startTime)
                ? $"DTSTART:{startDate:yyyyMMdd'T'}{startTime:HHmmss}" : $"DTSTART;VALUE=DATE:{startDate:yyyyMMdd}");
        else if (TimeOnly.TryParseExact(J(item, "startZeit"), "HH:mm", out var legacyTime))
            lines.Add($"X-MAGNOLIE-START-TIME:{legacyTime:HH:mm}");
        if (DateOnly.TryParse(J(item, "faellig"), out var due))
        {
            if (TimeOnly.TryParseExact(J(item, "faelligZeit"), "HH:mm", out var dueTime))
                lines.Add($"DUE:{due:yyyyMMdd'T'}{dueTime:HHmmss}");
            else lines.Add($"DUE;VALUE=DATE:{due:yyyyMMdd}");
        }
        if (JBool(item, "erledigt")) lines.AddRange(new[] { "STATUS:COMPLETED", "PERCENT-COMPLETE:100" });
        if (J(item, "notiz") is { Length: > 0 } note) lines.Add($"DESCRIPTION:{V(note)}");
        if (J(item, "_icsExportParent") is { Length: > 0 } parent) lines.Add($"RELATED-TO;RELTYPE=PARENT:{V(parent)}");
        lines.Add($"X-MAGNOLIE-REIHENFOLGE:{Math.Max(0, JInt(item, "reihenfolge"))}");
        if (JBool(item, "erinnern")) lines.Add("X-MAGNOLIE-ERINNERUNG-AM-TAG:1");
        if (JInt(item, "individuelleErinnerungTage") is > 0 and <= 7) lines.Add($"X-MAGNOLIE-ERINNERUNG-TAGE:{JInt(item, "individuelleErinnerungTage")}");
        ApplyIcsRoundtrip(lines, item);
        lines.RemoveAll(line => PropertyName(line) == "X-MAGNOLIE-TASK-IDENTITY");
        lines.Add("X-MAGNOLIE-TASK-IDENTITY:" + V(item.GetProperty("_icsTaskIdentity").GetRawText()));
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
        var generated = new HashSet<string>(new[] { "UID", "DTSTAMP", "LAST-MODIFIED", "DTSTART", "DTEND", "DUE", "PRIORITY", "PERCENT-COMPLETE", "X-MAGNOLIE-START-TIME", "X-MAGNOLIE-ERINNERUNG-AM-TAG", "SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "X-MAGNOLIE-KOSTENSTELLE", "X-MAGNOLIE-KUNDE", "X-MAGNOLIE-ERINNERUNG-TAGE", "X-MAGNOLIE-STANDARDERINNERUNG", "X-MAGNOLIE-TYPE-ID", "X-MAGNOLIE-TYP", "X-MAGNOLIE-JAHRESTAG-TYP", "X-MAGNOLIE-DATE", "X-MAGNOLIE-REIHENFOLGE" });
        if (complex) { names.Add("DTSTART"); names.Add("DTEND"); names.Add("DUE"); }
        if (values.Any(value => value.Name == "RECURRENCE-ID")) names.UnionWith(new[] { "SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "PRIORITY" });
        var result = new JsonArray(); var depth = 0;
        foreach (var value in values)
        {
            if (value.Name == "RELATED-TO" && value.Parameters.Any(parameter =>
                parameter.Equals("RELTYPE=PARENT", StringComparison.OrdinalIgnoreCase))) continue;
            if (value.Name == "BEGIN") depth++;
            if (depth > 0 || names.Contains(value.Name) || !generated.Contains(value.Name) || value.Name == "STATUS" && value.Value.Equals("CANCELLED", StringComparison.OrdinalIgnoreCase)) result.Add(value.Raw);
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

    internal static string ReplaceCalendarAnniversary(string resource, JsonObject anniversary)
    {
        using var item = JsonDocument.Parse(new JsonArray(anniversary.DeepClone()).ToJsonString());
        var replacement = EventBlock().Match(WriteIcs("ics-jahrestage", item.RootElement).Text);
        if (!replacement.Success) throw new InvalidDataException("Der Jahrestag konnte nicht geschrieben werden.");
        var matches = EventBlock().Matches(resource).Cast<Match>().Where(match =>
        {
            try
            {
                var parsed = ParseIcs(match.Value);
                return parsed.Jahrestage.Count == 1 && parsed.Jahrestage[0]?["uid"]?.GetValue<string>() == anniversary["uid"]?.GetValue<string>();
            }
            catch (Exception) { return false; }
        }).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("Die Kalenderressource enthält nicht genau einen passenden Jahrestag.");
        var target = matches[0];
        return resource[..target.Index] + replacement.Value.TrimEnd('\r', '\n') + resource[(target.Index + target.Length)..];
    }

    internal static string ReplaceCalendarTask(string resource, JsonObject task)
    {
        using var item = JsonDocument.Parse(new JsonArray(task.DeepClone()).ToJsonString());
        var replacement = TaskBlock().Match(WriteIcs("ics-aufgaben", item.RootElement).Text);
        if (!replacement.Success) throw new InvalidDataException("Die Aufgabe konnte nicht geschrieben werden.");
        var matches = TaskBlock().Matches(resource).Cast<Match>().Where(match =>
        {
            var parsed = ParseIcs(match.Value);
            return parsed.Aufgaben.Count == 1 && parsed.Aufgaben[0]?["uid"]?.GetValue<string>() == task["uid"]?.GetValue<string>();
        }).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("Die Kalenderressource enthält nicht genau eine passende Aufgabe.");
        var target = matches[0];
        return resource[..target.Index] + replacement.Value.TrimEnd('\r', '\n') + resource[(target.Index + target.Length)..];
    }

    internal static string? RemoveCalendarTask(string resource, string uid)
    {
        var matches = TaskBlock().Matches(resource).Cast<Match>().Where(match =>
        {
            var parsed = ParseIcs(match.Value);
            return parsed.Aufgaben.Count == 1 && parsed.Aufgaben[0]?["uid"]?.GetValue<string>() == uid;
        }).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("Die Kalenderressource enthält nicht genau eine passende Aufgabe.");
        var target = matches[0]; var remaining = resource[..target.Index] + resource[(target.Index + target.Length)..];
        return Regex.IsMatch(remaining, "^BEGIN:(?:VEVENT|VTODO|VJOURNAL|VFREEBUSY)\\s*$", RegexOptions.IgnoreCase | RegexOptions.Multiline)
            ? remaining : null;
    }

    internal static string? RemoveCalendarEvent(string resource, string uid)
    {
        var matches = EventBlock().Matches(resource).Cast<Match>().Where(match =>
        {
            var parsed = ParseIcs(match.Value);
            return parsed.FehlerhafteTermine == 0 && parsed.Termine.Count + parsed.Jahrestage.Count == 1 &&
                (parsed.Termine.FirstOrDefault() ?? parsed.Jahrestage.FirstOrDefault())?["uid"]?.GetValue<string>() == uid;
        }).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("Die Kalenderressource enthält nicht genau einen passenden Termin.");
        var target = matches[0]; var remaining = resource[..target.Index] + resource[(target.Index + target.Length)..];
        return Regex.IsMatch(remaining, "^BEGIN:(?:VEVENT|VTODO|VJOURNAL|VFREEBUSY)\\s*$", RegexOptions.IgnoreCase | RegexOptions.Multiline)
            ? remaining : null;
    }

    private static void ApplyIcsRoundtrip(List<string> lines, JsonElement item, bool anniversary = false)
    {
        if (!item.TryGetProperty("icsRoundtrip", out var metadata) || metadata.ValueKind != JsonValueKind.Array) return;
        var raw = metadata.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String).Select(value => value.GetString() ?? "")
            .Where(ValidIcsRoundtripLine).Where(line =>
            {
                var property = ParseIcsProperty(line);
                return property?.Name != "X-MAGNOLIE-REIHENFOLGE" && !(property?.Name == "RELATED-TO" &&
                    property.Parameters.Any(parameter => parameter.Equals("RELTYPE=PARENT", StringComparison.OrdinalIgnoreCase)));
            }).ToArray();
        if (anniversary)
        {
            // Annual core fields are generated; nested VALARM data remains opaque.
            var depth = 0;
            raw = raw.Where(line =>
            {
                var name = PropertyName(line);
                if (name == "BEGIN") depth++;
                var keep = depth > 0 || name is not ("DTSTART" or "DTEND" or "DUE" or "DURATION" or "RRULE" or
                    "X-MAGNOLIE-DATE" or "X-MAGNOLIE-TYPE-ID" or "X-MAGNOLIE-TYP" or "X-MAGNOLIE-JAHRESTAG-TYP");
                if (name == "END") depth--;
                return keep;
            }).ToArray();
        }
        var properties = raw.Select(ParseIcsProperty).OfType<IcsProperty>().ToList();
        var topLevel = TopLevelProperties(properties);
        var task = lines[0] == "BEGIN:VTODO";
        if (topLevel.Any(property => property.Name == "DTSTART" || task && property.Name == "DUE"))
        {
            var zone = CalendarRecurrence.Zone(J(item, "icsAnzeigeZeitzone"));
            var zones = CalendarRecurrence.CalendarZones(item);
            var original = task ? ParseTask(properties, zone, zones) : ParseEvent(properties, zone, zones).Value;
            var fields = task ? new[] { "startDatum", "startZeit", "faellig", "faelligZeit" } : new[] { "datum", "zeit", "endDatum", "endZeit" };
            if (fields.Any(field => item.TryGetProperty(field, out _) && J(item, field) != TextField(original, field)))
            {
                var depth = 0;
                raw = raw.Where(line =>
                {
                    var property = ParseIcsProperty(line)!;
                    if (property.Name == "BEGIN") depth++;
                    var keep = depth > 0 || property.Name is not ("DTSTART" or "DTEND" or "DUE" or "DURATION");
                    if (property.Name == "END") depth--;
                    return keep;
                }).ToArray();
                topLevel = TopLevelProperties(raw.Select(ParseIcsProperty).OfType<IcsProperty>());
                var zoneId = TimeZoneInfo.TryConvertWindowsIdToIanaId(zone.Id, out var iana) ? iana : zone.Id;
                for (var index = 0; index < lines.Count; index++)
                {
                    var property = ParseIcsProperty(lines[index]);
                    if (property?.Name is not ("DTSTART" or "DTEND" or "DUE") || property.Value.Length == 8 ||
                        property.Value.EndsWith('Z') || property.Parameters.Any(value => value.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase))) continue;
                    lines[index] = zoneId is "UTC" or "Etc/UTC" ? property.Name + ":" + property.Value + "Z" :
                        new IcsProperty(property.Name, property.Value, property.Parameters.Append("TZID=" + zoneId).ToArray()).Raw;
                }
            }
        }
        var replace = topLevel.Select(property => property.Name).Where(name => name is "DTSTART" or "DTEND" or "DUE" or "DURATION" or "RRULE" or "EXRULE" or "RECURRENCE-ID" or "STATUS").ToHashSet();
        lines.RemoveAll(line => replace.Contains(PropertyName(line)));
        var rawDepth = 0;
        foreach (var line in raw)
        {
            var name = PropertyName(line);
            if (name == "BEGIN") rawDepth++;
            if (rawDepth > 0 || name is not ("SUMMARY" or "DESCRIPTION" or "CATEGORIES" or "PRIORITY")) lines.Add(line);
            if (name == "END") rawDepth = Math.Max(0, rawDepth - 1);
        }
        var duration = topLevel.Any(property => property.Name == "DURATION");
        if (duration) lines.RemoveAll(line => PropertyName(line) is "DTEND" or "DUE");
    }

    private static SortedSet<DateOnly> StructuredDates(JsonElement item, string name)
    {
        if (!item.TryGetProperty(name, out var values) || values.ValueKind != JsonValueKind.Array) return new();
        return new SortedSet<DateOnly>(values.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String &&
            DateOnly.TryParseExact(value.GetString(), "yyyy-MM-dd", out _)).Select(value => DateOnly.ParseExact(value.GetString()!, "yyyy-MM-dd")));
    }

    private static SortedSet<(DateOnly Date, string Time)> StructuredOccurrences(JsonElement item)
    {
        var result = new SortedSet<(DateOnly, string)>();
        if (!item.TryGetProperty("icsZusatzTermine", out var values) || values.ValueKind != JsonValueKind.Array) return result;
        foreach (var value in values.EnumerateArray())
            if (value.ValueKind == JsonValueKind.Object && DateOnly.TryParseExact(J(value, "datum"), "yyyy-MM-dd", out var date) &&
                J(value, "zeit").Length > 0 && TimeOnly.TryParseExact(J(value, "zeit"), "HH:mm", out _))
                result.Add((date, J(value, "zeit")));
        return result;
    }

    private static HashSet<DateOnly> IcsDates(IEnumerable<string> lines, string name)
    {
        var result = new HashSet<DateOnly>();
        foreach (var line in lines)
        {
            var property = ParseIcsProperty(line);
            if (property?.Name != name) continue;
            foreach (var rawDate in property.Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                try { result.Add(DateOnly.FromDateTime(ParseIcsDate(property with { Value = rawDate }).DateTime)); }
                catch (Exception) when (rawDate.Length > 0) { }
        }
        return result;
    }

    private static string RecurrenceDateLine(string name, IEnumerable<DateOnly> dates, string time) =>
        (time.Length > 0 ? name + ":" : name + ";VALUE=DATE:") + string.Join(',', dates.Select(value =>
            value.ToString("yyyyMMdd") + (time.Length > 0 ? "T" + time.Replace(":", "") + "00" : "")));

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
        var colon = ContentColon(line); if (colon < 1) return null;
        var head = SplitVCardHeader(line[..colon]);
        return new IcsProperty(head[0].ToUpperInvariant(), line[(colon + 1)..], head.Skip(1).ToArray());
    }

    private static int ContentColon(string line)
    {
        var quoted = false;
        for (var index = 0; index < line.Length; index++)
        {
            if (line[index] == '"') quoted = !quoted;
            else if (line[index] == ':' && !quoted) return index;
        }
        return -1;
    }

    internal static string SupplementVCard(string embedded, IEnumerable<string> fallback, Func<string, string>? photoResolver = null)
    {
        var lines = UnfoldVCard(embedded).Where(line => line.Length <= 65536 && ContentColon(line) > 0 &&
            VCardPropertyName(line) is not ("BEGIN" or "END" or "VERSION" or "UID")).ToList();
        var embeddedValues = ParseVCardProperties(lines);
        if (photoResolver is not null && Photo(embeddedValues).Length == 0)
        {
            var resolved = Entries(embeddedValues, "PHOTO").Select(photo => photoResolver(photo.Value)).FirstOrDefault(value => value.Length > 0);
            if (resolved is not null) { lines.RemoveAll(line => VCardPropertyName(line) == "PHOTO"); lines.Add("PHOTO:" + resolved); }
        }
        foreach (var line in fallback)
        {
            var name = VCardPropertyName(line);
            if (name is "BEGIN" or "END" or "VERSION") continue;
            var existing = ParseVCardProperties(lines);
            var entry = Entries(ParseVCardProperties([line]), name).FirstOrDefault();
            if (entry is null) continue;
            if (name is "N" or "FN" or "ORG" or "BDAY" or "ANNIVERSARY" or "NOTE" or "PHOTO" or "TITLE" or "NICKNAME")
            {
                if (name == "PHOTO" && Photo(existing).Length == 0 && Photo(ParseVCardProperties([line])).Length > 0)
                    lines.RemoveAll(value => VCardPropertyName(value) == "PHOTO");
                else if (Entries(existing, name).Any(value => value.Raw.Length > 0)) continue;
            }
            else
            {
                var prefix = name == "TEL" ? "tel:" : name == "EMAIL" ? "mailto:" : "";
                if (Entries(existing, name).Any(value => CleanUri(value.Value, prefix).Equals(CleanUri(entry.Value, prefix),
                    name == "EMAIL" ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))) continue;
            }
            lines.Add(line);
        }
        return "BEGIN:VCARD\r\nVERSION:3.0\r\n" + string.Join("\r\n", lines) + "\r\nEND:VCARD\r\n";
    }

    private static IcsProperty? First(IEnumerable<IcsProperty> values, string name) => values.FirstOrDefault(value => value.Name == name);
    private static (DateTime DateTime, bool AllDay) ParseIcsDate(IcsProperty property, TimeZoneInfo? timeZone = null, IReadOnlyDictionary<string, CalendarRecurrence.SourceZone>? zones = null)
    {
        var stamp = CalendarRecurrence.ParseStamp(new CalendarRecurrence.Property(property.Name, property.Value, property.Parameters), zones);
        return (CalendarRecurrence.InZone(stamp, timeZone ?? TimeZoneInfo.Local), stamp.AllDay);
    }

    private static bool RecurrenceZoneIsLocal(IcsProperty property)
    {
        if (property.Value.EndsWith('Z')) return TimeZoneInfo.Local.HasSameRules(TimeZoneInfo.Utc);
        var parameter = property.Parameters.FirstOrDefault(value =>
            value.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase));
        if (parameter is null) return true;
        var zoneId = parameter[5..].Trim('"');
        try
        {
            var zone = TimeZoneInfo.FindSystemTimeZoneById(zoneId);
            return zone.Id == TimeZoneInfo.Local.Id || zone.HasSameRules(TimeZoneInfo.Local);
        }
        catch (TimeZoneNotFoundException)
        {
            if (!TimeZoneInfo.TryConvertIanaIdToWindowsId(zoneId, out var windowsId)) return false;
            try
            {
                var zone = TimeZoneInfo.FindSystemTimeZoneById(windowsId);
                return zone.Id == TimeZoneInfo.Local.Id || zone.HasSameRules(TimeZoneInfo.Local);
            }
            catch (TimeZoneNotFoundException) { return false; }
        }
    }

    private static string RecurrenceKind(string rule, DateTime start)
    {
        if (rule.Length == 0) return "none";
        var parts = rule.Split(';').Select(value => value.Split('=', 2)).ToArray();
        if (parts.Any(part => part.Length != 2) ||
            parts.Select(part => part[0].ToUpperInvariant()).Distinct().Count() != parts.Length ||
            parts.Any(part => part[0].ToUpperInvariant() is not
                ("FREQ" or "INTERVAL" or "UNTIL" or "BYDAY" or "BYMONTHDAY" or "BYMONTH" or "BYSETPOS" or "WKST"))) return "";
        if (RRuleValue(rule, "INTERVAL") is { Length: > 0 } interval &&
            (!int.TryParse(interval, out var parsed) || parsed < 1 || parsed > 3660)) return "";
        var frequency = RRuleValue(rule, "FREQ").ToUpperInvariant();
        if (RRuleValue(rule, "INTERVAL") is { Length: > 0 } value && value != "1" &&
            frequency is not ("DAILY" or "WEEKLY")) return "";
        if (RRuleValue(rule, "WKST") is { Length: > 0 } weekStart &&
            !Regex.IsMatch(weekStart, "^(MO|TU|WE|TH|FR|SA|SU)$", RegexOptions.IgnoreCase)) return "";
        var weekdays = new[] { "SU", "MO", "TU", "WE", "TH", "FR", "SA" };
        var startWeekday = weekdays[(int)start.DayOfWeek];
        return frequency switch
        {
            "DAILY" when EmptyRuleValues(rule, "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS") => "daily",
            "WEEKLY" when (RRuleValue(rule, "BYDAY") is "" ||
                          RRuleValue(rule, "BYDAY").Equals(startWeekday, StringComparison.OrdinalIgnoreCase)) &&
                          EmptyRuleValues(rule, "BYMONTHDAY", "BYMONTH", "BYSETPOS") => "weekly",
            "MONTHLY" when MonthlyWeekday(rule).Form.Length > 0 ||
                           EmptyRuleValues(rule, "BYDAY", "BYMONTH", "BYSETPOS") &&
                           RRuleValue(rule, "BYMONTHDAY") is var monthDay &&
                           (monthDay.Length == 0 || monthDay == start.Day.ToString(CultureInfo.InvariantCulture)) => "monthly",
            "YEARLY" when EmptyRuleValues(rule, "BYDAY", "BYSETPOS") &&
                          RRuleValue(rule, "BYMONTH") is var month &&
                          (month.Length == 0 || month == start.Month.ToString(CultureInfo.InvariantCulture)) &&
                          RRuleValue(rule, "BYMONTHDAY") is var yearDay &&
                          (yearDay.Length == 0 || yearDay == start.Day.ToString(CultureInfo.InvariantCulture)) => "yearly",
            _ => ""
        };
    }
    private static bool EmptyRuleValues(string rule, params string[] names) =>
        names.All(name => RRuleValue(rule, name).Length == 0);
    private static (string Form, int Ordinal, string Weekday) MonthlyWeekday(string rule)
    {
        if (rule.Length == 0) return ("", 0, "");
        var parts = rule.Split(';').Select(value => value.Split('=', 2)).ToArray();
        if (parts.Any(part => part.Length != 2) || parts.Select(part => part[0].ToUpperInvariant()).Distinct().Count() != parts.Length ||
            parts.Any(part => part[0].ToUpperInvariant() is not ("FREQ" or "INTERVAL" or "UNTIL" or "BYDAY" or "BYSETPOS" or "WKST")) ||
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
    private static string IcsText(string value) => VCardText(value);
    private static int TaskPriority(string? value) => int.TryParse(value, out var priority) ? priority is >= 1 and <= 3 ? 1 : priority >= 7 ? 3 : 2 : 2;

    private static Dictionary<string, List<VCardEntry>> ParseVCardProperties(IEnumerable<string> lines)
    {
        var source = lines.ToArray();
        var labels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in source)
        {
            var colon = ContentColon(line);
            if (colon > 0 && VCardPropertyName(line) == "X-ABLABEL") labels[line[..colon].Split('.')[0]] = VCardText(line[(colon + 1)..]);
        }
        var result = new Dictionary<string, List<VCardEntry>>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in source)
        {
            var colon = ContentColon(line); if (colon < 1) continue;
            var head = SplitVCardHeader(line[..colon]); var name = head[0].Split('.').Last().ToUpperInvariant();
            var types = head.Skip(1).SelectMany(value => value.StartsWith("TYPE=", StringComparison.OrdinalIgnoreCase) ? value[5..].Trim('"').Split(',') : value.Contains('=') ? [] : new[] { value }).Select(value => value.ToUpperInvariant()).ToArray();
            if (!result.TryGetValue(name, out var list)) result[name] = list = new List<VCardEntry>();
            var raw = line[(colon + 1)..];
            if (head.Any(value => value.Equals("ENCODING=QUOTED-PRINTABLE", StringComparison.OrdinalIgnoreCase) || value.Equals("QUOTED-PRINTABLE", StringComparison.OrdinalIgnoreCase)))
            {
                Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
                var charset = head.FirstOrDefault(value => value.StartsWith("CHARSET=", StringComparison.OrdinalIgnoreCase))?[8..].Trim('"') ?? "utf-8";
                var bytes = new List<byte>();
                for (var index = 0; index < raw.Length; index++)
                    if (raw[index] == '=' && index + 2 < raw.Length && byte.TryParse(raw.AsSpan(index + 1, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var octet))
                    { bytes.Add(octet); index += 2; }
                    else bytes.AddRange(Encoding.UTF8.GetBytes(raw[index].ToString()));
                raw = Encoding.GetEncoding(charset).GetString(bytes.ToArray());
            }
            list.Add(new VCardEntry(raw, types, head.Skip(1).ToArray(), head[0].Contains('.') ? labels.GetValueOrDefault(head[0].Split('.')[0], "") : ""));
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
        .Where(line => SafeUnknownVCardLine(line)).Select(line => JsonValue.Create(line)).ToArray());
    private static bool SafeParameter(string value) => value.Length <= 1024 &&
        Regex.IsMatch(value, "^[A-Za-z0-9-]+(?:=(?:[^\\r\\n\\\";:,]+|\\\"[^\\r\\n\\\"]*\\\"))?$");
    private static bool SafeUnknownVCardLine(string line, bool checkLength = true)
    {
        if (line.Length < 3 || checkLength && line.Length > 65536 || line.IndexOfAny(['\r', '\n']) >= 0) return false;
        var colon = ContentColon(line); if (colon < 1) return false;
        var name = line[..colon].Split(';')[0].Split('.').Last().ToUpperInvariant();
        return name is not ("BEGIN" or "END" or "VERSION" or "TEL" or "EMAIL" or "ADR" or "NOTE" or "UID" or "REV" or "X-ABLABEL" or "X-MAGNOLIE-KONTAKTPERSON-NAME" or "X-MAGNOLIE-KONTAKTPERSON-TELEFON" or "X-MAGNOLIE-KONTAKTPERSON-STATUS" or "X-MAGNOLIE-NOTFALLKONTAKT" or "X-MAGNOLIE-SOZIALES-MEDIUM");
    }
    private static string Value(Dictionary<string, List<VCardEntry>> values, string name) => VCardText(RawValue(values, name));
    private static string RawValue(Dictionary<string, List<VCardEntry>> values, string name) => values.TryGetValue(name, out var list) ? list.FirstOrDefault()?.Raw ?? "" : "";
    private static IEnumerable<VCardEntry> Entries(Dictionary<string, List<VCardEntry>> values, string name) => values.TryGetValue(name, out var list) ? list : Enumerable.Empty<VCardEntry>();
    private static string[] SplitVCard(string value)
        => SplitEscaped(value, ';').Select(VCardText).ToArray();

    private static string[] SplitEscaped(string value, char separator)
    {
        var parts = new List<string>(); var current = new StringBuilder(); var escaped = false;
        foreach (var character in value)
        {
            if (character == separator && !escaped) { parts.Add(current.ToString()); current.Clear(); continue; }
            current.Append(character);
            escaped = character == '\\' && !escaped;
            if (character != '\\') escaped = false;
        }
        parts.Add(current.ToString()); return parts.ToArray();
    }
    private static string NameComponent(string value) => string.Join(' ', SplitEscaped(value, ',').Select(VCardText));
    internal static string[] VCardNameParts(IEnumerable<string> lines)
    {
        var parts = SplitEscaped(RawValue(ParseVCardProperties(lines), "N"), ';');
        return Enumerable.Range(0, 5).Select(index => NameComponent(parts.ElementAtOrDefault(index) ?? "")).ToArray();
    }
    private static string VCardPropertyName(string line) => line.Split(':', 2)[0].Split(';')[0].Split('.').Last().ToUpperInvariant();
    private static string TextField(JsonObject item, string name) => item[name]?.ToString() ?? "";
    private static string VCardDate(VCardEntry? entry)
    {
        if (entry is null) return "";
        var date = ParseBirthday(entry.Value);
        var omittedYear = entry.Parameters.FirstOrDefault(value => value.StartsWith("X-APPLE-OMIT-YEAR=", StringComparison.OrdinalIgnoreCase))?.Split('=', 2)[1].Trim('"');
        return date.Length == 10 && omittedYear == date[..4] ? "--" + date[5..] : date;
    }
    private static string VCardText(string value)
    {
        var result = new StringBuilder();
        for (var index = 0; index < value.Length; index++)
        {
            if (value[index] == '\\' && index + 1 < value.Length)
            { index++; result.Append(value[index] is 'n' or 'N' ? '\n' : value[index]); }
            else result.Append(value[index]);
        }
        return result.ToString();
    }
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
            unknown = yearText.Length == 0 || yearText.All(character => character == '0');
            birthdayRaw = unknown ? $"--{month:00}-{day:00}" : Regex.IsMatch(yearText, "^\\d{4}$")
                ? $"{yearText}-{month:00}-{day:00}" : "";
        }
        // The case-insensitive map aliases "birthday" to LDIF's split "birthDay".
        if (birthdayRaw.Length == 0) birthdayRaw = One("birthday");
        var birthday = ParseBirthday(birthdayRaw); unknown |= birthdayRaw.StartsWith("--", StringComparison.Ordinal);
        var name = (first + " " + last).Trim(); var company = One("o", "organization", "company"); if (name.Length == 0) name = display.Length > 0 ? display : company;
        if (name.Length == 0 && emails.Length == 0) return null;
        var notes = Many("description", "info", "notes", "remarks", "custom1", "custom2", "custom3", "custom4", "mozillaCustom1", "mozillaCustom2", "mozillaCustom3", "mozillaCustom4", "homeUrl", "workUrl").Distinct().ToArray();
        var anniversary = ParseBirthday(One("anniversary", "dateOfAnniversary"));
        if (anniversary.Length == 0 && int.TryParse(One("anniversaryMonth"), out var anniversaryMonth) && int.TryParse(One("anniversaryDay"), out var anniversaryDay))
        {
            var year = One("anniversaryYear");
            anniversary = ParseBirthday(year.Length > 0 ? $"{year}-{anniversaryMonth:00}-{anniversaryDay:00}" : $"--{anniversaryMonth:00}-{anniversaryDay:00}");
        }
        var contact = new JsonObject { ["uid"] = One("entryUUID", "uid"), ["vorname"] = first, ["nachname"] = last, ["anzeigename"] = display, ["firma"] = company, ["jubilaeum"] = anniversary,
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
        if (J(contact, "anzeigename").Length > 0) parts.Add("FN:" + J(contact, "anzeigename"));
        if (J(contact, "jubilaeum").Length > 0) parts.Add("ANNIVERSARY:" + J(contact, "jubilaeum"));
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
                var label = J(entry, "label"); var group = label.Length > 0 ? $"item{lines.Count}." : "";
                lines.Add(group + property + (types.Length > 0 ? ";TYPE=" + string.Join(',', types) : "") + ExtraParameters(entry) + ":" + V(value));
                if (label.Length > 0) lines.Add(group + "X-ABLabel:" + V(label));
            }
        foreach (var value in fallback) if (value.Length > 0 && seen.Add(value) && (property != "EMAIL" || ValidEmail(value))) lines.Add($"{property}:{V(value)}");
    }
    private static void AddAddress(List<string> lines, JsonElement address)
    {
        var street = J(address, "strasse"); var city = J(address, "ort"); var postal = J(address, "plz"); var country = J(address, "land");
        var region = J(address, "region"); var box = J(address, "postfach"); var extra = J(address, "zusatz");
        if (street.Length + city.Length + postal.Length + country.Length + region.Length + box.Length + extra.Length == 0) return;
        var types = address.TryGetProperty("typen", out var typeArray) && typeArray.ValueKind == JsonValueKind.Array ? typeArray.EnumerateArray().Select(type => type.GetString() ?? "").Where(type => Regex.IsMatch(type, "^[A-Za-z0-9-]+$")).ToArray() : Array.Empty<string>();
        var label = J(address, "label"); var group = label.Length > 0 ? $"item{lines.Count}." : "";
        lines.Add(group + "ADR" + (types.Length > 0 ? ";TYPE=" + string.Join(',', types) : "") + ExtraParameters(address) + $":{V(box)};{V(extra)};{V(street)};{V(city)};{V(region)};{V(postal)};{V(country)}");
        if (label.Length > 0) lines.Add(group + "X-ABLabel:" + V(label));
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
    [GeneratedRegex("^BEGIN:VTODO\\s*$.*?^END:VTODO\\s*$", RegexOptions.IgnoreCase | RegexOptions.Multiline | RegexOptions.Singleline)] private static partial Regex TaskBlock();
    [GeneratedRegex("BEGIN:VCARD.*?END:VCARD", RegexOptions.IgnoreCase | RegexOptions.Singleline)] private static partial Regex VCardBlock();
}
