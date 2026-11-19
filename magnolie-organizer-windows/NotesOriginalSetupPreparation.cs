using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Native-owned rendezvous with the ordinary renderer save queue. A renderer
// reply is only a restriction: the independent native SavedBook remains required.
internal sealed class NotesOriginalSetupPreparation : IDisposable
{
    private readonly object gate = new();
    private readonly Func<NativeActorBookSnapshot?> capture;
    private readonly Func<string?> nativeSource;
    private readonly Func<long> clock;
    private readonly string source;
    private readonly long deadline;
    private readonly TaskCompletionSource<NativeActorBookSnapshot?> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private bool consumed;
    internal string Token { get; } = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();

    // Caller holds the native book gate. No saved witness is manufactured on load.
    internal NotesOriginalSetupPreparation(Func<string?> nativeSource, Func<NativeActorBookSnapshot?> capture,
        Func<long>? monotonicMilliseconds = null)
    {
        this.nativeSource = nativeSource; this.capture = capture; clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
        source = nativeSource() ?? throw new InvalidOperationException("notes_setup_native_book_required");
        deadline = clock() + 40_000;
    }
    internal Task<NativeActorBookSnapshot?> WaitAsync(CancellationToken cancellation) =>
        completion.Task.WaitAsync(TimeSpan.FromSeconds(40), cancellation);

    // Caller holds the actual native book gate, NOT a receive/tree gate.
    internal bool Accept(string token, bool idle, string savedHash)
    {
        lock (gate)
        {
            if (consumed || token != Token) return false;
            consumed = true;
        }
        NativeActorBookSnapshot? snapshot = null;
        try
        {
            if (idle && clock() < deadline && nativeSource() == source)
            {
                var actual = capture();
                if (actual is not null && actual.SavedBook.BookSource == source && actual.SavedBook.Sha256 == savedHash &&
                    nativeSource() == source && capture()?.SavedBook == actual.SavedBook && clock() < deadline)
                    snapshot = actual;
            }
        }
        finally { completion.TrySetResult(snapshot); }
        return snapshot is not null;
    }
    public void Dispose()
    {
        lock (gate) consumed = true;
        completion.TrySetCanceled();
    }
}
