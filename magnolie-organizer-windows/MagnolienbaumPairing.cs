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
        if (created < 0 || until <= created || until <= now || until - created > 3600 || document["ziel"] is not JsonObject target ||
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

    internal static JsonObject SetSharingPermission(JsonObject state, string id, string publicKey, bool allowed)
    {
        var partner = state["partner"]!.AsArray().OfType<JsonObject>().FirstOrDefault(value => value["kennung"]?.GetValue<string>() == id);
        if (partner?["bestaetigt"]?.GetValue<bool>() != true || partner["oeffentlich"]?.GetValue<string>() != publicKey)
            throw new InvalidOperationException("Die Paarungsanfrage gilt nicht mehr.");
        partner["weitergabeErlaubt"] = allowed;
        if (!allowed && state["paarungen"] is JsonArray invitations)
            state["paarungen"] = new JsonArray(invitations.OfType<JsonObject>()
                .Where(value => value["weitergabeVon"]?.GetValue<string>() != id)
                .Select(value => value.DeepClone()).ToArray());
        return partner;
    }

    internal static JsonObject CreateSharedFile(JsonObject state, string sponsorId, string sponsorPublicKey,
        JsonObject recipient, string address, int port, long now)
    {
        var sponsor = state["partner"]!.AsArray().OfType<JsonObject>().FirstOrDefault(value => value["kennung"]?.GetValue<string>() == sponsorId);
        if (sponsor?["bestaetigt"]?.GetValue<bool>() != true || sponsor["weitergabeErlaubt"]?.GetValue<bool>() != true ||
            sponsor["oeffentlich"]?.GetValue<string>() != sponsorPublicKey)
            throw new InvalidOperationException(NativeLocalization.Gettext("Sharing this connection is not allowed."));
        if (!recipient.Select(value => value.Key).ToHashSet(StringComparer.Ordinal).SetEquals(new[] { "kennung", "name", "oeffentlich", "port" }))
            throw new InvalidDataException("Die Zweigidentität ist unvollständig.");
        var id = recipient["kennung"]?.GetValue<string>() ?? "";
        var key = recipient["oeffentlich"]?.GetValue<string>() ?? "";
        if (id.Length is < 1 or > 32 || id == sponsorId || id == state["kennung"]?.GetValue<string>() ||
            !ValidPublic(key) || key == sponsorPublicKey || key == state["oeffentlich"]?.GetValue<string>())
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var document = CreateFile(state, address, port, now);
        var invitation = state["paarungen"]!.AsArray().OfType<JsonObject>().Single(value => value["paarung"]!.GetValue<string>() == document["paarung"]!.GetValue<string>());
        invitation["weitergabeVon"] = sponsorId; invitation["weitergabeSchluessel"] = sponsorPublicKey;
        invitation["zielKennung"] = id; invitation["zielOeffentlich"] = key;
        return document;
    }

    // Called only after the enclosing FS1 request has authenticated the current peer.
    internal static JsonObject SharedRequest(JsonObject state, JsonObject peer, JsonObject request, long now)
    {
        if (peer["bestaetigt"]?.GetValue<bool>() != true ||
            !state["partner"]!.AsArray().OfType<JsonObject>().Any(value => ReferenceEquals(value, peer)))
            throw new InvalidDataException("Dieser Zweig wurde noch nicht bestätigt.");
        var operation = request["aktion"]?.GetValue<string>() ?? "";
        var id = request["id"]?.GetValue<string>() ?? "";
        _ = MagnolienbaumCrypto.ReadBase64Url(id, 16);
        if (operation == "einladung")
        {
            if (!request.Select(value => value.Key).ToHashSet().SetEquals(new[] { "aktion", "id", "ziel", "adresse", "port" }))
                throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
            if (peer["weitergabeErlaubt"]?.GetValue<bool>() != true)
                throw new InvalidOperationException(NativeLocalization.Gettext("Sharing this connection is not allowed."));
            var hash = Convert.ToHexString(SHA256.HashData(MagnolienbaumCrypto.Canonical(request)));
            var invitations = state["paarungen"] as JsonArray ?? new JsonArray();
            var prior = invitations.OfType<JsonObject>().FirstOrDefault(value =>
                value["weitergabeAnfrage"]?.GetValue<string>() == id &&
                value["weitergabeVon"]?.GetValue<string>() == peer["kennung"]!.GetValue<string>());
            if (prior is not null)
            {
                if (prior["weitergabeHash"]?.GetValue<string>() != hash ||
                    prior["weitergabeSchluessel"]?.GetValue<string>() != peer["oeffentlich"]!.GetValue<string>() ||
                    prior["gueltigBis"]!.GetValue<long>() <= now)
                    throw new InvalidDataException("Die Paarungsanfrage gilt nicht mehr.");
                return prior["weitergabeDatei"]!.DeepClone().AsObject();
            }
            var document = CreateSharedFile(state, peer["kennung"]!.GetValue<string>(), peer["oeffentlich"]!.GetValue<string>(),
                request["ziel"]!.AsObject(), request["adresse"]!.GetValue<string>(), request["port"]!.GetValue<int>(), now);
            var created = state["paarungen"]!.AsArray().OfType<JsonObject>().Single(value =>
                value["paarung"]!.GetValue<string>() == document["paarung"]!.GetValue<string>());
            created["weitergabeAnfrage"] = id; created["weitergabeHash"] = hash; created["weitergabeDatei"] = document.DeepClone();
            return document;
        }
        if (operation == "angebot")
        {
            if (!request.Select(value => value.Key).ToHashSet().SetEquals(new[] { "aktion", "id", "datei", "ziel" }) ||
                request["ziel"]?["kennung"]?.GetValue<string>() != state["kennung"]!.GetValue<string>() ||
                request["ziel"]?["oeffentlich"]?.GetValue<string>() != state["oeffentlich"]!.GetValue<string>())
                throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
            var document = request["datei"]!.AsObject(); ValidateFile(document, now);
            if (document["einlader"]!["kennung"]!.GetValue<string>() == state["kennung"]!.GetValue<string>())
                throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
            var completed = (state["weitergabeAbschluesse"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(value =>
                value["id"]!.GetValue<string>() == id && value["gueltigBis"]!.GetValue<long>() > now);
            if (completed is not null)
            {
                if (completed["von"]!.GetValue<string>() != peer["kennung"]!.GetValue<string>() ||
                    completed["schluessel"]!.GetValue<string>() != peer["oeffentlich"]!.GetValue<string>() ||
                    completed["home"]!.GetValue<string>() != document["einlader"]!["kennung"]!.GetValue<string>() ||
                    completed["homeSchluessel"]!.GetValue<string>() != document["einlader"]!["oeffentlich"]!.GetValue<string>())
                    throw new InvalidDataException("Die Paarungsanfrage gilt nicht mehr.");
                var accepted = completed["angenommen"]!.GetValue<bool>();
                if (accepted && !state["partner"]!.AsArray().OfType<JsonObject>().Any(value => value["bestaetigt"]?.GetValue<bool>() == true &&
                    value["kennung"]?.GetValue<string>() == completed["home"]!.GetValue<string>() &&
                    value["oeffentlich"]?.GetValue<string>() == completed["homeSchluessel"]!.GetValue<string>()))
                    throw new InvalidDataException("Die Paarungsanfrage gilt nicht mehr.");
                return new JsonObject { ["id"] = id, ["wartet"] = false, ["angenommen"] = accepted };
            }
            var offers = new JsonArray((state["weitergabeAngebote"] as JsonArray ?? new JsonArray()).OfType<JsonObject>()
                .Where(value => value["datei"]!["gueltigBis"]!.GetValue<long>() > now).Select(value => value.DeepClone()).ToArray());
            var previous = offers.OfType<JsonObject>().FirstOrDefault(value => value["id"]!.GetValue<string>() == id);
            var offer = new JsonObject { ["id"] = id, ["von"] = peer["kennung"]!.DeepClone(),
                ["schluessel"] = peer["oeffentlich"]!.DeepClone(), ["datei"] = document.DeepClone(), ["ziel"] = request["ziel"]!.DeepClone() };
            var original = previous?.DeepClone().AsObject(); original?.Remove("anfrage");
            if (original is not null && !JsonNode.DeepEquals(original, offer)) throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
            if (previous is null)
            {
                if (offers.Count >= 8) throw new InvalidOperationException(NativeLocalization.Gettext("Too many pairing requests are waiting."));
                offers.Add(offer);
            }
            state["weitergabeAngebote"] = offers;
            return new JsonObject { ["id"] = id, ["wartet"] = true };
        }
        throw new InvalidDataException("Unbekannter Endpunkt.");
    }

    internal static void CompleteSharedOffer(JsonObject state, JsonObject offer, bool accepted, long now)
    {
        var receipts = new JsonArray((state["weitergabeAbschluesse"] as JsonArray ?? new JsonArray()).OfType<JsonObject>()
            .Where(value => value["gueltigBis"]!.GetValue<long>() > now).Select(value => value.DeepClone()).ToArray());
        if (receipts.Count >= 100) throw new InvalidOperationException(NativeLocalization.Gettext("Too many pairing requests are waiting."));
        receipts.Add(new JsonObject { ["id"] = offer["id"]!.DeepClone(), ["von"] = offer["von"]!.DeepClone(),
            ["schluessel"] = offer["schluessel"]!.DeepClone(), ["home"] = offer["datei"]!["einlader"]!["kennung"]!.DeepClone(),
            ["homeSchluessel"] = offer["datei"]!["einlader"]!["oeffentlich"]!.DeepClone(), ["angenommen"] = accepted,
            ["gueltigBis"] = now + 1800 });
        state["weitergabeAbschluesse"] = receipts;
        state["weitergabeAngebote"]!.AsArray().Remove(offer);
    }

    internal static JsonObject BuildRequest(JsonObject state, JsonObject document, byte[]? nonce = null, long? now = null)
    {
        ValidateFile(document, now ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        if (nonce is not null && nonce.Length != 32) throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
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
            if ((old["behaltenBis"]?.GetValue<long>() ?? 0) > now &&
                old["paarung"]?.GetValue<string>() == request["paarung"]?.GetValue<string>() && old["anfrageHash"]?.GetValue<string>() == requestHash)
            {
                if (old["zielKennung"] is JsonNode recipientId)
                {
                    var recipient = state["partner"]!.AsArray().OfType<JsonObject>().FirstOrDefault(value => value["kennung"]?.GetValue<string>() == recipientId.GetValue<string>());
                    if (recipient?["bestaetigt"]?.GetValue<bool>() != true || recipient["oeffentlich"]?.GetValue<string>() != old["zielOeffentlich"]?.GetValue<string>())
                        throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
                }
                return old["antwort"]!.DeepClone().AsObject();
            }
        var invitations = state["paarungen"] as JsonArray ?? new JsonArray();
        var invitation = invitations.OfType<JsonObject>().FirstOrDefault(item => item["paarung"]?.GetValue<string>() == request["paarung"]?.GetValue<string>());
        if (invitation is null || (invitation["gueltigBis"]?.GetValue<long>() ?? 0) <= now)
            throw new InvalidDataException("Die Paarungsdatei ist nicht mehr gültig.");
        var secret = MagnolienbaumCrypto.ReadBase64Url(invitation["geheimnis"]!.GetValue<string>(), 32);
        _ = MagnolienbaumCrypto.ReadBase64Url(request["nonce"]?.GetValue<string>() ?? "", 32);
        if (branch.Count != 4 || string.IsNullOrEmpty(branch["kennung"]?.GetValue<string>()) || !ValidPublic(branch["oeffentlich"]?.GetValue<string>()))
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var delegated = invitation["weitergabeVon"]?.GetValue<string>();
        var sponsor = delegated is null ? null : state["partner"]!.AsArray().OfType<JsonObject>().FirstOrDefault(value => value["kennung"]?.GetValue<string>() == delegated);
        if (delegated is not null && (sponsor?["bestaetigt"]?.GetValue<bool>() != true || sponsor["weitergabeErlaubt"]?.GetValue<bool>() != true ||
                sponsor["oeffentlich"]?.GetValue<string>() != invitation["weitergabeSchluessel"]?.GetValue<string>() ||
                branch["kennung"]?.GetValue<string>() != invitation["zielKennung"]?.GetValue<string>() ||
                branch["oeffentlich"]?.GetValue<string>() != invitation["zielOeffentlich"]?.GetValue<string>()))
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var proof = MagnolienbaumCrypto.ReadBase64Url(request["beweis"]?.GetValue<string>() ?? "", 32);
        var requestCore = request.DeepClone().AsObject(); requestCore.Remove("beweis");
        if (!CryptographicOperations.FixedTimeEquals(proof, MagnolienbaumCrypto.Hmac(secret, "magnolie-pair-request-v2\0"u8.ToArray(), requestCore)))
            throw new InvalidDataException("Die Paarungsanfrage ist ungültig.");
        var wasConfirmed = state["partner"]!.AsArray().OfType<JsonObject>().Any(value =>
            value["kennung"]?.GetValue<string>() == branch["kennung"]?.GetValue<string>() && value["bestaetigt"]?.GetValue<bool>() == true);
        var paired = AddPartner(state, branch, address, true);
        if (delegated is not null && !wasConfirmed)
        {
            paired["vertraut"] = sponsor!["vertraut"]?.GetValue<bool>() == true;
            paired["weitergabeVon"] = delegated; paired["weitergabeErlaubt"] = false;
            paired["weitergabeSchluessel"] = sponsor!["oeffentlich"]!.DeepClone();
        }
        var response = new JsonObject { ["magnolie"] = "baum-paarung-2-antwort", ["paarung"] = request["paarung"]!.DeepClone(),
            ["nonce"] = request["nonce"]!.DeepClone(), ["zweig"] = Identity(state) };
        response["beweis"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(secret,
            "magnolie-pair-response-v2\0"u8.ToArray(), response.DeepClone().AsObject()));
        state["paarungen"] = new JsonArray(invitations.OfType<JsonObject>().Where(item => item != invitation).Select(item => item.DeepClone()).ToArray());
        var receipt = new JsonObject { ["paarung"] = request["paarung"]!.DeepClone(), ["anfrageHash"] = requestHash,
            ["antwort"] = response.DeepClone(), ["behaltenBis"] = now + 86400 };
        if (delegated is not null) { receipt["zielKennung"] = paired["kennung"]!.DeepClone(); receipt["zielOeffentlich"] = paired["oeffentlich"]!.DeepClone(); }
        consumed.Add(receipt);
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
        if (partner is not null && (partner["bestaetigt"]?.GetValue<bool>() == true || partner["anfrageAusgehend"]?.GetValue<bool>() == true) && partner["oeffentlich"]?.GetValue<string>() != publicKey)
            throw new CryptographicException("Der Schlüssel dieses Zweigs hat sich geändert.");
        if (partner?["bestaetigt"]?.GetValue<bool>() == true)
        {
            // File proof authorizes a protocol upgrade, not renewed consent or identity replacement.
            // Unauthenticated v1 requests must remain a complete no-op for this record.
            if (filePairing && (partner["protokoll"]?.GetValue<string>() ?? "baum-1") is "baum-1" or "baum-fs1")
            {
                partner["protokoll"] = "baum-fs1";
                partner["paarungsart"] = "datei-v2";
            }
            return partner;
        }
        if (partner?["anfrageAusgehend"]?.GetValue<bool>() == true && !filePairing) return partner;
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
        if (filePairing) partner["wartetFern"] = false;
        partner["protokoll"] = filePairing ? "baum-fs1" : "baum-1";
        partner["paarungsart"] = filePairing ? "datei-v2" : "lokal-v1";
        return partner;
    }

    internal static JsonObject Identity(JsonObject state) => new() { ["kennung"] = state["kennung"]!.DeepClone(),
        ["name"] = state["name"]!.DeepClone(), ["oeffentlich"] = state["oeffentlich"]!.DeepClone(), ["port"] = state["port"]!.DeepClone() };

    internal static string NormalizeFingerprint(string value)
    {
        var clean = new string(value.Where(Uri.IsHexDigit).ToArray()).ToUpperInvariant();
        return clean.Length == 16 ? string.Join("-", clean.Chunk(4).Select(chars => new string(chars))) : "";
    }

    internal static JsonObject PreparePinnedRequest(JsonObject state, JsonObject identity, string address, string expectedFingerprint)
    {
        var expected = NormalizeFingerprint(expectedFingerprint);
        if (expected.Length == 0) throw new InvalidDataException("Der eingegebene Fingerabdruck ist unvollständig.");
        if (!ValidPublic(identity["oeffentlich"]?.GetValue<string>()) ||
            MagnolienbaumCrypto.Fingerprint(Convert.FromBase64String(identity["oeffentlich"]!.GetValue<string>())) != expected)
            throw new CryptographicException("Der Fingerabdruck stimmt nicht überein.");
        var peer = AddPartner(state, identity, address, false);
        if (peer["bestaetigt"]?.GetValue<bool>() != true)
        {
            peer["anfrageAusgehend"] = true; peer["wartetFern"] = true; peer["wartet"] = false;
            peer["paarungsart"] = "anfrage-pin-v1";
        }
        return peer;
    }

    internal static bool CompletePinnedRequest(JsonObject state, string id, string publicKey, string ownId, string ownPublicKey)
    {
        var peer = (state["partner"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(value => value["kennung"]?.GetValue<string>() == id);
        if (peer is null || peer["oeffentlich"]?.GetValue<string>() != publicKey || state["kennung"]?.GetValue<string>() != ownId ||
            state["oeffentlich"]?.GetValue<string>() != ownPublicKey || peer["anfrageAusgehend"]?.GetValue<bool>() != true ||
            peer["bestaetigt"]?.GetValue<bool>() == true) return false;
        peer["bestaetigt"] = true; peer["wartet"] = false; peer["wartetFern"] = false; peer["protokoll"] = "baum-fs1";
        return true;
    }

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
