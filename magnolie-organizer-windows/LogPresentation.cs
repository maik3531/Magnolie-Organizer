using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class LogPresentation
{
    internal const string Marker = "\"No valid\"";
    private static Regex MaskPattern(string pattern) => new(pattern, RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    private static readonly Regex SensitiveValue = MaskPattern("""(?i)(["']?\b(?:password|passwd|passphrase|passwort|kennwort|pwd|secret|client_secret|token|access[_-]?token|refresh[_-]?token|api[_-]?key|private[_-]?key|session[_-]?key|authorization|cookie|pin|telefon(?:nummer)?|telephone|phone(?:[_-]?number)?|mobile|mobil|rufnummer|(?:e-?)?mail(?:[_-]?(?:address|adresse))?|ip(?:[_-]?address)?|(?:remote|local|peer)[_-]?(?:address|ip))\b["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n,;}\]]+)""");
    private static readonly Regex Credentials = MaskPattern("""(?i)(https?://)[^\s/@]+:[^\s/@]+@""");
    private static readonly Regex Bearer = MaskPattern("""(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+""");
    private static readonly Regex Email = MaskPattern("""(?<![\w.*])(?!\*+@)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9-]+\.)*[A-Za-z0-9-]+""");
    private static readonly Regex Ipv4 = MaskPattern("""(?<=://)(?:\d{1,3}\.){3}\d{1,3}\b""");
    private static readonly Regex Technical = MaskPattern("""(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+Z-]+)?|\b(?:time_ms|created_ms|expires_ms|timestamp)\b["']?\s*[:=]\s*\d+""");
    private static readonly Regex Phone = MaskPattern("""(?<![\w])\+?\d[\d ()./-]{5,}\d(?![\w])""");

    internal static string MaskSensitive(string value)
    {
        try
        {
            var text = SensitiveValue.Replace(value, match =>
            {
                var quote = match.Groups[2].Value.FirstOrDefault() is '\'' or '"' ? match.Groups[2].Value[..1] : "";
                return match.Groups[1].Value + quote + "***" + quote;
            });
            text = Credentials.Replace(text, match => match.Groups[1].Value + "***:***@");
            text = Bearer.Replace(text, match => match.Groups[1].Value + "***");
            text = Email.Replace(text, "***");
            text = Ipv4.Replace(text, match => match.Value.Split('.').All(part => int.Parse(part) <= 255) ? "***" : match.Value);
            string Numbers(string part) => Phone.Replace(part, match => match.Value.Count(char.IsDigit) is >= 7 and <= 15 ? "***" : match.Value);
            var output = new System.Text.StringBuilder(); var offset = 0;
            foreach (Match match in Technical.Matches(text))
            {
                output.Append(Numbers(text[offset..match.Index])).Append(match.Value); offset = match.Index + match.Length;
            }
            return output.Append(Numbers(text[offset..])).ToString();
        }
        catch (RegexMatchTimeoutException) { return "*** [diagnostic redaction deadline]"; }
    }

    internal static bool HasPersistentContributorUnlock(
        string? plainText, bool contributorHashConfigured, bool plainTextAvailable)
    {
        if (!contributorHashConfigured || !plainTextAvailable || string.IsNullOrWhiteSpace(plainText))
            return false;
        try
        {
            using var document = JsonDocument.Parse(plainText);
            return document.RootElement.TryGetProperty("einstellungen", out var settings) &&
                settings.ValueKind == JsonValueKind.Object &&
                settings.TryGetProperty("allgemein", out var general) &&
                general.ValueKind == JsonValueKind.Object &&
                general.TryGetProperty("contributorFreigeschaltet", out var enabled) &&
                enabled.ValueKind == JsonValueKind.True;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    internal static string Format(string? text, bool unlocked, DateTimeOffset? now = null)
    {
        var lines = MaskSensitive(text ?? "").ReplaceLineEndings("\n").Split('\n').ToList();
        if (lines.Count > 0 && lines[^1].Length == 0) lines.RemoveAt(lines.Count - 1);
        lines.RemoveAll(line => line.Trim().Equals(Marker, StringComparison.Ordinal));
        if (unlocked) return lines.Count == 0 ? "" : string.Join(Environment.NewLine, lines) + Environment.NewLine;

        var timestamp = (now ?? DateTimeOffset.Now).ToString("O");
        if (lines.Count == 0)
        {
            lines.Add($"{timestamp} Diagnostic view created.");
            lines.Add($"{timestamp} No log entries are available.");
        }
        else if (lines.Count == 1)
        {
            lines.Add($"{timestamp} Diagnostic view created.");
        }
        var position = Math.Clamp(lines.Count / 2, 1, lines.Count - 1);
        lines.Insert(position, Marker);
        return string.Join(Environment.NewLine, lines) + Environment.NewLine;
    }

    internal static string CreateView(string logsPath, bool unlocked)
    {
        Directory.CreateDirectory(logsPath);
        RejectReparsePoint(logsPath);
        var viewPath = Path.Combine(logsPath, "Ansicht");
        if (Directory.Exists(viewPath))
        {
            RejectReparsePoint(viewPath);
            foreach (var entry in Directory.EnumerateFileSystemEntries(viewPath))
            {
                if (File.GetAttributes(entry).HasFlag(FileAttributes.ReparsePoint) || Directory.Exists(entry))
                    throw new IOException("Der Protokoll-Ansichtsordner ist nicht sicher.");
                File.Delete(entry);
            }
        }
        else
        {
            Directory.CreateDirectory(viewPath);
            RejectReparsePoint(viewPath);
        }

        var sources = Directory.EnumerateFiles(logsPath, "*.log", SearchOption.TopDirectoryOnly).ToArray();
        if (sources.Length == 0)
        {
            File.WriteAllText(Path.Combine(viewPath, "diagnose.log"), Format("", unlocked));
        }
        else
        {
            foreach (var source in sources)
            {
                if (File.GetAttributes(source).HasFlag(FileAttributes.ReparsePoint))
                    throw new IOException("Eine Protokolldatei ist eine Verknüpfung.");
                File.WriteAllText(Path.Combine(viewPath, Path.GetFileName(source)),
                    Format(File.ReadAllText(source), unlocked));
            }
        }
        return viewPath;
    }

    private static void RejectReparsePoint(string path)
    {
        if (File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
            throw new IOException("Der Protokollpfad ist eine Verknüpfung.");
    }
}
