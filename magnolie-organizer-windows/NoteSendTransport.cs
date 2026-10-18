using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal sealed class NoteSendException(string code, bool dispatched = false) : Exception(code)
{
    internal string Code { get; } = code;
    internal bool Dispatched { get; } = dispatched;
}
internal sealed record NoteSendSettings(bool Enabled, string FaxServer);
internal sealed record NotePdfReceipt(long Bytes, string Sha256);
internal sealed record NoteMailClient(bool Supported, bool Available, string Id, string Name);
internal sealed record NoteMailEnvelope(string Recipient, string Subject, string PdfPath);
internal sealed record NoteSendReceipt(string Stage, string Adapter, bool Accepted, bool DeliveryConfirmed, NotePdfReceipt Document);

internal static class NoteSendTransport
{
    internal const int MaxPdfBytes = 32 * 1024 * 1024;
    internal static string FaxServer(string value)
    {
        value = value.Trim();
        if (value.Length == 0) return "";
        var match = Regex.Match(value, @"^([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::([0-9]{1,5}))?$");
        if (!match.Success || match.Groups[1].Value.Split('.').Any(label => !Regex.IsMatch(label, @"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")) ||
            match.Groups[2].Success && (!int.TryParse(match.Groups[2].Value, out var port) || port is < 1 or > 65535)) throw new NoteSendException("invalid_fax_server");
        return match.Groups[1].Value.ToLowerInvariant() + (match.Groups[2].Success ? ":" + int.Parse(match.Groups[2].Value) : "");
    }
    internal static NoteSendSettings Settings(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Object) return new(false, "");
        return new(value.TryGetProperty("enabled", out var enabled) && enabled.ValueKind == JsonValueKind.True,
            FaxServer(value.TryGetProperty("faxServer", out var server) && server.ValueKind == JsonValueKind.String ? server.GetString() ?? "" : ""));
    }
    internal static string Recipient(string kind, string value)
    {
        value = value.Trim();
        if (kind == "email")
        {
            if (value.Length > 320 || value.StartsWith('-') || !Regex.IsMatch(value, @"^[^\s@<>;,\x00-\x1f\x7f]+@[^\s@<>;,\x00-\x1f\x7f]+\.[^\s@<>;,\x00-\x1f\x7f]+$")) throw new NoteSendException("invalid_recipient");
            return value;
        }
        if (kind != "fax") throw new NoteSendException("unsupported_adapter");
        if (value.Length > 80 || !Regex.IsMatch(value, @"^\+?[0-9][0-9 ().-]*[0-9]$")) throw new NoteSendException("invalid_recipient");
        var number = Regex.Replace(value, @"[ ().-]", "");
        if (number.Count(char.IsDigit) is < 3 or > 30) throw new NoteSendException("invalid_recipient");
        return number;
    }
    internal static NotePdfReceipt PdfReceipt(string path, string ownedDirectory)
    {
        try
        {
            path = Path.GetFullPath(path); ownedDirectory = Path.GetFullPath(ownedDirectory);
            var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            if (!string.Equals(Path.GetDirectoryName(path), ownedDirectory, comparison) ||
                (File.GetAttributes(ownedDirectory) & FileAttributes.ReparsePoint) != 0 ||
                (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new NoteSendException("invalid_document");
            using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (source.Length is < 8 or > MaxPdfBytes) throw new NoteSendException("invalid_document");
            var before = File.GetLastWriteTimeUtc(path);
            Span<byte> header = stackalloc byte[5]; source.ReadExactly(header);
            if (!header.SequenceEqual("%PDF-"u8)) throw new NoteSendException("invalid_document");
            source.Position = 0; var digest = Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant();
            var length = source.Length; source.Position = Math.Max(0, length - 1024);
            var tail = new byte[length - source.Position]; source.ReadExactly(tail);
            if (!Encoding.ASCII.GetString(tail).Contains("%%EOF", StringComparison.Ordinal) || source.Length != length || File.GetLastWriteTimeUtc(path) != before)
                throw new NoteSendException("invalid_document");
            return new(length, digest);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
        { throw new NoteSendException("invalid_document"); }
    }
    internal static NoteMailClient DiscoverMailClient()
    {
        if (!OperatingSystem.IsWindows()) return new(false, false, "", "");
        try
        {
            string client = "";
            foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
            {
                using var root = RegistryKey.OpenBaseKey(hive, RegistryView.Registry64);
                using var mail = root.OpenSubKey(@"Software\Clients\Mail");
                if (mail?.GetValue(null) is string name && !string.IsNullOrWhiteSpace(name)) { client = name; break; }
            }
            if (client.Length == 0 || !File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "MAPI32.dll"))) return new(true, false, "", "");
            foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
            {
                using var root = RegistryKey.OpenBaseKey(hive, RegistryView.Registry64);
                using var registration = root.OpenSubKey(@"Software\Clients\Mail\" + client);
                foreach (var field in new[] { "DLLPathEx", "DLLPath" })
                    if (registration?.GetValue(field) is string path && File.Exists(Environment.ExpandEnvironmentVariables(path))) return new(true, true, client, client);
            }
            return new(true, false, client, client);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { return new(true, false, "", ""); }
    }
    internal static NoteSendReceipt Handoff(NoteSendSettings settings, string kind, string recipient, string subject, string pdfPath, string ownedDirectory,
        Func<NoteMailEnvelope, uint>? send = null)
    {
        if (!settings.Enabled) throw new NoteSendException("feature_disabled");
        if (kind != "email") throw new NoteSendException("unsupported_adapter");
        recipient = Recipient(kind, recipient); subject = subject.Trim();
        if (subject.Length > 200 || Regex.IsMatch(subject, @"[\x00-\x1f\x7f]")) throw new NoteSendException("invalid_subject");
        var document = PdfReceipt(pdfPath, ownedDirectory);
        if (send is null && (!OperatingSystem.IsWindows() || !DiscoverMailClient().Available)) throw new NoteSendException("native_unavailable");
        uint result;
        try { result = (send ?? SendMapi)(new(recipient, subject, Path.GetFullPath(pdfPath))); }
        catch (Exception error) when (error is DllNotFoundException or EntryPointNotFoundException or BadImageFormatException)
        { throw new NoteSendException("native_unavailable"); }
        return result switch
        {
            0 => new("handed_off", "simple-mapi", true, false, document),
            1 => new("cancelled", "simple-mapi", false, false, document),
            27 => throw new NoteSendException("unsupported_adapter"),
            _ => throw new NoteSendException("native_operation_failed", dispatched: true)
        };
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct MapiRecipient { public uint Reserved, RecipientClass; public string Name, Address; public uint EntryIdSize; public nint EntryId; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct MapiFile { public uint Reserved, Flags, Position; public string Path, Name; public nint FileType; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct MapiMessage
    {
        public uint Reserved; public string Subject, NoteText; public nint MessageType, DateReceived, ConversationId;
        public uint Flags; public nint Originator; public uint RecipientCount; public nint Recipients; public uint FileCount; public nint Files;
    }
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("MAPI32.dll", EntryPoint = "MAPISendMailW", ExactSpelling = true, CharSet = CharSet.Unicode)]
    private static extern uint SendMail(nint session, nint owner, ref MapiMessage message, uint flags, uint reserved);
    private static uint SendMapi(NoteMailEnvelope envelope)
    {
        if (!OperatingSystem.IsWindows() || Thread.CurrentThread.GetApartmentState() != ApartmentState.STA) throw new NoteSendException("native_unavailable");
        var recipient = new MapiRecipient { RecipientClass = 1, Name = envelope.Recipient, Address = "SMTP:" + envelope.Recipient };
        var file = new MapiFile { Position = uint.MaxValue, Path = envelope.PdfPath, Name = "Magnolie " + NativeLocalization.Gettext("Notes") + ".pdf" };
        var recipientPointer = Marshal.AllocHGlobal(Marshal.SizeOf<MapiRecipient>());
        var filePointer = Marshal.AllocHGlobal(Marshal.SizeOf<MapiFile>());
        var recipientWritten = false; var fileWritten = false;
        try
        {
            Marshal.StructureToPtr(recipient, recipientPointer, false); recipientWritten = true;
            Marshal.StructureToPtr(file, filePointer, false); fileWritten = true;
            var message = new MapiMessage { Subject = envelope.Subject, NoteText = "", RecipientCount = 1, Recipients = recipientPointer, FileCount = 1, Files = filePointer };
            // MAPISendMailW: LOGON_UI | DIALOG | FORCE_UNICODE. Never let an
            // ANSI-only provider silently change a recipient, subject or path.
            return SendMail(0, 0, ref message, 0x00000001 | 0x00000008 | 0x00040000, 0);
        }
        finally
        {
            if (recipientWritten) Marshal.DestroyStructure<MapiRecipient>(recipientPointer);
            if (fileWritten) Marshal.DestroyStructure<MapiFile>(filePointer);
            Marshal.FreeHGlobal(recipientPointer); Marshal.FreeHGlobal(filePointer);
        }
    }
}
