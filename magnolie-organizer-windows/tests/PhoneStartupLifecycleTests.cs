using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneStartupLifecycleTests
{
    internal sealed class Platform(WindowsPaths paths) : IPhoneStartupPlatform
    {
        internal object? Registration;
        internal int Writes;
        internal bool FailEnable;
        private readonly TraySettingsService tray = new(paths.TraySettings);
        public TraySettings Load() => tray.Load();
        public void Save(TraySettings value) { Writes++; tray.Save(value); }
        public object? CaptureAutostart() => Registration;
        public void EnableAutostart()
        {
            Writes++; Registration = TraySettingsService.AutostartCommand("C:\\owned-fixture.exe");
            if (FailEnable) throw new IOException("Injected registry-adapter failure");
        }
        public void RestoreAutostart(object? value) { Writes++; Registration = value; }
    }
    private sealed class PhoneServices(TelefonStore store, Platform platform, IReadOnlyList<string> live) : IFirstRunSetupPhoneServices
    {
        internal Exception? StatusFailure;
        public IReadOnlyList<SetupPhoneCapability> Capabilities => [new("wifi", true, true), new("bluetooth", true, true), new("kdeconnect", true, true)];
        public Task<SetupPhoneResult> ConnectAsync(string transport, Func<SetupPhonePrompt, Task<string?>> prompt, CancellationToken token) => throw new NotSupportedException();
        public Task<IReadOnlyList<string>> ConnectedAsync(CancellationToken token) => StatusFailure is null
            ? Task.FromResult(live) : Task.FromException<IReadOnlyList<string>>(StatusFailure);
        public Task CommitStartupAsync(IReadOnlyList<string> transports, CancellationToken token)
        { token.ThrowIfCancellationRequested(); FirstRunPhoneStartup.Apply(transports, store, platform,
            connectedPhone: live.Any(t => t is "wifi" or "bluetooth")); return Task.CompletedTask; }
    }

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-phone-startup-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            foreach (var selected in new[] { Array.Empty<string>(), new[] { "wifi" }, new[] { "bluetooth" }, new[] { "wifi", "bluetooth" }, new[] { "kdeconnect" } })
            {
                var paths = new WindowsPaths(Path.Combine(root, Guid.NewGuid().ToString("N")));
                paths.EnsureDirectories();
                var key = RandomNumberGenerator.GetBytes(32);
                var store = new TelefonStore(paths, key);
                var peer = new TelefonPeer(Guid.NewGuid().ToString(), "Friendly phone", RandomNumberGenerator.GetBytes(32));
                store.SavePeers([peer]);
                store.SetBluetoothAddress(peer.Id, "AA:BB:CC:DD:EE:01");
                var platform = new Platform(paths);
                var state = new FirstRunSetupState(paths); state.Begin();
                var phones = new PhoneServices(store, platform, ["wifi", "bluetooth", "kdeconnect"]);
                var result = await FirstRunPhoneFinish.CompleteAsync(state, new() { PhoneBackgroundServices = selected.ToList() }, false, phones, CancellationToken.None);
                TestAssert.That(state.Classify() == FirstRunSetupClassification.Complete, "Finish marker not persisted");
                var tray = new TraySettingsService(paths.TraySettings).Load();
                TestAssert.That(tray.Autostart == (selected.Length > 0) && (platform.Registration is not null) == (selected.Length > 0), "Startup choice did not reach settings and registry adapter");
                TestAssert.That(store.Enabled, "Finish did not persist the verified connection preference");
                var reopened = new TelefonStore(paths, key);
                using var restarted = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: reopened, localOnly: true);
                TestAssert.That(restarted.Enabled, "App restart requires a second Connect");
                await restarted.ResumeAsync();
                TestAssert.That(restarted.IsRunning, "Persisted connection did not start after restart");
                var savedPeer = reopened.LoadPeers().Single();
                TestAssert.That(savedPeer.Id == peer.Id && savedPeer.PublicKey.SequenceEqual(peer.PublicKey) &&
                    reopened.BluetoothAddress(peer.Id) == "AA:BB:CC:DD:EE:01", "Finish changed trusted identity or Bluetooth binding");
                new AtomicStore().WriteRecoverableJson(paths.TelefonSettings,
                    "{\"enabled\":true,\"bluetooth\":{\"" + peer.Id + "\":{\"enabled\":false,\"address\":\"\"}}}");
                TestAssert.That(reopened.BluetoothAddress(peer.Id) == "", "Settings off did not stop Bluetooth reconnect");
                TestAssert.That(reopened.LoadPeers().Single().PublicKey.SequenceEqual(peer.PublicKey), "Settings off removed pairing");
                TestAssert.That(result.PhoneBackgroundServices.SequenceEqual(selected), "Chosen service IDs changed");
                TestAssert.That(result.ForegroundPhoneTransports.Count == 2 && !File.ReadAllText(paths.FirstRunSetup).Contains("ForegroundPhoneTransports"), "Foreground intent leaked into persistent startup consent");
                if (selected.Length == 0) TestAssert.That(platform.Writes == 0, "Default-off Finish mutated startup");
            }
            var failurePaths = new WindowsPaths(Path.Combine(root, "failure")); failurePaths.EnsureDirectories();
            var failureStore = new TelefonStore(failurePaths, RandomNumberGenerator.GetBytes(32));
            var previous = new TraySettings(Aktiv: true, SchliessenInTray: false, Zaehler: true);
            var failurePlatform = new Platform(failurePaths) { Registration = "original reminder command", FailEnable = true };
            failurePlatform.Save(previous);
            var failureState = new FirstRunSetupState(failurePaths); failureState.Begin();
            var unavailable = new PhoneServices(failureStore, failurePlatform, [])
                { StatusFailure = new IOException("Synthetic unavailable phone setup") };
            var beforeOptional = failurePlatform.Writes;
            var withoutPhone = await FirstRunPhoneFinish.CompleteAsync(failureState, new(), false, unavailable, CancellationToken.None);
            TestAssert.That(failureState.Classify() == FirstRunSetupClassification.Complete &&
                withoutPhone.ForegroundPhoneTransports.Count == 0 && failurePlatform.Writes == beforeOptional,
                "An optional failed phone connection blocked Finish or changed startup settings");
            failureState.Begin();
            try { await FirstRunPhoneFinish.CompleteAsync(failureState, new() { PhoneBackgroundServices = ["wifi"] }, false, unavailable, CancellationToken.None); throw new Exception("Explicit startup failure ignored"); }
            catch (IOException) { }
            TestAssert.That(failureState.Classify() == FirstRunSetupClassification.Pending && failurePlatform.Writes == beforeOptional,
                "Explicitly requested unavailable service was silently accepted");
            var service = new PhoneServices(failureStore, failurePlatform, ["wifi"]);
            try { await FirstRunPhoneFinish.CompleteAsync(failureState, new() { PhoneBackgroundServices = ["wifi"] }, false, service, CancellationToken.None); throw new Exception("Failure injection ignored"); }
            catch (IOException) { }
            TestAssert.That(failureState.Classify() == FirstRunSetupClassification.Pending && !failureStore.Enabled && Equals(failurePlatform.Registration, "original reminder command") && failurePlatform.Load() == previous, "Failed Finish did not restore exact prior startup state");
            var writes = failurePlatform.Writes;
            await FirstRunPhoneFinish.CompleteAsync(failureState, new() { PhoneBackgroundServices = ["wifi"], Autostart = true }, true, service, CancellationToken.None);
            TestAssert.That(failurePlatform.Writes == writes && !failureStore.Enabled, "Skip enabled startup");
            failureState.Begin();
            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
            try { await FirstRunPhoneFinish.CompleteAsync(failureState, new() { PhoneBackgroundServices = ["wifi"] }, false, service, cancelled.Token); throw new Exception("Cancellation ignored"); }
            catch (OperationCanceledException) { }
            TestAssert.That(failurePlatform.Writes == writes && failureState.Classify() == FirstRunSetupClassification.Pending, "Cancel changed startup state");
            var preserved = previous with { Autostart = true, StartMinimiert = true };
            failurePlatform.FailEnable = false; failurePlatform.Save(preserved);
            FirstRunPhoneStartup.Apply(["kdeconnect"], failureStore, failurePlatform);
            TestAssert.That(Equals(failurePlatform.Registration, "original reminder command") && !failureStore.Enabled && !failurePlatform.Load().SchliessenInTray, "Existing registration or unrelated choices were replaced");
            using var foreground = new TelefonCoordinator(failurePaths, (_, _) => Task.CompletedTask, dataStore: failureStore, foregroundEnabled: true, localOnly: true);
            await foreground.ResumeAsync();
            TestAssert.That(foreground.IsRunning && !failureStore.Enabled, "Foreground runtime was not transient");
            var listenerField = typeof(TelefonCoordinator).GetField("listener", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
            var listener = listenerField.GetValue(foreground);
            await foreground.ResumeAsync();
            TestAssert.That(ReferenceEquals(listener, listenerField.GetValue(foreground)), "Repeated initialization created another owner");
            foreground.Dispose();
            await foreground.ResumeAsync();
            TestAssert.That(!foreground.IsRunning && !failureStore.Enabled, "Disposed setup owner restarted");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
    }
}
