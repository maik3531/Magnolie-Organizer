using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonBluetoothSetupTests
{
    private const string Phone = "AA:BB:CC:DD:EE:01";
    internal static async Task RunAsync()
    {
        TestAssert.That(TelefonBluetoothClient.ValidAddress(Phone), "Canonical MAC rejected");
        foreach (var wrong in new[] { "http://127.0.0.1", "AA:BB", "AA:BB:CC:DD:EE:GG", "aa:bb:cc:dd:ee:01" })
            TestAssert.That(!TelefonBluetoothClient.ValidAddress(wrong), "Invalid Bluetooth target accepted");
        if (Environment.GetEnvironmentVariable("MAGNOLIE_BLUETOOTH_INTEGRATION") != "1") return;
        var root = Path.Combine(Path.GetTempPath(), "magnolie-bt-negative-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, RandomNumberGenerator.GetBytes(32));
            var prompts = 0;
            using var coordinator = new TelefonCoordinator(paths, (name, value) =>
            {
                if (name == "App.telefonPaarung" && JsonSerializer.SerializeToNode(value)?["code"]?.GetValue<string>() is { Length: > 0 }) Interlocked.Increment(ref prompts);
                return Task.CompletedTask;
            }, dataStore: store, localOnly: true);
            await coordinator.SwitchAsync(true);
            var id = Guid.NewGuid().ToString();
            foreach (var attack in new[] { "wrong-device", "wrong-target", "expired", "cancelled", "replayed-token", "bad-proof" })
            {
                var offer = coordinator.OpenBluetoothSetupPairing(id, Phone);
                var token = offer["token"]!.GetValue<string>();
                if (attack == "expired") typeof(TelefonCoordinator).GetField("pairingUntil", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(coordinator, 0L);
                if (attack is "cancelled" or "replayed-token") coordinator.EndSetupPairing(token);
                if (attack == "replayed-token") offer = coordinator.OpenBluetoothSetupPairing(id, Phone);
                using var listener = new TcpListener(IPAddress.Loopback, 0);
                listener.Start();
                using var client = new TcpClient();
                await client.ConnectAsync((IPEndPoint)listener.LocalEndpoint);
                using var server = await listener.AcceptTcpClientAsync();
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                var handler = Task.Run(async () =>
                {
                    using (server) await coordinator.HandleStreamAsync(server.GetStream(), timeout.Token, "bluetooth",
                        "bluetooth:" + (attack == "wrong-device" ? "AA:BB:CC:DD:EE:03" : Phone));
                });
                var keys = TelefonCrypto.GenerateX25519();
                var init = new JsonObject {
                    ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_init", ["role"] = "phone", ["pairing_token"] = token,
                    ["device_id"] = attack == "wrong-target" ? Guid.NewGuid().ToString() : id, ["display_name"] = "Fixture",
                    ["static_public"] = Convert.ToBase64String(keys.Public), ["ephemeral_public"] = Convert.ToBase64String(keys.Public),
                    ["nonce"] = Convert.ToBase64String(new byte[32]), ["versions"] = new JsonArray(1)
                };
                await TelefonCoordinator.WriteFrameAsync(client.GetStream(), init, timeout.Token);
                CryptographicOperations.ZeroMemory(keys.Private);
                if (attack == "bad-proof")
                {
                    var response = await TelefonCoordinator.ReadFrameAsync(client.GetStream(), 65536, timeout.Token);
                    while (prompts == 0) await Task.Delay(10, timeout.Token);
                    coordinator.ConfirmPairing(id, true);
                    var transcript = SHA256.HashData(TelefonCrypto.Canonical(init).Concat(TelefonCrypto.Canonical(response)).ToArray());
                    await TelefonCoordinator.WriteFrameAsync(client.GetStream(), new JsonObject {
                        ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_confirm", ["side"] = "phone",
                        ["transcript"] = Convert.ToBase64String(transcript), ["proof"] = Convert.ToBase64String(new byte[32])
                    }, timeout.Token);
                }
                TestAssert.That(await client.GetStream().ReadAsync(new byte[1], timeout.Token) == 0, "Bluetooth attack produced a response: " + attack);
                await handler;
                coordinator.EndSetupPairing(offer["token"]!.GetValue<string>());
                TestAssert.That(prompts == (attack == "bad-proof" ? 1 : 0) && store.LoadPeers().Count == 0, "Bluetooth attack persisted trust or bypassed validation");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
    }
    internal sealed class FakeOs(int port, string mode) : ITelefonBluetoothClient
    {
        internal bool Paired;
        internal int Connections;
        internal TelefonBluetoothLink? Last;
        public Task<IReadOnlyList<TelefonBluetoothCandidate>> DiscoverAsync(CancellationToken cancellation) =>
            Task.FromResult<IReadOnlyList<TelefonBluetoothCandidate>>([new("fixture", Phone, "Owned phone", Paired)]);
        public async Task PairAsync(TelefonBluetoothCandidate device, CancellationToken cancellation)
        {
            TestAssert.That(device.Address == Phone && device.Id == "fixture", "OS pairing addressed wrong device");
            if (Paired) return;
            Console.WriteLine("OSPAIR");
            if (await Console.In.ReadLineAsync(cancellation) != "OSACCEPT") throw new UnauthorizedAccessException();
            Paired = true;
        }
        public async Task<TelefonBluetoothLink> ConnectAsync(string address, CancellationToken cancellation)
        {
            TestAssert.That(Paired && address == Phone, "RFCOMM before OS consent or to wrong device");
            var socket = new TcpClient();
            await socket.ConnectAsync(IPAddress.Loopback, port, cancellation);
            Interlocked.Increment(ref Connections);
            return Last = new TelefonBluetoothLink(mode == "wrong-device" ? "AA:BB:CC:DD:EE:03" : address, socket.GetStream(), socket.Dispose);
        }
    }

    internal static async Task<int> HostAsync(int port, string mode)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-bt-first-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        TelefonStore? store = null;
        TelefonCoordinator? resumed = null;
        try
        {
            var paths = new WindowsPaths(root); var storageKey = RandomNumberGenerator.GetBytes(32);
            store = new TelefonStore(paths, storageKey);
            var os = new FakeOs(port, mode);
            var platform = new PhoneStartupLifecycleTests.Platform(paths);
            using var setup = new FirstRunSetupPhoneServices(paths, store, os, platform, localOnly: true);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(55));
            var result = await setup.ConnectAsync("bluetooth", async prompt =>
            {
                if (prompt.Kind == "select") return Phone;
                TestAssert.That(prompt.CanMarkOwn && prompt.Code.Length > 0, "No cryptographic confirmation prompt");
                Console.WriteLine("CODE " + prompt.Code);
                return await Console.In.ReadLineAsync(timeout.Token) == "ACCEPT" ? "accept" : null;
            }, timeout.Token);
            TestAssert.That(result.Authenticated && store.BluetoothAddress(result.DeviceId) == Phone && !store.PersonalSettings(result.DeviceId).OwnDevice,
                "First Bluetooth result is unauthenticated or auto-owned");
            TestAssert.That(os.Connections == (mode == "drop-finish" ? 3 : 2), "Unexpected Bluetooth handshake connection count");
            FirstRunSetupSelections? handoff = null;
            if (mode is "foreground-restart" or "background-restart")
            {
                var state = new FirstRunSetupState(paths); state.Begin();
                handoff = await FirstRunPhoneFinish.CompleteAsync(state,
                    new() { PhoneBackgroundServices = mode == "background-restart" ? ["bluetooth"] : [] }, false, setup, timeout.Token);
            }
            Console.WriteLine("RESULT " + JsonSerializer.Serialize(result));
            if (await Console.In.ReadLineAsync(timeout.Token) != "RECONNECT") throw new InvalidDataException();
            var previousConnections = os.Connections;
            if (handoff is not null)
            {
                setup.Dispose();
                var authenticated = false;
                resumed = new TelefonCoordinator(paths, (name, value) =>
                {
                    if (name == "App.telefonVerbindungStand") authenticated = (JsonSerializer.SerializeToNode(value)?["telefone"] as JsonArray)?.OfType<JsonObject>().Any(p =>
                        p["kennung"]?.GetValue<string>() == result.DeviceId && p["online"]?.GetValue<bool>() == true && p["state"]?.GetValue<string>() == "paired" && p["transport"]?.GetValue<string>() == "bluetooth") == true;
                    return Task.CompletedTask;
                }, dataStore: new TelefonStore(paths, storageKey), bluetoothClient: os, localOnly: true);
                await resumed.ResumeAsync();
                while (!authenticated || os.Connections <= previousConnections) { await resumed.ReportStatusAsync(); await Task.Delay(100, timeout.Token); }
                TestAssert.That((platform.Registration is not null) == (mode == "background-restart"), "Foreground handoff changed actual startup registration");
            }
            else
            {
                os.Last!.Dispose();
                while (os.Connections <= previousConnections || !(await setup.ConnectedAsync(timeout.Token)).Contains("bluetooth")) await Task.Delay(100, timeout.Token);
            }
            Console.WriteLine("RECONNECTED");
            await Console.In.ReadLineAsync(timeout.Token);
            setup.Dispose();
            TestAssert.That(store.Enabled == (mode is "background-restart" or "foreground-restart"), "Bluetooth connection consent did not persist correctly");
            return 0;
        }
        catch (Exception error) when (mode != "accept" && error is UnauthorizedAccessException or OperationCanceledException or InvalidDataException)
        {
            TestAssert.That(store is not null && store.LoadPeers().Count == 0 && !store.Enabled, "Rejected attempt persisted trust or startup");
            Console.WriteLine("REJECTED"); return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            resumed?.Dispose();
            for (var retry = 0; ; retry++)
            {
                try { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); break; }
                catch (IOException) when (retry < 20) { await Task.Delay(100); }
            }
        }
    }
}
