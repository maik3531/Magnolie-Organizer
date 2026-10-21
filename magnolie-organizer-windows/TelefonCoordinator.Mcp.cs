using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private readonly byte[] mcpRevisionKey = RandomNumberGenerator.GetBytes(32);
    private sealed class McpConflictException : Exception { }
    private sealed class McpRequestException : Exception { }
    private sealed class McpEmission { internal volatile bool Active = true; }
    private readonly AsyncLocal<McpEmission?> mcpEmission = new();
    private readonly SemaphoreSlim mcpOperations = new(1, 1);
    internal Func<string?> NativeBookSource { private get; set; } = () => null;
    internal Func<NativeBookSaveState?> NativeSavedBook { private get; set; } = () => null;
    internal string? CurrentActorSource(string id, string fingerprint) => CurrentActorSource(id, fingerprint, NativeBookSource);
    private PersonalSyncActorStore? nativeActorStore;

    internal async Task<T> WithPersonalActorStoreAsync<T>(Func<PersonalSyncActorStore, T> action, CancellationToken cancellation = default)
    {
        // Only local store work belongs here; never hold these gates for network or GUI waits.
        await store.NotePolicyGate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            lock (gate)
            {
                ObjectDisposedException.ThrowIf(disposed, this);
                nativeActorStore ??= new PersonalSyncActorStore(store, CurrentActorSource);
                return action(nativeActorStore);
            }
        }
        finally { store.NotePolicyGate.Release(); }
    }

    // Native controller only: a caller-supplied JSON digest is never book authority.
    // Acquire native book/coordinator guards before calling a protected actor store.
    internal string? CurrentActorSource(string id, string fingerprint, Func<string?> nativeBookSource)
    {
        lock (gate)
        {
            if (disposed || !Enabled || store.RestoreFenced || nativeBookSource is null) return null;
            try
            {
                RequireSolePeer(id);
                var peer = RequireMcpPeer(id, fingerprint);
                if (!PersonalSyncActorContract.Supported(SharedLocalCapabilities(), peer.Capabilities)) return null;
                if (!online.TryGetValue(id, out var connection)) return null;
                var snapshot = connection.ActorSourceSnapshot();
                var book = nativeBookSource();
                if (book is null || !System.Text.RegularExpressions.Regex.IsMatch(book, "\\A[0-9a-f]{64}\\z")) return null;
                snapshot["profile"] = identity.Id; snapshot["book"] = book;
                var bytes = TelefonCrypto.Canonical(snapshot);
                try
                {
                    var revision = Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, bytes)).ToLowerInvariant();
                    return nativeBookSource() == book ? revision : null;
                }
                finally { Array.Clear(bytes); }
            }
            catch (Exception error) when (error is InvalidOperationException or InvalidDataException or McpConflictException)
            { return null; }
        }
    }

    private Task McpServiceTask(Func<Task> body)
    {
        if (mcpEmission.Value is { Active: true } && !ExecutionContext.IsFlowSuppressed())
        { using (ExecutionContext.SuppressFlow()) return Task.Run(body); }
        return Task.Run(body);
    }

    private void CheckMcpRevision(string? expected)
    {
        if (expected is not null && expected != McpStatus()["revision"]!.GetValue<string>()) throw new McpConflictException();
    }

    private TelefonPeer RequireMcpPeer(string id, string fingerprint, bool requirePaired = true)
    {
        var peer = store.LoadPeers().FirstOrDefault(peer => peer.Id == id && (!requirePaired || peer.State == "paired"));
        if (peer is null || !TelefonCrypto.Fingerprint(peer.PublicKey).Equals(fingerprint, StringComparison.OrdinalIgnoreCase)) throw new McpConflictException();
        return peer;
    }

    internal void AssertMcpTarget(string id, string fingerprint, string? revision = null)
    { lock (gate) { CheckMcpRevision(revision); RequireMcpPeer(id, fingerprint, requirePaired: false); } }

    internal async Task SetBluetoothPreferenceAsync(string id, bool enabled, string address, string? expectedFingerprint = null, string? expectedRevision = null)
    {
        if (enabled && !TelefonBluetoothSupport.Available) throw new NotSupportedException();
        address = address.Trim().ToUpperInvariant();
        lock (gate)
        {
            CheckMcpRevision(expectedRevision);
            if (expectedFingerprint is not null) RequireMcpPeer(id, expectedFingerprint);
            else if (Peers.All(peer => peer.Id != id)) throw new InvalidOperationException(T("The phone is not paired."));
            store.SetBluetoothPreference(id, enabled, address);
        }
        await ReportStatusAsync();
    }

    private static string[] McpEditableGrants() => TelefonProtocolContract.GrantNames.Where(name => !TelefonProtocolContract.IsDesktopGranted(name)).Order(StringComparer.Ordinal).ToArray();
    private static string McpText(JsonObject request, string key, bool required = false)
    {
        if (request[key] is null && !required) return "";
        if (request[key] is JsonValue value && value.TryGetValue<string>(out var text) && text.Length <= 512 && (!required || text.Length > 0)) return text;
        throw new McpRequestException();
    }
    private static bool McpFlag(JsonObject request, string key) => request[key] is JsonValue value && value.TryGetValue<bool>(out var flag) ? flag : throw new McpRequestException();

    internal JsonObject McpNotesSettings(string id, string fingerprint)
    {
        lock (gate)
        {
            RequireSolePeer(id);
            var peer = RequireMcpPeer(id, fingerprint);
            var personal = store.PersonalSettings(id);
            var control = new JsonObject { ["phone_revision"] = McpStatus()["revision"]!.DeepClone(),
                ["own_device"] = personal.OwnDevice, ["remote_own_device"] = personal.RemoteOwnDevice,
                ["auto_wifi"] = personal.AutoWifi, ["note"] = store.NoteSettings(id),
                ["custom"] = store.CustomSettings(id), ["time"] = store.TimeSettings(id, allowFailed: true),
                ["shared"] = store.SharedSettings(id, peer.PublicKey) };
            var bytes = Encoding.UTF8.GetBytes(control.ToJsonString());
            string revision;
            try { revision = Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, bytes)).ToLowerInvariant(); }
            finally { Array.Clear(bytes); }
            return new() { ["revision"] = revision, ["peer_id"] = id, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey),
                ["own_device"] = personal.OwnDevice, ["remote_own_device"] = personal.RemoteOwnDevice,
                ["auto_wifi"] = personal.AutoWifi, ["skip_deletions"] = store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != true,
                ["note_direction"] = new JsonObject { ["supported"] = store.NoteModeSupported(id), ["local_mode"] = store.NoteSettings(id)["local"]?["mode"]?.DeepClone() },
                ["policies"] = new JsonObject {
                    ["custom"] = new JsonObject { ["supported"] = store.CustomSupported(id), ["local_enabled"] = control["custom"]?["local"]?["enabled"]?.DeepClone() },
                    ["time"] = new JsonObject { ["supported"] = store.TimeSupported(id), ["local_enabled"] = control["time"]?["local"]?["enabled"]?.DeepClone() } },
                ["shared"] = SharedPreferences(id) };
        }
    }

    private void AssertMcpLegacyNotes(string id, string fingerprint, string? revision)
    {
        var state = McpNotesSettings(id, fingerprint);
        if (revision != state["revision"]!.GetValue<string>()) throw new McpConflictException();
        if (state["shared"]!["supported"]!.GetValue<bool>() || state["shared"]!["initialized"]!.GetValue<bool>()) throw new NotSupportedException();
    }

    internal async Task<JsonObject> ExecuteMcpAsync(JsonObject request, CancellationToken cancellation,
        Func<string, string, string, Task>? removeWithRuntime = null)
    {
        if (request["action"]?.GetValue<string>() is "device_status_query" or "device_status_cancel") return await ExecuteMcpStatusAsync(request, cancellation);
        if (request["action"]?.GetValue<string>()?.StartsWith("call_actor_", StringComparison.Ordinal) == true) return ExecuteMcpCallActor(request);
        if (request["action"]?.GetValue<string>() == "call_context_read") return ExecuteMcpCallContext(request);
        if (request["action"]?.GetValue<string>()?.StartsWith("time_control_", StringComparison.Ordinal) == true) return await ExecuteMcpTimeControlAsync(request, cancellation);
        if (request["action"]?.GetValue<string>()?.StartsWith("notes_actor_", StringComparison.Ordinal) == true)
            return await ExecuteMcpActorAsync(request, cancellation);
        if (!await mcpOperations.WaitAsync(0, cancellation).ConfigureAwait(false)) return new() { ["ok"] = false, ["code"] = "native_busy" };
        var previous = mcpEmission.Value; var capture = new McpEmission(); mcpEmission.Value = capture;
        try
        {
            if (store.RestoreFenced) return new() { ["ok"] = false, ["code"] = "native_busy" };
            if (request["action"]?.GetValue<string>() == "notes_settings_read")
                return new() { ["ok"] = true, ["notesSettings"] = McpNotesSettings(McpText(request, "peerId", true), McpText(request, "fingerprint", true)) };
            var action = McpText(request, "action", true); var revision = McpText(request, "expectedRevision", true);
            var id = McpText(request, "peerId"); var fingerprint = McpText(request, "fingerprint");
            var enabled = (action is "settings" or "grant" or "bluetooth" or "notes_ownership" or "notes_legacy_mode" or "notes_legacy_policy") && McpFlag(request, "enabled");
            var skipDeletions = action == "notes_legacy_mode" && McpFlag(request, "skipDeletions");
            var name = McpText(request, "name"); var address = McpText(request, "address").Trim().ToUpperInvariant();
            var accept = action == "pairing_confirm" && McpFlag(request, "accept");
            Func<Task> operation;
            PairingConfirmation? confirmation = null;
            lock (gate)
            {
                if (store.RestoreFenced) return new() { ["ok"] = false, ["code"] = "native_busy" };
                if (action is "notes_settings_update" or "notes_ownership" or "notes_legacy_mode" or "notes_note_direction" or "notes_legacy_policy")
                {
                    var notes = McpNotesSettings(id, fingerprint);
                    if (revision != notes["revision"]!.GetValue<string>()) throw new McpConflictException();
                    if (action == "notes_settings_update" && !notes["shared"]!["supported"]!.GetValue<bool>()) throw new NotSupportedException();
                }
                else CheckMcpRevision(revision);
                if (action is "remove" or "grant" or "bluetooth") RequireMcpPeer(id, fingerprint, requirePaired: action != "remove");
                if (action == "grant" && !McpEditableGrants().Contains(name, StringComparer.Ordinal)) return new() { ["ok"] = false, ["code"] = "unsupported_feature" };
                if (action == "pairing_begin" && (!Enabled || !IsRunning)) throw new McpConflictException();
                if (action is "pairing_confirm" or "pairing_cancel")
                {
                    var attempt = McpText(request, "attemptId", true);
                    if (!confirmations.TryGetValue(id, out confirmation) || confirmation.AttemptId != attempt || confirmation.Completion.Task.IsCompleted || confirmation.Deadline <= Environment.TickCount64 ||
                        !confirmation.Public["fingerprint"]!.GetValue<string>().Equals(fingerprint, StringComparison.OrdinalIgnoreCase)) throw new McpConflictException();
                }
                operation = action switch
                {
                    "settings" => () => SwitchAsync(enabled, revision),
                    "pairing_begin" => () => StartPairingAsync(revision),
                    "pairing_confirm" or "pairing_cancel" => () =>
                    {
                        lock (gate)
                        {
                            CheckMcpRevision(revision);
                            if (!confirmations.TryGetValue(id, out var current) || !ReferenceEquals(current, confirmation)) throw new McpConflictException();
                            ConfirmPairing(id, action == "pairing_confirm" && accept);
                        }
                        return Task.CompletedTask;
                    },
                    "remove" => () => removeWithRuntime is null ? RemoveAsync(id, fingerprint, revision) : removeWithRuntime(id, fingerprint, revision),
                    "grant" => () => SetGrantAsync(id, name, enabled, fingerprint, revision),
                    "bluetooth" => () => SetBluetoothPreferenceAsync(id, enabled, address, fingerprint, revision),
                    "notes_ownership" => () => SetPersonalSyncAsync(id, enabled, false, fingerprint, revision),
                    "notes_legacy_mode" => () => SetPersonalSyncModeAsync(id, enabled, skipDeletions, fingerprint, revision),
                    "notes_note_direction" => () => SetNoteModeAsync(id, McpText(request, "mode", true), fingerprint, revision),
                    "notes_legacy_policy" when name == "time" => () => SendTimeBridgeAsync(id, TimeSyncContract.Settings, new JsonObject { ["enabled"] = enabled }, fingerprint, revision),
                    "notes_legacy_policy" when name == "custom" => () => SendCustomBridgeAsync(id, "personal_sync.custom_settings", new JsonObject(), fingerprint, revision, enabled),
                    "notes_settings_update" => () => SetCommonPreferencesAsync(id, fingerprint,
                        request["initial"] as JsonObject ?? throw new McpRequestException(),
                        McpText(request, "field", true), request["value"] ?? throw new McpRequestException(), expectedNotesRevision: revision),
                    _ => throw new McpRequestException()
                };
            }
            await operation().ConfigureAwait(false);
            cancellation.ThrowIfCancellationRequested();
            if (action == "notes_legacy_policy")
            {
                lock (gate)
                {
                    var state = McpNotesSettings(id, fingerprint);
                    if (state["policies"]?[name]?["local_enabled"]?.GetValue<bool>() != enabled)
                        return new() { ["ok"] = false, ["code"] = "verification_failed" };
                    return new() { ["ok"] = true, ["action"] = action, ["notesSettings"] = state,
                        ["localVerified"] = true, ["persisted"] = true, ["deliveryConfirmed"] = false };
                }
            }
            if (action == "notes_note_direction")
            {
                lock (gate)
                {
                    var state = McpNotesSettings(id, fingerprint);
                    if (state["note_direction"]!["local_mode"]?.GetValue<string>() != McpText(request, "mode", true))
                        return new() { ["ok"] = false, ["code"] = "verification_failed" };
                    return new() { ["ok"] = true, ["action"] = action, ["notesSettings"] = state,
                        ["localVerified"] = true, ["persisted"] = true, ["deliveryConfirmed"] = false };
                }
            }
            if (action == "notes_legacy_mode")
            {
                lock (gate)
                {
                    var state = McpNotesSettings(id, fingerprint);
                    if (!state["own_device"]!.GetValue<bool>() || state["auto_wifi"]!.GetValue<bool>() != enabled ||
                        !store.StoredGrantMatches("personal_notes_sync", true) || !store.StoredGrantMatches("personal_tasks_sync", true) ||
                        !store.StoredGrantMatches("personal_deletions_sync", !skipDeletions))
                        return new() { ["ok"] = false, ["code"] = "verification_failed" };
                    return new() { ["ok"] = true, ["action"] = action, ["notesSettings"] = state,
                        ["localVerified"] = true, ["persisted"] = true, ["deliveryConfirmed"] = false };
                }
            }
            if (action == "notes_ownership")
            {
                lock (gate)
                {
                    var state = McpNotesSettings(id, fingerprint);
                    if (state["own_device"]!.GetValue<bool>() != enabled || (!enabled && state["auto_wifi"]!.GetValue<bool>()))
                        return new() { ["ok"] = false, ["code"] = "verification_failed" };
                    return new() { ["ok"] = true, ["action"] = action, ["notesSettings"] = state,
                        ["localVerified"] = true, ["persisted"] = true, ["deliveryConfirmed"] = false };
                }
            }
            if (action == "notes_settings_update")
            {
                lock (gate)
                {
                    var state = McpNotesSettings(id, fingerprint);
                    var values = state["shared"]?["values"] as JsonObject;
                    if (!state["own_device"]!.GetValue<bool>() || values is null || !JsonNode.DeepEquals(values[McpText(request, "field", true)], request["value"]) ||
                        store.PersonalSettings(id).AutoWifi != (values["auto_mode"]!.GetValue<string>() == "wifi") ||
                        !store.StoredGrantMatches("personal_deletions_sync", !values["skip_deletions"]!.GetValue<bool>()))
                        return new() { ["ok"] = false, ["code"] = "verification_failed" };
                    return new() { ["ok"] = true, ["action"] = action, ["notesSettings"] = state,
                        ["localVerified"] = true, ["persisted"] = true, ["deliveryConfirmed"] = false };
                }
            }
            bool verified, persisted;
            lock (gate)
            {
                persisted = action switch
                {
                    "settings" => store.StoredEnabledMatches(enabled),
                    "remove" => store.LoadPeers().All(peer => peer.Id != id),
                    "grant" => store.StoredGrantMatches(name, enabled),
                    "bluetooth" => store.StoredBluetoothMatches(id, enabled, address),
                    _ => false
                };
                if (action is "grant" or "bluetooth") RequireMcpPeer(id, fingerprint);
                verified = action switch
                {
                    "settings" => persisted && Enabled == enabled && IsRunning == enabled,
                    "pairing_begin" => McpStatus()["pairing_open"]!.GetValue<bool>(),
                    "pairing_confirm" or "pairing_cancel" => confirmation is not null && confirmation.Completion.Task.IsCompletedSuccessfully && confirmation.Completion.Task.Result == (action == "pairing_confirm" && accept),
                    _ => persisted
                };
            }
            if (!verified) return new() { ["ok"] = false, ["code"] = "verification_failed" };
            return new() { ["ok"] = true, ["status"] = McpStatus(), ["action"] = action, ["localVerified"] = true, ["persisted"] = persisted, ["deliveryConfirmed"] = false };
        }
        catch (McpConflictException) { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (McpRequestException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (InvalidDataException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (NotSupportedException) { return new() { ["ok"] = false, ["code"] = "unsupported_feature" }; }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (InvalidOperationException error) when (error.Message == "binding_conflict") { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (Exception) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
        finally { capture.Active = false; mcpEmission.Value = previous; mcpOperations.Release(); }
    }

    private static JsonObject McpGrants(JsonObject value)
    {
        var result = new JsonObject();
        foreach (var (key, raw) in value.OrderBy(item => item.Key, StringComparer.Ordinal))
            if (key.Length <= 80 && raw is JsonValue scalar && scalar.TryGetValue<bool>(out var enabled)) result[key] = enabled;
        return result;
    }

    private static JsonObject McpCapabilities(JsonObject value)
    {
        var result = new JsonObject();
        foreach (var (key, raw) in value.OrderBy(item => item.Key, StringComparer.Ordinal))
        {
            if (key.Length > 80 || raw is not JsonObject item) continue;
            result[key] = new JsonObject { ["available"] = item["available"] is JsonValue flag && flag.TryGetValue<bool>(out var available) && available,
                ["versions"] = new JsonArray((item["versions"] as JsonArray ?? []).OfType<JsonValue>()
                    .Where(version => version.TryGetValue<int>(out var number) && number is >= 0 and <= 1000).Take(32).Select(version => version.DeepClone()).ToArray()) };
        }
        return result;
    }

    private static JsonObject McpBluetoothStatus()
    {
        var reason = TelefonBluetoothSupport.Reason;
        if (reason.Length > 80 || !System.Text.RegularExpressions.Regex.IsMatch(reason, "^[a-z0-9_]+$")) reason = "unavailable";
        return new() { ["available"] = TelefonBluetoothSupport.Available, ["reason"] = reason, ["paired_devices_supported"] = false, ["devices"] = new JsonArray() };
    }

    internal JsonObject McpStatus()
    {
        lock (gate)
        {
            var peers = store.LoadPeers().OrderBy(peer => peer.Id, StringComparer.Ordinal).ToArray();
            var publicPeers = new JsonArray(); var controls = new JsonArray();
            var grants = McpGrants(store.LocalGrants());
            foreach (var peer in peers)
            {
                var address = store.BluetoothAddress(peer.Id);
                publicPeers.Add(new JsonObject { ["id"] = peer.Id, ["name"] = peer.Name, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey), ["state"] = peer.State,
                    ["online"] = online.ContainsKey(peer.Id), ["transport"] = OnlineTransport(peer.Id), ["bluetooth_enabled"] = address.Length > 0, ["bluetooth_address"] = address,
                    ["local_grants"] = grants.DeepClone(), ["remote_grants"] = McpGrants(peer.Grants), ["remote_capabilities"] = McpCapabilities(peer.Capabilities) });
                controls.Add(new JsonObject { ["id"] = peer.Id, ["key"] = Convert.ToBase64String(peer.PublicKey), ["state"] = peer.State, ["bluetooth"] = address,
                    ["remote_grants"] = peer.Grants.DeepClone(), ["remote_grant_revision"] = peer.GrantRevision, ["remote_capabilities"] = peer.Capabilities.DeepClone(), ["remote_capability_revision"] = peer.CapabilityRevision });
            }
            var pending = new JsonArray(confirmations.Values.Where(item => !item.Completion.Task.IsCompleted && item.Deadline > Environment.TickCount64)
                .OrderBy(item => item.AttemptId, StringComparer.Ordinal).Select(item =>
                {
                    var value = item.Public.DeepClone().AsObject(); value["decision_pending"] = true; return (JsonNode)value;
                }).ToArray());
            var pairingOpen = pairingToken is not null && pairingUntil > DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var control = new JsonObject { ["id"] = identity.Id, ["key"] = Convert.ToBase64String(identity.PublicKey), ["enabled"] = Enabled,
                ["stored_enabled"] = store.Enabled, ["peers"] = controls, ["local_grants"] = grants, ["pairing"] = pairingOpen,
                ["pairing_token"] = pairingToken is null ? "" : Convert.ToBase64String(pairingToken), ["pending"] = pending.DeepClone() };
            var bytes = Encoding.UTF8.GetBytes(control.ToJsonString());
            string revision;
            try { revision = Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, bytes)).ToLowerInvariant(); }
            finally { Array.Clear(bytes); }
            return new JsonObject { ["revision"] = revision, ["available"] = true, ["enabled"] = Enabled, ["listening"] = IsRunning,
                ["id"] = identity.Id, ["name"] = identity.Name, ["fingerprint"] = TelefonCrypto.Fingerprint(identity.PublicKey), ["port"] = Port,
                ["pairing_open"] = pairingOpen, ["pending_pairings"] = pending, ["binding_conflict"] = peers.Length > 1, ["error_present"] = error.Length > 0,
                ["capabilities"] = McpCapabilities(TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject()),
                ["editable_grants"] = new JsonArray(McpEditableGrants().Select(name => (JsonNode?)JsonValue.Create(name)).ToArray()), ["bluetooth"] = McpBluetoothStatus(), ["peers"] = publicPeers };
        }
    }
}
