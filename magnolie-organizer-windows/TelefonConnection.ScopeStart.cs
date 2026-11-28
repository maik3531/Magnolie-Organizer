using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private ScopedConnectionStart? scopedConnectionStart;
    private JsonObject? acknowledgedStartScope;
    private bool scopedConnectionStarted;
    private string? scopedInitialRun;
    private JsonObject? writtenInitialFrame;
    private int scopedInitialAttempts;
    private long nextScopedInitialAttempt;
    private bool scopedInitialComplete, scopedInitialRejected;

    internal bool CanOfferScopedConnectionStart()
    {
        try { BuildScopedConnectionStart(); return true; }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException)
        {
            return false;
        }
    }

    internal JsonObject PrepareScopedConnectionStart(string fingerprint, NativeBookSaveState saved)
    {
        if (TelefonCrypto.Fingerprint(peer.PublicKey) != fingerprint)
            throw new InvalidOperationException("The selected connection peer changed.");
        var (authority, reference, format, request) = BuildScopedConnectionStart();
        var now = Environment.TickCount64;
        if (scopedConnectionStart is not { } plan || plan.Expires <= now || plan.Authority != authority ||
            plan.Format != format || !JsonNode.DeepEquals(plan.Reference, reference) || plan.Book.BookSource != saved.BookSource)
        {
            plan = new ScopedConnectionStart(authority, reference, format, request, saved,
                Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), now + 30_000);
            scopedConnectionStart = plan;
        }
        return new JsonObject
        {
            ["token"] = plan.Token, ["run_id"] = plan.Request["run_id"]!.DeepClone(), ["format"] = format,
            ["transport"] = transport, ["scope"] = CurrentContentScope(reference)
        };
    }

    internal void StartScopedConnection(string token, JsonObject request, NativeBookSaveState saved, Action<JsonObject, string> stage)
    {
        if (scopedConnectionStart is not { } plan || plan.Token != token)
            throw new InvalidOperationException("This reader has no matching native start plan.");
        scopedConnectionStart = null;
        var (authority, reference, format, _) = BuildScopedConnectionStart();
        if (plan.Expires <= Environment.TickCount64 || authority != plan.Authority || format != plan.Format ||
            !JsonNode.DeepEquals(reference, plan.Reference) || !JsonNode.DeepEquals(request, plan.Request) ||
            saved.BookSource != plan.Book.BookSource || saved.Sequence < plan.Book.Sequence)
            throw new InvalidOperationException("The native start plan lost its reader, scope or saved book.");
        stage(reference, authority);
        scopedConnectionStarted = true;
    }

    internal void StageScopedConnectionStart(string token, JsonObject request, IReadOnlyList<JsonObject> batches, string text,
        NativeBookSaveState saved, Func<NativeBookSaveState?> currentBook)
    {
        StartScopedConnection(token, request, saved, (scope, authority) => new PersonalSyncStore(store).StageScopedConnectionStart(
            peer.Id, peer.PublicKey, request, CurrentContentScope(scope), batches, text, saved, Now(), authority,
            () => ConnectionRequestAuthority(request, scope), () => currentBook() == saved));
        scopedInitialRun = request["run_id"]!.GetValue<string>();
    }

    private async Task PumpScopedConnectionStartAsync()
    {
        if (scopedInitialRun is not { } runId || scopedInitialComplete || scopedInitialRejected ||
            nextScopedInitialAttempt > Now() || ConnectionReplyBook is not { } currentBook) return;
        var runs = new PersonalSyncStore(store);
        JsonObject? Next() => runs.NextScopedConnectionStart(peer.Id, runId, Now(), ConnectionRequestAuthority, currentBook,
            acknowledgedReplyOriginalControls.ContainsKey);
        try
        {
            if (Next() is not { } frame) return;
            await WritePlainAsync(frame, () =>
            {
                if (!JsonNode.DeepEquals(Next(), frame))
                    throw new InvalidOperationException("The initial connection frame lost its native source before send.");
            });
            Volatile.Write(ref writtenInitialFrame, frame);
            nextScopedInitialAttempt = Now() + TelefonStore.RetryDelayMs(++scopedInitialAttempts);
        }
        catch (Exception error) when (error is InvalidDataException or InvalidOperationException or TelefonMessageException or
            CryptographicException or Microsoft.Data.Sqlite.SqliteException)
        {
            nextScopedInitialAttempt = Now() + TelefonStore.RetryDelayMs(1);
        }
    }

    private async Task<bool> ObserveScopedConnectionStartAckAsync(string id, string status, string error)
    {
        if (Volatile.Read(ref writtenInitialFrame)?["message_id"]?.GetValue<string>() != id) return false;
        await store.NotePolicyGate.WaitAsync(cancellation);
        try
        {
            if (scopedInitialRejected || scopedInitialRun is not { } runId || ConnectionReplyBook is not { } currentBook ||
                writtenInitialFrame is not { } written || written["message_id"]?.GetValue<string>() != id) return true;
            if (status is "accepted" or "duplicate" && error == "none")
            {
                var runs = new PersonalSyncStore(store);
                if (runs.AcknowledgeScopedConnectionStart(peer.Id, runId, written, Now(), ConnectionRequestAuthority, currentBook,
                    acknowledgedReplyOriginalControls.ContainsKey, out var complete))
                {
                    scopedInitialComplete = complete;
                    Volatile.Write(ref writtenInitialFrame, null);
                    scopedInitialAttempts = 0;
                    nextScopedInitialAttempt = 0;
                }
            }
            else if (error != "temporary_failure") scopedInitialRejected = true;
            return true;
        }
        catch (Exception fault) when (fault is InvalidDataException or InvalidOperationException or TelefonMessageException or
            CryptographicException or Microsoft.Data.Sqlite.SqliteException)
        {
            return true;
        }
        finally { store.NotePolicyGate.Release(); }
    }

    private (string Authority, JsonObject Reference, int Format, JsonObject Request) BuildScopedConnectionStart()
    {
        var identity = store.LoadOrCreateIdentity();
        try
        {
            if (scopedConnectionStarted || Volatile.Read(ref acknowledgedConnectionRequest) is not null ||
                StringComparer.Ordinal.Compare(identity.Id, peer.Id) >= 0)
                throw new InvalidOperationException("This reader is not the elected connection initiator.");
        }
        finally { CryptographicOperations.ZeroMemory(identity.PrivateKey); }
        if (Volatile.Read(ref sentConnectionCapabilities) is not { } sent ||
            disposed || cancellation.IsCancellationRequested || store.RestoreFenced ||
            CurrentConnectionReader?.Invoke(this) != true || !ContentScopeControlsReady || receivedContentScope is null)
            throw new InvalidOperationException("Connection automation is waiting for agreed scope controls.");
        var reference = receivedContentScope.CurrentReference(peer.Id, ScopePublicKey, 0);
        if (!JsonNode.DeepEquals(reference, Volatile.Read(ref acknowledgedStartScope)))
            throw new InvalidOperationException("Connection automation is waiting for the exact written scope receipt.");
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
        var modules = new[] { "notes", "tasks" };
        var format = new[] { 14, 3 }.FirstOrDefault(version => current is not null && modules.All(module =>
        {
            var kind = $"personal_{module}_sync";
            return TelefonCoordinator.SupportsPersonalFormat(current, kind, version) &&
                sent["items"]?[kind]?["versions"] is JsonArray versions && versions.Any(value => value?.GetValue<int>() == version);
        }));
        if (format == 0) throw new InvalidOperationException("There is no common scoped connection format.");
        var request = new JsonObject
        {
            ["format"] = format, ["run_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = PersonalSyncContract.AutoConnectionTrigger,
            ["modules"] = new JsonArray("notes", "tasks")
        };
        return (ConnectionRequestAuthority(request, reference), reference, format, request);
    }

    private sealed record ScopedConnectionStart(string Authority, JsonObject Reference, int Format, JsonObject Request,
        NativeBookSaveState Book, string Token, long Expires);
}

internal sealed partial class TelefonCoordinator
{
    internal async Task<JsonObject> PrepareScopedConnectionStartAsync(string peerId, string fingerprint, CancellationToken cancellation)
    {
        await store.NotePolicyGate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            lock (gate)
            {
                cancellation.ThrowIfCancellationRequested();
                if (disposed || !Enabled || store.RestoreFenced || !online.TryGetValue(peerId, out var reader) ||
                    NativeSavedBook() is not { } saved)
                    throw new InvalidOperationException("The connection start needs its native reader and saved book.");
                return reader.PrepareScopedConnectionStart(fingerprint, saved);
            }
        }
        finally { store.NotePolicyGate.Release(); }
    }

    internal async Task StageScopedConnectionStartAsync(string peerId, string token, string sha, JsonObject request,
        IReadOnlyList<JsonObject> batches, string savedText, CancellationToken cancellation)
    {
        await store.NotePolicyGate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            lock (gate)
            {
                cancellation.ThrowIfCancellationRequested();
                if (disposed || !Enabled || store.RestoreFenced || !online.TryGetValue(peerId, out var reader) ||
                    NativeSavedBook() is not { } saved || saved.Sha256 != sha)
                    throw new InvalidOperationException("The connection start lost its native reader or saved book.");
                reader.StageScopedConnectionStart(token, request, batches, savedText, saved, NativeSavedBook);
            }
        }
        finally { store.NotePolicyGate.Release(); }
    }
}
