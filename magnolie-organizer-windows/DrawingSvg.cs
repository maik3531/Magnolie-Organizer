using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows;

internal static class DrawingSvg
{
    private static bool InlinePng(string value)
    {
        try
        {
            var file = AttachmentFile.Parse(value, "drawing.png");
            return file.MimeType == "image/png" && file.Bytes.Length >= 24 &&
                BinaryPrimitives.ReadUInt32BigEndian(file.Bytes.AsSpan(16, 4)) is > 0 and <= 4096 &&
                BinaryPrimitives.ReadUInt32BigEndian(file.Bytes.AsSpan(20, 4)) is > 0 and <= 4096;
        }
        catch (InvalidDataException) { return false; }
    }
    internal static byte[] Validate(string value)
    {
        if (Encoding.UTF8.GetByteCount(value) > 64 * 1024 * 1024 || value.Contains("<!", StringComparison.Ordinal)) throw new InvalidDataException("Invalid drawing SVG.");
        using var reader = XmlReader.Create(new StringReader(value), new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 64 * 1024 * 1024 });
        var document = XDocument.Load(reader); XNamespace ns = "http://www.w3.org/2000/svg";
        if (document.Root?.Name != ns + "svg") throw new InvalidDataException("Invalid drawing SVG root.");
        foreach (var node in document.Root.DescendantsAndSelf())
        {
            if (node.Name.Namespace != ns || node.Name.LocalName is not ("svg" or "defs" or "mask" or "g" or "path" or "rect" or "linearGradient" or "stop" or "image") || node.Nodes().OfType<XText>().Any(text => !string.IsNullOrWhiteSpace(text.Value)))
                throw new InvalidDataException("Unsupported drawing SVG element.");
            foreach (var attribute in node.Attributes())
            {
                if (attribute.IsNamespaceDeclaration && node == document.Root && attribute.Value == ns.NamespaceName) continue;
                var name = attribute.Name.LocalName; var raw = attribute.Value;
                var allowed = attribute.Name.NamespaceName.Length == 0 && (name switch
                {
                    "x" or "y" or "width" or "height" or "stroke-width" or "opacity" or "viewBox" or "x1" or "y1" or "x2" or "y2" or "offset" => Regex.IsMatch(raw, "^[0-9. +%-]+$"),
                    "d" => Regex.IsMatch(raw, "^[MLACZ0-9. +,-]+$"),
                    "fill" => Regex.IsMatch(raw, @"^(#[0-9a-fA-F]{6}|white|none|url\(#gradient[0-9]+\))$"),
                    "stroke" or "stop-color" => Regex.IsMatch(raw, "^(#[0-9a-fA-F]{6}|white|none)$"),
                    "id" => Regex.IsMatch(raw, "^(erase|gradient)[0-9]+$"),
                    "mask" => Regex.IsMatch(raw, @"^url\(#erase[0-9]+\)$"),
                    "maskUnits" or "gradientUnits" => raw == "userSpaceOnUse",
                    "stroke-linecap" or "stroke-linejoin" => raw == "round",
                    "href" => node.Name.LocalName == "image" && InlinePng(raw),
                    _ => false
                });
                if (!allowed) throw new InvalidDataException("Unsupported drawing SVG attribute.");
            }
        }
        return Encoding.UTF8.GetBytes(value);
    }
}
