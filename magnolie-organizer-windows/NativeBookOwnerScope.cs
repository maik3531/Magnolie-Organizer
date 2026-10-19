using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Native lifecycle authority only; neither document tracking nor a caller revision.
internal sealed class NativeBookOwnerScope
{
    private readonly object gate = new();
    private bool ready;
    private string binding = "";
    private string? source;

    internal void SetReady(bool value)
    {
        lock (gate) { ready = value; if (!value) { source = null; binding = ""; } }
    }

    internal void Invalidate()
    { lock (gate) { source = null; binding = ""; } }

    internal string? Current(string nativeBinding, bool nativeAvailable)
    {
        lock (gate)
        {
            if (!ready || !nativeAvailable || string.IsNullOrEmpty(nativeBinding))
            { source = null; binding = ""; return null; }
            if (source is null || binding != nativeBinding)
            { binding = nativeBinding; source = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(); }
            return source;
        }
    }
}
