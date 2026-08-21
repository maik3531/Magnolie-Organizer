using System.Text;

namespace MagnolieOrganizer.Windows;

internal static class RotatingLog
{
    internal const long MaximumBytes = 5L * 1024 * 1024;
    internal const int MaximumEntryBytes = 64 * 1024;
    private static readonly Mutex Writer = new(false, "MagnolieOrganizer.Windows.LogWriter.v1");

    internal static void Append(string path, string message)
    {
        var entry = Limited(message.ReplaceLineEndings(" ")) + Environment.NewLine;
        var acquired = false;
        try
        {
            try { acquired = Writer.WaitOne(TimeSpan.FromSeconds(5)); }
            catch (AbandonedMutexException) { acquired = true; }
            if (!acquired) return;
            Directory.CreateDirectory(Path.GetDirectoryName(path) ?? throw new IOException("Der Protokollpfad ist ungültig."));
            if (File.Exists(path) && new FileInfo(path).Length + Encoding.UTF8.GetByteCount(entry) > MaximumBytes)
            {
                var old = path + ".old";
                if (File.Exists(old)) File.Delete(old);
                if (new FileInfo(path).Length <= MaximumBytes) File.Move(path, old);
                else File.Delete(path);
            }
            File.AppendAllText(path, entry, new UTF8Encoding(false));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ObjectDisposedException) { }
        finally { if (acquired) try { Writer.ReleaseMutex(); } catch (ApplicationException) { } }
    }

    internal static string ReadAll(string path)
    {
        var acquired = false;
        try
        {
            try { acquired = Writer.WaitOne(TimeSpan.FromSeconds(5)); }
            catch (AbandonedMutexException) { acquired = true; }
            if (!acquired || !File.Exists(path) || new FileInfo(path).Length > MaximumBytes) return "";
            return File.ReadAllText(path);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ObjectDisposedException) { return ""; }
        finally { if (acquired) try { Writer.ReleaseMutex(); } catch (ApplicationException) { } }
    }

    private static string Limited(string value)
    {
        if (Encoding.UTF8.GetByteCount(value) <= MaximumEntryBytes) return value;
        const string marker = " ... [gekürzt]";
        var budget = MaximumEntryBytes - Encoding.UTF8.GetByteCount(marker);
        var builder = new StringBuilder();
        foreach (var rune in value.EnumerateRunes())
        {
            var bytes = rune.Utf8SequenceLength;
            if (budget < bytes) break;
            builder.Append(rune); budget -= bytes;
        }
        return builder.Append(marker).ToString();
    }
}
