using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class LogPresentation
{
    internal const string Marker = "\"No valid\"";

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
        var lines = (text ?? "").ReplaceLineEndings("\n").Split('\n').ToList();
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
