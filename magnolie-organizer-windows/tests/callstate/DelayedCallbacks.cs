using System.Reflection;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

static class Probe {
    static int checks;
    static object Field(object obj, string name) => obj.GetType().GetField(name, BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(obj)!;
    static void Set(object obj, string name, object value) => obj.GetType().GetField(name, BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(obj, value);
    static object? Invoke(object obj, string name, params object?[] args) => obj.GetType().GetMethod(name, BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(obj, args);
    static void Check(bool ok, string label) { if (!ok) throw new Exception(label); checks++; }
    static T Bind<T>(object owner, string name) where T : Delegate =>
        owner.GetType().GetMethod(name, BindingFlags.NonPublic | BindingFlags.Instance)!.CreateDelegate<T>(owner);
    static async Task Main() {
        var root = Path.Combine("/tmp/opencode", "v1-v4-data-" + Guid.NewGuid().ToString("N"));
        var paths = new WindowsPaths(root); paths.EnsureDirectories();
        try {
            // Actual native backend and pinned store; no listener constructor, no network.
            var backend = (KdeConnectDirectBackend)System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(typeof(KdeConnectDirectBackend));
            var store = new KdeConnectIdentityStore(paths, new Protector());
            Set(backend, "store", store);
            Set(backend, "activeGate", new object());
            var activeField = typeof(KdeConnectDirectBackend).GetField("active", BindingFlags.NonPublic | BindingFlags.Instance)!;
            var active = Activator.CreateInstance(activeField.FieldType)!; activeField.SetValue(backend, active);
            var connectionType = typeof(KdeConnectDirectBackend).GetNestedType("Connection", BindingFlags.NonPublic)!;
            using var key = ECDsa.Create();
            using var cert = new CertificateRequest("CN=Synthetic", key, HashAlgorithmName.SHA256).CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
            const string a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
            var capture = new CaptureTls();
            object Connection(string id) => Activator.CreateInstance(connectionType, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
                null, [new TcpClient(), capture, cert, new KdeConnectIdentity(id, "Dummy", 1716, [KdeConnectProtocol.SmsRequest], []), IPAddress.Loopback, 1716], null)!;
            store.Pin(new KdeConnectPeer(a, "Dummy A", KdeConnectProtocol.CertificatePin(cert), 1));
            var ca = Connection(a); active.GetType().GetMethod("TryAdd")!.Invoke(active, [a, ca]);
            Check(((System.Collections.ICollection)Invoke(backend, "UsableConnections")!).Count == 1, "A not usable");
            // UI click observed A. Dispatch is held while the paired phone is replaced by B.
            active.GetType().GetMethod("Clear")!.Invoke(active, null); store.Remove(a);
            store.Pin(new KdeConnectPeer(b, "Dummy B", KdeConnectProtocol.CertificatePin(cert), 1));
            active.GetType().GetMethod("TryAdd")!.Invoke(active, [b, Connection(b)]);
            var sms = (KdeConnectSms)System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(typeof(KdeConnectSms));
            Set(sms, "backend", new Lazy<KdeConnectDirectBackend>(() => backend));
            var journalPath = Path.Combine(root, "synthetic-submissions.json");
            Set(sms, "submissions", new SmsSubmissionJournal(journalPath));
            var pin = KdeConnectProtocol.CertificatePin(cert);
            var result = await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-A", a, pin);
            Check(!result.Ok && capture.Writes == 0, "replacement phone received SMS");
            var conflict = false;
            try { await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-A", b, pin); }
            catch (InvalidDataException) { conflict = true; }
            Check(conflict && capture.Writes == 0, "journal forgot expected device");
            result = await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-B", b, pin);
            Check(result.Ok && capture.Writes == 1, "bound positive send failed");
            Set(sms, "submissions", new SmsSubmissionJournal(journalPath));
            await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-B", b, pin);
            Check(capture.Writes == 1, "restart replay sent twice");
            await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-key", b, "wrong-key");
            await sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-missing", "", "");
            Check(capture.Writes == 1, "changed or absent identity sent");
            var durable = File.ReadAllText(journalPath);
            Check(!durable.Contains("Synthetic only") && !durable.Contains(pin) && !durable.Contains(b) && !durable.Contains("12025550123"), "journal retained payload");
            active.GetType().GetMethod("Clear")!.Invoke(active, null);
            var activating = sms.SendWithResultAsync("+12025550123", "Synthetic only", "US", "ref-activation", b, pin);
            Check(!activating.IsCompleted, "actual activation was not delayed");
            store.Remove(b); store.Pin(new KdeConnectPeer(a, "Dummy A", pin, 1));
            active.GetType().GetMethod("TryAdd")!.Invoke(active, [a, ca]);
            Check(!(await activating.WaitAsync(TimeSpan.FromSeconds(2))).Ok && capture.Writes == 1, "activation selected a replacement phone");
            Console.WriteLine("PASS V2 actual backend/journal: click/activation substitution, pin, missing, valid, restart, replay, digest-only");
            var smsCommand = new JsonObject { ["cmd"] = "kde_sms_senden", ["nummer"] = "+12025550123",
                ["text"] = "Synthetic only", ["land"] = "US", ["clientRef"] = "bridge-fixture",
                ["device_id"] = b, ["device_fingerprint"] = pin };
            using (var parsed = BridgeDispatcherContract.Parse(smsCommand.ToJsonString()))
                Check(parsed.RootElement.EnumerateObject().Count() == 7, "SMS bridge schema changed");
            foreach (var damage in new[] { "device_id", "device_fingerprint", "unexpected" }) {
                var invalid = smsCommand.DeepClone().AsObject();
                if (damage == "unexpected") invalid[damage] = true; else invalid.Remove(damage);
                var rejected = false;
                try { using var parsed = BridgeDispatcherContract.Parse(invalid.ToJsonString()); }
                catch (InvalidDataException) { rejected = true; }
                Check(rejected, "SMS bridge accepted missing identity or unknown field");
            }
            var statusCommand = new JsonObject { ["cmd"] = "telefon_status_anfordern", ["kennung"] = "synthetic-peer",
                ["requestId"] = Guid.NewGuid().ToString("D") };
            using (var parsed = BridgeDispatcherContract.Parse(statusCommand.ToJsonString()))
                Check(parsed.RootElement.EnumerateObject().Count() == 3, "status request bridge schema changed");
            statusCommand.Remove("requestId");
            var missingRequestRejected = false;
            try { using var parsed = BridgeDispatcherContract.Parse(statusCommand.ToJsonString()); }
            catch (InvalidDataException) { missingRequestRejected = true; }
            Check(missingRequestRejected, "status bridge accepted missing request identity");
            Console.WriteLine("PASS actual bridge schemas: kde_sms_senden requires device_id/device_fingerprint; telefon_status_anfordern requires requestId; missing/unknown fields rejected");

            var phoneStore = new TelefonStore(paths, new byte[32]);
            var peer = new TelefonPeer("11111111-1111-4111-8111-111111111111", "Dummy", new byte[32],
                StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(), StoredGrants: TelefonProtocolContract.DesktopGrants());
            phoneStore.SavePeers([peer]); phoneStore.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var form = new MainForm();
            TelefonCoordinator? coordinator = null;
            coordinator = new TelefonCoordinator(paths, (function, payload) => function == "App.telefonStatus" ? form.SendAsync("App.geraetStatus", payload,
                () => new { kennung = peer.Id, status = coordinator!.CurrentDeviceStatus((JsonObject)payload) }) : Task.CompletedTask, dataStore: phoneStore, localOnly: true);
            form.telefonCoordinator = coordinator;
            using var connection = new TelefonConnection(peer, new MemoryStream(), new byte[32], new byte[72], phoneStore,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi",
                authorizeCall: Bind<Func<TelefonPeer, string, JsonObject, string?>>(coordinator, "AuthorizeCall"),
                sendCall: Bind<Func<TelefonConnection, TelefonPeer, JsonObject, Action, bool>>(coordinator, "SendCall"));
            var online = (Dictionary<string, TelefonConnection>)Field(coordinator, "online"); online[peer.Id] = connection;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var requestId = Guid.NewGuid().ToString("D");
            var body = JsonNode.Parse("""
                {"model":"Dummy","manufacturer":"Dummy","os_name":"Android","os_version":"1",
                 "battery_percent":50,"charging":"unknown","sdk_int":34,"battery_temperature_deci_c":-1,
                 "power_source":"unknown","storage_total_bytes":-1,"storage_available_bytes":-1,
                 "memory_total_bytes":-1,"memory_available_bytes":-1,"uptime_ms":-1,
                 "network_transport":"none","network_validated":false,"network_metered":false,
                 "app_version":"synthetic","version":4,"identifiers":{
                   "phone_number":{"status":"not_shared","value":""},
                   "serial":{"status":"available","value":"SYNTHETIC-PRIVATE-SERIAL"},
                   "imei":{"status":"not_shared","value":""}}}
                """)!.AsObject();
            body["request_id"] = requestId; body["captured_ms"] = now;
            Check(phoneStore.SendIdentifierRequest(peer, TelefonCoordinator.DeviceStatusRequest(requestId, new JsonArray(4), true), now, () => { }), "request rejected");
            var message = new JsonObject { ["type"] = "message", ["kind"] = "device_status.report", ["body"] = body,
                ["message_id"] = Guid.NewGuid().ToString("D"), ["expires_ms"] = now + 60000 };
            var delivery = (Task)Invoke(coordinator, "HandleMessageAsync", peer, message, "wifi")!;
            Check(form.Queue.Count == 1, "UI callback not held");
            phoneStore.SetPersonalSettings(peer.Id, ownDevice: false);
            form.Drain(); await delivery;
            Check(!form.webView.CoreWebView2.Scripts.Any(s => s.Contains("SYNTHETIC-PRIVATE-SERIAL")), "revoked identifiers dispatched");
            Check(!File.ReadAllText(paths.TelefonStatusCache).Contains("SYNTHETIC-PRIVATE-SERIAL"), "durable identifier leak");
            foreach (var change in new[] { "valid", "reopen", "expired", "remote", "capability", "key", "disconnect", "new-request" }) {
                phoneStore.SavePeers([peer]); phoneStore.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
                online[peer.Id] = connection;
                requestId = Guid.NewGuid().ToString("D"); body["request_id"] = requestId;
                phoneStore.SendIdentifierRequest(peer, TelefonCoordinator.DeviceStatusRequest(requestId, new JsonArray(4), true), now, () => { });
                form.InvokeRequired = true; form.webView.CoreWebView2.Scripts.Clear();
                delivery = (Task)Invoke(coordinator, "HandleMessageAsync", peer, message, "wifi")!;
                Check(form.Queue.Count == 1, "status callback not queued");
                if (change == "reopen") coordinator.ClearDeviceIdentifiers(peer.Id);
                if (change == "expired") phoneStore.Cleanup(now + 120000);
                if (change == "remote") phoneStore.SetPersonalSettings(peer.Id, remoteOwnDevice: false);
                if (change == "capability") { var caps = peer.Capabilities.DeepClone().AsObject(); caps["device_status"]!["available"] = false; phoneStore.UpdatePeerProtocol(peer.Id, 2, caps, 0, null); }
                if (change == "key") phoneStore.SavePeers([peer with { PublicKey = Enumerable.Repeat((byte)1, 32).ToArray() }]);
                if (change == "disconnect") online.Clear();
                if (change == "new-request") phoneStore.SendIdentifierRequest(peer, TelefonCoordinator.DeviceStatusRequest(Guid.NewGuid().ToString("D"), new JsonArray(4), true), now, () => { });
                form.Drain(); await delivery;
                Check(form.webView.CoreWebView2.Scripts.Any(s => s.Contains("SYNTHETIC-PRIVATE-SERIAL")) == (change == "valid"), "identifier boundary " + change);
            }
            Console.WriteLine("PASS V3 actual coordinator/store + queued MainForm: valid/revoked/expired/reopen/key/disconnect/new-request/capability; no durable identifiers");
            phoneStore.SavePeers([peer]); phoneStore.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var newerRequest = Guid.NewGuid().ToString("D"); body["request_id"] = newerRequest;
            phoneStore.SendIdentifierRequest(peer, TelefonCoordinator.DeviceStatusRequest(newerRequest, new JsonArray(4), true), now, () => { });
            var oldReport = body.DeepClone().AsObject(); oldReport["request_id"] = Guid.NewGuid().ToString("D");
            Check(!phoneStore.AcceptIdentifiers(peer, oldReport, now, now + 60000), "old report was accepted");
            Check(phoneStore.AcceptIdentifiers(peer, body, now, now + 60000), "old report cancelled the newer identifier request");
            Check(!phoneStore.AcceptIdentifiers(peer, body, now, now + 60000), "duplicate report was accepted");
            Check(phoneStore.CurrentIdentifierStatus(peer, body).ContainsKey("identifiers"), "duplicate report erased the accepted newer result");
            Console.WriteLine("PASS V3 positive continuation: old/duplicate replies cannot cancel the newer request or result");
            foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                Check(File.ReadAllBytes(file).AsSpan().IndexOf(System.Text.Encoding.UTF8.GetBytes("SYNTHETIC-PRIVATE-SERIAL")) < 0, "synthetic identifier persisted");

            var ring = new JsonObject { ["device_id"] = peer.Id, ["call_ref"] = requestId, ["revision"] = 1L,
                ["direction"] = "incoming", ["state"] = "ringing", ["occurred_ms"] = now };
            var idle = ring.DeepClone().AsObject(); idle["state"] = "idle"; idle["revision"] = 2L;
            form.InvokeRequired = true;
            var callGrants = peer.Grants.DeepClone().AsObject();
            foreach (var name in new[] { "incoming_call_state", "answer_call", "end_call" }) {
                callGrants[name] = true; phoneStore.SetLocalGrant(name, true);
            }
            peer = peer with { Grants = callGrants };
            peer.Capabilities["end_call"]!["versions"] = new JsonArray(1, 2);
            phoneStore.SetLocalGrant("incoming_call_state", true);
            phoneStore.SavePeers([peer]); online[peer.Id] = connection;
            var calls = (Dictionary<string, JsonObject>)Field(coordinator, "calls"); calls[peer.Id] = idle;
            form.TrackIncomingCall(ring);
            form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id, callRef = requestId, revision = 1L }));
            form.TrackIncomingCall(idle);
            form.Drain();
            Check(form.callNotifications.Shown == 0, "stale ring presented");
            requestId = Guid.NewGuid().ToString("D"); ring["call_ref"] = requestId;
            calls[peer.Id] = ring;
            form.TrackIncomingCall(ring);
            // A running GUI must prefer its compact panel even with legacy system style.
            form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id, callRef = requestId, revision = 1L, stil = "system" }));
            Check(form.callNotifications.Shown == 0 && form.callAlert?.Visible == true, "own popup was bypassed");
            var buttons = form.callAlert!.Controls.OfType<FlowLayoutPanel>().Single().Controls.OfType<Button>().ToArray();
            Check(buttons.Length == 3 && !buttons[0].Enabled && !buttons[1].Enabled && buttons[2].Enabled,
                "unsupported controls must remain labeled and disabled");
            form.callAlert.Close(); form.shownCallAlert = "";
            Form.Unsupported = true;
            form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id, callRef = requestId, revision = 1L }));
            Check(form.callNotifications.Shown == 1, "valid ring hidden");
            var beforeOldEvent = form.callNotifications.Withdrawn;
            form.TrackIncomingCall(idle);  // Delayed old UI event; coordinator already owns the newer ring.
            Check(form.callNotifications.Withdrawn == beforeOldEvent, "old callback withdrew a newer current alert");
            // Hold the generation lock while an old callback waits, then deliver a
            // newer call reentrantly. The waiting callback must recheck authority.
            var newerRing = ring.DeepClone().AsObject(); newerRing["call_ref"] = Guid.NewGuid().ToString("D");
            var oldCallback = new Thread(() => form.TrackIncomingCall(ring)) { IsBackground = true };
            int afterNewerAlert;
            lock (form.incomingCallGate) {
                oldCallback.Start();
                Check(SpinWait.SpinUntil(() => (oldCallback.ThreadState & System.Threading.ThreadState.WaitSleepJoin) != 0, 2000), "old callback did not reach the generation lock");
                calls[peer.Id] = newerRing;
                form.TrackIncomingCall(newerRing);
                form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id,
                    callRef = newerRing["call_ref"]!.GetValue<string>(), revision = 1L }));
                afterNewerAlert = form.callNotifications.Withdrawn;
            }
            Check(oldCallback.Join(2000), "old callback did not finish");
            Check(form.callNotifications.Withdrawn == afterNewerAlert &&
                form.currentIncomingCall?["call_ref"]?.GetValue<string>() == newerRing["call_ref"]!.GetValue<string>(),
                "concurrent old callback withdrew or replaced a newer current alert");
            Console.WriteLine("PASS V4 generation lock: concurrent old callback cannot replace or withdraw the newer call");
            calls[peer.Id] = ring;
            foreach (var change in new[] { "idle", "grant", "capability", "disconnect", "expiry", "new-call" }) {
                calls[peer.Id] = ring; online[peer.Id] = connection; phoneStore.SavePeers([peer]); phoneStore.SetLocalGrant("incoming_call_state", true);
                form.shownCallAlert = ""; form.TrackIncomingCall(ring);
                form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id, callRef = requestId, revision = 1L, annehmen = true }));
                Check(form.callNotifications.Tokens.Count == 2, "real native call controls absent");
                var answerToken = form.callNotifications.Tokens["answer"];
                var withdrawn = form.callNotifications.Withdrawn;
                if (change == "idle") calls[peer.Id] = idle;
                if (change == "grant") phoneStore.SetLocalGrant("incoming_call_state", false);
                if (change == "capability") {
                    var caps = peer.Capabilities.DeepClone().AsObject(); caps["incoming_call_state"]!["available"] = false;
                    caps["incoming_call_state"]!["reason"] = "disabled";
                    await (Task)Invoke(coordinator, "HandleMessageAsync", peer,
                        new JsonObject { ["type"] = "message", ["kind"] = "capabilities.update", ["body"] = new JsonObject { ["revision"] = 2L, ["items"] = caps } }, "wifi")!;
                }
                if (change == "disconnect") online.Clear();
                if (change == "expiry") { calls[peer.Id] = ring.DeepClone().AsObject(); calls[peer.Id]["occurred_ms"] = now - 61000; }
                if (change == "new-call") { calls[peer.Id] = ring.DeepClone().AsObject(); calls[peer.Id]["call_ref"] = Guid.NewGuid().ToString("D"); }
                System.Windows.Forms.Timer.Fire();
                Check(form.callNotifications.Withdrawn > withdrawn, "caller not withdrawn: " + change);
                Check(!await coordinator.ExecuteCallActionAsync(answerToken), "stale action accepted: " + change);
            }
            calls[peer.Id] = ring; online[peer.Id] = connection; phoneStore.SavePeers([peer]); phoneStore.SetLocalGrant("incoming_call_state", true);
            var liveTokens = coordinator.CallActionTokens(peer.Id, requestId, 1);
            Check(await coordinator.ExecuteCallActionAsync(liveTokens["reject"]), "captured reject was not submitted");
            Check(!await coordinator.ExecuteCallActionAsync(liveTokens["reject"]) && !await coordinator.ExecuteCallActionAsync(liveTokens["answer"]), "double/sibling action accepted");
            Console.WriteLine("PASS V4 actual MainForm/coordinator: coalesced ring/idle, valid controls, grant/capability/disconnect/expiry/new-call withdrawal, captured reject, double/sibling rejection");
            online.Clear(); coordinator.Dispose();
            if (Environment.GetEnvironmentVariable("MAGNOLIE_CALL_TRACE_DIR") is { Length: > 0 } traceDirectory)
                await AndroidTrace(root, traceDirectory);
            Console.WriteLine($"PASS delayed callback probe: {checks} assertions; capture transports only");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
    }
    static async Task AndroidTrace(string root, string directory) {
        foreach (var direction in new[] { "incoming", "outgoing" }) foreach (var supported in new[] { true, false }) {
            var paths = new WindowsPaths(Path.Combine(root, "trace-" + direction + "-" + supported)); paths.EnsureDirectories();
            var store = new TelefonStore(paths, new byte[32]);
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            capabilities["end_call"]!["versions"] = new JsonArray(1, 2);
            var grants = TelefonProtocolContract.DesktopGrants();
            foreach (var name in new[] { "incoming_call_state", "answer_call", "end_call" }) {
                grants[name] = true; store.SetLocalGrant(name, true);
            }
            var peer = new TelefonPeer("11111111-1111-4111-8111-111111111111", "Synthetic Android", new byte[32],
                StoredCapabilities: capabilities, StoredGrants: grants);
            store.SavePeers([peer]);
            var delivered = new List<JsonObject>();
            using var coordinator = new TelefonCoordinator(paths, (function, payload) => {
                if (function == "App.telefonEingehenderAnruf") delivered.Add(JsonSerializer.SerializeToNode(payload)!.AsObject());
                return Task.CompletedTask;
            }, dataStore: store, localOnly: true);
            using var transport = new MemoryStream();
            using var connection = new TelefonConnection(peer, transport, new byte[32], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi",
                authorizeCall: Bind<Func<TelefonPeer, string, JsonObject, string?>>(coordinator, "AuthorizeCall"),
                sendCall: Bind<Func<TelefonConnection, TelefonPeer, JsonObject, Action, bool>>(coordinator, "SendCall"));
            var online = (Dictionary<string, TelefonConnection>)Field(coordinator, "online"); online[peer.Id] = connection;
            var form = new MainForm { telefonCoordinator = coordinator, InvokeRequired = false };
            Form.Unsupported = !supported;
            var trace = JsonNode.Parse(File.ReadAllText(Path.Combine(directory, direction + ".json")))!.AsArray();
            // Rebase the recorded clock, preserving every ID, direction, revision and interval.
            var delta = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - trace.Last()!["occurred_ms"]!.GetValue<long>();
            foreach (var item in trace.OfType<JsonObject>()) {
                var body = item.DeepClone().AsObject();
                foreach (var key in new[] { "occurred_ms", "started_ms", "offhook_ms", "ended_ms" })
                    if (body[key]!.GetValue<long>() > 0) body[key] = body[key]!.GetValue<long>() + delta;
                TelefonCallContract.Validate("incoming_call_state.event", body);
                await (Task)Invoke(coordinator, "HandleMessageAsync", peer, new JsonObject {
                    ["type"] = "message", ["kind"] = "incoming_call_state.event", ["body"] = body }, "wifi")!;
                var current = delivered.Last(); form.TrackIncomingCall(current);
                form.ShowIncomingCall(JsonSerializer.SerializeToElement(new { kennung = peer.Id,
                    callRef = body["call_ref"]!.GetValue<string>(), revision = body["revision"]!.GetValue<long>(), annehmen = true }));
                if (direction == "incoming" && body["state"]!.GetValue<string>() == "ringing") {
                    Check(supported ? form.callAlert?.Visible == true && form.callNotifications.Shown == 0 : form.callNotifications.Shown == 1,
                        "Android trace chose wrong presentation");
                    var tokens = supported ? coordinator.CallActionTokens(peer.Id, body["call_ref"]!.GetValue<string>(), 1) : form.callNotifications.Tokens;
                    Check(await coordinator.ExecuteCallActionAsync(tokens["answer"]), "Android trace answer not submitted");
                    // Decode the real authenticated frame emitted into the capture stream.
                    var bytes = transport.ToArray(); var length = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes);
                    var envelope = JsonNode.Parse(bytes.AsSpan(4, length))!.AsObject();
                    var cipher = Convert.FromBase64String(envelope["ciphertext"]!.GetValue<string>()); envelope.Remove("ciphertext");
                    var nonce = new byte[12]; System.Buffers.Binary.BinaryPrimitives.WriteInt64BigEndian(nonce.AsSpan(4), envelope["seq"]!.GetValue<long>());
                    var plain = new byte[cipher.Length - 16];
                    using (var aes = new AesGcm(new byte[32], 16)) aes.Decrypt(nonce, cipher.AsSpan(0, plain.Length), cipher.AsSpan(plain.Length), plain, TelefonCrypto.Canonical(envelope));
                    var command = JsonNode.Parse(plain)!.AsObject();
                    Check(command["kind"]!.GetValue<string>() == "answer_call.command" &&
                        command["body"]!["call_ref"]!.GetValue<string>() == body["call_ref"]!.GetValue<string>(), "Android trace command changed call ID");
                }
                if (direction == "outgoing") Check(form.callAlert is null && form.callNotifications.Shown == 0 && transport.Length == 0, "outgoing trace raised incoming notification");
            }
            Check(delivered.Select(value => value["state"]!.GetValue<string>()).SequenceEqual(new[] { "ringing", "offhook", "idle" }), "Android trace lost directed state");
            online.Clear();
        }
        Console.WriteLine("PASS Android recorded events -> Windows coordinator -> native popup/fallback -> authenticated captured answer, exact IDs");
    }
    sealed class Protector : IKdeConnectSecretProtector {
        public byte[] Protect(byte[] value) => value; public byte[] Unprotect(byte[] value) => value;
    }
    sealed class CaptureTls() : SslStream(new MemoryStream()) {
        internal int Writes;
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken token = default) { Writes++; return ValueTask.CompletedTask; }
        public override Task FlushAsync(CancellationToken token) => Task.CompletedTask;
    }
}
