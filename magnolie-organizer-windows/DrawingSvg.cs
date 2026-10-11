using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal static class DrawingSvg
{
    internal static byte[] Validate(string value)
    {
        if (Encoding.UTF8.GetByteCount(value) > 64 * 1024 * 1024 || value.Contains("<!", StringComparison.Ordinal)) throw new InvalidDataException("Invalid drawing SVG.");
        using var reader = XmlReader.Create(new StringReader(value), new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 64 * 1024 * 1024 });
        var document = XDocument.Load(reader); XNamespace ns = "http://www.w3.org/2000/svg";
        if (document.Root?.Name != ns + "svg") throw new InvalidDataException("Invalid drawing SVG root.");
        foreach (var node in document.Root.DescendantsAndSelf())
        {
            if (node.Name.Namespace != ns || node.Name.LocalName is not ("svg" or "defs" or "mask" or "g" or "path" or "rect") || node.Nodes().OfType<XText>().Any(text => !string.IsNullOrWhiteSpace(text.Value)))
                throw new InvalidDataException("Unsupported drawing SVG element.");
            foreach (var attribute in node.Attributes())
            {
                if (attribute.IsNamespaceDeclaration && node == document.Root && attribute.Value == ns.NamespaceName) continue;
                var name = attribute.Name.LocalName; var raw = attribute.Value;
                var allowed = attribute.Name.NamespaceName.Length == 0 && (name switch
                {
                    "x" or "y" or "width" or "height" or "stroke-width" or "opacity" or "viewBox" => Regex.IsMatch(raw, "^[0-9. +%-]+$"),
                    "d" => Regex.IsMatch(raw, "^[MLAZ0-9. +,-]+$"),
                    "fill" or "stroke" => Regex.IsMatch(raw, "^(#[0-9a-fA-F]{6}|white|none)$"),
                    "id" => Regex.IsMatch(raw, "^erase[0-9]+$"),
                    "mask" => Regex.IsMatch(raw, @"^url\(#erase[0-9]+\)$"),
                    "maskUnits" => raw == "userSpaceOnUse",
                    "stroke-linecap" or "stroke-linejoin" => raw == "round",
                    _ => false
                });
                if (!allowed) throw new InvalidDataException("Unsupported drawing SVG attribute.");
            }
        }
        return Encoding.UTF8.GetBytes(value);
    }
}
