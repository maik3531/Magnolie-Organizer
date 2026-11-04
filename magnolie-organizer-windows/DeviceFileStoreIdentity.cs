using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Unlike LoadOrCreateIdentity, this neither bootstraps keys nor refreshes
    // the display name. A media route must use the already protected identity.
    internal NativeFileControlIdentity ReadFileIdentity()
    {
        lock (gate)
        {
            if (RestoreFenced) throw DeviceFileControl.Error("file_identity_unavailable");
            var text = files.Read(paths.TelefonIdentity, 64 * 1024);
            var encrypted = files.Read(paths.TelefonIdentityKey, 4096);
            if (text is null || encrypted is null) throw DeviceFileControl.Error("file_identity_unavailable");
            var value = JsonNode.Parse(text) as JsonObject ?? throw DeviceFileControl.Error("file_identity_invalid");
            var id = value["device_id"]?.GetValue<string>() ?? "";
            var name = value["display_name"]?.GetValue<string>() ?? "";
            if (!Guid.TryParseExact(id, "D", out _) || value["role"]?.GetValue<string>() != "desktop" || name.Length is < 1 or > 60)
                throw DeviceFileControl.Error("file_identity_invalid");
            var publicKey = ReadBase64(value, "static_public", 32);
            var privateKey = Open("identity", id, Convert.FromBase64String(encrypted));
            try
            {
                if (privateKey.Length != 32 || !TelefonCrypto.X25519Public(privateKey).SequenceEqual(publicKey))
                    throw DeviceFileControl.Error("file_identity_invalid");
                return new(id, Convert.ToHexString(SHA256.HashData(publicKey)).ToLowerInvariant());
            }
            finally { CryptographicOperations.ZeroMemory(privateKey); }
        }
    }
}
