using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Local book/source equality and fingerprints ONLY, never telephone records,
// projection hashes, clocks, admission or public signatures. Fractional drawing
// coordinates are valid local JSON; bool and number remain different types.
internal static class NativeBookJson
{
    internal static byte[] Canonical(JsonNode value)
    {
        var text = new StringBuilder(); Write(text, value);
        return new UTF8Encoding(false, true).GetBytes(text.ToString());
    }
    internal static string Hash(JsonNode value) => Convert.ToHexString(SHA256.HashData(Canonical(value))).ToLowerInvariant();
    internal static bool Same(JsonNode left, JsonNode right) => Canonical(left).AsSpan().SequenceEqual(Canonical(right));
    private static void Write(StringBuilder text, JsonNode? value)
    {
        if (value is null) { text.Append("null"); return; }
        if (value is JsonObject map)
        {
            text.Append('{'); var first = true;
            foreach (var pair in map.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                if (!first) text.Append(','); first = false;
                text.Append(JsonSerializer.Serialize(pair.Key)); text.Append(':'); Write(text, pair.Value);
            }
            text.Append('}'); return;
        }
        if (value is JsonArray array)
        {
            text.Append('[');
            for (var index = 0; index < array.Count; index++) { if (index > 0) text.Append(','); Write(text, array[index]); }
            text.Append(']'); return;
        }
        var element = JsonSerializer.SerializeToElement(value);
        if (element.ValueKind == JsonValueKind.Number && (!element.TryGetDouble(out var number) || !double.IsFinite(number)))
            throw new InvalidDataException("invalid_native_book_number");
        text.Append(element.ValueKind == JsonValueKind.String ? JsonSerializer.Serialize(element.GetString()) : element.GetRawText());
    }
}
