using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Net.Sockets;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonInvitationTests
{
    // Interactive fixture: tests must compare Android's displayed code before
    // sending ACCEPT. It never discovers/selects an arbitrary real phone.
    internal static async Task<int> HostAsync(string target)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-phone-invite-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, RandomNumberGenerator.GetBytes(32));
            using var setup = new FirstRunSetupPhoneServices(paths, store);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(40));
            var result = await setup.ConnectAsync("wifi", async prompt =>
            {
                if (prompt.Kind == "select")
                {
                    if (!prompt.Devices.Any(d => d.Uid == target)) throw new InvalidOperationException("Fixture phone not discovered");
                    Console.Error.WriteLine("Fixture phone discovered and explicitly selected");
                    return target;
                }
                if (prompt.Devices.Single().Uid != target || prompt.Code.Length == 0) throw new InvalidDataException();
                Console.WriteLine("CODE " + prompt.Code);
                var decision = await Console.In.ReadLineAsync(timeout.Token);
                return decision == "ACCEPT" ? "accept" : null;
            }, timeout.Token);
            if (!result.Authenticated || result.DeviceId != target || store.PersonalSettings(target).OwnDevice)
                throw new InvalidDataException("Unauthenticated or auto-owned fixture phone");
            Console.WriteLine("RESULT " + JsonSerializer.Serialize(result));
            await Console.In.ReadLineAsync(timeout.Token);
            setup.Dispose();
            TestAssert.That(!store.Enabled, "Setup enabled background operation without consent");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
        finally
        {
            for (var retry = 0; ; retry++)
            {
                try { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); break; }
                catch (IOException) when (retry < 20) { await Task.Delay(100); }
            }
        }
    }

    internal static Task RunAsync()
    {
        foreach (var address in new[] { "127.0.0.1", "0.0.0.0", "8.8.8.8", "224.0.0.251", "::1", "::ffff:127.0.0.1" })
            TestAssert.That(!TelefonInvitation.Local(IPAddress.Parse(address)), "Unsafe invitation address accepted");
        var records = new Dictionary<(IPAddress, string), (int, Dictionary<string, string>?)>();
        for (var i = 0; i < 512; i++)
        {
            var packet = RandomNumberGenerator.GetBytes(i % 256);
            try { TelefonInvitation.ReadAnnouncement(packet, IPAddress.Parse("192.168.1.2"), records); }
            catch (Exception error) when (error is InvalidDataException or ArgumentException or IndexOutOfRangeException) { }
            TestAssert.That(records.Count <= 64, "Unbounded discovery cache");
        }
        return Environment.GetEnvironmentVariable("MAGNOLIE_WLAN_INTEGRATION") == "1" ? ScopedPairingAsync() : Task.CompletedTask;
    }

    private static async Task ScopedPairingAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-phone-scope-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, RandomNumberGenerator.GetBytes(32));
            var prompts = 0;
            using var coordinator = new TelefonCoordinator(paths, (name, value) =>
            {
                if (name == "App.telefonPaarung" && JsonSerializer.SerializeToNode(value)?["code"]?.GetValue<string>() is { Length: > 0 }) prompts++;
                return Task.CompletedTask;
            }, dataStore: store);
            await coordinator.SwitchAsync(true);
            TestAssert.That(coordinator.IsRunning, "Fixture port 8741 is unavailable");
            var address = TelefonMdnsPublisher.MulticastInterfaces().Select(x => x.Address).First(TelefonInvitation.Local);
            var target = Guid.NewGuid().ToString();
            foreach (var attack in new[] { "wrong-target", "wrong-source", "expired", "cancelled", "replayed-token" })
            {
                var offer = coordinator.OpenSetupPairing(target, attack == "wrong-source" ? IPAddress.Parse("192.168.99.99") : address);
                var token = offer["token"]!.GetValue<string>();
                if (attack == "expired") typeof(TelefonCoordinator).GetField("pairingUntil", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.SetValue(coordinator, 0L);
                if (attack is "cancelled" or "replayed-token") coordinator.EndSetupPairing(token);
                if (attack == "replayed-token") offer = coordinator.OpenSetupPairing(target, address);
                try
                {
                    using var client = new TcpClient();
                    await client.ConnectAsync(address, TelefonCoordinator.Port);
                    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                    var key = TelefonCrypto.GenerateX25519();
                    await TelefonCoordinator.WriteFrameAsync(client.GetStream(), new JsonObject {
                        ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_init", ["role"] = "phone",
                        ["pairing_token"] = token, ["device_id"] = attack == "wrong-target" ? Guid.NewGuid().ToString() : target,
                        ["display_name"] = "Fixture", ["static_public"] = Convert.ToBase64String(key.Public),
                        ["ephemeral_public"] = Convert.ToBase64String(key.Public), ["nonce"] = Convert.ToBase64String(new byte[32]),
                        ["versions"] = new JsonArray(1)
                    }, timeout.Token);
                    CryptographicOperations.ZeroMemory(key.Private);
                    TestAssert.That(await client.GetStream().ReadAsync(new byte[1], timeout.Token) == 0, "Unauthenticated setup attack accepted: " + attack);
                    TestAssert.That(prompts == 0 && store.LoadPeers().Count == 0, "Attack caused a prompt or persisted trust");
                }
                finally { coordinator.EndSetupPairing(offer["token"]!.GetValue<string>()); }
            }
            store.SavePeers([new TelefonPeer(target, "Pinned fixture", TelefonCrypto.GenerateX25519().Public)]);
            TestAssert.Throws<InvalidOperationException>(() => coordinator.OpenSetupPairing(Guid.NewGuid().ToString(), address), "Existing peer replaced");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
    }
}
