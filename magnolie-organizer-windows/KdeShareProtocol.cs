using System.Buffers;
using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeShareAnnouncement(string Name, long Size, int Port,
    long? NumberOfFiles, long? TotalPayloadSize);

// These are collection hints, never a persistent receive grant or a batch ID.
// Capability advertisement and actual receiving are deliberately separate.
internal static class KdeShareProtocol
{
    internal const string Request = "kdeconnect.share.request";
    internal const string Update = "kdeconnect.share.request.update";
    internal const long MaxFileBytes = 50 * 1024 * 1024;
    private static readonly HashSet<string> BodyFields = new(StringComparer.Ordinal)
        { "filename", "open", "creationTime", "lastModified", "numberOfFiles", "totalPayloadSize" };
    private static readonly HashSet<string> ReservedNames = new(StringComparer.OrdinalIgnoreCase)
        { "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
          "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
          "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
          "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³" };

    internal static long Integer(JsonNode? value)
    {
        if (value is JsonValue atom)
        {
            if (atom.TryGetValue<long>(out var number) && number >= 0) return number;
            if (atom.TryGetValue<int>(out var small) && small >= 0) return small;
        }
        throw new InvalidDataException("invalid_share_integer");
    }

    internal static bool SafeName(string value)
    {
        if (value.Length is < 1 or > 255 || value is "." or ".." || value.EndsWith('.') || value.EndsWith(' ') ||
            value.IndexOfAny(['<', '>', ':', '"', '/', '\\', '|', '?', '*']) >= 0 ||
            ReservedNames.Contains(value.Split('.')[0].TrimEnd(' '))) return false;
        for (var index = 0; index < value.Length;)
        {
            if (Rune.DecodeFromUtf16(value.AsSpan(index), out var rune, out var consumed) != OperationStatus.Done)
                return false;
            if (Rune.GetUnicodeCategory(rune) is UnicodeCategory.Control or UnicodeCategory.Format or
                UnicodeCategory.Surrogate or UnicodeCategory.PrivateUse or UnicodeCategory.OtherNotAssigned) return false;
            index += consumed;
        }
        return true;
    }

    internal static KdeShareAnnouncement Parse(KdeConnectPacket packet)
    {
        if (packet.Type != Request || packet.PayloadSize is not (>= 0 and <= MaxFileBytes) ||
            packet.PayloadPort is not (>= KdeConnectProtocol.FirstPort and <= KdeConnectProtocol.LastPort) ||
            packet.Body.Any(field => !BodyFields.Contains(field.Key)) ||
            packet.Body["filename"] is not JsonValue filename || !filename.TryGetValue<string>(out var name) ||
            name is null || !SafeName(name)) throw new InvalidDataException("invalid_share_announcement");
        if (packet.Body.ContainsKey("open") &&
            (packet.Body["open"] is not JsonValue open || !open.TryGetValue<bool>(out _)))
            throw new InvalidDataException("invalid_share_open_flag");
        foreach (var field in new[] { "creationTime", "lastModified", "numberOfFiles", "totalPayloadSize" })
            if (packet.Body.ContainsKey(field)) Integer(packet.Body[field]);
        return new(name, packet.PayloadSize.Value, packet.PayloadPort.Value,
            packet.Body.ContainsKey("numberOfFiles") ? Integer(packet.Body["numberOfFiles"]) : null,
            packet.Body.ContainsKey("totalPayloadSize") ? Integer(packet.Body["totalPayloadSize"]) : null);
    }

    internal static (long NumberOfFiles, long TotalPayloadSize) ParseUpdate(JsonObject body)
    {
        if (body.Count != 2 || !body.ContainsKey("numberOfFiles") || !body.ContainsKey("totalPayloadSize"))
            throw new InvalidDataException("invalid_share_update");
        return (Integer(body["numberOfFiles"]), Integer(body["totalPayloadSize"]));
    }
}
