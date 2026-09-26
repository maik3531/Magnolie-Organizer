using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record RemoteContact(string Id, string ETag, long Modified, JsonObject Data, bool Owned);

internal sealed record ContactSyncCounts(int Imported, int Exported, int Updated, int Deleted, int Errors)
{
    internal string Report(string name) =>
        $"{name}: {Imported} importiert, {Exported} exportiert, {Updated} aktualisiert, {Deleted} gelöscht" +
        (Errors > 0 ? $", {Errors} Fehler." : ".");
}

internal sealed record ContactSyncResult(JsonArray Contacts, JsonArray Tombstones, ContactSyncCounts Counts);

internal interface IContactRemote
{
    bool SupportsYearlessBirthdays => true;
    Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken);
    Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken);
    Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken);
    Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken);
}

internal static class ContactFields
{
    internal static bool NormalizeBirthday(JsonObject contact)
    {
        // Some contact providers use the leap year 1604 when only month/day
        // are known. This is a birthday rule, not a general date conversion.
        var value = Text(contact, "geburtstag");
        if (!ExchangeCodec.TryParseCanonicalDate(value, out var date, out _, out _) || date is null ||
            (date.Value.Year != 1604 && contact["geburtstagJahrUnbekannt"]?.GetValue<bool>() != true)) return false;
        contact["geburtstag"] = "--" + value[5..];
        contact["geburtstagJahrUnbekannt"] = true;
        return true;
    }

    internal static readonly string[] Names =
    {
        "nachname", "vorname", "anzeigename", "firma", "strasse", "plz", "ort", "land", "telefon", "mobil",
        "telefone", "email", "emails", "emailEintraege", "anschriften", "geburtstag",
        "geburtstagJahrUnbekannt", "jubilaeum", "jubilaeumJahrUnbekannt", "notiz", "foto", "kontaktpersonName", "kontaktpersonTelefon",
        "kontaktpersonStatus", "kontaktpersonen", "sozialeMedien", "vcardRoundtrip"
    };

    // UI contacts can omit nested defaults which a vCard reader materializes.
    // Empty parameters are not content; nonempty provider extensions still are.
    internal static string ContentHash(JsonObject contact) => SyncBaseline.Hash(ContentProjection(contact), Names);

    internal static JsonObject ContentProjection(JsonObject contact)
    {
        static JsonNode? Normalize(JsonNode? value)
        {
            if (value is JsonObject obj)
            {
                var result = new JsonObject();
                foreach (var property in obj)
                {
                    var normalized = Normalize(property.Value);
                    if (normalized is null || normalized.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0") continue;
                    result[property.Key] = normalized;
                }
                return result;
            }
            if (value is JsonArray array) return new JsonArray(array.Select(Normalize).ToArray());
            return value?.DeepClone();
        }
        var copy = new JsonObject();
        foreach (var name in Names) if (contact.ContainsKey(name)) copy[name] = Normalize(contact[name]);
        NormalizeBirthday(copy);
        foreach (var (date, unknown) in new[] { ("geburtstag", "geburtstagJahrUnbekannt"), ("jubilaeum", "jubilaeumJahrUnbekannt") })
            if (ExchangeCodec.TryParseCanonicalDate(Text(copy, date), out _, out _, out _)) copy.Remove(unknown);
        var display = Text(copy, "anzeigename");
        var derived = string.Join(' ', new[] { Text(copy, "vorname"), Text(copy, "nachname") }.Where(value => value.Length > 0));
        if (display == derived || display.Length > 0 && derived.Length == 0 && display == Text(copy, "firma")) copy.Remove("anzeigename");
        foreach (var category in new[] { "telefone", "emailEintraege", "anschriften" })
            foreach (var phone in (copy[category] as JsonArray ?? []).OfType<JsonObject>())
            {
                var types = (phone["typen"] as JsonArray ?? []).Select(node => node?.GetValue<string>()?.ToUpperInvariant() ?? "")
                    .Select(value => value == "MOBILE" ? "CELL" : value)
                    .Where(value => value.Length > 0 && value != "PREF").Distinct().Order(StringComparer.Ordinal).ToArray();
                if (types.All(value => value is "VOICE" or "CELL" or "HOME" or "WORK")) types = types.Where(value => value != "VOICE").ToArray();
                if (category == "emailEintraege") types = types.Where(value => value != "INTERNET").ToArray();
                var messages = types.Contains("FAX") ? new[] { "Fax" } : types.Contains("PAGER") ? ["Pager"] :
                    types.Contains("CELL") ? ["Mobile", "Mobil", "Handy"] :
                    types.Contains("WORK") ? ["Work phone", "Work", "Arbeit"] :
                    types.Contains("HOME") ? ["Home phone", "Home", "Private", "Privat", "Zuhause"] :
                    category == "telefone" ? ["Phone", "Landline", "Telefon", "Festnetz"] :
                    category == "emailEintraege" ? ["Email", "E-Mail", "E-mail"] : ["Address", "Adresse"];
                if (messages.Any(message => NativeLocalization.IsTranslation(message, Text(phone, "label")))) phone.Remove("label");
                if (types.Length == 0) phone.Remove("typen");
                else phone["typen"] = new JsonArray(types.Select(value => JsonValue.Create(value)).ToArray());
                if (category == "telefone") phone["wert"] = NumberKey(Text(phone, "wert"));
                if (category == "emailEintraege") phone["wert"] = Text(phone, "wert").ToLowerInvariant();
            }
        if (copy["telefone"] is JsonArray structuredPhones)
            foreach (var field in new[] { "telefon", "mobil" })
                if (structuredPhones.OfType<JsonObject>().Any(phone => Text(phone, "wert") == NumberKey(Text(copy, field)))) copy.Remove(field);
        if (copy["emailEintraege"] is JsonArray structuredEmails)
        {
            var addresses = structuredEmails.OfType<JsonObject>().Select(email => Text(email, "wert")).ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (addresses.Contains(Text(copy, "email"))) copy.Remove("email");
            if (copy["emails"] is JsonArray emails && emails.All(email => addresses.Contains(email?.GetValue<string>() ?? ""))) copy.Remove("emails");
        }
        if (copy["anschriften"] is JsonArray structuredAddresses && structuredAddresses.OfType<JsonObject>().Any(address =>
                new[] { "strasse", "plz", "ort", "land" }.All(field => Text(copy, field).Length == 0 || Text(copy, field) == Text(address, field))))
            foreach (var field in new[] { "strasse", "plz", "ort", "land" }) copy.Remove(field);
        copy["vcardRoundtrip"] = ExchangeCodec.UnrepresentedContactProperties(copy);
        return Normalize(copy)!.AsObject();
    }

    private static string NumberKey(string value)
    {
        var number = System.Text.RegularExpressions.Regex.Replace(value, @"[\s()./\-]", "");
        return number.StartsWith("00", StringComparison.Ordinal) ? "+" + number[2..] : number;
    }

    internal static bool ContainsContent(JsonNode? complete, JsonNode? partial, string field = "", string homeCountry = "")
    {
        if (partial is null || partial.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0") return true;
        if (complete is null) return false;
        if (JsonNode.DeepEquals(complete, partial)) return true;
        if (complete is JsonObject obj && partial is JsonObject other)
            return other.All(pair => ContainsContent(obj[pair.Key], pair.Value, field.Length == 0 ? pair.Key : field + "." + pair.Key, homeCountry));
        if (complete is JsonArray array && partial is JsonArray subset)
            return subset.All(item => array.Any(candidate => ContainsContent(candidate, item, field, homeCountry)));
        if (field == "telefone.wert" && complete is JsonValue fullNumber && partial is JsonValue shortNumber &&
            fullNumber.TryGetValue<string>(out var a) && shortNumber.TryGetValue<string>(out var b) && homeCountry.Length > 0)
            return IdentityNumberKey(a, homeCountry) == IdentityNumberKey(b, homeCountry);
        if (field is "geburtstag" or "jubilaeum" && complete is JsonValue date && partial is JsonValue monthDay &&
            date.TryGetValue<string>(out var full) && monthDay.TryGetValue<string>(out var part) && part.StartsWith("--", StringComparison.Ordinal) &&
            full.Length == 10 && ExchangeCodec.TryParseCanonicalDate(full, out _, out _, out _)) return full[4..] == part[1..];
        return false;
    }

    private static string IdentityNumberKey(string number, string homeCountry)
    {
        if (homeCountry.Length > 0 && number.Length <= 128)
            try
            {
                var utility = PhoneNumbers.PhoneNumberUtil.GetInstance();
                var parsed = utility.Parse(number, homeCountry);
                if (utility.IsValidNumber(parsed)) return utility.Format(parsed, PhoneNumbers.PhoneNumberFormat.E164) +
                    (string.IsNullOrEmpty(parsed.Extension) ? "" : ";ext=" + parsed.Extension);
            }
            catch (PhoneNumbers.NumberParseException) { }
        return NumberKey(number);
    }

    internal static HashSet<string> StrongKeys(JsonObject contact, string homeCountry = "")
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        foreach (var number in (contact["telefone"] as JsonArray ?? []).OfType<JsonObject>().Select(item => Text(item, "wert"))
            .Concat(new[] { Text(contact, "telefon"), Text(contact, "mobil") }))
        {
            var key = IdentityNumberKey(number, homeCountry);
            if (key.Any(char.IsDigit)) result.Add("phone:" + key);
        }
        foreach (var email in (contact["emailEintraege"] as JsonArray ?? []).OfType<JsonObject>().Select(item => Text(item, "wert"))
            .Concat((contact["emails"] as JsonArray ?? []).OfType<JsonValue>().Select(value => value.GetValue<string>()))
            .Append(Text(contact, "email"))) if (email.Contains('@')) result.Add("email:" + email.Trim().ToLowerInvariant());
        return result;
    }

    internal static bool Dirty(JsonObject contact, JsonObject? mapping, JsonObject? remote = null)
    {
        var hash = ContentHash(contact);
        if (mapping?["inhaltFormat"]?.GetValue<string>() == "windows-contact-2" &&
            mapping["inhaltSha256"] is JsonValue baseline && baseline.TryGetValue<string>(out var saved)) return saved != hash;
        // A legacy exact baseline still proves an unchanged local card. An
        // equivalent remote value can also establish the new semantic baseline.
        if (!SyncBaseline.Dirty(contact, mapping, Names)) return false;
        return remote is null || hash != ContentHash(remote);
    }

    internal static JsonObject CopyRemoteFields(JsonObject target, JsonObject source, string provider = "")
    {
        foreach (var name in Names)
        {
            if (provider is "windows-contacts" or "microsoft-graph")
            {
                if (name is "foto" or "emailEintraege" or "kontaktpersonName" or "kontaktpersonTelefon" or
                    "kontaktpersonStatus" or "kontaktpersonen" or "sozialeMedien" or "vcardRoundtrip") continue;
                if (provider == "microsoft-graph" && name is "anzeigename" or "jubilaeum" or "jubilaeumJahrUnbekannt") continue;
            }
            var dateField = name switch { "geburtstagJahrUnbekannt" => "geburtstag", "jubilaeumJahrUnbekannt" => "jubilaeum", _ => name };
            if (dateField is "geburtstag" or "jubilaeum" && Text(source, dateField).Length == 0 && Text(target, dateField).Length > 0) continue;
            if (name == "anzeigename" && !source.ContainsKey(name)) continue;
            target[name] = source[name]?.DeepClone();
        }
        NormalizeBirthday(target);
        return target;
    }

    internal static string Text(JsonObject value, string name) => value[name]?.GetValue<string>()?.Trim() ?? "";

    internal static JsonObject? Source(JsonObject value, string source)
    {
        return value["syncQuellen"] is JsonObject all && all[source] is JsonObject item ? item : null;
    }

    internal static void SetSource(JsonObject value, string source, RemoteContact remote, bool remoteBaseline = false)
    {
        var baseline = remoteBaseline ? remote.Data : value;
        if (remoteBaseline && source is "windows-contacts" or "microsoft-graph")
            baseline = CopyRemoteFields(value.DeepClone().AsObject(), remote.Data, source);
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject();
        value["syncQuellen"] = all;
        all[source] = new JsonObject
        {
            ["id"] = remote.Id, ["etag"] = remote.ETag, ["geaendert"] = remote.Modified,
            ["eigen"] = remote.Owned,
            ["inhaltFormat"] = "windows-contact-2",
            ["inhaltSha256"] = ContentHash(baseline),
            ["fernInhaltSha256"] = ContentHash(remote.Data)
        };
        value["sync"] = true;
    }
}

internal static class ContactCleanupPlan
{
    private sealed record Candidate(JsonObject[] Cards, JsonObject Complete);

    private static IEnumerable<Candidate> Candidates(JsonObject[] contacts, string homeCountry)
    {
        string Name(JsonObject card) => string.Join('\u001f', new[] { "vorname", "nachname", "firma" }
            .Select(field => ContactFields.Text(card, field).ToUpperInvariant()));
        foreach (var named in contacts.GroupBy(Name, StringComparer.Ordinal))
        {
            var cards = named.ToArray();
            if (cards.Length < 2) continue;
            var common = ContactFields.StrongKeys(cards[0], homeCountry);
            foreach (var card in cards.Skip(1)) common.IntersectWith(ContactFields.StrongKeys(card, homeCountry));
            var projected = cards.Select(ContactFields.ContentProjection).ToArray();
            var complete = common.Count == 0 ? -1 : Array.FindIndex(projected,
                candidate => projected.All(part => ContactFields.ContainsContent(candidate, part, homeCountry: homeCountry)));
            if (complete >= 0) yield return new Candidate(cards, cards[complete]);
            else foreach (var exact in cards.GroupBy(ContactFields.ContentHash, StringComparer.Ordinal).Where(group => group.Count() > 1))
                yield return new Candidate(exact.ToArray(), exact.First());
        }
    }

    internal static JsonObject Create(System.Text.Json.JsonElement profile, string homeCountry = "DE")
    {
        var groups = new JsonArray();
        var source = profile.TryGetProperty("einstellungen", out var settings) && settings.TryGetProperty("sync", out var sync) &&
            sync.TryGetProperty("adressbuchUid", out var selected) && selected.ValueKind == System.Text.Json.JsonValueKind.String
            ? selected.GetString() ?? "" : "";
        var raw = profile.TryGetProperty("kontakte", out var values) && values.ValueKind == System.Text.Json.JsonValueKind.Array ? values.GetRawText() : "[]";
        var fingerprint = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(raw))).ToLowerInvariant();
        homeCountry = PhoneRegionInfo.HomeCountry(homeCountry);
        var result = new JsonObject { ["format"] = 1, ["source"] = source, ["homeCountry"] = homeCountry, ["fingerprint"] = fingerprint, ["groups"] = groups };
        if (!NextcloudDavSelection.IsAddressBook(source)) return result;
        if (profile.TryGetProperty("syncNachRestore", out var restore) && restore.ValueKind == System.Text.Json.JsonValueKind.Object &&
            new[] { "additiv", "loeschungsfrei" }.Any(field => restore.TryGetProperty(field, out var flag) && flag.ValueKind == System.Text.Json.JsonValueKind.True)) return result;
        var contacts = JsonNode.Parse(raw)!.AsArray().OfType<JsonObject>().ToArray();
        var metadata = new HashSet<string>(new[] { "id", "uid", "geaendert", "sync", "syncQuellen", "baumKontakt", "importBindungen", "importHerkunfte", "importKonflikt", "kontaktAliase" }, StringComparer.Ordinal);
        foreach (var candidate in Candidates(contacts, homeCountry))
        {
            var cards = candidate.Cards;
            var desiredHash = ContactFields.ContentHash(candidate.Complete);
            if (cards.Any(card => ContactFields.Text(card, "id").Length == 0 || card["importKonflikt"]?.GetValue<bool>() == true) ||
                cards.Select(card => ContactFields.Text(card, "id")).Distinct(StringComparer.Ordinal).Count() != cards.Length) continue;
            var first = cards[0];
            var strong = new[] { "email", "telefon", "mobil" }.Any(field => ContactFields.Text(first, field).Length > 0) ||
                new[] { "emailEintraege", "telefone" }.Any(field => first[field] is JsonArray entries && entries.OfType<JsonObject>().Any(entry => ContactFields.Text(entry, "wert").Length > 0));
            if (!strong) continue;
            var treeIds = cards.Select(card => card["baumKontakt"] is JsonObject tree ? ContactFields.Text(tree, "freigabeId") : "")
                .Where(value => value.Length > 0).Distinct(StringComparer.Ordinal).ToArray();
            if (treeIds.Length > 1 || cards.Select(card => card["baumKontakt"]?["entscheidungHash"]?.GetValue<string>() ?? "")
                .Where(value => value.Length > 0).Distinct(StringComparer.Ordinal).Count() > 1) continue;
            var unknown = cards.SelectMany(card => card.Select(pair => pair.Key)).Distinct(StringComparer.Ordinal)
                .Where(field => !metadata.Contains(field) && !ContactFields.Names.Contains(field));
            if (unknown.Any(field => field is "__proto__" or "prototype" or "constructor" || cards.Select(card => card[field]?.ToJsonString() ?? "null")
                .Where(value => value is not ("null" or "\"\"" or "[]" or "{}" or "false" or "0")).Distinct(StringComparer.Ordinal).Count() > 1)) continue;
            var bindings = cards.Where(card => ContactFields.Source(card, source) is JsonObject map && ContactFields.Text(map, "id").Length > 0).ToArray();
            if (bindings.Length == 0 || bindings.Any(card => ContactFields.Text(ContactFields.Source(card, source)!, "etag").Length == 0)) continue;
            var otherSources = cards.SelectMany(card => (card["syncQuellen"] as JsonObject ?? []).Select(pair => pair.Key))
                .Where(key => key != source).Distinct(StringComparer.Ordinal);
            if (otherSources.Any(key => cards.Select(card => ContactFields.Source(card, key)).OfType<JsonObject>()
                .Select(map => ContactFields.Text(map, "id")).Where(value => value.Length > 0).Distinct(StringComparer.Ordinal).Count() > 1)) continue;
            var keeper = cards.OrderByDescending(card => card["baumKontakt"] is JsonObject)
                .ThenByDescending(card => card["baumKontakt"]?["version"]?.GetValue<long>() ?? 0).First();
            var contentHolder = cards.All(card => ContactFields.ContentHash(card) == desiredHash) ? keeper : candidate.Complete;
            // Retain the provider's original record when Magnolie previously exported a redundant copy.
            var provider = bindings.OrderBy(card => ContactFields.Text(card, "uid").StartsWith("mag-", StringComparison.Ordinal))
                .ThenBy(card => ReferenceEquals(card, keeper) ? 0 : 1).First();
            var keptMapping = ContactFields.Source(provider, source)!;
            static JsonArray Strings(IEnumerable<JsonNode?> values) => new(values.OfType<JsonValue>()
                .Select(value => value.TryGetValue<string>(out var text) ? text : "").Where(value => value.Length > 0)
                .Distinct(StringComparer.Ordinal).Select(value => JsonValue.Create(value)).ToArray());
            var combinedSources = new JsonObject();
            foreach (var card in cards.Reverse())
                foreach (var pair in card["syncQuellen"] as JsonObject ?? []) combinedSources[pair.Key] = pair.Value?.DeepClone();
            combinedSources[source] = keptMapping.DeepClone();
            var combined = new JsonObject { ["syncQuellen"] = combinedSources, ["sync"] = true,
                ["importBindungen"] = Strings(cards.SelectMany(card => card["importBindungen"] as JsonArray ?? [])),
                ["importHerkunfte"] = Strings(cards.SelectMany(card => card["importHerkunfte"] as JsonArray ?? [])),
                ["kontaktAliase"] = new JsonObject {
                    ["ids"] = Strings(cards.SelectMany(card => (card["kontaktAliase"]?["ids"] as JsonArray ?? [])
                        .Append(card["id"]))),
                    ["uids"] = Strings(cards.SelectMany(card => (card["kontaktAliase"]?["uids"] as JsonArray ?? [])
                        .Append(card["uid"])))
                }
            };
            if (keeper["baumKontakt"] is JsonObject tree)
            {
                var mergedTree = tree.DeepClone().AsObject();
                mergedTree["partner"] = Strings(cards.SelectMany(card => card["baumKontakt"]?["partner"] as JsonArray ?? []));
                mergedTree["staende"] = Strings(cards.SelectMany(card => card["baumKontakt"]?["staende"] as JsonArray ?? []));
                combined["baumKontakt"] = mergedTree;
            }
            foreach (var field in unknown)
                if (keeper[field] is null) combined[field] = cards.Select(card => card[field]).FirstOrDefault(value => value is not null)?.DeepClone();
            var deletions = new JsonArray();
            foreach (var duplicate in bindings.GroupBy(card => ContactFields.Text(ContactFields.Source(card, source)!, "id"), StringComparer.Ordinal))
            {
                if (duplicate.Key == ContactFields.Text(keptMapping, "id")) continue;
                var removed = duplicate.First();
                var removedMapping = ContactFields.Source(removed, source)!;
                deletions.Add(new JsonObject { ["mapping"] = removedMapping.DeepClone(),
                    ["keeperId"] = ContactFields.Text(keptMapping, "id"),
                    ["contentHash"] = ContactFields.Text(removedMapping, "fernInhaltSha256") is { Length: 64 } remoteHash ? remoteHash : ContactFields.ContentHash(removed),
                    ["keeperHash"] = ContactFields.Text(keptMapping, "fernInhaltSha256") is { Length: 64 } keeperHash ? keeperHash : ContactFields.ContentHash(provider),
                    ["desiredHash"] = desiredHash });
            }
            groups.Add(new JsonObject { ["keepId"] = ContactFields.Text(keeper, "id"),
                ["ids"] = new JsonArray(cards.Select(card => JsonValue.Create(ContactFields.Text(card, "id"))).ToArray()),
                ["metadata"] = combined, ["mapping"] = keptMapping.DeepClone(), ["deletions"] = deletions,
                ["contentFromId"] = ContactFields.Text(contentHolder, "id"),
                ["contentFields"] = new JsonArray(ContactFields.Names.Select(field => JsonValue.Create(field)).ToArray()) });
        }
        return result;
    }
}

internal static class SyncBaseline
{
    internal static string Hash(JsonObject value, IEnumerable<string> fields)
    {
        var projection = new JsonObject();
        foreach (var field in fields)
        {
            var node = value[field];
            // The frontend materializes empty/default fields when saving imported records.
            if (node is null || node.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0") continue;
            projection[field] = node.DeepClone();
        }
        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            MagnolienbaumCrypto.Canonical(projection))).ToLowerInvariant();
    }

    internal static bool Dirty(JsonObject value, JsonObject? mapping, IEnumerable<string> fields,
        JsonObject? unchangedRemote = null)
    {
        var hash = Hash(value, fields);
        if (mapping?["inhaltFormat"]?.GetValue<string>() == "windows-1" &&
            mapping["inhaltSha256"] is JsonValue baseline && baseline.TryGetValue<string>(out var saved))
            return saved != hash;
        // Shipped mappings have no content baseline. Only an unchanged remote
        // revision can establish one without hiding an unsynchronized local edit.
        return unchangedRemote is null || hash != Hash(unchangedRemote, fields);
    }

    internal static void RequireDeletionRevision(JsonObject? mapping, string etag)
    {
        if (string.IsNullOrWhiteSpace(etag) || mapping?["etag"]?.GetValue<string>() != etag)
            throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
    }

    internal static bool ContainsSavedResult(JsonObject result, JsonObject saved)
    {
        if (result["syncEpoch"] is not null && !JsonNode.DeepEquals(result["syncEpoch"], saved["syncEpoch"])) return false;
        if (result["syncAbgleichBasis"] is JsonObject basis && saved["syncAbgleichNachweis"] is JsonObject current)
        {
            if (!JsonNode.DeepEquals(result["transactionId"], current["transactionId"])) return false;
            result = result.DeepClone().AsObject();
            foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage" })
            {
                if (basis[field] is not JsonArray before || current[field] is not JsonArray local || result[field] is not JsonArray remote) return false;
                result[field] = Reconcile(before, local, remote);
            }
            foreach (var field in new[] { "termine", "aufgaben", "kontakte" })
            {
                if (basis["geloescht"]?[field] is not JsonArray before || current["geloescht"]?[field] is not JsonArray local || result["geloescht"]?[field] is not JsonArray remote) return false;
                result["geloescht"]![field] = Reconcile(before, local, remote);
            }
        }
        static bool Contains(JsonNode? expected, JsonNode? actual)
        {
            // Accept frontend defaults and redundant DAV/ICS fields, not missing domain content or mappings.
            if (expected is JsonObject obj) return actual is JsonObject other && obj.All(pair =>
                other.ContainsKey(pair.Key) ? Contains(pair.Value, other[pair.Key]) :
                pair.Value is null || pair.Value.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0" ||
                (pair.Key is "davHref" or "davEtag") && obj["syncQuellen"] is JsonObject ||
                pair.Key == "icsStatus" && obj["icsRoundtrip"] is JsonArray ||
                obj.ContainsKey("art") && (pair.Key == "rruleForm" || pair.Key == "intervall" && pair.Value.ToJsonString() == "1"));
            if (expected is JsonArray array) return actual is JsonArray otherArray && array.Count == otherArray.Count &&
                array.Zip(otherArray).All(pair => Contains(pair.First, pair.Second));
            return JsonNode.DeepEquals(expected, actual);
        }
        return new[] { "termine", "aufgaben", "kontakte", "jahrestage", "geloescht", "letzterSync", "letzteSyncs", "syncMetadaten" }
            .All(field => result.ContainsKey(field) && saved.ContainsKey(field) && Contains(result[field], saved[field]));
    }

    private static JsonArray Reconcile(JsonArray baseline, JsonArray current, JsonArray remote)
    {
        static string Key(JsonObject item) => ContactFields.Text(item, "uid") is { Length: > 0 } uid ? uid : ContactFields.Text(item, "id");
        var before = baseline.OfType<JsonObject>().ToDictionary(Key, StringComparer.Ordinal);
        var local = current.OfType<JsonObject>().ToDictionary(Key, StringComparer.Ordinal);
        var result = new JsonArray();
        foreach (var item in remote.OfType<JsonObject>())
        {
            var key = Key(item); before.TryGetValue(key, out var original); local.Remove(key, out var now);
            if (original is not null && now is null) continue;
            var merged = item.DeepClone().AsObject();
            if (now is not null && !JsonNode.DeepEquals(original, now))
                foreach (var field in (original?.Select(pair => pair.Key) ?? []).Concat(now.Select(pair => pair.Key)).Distinct())
                {
                    if (JsonNode.DeepEquals(original?[field], now[field])) continue;
                    if (now.ContainsKey(field)) merged[field] = now[field]?.DeepClone();
                    else merged.Remove(field);
                }
            result.Add(merged);
        }
        foreach (var (key, item) in local)
            if (!JsonNode.DeepEquals(before.GetValueOrDefault(key), item)) result.Add(item.DeepClone());
        return result;
    }
}

internal sealed class ContactSyncEngine
{
    internal async Task<ContactSyncResult> SyncAsync(string source, JsonArray contacts, JsonArray tombstones,
        long lastSync, IContactRemote remoteStore, CancellationToken cancellationToken = default,
        bool additiveOnly = false, Func<Task>? beforeMutation = null)
    {
        var local = new JsonArray(contacts.Select(item => item?.DeepClone()).ToArray());
        var dead = new JsonArray(tombstones.Select(item => item?.DeepClone()).ToArray());
        var received = await remoteStore.ReadAsync(cancellationToken).ConfigureAwait(false);
        var birthdayRepairs = new HashSet<string>(StringComparer.Ordinal);
        // Remember the uncorrected wire state separately: a normalized content
        // baseline must not hide a repair still owed to the remote source.
        var remote = received.Select(item =>
        {
            var data = item.Data.DeepClone().AsObject();
            if (ContactFields.NormalizeBirthday(data) && remoteStore.SupportsYearlessBirthdays) birthdayRepairs.Add(item.Id);
            return item with { Data = data };
        }).ToArray();
        foreach (var item in local.OfType<JsonObject>()) ContactFields.NormalizeBirthday(item);
        if (remote.Any(item => string.IsNullOrWhiteSpace(item.Id)) || remote.Select(item => item.Id).Distinct(StringComparer.Ordinal).Count() != remote.Length)
            throw new InvalidDataException(NativeLocalization.Gettext("The Nextcloud response was incomplete."));
        var remoteById = remote.ToDictionary(item => item.Id, StringComparer.Ordinal);
        if (!additiveOnly && NextcloudDavSelection.IsAddressBook(source))
            foreach (var tombstone in dead.OfType<JsonObject>())
            {
                var mapping = ContactFields.Source(tombstone, source);
                if (mapping?["id"]?.GetValue<string>() is string id && remoteById.TryGetValue(id, out var other))
                {
                    if (tombstone["kontaktDuplikat"] is JsonObject proof)
                    {
                        var keeperId = ContactFields.Text(proof, "keeperId");
                        var expected = ContactFields.Text(proof, "contentHash");
                        var keeperHash = ContactFields.Text(proof, "keeperHash") is { Length: 64 } prior ? prior : expected;
                        var desiredHash = ContactFields.Text(proof, "desiredHash") is { Length: 64 } desired ? desired : expected;
                        if (ContactFields.Text(proof, "source") != source || keeperId == id || expected.Length != 64 ||
                            !remoteById.TryGetValue(keeperId, out var keeper) || other.ETag.Length == 0 ||
                            ContactFields.ContentHash(other.Data) != expected ||
                            ContactFields.ContentHash(keeper.Data) is var currentKeeper && currentKeeper != keeperHash && currentKeeper != desiredHash ||
                            !local.OfType<JsonObject>().Any(card => ContactFields.Text(ContactFields.Source(card, source) ?? new JsonObject(), "id") == keeperId))
                            throw new InvalidOperationException("Die Kontaktkopien wurden gleichzeitig geändert; nichts wurde entfernt.");
                    }
                    else SyncBaseline.RequireDeletionRevision(mapping, other.ETag);
                }
            }
        var mappedIds = local.OfType<JsonObject>().Select(item => ContactFields.Source(item, source)?["id"]?.GetValue<string>())
            .Where(id => !string.IsNullOrWhiteSpace(id)).GroupBy(id => id!, StringComparer.Ordinal)
            .Where(group => group.Count() == 1).ToDictionary(group => group.Key, _ => true, StringComparer.Ordinal);
        var reservedIds = local.Concat(dead).OfType<JsonObject>()
            .Select(item => ContactFields.Source(item, source)?["id"]?.GetValue<string>())
            .Where(id => !string.IsNullOrWhiteSpace(id)).ToHashSet(StringComparer.Ordinal);
        var sameContent = remote.GroupBy(item => ContactFields.ContentHash(item.Data), StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.Ordinal);
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var errors = 0;

        foreach (var item in local.OfType<JsonObject>().ToArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var uid = ContactFields.Text(item, "uid");
            if (uid.Length == 0) { uid = $"mag-{Guid.NewGuid():N}@magnolie-organizer"; item["uid"] = uid; }
            var mapping = ContactFields.Source(item, source);
            var remoteId = mapping?["id"]?.GetValue<string>() ?? "";
            if (remoteId.Length == 0 && sameContent.TryGetValue(ContactFields.ContentHash(item), out var equal))
            {
                // A different provider UID does not make otherwise identical
                // contact data a new person. Names alone remain ambiguous.
                var hasContactDetails = new[] { "email", "telefon", "mobil" }.Any(field => ContactFields.Text(item, field).Length > 0) ||
                    new[] { "emails", "emailEintraege", "telefone" }.Any(field => item[field] is JsonArray entries && entries.Any(entry =>
                        entry is JsonValue text && text.TryGetValue<string>(out var value) && !string.IsNullOrWhiteSpace(value) ||
                        entry is JsonObject detail && ContactFields.Text(detail, "wert").Length > 0));
                var available = equal.Where(other => remoteById.ContainsKey(other.Id) && !reservedIds.Contains(other.Id)).ToArray();
                var sameUid = available.Where(other => ContactFields.Text(other.Data, "uid") == uid).Take(2).ToArray();
                // Windows .contact deletion ownership is tied to its embedded
                // Magnolie UID; do not infer a different identity there.
                var candidates = sameUid.Length > 0 ? sameUid : source != "windows-contacts" && hasContactDetails ? available.Take(2).ToArray() : [];
                if (candidates.Length == 1)
                {
                    var same = candidates[0];
                    ContactFields.SetSource(item, source, same);
                    mapping = ContactFields.Source(item, source); remoteId = same.Id;
                    mappedIds[remoteId] = true; reservedIds.Add(remoteId);
                }
                else if (source != "windows-contacts" && hasContactDetails)
                {
                    // An existing equal source record is not permission to create
                    // another one just because a local duplicate already owns it.
                    continue;
                }
            }
            if (additiveOnly && remoteId.Length == 0)
            {
                var matches = remoteById.Values.Where(value => ContactFields.Text(value.Data, "uid") == uid).ToArray();
                if (matches.Length == 1)
                {
                    var other = matches[0]; remoteById.Remove(other.Id);
                    if (other.Modified > (item["geaendert"]?.GetValue<long>() ?? 0))
                    {
                        ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    }
                    ContactFields.SetSource(item, source, other, remoteBaseline: true);
                }
                continue;
            }
            if (remoteId.Length > 0 && !mappedIds.ContainsKey(remoteId))
            {
                remoteById.Remove(remoteId);
                errors++;
                continue;
            }
            if (remoteId.Length > 0 && mappedIds.ContainsKey(remoteId))
            {
                if (!remoteById.Remove(remoteId, out var other))
                {
                    if (additiveOnly) { if (mapping is not null) mapping["inhaltSha256"] = ""; continue; }
                    if (!ContactFields.Dirty(item, mapping)) { local.Remove(item); deleted++; continue; }
                    if (beforeMutation is not null) await beforeMutation();
                    try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); exported++; }
                    catch { errors++; }
                    continue;
                }
                var localTime = item["geaendert"]?.GetValue<long>() ?? 0;
                var priorEtag = mapping?["etag"]?.GetValue<string>() ?? "";
                var remoteChanged = priorEtag.Length > 0 || other.ETag.Length > 0
                    ? priorEtag != other.ETag : (mapping?["geaendert"]?.GetValue<long>() ?? lastSync) != other.Modified;
                var localChanged = ContactFields.Dirty(item, mapping, other.Data);
                var conflictingChanges = remoteChanged && localChanged &&
                    ContactFields.ContentHash(item) != ContactFields.ContentHash(other.Data);
                var repairBirthday = birthdayRepairs.Contains(other.Id) ||
                    ContactFields.Text(item, "geburtstag").Length > 0 && ContactFields.Text(other.Data, "geburtstag").Length == 0 &&
                    (remoteStore.SupportsYearlessBirthdays || !ContactFields.Text(item, "geburtstag").StartsWith("--", StringComparison.Ordinal));
                var wroteRemote = false;
                if (additiveOnly)
                {
                    if (other.Modified > localTime)
                    {
                        ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    }
                    ContactFields.SetSource(item, source, other, remoteBaseline: true);
                }
                else if (conflictingChanges)
                {
                    var conflict = item.DeepClone().AsObject();
                    conflict["id"] = Guid.NewGuid().ToString("N");
                    conflict["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
                    conflict.Remove("syncQuellen"); conflict["sync"] = false;
                    local.Add(conflict);
                    ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else if (remoteChanged)
                {
                    ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else if (localChanged)
                {
                    if (beforeMutation is not null) await beforeMutation();
                    try { var changed = await remoteStore.UpdateAsync(other, uid, item, cancellationToken); ContactFields.SetSource(item, source, changed); updated++; wroteRemote = true; }
                    catch { errors++; }
                }
                else ContactFields.SetSource(item, source, other);
                if (!additiveOnly && repairBirthday && !wroteRemote && !conflictingChanges)
                {
                    if (beforeMutation is not null) await beforeMutation();
                    try { var changed = await remoteStore.UpdateAsync(other, uid, item, cancellationToken); ContactFields.SetSource(item, source, changed); updated++; }
                    catch { errors++; }
                }
                continue;
            }
            if (!additiveOnly)
            {
                if (beforeMutation is not null) await beforeMutation();
                try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); remoteById.Remove(made.Id); exported++; }
                catch { errors++; }
            }
        }

        if (!additiveOnly && errors == 0)
            foreach (var tombstone in dead.OfType<JsonObject>().ToArray())
            {
                var mapping = ContactFields.Source(tombstone, source);
                var id = mapping?["id"]?.GetValue<string>() ?? "";
                var other = id.Length > 0 ? remote.FirstOrDefault(item => item.Id == id) : null;
                if (other is null)
                {
                    if (tombstone["kontaktDuplikat"] is JsonObject proof && ContactFields.Text(proof, "source") == source)
                    {
                        var sources = tombstone["syncQuellen"] as JsonObject;
                        sources?.Remove(source);
                        if (sources is null || sources.Count == 0) dead.Remove(tombstone);
                    }
                    continue;
                }
                remoteById.Remove(id);
                if (beforeMutation is not null) await beforeMutation();
                try
                {
                    await remoteStore.DeleteAsync(other, ContactFields.Text(tombstone, "uid"), cancellationToken);
                    var sources = tombstone["syncQuellen"] as JsonObject;
                    sources?.Remove(source);
                    if (sources is null || sources.Count == 0) dead.Remove(tombstone);
                    deleted++;
                }
                catch { errors++; break; }
            }

        foreach (var other in remoteById.Values)
        {
            var item = other.Data.DeepClone().AsObject();
            item["id"] = Guid.NewGuid().ToString("N");
            if (ContactFields.Text(item, "uid").Length == 0)
                item["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
            item["geaendert"] = other.Modified;
            var importedRemote = other;
            if (!additiveOnly && birthdayRepairs.Contains(other.Id))
            {
                if (beforeMutation is not null) await beforeMutation();
                try { importedRemote = await remoteStore.UpdateAsync(other, ContactFields.Text(item, "uid"), item, cancellationToken); updated++; }
                catch { errors++; }
            }
            ContactFields.SetSource(item, source, importedRemote);
            local.Add(item); imported++;
        }

        return new ContactSyncResult(local, dead, new ContactSyncCounts(imported, exported, updated, deleted, errors));
    }
}
