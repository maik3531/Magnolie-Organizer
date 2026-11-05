using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

// Native lifecycle authority only; neither document tracking nor a caller revision.
internal sealed class NativeBookOwnerScope
{
    private readonly object gate = new();
    private bool ready;
    private string binding = "";
    private string? source;
    private long saveSequence;
    private string savedHash = "";

    internal void SetReady(bool value)
    {
        lock (gate) { ready = value; if (!value) Reset(); }
    }

    internal void Invalidate()
    { lock (gate) Reset(); }

    private void Reset()
    { source = null; binding = ""; saveSequence = 0; savedHash = ""; }

    // The writer may replace the primary file and still fail before confirming
    // its durability. Invalidate the OLD saved witness before touching storage,
    // while preserving book identity and the monotonic successful-save sequence.
    internal void InvalidateSaved()
    { lock (gate) savedHash = ""; }

    internal string? Current(string nativeBinding, bool nativeAvailable)
    {
        lock (gate)
        {
            if (!ready || !nativeAvailable || string.IsNullOrEmpty(nativeBinding))
            { Reset(); return null; }
            if (source is null || binding != nativeBinding)
            { Reset(); binding = nativeBinding; source = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(); }
            return source;
        }
    }

    // Called only after the existing native book writer confirms its actual store commit.
    internal NativeBookSaveState? RecordSaved(string nativeBinding, bool nativeAvailable, string sha256)
    {
        if (sha256.Length != 64 || sha256.Any(value => value is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            throw new ArgumentException("Invalid native saved-book hash.");
        lock (gate)
        {
            var current = Current(nativeBinding, nativeAvailable); if (current is null) return null;
            saveSequence = checked(saveSequence + 1); savedHash = sha256;
            return new(current, saveSequence, savedHash);
        }
    }

    internal NativeBookSaveState? SaveState(string nativeBinding, bool nativeAvailable)
    {
        lock (gate)
        {
            var current = Current(nativeBinding, nativeAvailable);
            return current is null ? null : new(current, saveSequence, savedHash);
        }
    }
}

internal sealed record NativeBookSaveState(string BookSource, long Sequence, string Sha256);

// Native-only producer input, not target authority and never a wire response.
// Capture must be called afresh under the consumer's native ownership gates;
// retaining this object cannot replace a later source/writer recheck.
internal sealed class NativeActorBookSnapshot
{
    internal NativeBookSaveState SavedBook { get; }
    internal string Text { get; }

    private NativeActorBookSnapshot(NativeBookSaveState savedBook, string text)
    { SavedBook = savedBook; Text = text; }

    internal static NativeActorBookSnapshot? Capture(Func<NativeBookSaveState?> currentSavedBook, Func<string?> currentPlainText)
    {
        ArgumentNullException.ThrowIfNull(currentSavedBook);
        ArgumentNullException.ThrowIfNull(currentPlainText);
        var before = currentSavedBook();
        if (before is null || before.Sequence <= 0 || !Hex(before.BookSource) || !Hex(before.Sha256)) return null;
        var text = currentPlainText();
        if (text is null || text.Length > 256L * 1024 * 1024) return null;
        var bytes = Encoding.UTF8.GetBytes(text);
        try
        {
            if (bytes.LongLength > 256L * 1024 * 1024 ||
                Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() != before.Sha256) return null;
            using var document = JsonDocument.Parse(bytes);
            if (document.RootElement.ValueKind != JsonValueKind.Object || currentSavedBook() != before) return null;
            return new(before, text);
        }
        catch (JsonException) { return null; }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    private static bool Hex(string value) => value.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
}
