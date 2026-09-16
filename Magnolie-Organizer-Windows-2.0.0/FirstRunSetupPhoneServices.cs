using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Setup consumes only pairing/status events. It never dispatches phone data into the organizer.
internal sealed class FirstRunSetupPhoneServices(WindowsPaths paths, TelefonStore? dataStore = null,
    ITelefonBluetoothClient? bluetoothClient = null, IPhoneStartupPlatform? startupPlatform = null,
    bool localOnly = false) : IFirstRunSetupPhoneServices, IDisposable
{
    private readonly ITelefonBluetoothClient? bluetoothClient = bluetoothClient ?? TelefonBluetoothClient.Create();
    private TelefonCoordinator? phone;
    private TelefonStore? phoneStore;
    private KdeConnectDirectBackend? kde;
    private JsonObject? phoneStatus;
    private readonly ConcurrentQueue<JsonObject> confirmations = new();
    private readonly Dictionary<string, string> connectedIds = new(StringComparer.Ordinal);
    private static string T(string value) => NativeLocalization.Gettext(value);
    public IReadOnlyList<SetupPhoneCapability> Capabilities =>
    [new("wifi", true, true), new("kdeconnect", true, true),
     new("bluetooth", bluetoothClient is not null, bluetoothClient is not null, "Bluetooth is unavailable in this build.")
    ];

    private Task Emit(string name, object value)
    {
        var json = JsonSerializer.SerializeToNode(value)!.AsObject();
        if (name == "App.telefonVerbindungStand") phoneStatus = json;
        if (name == "App.telefonPaarung" && json["code"]?.GetValue<string>() is { Length: > 0 }) confirmations.Enqueue(json);
        return Task.CompletedTask;
    }

    public async Task<SetupPhoneResult> ConnectAsync(string transport, Func<SetupPhonePrompt, Task<string?>> prompt, CancellationToken cancellationToken)
    {
        if (!Capabilities.Any(c => c.Transport == transport && c.Available)) throw new NotSupportedException(T("This phone transport is unavailable."));
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromMinutes(2));
        var ct = timeout.Token;
        if (transport == "kdeconnect")
        {
            kde ??= new KdeConnectDirectBackend(paths);
            string selected = "";
            KdeConnectPairing? ownedRequest = null;
            try
            {
                if (!kde.HasPairedPeers)
                {
                    var devices = await kde.DiscoverAsync(TimeSpan.FromSeconds(5), ct, collectForDuration: true);
                    if (devices.Count == 0) throw new InvalidOperationException(T("No phone was found. Open the phone app and try again."));
                    selected = devices.Count == 1 ? devices[0].Identity.DeviceId :
                        await prompt(new SetupPhonePrompt("select", devices.Select(d => new SetupSource(d.Identity.DeviceId, d.Identity.DeviceName)).ToArray())).WaitAsync(ct) ?? "";
                    if (selected.Length == 0) throw new OperationCanceledException();
                    if (!devices.Any(d => d.Identity.DeviceId == selected)) throw new InvalidOperationException(T("The selected phone changed. Try again."));
                    var pairing = await kde.BeginPairingAsync(selected, ct);
                    ownedRequest = pairing;
                    var accepted = await prompt(new SetupPhonePrompt("confirm", [new SetupSource(selected, pairing.DeviceName)], pairing.Code)).WaitAsync(ct);
                    await kde.ConfirmPairingAsync(selected, accepted == "accept", ct);
                    if (accepted != "accept") throw new OperationCanceledException();
                }
                while (true)
                {
                    ct.ThrowIfCancellationRequested();
                    var status = await kde.GetStatusAsync(ct);
                    if (status.Available && status.PairedCount > 0 && (selected.Length == 0 || status.DeviceId == selected))
                    {
                        connectedIds[transport] = status.DeviceId;
                        return new SetupPhoneResult(transport, status.DeviceId, status.PeerName, true);
                    }
                    await Task.Delay(300, ct);
                }
            }
            finally
            {
                if (ownedRequest is not null) kde.CancelSetupPairing(ownedRequest);
            }
        }
        if (phone is null)
        {
            var settings = new AtomicStore().Read(paths.TelefonSettings, 64 * 1024);
            if (settings is not null && JsonNode.Parse(settings) is not JsonObject)
                throw new InvalidDataException(T("The phone settings could not be read."));
            phoneStore = dataStore ?? new TelefonStore(paths);
            phone = new TelefonCoordinator(paths, Emit, dataStore: phoneStore, bluetoothClient: bluetoothClient, localOnly: localOnly);
        }
        await phone.StartSetupAsync();
        if (!phone.IsRunning) throw new InvalidOperationException(T("The phone listener could not start."));
        if (transport == "bluetooth" && phone.StatusPeers.Length == 0) return await ConnectBluetoothAsync(prompt, ct);
        if (transport == "bluetooth")
        {
            await Task.Delay(700, ct);
            if (!TelefonBluetoothSupport.Available && !phone.StatusPeers.Any(p => TelefonBluetoothClient.ValidAddress(phoneStore!.BluetoothAddress(p.Id))))
                throw new NotSupportedException(T("Bluetooth is unavailable. Check the radio and OS permissions."));
        }
        string? selectedPhone = null;
        JsonObject? invitation = null;
        try
        {
        if (transport == "wifi" && phone.StatusPeers.Length == 0)
        {
            var devices = await TelefonInvitation.DiscoverAsync(ct);
            if (devices.Count == 0) throw new InvalidOperationException(T("No phone was found. Open the phone app and try again."));
            selectedPhone = await prompt(new SetupPhonePrompt("select", devices.Select(d => new SetupSource(d.Id, d.Name)).ToArray())).WaitAsync(ct);
            var selected = devices.FirstOrDefault(d => d.Id == selectedPhone) ?? throw new OperationCanceledException();
            invitation = phone.OpenSetupPairing(selected.Id, selected.Address);
            await TelefonInvitation.SendAsync(selected, invitation, ct);
        }
        else if (phone.StatusPeers.Length == 0) await phone.StartPairingAsync();
        string? ownId = null;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            while (confirmations.TryDequeue(out var challenge))
            {
                var id = challenge["kennung"]!.GetValue<string>();
                if (selectedPhone is not null && selectedPhone != id) { phone.ConfirmPairing(id, false); continue; }
                var accepted = await prompt(new SetupPhonePrompt("confirm", [new SetupSource(id, challenge["name"]!.GetValue<string>())],
                    challenge["code"]!.GetValue<string>(), true)).WaitAsync(ct);
                phone.ConfirmPairing(id, accepted is "accept" or "accept-own");
                if (accepted is not ("accept" or "accept-own")) throw new OperationCanceledException();
                if (accepted == "accept-own") ownId = id;
            }
            await phone.ReportStatusAsync();
            var peer = (phoneStatus?["telefone"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(p =>
                p["state"]?.GetValue<string>() == "paired" && p["online"]?.GetValue<bool>() == true && p["transport"]?.GetValue<string>() == transport &&
                (selectedPhone is null || p["kennung"]?.GetValue<string>() == selectedPhone));
            if (peer is not null)
            {
                var id = peer["kennung"]!.GetValue<string>();
                if (ownId == id) phoneStore!.SetPersonalSettings(id, ownDevice: true);
                connectedIds[transport] = id;
                return new SetupPhoneResult(transport, id, peer["name"]!.GetValue<string>(), true);
            }
            await Task.Delay(250, ct);
        }
        }
        finally { if (invitation is not null) phone.EndSetupPairing(invitation["token"]!.GetValue<string>()); }
    }

    private async Task<SetupPhoneResult> ConnectBluetoothAsync(Func<SetupPhonePrompt, Task<string?>> prompt, CancellationToken cancellation)
    {
        phone!.PauseUnpairedWindow();
        var devices = await bluetoothClient!.DiscoverAsync(cancellation);
        if (devices.Count == 0) throw new InvalidOperationException(T("No phone was found. Open the phone app and try again."));
        var selectedId = await prompt(new("select", devices.Select(d => new SetupSource(d.Address, d.Name)).ToArray())).WaitAsync(cancellation);
        var selected = devices.SingleOrDefault(d => d.Address == selectedId) ?? throw new OperationCanceledException();
        await bluetoothClient.PairAsync(selected, cancellation);
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        using var link = await bluetoothClient.ConnectAsync(selected.Address, lifetime.Token);
        using var registration = lifetime.Token.Register(link.Dispose);
        var available = await TelefonBluetoothClient.AvailableAsync(link, selected.Address, lifetime.Token);
        var invitation = phone.OpenBluetoothSetupPairing(available.Id, selected.Address);
        Task? handshake = null;
        try
        {
            await TelefonBluetoothClient.InviteAsync(link.Stream, available.Id, available.Nonce, invitation, lifetime.Token);
            handshake = phone.HandleStreamAsync(link.Stream, lifetime.Token, "bluetooth", "bluetooth:" + link.Address);
            var configured = false; var own = false;
            while (true)
            {
                lifetime.Token.ThrowIfCancellationRequested();
                while (confirmations.TryDequeue(out var challenge))
                {
                    var id = challenge["kennung"]!.GetValue<string>();
                    if (id != available.Id) { phone.ConfirmPairing(id, false); continue; }
                    var answer = await prompt(new("confirm", [new(id, challenge["name"]!.GetValue<string>())],
                        challenge["code"]!.GetValue<string>(), true)).WaitAsync(lifetime.Token);
                    phone.ConfirmPairing(id, answer is "accept" or "accept-own");
                    if (answer is not ("accept" or "accept-own")) throw new OperationCanceledException();
                    own = answer == "accept-own";
                }
                if (!configured && handshake.IsCompleted)
                {
                    await handshake;
                    if (!phone.StatusPeers.Any(p => p.Id == available.Id)) throw new InvalidOperationException(T("Phone connection cancelled or timed out."));
                    if (phone.Peers.Any(p => p.Id == available.Id))
                    {
                        link.Dispose();
                        phoneStore!.SetBluetoothAddress(available.Id, selected.Address);
                        configured = true;
                    }
                }
                await phone.ReportStatusAsync();
                var peer = (phoneStatus?["telefone"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(p =>
                    p["kennung"]?.GetValue<string>() == available.Id && p["online"]?.GetValue<bool>() == true &&
                    p["state"]?.GetValue<string>() == "paired" && p["transport"]?.GetValue<string>() == "bluetooth");
                if (peer is not null)
                {
                    if (own) phoneStore!.SetPersonalSettings(available.Id, ownDevice: true);
                    connectedIds["bluetooth"] = available.Id;
                    return new("bluetooth", available.Id, peer["name"]!.GetValue<string>(), true);
                }
                await Task.Delay(200, lifetime.Token);
            }
        }
        finally
        {
            lifetime.Cancel(); phone.EndSetupPairing(invitation["token"]!.GetValue<string>());
            if (handshake is not null) try { await handshake; } catch (OperationCanceledException) { }
        }
    }

    public async Task<IReadOnlyList<string>> ConnectedAsync(CancellationToken cancellationToken)
    {
        var result = new List<string>();
        if (phone is not null)
        {
            await phone.ReportStatusAsync();
            foreach (var p in (phoneStatus?["telefone"] as JsonArray ?? []).OfType<JsonObject>())
                if (p["online"]?.GetValue<bool>() == true && p["state"]?.GetValue<string>() == "paired" &&
                    p["transport"]?.GetValue<string>() is { } transport && connectedIds.TryGetValue(transport, out var id) && id == p["kennung"]?.GetValue<string>()) result.Add(transport);
        }
        if (kde is not null && connectedIds.TryGetValue("kdeconnect", out var kdeId))
        {
            var status = await kde.GetStatusAsync(cancellationToken);
            if (status.Available && status.PairedCount > 0 && status.DeviceId == kdeId) result.Add("kdeconnect");
        }
        return result;
    }

    public async Task CommitStartupAsync(IReadOnlyList<string> transports, CancellationToken cancellationToken)
    {
        var live = await ConnectedAsync(cancellationToken);
        if (transports.Any(t => !live.Contains(t))) throw new InvalidOperationException(T("The phone is no longer connected."));
        cancellationToken.ThrowIfCancellationRequested();
        FirstRunPhoneStartup.Apply(transports, phoneStore, startupPlatform ?? new NativePhoneStartupPlatform(paths),
            connectedPhone: live.Any(t => t is "wifi" or "bluetooth"));
    }

    public void Dispose()
    {
        phone?.Dispose(); kde?.Dispose();
    }
}
