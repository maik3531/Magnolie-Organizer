using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    internal Func<JsonObject> SharedLocalCapabilities { get; set; } = () => TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject();

    internal JsonObject SharedPreferences(string id)
    {
        lock (gate)
        {
            var peer = store.LoadPeers().SingleOrDefault(value => value.Id == id && value.State == "paired");
            if (peer is null) return new JsonObject { ["supported"] = false, ["initialized"] = false, ["ready"] = false, ["values"] = null };
            var body = store.SharedSettings(id, peer.PublicKey);
            online.TryGetValue(id, out var connection);
            return new JsonObject { ["supported"] = SharedSyncSettings.Supported(SharedLocalCapabilities(), peer.Capabilities),
                ["initialized"] = body is not null, ["ready"] = connection?.SharedSettingsReady == true,
                ["values"] = body is null ? null : SharedSyncSettings.Effective(body) };
        }
    }

    internal async Task SetCommonPreferencesAsync(string id, string expectedFingerprint, JsonObject initial,
        string? field = null, JsonNode? value = null)
    {
        await store.NotePolicyGate.WaitAsync();
        TelefonConnection? connection;
        try
        {
            lock (gate)
            {
                RequireSolePeer(id);
                var peer = store.LoadPeers().Single(item => item.Id == id && item.State == "paired");
                if (TelefonCrypto.Fingerprint(peer.PublicKey) != expectedFingerprint || !store.PersonalSettings(id).OwnDevice ||
                    !SharedSyncSettings.Supported(SharedLocalCapabilities(), peer.Capabilities))
                    throw new InvalidOperationException("Shared preferences are unavailable for this paired device.");
                var validated = SharedSyncSettings.Create(identity.Id, initial);
                if (!initial.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(SharedSyncSettings.Effective(validated).Select(pair => pair.Key)))
                    throw new InvalidDataException("A complete initial preference snapshot is required.");
                if (field is null)
                {
                    if (value is not null) throw new InvalidDataException("Unexpected preference value.");
                    store.InitializeSharedSettings(id, peer.PublicKey, initial);
                }
                else store.ChangeSharedSetting(id, peer.PublicKey, field, value ?? throw new InvalidDataException("Missing preference value."), initial);
                online.TryGetValue(id, out connection);
            }
        }
        finally { store.NotePolicyGate.Release(); }
        await ApplyCommonPreferencesAsync(id);
        if (connection is not null) await connection.SendSharedSettingsAsync();
        await ReportStatusAsync();
    }

    internal async Task StartCommonSyncAsync(string id, string expectedFingerprint, JsonObject initial)
    {
        await SetCommonPreferencesAsync(id, expectedFingerprint, initial);
        TelefonConnection? connection;
        lock (gate)
        {
            RequireSolePeer(id);
            var peer = store.LoadPeers().Single(item => item.Id == id && item.State == "paired");
            if (TelefonCrypto.Fingerprint(peer.PublicKey) != expectedFingerprint) throw new InvalidOperationException("Shared preference peer changed.");
            store.Enqueue(id, SharedSyncSettings.StartKind, new JsonObject { ["format"] = 9,
                ["request_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual" }, 60000, Now());
            online.TryGetValue(id, out connection);
        }
        if (connection is not null) await connection.PumpOutboxNowAsync();
    }

    private async Task ApplyCommonPreferencesAsync(string id)
    {
        TelefonConnection? connection;
        bool? deletionChoice = null;
        await store.NotePolicyGate.WaitAsync();
        try
        {
            lock (gate)
            {
                var peer = store.LoadPeers().SingleOrDefault(item => item.Id == id && item.State == "paired");
                if (peer is null || !store.PersonalSettings(id).OwnDevice) return;
                var body = store.SharedSettings(id, peer.PublicKey);
                if (body is null) return;
                var values = SharedSyncSettings.Effective(body);
                var deletions = !values["skip_deletions"]!.GetValue<bool>();
                if (store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != deletions) deletionChoice = deletions;
                var auto = values["auto_mode"]!.GetValue<string>() == "wifi";
                if (store.PersonalSettings(id).AutoWifi != auto) store.SetPersonalSettings(id, autoWifi: auto);
                var enabled = values["time_enabled"]!.GetValue<bool>();
                var local = store.TimeSettings(id, allowFailed: true)["local"] as JsonObject;
                if (store.TimeSupported(id) && (local is not null || enabled) && local?["enabled"]?.GetValue<bool>() != enabled)
                    store.SetTimeSettings(id, TimeSyncContract.NewSettings(enabled, (local is null ? 0 : TelefonProtocolContract.Integer(local["revision"])) + 1));
                enabled = values["custom_enabled"]!.GetValue<bool>();
                local = store.CustomSettings(id)["local"] as JsonObject;
                if (store.CustomSupported(id) && (local is not null || enabled) && local?["enabled"]?.GetValue<bool>() != enabled)
                {
                    var policy = TelefonStore.NewCustomSettings(enabled, (local is null ? 0 : TelefonProtocolContract.Integer(local["revision"])) + 1);
                    store.SetCustomSettings(id, policy, false);
                    store.Enqueue(id, "personal_sync.custom_settings", policy, 86_400_000, Now());
                }
                online.TryGetValue(id, out connection);
            }
        }
        finally { store.NotePolicyGate.Release(); }
        if (deletionChoice is bool allowDeletions) await SetGrantAsync(id, "personal_deletions_sync", allowDeletions);
        if (connection is not null) { await connection.SendTimeSettingsAsync(); await connection.PumpOutboxNowAsync(); }
    }
}
