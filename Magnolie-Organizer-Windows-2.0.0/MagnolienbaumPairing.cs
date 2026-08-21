using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class MagnolienbaumPairing
{
    internal static JsonObject CreateFile(JsonObject state, string address, int port, long now, byte[]? secret = null)
    {
        if (!System.Net.IPAddress.TryParse(address.Split('%')[0], out var ip) || IPAddressInvalid(ip, address) || port is < 1 or > 65535)
            throw new ArgumentException("Eine erreichbare numerische IP-Adresse und ein gültiger Port sind erforderlich.");
        var open = state["paarungen"] as JsonArray ?? new JsonArray();
        var valid = new JsonArray(open.OfType<JsonObject>().Where(item => (item["gueltigBis"]?.GetValue<long>() ?? 0) > now)
            .Select(item => item.DeepClone()).ToArray());
        if (valid.Count >= 20) throw new InvalidOperationException("Zu viele Paarungsdateien sind noch gültig.");
        secret ??= RandomNumberGenerator.GetBytes(32);
        if (secret.Length != 32) throw new ArgumentException("Das Paarungsgeheimnis ist ungültig.");
        var commitment = SHA256.HashData("magnolie-pair-commit-v2\0"u8.ToArray().Concat(secret).ToArray());
        var document = new JsonObject
        {
            ["magnolie"] = "magnolie-paarungsdatei", ["fassung"] = 2,
            ["paarung"] = MagnolienbaumCrypto.Base64Url(commitment), ["erstellt"] = now, ["gueltigBis"] = now + 900,
            ["ziel"] = new JsonObject { ["adresse"] = address, ["port"] = port },
            ["einlader"] = Identity(state), ["geheimnis"] = MagnolienbaumCrypto.Base64Url(secret)
        };
        document["mac"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(secret,
            "magnolie-pair-file-v2\0"u8.ToArray(), PublicPart(document)));
        valid.Add(new JsonObject { ["paarung"] = document["paarung"]!.DeepClone(),
            ["geheimnis"] = document["geheimnis"]!.DeepClone(), ["gueltigBis"] = now + 900 });
        state["paarungen"] = valid;
        return document;
    }

    internal static JsonObject ValidateFile(JsonObject document, long now)
    {
        var expected = new[] { "einlader", "erstellt", "fassung", "geheimnis", "gueltigBis", "mac", "magnolie", "paarung", "ziel" };
        if (!document.Select(item => item.Key).Order().SequenceEqual(expected) ||
            document["magnolie"]?.GetValue<string>() != "magnolie-paarungsdatei" || document["fassung"]?.GetValue<int>() != 2)
            throw new InvalidDataException("Die Paarungsdatei ist ungültig oder abgelaufen.");
        var created = document["erstellt"]?.GetValue<long>() ?? 0;
        var until = document["gueltigBis"]?.GetValue<long>() ?? 0;
        if (until <= now || until - created > 3600 || document["ziel"] is not JsonObject target ||
            document["einlader"] is not JsonObject inviter || target.Count != 2 || inviter.Count != 4)
            throw new InvalidDataException("Die Paarungsdatei ist ungültig oder abgelaufen.");
        var address = target["adresse"]?.GetValue<string>() ?? "";
        var port = target["port"]?.GetValue<int>() ?? 0;
        if (!System.Net.IPAddress.TryParse(address.Split('%')[0], out var ip) || IPAddressInvalid(ip, address) || port is < 1 or > 65535 ||
            string.IsNullOrEmpty(inviter["kennung"]?.GetValue<string>()) || !ValidPublic(inviter["oeffentlich"]?.GetValue<string>()))
            throw new InvalidDataException("Die Paarungsdatei ist beschädigt.");
        var secret = MagnolienbaumCrypto.ReadBase64Url(document["geheimnis"]?.GetValue<string>() ?? "", 32);
        var commitment = MagnolienbaumCrypto.ReadBase64Url(document["paarung"]?.GetValue<string>() ?? "", 32);
        var expectedCommitment = SHA256.HashData("magnolie-pair-commit-v2\0"u8.ToArray().Concat(secret).ToArray());
        var mac = MagnolienbaumCrypto.ReadBase64Url(document["mac"]?.GetValue<string>() ?? "", 32);
        var expectedMac = MagnolienbaumCrypto.Hmac(secret, "magnolie-pair-file-v2\0"u8.ToArray(), PublicPart(document));
        if (!CryptographicOperations.FixedTimeEquals(commitment, expectedCommitment) || !CryptographicOperations.FixedTimeEquals(mac, expectedMac))
            throw new InvalidDataException("Die Paarungsdatei wurde verändert.");
        return document;
    }

    internal static JsonObject BuildRequest(JsonObject state, JsonObject document, byte[]? nonce = null, long? now = null)
    {
        ValidateFile(document, now ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        var secret = MagnolienbaumCrypto.ReadBase64Url(document["geheimnis"]!.GetValue<string>(), 32);
        var core = new JsonObject { ["magnolie"] = "baum-paarung-2", ["paarung"] = document["paarung"]!.DeepClone(),
            ["nonce"] = MagnolienbaumCrypto.Base64Url(nonce ?? RandomNumberGenerator.GetBytes(32)), ["zweig"] = Identity(state) };
        core["beweis"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(secret,
            "magnolie-pair-request-v2\0"u8.ToArray(), core.DeepClone().AsObject()));
        return core;
    }

    internal static JsonObject AcceptRequest(JsonObject state, JsonObject request, string address, long now)
    {
        if (request.Count != 5 || request["magnolie"]?.GetValue<string>() != "baum-paarung-2" || request["zweig"] is not JsonObject branch)
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var requestHash = Convert.ToHexString(SHA256.HashData(MagnolienbaumCrypto.Canonical(request))).ToLowerInvariant();
        var consumed = state["paarungenVerbraucht"] as JsonArray ?? new JsonArray();
        foreach (var old in consumed.OfType<JsonObject>())
            if (old["paarung"]?.GetValue<string>() == request["paarung"]?.GetValue<string>() && old["anfrageHash"]?.GetValue<string>() == requestHash)
                return old["antwort"]!.DeepClone().AsObject();
        var invitations = state["paarungen"] as JsonArray ?? new JsonArray();
        var invitation = invitations.OfType<JsonObject>().FirstOrDefault(item => item["paarung"]?.GetValue<string>() == request["paarung"]?.GetValue<string>());
        if (invitation is null || (invitation["gueltigBis"]?.GetValue<long>() ?? 0) <= now)
            throw new InvalidDataException("Die Paarungsdatei ist nicht mehr gültig.");
        var secret = MagnolienbaumCrypto.ReadBase64Url(invitation["geheimnis"]!.GetValue<string>(), 32);
        _ = MagnolienbaumCrypto.ReadBase64Url(request["nonce"]?.GetValue<string>() ?? "", 32);
        if (branch.Count != 4 || string.IsNullOrEmpty(branch["kennung"]?.GetValue<string>()) || !ValidPublic(branch["oeffentlich"]?.GetValue<string>()))
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var proof = MagnolienbaumCrypto.ReadBase64Url(request["beweis"]?.GetValue<string>() ?? "", 32);
        var requestCore = request.DeepClone().AsObject(); requestCore.Remove("beweis");
        if (!CryptographicOperations.FixedTimeEquals(proof, MagnolienbaumCrypto.Hmac(secret, "magnolie-pair-request-v2\0"u8.ToArray(), requestCore)))
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        AddPartner(state, branch, address, true);
        var response = new JsonObject { ["magnolie"] = "baum-paarung-2-antwort", ["paarung"] = request["paarung"]!.DeepClone(),
            ["nonce"] = request["nonce"]!.DeepClone(), ["zweig"] = Identity(state) };
        response["beweis"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(secret,
            "magnolie-pair-response-v2\0"u8.ToArray(), response.DeepClone().AsObject()));
        state["paarungen"] = new JsonArray(invitations.OfType<JsonObject>().Where(item => item != invitation).Select(item => item.DeepClone()).ToArray());
        consumed.Add(new JsonObject { ["paarung"] = request["paarung"]!.DeepClone(), ["anfrageHash"] = requestHash,
            ["antwort"] = response.DeepClone(), ["behaltenBis"] = now + 86400 });
        state["paarungenVerbraucht"] = new JsonArray(consumed.OfType<JsonObject>()
            .Where(item => (item["behaltenBis"]?.GetValue<long>() ?? 0) > now).TakeLast(100).Select(item => item.DeepClone()).ToArray());
        return response;
    }

    internal static void ValidateResponse(JsonObject document, JsonObject request, JsonObject response)
    {
        var secret = MagnolienbaumCrypto.ReadBase64Url(document["geheimnis"]!.GetValue<string>(), 32);
        if (response.Count != 5 || response["magnolie"]?.GetValue<string>() != "baum-paarung-2-antwort" ||
            response["paarung"]?.GetValue<string>() != document["paarung"]?.GetValue<string>() ||
            response["nonce"]?.GetValue<string>() != request["nonce"]?.GetValue<string>() ||
            !JsonNode.DeepEquals(response["zweig"], document["einlader"]))
            throw new CryptographicException("Der andere Zweig hat die Paarungsdatei nicht bewiesen.");
        var proof = MagnolienbaumCrypto.ReadBase64Url(response["beweis"]!.GetValue<string>(), 32);
        var core = response.DeepClone().AsObject(); core.Remove("beweis");
        if (!CryptographicOperations.FixedTimeEquals(proof, MagnolienbaumCrypto.Hmac(secret, "magnolie-pair-response-v2\0"u8.ToArray(), core)))
            throw new CryptographicException("Der andere Zweig hat die Paarungsdatei nicht bewiesen.");
    }

    internal static JsonObject AddPartner(JsonObject state, JsonObject identity, string address, bool filePairing)
    {
        var expected = new[] { "kennung", "name", "oeffentlich", "port" };
        var fields = identity.Select(item => item.Key).ToHashSet(StringComparer.Ordinal);
        if (!fields.SetEquals(expected))
            throw new InvalidDataException("Die Zweigidentität ist unvollständig.");
        var id = identity["kennung"]?.GetValue<string>() ?? "";
        var name = identity["name"]?.GetValue<string>() ?? "";
        var publicKey = identity["oeffentlich"]?.GetValue<string>() ?? "";
        var port = identity["port"]?.GetValue<int>() ?? 0;
        if (id.Length is < 1 or > 32 || name.Length > 60 || !ValidPublic(publicKey) || port is < 1 or > 65535)
            throw new InvalidDataException("Die Zweigidentität ist ungültig.");

        var partners = state["partner"]!.AsArray();
        var partner = partners.OfType<JsonObject>().FirstOrDefault(item => item["kennung"]?.GetValue<string>() == id);
        if (partner is not null && partner["bestaetigt"]?.GetValue<bool>() == true && partner["oeffentlich"]?.GetValue<string>() != publicKey)
            throw new CryptographicException("Der Schlüssel dieses Zweigs hat sich geändert.");
        if (partner is null)
        {
            if (partners.Count >= 100 || partners.OfType<JsonObject>().Count(item => item["bestaetigt"]?.GetValue<bool>() != true) >= 20)
                throw new InvalidOperationException("Die Höchstzahl der Zweige ist erreicht.");
            partner = new JsonObject(); partners.Add(partner);
        }
        partner["kennung"] = id; partner["name"] = name.Length > 0 ? name : id;
        partner["oeffentlich"] = publicKey; if (address.Length > 0) partner["adresse"] = address;
        partner["port"] = port; partner["fernAdresse"] ??= ""; partner["fernPort"] ??= 8737;
        partner["zaehler_raus"] ??= 0; partner["zaehler_rein"] ??= 0; partner["zuletzt"] ??= "";
        partner["bestaetigt"] = filePairing; partner["wartet"] = !filePairing; partner["vertraut"] = filePairing;
        partner["protokoll"] = filePairing ? "baum-fs1" : "baum-1";
        partner["paarungsart"] = filePairing ? "datei-v2" : "lokal-v1";
        return partner;
    }

    internal static JsonObject Identity(JsonObject state) => new() { ["kennung"] = state["kennung"]!.DeepClone(),
        ["name"] = state["name"]!.DeepClone(), ["oeffentlich"] = state["oeffentlich"]!.DeepClone(), ["port"] = state["port"]!.DeepClone() };

    private static JsonObject PublicPart(JsonObject document) => new() { ["magnolie"] = document["magnolie"]!.DeepClone(),
        ["fassung"] = document["fassung"]!.DeepClone(), ["paarung"] = document["paarung"]!.DeepClone(),
        ["erstellt"] = document["erstellt"]!.DeepClone(), ["gueltigBis"] = document["gueltigBis"]!.DeepClone(),
        ["ziel"] = document["ziel"]!.DeepClone(), ["einlader"] = document["einlader"]!.DeepClone() };

    private static bool ValidPublic(string? value)
    {
        try
        {
            var raw = Convert.FromBase64String(value ?? "");
            return raw.Length == 32 && Convert.ToBase64String(raw) == value;
        }
        catch (FormatException) { return false; }
    }

    private static bool IPAddressInvalid(System.Net.IPAddress ip, string original) => ip.Equals(System.Net.IPAddress.Any) ||
        ip.Equals(System.Net.IPAddress.IPv6Any) || ip.IsIPv6Multicast || (ip.IsIPv6LinkLocal && !original.Contains('%'));
}
