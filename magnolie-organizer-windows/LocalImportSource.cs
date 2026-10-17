using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class LocalImportSource
{
    private static readonly string[] Collections = ["kontakte", "geburtstage", "termine", "jahrestage", "aufgaben", "notizen"];

    // Uses exactly the GUI's existing Windows Contacts/Thunderbird readers.
    // Explicit roots allow isolated fixtures; no root path is exposed over IPC.
    internal static async Task<JsonObject> ReadAsync(string area, bool onlyContacts,
        string contactsDirectory, string thunderbirdRoot)
    {
        if (area is not ("" or "kontakte" or "thunderbird")) throw new ArgumentException("Unknown local import area.");
        var contactsOnly = area == "kontakte";
        var thunderbirdOnly = area == "thunderbird";
        var contacts = new JsonArray();
        if (!thunderbirdOnly)
        {
            var store = new WindowsContactStore(contactsDirectory);
            foreach (var contact in await store.ReadAsync(CancellationToken.None))
            {
                var item = contact.Data.DeepClone().AsObject(); item["uid"] = store.ImportUid(contact);
                item["geaendert"] = contact.Modified; contacts.Add(item);
            }
        }
        var result = new JsonObject
        {
            ["art"] = "lokal", ["abgebrochen"] = false, ["kontakte"] = contacts,
            ["geburtstage"] = new JsonArray(), ["termine"] = new JsonArray(),
            ["jahrestage"] = new JsonArray(), ["aufgaben"] = new JsonArray(),
            ["uebersprungen"] = 0, ["wiederholend"] = 0, ["localCalendarStores"] = 0, ["localAddressBooks"] = 0
        };
        if (!contactsOnly && Directory.Exists(thunderbirdRoot))
        {
            var profiles = ThunderbirdCalendarImporter.DiscoverProfiles(thunderbirdRoot);
            if (!onlyContacts)
            {
                var calendars = ThunderbirdCalendarImporter.DiscoverCalendarStores(profiles);
                var parsed = ThunderbirdCalendarImporter.ParseProfiles(calendars, out var read);
                result["termine"] = parsed.Termine.DeepClone(); result["jahrestage"] = parsed.Jahrestage.DeepClone();
                result["aufgaben"] = parsed.Aufgaben.DeepClone(); result["uebersprungen"] = parsed.Uebersprungen;
                result["wiederholend"] = parsed.Wiederholend; result["localCalendarStores"] = read;
            }
            var books = ThunderbirdCalendarImporter.ParseAddressBooks(profiles, out var addressBooks);
            // The combined GUI scan retains Windows Contacts; an explicit
            // Thunderbird scan starts with an empty list above.
            foreach (var contact in books.Kontakte.OfType<JsonObject>()) contacts.Add(contact.DeepClone());
            result["localAddressBooks"] = addressBooks;
            result["uebersprungen"] = result["uebersprungen"]!.GetValue<int>() + books.Uebersprungen;
        }
        return result;
    }

    internal static void BindSnapshot(JsonObject payload, string source, string scope, string? expectedRevision = null)
    {
        if (source is not ("windows_contacts" or "thunderbird") || scope is not ("contacts" or "all"))
            throw new ArgumentException("Unknown local import selection.");
        var semantic = new JsonObject { ["source"] = source, ["scope"] = scope, ["version"] = 1,
            ["uebersprungen"] = payload["uebersprungen"]?.DeepClone() ?? JsonValue.Create(0),
            ["wiederholend"] = payload["wiederholend"]?.DeepClone() ?? JsonValue.Create(0) };
        foreach (var name in Collections)
        {
            var records = new List<string>();
            if (payload[name] is JsonArray values) foreach (var node in values)
            {
                if (node is not JsonObject value) throw new InvalidDataException("Invalid local import record.");
                var copy = value.DeepClone().AsObject(); copy.Remove("id");
                records.Add(Encoding.UTF8.GetString(TelefonCrypto.Canonical(copy)));
            }
            else if (payload[name] is not null) throw new InvalidDataException("Invalid local import collection.");
            records.Sort(StringComparer.Ordinal);
            semantic[name] = new JsonArray(records.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        }
        var bytes = TelefonCrypto.Canonical(semantic);
        if (bytes.Length > ExchangeCodec.MaxImportBytes ||
            Encoding.UTF8.GetByteCount(payload.ToJsonString()) > ExchangeCodec.MaxImportBytes)
            throw new InvalidDataException("local_import_too_large");
        var revision = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        if (!string.IsNullOrEmpty(expectedRevision) && expectedRevision != revision) throw new InvalidOperationException("mcp_conflict");
        payload["source"] = source; payload["scope"] = scope; payload["revision"] = revision; payload["ok"] = true;
    }
}
