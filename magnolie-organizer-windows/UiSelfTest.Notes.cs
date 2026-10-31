using System.Buffers.Binary;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Web.WebView2.Core;

namespace MagnolieOrganizer.Windows;

internal static partial class UiSelfTest
{
    // Real WebView/dispatcher/native SaveACKs, only the existing private UI-test profile.
    private static async Task TestNotesRoundTripAsync(MainForm form, CoreWebView2 web, WindowsPaths paths)
    {
        Test(Path.GetFileName(paths.Root).StartsWith("magnolie-ui-self-test-", StringComparison.Ordinal), "Private UI profile required.");
        var flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var dispatcher = (BridgeDispatcher)typeof(MainForm).GetField("dispatcher", flags)!.GetValue(form)!;
        var coordinator = (TelefonCoordinator)typeof(BridgeDispatcher).GetProperty("telefon", flags)!.GetValue(dispatcher)!;
        var store = (TelefonStore)typeof(TelefonCoordinator).GetField("store", flags)!.GetValue(coordinator)!;
        var phoneId = Guid.NewGuid().ToString("D");
        const string phoneActor = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
        const string desktopActor = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
        const string noteId = "native-ui-note";
        var capabilities = TelefonProtocolContract.DesktopCapabilities();
        var grants = TelefonProtocolContract.DesktopGrants(); grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
        var peer = new TelefonPeer(phoneId, "Synthetic UI phone", Enumerable.Repeat((byte)112, 32).ToArray());
        store.SavePeers([peer]); store.SetPersonalSettings(phoneId, ownDevice: true, remoteOwnDevice: true, autoWifi: false);
        store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
        var identity = store.LoadOrCreateIdentity(); var actor = identity.Id; CryptographicOperations.ZeroMemory(identity.PrivateKey);
        var initial = SharedSyncSettings.Effective(SharedSyncSettings.Create(actor)); initial["content_mode"] = "two_way"; initial["auto_mode"] = "manual";
        store.InitializeSharedSettings(phoneId, peer.PublicKey, initial);
        var receive = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", flags)!;
        using var wire = new MemoryStream();
        using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store,
            (source, message) => (Task<TelefonAck?>)receive.Invoke(coordinator, [source, message, "wifi"])!, CancellationToken.None, "wifi");
        var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", flags)!.GetValue(coordinator)!;
        online[phoneId] = connection;
        JsonObject Message(string kind, JsonObject body)
        {
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body.DeepClone() };
        }
        try
        {
            await connection.HandlePlainAsync(Message("capabilities.update", capabilities));
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = grants }));
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            var remote = SharedSyncSettings.Merge(SharedSyncSettings.Create(phoneId, initial), store.SharedSettings(phoneId, peer.PublicKey)!, phoneId, actor);
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, remote));
            Test(connection.SharedSettingsReady, "Synthetic native shared settings did not reach agreement.");
            foreach (var scoped in new[] { false, true })
            {
                if (scoped)
                {
                    store.ChangeSharedSetting(phoneId, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
                    await connection.SendSharedSettingsAsync();
                    await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, store.SharedSettings(phoneId, peer.PublicKey)!));
                    Test(connection.SharedSettingsReady, "Native scoped preference did not reach agreement.");
                }
                var manifest = PhoneContentScope.Create([noteId], []);
                if (scoped) foreach (var part in PhoneContentScope.Chunks(manifest)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                foreach (var fork in new[] { false, true })
                {
                    var data = new JsonObject { ["personalSync"] = new JsonObject { ["actor_id"] = desktopActor },
                        ["notizbuecher"] = new JsonArray(new JsonObject { ["id"] = "shared-book", ["name"] = "Synthetic notebook" }),
                        ["notizen"] = fork ? new JsonArray(new JsonObject { ["id"] = noteId, ["titel"] = "Synthetic note", ["text"] = "Desktop old copy",
                            ["html"] = "<p>Desktop old copy</p>", ["notizbuchId"] = "shared-book", ["angelegt"] = 1000, ["personalGeaendert"] = 1000, ["ursprungApp"] = "notes" }) : new JsonArray() };
                    await NotesScriptAsync(web, $$"""
                        (async () => {
                          App.init({daten:{{data.ToJsonString()}},neu:false});
                          await OrganizerTest.personalSyncSnapshot(['notes'],14,{{JsonSerializer.Serialize(phoneId)}});
                          await new Promise((resolve,reject) => OrganizerTest.nachDauerhaftemSpeichern(resolve,reject));
                          return true;
                        })()
                        """);
                    await coordinator.ReportStatusAsync();
                    var value = new JsonObject { ["title"] = "Synthetic note", ["text"] = "Phone first copy", ["html"] = "<p>Phone first copy</p>",
                        ["notebook_id"] = "shared-book", ["symbol"] = "", ["created_ms"] = 1000, ["modified_ms"] = 2000,
                        ["attachments"] = new JsonArray(), ["origin_app"] = "notes" };
                    var record = new JsonObject { ["kind"] = "note", ["id"] = noteId, ["state"] = "live", ["clock"] = new JsonArray(new JsonObject {
                        ["actor_id"] = phoneActor, ["counter"] = 1 }), ["hash"] = PersonalSyncContract.ProjectionHash(value), ["modified_ms"] = 2000, ["value"] = value };
                    async Task<JsonObject> Exchange(JsonObject incoming)
                    {
                        wire.SetLength(0); wire.Position = 0;
                        var run = Guid.NewGuid().ToString("D");
                        var request = new JsonObject { ["format"] = 14, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
                        var records = new JsonArray(incoming.DeepClone());
                        var batch = new JsonObject { ["format"] = 14, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = 0,
                            ["last"] = true, ["reply"] = false, ["records_hash"] = PersonalSyncContract.RecordsHash(records), ["records"] = records };
                        JsonObject Frame(string kind, JsonObject body) => scoped ? Message(PhoneContentScope.DataKind, PhoneContentScope.Wrap(kind, body, manifest)) : Message(kind, body);
                        await connection.HandlePlainAsync(Frame("personal_sync.request", request)).WaitAsync(TimeSpan.FromSeconds(20));
                        await connection.HandlePlainAsync(Frame("personal_sync.batch", batch)).WaitAsync(TimeSpan.FromSeconds(20));
                        var outgoing = await NotesPlainFramesAsync(wire);
                        var plain = outgoing.Where(item => item["type"]?.GetValue<string>() == "message").Select(item => {
                            var kind = item["kind"]!.GetValue<string>(); var body = item["body"]!.AsObject();
                            return kind == PhoneContentScope.DataKind ? PhoneContentScope.Unwrap(body, manifest) : (Kind: kind, Body: body);
                        }).ToArray();
                        var replies = plain.Where(item => item.Kind == "personal_sync.batch" && item.Body["run_id"]?.GetValue<string>() == run && item.Body["reply"]?.GetValue<bool>() == true).ToArray();
                        Test(replies.Length != 0, "Native UI saved the note but emitted no actual reply batch.");
                        Test(plain.Any(item => item.Kind == "personal_sync.report" && item.Body["run_id"]?.GetValue<string>() == run), "Native UI reply did not reach its report phase.");
                        var saved = JsonNode.Parse(await File.ReadAllTextAsync(paths.Data))!.AsObject();
                        Test(saved["notizen"]!.AsArray().Count == (fork ? 2 : 1), "Native UI created another note instead of updating the existing logical record.");
                        return replies.SelectMany(item => item.Body["records"]!.AsArray()).OfType<JsonObject>()
                            .Single(item => item["kind"]?.GetValue<string>() == "note" && item["id"]?.GetValue<string>() == noteId).DeepClone().AsObject();
                    }
                    var reply = await Exchange(record);
                    var next = reply.DeepClone().AsObject(); var nextValue = next["value"]!.AsObject();
                    nextValue["text"] = "Phone next edit after native reply"; nextValue["html"] = "<p>Phone next edit after native reply</p>";
                    nextValue["modified_ms"] = 3000; next["modified_ms"] = 3000; next["hash"] = PersonalSyncContract.ProjectionHash(nextValue);
                    var clocks = next["clock"]!.AsArray().OfType<JsonObject>().ToDictionary(item => item["actor_id"]!.GetValue<string>(), item => TelefonProtocolContract.Integer(item["counter"]));
                    clocks[phoneActor] = clocks.GetValueOrDefault(phoneActor) + 1;
                    next["clock"] = new JsonArray(clocks.OrderBy(item => item.Key, StringComparer.Ordinal).Select(item => (JsonNode)new JsonObject { ["actor_id"] = item.Key, ["counter"] = item.Value }).ToArray());
                    await Exchange(next);
                    Console.WriteLine($"WINDOWS-NOTES-NATIVE-SAVE-REPLY scoped={scoped} historicalFork={fork} count={(fork ? 2 : 1)}");
                }
            }
        }
        finally { online.Remove(phoneId); }
    }

    private static async Task NotesScriptAsync(CoreWebView2 web, string expression)
    {
        var key = "__notesNativeProof" + Guid.NewGuid().ToString("N"); var literal = JsonSerializer.Serialize(key);
        await web.ExecuteScriptAsync($$$"""
            window[{{{literal}}}]=null;
            (async()=>{try {await ({{{expression}}});window[{{{literal}}}]={ok:true};}
              catch(error){window[{{{literal}}}]={ok:false,error:String(error.message||error)};}})();
            """);
        var deadline = DateTimeOffset.UtcNow.AddSeconds(20);
        while (DateTimeOffset.UtcNow < deadline)
        {
            var text = await web.ExecuteScriptAsync("window[" + literal + "]");
            if (text != "null")
            {
                var result = JsonNode.Parse(text)!.AsObject();
                Test(result["ok"]?.GetValue<bool>() == true, "Synthetic native Notes setup/save failed: " + result["error"]?.GetValue<string>());
                return;
            }
            await Task.Delay(25);
        }
        throw new TimeoutException("Native Notes setup did not receive its actual SaveACK.");
    }

    private static async Task<IReadOnlyList<JsonObject>> NotesPlainFramesAsync(MemoryStream wire)
    {
        using var input = new MemoryStream(wire.ToArray()); var result = new List<JsonObject>();
        while (input.Position < input.Length)
        {
            var envelope = await TelefonCoordinator.ReadFrameAsync(input, 1_048_576, CancellationToken.None);
            var cipher = Convert.FromBase64String(envelope["ciphertext"]!.GetValue<string>()); envelope.Remove("ciphertext");
            var nonce = new byte[12]; BinaryPrimitives.WriteUInt64BigEndian(nonce.AsSpan(4), (ulong)TelefonProtocolContract.Integer(envelope["seq"]));
            var clear = new byte[cipher.Length - 16];
            using var aes = new AesGcm(new byte[32], 16);
            aes.Decrypt(nonce, cipher.AsSpan(0, clear.Length), cipher.AsSpan(clear.Length), clear, TelefonCrypto.Canonical(envelope));
            result.Add(JsonNode.Parse(clear)!.AsObject()); CryptographicOperations.ZeroMemory(clear);
        }
        return result;
    }
}
