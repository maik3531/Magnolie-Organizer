using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

// Synthetic-only NDJSON adapter. The actual coordinator authenticates each request.
var root = Environment.GetEnvironmentVariable("CONTACT_INTEROP_HOME") ?? throw new Exception("CONTACT_INTEROP_HOME required");
if (!Path.GetFullPath(root).StartsWith("/tmp/opencode/", StringComparison.Ordinal)) throw new Exception("isolated home required");
var paths = new WindowsPaths(Path.Combine(root, "windows"));
var store = new MagnolienbaumStore(paths);
JsonNode? report = null;
JsonNode? sentReport = null;
Task Emit(string name, object value) { if (name == "App.baumStand") report = JsonSerializer.SerializeToNode(value); if (name == "App.baumGesendet") sentReport = JsonSerializer.SerializeToNode(value); return Task.CompletedTask; }
var coordinator = new MagnolienbaumCoordinator(paths, Emit);
JsonObject State() => (JsonObject)typeof(MagnolienbaumCoordinator).GetField("state", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
JsonObject Partner() => State()["partner"]!.AsArray()[0]!.AsObject();
MagnolienbaumFsStart? start = null;
MagnolienbaumFsSession? session = null;
JsonObject? envelope = null;
while (Console.ReadLine() is { } input)
{
    try
    {
        var r = JsonNode.Parse(input)!.AsObject(); var op = r["op"]!.ToString();
        var data = r["data"]; var text = r["text"]?.ToString() ?? "";
        JsonNode? result;
        switch (op)
        {
            case "init":
                State()["an"] = true; State()["partner"] = new JsonArray(); store.SaveState(State());
                store.SaveOutbox(new JsonArray()); store.SaveInbox(new JsonArray());
                foreach (var field in new[] { "outbox", "inbox" }) typeof(MagnolienbaumCoordinator).GetField(field, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(coordinator, new JsonArray());
                result = MagnolienbaumPairing.Identity(State()); break;
            case "pair":
                var peer = MagnolienbaumPairing.AddPartner(State(), data!.AsObject(), "127.0.0.1", false);
                peer["bestaetigt"] = true; peer["wartet"] = false; store.SaveState(State()); result = peer.DeepClone(); break;
            case "start": start = MagnolienbaumFs1.BuildStart(State(), Partner()); result = start.Message.DeepClone(); break;
            case "message":
                session = MagnolienbaumFs1.OpenResponse(State(), Partner(), start!.Message, data!.AsObject(), start.EphemeralPrivate);
                envelope = MagnolienbaumFs1.BuildEnvelope(session, State()["kennung"]!.ToString(), Partner()["kennung"]!.ToString(), r["content"]!.DeepClone(), Convert.ToBase64String(System.Security.Cryptography.RandomNumberGenerator.GetBytes(16)));
                result = envelope.DeepClone(); break;
            case "ack": result = JsonValue.Create(MagnolienbaumFs1.VerifyAcknowledgement(session!, envelope!, data!.AsObject())); session!.Dispose(); start!.Dispose(); break;
            case "request":
                var response = typeof(MagnolienbaumCoordinator).GetMethod("HandleRequest", BindingFlags.Instance | BindingFlags.NonPublic)!
                    .Invoke(coordinator, [text, data!.AsObject(), "127.0.0.1"])!;
                result = JsonSerializer.SerializeToNode(response); break;
            case "status": await coordinator.ReportStatusAsync(); result = report?.DeepClone(); break;
            case "outbox": result = store.LoadOutbox(); break;
            case "restart": coordinator.Dispose(); coordinator = new MagnolienbaumCoordinator(paths, Emit); result = Partner().DeepClone(); break;
            case "remove": await coordinator.RemoveAsync(Partner()["kennung"]!.ToString()); result = State().DeepClone(); break;
            case "capabilities": result = BaumContactSyncContract.Capabilities(false); break;
            case "validate":
                var kind = data!["art"]!.ToString();
                if (kind == "kontakt_faehigkeiten") BaumContactSyncContract.ValidateCapabilities(data);
                else if (kind == "kontakt_sync") BaumContactSyncContract.Validate(data);
                else BaumContactSyncContract.ValidateImport(data, kind);
                result = JsonValue.Create(true); break;
            case "for-peer": result = BaumContactSyncContract.ForPeer(r["peer"]!.AsObject(), data!.AsObject()); break;
            case "queue-compat":
                Partner().Remove("kontaktFaehigkeiten"); Partner()["protokoll"] = "baum-1";
                store.SaveOutbox(new JsonArray());
                typeof(MagnolienbaumCoordinator).GetField("outbox", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(coordinator, new JsonArray());
                var observed = new List<string>();
                var key = MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(State()["geheim"]!.ToString()),
                    Convert.FromBase64String(Partner()["oeffentlich"]!.ToString()), State()["kennung"]!.ToString(), Partner()["kennung"]!.ToString());
                var fake = new ContactHttpHandler(async request => {
                    var encrypted = JsonNode.Parse(await request.Content!.ReadAsStringAsync())!.AsObject();
                    var opened = MagnolienbaumCrypto.DecryptBaum1(key, encrypted, State()["kennung"]!.ToString(), 0, out _);
                    var kind = opened["art"]!.ToString(); observed.Add(kind);
                    var accepted = text == "reject-contact" ? kind == "kontakt_faehigkeiten" : kind == "kontakt_sync";
                    return new HttpResponseMessage(accepted ? System.Net.HttpStatusCode.OK : System.Net.HttpStatusCode.Forbidden)
                        { Content = new StringContent("{\"ok\":true}") };
                });
                typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(coordinator, new HttpClient(fake));
                await coordinator.SendAsync(Partner()["kennung"]!.ToString(), "kontakt_sync", data!);
                result = new JsonObject { ["report"] = sentReport?.DeepClone(), ["observed"] = JsonSerializer.SerializeToNode(observed), ["outbox"] = store.LoadOutbox() }; break;
            case "core-contacts": await MagnolieOrganizer.Windows.Tests.ContractGroupTests.TreeContactsAsync(); result = JsonValue.Create(true); break;
            case "vcf": result = ExchangeCodec.ParseVCard(text).ToPayload("vcf", "synthetic.vcf"); break;
            case "ldif": result = ExchangeCodec.ParseLdif(text).ToPayload("claws", "synthetic.ldif"); break;
            case "write-vcf":
            case "write-ldif":
                using (var doc = JsonDocument.Parse(data!.ToJsonString())) result = JsonValue.Create(op == "write-vcf"
                    ? ExchangeCodec.WriteVCard(doc.RootElement).Text : ExchangeCodec.WriteLdif(doc.RootElement).Text);
                break;
            default: throw new Exception(op);
        }
        Console.WriteLine(new JsonObject { ["value"] = result?.DeepClone() }.ToJsonString());
    }
    catch (Exception error) { Console.WriteLine(new JsonObject { ["error"] = error.ToString() }.ToJsonString()); }
}
coordinator.Dispose();

sealed class ContactHttpHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handle) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => handle(request);
}
