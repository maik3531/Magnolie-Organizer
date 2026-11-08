using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Explicit desktop media metadata bridge. Ordinary file offers stay unchanged.
// Parsing grants no native source/receiver, current intent, book or gallery rights.
internal sealed record NativeMediaOffer(JsonObject Offer, DeviceFileManifest Manifest, JsonObject Settings,
    string MediaType, JsonObject MimeTypes, JsonObject Originals);

internal static class MediaOfferEnvelope
{
    internal const string Kind = "file_transfer.media_offer";

    internal static JsonObject Create(DeviceFileManifest manifest, JsonObject settings, string mediaType,
        JsonObject mimeTypes, JsonObject originals, long now, string? messageId = null)
    {
        var message = DeviceFileOfferEnvelope.Create(manifest, now, messageId);
        var offer = message["body"]!.DeepClone();
        message["kind"] = Kind;
        message["body"] = new JsonObject { ["format"] = 1, ["offer"] = offer, ["settings"] = settings.DeepClone(),
            ["media_type"] = mediaType, ["mime_types"] = mimeTypes.DeepClone(), ["originals"] = originals.DeepClone() };
        _ = Validate(message, manifest.SenderId, manifest.ReceiverId, now); return message;
    }

    internal static NativeMediaOffer Validate(JsonObject message, string senderId, string receiverId, long now)
    {
        if (TelefonCrypto.Canonical(message).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes ||
            TelefonMessagingContract.String(message, "kind") != Kind || now >= TelefonProtocolContract.Integer(message["expires_ms"]))
            throw DeviceFileControl.Error("media_offer_invalid_envelope");
        var body = TelefonProtocolContract.ExactObject(message["body"]!, "format", "offer", "settings", "media_type", "mime_types", "originals");
        if (TelefonProtocolContract.Integer(body["format"]) != 1 || body["offer"] is not JsonObject rawOffer || body["settings"] is not JsonObject settings ||
            body["mime_types"] is not JsonObject mime || body["originals"] is not JsonObject originals)
            throw DeviceFileControl.Error("media_offer_invalid_schema");
        var offer = message.DeepClone().AsObject(); offer["kind"] = DeviceFileOfferEnvelope.Kind; offer["body"] = rawOffer.DeepClone();
        var manifest = DeviceFileOfferEnvelope.Validate(offer, senderId, receiverId, now);
        var kind = TelefonMessagingContract.String(body, "media_type");
        MediaSyncSettings.ValidateStart(new JsonObject { ["format"] = 1, ["settings"] = settings.DeepClone() });
        if (!MediaSyncSettings.TransferRequestedFor(settings, kind, toPhone: true)) throw DeviceFileControl.Error("media_offer_sending_intent_required");
        var ids = manifest.Files.Select(file => file.Id).ToHashSet(StringComparer.Ordinal);
        if (!ids.SetEquals(mime.Select(item => item.Key)) || originals.Any(item => !ids.Contains(item.Key)) ||
            MediaSyncSettings.Effective(settings)["collection_mode"]!.GetValue<string>() == "phone_inventory" && originals.Count != ids.Count)
            throw DeviceFileControl.Error("media_offer_original_scope_required");
        var prefix = kind == "images" ? "image" : "video";
        if (mime.Any(item => item.Value is not JsonValue value || !value.TryGetValue<string>(out var text) || text.Length > 133 ||
            !Regex.IsMatch(text, "\\A" + prefix + "/[a-z0-9][a-z0-9.+-]{0,126}\\z", RegexOptions.CultureInvariant)))
            throw DeviceFileControl.Error("media_offer_mime_invalid");
        var known = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (_, reference) in originals)
        {
            var original = TelefonProtocolContract.ExactObject(reference!, "source_epoch", "photo_id", "media_type", "manifest_sha256", "file_id", "original_size", "original_sha256", "receipt_sha256");
            if (TelefonMessagingContract.String(original, "media_type") != kind ||
                !Regex.IsMatch(TelefonMessagingContract.String(original, "file_id"), "\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant) ||
                TelefonProtocolContract.Integer(original["original_size"]) is < 1 or > DeviceFileManifest.MaxFileBytes ||
                new[] { "source_epoch", "photo_id", "manifest_sha256", "original_sha256", "receipt_sha256" }.Any(key => !DeviceFileControl.Hash(TelefonMessagingContract.String(original, key))) ||
                !known.Add(DeviceFileControl.Digest("magnolie-media-offer-original-v1\0", original)))
                throw DeviceFileControl.Error("media_offer_original_reference_invalid");
        }
        return new(offer, manifest, settings.DeepClone().AsObject(), kind, mime.DeepClone().AsObject(), originals.DeepClone().AsObject());
    }
}
