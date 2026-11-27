using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

if (args.Length != 4) throw new ArgumentException("assembly input.json output.json import|export|store-export");
var assemblyPath = Path.GetFullPath(args[0]);
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    var candidate = Path.Combine(Path.GetDirectoryName(assemblyPath)!, name.Name + ".dll");
    return File.Exists(candidate) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(candidate) : null;
};
var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
var codec = assembly.GetType("MagnolieOrganizer.Windows.ExchangeCodec", throwOnError: true)!;
var parse = codec.GetMethod("ParseImport", BindingFlags.NonPublic | BindingFlags.Static)!;
var write = codec.GetMethod("WriteIcs", BindingFlags.NonPublic | BindingFlags.Static)!;
JsonObject Import(string text, string filename)
{
    var parsed = parse.Invoke(null, [Encoding.UTF8.GetBytes(text), "ics", filename])!;
    return (JsonObject)parsed.GetType().GetMethod("ToPayload", BindingFlags.NonPublic | BindingFlags.Instance)!
        .Invoke(parsed, ["ics", filename])!;
}
var results = new JsonArray();
foreach (var entry in JsonNode.Parse(File.ReadAllText(args[1]))!.AsArray())
{
    var item = entry!.AsObject(); var id = item["id"]!.GetValue<string>();
    var result = new JsonObject { ["id"] = id };
    JsonObject payload;
    if (args[3] == "import")
    {
        payload = Import(item["input"]!.GetValue<string>(), id + ".ics");
        result["payload"] = payload;
    }
    else payload = item["book"]!.AsObject();
    if (args[3] == "store-export")
    {
        var storeType = assembly.GetType("MagnolieOrganizer.Windows.AtomicStore", throwOnError: true)!;
        var store = storeType.GetConstructors(BindingFlags.Instance | BindingFlags.NonPublic).Single().Invoke([null]);
        var storeWrite = storeType.GetMethod("WriteRecoverableJson", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var storeRead = storeType.GetMethod("ReadRecoverableJson", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var folder = Path.Combine(Path.GetTempPath(), "magnolie-colour-book-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            var bookPath = Path.Combine(folder, "book.json");
            storeWrite.Invoke(store, [bookPath, payload.ToJsonString(new JsonSerializerOptions(JsonSerializerOptions.Default)), 256L * 1024 * 1024]);
            var reopened = JsonNode.Parse((string)storeRead.Invoke(store, [bookPath, 256L * 1024 * 1024])!)!.AsObject();
            if (!JsonNode.DeepEquals(payload, reopened)) throw new InvalidOperationException(id + ": actual AtomicStore reopen changed JSON");
            result["storage"] = new JsonObject { ["path"] = "AtomicStore.WriteRecoverableJson → ReadRecoverableJson", ["book_reopened_equal"] = true,
                ["file_sha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(bookPath))).ToLowerInvariant() };
            payload = reopened;
        }
        finally { Directory.Delete(folder, true); }
    }
    var exports = new JsonObject();
    foreach (var kind in new[] { "termine", "aufgaben", "jahrestage" })
    {
        if (payload[kind] is not JsonArray values || values.Count == 0) continue;
        using var data = JsonDocument.Parse(values.ToJsonString());
        var exported = write.Invoke(null, ["ics-" + kind, data.RootElement])!;
        var text = (string)exported.GetType().GetProperty("Text")!.GetValue(exported)!;
        exports[kind] = new JsonObject { ["text"] = text, ["reimport"] = Import(text, id + ".ics") };
    }
    result["exports"] = exports; results.Add(result);
}
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[2]))!);
File.WriteAllText(args[2], results.ToJsonString(new JsonSerializerOptions(JsonSerializerOptions.Default) { WriteIndented = true }) + "\n");
Console.WriteLine(JsonSerializer.Serialize(new { runtime = ".NET actual compiled ExchangeCodec via reflection",
    mode = args[3], cases = results.Count, assembly = assemblyPath,
    assembly_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant(), output = args[2] }));
