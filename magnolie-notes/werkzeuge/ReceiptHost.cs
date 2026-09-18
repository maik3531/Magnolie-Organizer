using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Text;
using System.Text.Json.Nodes;

// No replacement protocol implementation: invoke the freshly built canonical Windows code.
var root = Path.GetFullPath(args[0]);
if (!root.StartsWith("/tmp/opencode/", StringComparison.Ordinal) || !Directory.Exists(root)) throw new InvalidOperationException();
var dll = Path.GetFullPath(args[1]);
var resolver = new AssemblyDependencyResolver(dll);
AssemblyLoadContext.Default.Resolving += (_, name) => resolver.ResolveAssemblyToPath(name) is string path
    ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
AssemblyLoadContext.Default.ResolvingUnmanagedDll += (_, name) => resolver.ResolveUnmanagedDllToPath(name) is string path
    ? NativeLibrary.Load(path) : IntPtr.Zero;
var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(dll);
const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
Type Class(string name) => assembly.GetType("MagnolieOrganizer.Windows." + name, true)!;
object New(string name, params object?[] values) => Activator.CreateInstance(Class(name), flags, null, values, null)!;
object? Call(object target, string name, params object?[] values) => target.GetType().GetMethod(name, flags)!.Invoke(target, values);
object? Static(string name, string method, params object?[] values) => Class(name).GetMethod(method, flags)!.Invoke(null, values);
var initial = JsonNode.Parse(Console.ReadLine()!)!.AsObject();
var paths = New("WindowsPaths", root);
var store = New("MagnolienbaumStore", paths, null, null, null);
var state = (JsonObject)Call(store, "LoadOrCreate")!;
var peers = state["partner"]!.AsArray();
var peer = peers.OfType<JsonObject>().FirstOrDefault(p => p["kennung"]!.GetValue<string>() == initial["id"]!.GetValue<string>());
if (peer is null)
{
    peer = new JsonObject { ["kennung"] = initial["id"]!.DeepClone(), ["name"] = "Owned Android",
        ["oeffentlich"] = initial["public"]!.DeepClone(), ["bestaetigt"] = true, ["protokoll"] = "baum-1" };
    peers.Add(peer);
}
if (peer["oeffentlich"]!.GetValue<string>() != initial["public"]!.GetValue<string>()) throw new InvalidOperationException();
peer["adresse"] = "127.0.0.1"; peer["port"] = initial["port"]!.DeepClone();
using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
var port = ((IPEndPoint)listener.LocalEndpoint).Port;
state["an"] = true; state["port"] = port; Call(store, "SaveState", state);
using var coordinator = (IDisposable)New("MagnolienbaumCoordinator", paths, (Func<string, object, Task>)((_, _) => Task.CompletedTask));
using var stop = new CancellationTokenSource();
var mode = "normal";
var requests = 0;
var gate = new object();
JsonObject Stats() => new() { ["inbox"] = ((JsonArray)Call(store, "LoadInbox")!).Count,
    ["outbox"] = (JsonArray)Call(store, "LoadOutbox")!, ["requests"] = requests };
void Output(JsonObject value) => Console.WriteLine("RECEIPT_HOST " + value.ToJsonString());
var serving = Task.Run(async () =>
{
    while (!stop.IsCancellationRequested)
    {
        try
        {
            using var socket = await listener.AcceptTcpClientAsync(stop.Token);
            socket.ReceiveTimeout = 5000;
            var stream = socket.GetStream();
            string Line()
            {
                var bytes = new List<byte>();
                while (bytes.Count < 8192) { var b = stream.ReadByte(); if (b < 0) throw new IOException(); if (b == 10) return Encoding.ASCII.GetString(bytes.ToArray()).TrimEnd('\r'); bytes.Add((byte)b); }
                throw new IOException();
            }
            var path = Line().Split(' ')[1]; int length = -1;
            for (var count = 0; count < 65; count++)
            {
                var line = Line(); if (line.Length == 0) break;
                if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)) length = int.Parse(line.Split(':', 2)[1]);
            }
            if (length is <= 0 or > 2097152) throw new IOException();
            var bytes = new byte[length]; stream.ReadExactly(bytes);
            var envelope = JsonNode.Parse(bytes)!.AsObject();
            Interlocked.Increment(ref requests);
            var result = ((int Status, JsonObject Body))Call(coordinator, "HandleProtocolRequest", path, envelope, "127.0.0.1")!;
            var body = result.Body;
            lock (gate)
            {
                if (result.Status == 200)
                {
                    if (mode == "unsigned") body = new JsonObject();
                    else if (mode == "wrong-mac") { body = body.DeepClone().AsObject(); body["mac"] = Convert.ToBase64String(new byte[32]); }
                    else if (mode == "wrong-binding")
                    {
                        var key = (byte[])Static("MagnolienbaumCrypto", "PartnerKey", Convert.FromBase64String(state["geheim"]!.GetValue<string>()),
                            Convert.FromBase64String(peer["oeffentlich"]!.GetValue<string>()), state["kennung"]!.GetValue<string>(), peer["kennung"]!.GetValue<string>())!;
                        body = (JsonObject)Static("BaumReceipt", "Create", key, peer["kennung"]!.GetValue<string>(), "other", envelope)!;
                        System.Security.Cryptography.CryptographicOperations.ZeroMemory(key);
                    }
                    else if (mode == "lost") continue;
                }
            }
            var payload = Encoding.UTF8.GetBytes(body.ToJsonString());
            var header = Encoding.ASCII.GetBytes($"HTTP/1.1 {result.Status} Fixture\r\nContent-Length: {payload.Length}\r\nConnection: close\r\n\r\n");
            await stream.WriteAsync(header, stop.Token); await stream.WriteAsync(payload, stop.Token);
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
        catch (Exception error) { Console.Error.WriteLine(error.GetType().Name + ": " + error.Message); }
    }
});
Output(new JsonObject { ["id"] = state["kennung"]!.DeepClone(), ["public"] = state["oeffentlich"]!.DeepClone(), ["port"] = port });
try
{
    while (Console.ReadLine() is string line)
    {
        var command = JsonNode.Parse(line)!.AsObject(); var op = command["op"]!.GetValue<string>();
        if (op == "quit") break;
        if (op == "mode") { lock (gate) mode = command["value"]!.GetValue<string>(); }
        else if (op == "send") await (Task)Call(coordinator, "SendAsync", peer["kennung"]!.GetValue<string>(), "stand", command["body"]!)!;
        else if (op == "vector")
        {
            Output((JsonObject)Static("BaumReceipt", "Create", Convert.FromHexString(command["key"]!.GetValue<string>()), "alpha", "beta", command["envelope"]!)!);
            continue;
        }
        Output(Stats());
    }
}
finally { stop.Cancel(); listener.Stop(); await serving; }
