using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record AttachmentFile(string MimeType, string Extension, string FileName, byte[] Bytes)
{
    internal const int MaxDataUrlLength = 12_000_000;
    internal const int MaxBytes = 8 * 1024 * 1024;

    private static readonly IReadOnlyDictionary<string, (string Extension, byte[] Magic)> Formats =
        new Dictionary<string, (string, byte[])>(StringComparer.Ordinal)
        {
            ["image/jpeg"] = (".jpg", [0xff, 0xd8, 0xff]),
            ["image/png"] = (".png", [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
            ["image/webp"] = (".webp", [0x52, 0x49, 0x46, 0x46]),
            ["image/gif"] = (".gif", [0x47, 0x49, 0x46, 0x38]),
            ["application/pdf"] = (".pdf", [0x25, 0x50, 0x44, 0x46, 0x2d])
        };

    internal static AttachmentFile Parse(string dataUrl, string requestedName)
    {
        if (string.IsNullOrEmpty(dataUrl) || dataUrl.Length > MaxDataUrlLength)
            throw new InvalidDataException("Die Anhangdaten sind leer oder zu groß.");

        var separator = dataUrl.IndexOf(',');
        if (separator < 0) throw new InvalidDataException("Die Anhangdaten sind ungültig.");
        var prefix = dataUrl[..separator];
        if (!prefix.StartsWith("data:", StringComparison.Ordinal) ||
            !prefix.EndsWith(";base64", StringComparison.Ordinal))
            throw new InvalidDataException("Die Anhangdaten sind ungültig.");
        var mime = prefix[5..^7];
        if (!Formats.TryGetValue(mime, out var format))
            throw new InvalidDataException("Der Dateityp des Anhangs wird nicht unterstützt.");

        var encoded = dataUrl[(separator + 1)..];
        if (encoded.Length == 0 || encoded.Length % 4 != 0 ||
            !Regex.IsMatch(encoded, "^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"))
            throw new InvalidDataException("Der Anhang enthält kein gültiges Base64.");
        if ((long)encoded.Length / 4 * 3 > MaxBytes + 2L)
            throw new InvalidDataException("Der Anhang ist größer als 8 MiB.");

        byte[] bytes;
        try { bytes = Convert.FromBase64String(encoded); }
        catch (FormatException error) { throw new InvalidDataException("Der Anhang enthält kein gültiges Base64.", error); }
        if (!Convert.ToBase64String(bytes).Equals(encoded, StringComparison.Ordinal))
            throw new InvalidDataException("Der Anhang enthält kein kanonisches Base64.");
        if (bytes.Length == 0 || bytes.Length > MaxBytes)
            throw new InvalidDataException("Der Anhang ist leer oder größer als 8 MiB.");
        if (!HasMagic(mime, bytes, format.Magic))
            throw new InvalidDataException("Dateityp und Inhalt des Anhangs stimmen nicht überein.");

        return new AttachmentFile(mime, format.Extension,
            SafeFileName(requestedName, format.Extension), bytes);
    }

    internal static string SafeFileName(string requestedName, string extension)
    {
        var leaf = requestedName.IndexOfAny(['/', '\\']) >= 0 ? "" : requestedName;
        const string windowsInvalid = "<>:\"/\\|?*";
        leaf = new string(leaf.Where(character => !char.IsControl(character) &&
            !windowsInvalid.Contains(character)).ToArray()).Trim().TrimEnd('.');
        var stem = Path.GetFileNameWithoutExtension(leaf).Trim().TrimEnd('.');
        if (stem.Length == 0 || Regex.IsMatch(stem, "^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", RegexOptions.IgnoreCase))
            stem = "Anhang";
        var maximumStem = 180 - extension.Length;
        if (stem.Length > maximumStem) stem = stem[..maximumStem].TrimEnd(' ', '.');
        return stem + extension;
    }

    private static bool HasMagic(string mime, byte[] bytes, byte[] magic)
    {
        if (bytes.Length < magic.Length || !bytes.AsSpan(0, magic.Length).SequenceEqual(magic)) return false;
        if (mime == "image/webp")
            return bytes.Length >= 12 && bytes.AsSpan(8, 4).SequenceEqual("WEBP"u8);
        if (mime == "image/gif")
            return bytes.Length >= 6 && (bytes.AsSpan(0, 6).SequenceEqual("GIF87a"u8) ||
                                         bytes.AsSpan(0, 6).SequenceEqual("GIF89a"u8));
        return true;
    }
}
