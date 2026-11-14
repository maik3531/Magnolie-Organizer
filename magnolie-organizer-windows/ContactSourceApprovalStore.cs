using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record StoredContactSourceBinding(string Source, Uri Collection);

// Native operation-local witness, never a renderer/deserialized permission.
internal sealed class StoredContactSourceApproval
{
    internal ContactSourceApprovalStore Store { get; }
    internal string KeyIdentity { get; }
    internal string Generation { get; }
    internal string AccountRevision { get; }
    internal NativeActorBookSnapshot Snapshot { get; }
    internal IReadOnlyList<StoredContactSourceBinding> Sources { get; }
    internal StoredContactSourceApproval(ContactSourceApprovalStore store, string keyIdentity, string generation,
        string accountRevision, NativeActorBookSnapshot snapshot, IReadOnlyList<StoredContactSourceBinding> sources)
    {
        Store = store; KeyIdentity = keyIdentity; Generation = generation; AccountRevision = accountRevision; Snapshot = snapshot;
        Sources = Array.AsReadOnly(sources.ToArray());
    }

    internal Task RequireCurrentAsync(CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        var current = Store.LoadCurrent();
        if (current is null || current.KeyIdentity != KeyIdentity || current.Generation != Generation ||
            current.AccountRevision != AccountRevision || !ContactSourceApprovalStore.SameSnapshot(current.Snapshot, Snapshot) ||
            !current.Sources.SequenceEqual(Sources))
            throw new UnauthorizedAccessException("contact_source_stored_approval_withdrawn");
        cancellation.ThrowIfCancellationRequested();
        return Task.CompletedTask;
    }
}

// The persistent core only. No application constructor, writer advancement,
// startup hydration, frontend grant or scheduler is implied by this helper.
internal sealed partial class ContactSourceApprovalStore
{
    private sealed class ConsentKeyProtector : ISecretProtector
    {
        private static readonly byte[] Entropy = "Magnolie/native-original-contact-consent/key/v1"u8.ToArray();
        public byte[] Protect(byte[] plain)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            return ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);
        }
        public byte[] Unprotect(byte[] cipher)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            return ProtectedData.Unprotect(cipher, Entropy, DataProtectionScope.CurrentUser);
        }
    }

    private sealed class State(byte[] key, JsonObject payload) : IDisposable
    {
        internal byte[] Key { get; } = key;
        internal JsonObject Payload { get; } = payload;
        internal string Identity => Hex(SHA256.HashData(Key));
        public void Dispose() => CryptographicOperations.ZeroMemory(Key);
    }

    private readonly ContactSourcePrivateFiles files;
    private readonly NextcloudMailboxSettingsStore account;
    private readonly Func<NativeActorBookSnapshot?> captureBook;
    private readonly Func<string> bookBinding;
    private readonly Func<ContactSourcePrimaryBook?>? capturePrimary;
    private readonly ISecretProtector keyProtector;
    private static readonly byte[] Domain = "Magnolie/native-original-contact-consent/windows/v1\0"u8.ToArray();
    private const int StateLimit = 128 * 1024;

    internal ContactSourceApprovalStore(ContactSourcePrivateFiles files, NextcloudMailboxSettingsStore account,
        Func<NativeActorBookSnapshot?> captureBook, Func<string> bookBinding, ISecretProtector? keyProtector = null,
        Func<ContactSourcePrimaryBook?>? capturePrimary = null)
    {
        this.files = files ?? throw new ArgumentNullException(nameof(files));
        this.account = account ?? throw new ArgumentNullException(nameof(account));
        this.captureBook = captureBook ?? throw new ArgumentNullException(nameof(captureBook));
        this.bookBinding = bookBinding ?? throw new ArgumentNullException(nameof(bookBinding));
        this.keyProtector = keyProtector ?? new ConsentKeyProtector();
        this.capturePrimary = capturePrimary;
    }

    private static string Hex(byte[] value) => Convert.ToHexString(value).ToLowerInvariant();
    private static bool IsHex(string? value) => value?.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static byte[] Canonical(JsonNode value) => NativeBookJson.Canonical(value);
    private static string Tag(byte[] key, string label, byte[] value)
    {
        var prefix = Encoding.UTF8.GetBytes(label + "\0");
        var input = new byte[Domain.Length + prefix.Length + value.Length];
        Domain.CopyTo(input, 0); prefix.CopyTo(input, Domain.Length); value.CopyTo(input, Domain.Length + prefix.Length);
        return Hex(HMACSHA256.HashData(key, input));
    }
    private static string Text(JsonObject value, string key) => value[key]?.GetValue<string>()
        ?? throw new InvalidDataException("contact_source_stored_approval_invalid");
    private static void Fields(JsonObject value, params string[] expected)
    {
        if (value.Count != expected.Length || expected.Any(name => !value.ContainsKey(name)))
            throw new InvalidDataException("contact_source_stored_approval_invalid");
    }
    private static JsonObject Parse(string text)
    {
        using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 16 });
        static void Unique(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var item in value.EnumerateObject())
                { if (!names.Add(item.Name)) throw new InvalidDataException("contact_source_stored_approval_duplicate_field"); Unique(item.Value); }
            }
            else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) Unique(item);
        }
        Unique(document.RootElement);
        return JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("contact_source_stored_approval_invalid");
    }

    private State Read(ContactSourcePrivateFiles.Session session)
    {
        if (session.Read(".transaction", 32) != "clean\n") throw new InvalidDataException("contact_source_stored_approval_pending");
        var envelope = Parse(session.Read("approval.json", StateLimit) ?? throw new InvalidDataException("contact_source_stored_approval_missing"));
        Fields(envelope, "payload", "mac");
        var payload = envelope["payload"] as JsonObject ?? throw new InvalidDataException("contact_source_stored_approval_invalid");
        var cipher = Convert.FromBase64String(session.Read(".key.dpapi", 16 * 1024)
            ?? throw new InvalidDataException("contact_source_stored_approval_key_missing"));
        byte[] key;
        try { key = keyProtector.Unprotect(cipher); }
        finally { CryptographicOperations.ZeroMemory(cipher); }
        try
        {
            var signature = Text(envelope, "mac");
            if (key.Length != 32 || !IsHex(signature) || !CryptographicOperations.FixedTimeEquals(
                    Convert.FromHexString(signature), Convert.FromHexString(Tag(key, "record", Canonical(payload)))))
                throw new CryptographicException("contact_source_stored_approval_invalid");
            Fields(payload, "version", "generation", "book", "content", "account", "sources");
            if (payload["version"]?.GetValue<int>() != 1 || !IsHex(Text(payload, "generation")) || !IsHex(Text(payload, "book")) ||
                payload["sources"] is not JsonArray sources || sources.Count > 256)
                throw new InvalidDataException("contact_source_stored_approval_invalid");
            var ids = new HashSet<string>(StringComparer.Ordinal); var hrefs = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in sources)
            {
                if (item is not JsonObject source) throw new InvalidDataException("contact_source_stored_approval_invalid");
                Fields(source, "source", "href");
                var id = Text(source, "source"); var href = Text(source, "href");
                if (id.Length is < 1 or > 8192 || href.Length is < 1 or > 8192 || !ids.Add(id) || !hrefs.Add(href))
                    throw new InvalidDataException("contact_source_stored_approval_invalid");
            }
            if (sources.Count == 0 ? payload["content"] is not null || payload["account"] is not null :
                !IsHex(Text(payload, "content")) || !IsHex(Text(payload, "account")))
                throw new InvalidDataException("contact_source_stored_approval_invalid");
            return new State(key, payload);
        }
        catch { CryptographicOperations.ZeroMemory(key); throw; }
    }

    private State? Active()
    {
        using var session = files.Open();
        if (session is null) return null;
        var state = Read(session);
        try
        {
            if (((JsonArray)state.Payload["sources"]!).Count > 0)
            {
                if (session.Read(".save-intent.json", 16 * 1024) is not null)
                    throw new InvalidDataException("contact_source_native_save_pending");
                return state;
            }
            state.Dispose(); return null;
        }
        catch { state.Dispose(); throw; }
    }

    private void Publish(ContactSourcePrivateFiles.Session session, byte[] key, JsonObject payload)
    {
        var envelope = Envelope(key, payload);
        try
        {
            session.Write(".transaction", "pending\n", 32);
            session.Delete(".save-intent.json");
            var cipher = keyProtector.Protect(key);
            try
            {
                if (cipher.Length == 0 || cipher.AsSpan().SequenceEqual(key))
                    throw new CryptographicException("contact_source_approval_key_not_protected");
                session.Write(".key.dpapi", Convert.ToBase64String(cipher), 16 * 1024);
            }
            finally { CryptographicOperations.ZeroMemory(cipher); }
            session.Write("approval.json", envelope, StateLimit);
            session.Write(".transaction", "clean\n", 32);
            using var actual = Read(session);
            if (!actual.Key.AsSpan().SequenceEqual(key) || !NativeBookJson.Same(actual.Payload, payload))
                throw new IOException("contact_source_stored_approval_write_unconfirmed");
        }
        catch
        {
            try { session.Write(".transaction", "pending\n", 32); } catch { }
            throw;
        }
    }

    private static string Envelope(byte[] key, JsonObject payload)
    {
        var encoded = Canonical(new JsonObject { ["payload"] = payload.DeepClone(), ["mac"] = Tag(key, "record", Canonical(payload)) });
        if (encoded.Length > StateLimit) throw new InvalidDataException("contact_source_native_approval_too_large");
        return Encoding.UTF8.GetString(encoded);
    }

    private (NativeActorBookSnapshot Snapshot, string Binding, string Content) Saved()
    {
        var snapshot = captureBook() ?? throw new InvalidOperationException("contact_source_native_saved_book_required");
        var binding = bookBinding();
        if (binding.Length is < 1 or > 8192 || BaumSyncSnapshot.Hash(snapshot.Text) != snapshot.SavedBook.Sha256)
            throw new InvalidOperationException("contact_source_native_saved_book_required");
        var content = NativeBookJson.Hash(JsonNode.Parse(snapshot.Text) as JsonObject
            ?? throw new InvalidDataException("contact_source_native_saved_book_required"));
        return (snapshot, binding, content);
    }
    internal static bool SameSnapshot(NativeActorBookSnapshot left, NativeActorBookSnapshot right) =>
        left.SavedBook == right.SavedBook && left.Text == right.Text;

    private static bool Matches(NextcloudMailboxSettings settings, string source, Uri collection)
    {
        if (!collection.IsAbsoluteUri || collection.Scheme != Uri.UriSchemeHttps || collection.UserInfo.Length != 0 ||
            collection.Query.Length != 0 || collection.Fragment.Length != 0 || collection.OriginalString.Contains('\\') ||
            collection.OriginalString.Any(char.IsControl) ||
            Regex.IsMatch(collection.OriginalString, "%(2f|5c|00)", RegexOptions.IgnoreCase) ||
            Uri.UnescapeDataString(collection.OriginalString).Split('/').Any(part => part is "." or "..")) return false;
        var decoded = Uri.UnescapeDataString(collection.AbsolutePath);
        if (decoded.Contains('\\') || decoded.Contains('\0') || decoded.Split('/').Any(part => part is "." or "..") ||
            Regex.IsMatch(decoded, "%[0-9a-f]{2}", RegexOptions.IgnoreCase)) return false;
        var server = NextcloudMailbox.ValidateServer(settings.ServerBase);
        return server.Scheme == collection.Scheme && server.IdnHost == collection.IdnHost && server.Port == collection.Port &&
            source == NextcloudDavClient.StableSourceId("addressbook", collection, settings.AccountType);
    }

    internal async Task<StoredContactSourceApproval?> ApproveAsync(NativeActorBookSnapshot snapshot,
        IReadOnlyList<NativeDavContactUpdateApproval> nativeApprovals, CancellationToken cancellation = default)
    {
        cancellation.ThrowIfCancellationRequested();
        var approvals = nativeApprovals.ToArray();
        if (approvals.Length == 0) { Revoke(); return null; }
        if (approvals.Length > 256 || approvals.Any(item => string.IsNullOrEmpty(item.Source) || item.Source.Length > 8192 ||
                item.Collection is null || !item.Collection.IsAbsoluteUri || item.Collection.AbsoluteUri.Length > 8192 || item.RequireApproved is null) ||
            approvals.Select(item => item.Source).Distinct(StringComparer.Ordinal).Count() != approvals.Length ||
            approvals.Select(item => item.Collection.AbsoluteUri).Distinct(StringComparer.Ordinal).Count() != approvals.Length)
            throw new InvalidDataException("contact_source_native_approval_ambiguous");
        var before = Saved();
        if (!SameSnapshot(before.Snapshot, snapshot)) throw new InvalidOperationException("contact_source_approval_book_changed");
        var current = account.ReadContactSourceAccount();
        foreach (var approval in approvals)
        {
            ContactSourceApprovalScope.RequireNativeDecision(approval, cancellation);
            await approval.RequireApproved(cancellation).ConfigureAwait(false);
            ContactSourceApprovalScope.RequireNativeDecision(approval, cancellation);
            if (approval.AccountRevision != current.Revision || !Matches(current.Settings, approval.Source, approval.Collection))
                throw new UnauthorizedAccessException("contact_source_native_approval_changed");
        }
        var key = RandomNumberGenerator.GetBytes(32); var generation = Hex(RandomNumberGenerator.GetBytes(32));
        var keyIdentity = Hex(SHA256.HashData(key));
        try
        {
            var sources = new JsonArray();
            foreach (var approval in approvals.OrderBy(item => item.Source, StringComparer.Ordinal))
                sources.Add(new JsonObject { ["source"] = approval.Source, ["href"] = approval.Collection.AbsoluteUri });
            var payload = new JsonObject { ["version"] = 1, ["generation"] = generation,
                ["book"] = Tag(key, "book", Encoding.UTF8.GetBytes(before.Binding)), ["content"] = before.Content,
                ["account"] = Tag(key, "account", Encoding.UTF8.GetBytes(current.Identity)), ["sources"] = sources };
            _ = Envelope(key, payload); // Reject oversized choices before creating/changing ANY private file.
            using (var session = files.Open(create: true) ?? throw new IOException("contact_source_private_store_missing")) Publish(session, key, payload);
            try
            {
                cancellation.ThrowIfCancellationRequested();
                var after = Saved();
                if (!SameSnapshot(after.Snapshot, snapshot) || after.Binding != before.Binding || account.ReadContactSourceAccount().Revision != current.Revision)
                    throw new InvalidOperationException("contact_source_approval_context_changed");
                foreach (var approval in approvals)
                {
                    ContactSourceApprovalScope.RequireNativeDecision(approval, cancellation);
                    await approval.RequireApproved(cancellation).ConfigureAwait(false);
                    ContactSourceApprovalScope.RequireNativeDecision(approval, cancellation);
                }
            }
            catch { RevokeIfGeneration(generation); throw; }
            var result = LoadCurrent();
            if (result is null || result.Generation != generation || result.KeyIdentity != keyIdentity)
                throw new InvalidOperationException("contact_source_approval_context_changed");
            return result;
        }
        finally { CryptographicOperations.ZeroMemory(key); }
    }

    private void RevokeLocked(ContactSourcePrivateFiles.Session session)
    {
        var key = RandomNumberGenerator.GetBytes(32);
        try { Publish(session, key, new JsonObject { ["version"] = 1, ["generation"] = Hex(RandomNumberGenerator.GetBytes(32)),
            ["book"] = new string('0', 64), ["content"] = null, ["account"] = null, ["sources"] = new JsonArray() }); }
        finally { CryptographicOperations.ZeroMemory(key); }
    }
    internal void Revoke()
    {
        using var session = files.Open(create: true) ?? throw new IOException("contact_source_private_store_missing");
        RevokeLocked(session);
    }
    private void RevokeIfGeneration(string generation)
    {
        using var session = files.Open() ?? throw new IOException("contact_source_private_store_missing");
        using var current = Read(session);
        if (Text(current.Payload, "generation") == generation) RevokeLocked(session);
    }

    internal StoredContactSourceApproval? LoadCurrent()
    {
        using var before = Active();
        if (before is null) return null;
        var saved = Saved();
        if (Text(before.Payload, "content") != saved.Content || Text(before.Payload, "book") != Tag(before.Key, "book", Encoding.UTF8.GetBytes(saved.Binding)))
            return null;
        var current = account.ReadContactSourceAccount();
        if (Text(before.Payload, "account") != Tag(before.Key, "account", Encoding.UTF8.GetBytes(current.Identity))) return null;
        var sources = ((JsonArray)before.Payload["sources"]!).OfType<JsonObject>().Select(item =>
            new StoredContactSourceBinding(Text(item, "source"), new Uri(Text(item, "href"), UriKind.Absolute))).ToArray();
        if (sources.Any(item => !Matches(current.Settings, item.Source, item.Collection)))
            throw new UnauthorizedAccessException("contact_source_stored_source_changed");
        var afterBook = Saved();
        if (!SameSnapshot(afterBook.Snapshot, saved.Snapshot) || afterBook.Binding != saved.Binding || account.ReadContactSourceAccount().Revision != current.Revision)
            throw new InvalidOperationException("contact_source_approval_context_changed");
        using var after = Active();
        if (after is null || !after.Key.AsSpan().SequenceEqual(before.Key) || !NativeBookJson.Same(after.Payload, before.Payload))
            throw new InvalidOperationException("contact_source_approval_context_changed");
        return new StoredContactSourceApproval(this, before.Identity, Text(before.Payload, "generation"), current.Revision,
            saved.Snapshot, Array.AsReadOnly(sources));
    }
}
