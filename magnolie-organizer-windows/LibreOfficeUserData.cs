using System.Xml;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal sealed record LibreOfficeUserDataResult(bool Ok, IReadOnlyDictionary<string, string> Felder,
    string Absender, string Fehler, string Quelle = "libreoffice");

internal static class LibreOfficeUserData
{
    private const long MaxFileBytes = 8 * 1024 * 1024;
    private static readonly HashSet<string> Interesting = new(StringComparer.Ordinal)
    {
        "givenname", "sn", "o", "street", "postalcode", "l", "c", "st",
        "mail", "telephonenumber", "homephone"
    };

    internal static string FindSettingsFile(string? applicationData = null)
    {
        var root = Path.Combine(applicationData ??
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LibreOffice");
        if (!Directory.Exists(root)) return "";
        try
        {
            foreach (var version in Directory.EnumerateDirectories(root)
                         .OrderByDescending(directory => Path.GetFileName(directory),
                             StringComparer.OrdinalIgnoreCase))
            {
                var candidate = Path.Combine(version, "user", "registrymodifications.xcu");
                if (File.Exists(candidate)) return Path.GetFullPath(candidate);
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                             System.Security.SecurityException) { }
        return "";
    }

    internal static LibreOfficeUserDataResult Read(string? path = null)
    {
        path ??= FindSettingsFile();
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return Failure("In LibreOffice wurden noch keine Benutzerdaten eingetragen " +
                "(Extras > Optionen > Benutzerdaten).");
        try
        {
            var info = new FileInfo(path);
            if (info.Length > MaxFileBytes)
                throw new IOException("Die LibreOffice-Einstellungsdatei ist zu groß.");
            if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Verknüpfte LibreOffice-Einstellungsdateien werden nicht geöffnet.");

            var settings = new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                MaxCharactersInDocument = MaxFileBytes,
                IgnoreComments = true
            };
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete);
            using var reader = XmlReader.Create(stream, settings);
            var document = XDocument.Load(reader, LoadOptions.None);
            XNamespace oor = "http://openoffice.org/2001/registry";
            var fields = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in document.Descendants().Where(node => node.Name.LocalName == "item" &&
                         ((string?)node.Attribute(oor + "path"))?.EndsWith("/org.openoffice.UserProfile/Data",
                             StringComparison.Ordinal) == true))
            {
                foreach (var property in item.Descendants().Where(node => node.Name.LocalName == "prop"))
                {
                    var name = (string?)property.Attribute(oor + "name") ?? "";
                    var value = property.Elements().FirstOrDefault(node => node.Name.LocalName == "value")?
                        .Value.Trim() ?? "";
                    if (Interesting.Contains(name) && value.Length > 0 && !fields.ContainsKey(name))
                        fields[name] = value;
                }
            }

            var lines = new List<string>();
            Add(lines, Join(fields, "givenname", "sn"));
            Add(lines, Get(fields, "o"));
            Add(lines, Get(fields, "street"));
            Add(lines, Join(fields, "postalcode", "l"));
            Add(lines, Get(fields, "c"));
            return lines.Count == 0
                ? new LibreOfficeUserDataResult(false, fields, "",
                    "Die LibreOffice-Benutzerdaten enthalten noch keine Anschrift " +
                    "(Extras > Optionen > Benutzerdaten).")
                : new LibreOfficeUserDataResult(true, fields, string.Join('\n', lines), "");
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or XmlException or
                                             System.Security.SecurityException)
        {
            return Failure($"Die LibreOffice-Benutzerdaten konnten nicht gelesen werden: {error.Message}");
        }
    }

    private static LibreOfficeUserDataResult Failure(string message) =>
        new(false, new Dictionary<string, string>(), "", message);

    internal static object ExchangeProfile(string requestId, string operation, IReadOnlyDictionary<string, string> changes, string stamp, string? settingsPath = null)
    {
        var path = settingsPath ?? FindSettingsFile();
        if (path.Length == 0) throw new IOException("No LibreOffice user profile is available.");
        var original = new AtomicStore().Read(path, MaxFileBytes) ?? throw new IOException("No LibreOffice user profile is available.");
        string Digest(string value) => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
        var current = Digest(original);
        using var text = new StringReader(original);
        using var reader = XmlReader.Create(text, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaxFileBytes });
        var document = XDocument.Load(reader, LoadOptions.PreserveWhitespace);
        XNamespace oor = "http://openoffice.org/2001/registry";
        var items = document.Descendants().Where(node => node.Name.LocalName == "item" &&
            ((string?)node.Attribute(oor + "path"))?.EndsWith("/org.openoffice.UserProfile/Data", StringComparison.Ordinal) == true).ToList();
        if (operation == "write")
        {
            if (changes.Any(pair => !Interesting.Contains(pair.Key) || pair.Value.Length > 2000 || pair.Value.Contains('\0')))
                throw new InvalidDataException("Invalid LibreOffice profile fields.");
            if (current != stamp) throw new IOException("LibreOffice user data changed. Compare the fields again.");
            if (File.Exists(Path.Combine(Path.GetDirectoryName(path)!, "..", ".lock")))
                throw new IOException("Close LibreOffice before updating its user data.");
            if (items.Count == 0)
            {
                var item = new XElement("item", new XAttribute(oor + "path", "/org.openoffice.UserProfile/Data"));
                document.Root!.Add(item); items.Add(item);
            }
            foreach (var item in items) foreach (var prop in item.Elements().Where(node => node.Name.LocalName == "prop" &&
                changes.ContainsKey((string?)node.Attribute(oor + "name") ?? "")).ToArray()) prop.Remove();
            foreach (var pair in changes) items[0].Add(new XElement("prop", new XAttribute(oor + "name", pair.Key),
                new XAttribute(oor + "op", "fuse"), new XElement("value", pair.Value)));
            var updated = document.ToString(SaveOptions.DisableFormatting);
            if (new AtomicStore().Read(path, MaxFileBytes) != original) throw new IOException("LibreOffice user data changed. Compare the fields again.");
            new AtomicStore().Write(path, updated, MaxFileBytes); current = Digest(updated);
        }
        else if (operation != "read") throw new InvalidDataException("Invalid profile operation.");
        var fields = new Dictionary<string, string>();
        foreach (var item in items) foreach (var prop in item.Elements())
        {
            var key = (string?)prop.Attribute(oor + "name") ?? "";
            if (Interesting.Contains(key)) fields[key] = prop.Elements().FirstOrDefault(node => node.Name.LocalName == "value")?.Value ?? "";
        }
        return new { requestId, ok = true, felder = fields, stamp = current };
    }
    private static string Get(IReadOnlyDictionary<string, string> fields, string name) =>
        fields.TryGetValue(name, out var value) ? value : "";
    private static string Join(IReadOnlyDictionary<string, string> fields, params string[] names) =>
        string.Join(' ', names.Select(name => Get(fields, name)).Where(value => value.Length > 0));
    private static void Add(List<string> lines, string value) { if (value.Length > 0) lines.Add(value); }
}
