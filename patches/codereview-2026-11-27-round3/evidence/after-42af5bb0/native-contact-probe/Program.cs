using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

// Calls the already-built actual repository source; no codec/restore copy.
var binary = Path.GetFullPath(args[0]);
var vcard = Path.GetFullPath(args[1]);
var source = Path.GetFullPath(args[2]);
var assembly = Assembly.LoadFrom(binary);
var flags = BindingFlags.NonPublic | BindingFlags.Static;
var codec = assembly.GetType("MagnolieOrganizer.Windows.ExchangeCodec", true)!;
var parsed = codec.GetMethod("ParseVCard", flags)!.Invoke(null, [File.ReadAllText(vcard)])!;
var contacts = (JsonArray)parsed.GetType().GetProperty("Kontakte")!.GetValue(parsed)!;
var old = contacts[0]!.DeepClone().AsObject();
old["id"] = "contact-local";
var currentContact = old.DeepClone().AsObject();
currentContact["uid"] = "new-uid";
currentContact["kontaktpersonen"] = new JsonArray();
foreach (var key in new[] { "kontaktpersonName", "kontaktpersonTelefon", "kontaktpersonStatus" })
    currentContact[key] = "";
var snapshot = new JsonObject { ["kontakte"] = new JsonArray(old) };
var current = new JsonObject { ["kontakte"] = new JsonArray(currentContact) };
var beforeSnapshot = snapshot.DeepClone();
var beforeCurrent = current.DeepClone();
var selection = assembly.GetType("MagnolieOrganizer.Windows.RestoreSelection", true)!;
var restored = (JsonObject)selection.GetMethod("Select", flags)!.Invoke(null,
    [snapshot, current, new[] { "contacts" }, "additive"])!;
var resultContact = restored["kontakte"]![0]!;
Console.WriteLine(JsonSerializer.Serialize(new {
    source_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source))).ToLowerInvariant(),
    assembly_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(binary))).ToLowerInvariant(),
    vcard_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(vcard))).ToLowerInvariant(),
    snapshot_person_count_from_actual_vcard_reader = old["kontaktpersonen"]!.AsArray().Count,
    restored_person_list = resultContact["kontaktpersonen"],
    restored_person_list_count = resultContact["kontaktpersonen"]!.AsArray().Count,
    restored_legacy_first_person_name = resultContact["kontaktpersonName"]!.ToString(),
    restored_card_count = restored["kontakte"]!.AsArray().Count,
    current_uid_preserved = resultContact["uid"]!.ToString() == "new-uid",
    inputs_unchanged = JsonNode.DeepEquals(snapshot, beforeSnapshot) && JsonNode.DeepEquals(current, beforeCurrent),
    scope = "Actual C# vCard reader and RestoreSelection from the built .NET 8 Linux CoreTests host; no native Windows GUI claim."
}, new JsonSerializerOptions { WriteIndented = true }));
