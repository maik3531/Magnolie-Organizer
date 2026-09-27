using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// A run can reuse its initial recovery point only across exactly acknowledged saves.
// Local edits, another sender/run, restore, restart or expiry break that continuity.
internal sealed class BaumSyncSnapshot
{
    private string run = "", peer = "", afterHash = "";
    private bool snapshotted;
    private DateTimeOffset expires;
    private readonly Func<DateTimeOffset> clock;

    internal BaumSyncSnapshot(Func<DateTimeOffset>? clock = null) => this.clock = clock ?? (() => DateTimeOffset.UtcNow);
    internal static string Hash(string text) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();
    private static string Text(JsonObject? obj, string name) => obj?[name] is JsonValue value && value.TryGetValue<string>(out var text) ? text : "";
    private static bool Valid(JsonObject? proof) => Guid.TryParseExact(Text(proof, "run"), "D", out _) &&
        Text(proof, "peer") is { Length: > 0 and <= 256 } name && !name.Any(char.IsControl) &&
        (Text(proof, "before").Length == 0 || Text(proof, "before").Length == 64 && Text(proof, "before").All(Uri.IsHexDigit));

    internal bool Covers(string previous, JsonObject? proof) => Valid(proof) && snapshotted && clock() < expires &&
        run == Text(proof, "run") && peer == Text(proof, "peer") && afterHash == Hash(previous) &&
        afterHash == Text(proof, "before");

    internal void Saved(string previous, string proposed, JsonObject? proof, bool changed, bool covered)
    {
        var oldHash = Hash(previous); var newHash = Hash(proposed);
        if (Valid(proof) && (Text(proof, "before").Length == 0 || Text(proof, "before") == oldHash))
        {
            if (!covered) expires = clock().AddMinutes(10);
            run = Text(proof, "run"); peer = Text(proof, "peer");
            afterHash = newHash; snapshotted = changed || covered;
        }
        else if (proof is null && !changed && oldHash == afterHash && clock() < expires) afterHash = newHash;
        else { run = peer = afterHash = ""; snapshotted = false; }
    }
}
