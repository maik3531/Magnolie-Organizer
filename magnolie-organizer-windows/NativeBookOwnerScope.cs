using System.Security.Cryptography;

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
