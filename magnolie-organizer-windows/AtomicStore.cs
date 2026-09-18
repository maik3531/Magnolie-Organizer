using System.Text;
using System.Text.Json;
using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed class AtomicStore
{
    internal enum WriteStage { TemporaryFlushed, PrimaryReplaced, BackupReplaced }

    internal const long MaxDataBytes = 256L * 1024 * 1024;
    internal const long MaxArchiveBytes = 384L * 1024 * 1024;
    private static readonly ConcurrentDictionary<string, object> Gates = new(StringComparer.OrdinalIgnoreCase);
    private readonly Action<WriteStage>? checkpoint;

    internal AtomicStore(Action<WriteStage>? checkpoint = null) => this.checkpoint = checkpoint;

    internal string? Read(string path, long maxBytes = MaxDataBytes)
    {
        if (!File.Exists(path)) return null;
        RejectReparsePoint(path);
        var info = new FileInfo(path);
        if (info.Length > maxBytes) throw new IOException("Die Datei ist zu groß.");
        return File.ReadAllText(path, Encoding.UTF8);
    }

    internal void Write(string path, string content, long maxBytes = MaxDataBytes)
    {
        ValidateSize(content, maxBytes);
        lock (Gate(path)) WriteFile(path, content);
    }

    internal void WriteRecoverableJson(string path, string content, long maxBytes = MaxDataBytes)
    {
        ValidateJsonObject(content);
        ValidateSize(content, maxBytes);
        lock (Gate(path))
        {
            WriteFile(path, content);
            checkpoint?.Invoke(WriteStage.PrimaryReplaced);
            WriteFile(BackupPath(path), content);
            checkpoint?.Invoke(WriteStage.BackupReplaced);
        }
    }

    internal string? ReadRecoverableJson(string path, long maxBytes = MaxDataBytes)
    {
        lock (Gate(path))
        {
            var primary = TryReadValidJson(path, maxBytes);
            if (primary is not null) return primary;
            var backup = TryReadValidJson(BackupPath(path), maxBytes);
            if (backup is null)
            {
                if (!File.Exists(path) && !File.Exists(BackupPath(path))) return null;
                throw new InvalidDataException("Der Datenbestand und seine atomare Sicherung sind beschädigt.");
            }
            WriteFile(path, backup);
            return backup;
        }
    }

    internal static string BackupPath(string path) => path + ".bak";

    private void WriteFile(string path, string content)
    {
        ArgumentNullException.ThrowIfNull(content);

        var directory = Path.GetDirectoryName(path)
            ?? throw new IOException("Das Zielverzeichnis fehlt.");
        Directory.CreateDirectory(directory);
        RejectReparseDirectories(directory);
        if (File.Exists(path)) RejectReparsePoint(path);

        var temporary = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write,
                       FileShare.None, 64 * 1024, FileOptions.WriteThrough))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
            {
                writer.Write(content);
                writer.Flush();
                stream.Flush(true);
            }
            checkpoint?.Invoke(WriteStage.TemporaryFlushed);
            File.Move(temporary, path, true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    private string? TryReadValidJson(string path, long maxBytes)
    {
        try
        {
            var text = Read(path, maxBytes);
            if (text is null) return null;
            ValidateJsonObject(text);
            return text;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }

    private static void ValidateJsonObject(string content)
    {
        using var document = JsonDocument.Parse(content);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
            throw new JsonException("Der Datenbestand muss ein JSON-Objekt sein.");
    }

    private static void ValidateSize(string content, long maxBytes)
    {
        ArgumentNullException.ThrowIfNull(content);
        if (Encoding.UTF8.GetByteCount(content) > maxBytes) throw new IOException("Die Datei ist zu groß.");
    }

    private static object Gate(string path)
    {
        var fullPath = Path.GetFullPath(path);
        var directory = Path.GetDirectoryName(fullPath) ?? fullPath;
        return Gates.GetOrAdd(directory, _ => new object());
    }

    internal string Backup(string source, string directory)
    {
        var text = ReadRecoverableJson(source) ?? throw new IOException("Es sind noch keine Daten gespeichert.");
        Directory.CreateDirectory(directory);
        var target = Path.Combine(directory,
            $"magnolie-sicherung-{DateTime.UtcNow:yyyyMMdd-HHmmss-fff}-{RandomNumberGenerator.GetHexString(4).ToLowerInvariant()}.json");
        Write(target, text);
        return target;
    }

    private static void RejectReparsePoint(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("Verknüpfte Dateien werden aus Sicherheitsgründen nicht geöffnet.");
    }

    private static void RejectReparseDirectories(string directory)
    {
        for (var current = new DirectoryInfo(Path.GetFullPath(directory)); current is not null; current = current.Parent)
        {
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Verknüpfte Verzeichnisse werden aus Sicherheitsgründen nicht beschrieben.");
        }
    }
}
