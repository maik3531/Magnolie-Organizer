using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed class TelefonStore
{
    internal const long MaximumMessageTtlMs = 30L * 24 * 60 * 60 * 1000;
    private const long OutboxLimitBytes = 50L * 1024 * 1024;
    private readonly object gate = new();
    private readonly WindowsPaths paths;
    private readonly AtomicStore files;
    private readonly Action<string>? restoreCheckpoint;
    private readonly byte[] storageKey;
    private readonly Dictionary<string, (string Request, string Key, long Expires, bool Include, long Deadline)> identifierRequests = new();
    private readonly Dictionary<string, (JsonObject Value, string Request, string Key, long Expires, long Deadline)> transientIdentifiers = new();
    private string RestoreFencePath => Path.Combine(paths.Telefon, "restore-fence.json");
    internal bool RestoreFenced => Path.Exists(RestoreFencePath) || Path.Exists(AtomicStore.BackupPath(RestoreFencePath));
    internal JsonObject? PendingRestore => RestoreFenced
        ? JsonNode.Parse(files.ReadRecoverableJson(RestoreFencePath) ?? throw new IOException("Restore fence is unreadable."))!.AsObject() : null;
    internal static string ProfileHash(string? stored) => stored is null ? "absent" : Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(stored)));

    internal void BeginRestore(string? token = null)
    {
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("Restore repair is pending.");
            identifierRequests.Clear(); transientIdentifiers.Clear();
            files.WriteRecoverableJson(RestoreFencePath, new JsonObject
            { ["token"] = token ?? Guid.NewGuid().ToString("D"), ["before"] = ProfileHash(files.Read(paths.Data)) }.ToJsonString());
        }
    }

    private JsonObject OwnedRestore(string token)
    {
        var pending = PendingRestore;
        if (pending?["token"]?.GetValue<string>() != token) throw new InvalidOperationException("Restore fence ownership changed.");
        return pending;
    }

    internal void PrepareRestoreCommit(string token, string stored, string epoch)
    {
        lock (gate)
        {
            var pending = OwnedRestore(token);
            pending["after"] = ProfileHash(stored); pending["epoch"] = epoch;
            files.WriteRecoverableJson(RestoreFencePath, pending.ToJsonString());
        }
    }

    internal void SetRestoreSnapshot(string token, string snapshot)
    {
        lock (gate)
        {
            var pending = OwnedRestore(token); pending["snapshot"] = snapshot;
            files.WriteRecoverableJson(RestoreFencePath, pending.ToJsonString());
        }
    }

    internal void ReleaseRestore(string token)
    {
        lock (gate)
        {
            OwnedRestore(token);
            // The primary is the last barrier removed. Never leave a recoverable stale mirror.
            restoreCheckpoint?.Invoke("before-fence-mirror-delete");
            File.Delete(AtomicStore.BackupPath(RestoreFencePath));
            restoreCheckpoint?.Invoke("before-fence-primary-delete");
            File.Delete(RestoreFencePath);
        }
    }

    internal void AbortRestore(string token)
    {
        lock (gate)
        {
            var pending = OwnedRestore(token);
            if (ProfileHash(files.Read(paths.Data)) != pending["before"]?.GetValue<string>())
                throw new InvalidOperationException("Restore content has changed; repair is required.");
            using var connection = OpenDatabase(); connection.Open();
            using var transaction = connection.BeginTransaction();
            using var command = connection.CreateCommand(); command.Transaction = transaction;
            // Do not resurrect pre-fence commands, receive tokens or batches on abort.
            // Keep effect/dedupe and consent high-water marks so old work cannot replay.
            command.CommandText = "DELETE FROM outbox; DELETE FROM inbox; DELETE FROM personal_batch; DELETE FROM personal_domain; DELETE FROM personal_attachment_chunk; DELETE FROM personal_attachment_transfer; DELETE FROM meta WHERE key NOT LIKE 'own_revision_%' AND key NOT GLOB 'personal_custom:*:consent' AND key != 'restore_epoch';";
            command.ExecuteNonQuery(); transaction.Commit();
            ReleaseRestore(token);
        }
    }

    internal void CompleteRestore(string epoch, string? token = null, bool releaseFence = true)
    {
        lock (gate)
        {
            token ??= PendingRestore?["token"]?.GetValue<string>() ?? throw new InvalidOperationException("Restore fence is missing.");
            var pending = OwnedRestore(token);
            if (pending["after"] is not null && (pending["epoch"]?.GetValue<string>() != epoch ||
                pending["after"]?.GetValue<string>() != ProfileHash(files.Read(paths.Data))))
                throw new InvalidOperationException("Restore profile binding changed.");
            using var connection = OpenDatabase(); connection.Open();
            using var previous = connection.CreateCommand(); previous.CommandText = "SELECT value FROM meta WHERE key='restore_epoch'";
            if (previous.ExecuteScalar() is byte[] previousEpoch && Encoding.UTF8.GetString(previousEpoch) == epoch)
            { if (releaseFence) ReleaseRestore(token); return; }
            var quarantine = Path.Combine(paths.Telefon, "restore-quarantine-" + Guid.Parse(token).ToString("N") + ".db");
            restoreCheckpoint?.Invoke("before-quarantine");
            using (var backup = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = quarantine, Pooling = false }.ToString()))
            { backup.Open(); connection.BackupDatabase(backup); }
            restoreCheckpoint?.Invoke("after-quarantine");
            using var transaction = connection.BeginTransaction();
            using var command = connection.CreateCommand(); command.Transaction = transaction;
            // Content restore must not reset the live pairing's consent high-water marks.
            command.CommandText = "DELETE FROM outbox; DELETE FROM inbox; DELETE FROM dedupe; DELETE FROM command_effect; DELETE FROM personal_batch; DELETE FROM personal_domain; DELETE FROM personal_attachment_chunk; DELETE FROM personal_attachment_transfer; DELETE FROM meta WHERE key NOT LIKE 'own_revision_%' AND key NOT GLOB 'personal_custom:*:consent'; INSERT INTO meta(key,value) VALUES('restore_epoch',$epoch);";
            command.Parameters.AddWithValue("$epoch", Encoding.UTF8.GetBytes(epoch)); command.ExecuteNonQuery();
            restoreCheckpoint?.Invoke("before-phone-commit");
            transaction.Commit();
            restoreCheckpoint?.Invoke("after-phone-commit");
            if (releaseFence) ReleaseRestore(token);
        }
    }

    internal TelefonStore(WindowsPaths paths, byte[]? testStorageKey = null,
        AtomicStore? fileStore = null, Action<string>? restoreCheckpoint = null)
    {
        this.paths = paths;
        files = fileStore ?? new AtomicStore();
        this.restoreCheckpoint = restoreCheckpoint;
        Directory.CreateDirectory(paths.Telefon);
        storageKey = testStorageKey?.ToArray() ?? LoadStorageKey();
        if (storageKey.Length != 32) throw new CryptographicException("Ungültiger Telefon-Speicherschlüssel.");
        InitializeDatabase();
        Cleanup(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    internal bool Enabled
    {
        get
        {
            try { return JsonNode.Parse(files.Read(paths.TelefonSettings, 16 * 1024) ?? "{}")?["enabled"]?.GetValue<bool>() == true; }
            catch (Exception) { return false; }
        }
        set { var settings = LoadSettings(); settings["enabled"] = value; SaveSettings(settings); }
    }

    internal bool ReadEnabledStrict() => LoadSettings()["enabled"]?.GetValue<bool>() ?? false;

    internal JsonObject LocalGrants()
    {
        var settings = LoadSettings(); var grants = TelefonProtocolContract.DesktopGrants();
        foreach (var name in TelefonProtocolContract.GrantNames.Where(name => !TelefonProtocolContract.IsDesktopGranted(name)))
            grants[name] = settings[name]?.GetValue<bool>() == true;
        return grants;
    }

    internal void SetLocalGrants(bool smsReceived, bool notifications)
    {
        _ = smsReceived; SetLocalGrant("selected_notifications_readonly", notifications);
    }

    internal void SetLocalGrant(string name, bool enabled)
    {
        if (!TelefonProtocolContract.GrantNames.Contains(name, StringComparer.Ordinal) || TelefonProtocolContract.IsDesktopGranted(name))
            throw new ArgumentOutOfRangeException(nameof(name));
        var settings = LoadSettings(); settings.Remove("sms_received"); settings.Remove("sms_send"); settings.Remove("call_control");
        settings[name] = enabled; SaveSettings(settings);
    }

    internal (bool OwnDevice, bool RemoteOwnDevice, bool AutoWifi) PersonalSettings(string peerId)
    {
        var value = LoadSettings()["personal_sync"]?[peerId] as JsonObject;
        return (value?["own_device"]?.GetValue<bool>() == true, value?["remote_own_device"]?.GetValue<bool>() == true, value?["auto_wifi"]?.GetValue<bool>() == true);
    }

    internal void SetPersonalSettings(string peerId, bool? ownDevice = null, bool? remoteOwnDevice = null, bool? autoWifi = null)
    {
        lock (gate)
        {
        if (ownDevice == false || remoteOwnDevice == false) PurgeIdentifiers(peerId);
        var settings = LoadSettings(); var all = settings["personal_sync"] as JsonObject ?? new JsonObject(); settings["personal_sync"] = all;
        var value = all[peerId] as JsonObject ?? new JsonObject { ["own_device"] = false, ["remote_own_device"] = false, ["auto_wifi"] = false }; all[peerId] = value;
        if (ownDevice.HasValue) value["own_device"] = ownDevice.Value; if (remoteOwnDevice.HasValue) value["remote_own_device"] = remoteOwnDevice.Value; if (autoWifi.HasValue) value["auto_wifi"] = autoWifi.Value;
        if (value["own_device"]?.GetValue<bool>() != true) value["auto_wifi"] = false; SaveSettings(settings);
        if (ownDevice == false || remoteOwnDevice == false) PauseCustom(peerId);
        }
    }

    internal JsonObject CustomSettings(string peerId)
    {
        lock (gate)
        {
            var key = "personal_custom:" + peerId + ":consent";
            using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "SELECT value FROM meta WHERE key=$key"; command.Parameters.AddWithValue("$key", key);
            return command.ExecuteScalar() is byte[] value ? JsonNode.Parse(Open("personal_custom", key, value))!.AsObject() : new JsonObject();
        }
    }

    internal bool CustomSupported(string peerId)
    {
        var peers = LoadPeers().Where(p => p.State == "paired").ToArray();
        return peers.Length == 1 && peers[0].Id == peerId &&
            peers[0].Capabilities["personal_tasks_sync"]?["available"]?.GetValue<bool>() == true &&
            TelefonProtocolContract.DesktopCapabilities()["items"]?["personal_tasks_sync"]?["versions"] is JsonArray local && local.Any(v => TelefonProtocolContract.Integer(v) == 4) &&
            peers[0].Capabilities["personal_tasks_sync"]?["versions"] is JsonArray remote && remote.Any(v => TelefonProtocolContract.Integer(v) == 4);
    }

    internal void SetCustomSettings(string peerId, JsonObject body, bool remote)
    {
        lock (gate)
        {
            PersonalSyncContract.ValidateCustomSettings(body);
            if (!CustomSupported(peerId) && (remote || body["enabled"]!.GetValue<bool>() || !LoadPeers().Any(p => p.Id == peerId)))
                throw new InvalidOperationException("Custom synchronization is not supported.");
            var custom = CustomSettings(peerId); var key = remote ? "remote" : "local";
            if (JsonNode.DeepEquals(custom[key], body)) { PersonalSyncContract.ValidateCustomSettings(body); return; }
            custom[key] = PersonalSyncContract.AcceptCustomSettings(custom[key] as JsonObject, body);
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            var metaKey = "personal_custom:" + peerId + ":consent";
            using (var save = connection.CreateCommand())
            {
                save.Transaction = transaction; save.CommandText = "INSERT OR REPLACE INTO meta(key,value) VALUES($key,$value)";
                save.Parameters.AddWithValue("$key", metaKey); save.Parameters.AddWithValue("$value", Seal("personal_custom", metaKey, TelefonCrypto.Canonical(custom))); save.ExecuteNonQuery();
            }
            using var command = connection.CreateCommand(); command.Transaction = transaction;
            command.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND (kind='personal_sync.custom_batch' OR kind='personal_sync.custom_request' OR ($local=1 AND kind='personal_sync.custom_settings'))";
            command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$local", remote ? 0 : 1); command.ExecuteNonQuery();
            transaction.Commit();
        }
    }

    internal static JsonObject NewCustomSettings(bool enabled, long revision) => new()
    { ["format"] = 4, ["scope"] = "custom", ["enabled"] = enabled, ["revision"] = revision, ["epoch"] = Guid.NewGuid().ToString("D") };

    internal void PauseCustom(string peerId)
    {
        lock (gate)
        {
            if (CustomSettings(peerId)["local"] is not JsonObject local) return;
            var body = NewCustomSettings(false, TelefonProtocolContract.Integer(local["revision"]) + 1);
            SetCustomSettings(peerId, body, false);
            if (CustomSupported(peerId)) Enqueue(peerId, "personal_sync.custom_settings", body, 86_400_000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        }
    }

    internal bool CustomAllowed(string peerId, string kind, JsonObject body, bool outgoing)
    {
        lock (gate)
        {
            if (RestoreFenced || !CustomSupported(peerId)) return false;
            var settings = CustomSettings(peerId);
            if (kind == "personal_sync.custom_settings") return !outgoing || JsonNode.DeepEquals(body, settings["local"]);
            var personal = PersonalSettings(peerId);
            return PersonalSyncContract.CustomScopeAllowed(settings[outgoing ? "remote" : "local"] as JsonObject,
                settings[outgoing ? "local" : "remote"] as JsonObject, [4], [4], personal.OwnDevice, personal.RemoteOwnDevice,
                body["sender_epoch"]!.GetValue<string>(), body["receiver_epoch"]!.GetValue<string>(),
                TelefonProtocolContract.Integer(body["sender_revision"]), TelefonProtocolContract.Integer(body["receiver_revision"]));
        }
    }

    internal bool SendCustomIfAllowed(string peerId, JsonObject message, Action send)
    {
        lock (gate)
        {
            if (!CustomAllowed(peerId, message["kind"]!.GetValue<string>(), message["body"]!.AsObject(), true)) return false;
            send(); return true;
        }
    }

    internal bool HasPendingCustomSettings(string peerId)
    {
        using var db = OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT 1 FROM outbox WHERE peer_id=$peer AND kind='personal_sync.custom_settings' AND expires_ms>$now LIMIT 1";
        command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$now", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        return command.ExecuteScalar() is not null;
    }

    internal string BluetoothAddress(string peerId)
    {
        // Existing Settings choices override the original authenticated setup binding.
        if (LoadSettings()["bluetooth"]?[peerId] is JsonObject preference)
            return preference["enabled"]?.GetValue<bool>() == true ? preference["address"]?.GetValue<string>() ?? "" : "";
        return LoadPeers().FirstOrDefault(p => p.Id == peerId)?.BluetoothAddress ?? "";
    }

    internal void SetBluetoothAddress(string peerId, string address)
    {
        if (!TelefonBluetoothClient.ValidAddress(address))
            throw new InvalidDataException();
        lock (gate)
        {
            var peers = LoadPeers();
            if (!peers.Any(p => p.Id == peerId && p.State == "paired")) throw new InvalidDataException();
            SavePeers(peers.Select(p => p.Id == peerId ? p with { BluetoothAddress = address } : p));
        }
    }

    internal TelefonIdentity LoadOrCreateIdentity()
    {
        var text = files.Read(paths.TelefonIdentity, 64 * 1024);
        if (text is null)
        {
            var keys = TelefonCrypto.GenerateX25519();
            var freshName = KdeConnectIdentityStore.DeviceName;
            var freshIdentity = new TelefonIdentity(Guid.NewGuid().ToString("D"), freshName[..Math.Min(60, freshName.Length)], keys.Public, keys.Private.ToArray());
            SaveIdentity(freshIdentity); CryptographicOperations.ZeroMemory(keys.Private); return freshIdentity;
        }
        var value = JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("Die Telefonidentität ist beschädigt.");
        var id = value["device_id"]?.GetValue<string>() ?? "";
        var name = value["display_name"]?.GetValue<string>() ?? "";
        if (!Guid.TryParseExact(id, "D", out _) || value["role"]?.GetValue<string>() != "desktop" || name.Length is < 1 or > 60)
            throw new InvalidDataException("Die Telefonidentität ist beschädigt.");
        var publicKey = ReadBase64(value, "static_public", 32);
        if (!File.Exists(paths.TelefonIdentityKey))
        {
            if (LoadPeers().Count != 0) throw new InvalidDataException("Die Telefonidentität ist unvollständig.");
            File.Delete(paths.TelefonIdentity);
            return LoadOrCreateIdentity();
        }
        var privateKey = Open("identity", id, Convert.FromBase64String(files.Read(paths.TelefonIdentityKey, 4096) ?? ""));
        if (privateKey.Length != 32 || !TelefonCrypto.X25519Public(privateKey).SequenceEqual(publicKey))
            throw new InvalidDataException("Die Telefonidentität ist beschädigt.");
        var currentName = KdeConnectIdentityStore.DeviceName;
        currentName = currentName[..Math.Min(60, currentName.Length)];
        var loadedIdentity = new TelefonIdentity(id, currentName, publicKey, privateKey);
        if (!StringComparer.Ordinal.Equals(name, currentName)) SaveIdentity(loadedIdentity);
        return loadedIdentity;
    }

    internal IReadOnlyList<TelefonPeer> LoadPeers()
    {
        lock (gate)
        {
            var text = files.Read(paths.TelefonPeers, 4 * 1024 * 1024);
            if (text is null) return [];
            var envelope = JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("Die Telefon-Gegenstellenliste ist beschädigt.");
            var plain = Open("peers", "all", Convert.FromBase64String(envelope["blob"]?.GetValue<string>() ?? ""));
            var array = JsonNode.Parse(plain) as JsonArray ?? throw new InvalidDataException("Die Telefon-Gegenstellenliste ist beschädigt.");
            return array.OfType<JsonObject>().Select(ReadPeer).ToArray();
        }
    }

    internal void SavePeers(IEnumerable<TelefonPeer> peers)
    {
        lock (gate)
        {
            var array = new JsonArray(peers.Select(peer => (JsonNode)WritePeer(peer)).ToArray());
            files.Write(paths.TelefonPeers, new JsonObject
            {
                ["blob"] = Convert.ToBase64String(Seal("peers", "all", Encoding.UTF8.GetBytes(array.ToJsonString())))
            }.ToJsonString());
        }
    }

    internal void SavePending(TelefonPeer peer, byte[] transcript, byte[] phoneProof, byte[] desktopProof, long expiresMs)
    {
        if (transcript.Length != 32 || phoneProof.Length != 32 || desktopProof.Length != 32) throw new InvalidDataException();
        var pending = peer with { State = "pair_commit_pending", PendingTranscript = transcript.ToArray(),
            PendingPhoneProof = phoneProof.ToArray(), PendingDesktopProof = desktopProof.ToArray(), PendingExpiresMs = expiresMs };
        var existing = LoadPeers();
        if (existing.Any(value => value.Id != peer.Id)) throw new InvalidOperationException("binding_conflict");
        var peers = existing.Where(value => value.Id != peer.Id).Append(pending).ToArray();
        SavePeers(peers);
    }

    internal bool TryFinishPending(string peerId, byte[] transcript, byte[] phoneProof, long now, out TelefonPeer peer, out JsonObject finish)
    {
        lock (gate)
        {
            var peers = LoadPeers().ToList();
            var index = peers.FindIndex(value => value.Id == peerId);
            if (index < 0) { peer = null!; finish = null!; return false; }
            var pending = peers[index];
            if (pending.State is not ("pair_commit_pending" or "paired") || pending.PendingExpiresMs < now || pending.PendingTranscript is null ||
                pending.PendingPhoneProof is null || pending.PendingDesktopProof is null ||
                !CryptographicOperations.FixedTimeEquals(pending.PendingTranscript, transcript) ||
                !CryptographicOperations.FixedTimeEquals(pending.PendingPhoneProof, phoneProof))
            { peer = null!; finish = null!; return false; }
            // Retain the bounded completion receipt until its original deadline.
            peer = pending with { State = "paired", LastSeenMs = now };
            peers[index] = peer; SavePeers(peers);
            finish = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_finish", ["side"] = "desktop",
                ["transcript"] = Convert.ToBase64String(transcript), ["proof"] = Convert.ToBase64String(pending.PendingDesktopProof) };
            return true;
        }
    }

    internal bool TryFinishPending(byte[] transcript, byte[] phoneProof, long now, out TelefonPeer peer, out JsonObject finish)
    {
        var candidate = LoadPeers().SingleOrDefault(value => value.State is ("pair_commit_pending" or "paired") && value.PendingTranscript is not null &&
            value.PendingPhoneProof is not null && value.PendingExpiresMs >= now && CryptographicOperations.FixedTimeEquals(value.PendingTranscript, transcript) &&
            CryptographicOperations.FixedTimeEquals(value.PendingPhoneProof, phoneProof));
        if (candidate is null) { peer = null!; finish = null!; return false; }
        return TryFinishPending(candidate.Id, transcript, phoneProof, now, out peer, out finish);
    }

    internal void UpdatePeerProtocol(string peerId, long capabilityRevision, JsonObject? capabilities, long grantRevision, JsonObject? grants)
    {
        PurgeIdentifiers(peerId);
        var peers = LoadPeers().ToList(); var index = peers.FindIndex(value => value.Id == peerId);
        if (index < 0) throw new InvalidOperationException("Unbekannte Gegenstelle.");
        var old = peers[index];
        peers[index] = old with {
            CapabilityRevision = capabilities is null ? old.CapabilityRevision : capabilityRevision,
            Capabilities = capabilities?.DeepClone().AsObject() ?? old.Capabilities,
            GrantRevision = grants is null ? old.GrantRevision : grantRevision,
            Grants = grants?.DeepClone().AsObject() ?? old.Grants };
        SavePeers(peers);
    }

    internal JsonObject? LoadStatus(string peerId)
    {
        try
        {
            var root = JsonNode.Parse(files.Read(paths.TelefonStatusCache, 1024 * 1024) ?? "{}") as JsonObject;
            var item = root?[peerId] as JsonObject;
            if (item is null || DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - (item["cached_ms"]?.GetValue<long>() ?? 0) > 86_400_000) return null;
            return TelefonDeviceStatusContract.WithoutIdentifiers(item);
        }
        catch (Exception) { return null; }
    }

    internal void RemoveStatus(string peerId)
    {
        lock (gate)
        {
            PurgeIdentifiers(peerId);
            try
            {
                var root = JsonNode.Parse(files.Read(paths.TelefonStatusCache, 1024 * 1024) ?? "{}") as JsonObject ?? new JsonObject();
                if (root.Remove(peerId)) files.Write(paths.TelefonStatusCache, root.ToJsonString());
            }
            catch (Exception) { }
        }
    }

    internal void SaveStatus(string peerId, JsonObject status)
    {
        var root = JsonNode.Parse(files.Read(paths.TelefonStatusCache, 1024 * 1024) ?? "{}") as JsonObject ?? new JsonObject();
        var copy = TelefonDeviceStatusContract.WithoutIdentifiers(status); copy["cached_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); root[peerId] = copy;
        files.Write(paths.TelefonStatusCache, root.ToJsonString());
    }

    internal void PurgeIdentifiers(string peerId)
    {
        lock (gate) { identifierRequests.Remove(peerId); transientIdentifiers.Remove(peerId); }
    }

    internal bool IdentifiersAllowed(TelefonPeer peer)
    {
        if (RestoreFenced) return false;
        var peers = LoadPeers();
        var current = peers.Count == 1 ? peers.SingleOrDefault(p => p.Id == peer.Id && p.State == "paired") : null;
        var settings = PersonalSettings(peer.Id);
        return current is not null && current.PublicKey.SequenceEqual(peer.PublicKey) && settings.OwnDevice && settings.RemoteOwnDevice &&
            LocalGrants()["device_status"]?.GetValue<bool>() == true && current.Grants["device_status"]?.GetValue<bool>() == true &&
            current.Capabilities["device_status"]?["available"]?.GetValue<bool>() == true &&
            current.Capabilities["device_status"]?["versions"] is JsonArray versions && versions.Any(v => TelefonProtocolContract.Integer(v) == 4);
    }

    internal bool SendIdentifierRequest(TelefonPeer peer, JsonObject body, long now, Action send)
    {
        lock (gate)
        {
            TelefonDeviceStatusContract.ValidateRequest(body);
            PurgeIdentifiers(peer.Id);
            if (!IdentifiersAllowed(peer)) return false;
            identifierRequests[peer.Id] = (body["request_id"]!.GetValue<string>(), Convert.ToBase64String(peer.PublicKey), now + 60_000, body["include_identifiers"]!.GetValue<bool>(), Environment.TickCount64 + 60_000);
            try { send(); return true; } catch { PurgeIdentifiers(peer.Id); throw; }
        }
    }

    internal bool AcceptIdentifiers(TelefonPeer peer, JsonObject body, long now, long expires)
    {
        lock (gate)
        {
            TelefonDeviceStatusContract.ValidateReport(body);
            // Reject stale/duplicate replies without consuming a newer request or result.
            if (!identifierRequests.TryGetValue(peer.Id, out var request) ||
                request.Request != body["request_id"]!.GetValue<string>() || request.Key != Convert.ToBase64String(peer.PublicKey))
                return false;
            if (!IdentifiersAllowed(peer) ||
                request.Expires <= now || request.Deadline <= Environment.TickCount64 || expires <= now || !request.Include && body["identifiers"]!.AsObject().Any(p => p.Value!["status"]!.GetValue<string>() != "not_shared"))
            { PurgeIdentifiers(peer.Id); return false; }
            identifierRequests.Remove(peer.Id);
            transientIdentifiers[peer.Id] = (body["identifiers"]!.DeepClone().AsObject(), request.Request, request.Key,
                Math.Min(expires, now + 60_000), Environment.TickCount64 + Math.Min(60_000, expires - now));
            return true;
        }
    }

    internal JsonObject CurrentIdentifierStatus(TelefonPeer peer, JsonObject status)
    {
        lock (gate)
        {
            var clean = TelefonDeviceStatusContract.WithoutIdentifiers(status);
            if (!IdentifiersAllowed(peer) || !transientIdentifiers.TryGetValue(peer.Id, out var entry) ||
                entry.Request != status["request_id"]?.GetValue<string>() || entry.Key != Convert.ToBase64String(peer.PublicKey) ||
                entry.Expires <= DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() || entry.Deadline <= Environment.TickCount64)
                return clean;
            clean["identifiers"] = entry.Value.DeepClone();
            clean["identifiers_expires_ms"] = entry.Expires;
            clean["identifiers_peer_fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey);
            return clean;
        }
    }

    internal void RemovePeer(string peerId)
    {
        lock (gate)
        {
            // Revoke authorization before modifying recoverable pairing/settings files.
            using (var db = OpenDatabase())
            {
                db.Open(); using var revoke = db.CreateCommand(); revoke.CommandText = "DELETE FROM meta WHERE key=$key";
                revoke.Parameters.AddWithValue("$key", "personal_custom:" + peerId + ":consent"); revoke.ExecuteNonQuery();
            }
            SavePeers(LoadPeers().Where(peer => peer.Id != peerId));
            RemoveStatus(peerId);
            var settings = LoadSettings(); if (settings["personal_sync"] is JsonObject personal) { personal.Remove(peerId); SaveSettings(settings); }
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            foreach (var table in new[] { "outbox", "inbox", "dedupe", "command_effect", "personal_batch", "personal_domain", "personal_attachment_chunk", "personal_attachment_transfer" })
            { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = $"DELETE FROM {table} WHERE peer_id=$id"; command.Parameters.AddWithValue("$id", peerId); command.ExecuteNonQuery(); }
            using (var meta = connection.CreateCommand()) { meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key LIKE $prefix OR key=$active OR key=$status OR key LIKE $request"; meta.Parameters.AddWithValue("$prefix", "personal_%:" + peerId + ":%"); meta.Parameters.AddWithValue("$active", "personal_active_auto:" + peerId); meta.Parameters.AddWithValue("$status", "device_status:" + peerId); meta.Parameters.AddWithValue("$request", "status_request:" + peerId + ":%"); meta.ExecuteNonQuery(); }
            transaction.Commit();
        }
    }

    internal string Enqueue(string peerId, string kind, JsonObject body, long ttlMs, long now, string transportPolicy = "any")
    {
        if (kind.StartsWith("device_status.", StringComparison.Ordinal) && (body.ContainsKey("identifiers") || TelefonProtocolContract.TryInteger(body["version"], out var statusVersion) && statusVersion == 4))
            throw new InvalidDataException("Device identifiers cannot enter a persistent queue.");
        if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        if (ttlMs <= 0 || ttlMs > MaximumMessageTtlMs) throw new InvalidDataException("Ungültige Nachrichtenlebensdauer.");
        if (transportPolicy is not ("any" or "wifi_only")) throw new InvalidDataException("Ungültige Transportpolicy.");
        var id = Guid.NewGuid().ToString("D"); var expires = checked(now + ttlMs);
        var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = id, ["kind"] = kind,
            ["created_ms"] = now, ["expires_ms"] = expires, ["body"] = body.DeepClone() };
        TelefonMessageContract.ValidateMessage(message, now, false);
        var payload = Seal("outbox", id, TelefonCrypto.Canonical(message));
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            if (kind == "personal_sync.custom_settings")
            {
                using var replace = connection.CreateCommand(); replace.Transaction = transaction;
                replace.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND kind='personal_sync.custom_settings'";
                replace.Parameters.AddWithValue("$peer", peerId); replace.ExecuteNonQuery();
            }
            using (var size = connection.CreateCommand())
            { size.Transaction = transaction; size.CommandText = "SELECT COALESCE(SUM(length(payload)),0) FROM outbox"; if ((long)(size.ExecuteScalar() ?? 0L) + payload.Length > OutboxLimitBytes) throw new InvalidOperationException("queue_full"); }
            using var command = connection.CreateCommand(); command.Transaction = transaction;
            command.CommandText = "INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES($id,$peer,$kind,$created,$expires,$payload,0,$now,'',$policy)";
            command.Parameters.AddWithValue("$id", id); command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$kind", kind);
            command.Parameters.AddWithValue("$created", now); command.Parameters.AddWithValue("$expires", expires); command.Parameters.AddWithValue("$payload", payload); command.Parameters.AddWithValue("$now", now); command.Parameters.AddWithValue("$policy", transportPolicy);
            command.ExecuteNonQuery(); transaction.Commit();
        }
        return id;
    }

    internal IReadOnlyList<TelefonQueuedMessage> Due(string peerId, long now, int maximum = 32, string transport = "wifi")
    {
        if (RestoreFenced) return [];
        var result = new List<TelefonQueuedMessage>();
        lock (gate)
        {
            if (RestoreFenced) return [];
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction(); using var command = connection.CreateCommand();
            if (transport is not ("wifi" or "bluetooth")) throw new ArgumentOutOfRangeException(nameof(transport));
            command.Transaction = transaction; command.CommandText = "SELECT message_id,kind,payload,attempts,transport_policy FROM outbox WHERE peer_id=$peer AND expires_ms>=$now AND next_attempt_ms<=$now AND (transport_policy='any' OR $transport='wifi') ORDER BY CASE WHEN kind='personal_sync.custom_settings' THEN 0 ELSE 1 END,created_ms";
            command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$now", now); command.Parameters.AddWithValue("$transport", transport);
            var queued = new List<(string Id, string Kind, byte[] Payload, int Attempts, string Policy)>();
            using (var reader = command.ExecuteReader()) while (reader.Read()) queued.Add((reader.GetString(0), reader.GetString(1), (byte[])reader[2], reader.GetInt32(3), reader.GetString(4)));
            var limit = Math.Clamp(maximum, 1, 32); var purgedRuns = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in queued)
            {
                if (result.Count == limit) break;
                JsonObject message;
                try { message = JsonNode.Parse(Open("outbox", item.Id, item.Payload))!.AsObject(); }
                catch (Exception) when (TelefonProtocolContract.PersonalKinds.Contains(item.Kind)) { DeleteOutbox(connection, transaction, peerId, item.Id); continue; }
                if (item.Kind != "personal_sync.settings" && TelefonProtocolContract.PersonalKinds.Contains(item.Kind) &&
                    message["body"]?["run_id"]?.GetValue<string>() is string runId &&
                    (purgedRuns.Contains(runId) || PersonalRunUnavailable(connection, transaction, peerId, runId, now)))
                {
                    if (purgedRuns.Add(runId)) PurgePersonalRun(connection, transaction, peerId, runId);
                    continue;
                }
                result.Add(new TelefonQueuedMessage(item.Id, message, item.Attempts, item.Policy));
            }
            transaction.Commit();
        }
        return result;
    }

    internal void MarkAttempt(string messageId, int previousAttempts, long now, string error = "")
    {
        var attempts = previousAttempts + 1;
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "UPDATE outbox SET attempts=$attempts,next_attempt_ms=CASE WHEN kind IN ('dial_request.command','answer_call.command','end_call.command') THEN expires_ms ELSE $next END,last_error=$error WHERE message_id=$id";
        command.Parameters.AddWithValue("$attempts", attempts); command.Parameters.AddWithValue("$next", checked(now + RetryDelayMs(attempts))); command.Parameters.AddWithValue("$error", error.Length == 0 ? "missing_ack" : error); command.Parameters.AddWithValue("$id", messageId); command.ExecuteNonQuery();
    }

    internal bool CompleteOutbox(string peerId, string messageId)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id"; command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$id", messageId); return command.ExecuteNonQuery() == 1;
    }

    internal bool RetryOutbox(string peerId, string messageId, long now, string error)
    {
        using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        int attempts;
        using (var read = connection.CreateCommand())
        {
            read.Transaction = transaction;
            read.CommandText = "SELECT attempts FROM outbox WHERE peer_id=$peer AND message_id=$id";
            read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$id", messageId);
            var value = read.ExecuteScalar(); if (value is null) return false; attempts = Convert.ToInt32(value);
        }
        using (var update = connection.CreateCommand())
        {
            update.Transaction = transaction;
            update.CommandText = "UPDATE outbox SET attempts=$attempts,next_attempt_ms=$next,last_error=$error WHERE peer_id=$peer AND message_id=$id";
            update.Parameters.AddWithValue("$attempts", attempts);
            update.Parameters.AddWithValue("$next", checked(now + RetryDelayMs(attempts)));
            update.Parameters.AddWithValue("$error", error); update.Parameters.AddWithValue("$peer", peerId);
            update.Parameters.AddWithValue("$id", messageId);
            if (update.ExecuteNonQuery() != 1) return false;
        }
        transaction.Commit(); return true;
    }

    internal bool CompletePersonalOutbox(string peerId, string messageId, long now)
    {
        lock (gate)
        {
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            string? kind; byte[]? payload;
            using (var read = connection.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT kind,payload FROM outbox WHERE peer_id=$peer AND message_id=$id";
                read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$id", messageId); using var reader = read.ExecuteReader();
                if (!reader.Read()) return false; kind = reader.GetString(0); payload = (byte[])reader[1];
            }
            if (!TelefonProtocolContract.PersonalKinds.Contains(kind)) return false;
            string? runId = null;
            try { runId = (JsonNode.Parse(Open("outbox", messageId, payload)) as JsonObject)?["body"]?["run_id"]?.GetValue<string>(); }
            catch (Exception) { }
            if (kind != "personal_sync.settings" && runId is not null && PersonalRunUnavailable(connection, transaction, peerId, runId, now))
                PurgePersonalRun(connection, transaction, peerId, runId);
            else
                DeleteOutbox(connection, transaction, peerId, messageId);
            transaction.Commit(); return true;
        }
    }

    internal bool AcknowledgePersonalOutbox(string peerId, string messageId, string status, string error, long now)
    {
        if (status == "rejected" && error == "temporary_failure") return OutboxMessage(peerId, messageId) is not null;
        return CompletePersonalOutbox(peerId, messageId, now);
    }

    internal void RememberCommand(string peerId, string clientRef, long now)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "INSERT INTO command_effect(client_ref,state,first_seen_ms,peer_id) VALUES($id,'queued',$now,$peer)";
        command.Parameters.AddWithValue("$id", clientRef); command.Parameters.AddWithValue("$now", now); command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery();
    }

    internal bool HasCommand(string peerId, string clientRef)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM command_effect WHERE peer_id=$peer AND client_ref=$id"; command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$id", clientRef);
        return command.ExecuteScalar() is not null;
    }

    internal bool UpdateCommand(string peerId, string clientRef, string state)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "UPDATE command_effect SET state=$state WHERE peer_id=$peer AND client_ref=$id";
        command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$id", clientRef); command.Parameters.AddWithValue("$state", state); return command.ExecuteNonQuery() == 1;
    }

    internal long NextOwnRevision(string name)
    {
        if (name is not ("capabilities" or "grants")) throw new ArgumentOutOfRangeException(nameof(name));
        lock (gate)
        {
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            long current;
            using (var read = connection.CreateCommand())
            { read.Transaction = transaction; read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", "own_revision_" + name); var value = read.ExecuteScalar(); current = value is byte[] bytes ? long.Parse(Encoding.ASCII.GetString(Open("meta", name, bytes)), System.Globalization.CultureInfo.InvariantCulture) : 0; }
            var next = checked(current + 1); var blob = Seal("meta", name, Encoding.ASCII.GetBytes(next.ToString(System.Globalization.CultureInfo.InvariantCulture)));
            using (var write = connection.CreateCommand())
            { write.Transaction = transaction; write.CommandText = "INSERT INTO meta(key,value) VALUES($key,$value) ON CONFLICT(key) DO UPDATE SET value=excluded.value"; write.Parameters.AddWithValue("$key", "own_revision_" + name); write.Parameters.AddWithValue("$value", blob); write.ExecuteNonQuery(); }
            transaction.Commit(); return next;
        }
    }

    internal TelefonAck CommitIncoming(string peerId, JsonObject message, long now, Func<string, JsonObject, string?> authorize,
        bool deferAcceptance = false, bool reauthorizeDuplicates = false)
    {
        if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        string id;
        try { TelefonMessageContract.ValidateMessage(message, now, true); id = message["message_id"]!.GetValue<string>(); }
        catch (TelefonMessageException error)
        {
            if (!TelefonProtocolContract.IsUuidV4(error.MessageId)) throw;
            return CommitRejection(peerId, error.MessageId, error.Error, now);
        }
        var kind = message["kind"]!.GetValue<string>(); var body = message["body"]!.AsObject();
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            using (var duplicate = connection.CreateCommand())
            {
                duplicate.Transaction = transaction; duplicate.CommandText = "SELECT result,error FROM dedupe WHERE peer_id=$peer AND message_id=$id";
                duplicate.Parameters.AddWithValue("$peer", peerId); duplicate.Parameters.AddWithValue("$id", id);
                using var reader = duplicate.ExecuteReader(); if (reader.Read())
                {
                    var prior = reader.GetString(0); var priorError = reader.GetString(1); reader.Close();
                    if (reauthorizeDuplicates && prior is ("accepted" or "pending") && authorize(kind, body) is { } currentRejection)
                        return new TelefonAck(id, "rejected", currentRejection);
                    var process = false;
                    if (prior is "accepted" or "pending")
                    { using var state = connection.CreateCommand(); state.Transaction = transaction; state.CommandText = "SELECT state FROM inbox WHERE peer_id=$peer AND message_id=$id"; state.Parameters.AddWithValue("$peer", peerId); state.Parameters.AddWithValue("$id", id); process = (string?)state.ExecuteScalar() == "accepted"; }
                    return new TelefonAck(id, prior == "rejected" ? "rejected" : prior == "accepted" ? "duplicate" : "accepted", priorError, process);
                }
            }
            var rejection = authorize(kind, body);
            var status = rejection is null ? (deferAcceptance ? "pending" : "accepted") : "rejected"; var error = rejection ?? "none";
            if (rejection is null)
            {
                var stored = message.DeepClone().AsObject();
                if (kind == "device_status.report") stored["body"] = TelefonDeviceStatusContract.WithoutIdentifiers(body);
                var payload = Seal("inbox", peerId + id, TelefonCrypto.Canonical(stored));
                using var inbox = connection.CreateCommand(); inbox.Transaction = transaction;
                inbox.CommandText = "INSERT INTO inbox VALUES($id,$peer,$kind,$now,$expires,$payload,'accepted')";
                inbox.Parameters.AddWithValue("$id", id); inbox.Parameters.AddWithValue("$peer", peerId); inbox.Parameters.AddWithValue("$kind", kind); inbox.Parameters.AddWithValue("$now", now);
                inbox.Parameters.AddWithValue("$expires", TelefonProtocolContract.Integer(message["expires_ms"])); inbox.Parameters.AddWithValue("$payload", payload); inbox.ExecuteNonQuery();
            }
            using (var dedupe = connection.CreateCommand())
            { dedupe.Transaction = transaction; dedupe.CommandText = "INSERT INTO dedupe VALUES($id,$peer,$result,$error,$now)"; dedupe.Parameters.AddWithValue("$id", id); dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$result", status); dedupe.Parameters.AddWithValue("$error", error); dedupe.Parameters.AddWithValue("$now", now); dedupe.ExecuteNonQuery(); }
            transaction.Commit(); return new TelefonAck(id, status == "pending" ? "accepted" : status, error, rejection is null);
        }
    }

    internal void MarkIncomingProcessed(string peerId, string messageId, long? now = null)
    {
        using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        using (var command = connection.CreateCommand())
        {
            command.Transaction = transaction; command.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$id AND state='accepted'";
            command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$id", messageId); command.ExecuteNonQuery();
        }
        using (var dedupe = connection.CreateCommand())
        {
            dedupe.Transaction = transaction; dedupe.CommandText = "UPDATE dedupe SET result='accepted',error='none',seen_ms=$now WHERE peer_id=$peer AND message_id=$id";
            dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$id", messageId);
            dedupe.Parameters.AddWithValue("$now", now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); dedupe.ExecuteNonQuery();
        }
        transaction.Commit();
    }

    internal void MarkIncomingRejected(string peerId, string messageId, string error, long now)
    {
        using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        using (var inbox = connection.CreateCommand()) { inbox.Transaction = transaction; inbox.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$id"; inbox.Parameters.AddWithValue("$peer", peerId); inbox.Parameters.AddWithValue("$id", messageId); inbox.ExecuteNonQuery(); }
        using (var dedupe = connection.CreateCommand()) { dedupe.Transaction = transaction; dedupe.CommandText = "UPDATE dedupe SET result='rejected',error=$error,seen_ms=$now WHERE peer_id=$peer AND message_id=$id"; dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$id", messageId); dedupe.Parameters.AddWithValue("$error", error); dedupe.Parameters.AddWithValue("$now", now); dedupe.ExecuteNonQuery(); }
        transaction.Commit();
    }

    internal JsonArray LoadRecent(string peerId, string kind, int maximum = 100)
    {
        var result = new JsonArray();
        lock (gate)
        {
            using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "SELECT message_id,payload FROM inbox WHERE peer_id=$peer AND kind=$kind AND state='processed' ORDER BY received_ms DESC LIMIT $limit";
            command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$kind", kind); command.Parameters.AddWithValue("$limit", Math.Clamp(maximum, 1, 100));
            using var reader = command.ExecuteReader(); while (reader.Read())
            { var id = reader.GetString(0); var message = JsonNode.Parse(Open("inbox", peerId + id, (byte[])reader[1]))!.AsObject(); result.Add(message["body"]!.DeepClone()); }
        }
        return result;
    }

    internal void RememberStatusRequest(string peerId, string requestId, long expiresMs)
    {
        var key = "status_request:" + peerId + ":" + requestId; var value = Seal("meta", key, Encoding.ASCII.GetBytes(expiresMs.ToString(System.Globalization.CultureInfo.InvariantCulture)));
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "INSERT INTO meta(key,value) VALUES($key,$value) ON CONFLICT(key) DO UPDATE SET value=excluded.value";
        command.Parameters.AddWithValue("$key", key); command.Parameters.AddWithValue("$value", value); command.ExecuteNonQuery();
    }

    internal bool HasStatusRequest(string peerId, string requestId, long now)
    {
        var key = "status_request:" + peerId + ":" + requestId; using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM meta WHERE key=$key"; command.Parameters.AddWithValue("$key", key); var value = command.ExecuteScalar();
        return value is byte[] bytes && long.Parse(Encoding.ASCII.GetString(Open("meta", key, bytes)), System.Globalization.CultureInfo.InvariantCulture) >= now;
    }

    internal void CompleteStatusRequest(string peerId, string requestId)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "DELETE FROM meta WHERE key=$key"; command.Parameters.AddWithValue("$key", "status_request:" + peerId + ":" + requestId); command.ExecuteNonQuery();
    }

    internal void Cleanup(long now)
    {
        lock (gate)
        {
            foreach (var id in identifierRequests.Where(p => p.Value.Expires <= now || p.Value.Deadline <= Environment.TickCount64).Select(p => p.Key).ToArray()) identifierRequests.Remove(id);
            foreach (var id in transientIdentifiers.Where(p => p.Value.Expires <= now || p.Value.Deadline <= Environment.TickCount64).Select(p => p.Key).ToArray()) transientIdentifiers.Remove(id);
            var peers = LoadPeers(); var retained = peers.Where(peer => peer.State != "pair_commit_pending" || peer.PendingExpiresMs >= now)
                .Select(peer => peer.State == "paired" && peer.PendingTranscript is not null && peer.PendingExpiresMs < now
                    ? peer with { PendingTranscript = null, PendingPhoneProof = null, PendingDesktopProof = null, PendingExpiresMs = 0 } : peer).ToArray();
            if (!retained.SequenceEqual(peers)) SavePeers(retained);
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            Execute(connection, transaction, "DELETE FROM outbox WHERE expires_ms<$now", now);
            Execute(connection, transaction, "DELETE FROM inbox WHERE expires_ms<$now OR received_ms<$now-2592000000 OR rowid IN (SELECT rowid FROM inbox ORDER BY received_ms DESC LIMIT -1 OFFSET 10000)", now);
            Execute(connection, transaction, "DELETE FROM dedupe WHERE seen_ms<$now-7776000000 OR rowid IN (SELECT rowid FROM dedupe ORDER BY seen_ms DESC LIMIT -1 OFFSET 100000)", now);
            Execute(connection, transaction, "DELETE FROM command_effect WHERE first_seen_ms<$now-7776000000", now);
            Execute(connection, transaction, "DELETE FROM personal_batch WHERE expires_ms<=$now OR received_ms<$now-86400000", now);
            Execute(connection, transaction, "DELETE FROM personal_domain WHERE expires_ms<=$now OR received_ms<$now-86400000", now);
            Execute(connection, transaction, "DELETE FROM personal_attachment_chunk WHERE NOT EXISTS (SELECT 1 FROM personal_attachment_transfer t WHERE t.peer_id=personal_attachment_chunk.peer_id AND t.run_id=personal_attachment_chunk.run_id AND t.reply=personal_attachment_chunk.reply AND t.records_hash=personal_attachment_chunk.records_hash AND t.sha256=personal_attachment_chunk.sha256 AND t.direction=personal_attachment_chunk.direction) OR EXISTS (SELECT 1 FROM personal_attachment_transfer t WHERE t.peer_id=personal_attachment_chunk.peer_id AND t.run_id=personal_attachment_chunk.run_id AND t.reply=personal_attachment_chunk.reply AND t.records_hash=personal_attachment_chunk.records_hash AND t.sha256=personal_attachment_chunk.sha256 AND t.direction=personal_attachment_chunk.direction AND t.expires_ms<=$now)", now);
            Execute(connection, transaction, "DELETE FROM personal_attachment_transfer WHERE expires_ms<=$now OR NOT EXISTS (SELECT 1 FROM meta WHERE key='personal_run:'||personal_attachment_transfer.peer_id||':'||personal_attachment_transfer.run_id)", now);
            Execute(connection, transaction, "DELETE FROM personal_batch WHERE NOT EXISTS (SELECT 1 FROM meta WHERE key='personal_run:'||personal_batch.peer_id||':'||personal_batch.run_id)", now);
            transaction.Commit();
        }
    }

    internal JsonObject? OutboxMessage(string peerId, string messageId)
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT payload FROM outbox WHERE peer_id=$peer AND message_id=$id";
        command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$id", messageId);
        return command.ExecuteScalar() is byte[] payload ? JsonNode.Parse(Open("outbox", messageId, payload)) as JsonObject : null;
    }

    private bool PersonalRunUnavailable(SqliteConnection connection, SqliteTransaction transaction, string peerId, string runId, long now)
    {
        var key = $"personal_run:{peerId}:{runId}"; byte[]? payload;
        using (var read = connection.CreateCommand()) { read.Transaction = transaction; read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key); payload = read.ExecuteScalar() as byte[]; }
        if (payload is null) return true;
        try
        {
            var value = JsonNode.Parse(Open("personal_run", key, payload))!.AsObject();
            return value["body"]?["run_id"]?.GetValue<string>() != runId || TelefonProtocolContract.Integer(value["expires_ms"]) <= now;
        }
        catch (Exception) { return true; }
    }

    private void PurgePersonalRun(SqliteConnection connection, SqliteTransaction transaction, string peerId, string runId)
    {
        var remove = new List<string>(); using (var read = connection.CreateCommand())
        {
            read.Transaction = transaction; read.CommandText = "SELECT message_id,payload FROM outbox WHERE peer_id=$peer AND kind LIKE 'personal_sync.%'"; read.Parameters.AddWithValue("$peer", peerId);
            using var reader = read.ExecuteReader(); while (reader.Read())
            {
                var id = reader.GetString(0);
                try { if ((JsonNode.Parse(Open("outbox", id, (byte[])reader[1])) as JsonObject)?["body"]?["run_id"]?.GetValue<string>() == runId) remove.Add(id); }
                catch (Exception) { }
            }
        }
        foreach (var id in remove) DeleteOutbox(connection, transaction, peerId, id);
        foreach (var table in new[] { "personal_batch", "personal_attachment_chunk", "personal_attachment_transfer" })
        {
            using var delete = connection.CreateCommand(); delete.Transaction = transaction; delete.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer AND run_id=$run";
            delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$run", runId); delete.ExecuteNonQuery();
        }
        var domains = new List<string>(); using (var read = connection.CreateCommand())
        {
            read.Transaction = transaction; read.CommandText = "SELECT message_id,payload FROM personal_domain WHERE peer_id=$peer"; read.Parameters.AddWithValue("$peer", peerId);
            using var reader = read.ExecuteReader(); while (reader.Read())
            {
                var id = reader.GetString(0);
                try { if ((JsonNode.Parse(Open("personal_domain", id, (byte[])reader[1])) as JsonObject)?["body"]?["run_id"]?.GetValue<string>() == runId) domains.Add(id); }
                catch (Exception) { }
            }
        }
        foreach (var id in domains)
        {
            using var delete = connection.CreateCommand(); delete.Transaction = transaction; delete.CommandText = "DELETE FROM personal_domain WHERE peer_id=$peer AND message_id=$id";
            delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$id", id); delete.ExecuteNonQuery();
        }
        using var meta = connection.CreateCommand(); meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key=$run OR key LIKE $report OR key LIKE $applied";
        meta.Parameters.AddWithValue("$run", $"personal_run:{peerId}:{runId}"); meta.Parameters.AddWithValue("$report", $"personal_report:{peerId}:{runId}%"); meta.Parameters.AddWithValue("$applied", $"personal_applied:{peerId}:{runId}%"); meta.ExecuteNonQuery();
    }

    private static void DeleteOutbox(SqliteConnection connection, SqliteTransaction transaction, string peerId, string messageId)
    {
        using var delete = connection.CreateCommand(); delete.Transaction = transaction; delete.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id";
        delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$id", messageId); delete.ExecuteNonQuery();
    }

    internal static long RetryDelayMs(int attempt) => attempt switch
    { 1 => 1_000, 2 => 2_000, 3 => 5_000, 4 => 10_000, 5 => 30_000, 6 => 60_000, _ => RandomNumberGenerator.GetInt32(240_000, 360_001) };

    private TelefonAck CommitRejection(string peerId, string messageId, string error, long now)
    {
        lock (gate)
        {
            using var connection = OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            using (var read = connection.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT result,error FROM dedupe WHERE peer_id=$peer AND message_id=$id";
                read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$id", messageId); using var reader = read.ExecuteReader();
                if (reader.Read()) return new TelefonAck(messageId, reader.GetString(0) == "rejected" ? "rejected" : "duplicate", reader.GetString(1));
            }
            using (var write = connection.CreateCommand())
            { write.Transaction = transaction; write.CommandText = "INSERT INTO dedupe VALUES($id,$peer,'rejected',$error,$now)"; write.Parameters.AddWithValue("$id", messageId); write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$error", error); write.Parameters.AddWithValue("$now", now); write.ExecuteNonQuery(); }
            transaction.Commit(); return new TelefonAck(messageId, "rejected", error);
        }
    }

    private void SaveIdentity(TelefonIdentity identity)
    {
        files.Write(paths.TelefonIdentity, new JsonObject { ["storage_version"] = 1, ["device_id"] = identity.Id,
            ["role"] = "desktop", ["display_name"] = identity.Name, ["static_public"] = Convert.ToBase64String(identity.PublicKey) }.ToJsonString());
        files.Write(paths.TelefonIdentityKey, Convert.ToBase64String(Seal("identity", identity.Id, identity.PrivateKey)));
    }

    private JsonObject LoadSettings()
    {
        try { return JsonNode.Parse(files.ReadRecoverableJson(paths.TelefonSettings, 16 * 1024) ?? "{}") as JsonObject
                ?? throw new InvalidDataException("Die Telefoneinstellungen sind beschädigt."); }
        catch (Exception error) when (error is JsonException or IOException or UnauthorizedAccessException)
        { throw new InvalidDataException("Die Telefoneinstellungen sind beschädigt.", error); }
    }

    private void SaveSettings(JsonObject settings) => files.WriteRecoverableJson(paths.TelefonSettings, settings.ToJsonString());

    private byte[] LoadStorageKey()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("DPAPI ist nur unter Windows verfügbar.");
        var text = files.Read(paths.TelefonStorageKey, 4096);
        if (text is not null) return ProtectedData.Unprotect(Convert.FromBase64String(text), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser);
        var key = RandomNumberGenerator.GetBytes(32);
        files.Write(paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(key, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
        return key;
    }

    internal byte[] Seal(string type, string id, byte[] plain)
    {
        var nonce = RandomNumberGenerator.GetBytes(12); var cipher = new byte[plain.Length]; var tag = new byte[16];
        using (var aes = new AesGcm(storageKey, 16)) aes.Encrypt(nonce, plain, cipher, tag, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1\0" + type + id));
        return nonce.Concat(cipher).Concat(tag).ToArray();
    }

    internal byte[] Open(string type, string id, byte[] blob)
    {
        if (blob.Length < 28) throw new CryptographicException("Die Telefonablage ist beschädigt.");
        var plain = new byte[blob.Length - 28];
        using (var aes = new AesGcm(storageKey, 16)) aes.Decrypt(blob.AsSpan(0, 12), blob.AsSpan(12, plain.Length), blob.AsSpan(blob.Length - 16), plain, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1\0" + type + id));
        return plain;
    }

    private static TelefonPeer ReadPeer(JsonObject value)
    {
        var state = value["state"]?.GetValue<string>() ?? ""; if (state is not ("paired" or "pair_commit_pending")) throw new InvalidDataException("Ungültiger Pairingzustand.");
        var grants = MigrateGrants(value["grants"] as JsonObject); TelefonProtocolContract.ValidateGrants(new JsonObject { ["revision"] = Math.Max(1, value["grant_revision"]?.GetValue<long>() ?? 0), ["grants"] = grants.DeepClone() });
        var capabilities = MigrateCapabilities(value["capabilities"] as JsonObject);
        var bluetoothAddress = value["bluetooth_address"]?.GetValue<string>() ?? "";
        if (bluetoothAddress.Length > 0 && !TelefonBluetoothClient.ValidAddress(bluetoothAddress)) throw new InvalidDataException();
        return new TelefonPeer(value["device_id"]!.GetValue<string>(), value["display_name"]!.GetValue<string>(), ReadBase64(value, "static_public", 32), state,
            value["last_seen_ms"]?.GetValue<long>() ?? 0, value["capability_revision"]?.GetValue<long>() ?? 0, capabilities.DeepClone().AsObject(),
            value["grant_revision"]?.GetValue<long>() ?? 0, grants.DeepClone().AsObject(), OptionalBase64(value, "pending_transcript"), OptionalBase64(value, "pending_phone_proof"),
            OptionalBase64(value, "pending_desktop_proof"), value["pending_expires_ms"]?.GetValue<long>() ?? 0, bluetoothAddress);
    }

    private static JsonObject WritePeer(TelefonPeer peer) => new()
    {
        ["device_id"] = peer.Id, ["display_name"] = peer.Name, ["static_public"] = Convert.ToBase64String(peer.PublicKey), ["state"] = peer.State,
        ["last_seen_ms"] = peer.LastSeenMs, ["capability_revision"] = peer.CapabilityRevision, ["capabilities"] = peer.Capabilities.DeepClone(),
        ["grant_revision"] = peer.GrantRevision, ["grants"] = peer.Grants.DeepClone(),
        ["pending_transcript"] = peer.PendingTranscript is null ? null : Convert.ToBase64String(peer.PendingTranscript),
        ["pending_phone_proof"] = peer.PendingPhoneProof is null ? null : Convert.ToBase64String(peer.PendingPhoneProof),
        ["pending_desktop_proof"] = peer.PendingDesktopProof is null ? null : Convert.ToBase64String(peer.PendingDesktopProof), ["pending_expires_ms"] = peer.PendingExpiresMs,
        ["bluetooth_address"] = peer.BluetoothAddress
    };

    private static JsonObject MigrateGrants(JsonObject? stored)
    {
        var result = new JsonObject(); var source = stored ?? new JsonObject();
        var known = TelefonProtocolContract.GrantNames.Concat(new[] { "sms_send", "sms_received", "call_control" }).ToHashSet(StringComparer.Ordinal);
        if (source.Any(item => !known.Contains(item.Key))) throw new InvalidDataException("Unbekannter gespeicherter Grant.");
        foreach (var name in TelefonProtocolContract.GrantNames) result[name] = source[name]?.DeepClone() ?? JsonValue.Create(name == "device_status");
        return result;
    }

    private static JsonObject MigrateCapabilities(JsonObject? stored)
    {
        if (stored is null || stored.Count == 0) return new JsonObject();
        var known = TelefonProtocolContract.CapabilityNames.Concat(new[] { "sms_send", "sms_received", "call_control" }).ToHashSet(StringComparer.Ordinal);
        if (stored.Any(item => !known.Contains(item.Key))) throw new InvalidDataException("Unbekannte gespeicherte Capability.");
        var result = new JsonObject();
        foreach (var name in TelefonProtocolContract.CapabilityNames)
            result[name] = stored[name]?.DeepClone() ?? new JsonObject { ["available"] = false, ["reason"] = "not_implemented", ["versions"] = new JsonArray(name == "incoming_call_state" ? 2 : 1) };
        return result;
    }

    private void InitializeDatabase()
    {
        using var connection = OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS outbox(message_id TEXT PRIMARY KEY,peer_id TEXT NOT NULL,kind TEXT NOT NULL,created_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,attempts INTEGER NOT NULL,next_attempt_ms INTEGER NOT NULL,last_error TEXT NOT NULL,transport_policy TEXT NOT NULL DEFAULT 'any'); CREATE INDEX IF NOT EXISTS outbox_due ON outbox(peer_id,next_attempt_ms); CREATE TABLE IF NOT EXISTS inbox(message_id TEXT NOT NULL,peer_id TEXT NOT NULL,kind TEXT NOT NULL,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,state TEXT NOT NULL,PRIMARY KEY(peer_id,message_id)); CREATE TABLE IF NOT EXISTS dedupe(message_id TEXT NOT NULL,peer_id TEXT NOT NULL,result TEXT NOT NULL,error TEXT NOT NULL,seen_ms INTEGER NOT NULL,PRIMARY KEY(peer_id,message_id)); CREATE TABLE IF NOT EXISTS command_effect(client_ref TEXT PRIMARY KEY,state TEXT NOT NULL,first_seen_ms INTEGER NOT NULL,peer_id TEXT NOT NULL DEFAULT ''); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS personal_batch(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,sequence INTEGER NOT NULL,batch_id TEXT NOT NULL UNIQUE,message_id TEXT NOT NULL UNIQUE,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,last INTEGER NOT NULL,commit_token TEXT NOT NULL,PRIMARY KEY(peer_id,run_id,reply,sequence)); CREATE TABLE IF NOT EXISTS personal_domain(peer_id TEXT NOT NULL,message_id TEXT NOT NULL,kind TEXT NOT NULL,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,commit_token TEXT NOT NULL,PRIMARY KEY(peer_id,message_id)); CREATE TABLE IF NOT EXISTS personal_attachment_transfer(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,size INTEGER NOT NULL,mime TEXT NOT NULL,transport_policy TEXT NOT NULL,expires_ms INTEGER NOT NULL,complete INTEGER NOT NULL DEFAULT 0,metadata BLOB NOT NULL,PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction)); CREATE TABLE IF NOT EXISTS personal_attachment_chunk(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,chunk_index INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction,chunk_index));";
        command.ExecuteNonQuery();
        using var columns = connection.CreateCommand(); columns.CommandText = "PRAGMA table_info(outbox)"; using var reader = columns.ExecuteReader(); var names = new HashSet<string>(StringComparer.Ordinal); while (reader.Read()) names.Add(reader.GetString(1)); reader.Close();
        if (!names.Contains("transport_policy")) { using var alter = connection.CreateCommand(); alter.CommandText = "ALTER TABLE outbox ADD COLUMN transport_policy TEXT NOT NULL DEFAULT 'any'"; alter.ExecuteNonQuery(); }
        using var legacy = connection.CreateCommand(); legacy.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sms_effect'";
        if (legacy.ExecuteScalar() is not null) { using var migrate = connection.CreateCommand(); migrate.CommandText = "INSERT OR IGNORE INTO command_effect(client_ref,state,first_seen_ms) SELECT client_ref,state,first_seen_ms FROM sms_effect; DROP TABLE sms_effect"; migrate.ExecuteNonQuery(); }
    }

    internal SqliteConnection OpenDatabase() => new(new SqliteConnectionStringBuilder { DataSource = paths.TelefonDatabase, Mode = SqliteOpenMode.ReadWriteCreate }.ToString());
    private static void Execute(SqliteConnection connection, SqliteTransaction transaction, string sql, long now)
    { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; command.Parameters.AddWithValue("$now", now); command.ExecuteNonQuery(); }
    private static byte[] ReadBase64(JsonObject value, string name, int length)
    { var bytes = Convert.FromBase64String(value[name]?.GetValue<string>() ?? ""); return bytes.Length == length ? bytes : throw new InvalidDataException("Die Telefonablage ist beschädigt."); }
    private static byte[]? OptionalBase64(JsonObject value, string name)
    { if (value[name] is null) return null; return ReadBase64(value, name, 32); }
}

internal sealed record TelefonIdentity(string Id, string Name, byte[] PublicKey, byte[] PrivateKey);
internal sealed record TelefonPeer(string Id, string Name, byte[] PublicKey, string State = "paired", long LastSeenMs = 0,
    long CapabilityRevision = 0, JsonObject? StoredCapabilities = null, long GrantRevision = 0, JsonObject? StoredGrants = null,
    byte[]? PendingTranscript = null, byte[]? PendingPhoneProof = null, byte[]? PendingDesktopProof = null, long PendingExpiresMs = 0, string BluetoothAddress = "")
{
    internal JsonObject Capabilities { get; init; } = StoredCapabilities ?? new JsonObject();
    internal JsonObject Grants { get; init; } = StoredGrants ?? TelefonProtocolContract.DesktopGrants();
}
internal sealed record TelefonQueuedMessage(string Id, JsonObject Message, int Attempts, string TransportPolicy = "any");
internal sealed record TelefonAck(string MessageId, string Status, string Error, bool Process = false);
