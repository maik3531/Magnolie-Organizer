using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Reflection;

namespace MagnolieOrganizer.Windows.Tests;

internal static class BackgroundLifecycleTests
{
    internal static async Task RunAsync()
    {
        var compactSave = "{\"cmd\":\"speichern\",\"id\":1,\"text\":\"{}\"}";
        TestAssert.That(BridgeDispatcherContract.IsCompactSaveEnvelope(compactSave), "Compact save did not select the worker lane.");
        using (var parsedSave = BridgeDispatcherContract.Parse(compactSave))
            TestAssert.That(parsedSave.RootElement.GetProperty("cmd").GetString() == "speichern", "Save envelope validation changed.");
        TestAssert.That(!BridgeDispatcherContract.IsCompactSaveEnvelope("{\"cmd\":\"beenden\"}"), "UI command selected the save worker lane.");
        var duplicateCommand = "{\"cmd\":\"speichern\",\"cmd\":\"beenden\",\"id\":1,\"text\":\"{}\"}";
        TestAssert.That(BridgeDispatcherContract.IsCompactSaveEnvelope(duplicateCommand), "Routing hint unexpectedly replaced validation.");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(duplicateCommand), "Worker validation accepted a forged duplicate command.");
        const string raw = """{"einstellungen":{"regional":{"timeZone":"UTC"},"erinnerung":{"an":true}},"aufgaben":[{"id":"a","startDatum":"2026-09-09","startZeit":"10:00","faellig":"2026-09-09","faelligZeit":"11:00","erinnern":false,"alarme":[{"offsetMinuten":60,"aktiviert":true,"related":"END","aktion":"display"}]}]}""";
        using var data = JsonDocument.Parse(ReminderScheduler.SelectRuntimeData(raw));
        TestAssert.That(ReminderScheduler.DueTasks(data.RootElement, data.RootElement.GetProperty("einstellungen").GetProperty("erinnerung"),
            new DateTime(2026, 9, 9, 10, 0, 0, DateTimeKind.Utc)).Count == 1, "Task alarm lost in projection");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-background-regression-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var key = RandomNumberGenerator.GetBytes(32);
            using (var entered = new ManualResetEventSlim())
            using (var release = new ManualResetEventSlim())
            using (var scheduler = new ReminderScheduler(paths.ReminderState, _ => { entered.Set(); release.Wait(TimeSpan.FromSeconds(3)); }))
            {
                scheduler.UpdateData(raw);
                var check = Task.Run(() => scheduler.RunOnce(new DateTime(2026, 9, 9, 10, 0, 0, DateTimeKind.Utc)));
                TestAssert.That(entered.Wait(3000), "Reminder callback did not enter");
                var stopped = scheduler.ShutdownAsync();
                TestAssert.That(!stopped.IsCompleted, "Shutdown did not drain running reminder callback");
                release.Set(); await Task.WhenAll(check, stopped).WaitAsync(TimeSpan.FromSeconds(3));
            }
            var damaged = new WindowsPaths(Path.Combine(root, "optional"));
            Directory.CreateDirectory(damaged.KdeConnect);
            File.WriteAllText(damaged.KdeConnectIdentity, "invalid");
            File.WriteAllText(damaged.KdeConnectIdentityKey, "invalid");
            using (var optional = new KdeConnectSms(damaged))
                await TestAssert.ThrowsAsync<JsonException>(() => optional.DirectStatusAsync(), "Damaged optional integration unexpectedly initialized");
            using (var lease = ProfileLease.Acquire(root))
                TestAssert.Throws<IOException>(() => ProfileLease.Acquire(root), "Second profile owner admitted");
            using (ProfileLease.Acquire(root)) { }
            var journalPath = Path.Combine(root, "sms-journal.json");
            var sms = new SmsSubmissionJournal(journalPath);
            TestAssert.That(sms.Reserve("plan:fixture", "+49123", "test", "DE") is null, "Initial SMS reservation rejected");
            TestAssert.That(new SmsSubmissionJournal(journalPath).Reserve("plan:fixture", "+49123", "test", "DE") == "uncertain", "Crash-window SMS was retried");
            sms.Submitted("plan:fixture");
            TestAssert.That(new SmsSubmissionJournal(journalPath).Reserve("plan:fixture", "+49123", "test", "DE") == "submitted", "Submitted SMS was retried");
            TestAssert.Throws<InvalidDataException>(() => sms.Reserve("plan:fixture", "+49123", "changed", "DE"), "Conflicting submission accepted");
            var store = new TelefonStore(paths, key); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var peer = new TelefonPeer(Guid.NewGuid().ToString(), "fixture", TelefonCrypto.GenerateX25519().Public);
            var transcript = RandomNumberGenerator.GetBytes(32); var proof = RandomNumberGenerator.GetBytes(32);
            store.SavePending(peer, transcript, proof, proof, now + 60000);
            TestAssert.That(store.TryFinishPending(peer.Id, transcript, proof, now, out _, out var first), "First pairing finish failed");
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(reopened.TryFinishPending(transcript, proof, now + 1, out _, out var repeat) && JsonNode.DeepEquals(first, repeat), "Lost pairing finish response is not replayable");
            TestAssert.That(!reopened.TryFinishPending(transcript, new byte[32], now + 1, out _, out _), "Forged pairing receipt accepted");

            var run = Guid.NewGuid().ToString(); var personal = new PersonalSyncStore(store);
            var request = new JsonObject { ["format"] = 1, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
            personal.RememberRun(peer.Id, request, now);
            var body = new JsonObject { ["format"] = 1, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString(), ["reply"] = false,
                ["sequence"] = 0, ["last"] = true, ["records"] = new JsonArray() };
            var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = "personal_sync.batch", ["message_id"] = Guid.NewGuid().ToString(), ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
            var staged = personal.StageBatch(peer.Id, message, "wifi", now)!;
            store.Enqueue(peer.Id, "personal_sync.batch", body, 60000, now);
            store.BeginRestore();
            TestAssert.That(reopened.RestoreFenced && reopened.Due(peer.Id, now).Count == 0 &&
                !personal.CommitBatch(peer.Id, staged.PendingMessageId, staged.CommitToken, now, out _), "Restore barrier accepted old work");
            reopened.CompleteRestore(Guid.NewGuid().ToString());
            TestAssert.That(store.Due(peer.Id, now).Count == 0 && !personal.CommitBatch(peer.Id, staged.PendingMessageId, staged.CommitToken, now, out _), "Restore retained old queue or token");
            TestAssert.That(store.LoadPeers().Single().Id == peer.Id, "Restore destroyed pairing");
            TestAssert.That(Directory.GetFiles(paths.Telefon, "restore-quarantine-*.db").Length == 1, "Restore has no quarantine");

            var radio = new Radio();
            using (var phone = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, bluetoothRadio: radio, dataStore: store))
            { await phone.RadioSwitch.RequestAsync("anruf/fixture"); await phone.ShutdownAsync(); }
            TestAssert.That(!radio.On, "Shutdown left owned radio on");
            await ReceiptsAsync(Path.Combine(root, "receipts"));
            await HttpBodyAsync(false); await HttpBodyAsync(true);
            await CloudRecurrenceAsync(Path.Combine(root, "cloud"));
            await TreeLifecycleAsync(Path.Combine(root, "lifecycle"));
            Wiring();
            if (OperatingSystem.IsWindows())
            {
                var native = new WindowsPaths(Path.Combine(root, "native"));
                var cloud = new CloudBackupService(native.CloudBackupPassword); cloud.StorePassword("synthetic-only");
                var backup = cloud.CreateVerified(new JsonObject(), new(true, "daily", 2, "", Path.Combine(root, "backups")), "test");
                TestAssert.That(File.Exists(backup), "Native DPAPI backup missing");
                var identity = new TelefonStore(native).LoadOrCreateIdentity();
                TestAssert.That(new TelefonStore(native).LoadOrCreateIdentity().Id == identity.Id, "Native DPAPI identity changed");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        Console.WriteLine("BACKGROUND: task alarms, SMS crash journal, profile lease, pairing receipt, restore barrier, owned radio, signed Baum receipts, HTTP body deadline/disposal passed");
    }

    private sealed class Radio : IBluetoothRadio
    { internal bool On; public Task<bool?> IsOnAsync() => Task.FromResult<bool?>(On); public Task<bool> SetAsync(bool on) { On = on; return Task.FromResult(true); } }

    private static void Wiring()
    {
        var root = TestSource.Root("MagnolieOrganizer.Windows.csproj");
        var form = File.ReadAllText(Path.Combine(root, "MainForm.cs"));
        var bridge = File.ReadAllText(Path.Combine(root, "BridgeDispatcher.cs"));
        var background = File.ReadAllText(Path.Combine(root, "BridgeDispatcher.Background.cs"));
        var setup = File.ReadAllText(Path.Combine(root, "Program.cs"));
        var installer = File.ReadAllText(Path.Combine(root, "installer", "MagnolieOrganizer.nsi"));
        TestAssert.That(form.Contains("traySettings.Aktiv && traySettings.Autostart,") && !form.Contains("reminderAutostart || traySettings"), "Reminder bypassed startup consent");
        TestAssert.That(form.Contains("eventArgs.CloseReason == CloseReason.UserClosing") && form.Contains("CloseReason.WindowsShutDown"), "Close reasons are conflated");
        TestAssert.That(bridge.Contains("var autostartError = form.SetReminderAutostart(active)") && bridge.Contains("fehler = autostartError"), "Autostart error discarded");
        TestAssert.That(background.Contains("predecessor.WaitAsync") && background.Contains("await bridgeCommands.WaitAsync") && bridge.Contains("_ = QueueBackground(ResumeOptionalServicesAsync)"), "Unlock replay blocks its commit lane");
        TestAssert.That(bridge.Split("await FencePhoneRestoreAsync();").Length == 4, "Not all restore routes fence phone work");
        TestAssert.That(!bridge.Contains("kdeConnectSms = new KdeConnectSms(paths)") && !bridge.Contains("telefon = new TelefonCoordinator"), "Optional integration still owns app startup");
        TestAssert.That(setup.Contains("ProfileLease.Acquire(paths.Root)") && installer.Contains("DeleteRegValue HKCU \"Software\\Microsoft\\Windows\\CurrentVersion\\Run\" \"Magnolie Organizer\""), "Profile ownership/uninstall startup cleanup missing");
        TestAssert.That(installer.Contains("MagnolieOrganizer.Windows.Exit") && form.Contains("NativeMethods.ExitMessage"), "Installer cannot request terminal saved exit");
    }

    private static async Task CloudRecurrenceAsync(string root)
    {
        var now = DateTimeOffset.UtcNow; var calls = 0; var successes = 0;
        var data = new JsonObject { ["text"] = "saved", ["einstellungen"] = new JsonObject { ["allgemein"] = new JsonObject {
            ["sicherungsordner"] = root, ["cloudSicherung"] = new JsonObject { ["aktiv"] = true, ["intervall"] = "daily" } } } };
        var saved = data.ToJsonString();
        CloudBackupWorker New() => new(new CloudBackupService(Path.Combine(root, "secret")), Path.Combine(root, "state.json"), "test",
            (_, payload) => { if (JsonSerializer.SerializeToNode(payload)?["status"]?.GetValue<string>() == "success") Interlocked.Increment(ref successes); return Task.CompletedTask; },
            () => now, TimeSpan.FromMilliseconds(20), (snapshot, _, _) => {
                TestAssert.That(snapshot["text"]!.GetValue<string>() == "saved", "Backup did not use immutable saved snapshot");
                Interlocked.Increment(ref calls); return "fixture";
            }, () => true);
        await using (var worker = New())
        {
            worker.UpdateSnapshot(saved); data["text"] = "unsaved";
            await Until(() => Volatile.Read(ref successes) == 1);
            now = now.AddDays(1).AddSeconds(1);
            await Until(() => Volatile.Read(ref successes) == 2);
        }
        await using (var restarted = New()) { restarted.UpdateSnapshot(saved); await Task.Delay(100); }
        TestAssert.That(calls == 2, "Periodic backup missing or restart repeated successful backup");
    }
    private static async Task Until(Func<bool> condition)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while (!condition()) await Task.Delay(10, timeout.Token);
    }
    private static async Task TreeLifecycleAsync(string root)
    {
        var paths = new WindowsPaths(root); var storage = new MagnolienbaumStore(paths); var state = storage.LoadOrCreate(); int port;
        using (var reserve = new TcpListener(IPAddress.Loopback, 0)) { reserve.Start(); port = ((IPEndPoint)reserve.LocalEndpoint).Port; }
        state["port"] = port; storage.SaveState(state);
        using var tree = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        await tree.SwitchAsync(true, "");
        using var socket = new TcpClient(); await socket.ConnectAsync(IPAddress.Loopback, port);
        await socket.GetStream().WriteAsync("POST / HTTP/1.1\r\n"u8.ToArray());
        await tree.StopAsync().WaitAsync(TimeSpan.FromSeconds(3));
        await tree.StartAsync(); await tree.ShutdownAsync().WaitAsync(TimeSpan.FromSeconds(3));
        using var listener = new TcpListener(IPAddress.Any, port); listener.Start();
    }

    private static async Task HttpBodyAsync(bool dispose)
    {
        using var server = new TcpListener(IPAddress.Loopback, 0); server.Start();
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serving = Task.Run(async () =>
        {
            try
            {
                using var socket = await server.AcceptTcpClientAsync(stop.Token);
                var stream = socket.GetStream(); await stream.ReadAsync(new byte[8192], stop.Token);
                await stream.WriteAsync("HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{"u8.ToArray(), stop.Token);
                await Task.Delay(Timeout.Infinite, stop.Token);
            }
            catch (OperationCanceledException) { }
        });
        try
        {
            using var client = DeadlineHttp.Create(TimeSpan.FromMilliseconds(dispose ? 4000 : 300), new SocketsHttpHandler { UseProxy = false });
            using var response = await client.GetAsync($"http://127.0.0.1:{((IPEndPoint)server.LocalEndpoint).Port}", HttpCompletionOption.ResponseHeadersRead);
            var read = response.Content.ReadAsStringAsync();
            if (dispose) client.Dispose();
            await TestAssert.ThrowsAsync<OperationCanceledException>(() => read.WaitAsync(TimeSpan.FromSeconds(2)), "Body outlived timeout/disposal");
        }
        finally { stop.Cancel(); await serving; }
    }

    private static async Task ReceiptsAsync(string root)
    {
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "resources", "baum-1-receipt-v1-vectors.json")))!.AsObject();
        var key = Convert.FromHexString(vector["partnerKeyHex"]!.GetValue<string>());
        var envelope = vector["envelope"]!.AsObject(); var receipt = BaumReceipt.Create(key, "alpha", "beta", envelope);
        TestAssert.That(JsonNode.DeepEquals(receipt, vector["receipt"]), "Portable receipt MAC differs");
        TestAssert.That(BaumReceipt.Verify(key, "alpha", "beta", envelope, receipt), "Valid receipt rejected");
        TestAssert.That(!BaumReceipt.Verify(new byte[32], "alpha", "beta", envelope, receipt) && !BaumReceipt.Verify(key, "beta", "alpha", envelope, receipt), "Wrong key/direction accepted");
        var changed = envelope.DeepClone().AsObject(); changed["zaehler"] = 2;
        TestAssert.That(!BaumReceipt.Verify(key, "alpha", "beta", changed, receipt) && !BaumReceipt.Verify(key, "alpha", "beta", envelope, new JsonObject()), "Wrong envelope/unsigned receipt accepted");
        var extra = receipt.DeepClone().AsObject(); extra["extra"] = true;
        TestAssert.That(!BaumReceipt.Verify(key, "alpha", "beta", envelope, extra), "Extra receipt field accepted");
        var paths = new WindowsPaths(root); var storage = new MagnolienbaumStore(paths); var state = storage.LoadOrCreate();
        var peerKeys = MagnolienbaumCrypto.GenerateX25519(); state["an"] = true;
        state["partner"]!.AsArray().Add(new JsonObject { ["kennung"] = "alpha", ["name"] = "fixture", ["oeffentlich"] = Convert.ToBase64String(peerKeys.Public), ["bestaetigt"] = true, ["adresse"] = "127.0.0.1", ["port"] = 8737 });
        storage.SaveState(state);
        using var tree = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        var shared = MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(state["geheim"]!.GetValue<string>()), peerKeys.Public, state["kennung"]!.GetValue<string>(), "alpha");
        var incoming = MagnolienbaumCrypto.EncryptBaum1(shared, "alpha", 1, new JsonObject { ["art"] = "notiz", ["text"] = "fixture" });
        var accepted = tree.HandleProtocolRequest("/magnolie/v1/nachricht", incoming, "127.0.0.1");
        TestAssert.That(accepted.Status == 200 && BaumReceipt.Verify(shared, "alpha", state["kennung"]!.GetValue<string>(), incoming, accepted.Body), "Receiver did not authenticate durable receipt");
        TestAssert.That(JsonNode.DeepEquals(accepted.Body, tree.HandleProtocolRequest("/magnolie/v1/nachricht", incoming, "127.0.0.1").Body) && storage.LoadInbox().Count == 1, "Receipt replay duplicated effect");
        using var reopened = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        TestAssert.That(JsonNode.DeepEquals(accepted.Body, reopened.HandleProtocolRequest("/magnolie/v1/nachricht", incoming, "127.0.0.1").Body), "Receipt did not survive restart");
        var field = typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!;
        ((HttpClient)field.GetValue(tree)!).Dispose(); var handler = new ReceiptHandler(shared, state["kennung"]!.GetValue<string>());
        field.SetValue(tree, new HttpClient(handler));
        await tree.SendAsync("alpha", "notiz", new JsonObject { ["text"] = "outgoing" });
        TestAssert.That(storage.LoadOutbox().Count == 0, "Valid receipt did not release outbox");
        handler.Sign = false;
        await tree.SendAsync("alpha", "notiz", new JsonObject { ["text"] = "uncertain" });
        TestAssert.That(storage.LoadOutbox().Single()!["unsicher"]!.GetValue<bool>(), "Unsigned receipt discarded queue");
        var calls = handler.Calls; await tree.SendAsync("alpha", "notiz", new JsonObject { ["text"] = "next" });
        TestAssert.That(handler.Calls == calls, "Uncertain head of queue was retried or overtaken");
    }
    private sealed class ReceiptHandler(byte[] key, string own) : HttpMessageHandler
    {
        internal bool Sign = true; internal int Calls;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Calls++; var envelope = JsonNode.Parse(await request.Content!.ReadAsStringAsync(token))!.AsObject();
            return new(HttpStatusCode.OK) { Content = new StringContent((Sign ? BaumReceipt.Create(key, own, "alpha", envelope) : new JsonObject()).ToJsonString()) };
        }
    }
}
