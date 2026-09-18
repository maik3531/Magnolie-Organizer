using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed class NextcloudSyncJournal
{
    private const long MaximumBytes = 256L * 1024 * 1024;
    private readonly string path;
    private readonly ISecretProtector protector;

    internal NextcloudSyncJournal(string path, ISecretProtector? protector = null)
    {
        this.path = path;
        this.protector = protector ?? new DpapiCurrentUserProtector();
    }

    internal void Save(string transactionId, string phase, JsonObject payload)
    {
        RejectCredentials(payload);
        var plain = Encoding.UTF8.GetBytes(new JsonObject
        {
            ["format"] = 1,
            ["id"] = transactionId,
            ["phase"] = phase,
            ["payload"] = payload.DeepClone()
        }.ToJsonString());
        byte[]? encrypted = null;
        try
        {
            encrypted = protector.Protect(plain);
            if (encrypted.Length == 0 || encrypted.AsSpan().SequenceEqual(plain))
                throw new CryptographicException("Das Synchronisationsjournal wurde nicht geschützt.");
            new AtomicStore().Write(path, Convert.ToBase64String(encrypted), MaximumBytes);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plain);
            if (encrypted is not null) CryptographicOperations.ZeroMemory(encrypted);
        }
    }

    internal (string Id, string Phase, JsonObject Payload)? Load()
    {
        var text = new AtomicStore().Read(path, MaximumBytes);
        if (text is null) return null;
        byte[] encrypted;
        try { encrypted = Convert.FromBase64String(text); }
        catch (FormatException error) { throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.", error); }
        byte[]? plain = null;
        try
        {
            plain = protector.Unprotect(encrypted);
            var root = JsonNode.Parse(plain) as JsonObject ?? throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.");
            if (root["format"]?.GetValue<int>() != 1 || root["id"]?.GetValue<string>() is not { Length: 64 } id ||
                root["phase"]?.GetValue<string>() is not { Length: > 0 } phase || root["payload"] is not JsonObject payload)
                throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.");
            return (id, phase, payload.DeepClone().AsObject());
        }
        catch (Exception error) when (error is not InvalidDataException)
        { throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.", error); }
        finally
        {
            CryptographicOperations.ZeroMemory(encrypted);
            if (plain is not null) CryptographicOperations.ZeroMemory(plain);
        }
    }

    internal string PrepareCreate(string transactionId, Uri href, string mediaType, string text)
    {
        if (transactionId.Length != 64 || transactionId.Any(value => !Uri.IsHexDigit(value))) throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.");
        var creates = new NextcloudSyncJournal(path + ".creates", protector);
        var saved = creates.Load();
        var payload = saved?.Id == transactionId ? saved.Value.Payload : new JsonObject();
        if (payload[href.AbsoluteUri] is JsonObject prior)
        {
            if (prior["mediaType"]?.GetValue<string>() != mediaType || prior["text"] is not JsonValue value || !value.TryGetValue<string>(out var original))
                throw new InvalidDataException("Das Synchronisationsjournal ist beschädigt.");
            if (Regex.Replace(original, @"(?m)^DTSTAMP:[^\r\n]*", "") != Regex.Replace(text, @"(?m)^DTSTAMP:[^\r\n]*", ""))
                throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
            return original;
        }
        payload[href.AbsoluteUri] = new JsonObject { ["mediaType"] = mediaType, ["text"] = text };
        // The exact request survives both a lost response and a later phase failure.
        creates.Save(transactionId, "creates", payload);
        return text;
    }

    internal bool HasPendingCreate(string transactionId, Uri href) =>
        new NextcloudSyncJournal(path + ".creates", protector).Load() is { } saved &&
        saved.Id == transactionId && saved.Payload[href.AbsoluteUri] is JsonObject;

    internal void Delete()
    {
        if (File.Exists(path)) File.Delete(path);
        if (File.Exists(path + ".creates")) File.Delete(path + ".creates");
    }

    internal (string Id, string Phase, JsonObject Payload)? LoadFor(string transactionId,
        IReadOnlyCollection<string> resumablePhases)
    {
        var saved = Load();
        if (saved is null) return null;
        if (saved.Value.Id == transactionId && resumablePhases.Contains(saved.Value.Phase)) return saved;
        Delete();
        return null;
    }

    internal bool Commit(string transactionId)
    {
        var saved = Load();
        if (saved is null || saved.Value.Id != transactionId) return false;
        Delete();
        return true;
    }

    private static void RejectCredentials(JsonNode node)
    {
        if (node is JsonObject value)
        {
            foreach (var item in value)
            {
                if (item.Key.Equals("kennwort", StringComparison.OrdinalIgnoreCase) ||
                    item.Key.Equals("anwendungskennwort", StringComparison.OrdinalIgnoreCase) ||
                    item.Key.Equals("password", StringComparison.OrdinalIgnoreCase) ||
                    item.Key.Equals("authorization", StringComparison.OrdinalIgnoreCase) ||
                    item.Key.Equals("credentials", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Zugangsdaten dürfen nicht im Synchronisationsjournal gespeichert werden.");
                if (item.Value is not null) RejectCredentials(item.Value);
            }
        }
        else if (node is JsonArray array)
            foreach (var item in array) if (item is not null) RejectCredentials(item);
    }
}
