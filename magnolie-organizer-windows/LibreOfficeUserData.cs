using System.Xml;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal sealed record LibreOfficeUserDataResult(bool Ok, IReadOnlyDictionary<string, string> Felder,
    string Absender, string Fehler);

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
    private static string Get(IReadOnlyDictionary<string, string> fields, string name) =>
        fields.TryGetValue(name, out var value) ? value : "";
    private static string Join(IReadOnlyDictionary<string, string> fields, params string[] names) =>
        string.Join(' ', names.Select(name => Get(fields, name)).Where(value => value.Length > 0));
    private static void Add(List<string> lines, string value) { if (value.Length > 0) lines.Add(value); }
}
