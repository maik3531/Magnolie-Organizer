using System.Buffers;
using System.Globalization;
using System.Text.Encodings.Web;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeConnectPacket(long Id, string Type, JsonObject Body);
internal sealed record KdeConnectIdentity(string DeviceId, string DeviceName, int TcpPort,
    string[] IncomingCapabilities, string[] OutgoingCapabilities);
internal sealed record KdeConnectNormalizedSms(string Text, int Units, int Segments, bool Changed);
internal sealed record KdeConnectSmsMessage(string Id, string DeviceId, string ThreadId, string SmsId,
    string From, string[] Addresses, bool Group, string Text, long TimestampMs, bool Incoming);

internal static class KdeConnectProtocol
{
    internal const int Version = 8;
    internal const int FirstPort = 1716;
    internal const int LastPort = 1764;
    internal const int MaxPacketBytes = 512 * 1024;
    internal const int MaxSmsSegments = 10;
    internal const string SmsRequest = "kdeconnect.sms.request";
    internal const string SmsRequestConversations = "kdeconnect.sms.request_conversations";
    internal const string SmsRequestConversation = "kdeconnect.sms.request_conversation";
    internal const string SmsMessages = "kdeconnect.sms.messages";

    private const string GsmBasic = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
    private const string GsmExtension = "^{}\\[~]|€";

    internal static byte[] Encode(string type, JsonObject body, long? id = null)
    {
        if (string.IsNullOrWhiteSpace(type) || type.Length > 200 || type.Any(char.IsControl))
            throw new InvalidDataException("Ungültiger KDE-Connect-Pakettyp.");
        var packet = new JsonObject { ["id"] = id ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            ["type"] = type, ["body"] = body.DeepClone() };
        var bytes = Encoding.UTF8.GetBytes(packet.ToJsonString(new JsonSerializerOptions {
            WriteIndented = false }) + "\n");
        if (bytes.Length > MaxPacketBytes) throw new InvalidDataException("Das KDE-Connect-Paket ist zu groß.");
        return bytes;
    }

    internal static KdeConnectPacket Decode(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 2 || bytes.Length > MaxPacketBytes || bytes[^1] != (byte)'\n' ||
            bytes[..^1].IndexOf((byte)'\n') >= 0 || bytes.IndexOf((byte)'\r') >= 0 || bytes.IndexOf((byte)'\0') >= 0)
            throw new InvalidDataException("Ungültiger KDE-Connect-Paketrahmen.");
        JsonObject root;
        try
        {
            RejectDuplicateMembers(bytes[..^1]);
            root = JsonNode.Parse(bytes[..^1]) as JsonObject ?? throw new InvalidDataException("Das KDE-Connect-Paket ist kein Objekt.");
        }
        catch (JsonException error) { throw new InvalidDataException("Ungültiges KDE-Connect-JSON.", error); }
        if (root.Count != 3 || !root.ContainsKey("id") || !root.ContainsKey("type") || !root.ContainsKey("body"))
            throw new InvalidDataException("Ungültiger KDE-Connect-Paketkopf.");
        long id;
        string type;
        try { id = root["id"]!.GetValue<long>(); type = root["type"]!.GetValue<string>(); }
        catch (InvalidOperationException error) { throw new InvalidDataException("Ungültiger KDE-Connect-Paketkopf.", error); }
        var body = root["body"] as JsonObject ?? throw new InvalidDataException("Der Paketinhalt fehlt.");
        if (id < 0 || type.Length is < 1 or > 200 || type.Any(char.IsControl))
            throw new InvalidDataException("Ungültiger KDE-Connect-Paketkopf.");
        return new KdeConnectPacket(id, type, body.DeepClone().AsObject());
    }

    internal static async Task<KdeConnectPacket> ReadAsync(Stream stream, CancellationToken cancellationToken)
    {
        var writer = new ArrayBufferWriter<byte>();
        var one = new byte[1];
        while (writer.WrittenCount < MaxPacketBytes)
        {
            var read = await stream.ReadAsync(one, cancellationToken).ConfigureAwait(false);
            if (read == 0) throw new EndOfStreamException("KDE Connect hat die Verbindung geschlossen.");
            writer.Write(one);
            if (one[0] == (byte)'\n') return Decode(writer.WrittenSpan);
        }
        throw new InvalidDataException("Das KDE-Connect-Paket ist zu groß.");
    }

    internal static JsonObject IdentityBody(string id, string name, int tcpPort, string? targetDeviceId = null)
    {
        var body = new JsonObject {
            ["deviceId"] = id, ["deviceName"] = name, ["protocolVersion"] = Version,
            ["deviceType"] = "desktop", ["tcpPort"] = tcpPort,
            ["incomingCapabilities"] = new JsonArray(SmsMessages),
            ["outgoingCapabilities"] = new JsonArray(SmsRequest, SmsRequestConversations, SmsRequestConversation)
        };
        if (!string.IsNullOrEmpty(targetDeviceId))
        { body["targetDeviceId"] = targetDeviceId; body["targetProtocolVersion"] = Version; }
        return body;
    }

    internal static KdeConnectIdentity ParseIdentity(KdeConnectPacket packet)
    {
        if (packet.Type != "kdeconnect.identity") throw new InvalidDataException("Keine KDE-Connect-Identität.");
        var body = packet.Body;
        try
        {
            string[] required = ["deviceId", "deviceName", "deviceType", "protocolVersion",
                "incomingCapabilities", "outgoingCapabilities"];
            var allowed = required.Append("tcpPort").Append("targetDeviceId").Append("targetProtocolVersion").ToHashSet(StringComparer.Ordinal);
            if (required.Any(key => !body.ContainsKey(key)) || body.Any(item => !allowed.Contains(item.Key)))
                throw new InvalidDataException("Ungültiger KDE-Connect-Identitätsinhalt.");
            var version = body["protocolVersion"]?.GetValue<int>() ?? 0;
            var id = body["deviceId"]?.GetValue<string>() ?? "";
            var name = body["deviceName"]?.GetValue<string>() ?? "";
            var deviceType = body["deviceType"]?.GetValue<string>() ?? "";
            var port = body["tcpPort"]?.GetValue<int>() ?? FirstPort;
            var targetVersion = body["targetProtocolVersion"];
            if (targetVersion is not null && CanonicalInteger(targetVersion, Version, Version) != Version)
                throw new InvalidDataException("Ungültige KDE-Connect-Zielversion.");
            if (version != Version || !ValidDeviceId(id) || string.IsNullOrWhiteSpace(name) || name.Length > 128 ||
                deviceType is not ("desktop" or "laptop" or "phone" or "smartphone" or "tablet" or "tv") ||
                port is < FirstPort or > LastPort)
                throw new InvalidDataException("Die sichere KDE-Connect-Identität ist ungültig oder inkompatibel.");
            return new KdeConnectIdentity(id, name.Trim(), port, Strings(body["incomingCapabilities"]), Strings(body["outgoingCapabilities"]));
        }
        catch (Exception error) when (error is InvalidOperationException or FormatException or OverflowException)
        { throw new InvalidDataException("Die sichere KDE-Connect-Identität ist ungültig oder inkompatibel.", error); }
    }

    internal static KdeConnectIdentity ParseTargetedIdentity(KdeConnectPacket packet, string localDeviceId)
    {
        var identity = ParseIdentity(packet);
        try
        {
            var hasTargetId = packet.Body.ContainsKey("targetDeviceId");
            var hasTargetVersion = packet.Body.ContainsKey("targetProtocolVersion");
            if (hasTargetId && !string.Equals(packet.Body["targetDeviceId"]?.GetValue<string>() ?? "",
                    localDeviceId, StringComparison.Ordinal) || hasTargetVersion &&
                CanonicalInteger(packet.Body["targetProtocolVersion"], Version, Version) != Version)
                throw new InvalidDataException("Die KDE-Connect-Verbindung ist nicht an dieses Gerät adressiert.");
            return identity;
        }
        catch (Exception error) when (error is InvalidOperationException or FormatException or OverflowException)
        { throw new InvalidDataException("Die KDE-Connect-Zieladressierung ist ungültig.", error); }
    }

    internal static JsonObject RequestConversationsBody() => new();

    internal static JsonObject RequestConversationBody(long threadId, int? count = null)
    {
        if (threadId < 0 || count is <= 0 or > 1000) throw new InvalidDataException("Ungültige SMS-Verlaufsanfrage.");
        var body = new JsonObject { ["threadID"] = threadId, ["rangeStartTimestamp"] = -1 };
        if (count.HasValue) body["numberToRequest"] = count.Value;
        return body;
    }

    internal static JsonObject SmsBody(string number, string text)
    {
        if (string.IsNullOrWhiteSpace(number) || number.Length is < 7 or > 21 || number != number.Trim() ||
            number[0] != '+' || number[1] is < '1' or > '9' || !number.Skip(2).All(char.IsAsciiDigit))
            throw new InvalidDataException("SMS-Empfänger ist ungültig.");
        var normalized = NormalizeSmsText(text);
        if (string.IsNullOrWhiteSpace(normalized.Text) || normalized.Text.Length > 5000 || normalized.Segments > MaxSmsSegments)
            throw new InvalidDataException("SMS-Nachricht ist ungültig oder länger als zehn Segmente.");
        return new JsonObject { ["version"] = 2,
            ["addresses"] = new JsonArray(new JsonObject { ["address"] = number }),
            ["messageBody"] = normalized.Text };
    }

    internal static KdeConnectNormalizedSms NormalizeSmsText(string value)
    {
        if (value is null) throw new InvalidDataException("SMS-Nachricht fehlt.");
        if (value.Contains('\0')) throw new InvalidDataException("SMS-Nachricht enthält ein NUL-Zeichen.");
        var original = value;
        foreach (var replacement in new (string From, string To)[] { ("❤️", "<3"), ("❤", "<3"),
            ("🙂", ":)"), ("😊", ":)"), ("👍", "+1"), ("👎", "-1"), ("😂", ":D"), ("😉", ";)"),
            ("—", "-"), ("–", "-"), ("…", "..."), ("‘", "'"), ("’", "'"), ("‚", "'"),
            ("“", "\""), ("”", "\""), ("„", "\""), (" ", " ") })
            value = value.Replace(replacement.From, replacement.To, StringComparison.Ordinal);
        var result = new StringBuilder();
        foreach (var rune in value.EnumerateRunes())
        {
            var text = rune.ToString();
            var code = rune.Value;
            if (GsmBasic.Contains(text, StringComparison.Ordinal) || GsmExtension.Contains(text, StringComparison.Ordinal)) result.Append(text);
            else if (code is 0xfe0e or 0xfe0f || code is >= 0x1f3fb and <= 0x1f3ff) continue;
            else if (text == "\t") result.Append(' ');
            else if (Rune.GetUnicodeCategory(rune) is UnicodeCategory.NonSpacingMark or UnicodeCategory.SpacingCombiningMark or UnicodeCategory.EnclosingMark) continue;
            else if (Rune.GetUnicodeCategory(rune) is UnicodeCategory.UppercaseLetter or UnicodeCategory.LowercaseLetter or
                UnicodeCategory.TitlecaseLetter or UnicodeCategory.ModifierLetter or UnicodeCategory.OtherLetter)
            {
                var folded = text.Normalize(NormalizationForm.FormKD).Where(character =>
                    GsmBasic.Contains(character) || GsmExtension.Contains(character)).ToArray();
                result.Append(folded.Length == 0 ? "?" : new string(folded));
            }
            else if (Rune.GetUnicodeCategory(rune) is UnicodeCategory.MathSymbol or UnicodeCategory.CurrencySymbol or
                UnicodeCategory.ModifierSymbol or UnicodeCategory.OtherSymbol or UnicodeCategory.ConnectorPunctuation or
                UnicodeCategory.DashPunctuation or UnicodeCategory.OpenPunctuation or UnicodeCategory.ClosePunctuation or
                UnicodeCategory.InitialQuotePunctuation or UnicodeCategory.FinalQuotePunctuation or UnicodeCategory.OtherPunctuation)
                result.Append("[Symbol]");
            else if (!Rune.IsControl(rune)) result.Append('?');
        }
        var normalized = result.ToString();
        var units = normalized.Sum(character => GsmExtension.Contains(character) ? 2 : 1);
        var segments = units == 0 ? 0 : units <= 160 ? 1 : (units + 152) / 153;
        return new KdeConnectNormalizedSms(normalized, units, segments, normalized != original);
    }

    internal static IReadOnlyList<KdeConnectSmsMessage> ParseSmsMessages(KdeConnectPacket packet,
        string deviceId, out int skipped)
    {
        int version;
        try { version = packet.Body["version"]?.GetValue<int>() ?? 0; }
        catch (InvalidOperationException error) { throw new InvalidDataException("Ungültiges KDE-Connect-SMS-Paket.", error); }
        if (packet.Type != SmsMessages || packet.Body.Count != 2 || version != 2 ||
            packet.Body["messages"] is not JsonArray rows || rows.Count > 1000)
            throw new InvalidDataException("Ungültiges KDE-Connect-SMS-Paket.");
        var result = new List<KdeConnectSmsMessage>(); skipped = 0;
        foreach (var node in rows)
        {
            try
            {
                var row = node as JsonObject ?? throw new FormatException();
                var allowed = new HashSet<string>(["_id", "thread_id", "addresses", "body", "date", "type", "read", "event", "sub_id", "attachments"], StringComparer.Ordinal);
                if (row.Any(item => !allowed.Contains(item.Key))) throw new FormatException();
                var text = row["body"]?.GetValue<string>() ?? throw new FormatException();
                if (text.Length == 0) throw new FormatException();
                if (text.Length > 5000) throw new InvalidDataException("SMS-Inhalt überschreitet die Größenbegrenzung.");
                var thread = CanonicalInteger(row["thread_id"], 0, long.MaxValue);
                var occurred = CanonicalInteger(row["date"], 1, long.MaxValue);
                if (occurred > DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 86_400_000) throw new FormatException();
                var type = CanonicalInteger(row["type"], 1, 6);
                var smsEvent = CanonicalInteger(row["event"], 0, int.MaxValue);
                _ = CanonicalInteger(row["read"], 0, 1, allowBoolean: true);
                if (row["sub_id"] is not null) _ = CanonicalInteger(row["sub_id"], 0, int.MaxValue);
                if ((smsEvent & 1) == 0 || type is not (1 or 2)) { skipped++; continue; }
                if (row["addresses"] is not JsonArray addressRows || addressRows.Count < 1) throw new FormatException();
                if (addressRows.Count > 32) throw new InvalidDataException("SMS-Adressliste überschreitet die Größenbegrenzung.");
                var addresses = addressRows.Select(value => {
                    var entry = value as JsonObject ?? throw new FormatException();
                    if (entry.Count != 1) throw new FormatException();
                    var address = entry["address"]?.GetValue<string>() ?? throw new FormatException();
                    if (address.Length is < 1 or > 320 || address != address.Trim() || address.Any(c => char.IsControl(c))) throw new FormatException();
                    return address;
                }).Distinct(StringComparer.Ordinal).ToArray();
                if (row["attachments"] is not null)
                {
                    if (row["attachments"] is not JsonArray attachments) throw new FormatException();
                    if (attachments.Count > 32) throw new InvalidDataException("SMS-Anhangsmetadaten überschreiten die Größenbegrenzung.");
                    foreach (var attachmentNode in attachments)
                    {
                        var attachment = attachmentNode as JsonObject ?? throw new FormatException();
                        var attachmentKeys = new HashSet<string>(["part_id", "mime_type", "encoded_thumbnail", "unique_identifier"], StringComparer.Ordinal);
                        if (attachment.Any(item => !attachmentKeys.Contains(item.Key)) || attachment["part_id"] is null ||
                            attachment["mime_type"] is null || attachment["unique_identifier"] is null) throw new FormatException();
                        _ = CanonicalInteger(attachment["part_id"], 0, long.MaxValue);
                        var mime = attachment["mime_type"]!.GetValue<string>();
                        var unique = attachment["unique_identifier"]!.GetValue<string>();
                        if (mime.Length is < 1 or > 255 || unique.Length is < 1 or > 512) throw new FormatException();
                        if (attachment["encoded_thumbnail"] is not null &&
                            attachment["encoded_thumbnail"]!.GetValue<string>().Length > 256_000)
                            throw new InvalidDataException("SMS-Anhangsmetadaten überschreiten die Größenbegrenzung.");
                    }
                }
                var officialId = row["_id"] is null ? null : CanonicalInteger(row["_id"], 0, long.MaxValue).ToString(CultureInfo.InvariantCulture);
                var canonical = JsonSerializer.SerializeToUtf8Bytes(new object[] { deviceId,
                    thread.ToString(CultureInfo.InvariantCulture), occurred.ToString(CultureInfo.InvariantCulture),
                    type.ToString(CultureInfo.InvariantCulture), addresses, text }, new JsonSerializerOptions {
                        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
                var smsId = officialId ?? "h" + Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant();
                var threadId = thread.ToString(CultureInfo.InvariantCulture);
                result.Add(new KdeConnectSmsMessage($"{deviceId}:{threadId}:{smsId}", deviceId, threadId,
                    smsId, addresses[0], addresses, (smsEvent & 2) != 0, text, occurred, type == 1));
            }
            catch (InvalidDataException) { throw; }
            catch (Exception error) when (error is InvalidOperationException or FormatException or OverflowException or KeyNotFoundException)
            { skipped++; }
        }
        return result;
    }

    internal static string CertificatePin(X509Certificate2 certificate) =>
        Convert.ToHexString(SHA256.HashData(certificate.RawData)).ToLowerInvariant();

    internal static string PairingCode(X509Certificate2 first, X509Certificate2 second, long timestamp)
    {
        if (timestamp <= 0) throw new InvalidDataException("Ungültiger KDE-Connect-Paarungszeitpunkt.");
        var firstKey = first.PublicKey.ExportSubjectPublicKeyInfo();
        var secondKey = second.PublicKey.ExportSubjectPublicKeyInfo();
        var ordered = firstKey.AsSpan().SequenceCompareTo(secondKey) >= 0
            ? firstKey.Concat(secondKey).ToArray() : secondKey.Concat(firstKey).ToArray();
        var time = Encoding.ASCII.GetBytes(timestamp.ToString(CultureInfo.InvariantCulture));
        return Convert.ToHexString(SHA256.HashData(ordered.Concat(time).ToArray()))[..8];
    }

    private static long CanonicalInteger(JsonNode? node, long minimum, long maximum, bool allowBoolean = false)
    {
        if (node is null) throw new FormatException();
        if (allowBoolean && node is JsonValue boolean && boolean.TryGetValue<bool>(out var flag)) return flag ? 1 : 0;
        long value;
        if (node is JsonValue json && json.TryGetValue<long>(out var number)) value = number;
        else if (node is JsonValue integer && integer.TryGetValue<int>(out var intNumber)) value = intNumber;
        else
        {
            if (node is not JsonValue textValue || !textValue.TryGetValue<string>(out var text)) throw new FormatException();
            if (text.Length == 0 || text.Length > 19 || text[0] == '0' && text.Length > 1 || !text.All(char.IsAsciiDigit) ||
                !long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out value)) throw new FormatException();
        }
        if (value < minimum || value > maximum) throw new FormatException();
        return value;
    }

    private static void RejectDuplicateMembers(ReadOnlySpan<byte> json)
    {
        var reader = new Utf8JsonReader(json, new JsonReaderOptions { CommentHandling = JsonCommentHandling.Disallow,
            AllowTrailingCommas = false });
        var objects = new Stack<HashSet<string>?>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.StartObject) objects.Push(new HashSet<string>(StringComparer.Ordinal));
            else if (reader.TokenType == JsonTokenType.StartArray) objects.Push(null);
            else if (reader.TokenType is JsonTokenType.EndObject or JsonTokenType.EndArray) objects.Pop();
            else if (reader.TokenType == JsonTokenType.PropertyName && objects.Peek() is { } names &&
                !names.Add(reader.GetString()!)) throw new InvalidDataException("Doppeltes KDE-Connect-JSON-Feld.");
        }
    }

    private static bool ValidDeviceId(string value) => value.Length is >= 4 and <= 64 &&
        value.All(character => char.IsAsciiLetterOrDigit(character) || character is '_' or '-');

    private static string[] Strings(JsonNode? node)
    {
        if (node is not JsonArray values || values.Count > 512) throw new InvalidDataException("Ungültige KDE-Connect-Fähigkeitsliste.");
        var result = values.Select(value => value?.GetValue<string>() ?? "").ToArray();
        if (result.Any(value => value.Length is < 1 or > 200) || result.Distinct(StringComparer.Ordinal).Count() != result.Length)
            throw new InvalidDataException("Ungültige KDE-Connect-Fähigkeitsliste.");
        return result;
    }
}
