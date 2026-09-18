using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

// Test-only loopback peer linking the current Windows cryptography and receipt code.
if (args.Length == 1)
{
    var vector = JsonNode.Parse(File.ReadAllText(args[0]))!.AsObject();
    var vectorKey = Convert.FromHexString(vector["partnerKeyHex"]!.GetValue<string>());
    var vectorEnvelope = vector["envelope"]!.AsObject();
    var expected = vector["receipt"]!.AsObject();
    if (!JsonNode.DeepEquals(BaumReceipt.Create(vectorKey, "alpha", "beta", vectorEnvelope), expected) ||
        Encoding.UTF8.GetString(MagnolienbaumCrypto.Canonical(vectorEnvelope)) != vector["canonicalEnvelope"]!.GetValue<string>() ||
        !BaumReceipt.Verify(vectorKey, "alpha", "beta", vectorEnvelope, expected) ||
        BaumReceipt.Verify(new byte[32], "alpha", "beta", vectorEnvelope, expected) ||
        BaumReceipt.Verify(vectorKey, "beta", "alpha", vectorEnvelope, expected))
        throw new IOException("Public receipt vector mismatch");
    foreach (var field in new[] { "counter", "envelopeSha256", "extra", "mac" })
    {
        var changed = expected.DeepClone().AsObject();
        if (field == "counter") changed[field] = 2;
        else if (field == "mac") changed.Remove(field);
        else changed[field] = "wrong";
        if (BaumReceipt.Verify(vectorKey, "alpha", "beta", vectorEnvelope, changed)) throw new IOException("Mutated receipt accepted");
    }
    if (BaumReceipt.Verify(vectorKey, "alpha", "beta", vectorEnvelope, new JsonObject { ["ok"] = true })) throw new IOException("Bare success accepted");
    Console.WriteLine("Public receipt vectors passed");
    return;
}
var keys = MagnolienbaumCrypto.GenerateX25519();
Console.WriteLine(new JsonObject { ["public"] = Convert.ToBase64String(keys.Public) }.ToJsonString());
var setup = JsonNode.Parse(Console.ReadLine()!)!.AsObject();
var key = MagnolienbaumCrypto.PartnerKey(keys.Private, Convert.FromBase64String(setup["public"]!.GetValue<string>()), "windows-fixture", setup["id"]!.GetValue<string>());
var peer = setup["id"]!.GetValue<string>();
var listener = new TcpListener(IPAddress.Loopback, 0);
listener.Start();
Console.WriteLine(new JsonObject { ["port"] = ((IPEndPoint)listener.LocalEndpoint).Port }.ToJsonString());
try
{
    using var client = await listener.AcceptTcpClientAsync().WaitAsync(TimeSpan.FromSeconds(15));
    using var stream = client.GetStream();
    var header = new List<byte>();
    var one = new byte[1];
    while (header.Count < 16384)
    {
        if (await stream.ReadAsync(one).AsTask().WaitAsync(TimeSpan.FromSeconds(5)) != 1) throw new IOException("Incomplete fixture HTTP header");
        header.Add(one[0]);
        if (header.Count >= 4 && header.TakeLast(4).SequenceEqual(new byte[] {13, 10, 13, 10})) break;
    }
    var lines = Encoding.ASCII.GetString(header.ToArray()).Split("\r\n");
    var length = int.Parse(lines.Single(line => line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)).Split(':')[1]);
    if (length is < 1 or > 65536) throw new IOException("Fixture body limit");
    var body = new byte[length];
    await stream.ReadExactlyAsync(body).AsTask().WaitAsync(TimeSpan.FromSeconds(5));
    var envelope = JsonNode.Parse(body)!.AsObject();
    var content = MagnolienbaumCrypto.DecryptBaum1(key, envelope, peer, 0, out var counter);
    if (counter != 1 || content["text"]!.GetValue<string>() != "linux-to-windows") throw new IOException("Wrong plaintext/counter");
    var receipt = MagnolienbaumCrypto.Canonical(BaumReceipt.Create(key, peer, "windows-fixture", envelope));
    await stream.WriteAsync(Encoding.ASCII.GetBytes($"HTTP/1.1 200 OK\r\nContent-Length: {receipt.Length}\r\nConnection: close\r\n\r\n"));
    await stream.WriteAsync(receipt);
    Console.WriteLine("{\"received\":true}");
    var incoming = JsonNode.Parse(Console.ReadLine()!)!.AsObject();
    using var http = new HttpClient(new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false });
    var outgoing = MagnolienbaumCrypto.EncryptBaum1(key, "windows-fixture", 1, new JsonObject { ["art"] = "notiz", ["text"] = "windows-to-linux" });
    using var response = await http.PostAsync($"http://127.0.0.1:{incoming["port"]}/magnolie/v1/nachricht", new StringContent(outgoing.ToJsonString(), Encoding.UTF8, "application/json"));
    var returned = JsonNode.Parse(await response.Content.ReadAsStringAsync())!.AsObject();
    if (!response.IsSuccessStatusCode || !BaumReceipt.Verify(key, "windows-fixture", peer, outgoing, returned)) throw new IOException("Linux receipt rejected by Windows");
    Console.WriteLine("{\"verified\":true}");
}
finally { listener.Stop(); }
