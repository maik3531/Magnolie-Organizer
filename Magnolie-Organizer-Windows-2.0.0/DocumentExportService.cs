using System.Globalization;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal sealed record DocumentSheetGroup(string Name, int Span);
internal sealed record DocumentChartSeries(string Name, string Color, IReadOnlyDictionary<string, double> Points);
internal sealed record DocumentChart(string Title, IReadOnlyList<DocumentChartSeries> Series);
internal sealed record DocumentSheet(string Name, IReadOnlyList<string> Columns, IReadOnlyList<IReadOnlyList<string>> Rows,
    IReadOnlyList<DocumentSheetGroup>? Groups = null, string Layout = "table",
    IReadOnlyList<IReadOnlyList<string>>? CellStyles = null,
    IReadOnlyList<IReadOnlyList<IReadOnlyList<string>>>? TextColors = null, DocumentChart? Chart = null);

internal static class DocumentExportService
{
    private static readonly XNamespace Office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0";
    private static readonly XNamespace Text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0";
    private static readonly XNamespace Table = "urn:oasis:names:tc:opendocument:xmlns:table:1.0";
    private static readonly XNamespace Style = "urn:oasis:names:tc:opendocument:xmlns:style:1.0";
    private static readonly XNamespace Fo = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0";
    private static readonly XNamespace Manifest = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0";
    private static readonly XNamespace Draw = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0";
    private static readonly XNamespace XLink = "http://www.w3.org/1999/xlink";
    private static readonly XNamespace Svg = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0";

    private static readonly IReadOnlyDictionary<string, (string Fill, string Text)> PlannerColors =
        new Dictionary<string, (string, string)>(StringComparer.Ordinal)
        {
            [""] = ("#ffffff", "#17140f"), ["empty"] = ("#e5e5e5", "#998f80"),
            ["saturday"] = ("#fffbc7", "#17140f"), ["sunday"] = ("#f5c38f", "#17140f"),
            ["vacation"] = ("#fff200", "#17140f"), ["personal-vacation"] = ("#d9eee7", "#17140f"),
            ["holiday"] = ("#f4c6ca", "#b01820"), ["holiday-vacation"] = ("#ffdd57", "#b01820"),
            ["outside"] = ("#e5e5e5", "#998f80"), ["week-number"] = ("#5c3f25", "#ffffff")
        };

    internal static byte[] CreateLetter(JsonElement contact, string sender = "", string layout = "din5008-b")
    {
        string Field(JsonElement item, string name) => Value(item, name).Trim();
        string[] Parts(string property)
        {
            var raw = StringArray(contact, "vcardRoundtrip");
            if (raw.Length == 0) raw = StringArray(contact, "vcardName");
            foreach (var line in raw)
            {
                var colon = line.IndexOf(':');
                if (colon < 0 || !line[..colon].Split(';')[0].Split('.').Last().Equals(property, StringComparison.OrdinalIgnoreCase)) continue;
                var parts = new List<string>();
                var part = new StringBuilder();
                var escaped = false;
                foreach (var character in line[(colon + 1)..])
                {
                    if (escaped) { part.Append(character is 'n' or 'N' ? '\n' : character); escaped = false; }
                    else if (character == '\\') escaped = true;
                    else if (character == ';') { parts.Add(part.ToString().Trim()); part.Clear(); }
                    else part.Append(property == "N" && character == ',' ? ' ' : character);
                }
                if (escaped) part.Append('\\');
                parts.Add(part.ToString().Trim());
                return parts.ToArray();
            }
            return [];
        }
        var first = Field(contact, "vorname");
        var last = Field(contact, "nachname");
        var display = Field(contact, "anzeigename");
        var recipientName = display.Length > 0 ? display : $"{first} {last}".Trim();
        var components = Parts("N").Concat(Enumerable.Repeat("", 5)).Take(5).ToArray();
        // Retain imported components only while the editable name still matches.
        if (display.Length == 0 && components[1] == first && components[0] == last)
        {
            var full = string.Join(" ", new[] { 3, 1, 2, 0, 4 }.Select(index => components[index]).Where(value => value.Length > 0));
            if (full.Length > 0) recipientName = full;
        }
        var company = Field(contact, "firma");
        var organization = Parts("ORG");
        if (organization.Length > 0 && organization[0] == company) company = string.Join("\n", organization);
        if (recipientName == company || (company.Length > 0 && recipientName == company.ReplaceLineEndings("\n").Split('\n')[0])) recipientName = "";
        var address = contact;
        if (contact.TryGetProperty("anschriften", out var addresses) && addresses.ValueKind == JsonValueKind.Array)
            foreach (var candidate in addresses.EnumerateArray())
                if (new[] { "postfach", "zusatz", "strasse", "plz", "ort", "region", "land" }.Any(key => Field(candidate, key).Length > 0))
                { address = candidate; break; }
        var recipient = new[]
        {
            recipientName, company, Field(address, "zusatz"), Field(address, "postfach"), Field(address, "strasse"),
            $"{Field(address, "plz")} {Field(address, "ort")}".Trim(), Field(address, "region"), Field(address, "land")
        }.SelectMany(value => value.ReplaceLineEndings("\n").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)).ToArray();
        if (recipient.Length == 0) throw new ArgumentException(NativeLocalization.Gettext("This contact card has no postal address."));
        var senderLines = sender.ReplaceLineEndings("\n").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var content = new XDocument(new XDeclaration("1.0", "UTF-8", null),
            new XElement(Office + "document-content", NamespaceAttributes(), new XAttribute(Office + "version", "1.2"),
                new XElement(Office + "body", new XElement(Office + "text",
                    new XElement(Text + "p", new XAttribute(Text + "style-name", layout == "din5008" ? "SenderDin" : "SenderCompact"),
                        string.Join(" · ", senderLines)),
                    recipient.Select(line => new XElement(Text + "p", new XAttribute(Text + "style-name", "Recipient"), line)),
                    new XElement(Text + "p", new XAttribute(Text + "style-name", "Date"), DateTime.Today.ToString("d")),
                    new XElement(Text + "p", new XAttribute(Text + "style-name", "Subject"), layout == "din5008" ? NativeLocalization.Gettext("Subject") : NativeLocalization.Gettext("Your letter")),
                    new XElement(Text + "p", new XAttribute(Text + "style-name", "Body"), NativeLocalization.Gettext("Dear Sir or Madam,")),
                    new XElement(Text + "p", new XAttribute(Text + "style-name", "Body"), ""),
                    new XElement(Text + "p", new XAttribute(Text + "style-name", "Body"), NativeLocalization.Gettext("Yours sincerely,"))))));
        var styles = new XDocument(new XDeclaration("1.0", "UTF-8", null),
            new XElement(Office + "document-styles", NamespaceAttributes(), new XAttribute(Office + "version", "1.2"),
                new XElement(Office + "styles",
                    ParagraphStyle("SenderDin", "2.5cm", "0.15cm", "8pt"),
                    ParagraphStyle("SenderCompact", "0cm", "0.3cm", "8pt"),
                    ParagraphStyle("Recipient", "0cm", "0cm", "11pt"),
                    ParagraphStyle("Date", "1.5cm", "0.5cm", "11pt", "right"),
                    ParagraphStyle("Subject", "0cm", "0.7cm", "11pt", "left", true),
                    ParagraphStyle("Body", "0cm", "0.45cm", "11pt")),
                new XElement(Office + "automatic-styles",
                    new XElement(Style + "page-layout", new XAttribute(Style + "name", "A4Letter"),
                        new XElement(Style + "page-layout-properties", new XAttribute(Fo + "page-width", "21cm"),
                            new XAttribute(Fo + "page-height", "29.7cm"), new XAttribute(Fo + "margin-top", "2cm"),
                            new XAttribute(Fo + "margin-bottom", "2cm"), new XAttribute(Fo + "margin-left", "2.5cm"),
                            new XAttribute(Fo + "margin-right", "2cm")))),
                new XElement(Office + "master-styles", new XElement(Style + "master-page", new XAttribute(Style + "name", "Standard"),
                    new XAttribute(Style + "page-layout-name", "A4Letter")))));
        if (layout is not ("compact" or "kompakt"))
        {
            // The shipped din5008 ID means Form B, never Form A.
            var formA = layout == "din5008-a";
            var returnAddress = string.Join(" · ", senderLines);
            // Liberation Sans/Arial advance widths; unknown glyphs reserve one em.
            int[] widths = [
                278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,
                556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,
                1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,
                667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,
                333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,
                556,556,333,500,278,556,500,722,500,500,500,334,260,334,584];
            double Width(string value, int points) => value.EnumerateRunes().Sum(rune =>
                rune.Value is >= 32 and <= 126 ? widths[rune.Value - 32] : rune.Value == 183 ? 278 : 1000) * points / 1000.0;
            const double available = 83.5 * 72 / 25.4;
            var returnPoints = new[] { 8, 7, 6 }.FirstOrDefault(points => Width(returnAddress, points) <= available);
            int FontSize(IEnumerable<string> contentLines, int maximum)
            {
                foreach (var points in new[] { 10, 8 })
                {
                    var lines = 0;
                    var fits = true;
                    foreach (var line in contentLines)
                    {
                        lines++;
                        double used = 0;
                        foreach (var word in line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
                        {
                            var width = Width(word, points);
                            if (width > available) fits = false;
                            var space = used > 0 ? Width(" ", points) : 0;
                            if (used + space + width > available) { lines++; used = width; }
                            else used += space + width;
                        }
                    }
                    if (fits && lines <= maximum) return points;
                }
                return 0;
            }
            var recipientPoints = FontSize(recipient, 6);
            var senderPoints = formA ? 10 : FontSize(senderLines, 5);
            if (returnPoints == 0 || recipientPoints == 0 || senderPoints == 0)
                throw new ArgumentException(NativeLocalization.Gettext("The address is too long for the letter's address field. Shorten the return address or recipient, or choose the compact template."));
            XElement P(string name, string value = "") => new(Text + "p", new XAttribute(Text + "style-name", name), value);
            XElement LetterStyle(string name, string size, params XAttribute[] properties) =>
                new(Style + "style", new XAttribute(Style + "name", name), new XAttribute(Style + "family", "paragraph"),
                    new XElement(Style + "paragraph-properties", properties),
                    new XElement(Style + "text-properties", new XAttribute(Style + "font-name", "Liberation Sans"),
                        new XAttribute(Fo + "font-family", "Liberation Sans"), new XAttribute(Fo + "font-size", size)));
            XElement Frame(string name, string x, string y, string width, string height, params object[] paragraphs) =>
                new(Draw + "frame", new XAttribute(Draw + "style-name", name == "Anschriftfeld" ? "Rahmen" : "DatumRahmen"), new XAttribute(Draw + "name", name),
                    new XAttribute(Text + "anchor-type", "page"), new XAttribute(Text + "anchor-page-number", "1"),
                    new XAttribute(Svg + "x", x), new XAttribute(Svg + "y", y), new XAttribute(Svg + "width", width),
                    new XAttribute(Svg + "height", height), new XElement(Draw + "text-box", paragraphs));
            XElement Mark(string name, string y, string end) => new(Draw + "line",
                new XAttribute(Draw + "style-name", "Marke"), new XAttribute(Draw + "name", name),
                new XAttribute(Text + "anchor-type", "page"), new XAttribute(Text + "anchor-page-number", "1"), new XAttribute(Svg + "x1", "1.5cm"),
                new XAttribute(Svg + "x2", end), new XAttribute(Svg + "y1", y), new XAttribute(Svg + "y2", y));
            var objects = P("Objekte");
            if (!formA && senderLines.Length > 0)
                objects.Add(Frame("Absenderblock", "2cm", "2cm", "8.5cm", "2.5cm", senderLines.Select(line => P("Absender", line))));
            objects.Add(Frame("Anschriftfeld", "2cm", formA ? "2.7cm" : "4.5cm", "8.5cm", "4.5cm",
                P("Rueckadresse", returnAddress), recipient.Select(line => P("Anschrift", line))));
            var city = senderLines.Reverse().Select(line => System.Text.RegularExpressions.Regex.Match(line, @"^(?:[A-Z]{1,2}-)?[0-9]{4,6}\s+(.+)$"))
                .FirstOrDefault(match => match.Success)?.Groups[1].Value ?? "";
            objects.Add(Frame("Datum", "12.5cm", formA ? "7.55cm" : "2cm", "6.5cm", formA ? "0.65cm" : "2.5cm",
                P("Datum", (!formA && city.Length > 0 ? city + ", " : "") + DateTime.Today.ToString("d"))));
            objects.Add(Mark("Faltmarke-oben", formA ? "8.7cm" : "10.5cm", "2.2cm"),
                Mark("Lochmarke", "14.85cm", "2.5cm"), Mark("Faltmarke-unten", formA ? "18.5cm" : "21cm", "2.2cm"));
            content.Root!.Element(Office + "body")!.ReplaceNodes(new XElement(Office + "text", objects,
                P("Briefbeginn"), P("Standard", NativeLocalization.Gettext("Dear Sir or Madam,")),
                P("Standard"), P("Standard"), P("Standard", NativeLocalization.Gettext("Yours sincerely,"))));
            var returnStyle = LetterStyle("Rueckadresse", $"{returnPoints}pt",
                new XAttribute(Fo + "margin-top", "0cm"), new XAttribute(Fo + "margin-bottom", "0cm"),
                new XAttribute(Fo + "line-height", "0.5cm"));
            returnStyle.Element(Style + "text-properties")!.Add(new XAttribute(Style + "text-underline-style", "solid"),
                new XAttribute(Style + "text-underline-width", "auto"));
            styles.Root!.Element(Office + "styles")!.ReplaceNodes(
                new XElement(Style + "style", new XAttribute(Style + "name", "Frame"), new XAttribute(Style + "family", "graphic")),
                new XElement(Style + "default-style", new XAttribute(Style + "family", "paragraph"),
                    new XElement(Style + "paragraph-properties", new XAttribute(Fo + "margin-top", "0cm"),
                        new XAttribute(Fo + "margin-bottom", "0cm"), new XAttribute(Fo + "line-height", "100%")),
                    new XElement(Style + "text-properties", new XAttribute(Style + "font-name", "Liberation Sans"),
                        new XAttribute(Fo + "font-family", "Liberation Sans"), new XAttribute(Fo + "font-size", "11pt"),
                        new XAttribute(Style + "letter-kerning", "true"))),
                LetterStyle("Standard", "11pt", new XAttribute(Fo + "margin-bottom", "0.42cm"), new XAttribute(Fo + "line-height", "120%")),
                LetterStyle("Objekte", "1pt", new XAttribute(Fo + "margin", "0cm"), new XAttribute(Fo + "line-height", "1%")),
                new XElement(Style + "style", new XAttribute(Style + "name", "Briefbeginn"), new XAttribute(Style + "family", "paragraph"),
                    new XAttribute(Style + "parent-style-name", "Standard"), new XElement(Style + "paragraph-properties",
                        new XAttribute(Fo + "margin-top", formA ? "6.75cm" : "8.55cm"), new XAttribute(Fo + "margin-bottom", "0.42cm"))),
                returnStyle,
                LetterStyle("Anschrift", $"{recipientPoints}pt",
                    new XAttribute(Fo + "margin-bottom", "0cm"), new XAttribute(Fo + "line-height", "0.455cm")),
                LetterStyle("Absender", $"{senderPoints}pt",
                    new XAttribute(Fo + "margin-bottom", "0cm"), new XAttribute(Fo + "line-height", "0.455cm")),
                LetterStyle("Datum", "10pt", new XAttribute(Fo + "text-align", "end")));
            var automatic = new XElement(Office + "automatic-styles");
            content.Root.AddFirst(automatic);
            foreach (var root in new[] { content.Root, styles.Root })
                root.AddFirst(new XElement(Office + "font-face-decls", new XElement(Style + "font-face",
                    new XAttribute(Style + "name", "Liberation Sans"), new XAttribute(Svg + "font-family", "Liberation Sans"))));
            foreach (var name in new[] { "Rahmen", "DatumRahmen", "Marke" })
            {
                var graphic = new XElement(Style + "graphic-properties", new XAttribute(Draw + "stroke", name == "Marke" ? "solid" : "none"),
                    new XAttribute(Draw + "fill", "none"), new XAttribute(Style + "horizontal-pos", "from-left"),
                    new XAttribute(Style + "horizontal-rel", "page"), new XAttribute(Style + "vertical-pos", "from-top"),
                    new XAttribute(Style + "vertical-rel", "page"));
                if (name != "Marke") graphic.Add(new XAttribute(Style + "wrap", "run-through"), new XAttribute(Fo + "border", "none"), new XAttribute(Fo + "padding", "0cm"));
                else graphic.Add(new XAttribute(Svg + "stroke-color", "#555555"), new XAttribute(Svg + "stroke-width", "0.02cm"));
                if (name == "Rahmen") graphic.Add(new XAttribute(Fo + "padding-top", "1.27cm"));
                automatic.Add(new XElement(Style + "style", new XAttribute(Style + "name", name), new XAttribute(Style + "family", "graphic"),
                    name != "Marke" ? new XAttribute(Style + "parent-style-name", "Frame") : null, graphic));
            }
        }
        var manifest = new XDocument(new XDeclaration("1.0", "UTF-8", null),
            new XElement(Manifest + "manifest", new XAttribute(XNamespace.Xmlns + "manifest", Manifest), new XAttribute(Manifest + "version", "1.2"),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "/"),
                    new XAttribute(Manifest + "media-type", "application/vnd.oasis.opendocument.text"), new XAttribute(Manifest + "version", "1.2")),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "content.xml"), new XAttribute(Manifest + "media-type", "text/xml")),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "styles.xml"), new XAttribute(Manifest + "media-type", "text/xml"))));
        using var stream = new MemoryStream();
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true))
        {
            WriteEntry(archive, "mimetype", "application/vnd.oasis.opendocument.text", CompressionLevel.NoCompression);
            WriteEntry(archive, "content.xml", content.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            WriteEntry(archive, "styles.xml", styles.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            WriteEntry(archive, "META-INF/manifest.xml", manifest.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
        }
        return stream.ToArray();
    }

    internal static string LetterFileName(string path) => Path.ChangeExtension(path, ".odt");

    internal static byte[] CreateSpreadsheet(IReadOnlyList<DocumentSheet> sheets)
    {
        ValidateSheets(sheets);
        var pictures = new List<(string Path, string Content)>();
        var spreadsheet = new XElement(Office + "spreadsheet");
        for (var index = 0; index < sheets.Count; index++)
        {
            var sheet = sheets[index];
            var safeName = SafeSheetName(sheet.Name);
            spreadsheet.Add(BuildTable(sheet, safeName, index, pictures));
        }
        var address = sheets.Select((sheet, index) => (sheet, index)).FirstOrDefault(item => item.sheet.Layout == "addresses");
        if (address.sheet is not null && address.sheet.Rows.Count > 0)
        {
            var name = SafeSheetName(address.sheet.Name).Replace("'", "''", StringComparison.Ordinal);
            spreadsheet.Add(new XElement(Table + "database-ranges",
                new XElement(Table + "database-range", new XAttribute(Table + "name", "AddressFilter"),
                    new XAttribute(Table + "target-range-address", $"$'{name}'.A2:{ColumnName(address.sheet.Columns.Count)}{address.sheet.Rows.Count + 2}"),
                    new XAttribute(Table + "display-filter-buttons", "true"))));
        }
        var content = new XDocument(new XDeclaration("1.0", "UTF-8", null),
            new XElement(Office + "document-content", NamespaceAttributes(), new XAttribute(Office + "version", "1.2"),
                BuildAutomaticStyles(sheets), new XElement(Office + "body", spreadsheet)));
        var styles = BuildStylesDocument();
        var manifest = new XDocument(new XDeclaration("1.0", "UTF-8", null),
            new XElement(Manifest + "manifest", new XAttribute(XNamespace.Xmlns + "manifest", Manifest), new XAttribute(Manifest + "version", "1.2"),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "/"), new XAttribute(Manifest + "media-type", "application/vnd.oasis.opendocument.spreadsheet"), new XAttribute(Manifest + "version", "1.2")),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "content.xml"), new XAttribute(Manifest + "media-type", "text/xml")),
                new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", "styles.xml"), new XAttribute(Manifest + "media-type", "text/xml")),
                pictures.Select(picture => new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", picture.Path), new XAttribute(Manifest + "media-type", "image/svg+xml")))));
        using var stream = new MemoryStream();
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true))
        {
            WriteEntry(archive, "mimetype", "application/vnd.oasis.opendocument.spreadsheet", CompressionLevel.NoCompression);
            WriteEntry(archive, "content.xml", content.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            WriteEntry(archive, "styles.xml", styles.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            foreach (var picture in pictures) WriteEntry(archive, picture.Path, picture.Content, CompressionLevel.Optimal);
            WriteEntry(archive, "META-INF/manifest.xml", manifest.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
        }
        return stream.ToArray();
    }

    internal static DocumentSheet ReadSheet(JsonElement message, string defaultName)
    {
        var columns = StringArray(message, "spalten");
        var layout = Value(message, "cmd") == "adressen_ods" ? "addresses" : Value(message, "layout") switch
        {
            "year" => "year", "month" => "month", _ => "table"
        };
        IReadOnlyList<IReadOnlyList<IReadOnlyList<string>>>? textColors = null;
        IReadOnlyList<IReadOnlyList<string>> rows;
        if (layout is "year" or "month" && message.TryGetProperty("inhalte", out var contents))
            (rows, textColors) = ReadPlannerRows(contents, columns.Length);
        else rows = ReadRows(message, "zeilen", columns.Length);
        var styles = ReadStyleRows(message, columns.Length, rows.Count);
        return new DocumentSheet(Value(message, "titel") is { Length: > 0 } title ? title : defaultName,
            columns, rows, null, layout, styles, textColors);
    }

    internal static IReadOnlyList<DocumentSheet> ReadHealthSheets(JsonElement message)
    {
        if (!message.TryGetProperty("tabellen", out var tables) || tables.ValueKind != JsonValueKind.Array)
            throw new ArgumentException("Die Gesundheitstabellen fehlen.");
        var result = new List<DocumentSheet>();
        foreach (var table in tables.EnumerateArray())
        {
            var title = Value(table, "titel") is { Length: > 0 } value ? value : "Gesundheit";
            if (table.TryGetProperty("diagramme", out var charts))
            {
                result.AddRange(ReadChartSheets(title, charts));
                continue;
            }
            var left = StringArray(table, "links");
            var right = StringArray(table, "rechts");
            if (left.Length == 0 || right.Length == 0) throw new ArgumentException("Die Gesundheitsspalten fehlen.");
            var sourceRows = ReadRows(table, "zeilen", left.Length + right.Length);
            var rows = sourceRows.Select(row => (IReadOnlyList<string>)row.Take(left.Length).Append("").Concat(row.Skip(left.Length)).ToArray()).ToList();
            var chart = table.TryGetProperty("diagramm", out var chartElement) ? ReadChart(chartElement) : null;
            if (chart is not null)
            {
                rows = rows.Take(20).ToList();
                while (rows.Count < 20) rows.Add(Enumerable.Repeat("", left.Length + 1 + right.Length).ToArray());
            }
            var columns = left.Append("").Concat(right).ToArray();
            var rightTitle = Value(table, "rechtsTitel") is { Length: > 0 } heading ? heading : title;
            result.Add(new DocumentSheet(title, columns, rows, new[]
            {
                new DocumentSheetGroup("", left.Length), new DocumentSheetGroup("", 1),
                new DocumentSheetGroup(rightTitle, right.Length)
            }, chart is null ? "health" : "health-chart", Chart: chart));
        }
        if (result.Count == 0) throw new ArgumentException("Es wurden keine exportierbaren Gesundheitstabellen übergeben.");
        return result;
    }

    private static XElement BuildTable(DocumentSheet sheet, string name, int sheetIndex,
        ICollection<(string Path, string Content)> pictures)
    {
        var table = new XElement(Table + "table", new XAttribute(Table + "name", name),
            new XAttribute(Table + "style-name", $"ta{sheetIndex}"),
            new XAttribute(Table + "print-ranges", $"$'{name.Replace("'", "''", StringComparison.Ordinal)}'.A1:{ColumnName(sheet.Columns.Count)}{PrintRowCount(sheet)}"));
        for (var column = 0; column < sheet.Columns.Count; column++)
            table.Add(new XElement(Table + "table-column", new XAttribute(Table + "style-name", ColumnStyle(sheet, sheetIndex, column))));
        table.Add(MergedRow(new[] { new DocumentSheetGroup(sheet.Name, sheet.Columns.Count) },
            sheet.Layout == "month" ? "ceMonthTitle" : "ceTitle", "roTitle"));
        if (sheet.Layout == "health-chart" && sheet.Groups is { Count: > 0 })
        {
            table.Add(HealthChartHeadingRow(sheet));
            AddHealthChartRows(table, sheet, sheetIndex, pictures);
            return table;
        }
        if (sheet.Layout == "health" && sheet.Groups is { Count: > 0 })
        {
            table.Add(MergedRow(sheet.Groups, "ceGroup", "roHeading"));
            table.Add(Row(sheet.Columns, "ceHeading", "roHeading"));
        }
        else
        {
            if (sheet.Groups is { Count: > 0 }) table.Add(MergedRow(sheet.Groups, "ceGroup", "roHeading"));
            table.Add(Row(sheet.Columns, HeadingStyle(sheet), "roHeading"));
        }
        for (var rowIndex = 0; rowIndex < sheet.Rows.Count; rowIndex++)
        {
            var rowStyle = sheet.Layout == "month" ? "roMonth" : sheet.Layout == "year" ? "roYear" :
                sheet.Layout.StartsWith("health", StringComparison.Ordinal) ? "roHealth" : "roData";
            table.Add(Row(sheet.Rows[rowIndex], rowStyle, sheet, rowIndex));
        }
        return table;
    }

    private static XElement HealthChartHeadingRow(DocumentSheet sheet)
    {
        var groups = sheet.Groups!;
        var left = groups[0].Span;
        var right = groups[2].Span;
        return new XElement(Table + "table-row", new XAttribute(Table + "style-name", "roHeading"),
            sheet.Columns.Take(left).Select(value => Cell(value, "ceHeading")),
            Cell("", "ceSpacer"),
            new XElement(Table + "table-cell", new XAttribute(Table + "style-name", "ceChartTitle"),
                new XAttribute(Table + "number-columns-spanned", right), new XAttribute(Office + "value-type", "string"), Paragraph(groups[2].Name)),
            Enumerable.Range(1, right - 1).Select(_ => new XElement(Table + "covered-table-cell")));
    }

    private static void AddHealthChartRows(XElement table, DocumentSheet sheet, int sheetIndex,
        ICollection<(string Path, string Content)> pictures)
    {
        var groups = sheet.Groups!;
        var left = groups[0].Span;
        var right = groups[2].Span;
        var path = $"Pictures/chart-{sheetIndex + 1}.svg";
        pictures.Add((path, CreateChartSvg(sheet.Chart!)));
        for (var rowIndex = 0; rowIndex < sheet.Rows.Count; rowIndex++)
        {
            var row = new XElement(Table + "table-row", new XAttribute(Table + "style-name", "roHealth"),
                sheet.Rows[rowIndex].Take(left).Select(value => TypedCell(value, "ceData", null, true)),
                Cell("", "ceSpacer"));
            if (rowIndex == 0)
            {
                row.Add(new XElement(Table + "table-cell", new XAttribute(Table + "style-name", "ceChartArea"),
                    new XAttribute(Table + "number-columns-spanned", right), new XAttribute(Table + "number-rows-spanned", sheet.Rows.Count),
                    new XElement(Draw + "frame", new XAttribute(Draw + "name", $"Diagramm {sheetIndex + 1}"),
                        new XAttribute(Text + "anchor-type", "cell"), new XAttribute(Svg + "x", "0.25cm"), new XAttribute(Svg + "y", "0.2cm"),
                        new XAttribute(Svg + "width", "12.5cm"), new XAttribute(Svg + "height", "11.4cm"),
                        new XElement(Draw + "image", new XAttribute(XLink + "href", path), new XAttribute(XLink + "type", "simple"),
                            new XAttribute(XLink + "show", "embed"), new XAttribute(XLink + "actuate", "onLoad")))),
                    Enumerable.Range(1, right - 1).Select(_ => new XElement(Table + "covered-table-cell")));
            }
            else row.Add(Enumerable.Range(0, right).Select(_ => new XElement(Table + "covered-table-cell")));
            table.Add(row);
        }
    }

    private static XElement Row(IReadOnlyList<string> values, string rowStyle, DocumentSheet sheet, int rowIndex) =>
        new(Table + "table-row", new XAttribute(Table + "style-name", rowStyle), values.Select((value, column) =>
        {
            var style = CellStyle(sheet, rowIndex, column);
            var colors = sheet.TextColors is not null ? sheet.TextColors[rowIndex][column] : null;
            var cell = TypedCell(value, style, colors, sheet.Layout is not ("addresses" or "year" or "month"));
            if (sheet.Layout.StartsWith("health", StringComparison.Ordinal) && sheet.Groups is { } groups && column == groups[0].Span)
                cell.SetAttributeValue(Table + "style-name", "ceSpacer");
            return cell;
        }));

    private static XElement Row(IEnumerable<string> values, string cellStyle, string rowStyle) =>
        new(Table + "table-row", new XAttribute(Table + "style-name", rowStyle), values.Select(value => Cell(value, cellStyle)));

    private static XElement Cell(string value, string style) => new(Table + "table-cell",
        new XAttribute(Table + "style-name", style), new XAttribute(Office + "value-type", "string"), Paragraph(value));

    private static XElement TypedCell(string value, string style, IReadOnlyList<string>? colors, bool typeNumbers)
    {
        var cell = new XElement(Table + "table-cell", new XAttribute(Table + "style-name", style));
        if (typeNumbers && value.Length > 0 && double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number))
        {
            cell.Add(new XAttribute(Office + "value-type", "float"), new XAttribute(Office + "value", number.ToString("G15", CultureInfo.InvariantCulture)));
        }
        else cell.Add(new XAttribute(Office + "value-type", "string"));
        cell.Add(Paragraph(value, colors));
        return cell;
    }

    private static XElement MergedRow(IEnumerable<DocumentSheetGroup> groups, string cellStyle, string rowStyle) =>
        new(Table + "table-row", new XAttribute(Table + "style-name", rowStyle), groups.SelectMany(group =>
            new[] { new XElement(Table + "table-cell", new XAttribute(Table + "style-name", cellStyle),
                new XAttribute(Table + "number-columns-spanned", group.Span), new XAttribute(Office + "value-type", "string"), Paragraph(group.Name)) }
                .Concat(Enumerable.Range(1, group.Span - 1).Select(_ => new XElement(Table + "covered-table-cell")))));

    private static XElement Paragraph(string value, IReadOnlyList<string>? colors = null)
    {
        var lines = value.ReplaceLineEndings("\n").Split('\n');
        return new XElement(Text + "p", lines.SelectMany((line, index) =>
        {
            var content = colors is not null && index < colors.Count && SafeColor(colors[index]) is { } color
                ? (object)new XElement(Text + "span", new XAttribute(Text + "style-name", "tx" + color[1..]), line)
                : line;
            return index == 0 ? new[] { content } : new object[] { new XElement(Text + "line-break"), content };
        }));
    }

    private static XElement BuildAutomaticStyles(IReadOnlyList<DocumentSheet> sheets)
    {
        var styles = new XElement(Office + "automatic-styles",
            RowStyle("roTitle", "0.9cm"), RowStyle("roHeading", "0.75cm"), RowStyle("roData", "0.75cm", true),
            RowStyle("roHealth", "0.6cm"), RowStyle("roYear", "0.43cm"), RowStyle("roMonth", "2.5cm"),
            CellStyleElement("ceTitle", "#ffffff", "#29231d", "none", "15pt", true, "left", "middle", "Liberation Serif"),
            CellStyleElement("ceMonthTitle", "#5c3f25", "#ffffff", "none", "17pt", true, "center", "middle", "Liberation Sans"),
            CellStyleElement("ceHeading", "#f0e4ec", "#4c2740", "0.03cm solid #9b6386", "7pt", true, "center", "middle"),
            CellStyleElement("ceYearHeading", "#f1ede4", "#17140f", "0.02cm solid #29251d", "8pt", true, "center", "middle"),
            CellStyleElement("ceMonthHeading", "#8b6a35", "#ffffff", "0.02cm solid #6d5129", "8pt", true, "center", "middle"),
            CellStyleElement("ceAddressHeading", "#7d95bd", "#ffffff", "0.02cm solid #526b94", "8pt", true, "center", "middle"),
            CellStyleElement("ceChartTitle", "#ffffff", "#29231d", "none", "13pt", true, "center", "middle", "Liberation Serif"),
            CellStyleElement("ceChartArea", "#ffffff", "#29231d", "none", "7pt", false, "left", "top"),
            CellStyleElement("ceGroup", "#f0e4ec", "#4c2740", "0.03cm solid #9b6386", "9pt", true, "left", "middle"),
            CellStyleElement("ceData", "#ffffff", "#29231d", "0.03cm solid #9b6386", "7pt", false, "left", "top"),
            CellStyleElement("ceAddress", "#ffffff", "#29231d", "0.02cm solid #8d8579", "8pt", false, "left", "top"),
            CellStyleElement("ceMonth", "#ffffff", "#29231d", "0.02cm solid #756a59", "8pt", false, "left", "top", wrap: false),
            CellStyleElement("ceSpacer", "#ffffff", "#ffffff", "none", "7pt", false, "left", "top"));
        foreach (var (key, colors) in PlannerColors)
        {
            styles.Add(CellStyleElement("cePlan" + StyleSuffix(key), colors.Fill, colors.Text, "0.02cm solid #625b50", "7pt", false, "left", "top"));
            if (key.Length > 0) styles.Add(CellStyleElement("ceMonth" + StyleSuffix(key), colors.Fill, colors.Text,
                "0.02cm solid #756a59", "8pt", key == "week-number", key == "week-number" ? "center" : "left", "top", wrap: false));
        }
        var textColors = sheets.Where(sheet => sheet.TextColors is not null).SelectMany(sheet => sheet.TextColors!)
            .SelectMany(row => row).SelectMany(cell => cell).Select(SafeColor).Where(color => color is not null).Distinct(StringComparer.Ordinal);
        foreach (var color in textColors)
            styles.Add(new XElement(Style + "style", new XAttribute(Style + "name", "tx" + color![1..]), new XAttribute(Style + "family", "text"),
                new XElement(Style + "text-properties", new XAttribute(Fo + "color", color))));
        for (var sheetIndex = 0; sheetIndex < sheets.Count; sheetIndex++)
        {
            var sheet = sheets[sheetIndex];
            styles.Add(new XElement(Style + "style", new XAttribute(Style + "name", $"ta{sheetIndex}"), new XAttribute(Style + "family", "table"),
                new XAttribute(Style + "master-page-name", "Landscape"), new XElement(Style + "table-properties", new XAttribute(Table + "display", "true"))));
            for (var column = 0; column < sheet.Columns.Count; column++)
                styles.Add(new XElement(Style + "style", new XAttribute(Style + "name", ColumnStyle(sheet, sheetIndex, column)), new XAttribute(Style + "family", "table-column"),
                    new XElement(Style + "table-column-properties", new XAttribute(Style + "column-width", ColumnWidth(sheet, column)))));
        }
        return styles;
    }

    private static XElement CellStyleElement(string name, string fill, string text, string border, string size,
        bool bold, string align, string vertical, string font = "Liberation Sans", bool wrap = true) =>
        new(Style + "style", new XAttribute(Style + "name", name), new XAttribute(Style + "family", "table-cell"),
            new XElement(Style + "table-cell-properties", new XAttribute(Fo + "background-color", fill), new XAttribute(Fo + "border", border),
                new XAttribute(Fo + "padding", "0.1cm"), new XAttribute(Style + "vertical-align", vertical), new XAttribute(Fo + "wrap-option", wrap ? "wrap" : "no-wrap")),
            new XElement(Style + "paragraph-properties", new XAttribute(Fo + "text-align", align),
                wrap ? null : new XAttribute(Fo + "line-height", "100%")),
            new XElement(Style + "text-properties", new XAttribute(Fo + "font-family", font), new XAttribute(Fo + "font-size", size),
                new XAttribute(Fo + "color", text), bold ? new XAttribute(Fo + "font-weight", "bold") : null));

    private static XElement RowStyle(string name, string height, bool optimal = false) =>
        new(Style + "style", new XAttribute(Style + "name", name), new XAttribute(Style + "family", "table-row"),
            new XElement(Style + "table-row-properties", new XAttribute(Style + "row-height", height),
                optimal ? new XAttribute(Style + "use-optimal-row-height", "true") : null));

    private static XDocument BuildStylesDocument() => new(new XDeclaration("1.0", "UTF-8", null),
        new XElement(Office + "document-styles", NamespaceAttributes(), new XAttribute(Office + "version", "1.2"),
            new XElement(Office + "styles", new XElement(Style + "default-style", new XAttribute(Style + "family", "table-cell"),
                new XElement(Style + "text-properties", new XAttribute(Fo + "font-family", "Liberation Sans"), new XAttribute(Fo + "font-size", "8pt")))),
            new XElement(Office + "automatic-styles", new XElement(Style + "page-layout", new XAttribute(Style + "name", "A4Landscape"),
                new XElement(Style + "page-layout-properties", new XAttribute(Fo + "page-width", "29.7cm"), new XAttribute(Fo + "page-height", "21cm"),
                    new XAttribute(Style + "print-orientation", "landscape"), new XAttribute(Fo + "margin-top", "0.7cm"),
                    new XAttribute(Fo + "margin-bottom", "0.7cm"), new XAttribute(Fo + "margin-left", "0.7cm"), new XAttribute(Fo + "margin-right", "0.7cm"),
                    new XAttribute(Style + "scale-to-pages", "1")))),
            new XElement(Office + "master-styles", new XElement(Style + "master-page", new XAttribute(Style + "name", "Landscape"),
                new XAttribute(Style + "page-layout-name", "A4Landscape")))));

    private static object[] NamespaceAttributes() =>
    [
        new XAttribute(XNamespace.Xmlns + "office", Office), new XAttribute(XNamespace.Xmlns + "table", Table),
        new XAttribute(XNamespace.Xmlns + "text", Text), new XAttribute(XNamespace.Xmlns + "style", Style),
        new XAttribute(XNamespace.Xmlns + "fo", Fo), new XAttribute(XNamespace.Xmlns + "draw", Draw),
        new XAttribute(XNamespace.Xmlns + "xlink", XLink), new XAttribute(XNamespace.Xmlns + "svg", Svg)
    ];

    private static string CellStyle(DocumentSheet sheet, int row, int column)
    {
        if (sheet.Layout == "addresses") return "ceAddress";
        if (sheet.Layout == "month")
        {
            var key = sheet.CellStyles?[row][column] ?? "";
            return key == "week-number" ? "cePlanWeekNumber" : "ceMonth" + (key.Length == 0 ? "" : StyleSuffix(key));
        }
        if (sheet.Layout == "year") return "cePlan" + StyleSuffix(sheet.CellStyles?[row][column] ?? "");
        return "ceData";
    }

    private static string HeadingStyle(DocumentSheet sheet) => sheet.Layout switch
    {
        "year" => "ceYearHeading", "month" => "ceMonthHeading", "addresses" => "ceAddressHeading", _ => "ceHeading"
    };

    private static string StyleSuffix(string key) => key.Length == 0 ? "Default" : string.Concat(key.Split('-', StringSplitOptions.RemoveEmptyEntries).Select(part => char.ToUpperInvariant(part[0]) + part[1..]));

    private static string ColumnStyle(DocumentSheet sheet, int sheetIndex, int column) => $"co{sheetIndex}_{column}";
    private static string ColumnWidth(DocumentSheet sheet, int column)
    {
        if (sheet.Layout == "year") return "2.35cm";
        if (sheet.Layout == "month") return column == 0 ? "1cm" : "3.9cm";
        if (sheet.Layout.StartsWith("health", StringComparison.Ordinal) && sheet.Groups is { } groups)
        {
            if (column < groups[0].Span) return (13.2 / groups[0].Span).ToString("0.###", CultureInfo.InvariantCulture) + "cm";
            if (column == groups[0].Span) return "0.5cm";
            return (13.2 / groups[2].Span).ToString("0.###", CultureInfo.InvariantCulture) + "cm";
        }
        var longest = Math.Max(sheet.Columns[column].Length, sheet.Rows.Take(50).Select(row => row[column].Split('\n').Max(line => line.Length)).DefaultIfEmpty(0).Max());
        return Math.Clamp(1.2 + longest * 0.18, 2.2, 5.5).ToString("0.##", CultureInfo.InvariantCulture) + "cm";
    }

    private static int PrintRowCount(DocumentSheet sheet) => sheet.Rows.Count + (sheet.Groups is { Count: > 0 } && sheet.Layout != "health-chart" ? 3 : 2);

    private static XElement ParagraphStyle(string name, string marginTop, string marginBottom, string size,
        string align = "left", bool bold = false) =>
        new(Style + "style", new XAttribute(Style + "name", name), new XAttribute(Style + "family", "paragraph"),
            new XElement(Style + "paragraph-properties", new XAttribute(Fo + "margin-top", marginTop),
                new XAttribute(Fo + "margin-bottom", marginBottom), new XAttribute(Fo + "text-align", align)),
            new XElement(Style + "text-properties", new XAttribute(Fo + "font-family", "Liberation Sans"),
                new XAttribute(Fo + "font-size", size), bold ? new XAttribute(Fo + "font-weight", "bold") : null));

    private static string CreateChartSvg(DocumentChart chart)
    {
        const double left = 58, top = 30, width = 540, height = 255;
        XNamespace svgNamespace = "http://www.w3.org/2000/svg";
        var points = chart.Series.SelectMany(series => series.Points.Select(point => (point.Key, point.Value))).ToArray();
        var dates = points.Select(point => point.Key).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var min = points.Length == 0 ? 0 : points.Min(point => point.Value);
        var max = points.Length == 0 ? 100 : points.Max(point => point.Value);
        var padding = Math.Max(1, (max - min) * 0.1); min -= padding; max += padding;
        double X(string date) => left + (dates.Length <= 1 ? width / 2 : Array.IndexOf(dates, date) * width / (dates.Length - 1));
        double Y(double value) => top + height - (value - min) * height / Math.Max(1, max - min);
        var svg = new XDocument(new XDeclaration("1.0", "UTF-8", null), new XElement(svgNamespace + "svg",
            new XAttribute("viewBox", "0 0 640 360"),
            new XElement(svgNamespace + "rect", new XAttribute("width", "640"), new XAttribute("height", "360"), new XAttribute("fill", "#ffffff")),
            Enumerable.Range(0, 5).Select(i => new XElement(svgNamespace + "line", new XAttribute("x1", left), new XAttribute("x2", left + width),
                new XAttribute("y1", top + i * height / 4), new XAttribute("y2", top + i * height / 4), new XAttribute("stroke", "#d4cec3"), new XAttribute("stroke-width", "1"))),
            new XElement(svgNamespace + "rect", new XAttribute("x", left), new XAttribute("y", top), new XAttribute("width", width), new XAttribute("height", height),
                new XAttribute("fill", "none"), new XAttribute("stroke", "#897b68"), new XAttribute("stroke-width", "1.5")),
            chart.Series.SelectMany((series, index) =>
            {
                var color = SafeColor(series.Color) ?? "#4f887b";
                var ordered = series.Points.OrderBy(point => point.Key, StringComparer.Ordinal).ToArray();
                var elements = new List<XElement>();
                if (ordered.Length > 0) elements.Add(new XElement(svgNamespace + "polyline", new XAttribute("fill", "none"), new XAttribute("stroke", color),
                    new XAttribute("stroke-width", "3"), new XAttribute("points", string.Join(" ", ordered.Select(point => $"{X(point.Key):0.##},{Y(point.Value):0.##}")))));
                elements.AddRange(ordered.Select(point => new XElement(svgNamespace + "circle", new XAttribute("cx", X(point.Key)), new XAttribute("cy", Y(point.Value)),
                    new XAttribute("r", "4"), new XAttribute("fill", color))));
                elements.Add(new XElement(svgNamespace + "text", new XAttribute("x", left + index * 180), new XAttribute("y", "330"),
                    new XAttribute("fill", color), new XAttribute("font-family", "Liberation Sans"), new XAttribute("font-size", "14"), "● " + series.Name));
                return elements;
            })));
        return svg.ToString(SaveOptions.DisableFormatting);
    }

    private static void ValidateSheets(IReadOnlyList<DocumentSheet> sheets)
    {
        if (sheets.Count is < 1 or > 24) throw new ArgumentException("Die Anzahl der Tabellen ist ungültig.");
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var sheet in sheets)
        {
            if (sheet.Columns.Count is < 1 or > 17 || sheet.Rows.Count > 5000) throw new ArgumentException("Die Tabellengröße ist ungültig.");
            if (!names.Add(SafeSheetName(sheet.Name))) throw new ArgumentException("Tabellennamen müssen eindeutig sein.");
            if (sheet.Rows.Any(row => row.Count != sheet.Columns.Count)) throw new ArgumentException("Eine Tabellenzeile hat die falsche Breite.");
            if (sheet.Groups is { } groups && (groups.Any(group => group.Span < 1) || groups.Sum(group => group.Span) != sheet.Columns.Count))
                throw new ArgumentException("Die Tabellenüberschriften haben die falsche Breite.");
            if (sheet.CellStyles is not null && (sheet.CellStyles.Count != sheet.Rows.Count || sheet.CellStyles.Any(row => row.Count != sheet.Columns.Count)))
                throw new ArgumentException("Die Tabellenstile haben die falsche Größe.");
        }
    }

    private static (IReadOnlyList<IReadOnlyList<string>>, IReadOnlyList<IReadOnlyList<IReadOnlyList<string>>>) ReadPlannerRows(JsonElement contents, int width)
    {
        if (contents.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Planerinhalte sind ungültig.");
        var rows = new List<IReadOnlyList<string>>();
        var colorRows = new List<IReadOnlyList<IReadOnlyList<string>>>();
        foreach (var row in contents.EnumerateArray())
        {
            if (row.ValueKind != JsonValueKind.Array || row.GetArrayLength() != width) throw new ArgumentException("Eine Planerzeile ist ungültig.");
            var values = new List<string>(); var colors = new List<IReadOnlyList<string>>();
            foreach (var cell in row.EnumerateArray())
            {
                if (cell.ValueKind != JsonValueKind.Object) throw new ArgumentException("Eine Planerzelle ist ungültig.");
                var lines = new List<string>(); var lineColors = new List<string>();
                AddLine(Value(cell, "datum"), "", lines, lineColors);
                AddObjectTexts(cell, "marker", lines, lineColors);
                AddObjectTexts(cell, "eintraege", lines, lineColors);
                if (cell.TryGetProperty("mehr", out var more) && more.TryGetInt32(out var count) && count > 0) AddLine($"+{count}", "#998f80", lines, lineColors);
                values.Add(string.Join("\n", lines)); colors.Add(lineColors);
            }
            rows.Add(values); colorRows.Add(colors);
        }
        return (rows, colorRows);
    }

    private static IReadOnlyList<IReadOnlyList<string>>? ReadStyleRows(JsonElement item, int width, int height)
    {
        if (!item.TryGetProperty("stile", out var rows)) return null;
        if (rows.ValueKind != JsonValueKind.Array || rows.GetArrayLength() != height) throw new ArgumentException("Die Tabellenstile sind ungültig.");
        return rows.EnumerateArray().Select(row =>
        {
            if (row.ValueKind != JsonValueKind.Array || row.GetArrayLength() != width) throw new ArgumentException("Eine Tabellenstilzeile ist ungültig.");
            return (IReadOnlyList<string>)row.EnumerateArray().Select(CellText).ToArray();
        }).ToArray();
    }

    private static void AddObjectTexts(JsonElement item, string name, List<string> lines, List<string> colors)
    {
        if (!item.TryGetProperty(name, out var values)) return;
        if (values.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Planerzelle ist ungültig.");
        foreach (var value in values.EnumerateArray())
        {
            if (value.ValueKind != JsonValueKind.Object) throw new ArgumentException("Die Planerzelle ist ungültig.");
            AddLine(Value(value, "text"), Value(value, "farbe"), lines, colors);
        }
    }

    private static void AddLine(string text, string color, ICollection<string> lines, ICollection<string> colors)
    {
        if (text.Length == 0) return;
        lines.Add(text); colors.Add(SafeColor(color) ?? "");
    }

    private static IEnumerable<DocumentSheet> ReadChartSheets(string parentTitle, JsonElement charts)
    {
        if (charts.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Gesundheitsdiagramme sind ungültig.");
        foreach (var element in charts.EnumerateArray())
        {
            var chart = ReadChart(element) ?? throw new ArgumentException("Ein Gesundheitsdiagramm ist ungültig.");
            var dates = chart.Series.SelectMany(series => series.Points.Keys).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
            var rows = dates.Select(date => (IReadOnlyList<string>)new[] { date }.Concat(chart.Series.Select(series =>
                series.Points.TryGetValue(date, out var point) ? point.ToString("G15", CultureInfo.InvariantCulture) : "")).Concat(new[] { "", "" }).ToArray()).Take(20).ToList();
            var columns = new[] { "Datum" }.Concat(chart.Series.Select(series => series.Name)).Concat(new[] { "", "" }).ToArray();
            while (rows.Count < 20) rows.Add(Enumerable.Repeat("", columns.Length).ToArray());
            var leftSpan = columns.Length - 2;
            yield return new DocumentSheet($"{parentTitle} · {chart.Title}", columns, rows,
                new[] { new DocumentSheetGroup("", leftSpan), new DocumentSheetGroup("", 1), new DocumentSheetGroup(chart.Title, 1) },
                "health-chart", Chart: chart);
        }
    }

    private static DocumentChart? ReadChart(JsonElement chart)
    {
        var title = Value(chart, "titel");
        if (title.Length == 0 || !chart.TryGetProperty("serien", out var series) || series.ValueKind != JsonValueKind.Array) return null;
        var parsed = series.EnumerateArray().Select(ReadChartSeries).ToArray();
        if (parsed.Length == 0) throw new ArgumentException("Ein Gesundheitsdiagramm enthält keine Datenreihen.");
        return new DocumentChart(title, parsed);
    }

    private static DocumentChartSeries ReadChartSeries(JsonElement series)
    {
        var name = Value(series, "name");
        if (name.Length == 0 || !series.TryGetProperty("punkte", out var points) || points.ValueKind != JsonValueKind.Array)
            throw new ArgumentException("Eine Gesundheitsdatenreihe ist ungültig.");
        var result = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var point in points.EnumerateArray())
        {
            if (point.ValueKind != JsonValueKind.Array || point.GetArrayLength() != 2) throw new ArgumentException("Ein Gesundheitspunkt ist ungültig.");
            var values = point.EnumerateArray().ToArray();
            if (values[0].ValueKind != JsonValueKind.String || values[1].ValueKind != JsonValueKind.Number) throw new ArgumentException("Ein Gesundheitspunkt ist ungültig.");
            result[values[0].GetString() ?? ""] = values[1].GetDouble();
        }
        return new DocumentChartSeries(name, SafeColor(Value(series, "farbe")) ?? "#4f887b", result);
    }

    private static IReadOnlyList<IReadOnlyList<string>> ReadRows(JsonElement item, string name, int width)
    {
        if (!item.TryGetProperty(name, out var rows) || rows.ValueKind != JsonValueKind.Array) throw new ArgumentException("Die Tabellenzeilen fehlen.");
        return rows.EnumerateArray().Select(row =>
        {
            if (row.ValueKind != JsonValueKind.Array) throw new ArgumentException("Eine Tabellenzeile ist ungültig.");
            var values = row.EnumerateArray().Select(CellText).ToArray();
            if (values.Length != width) throw new ArgumentException("Eine Tabellenzeile hat die falsche Breite.");
            return (IReadOnlyList<string>)values;
        }).ToArray();
    }

    private static string? SafeColor(string value)
    {
        if (value.Length != 7 || value[0] != '#' || !value[1..].All(Uri.IsHexDigit)) return null;
        return value.ToLowerInvariant();
    }

    private static string[] StringArray(JsonElement item, string name) => item.TryGetProperty(name, out var array) && array.ValueKind == JsonValueKind.Array
        ? array.EnumerateArray().Select(CellText).ToArray() : Array.Empty<string>();
    private static string CellText(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String) throw new ArgumentException("Eine Tabellenzelle ist kein Text.");
        var text = value.GetString() ?? "";
        if (text.Length > 10_000) throw new ArgumentException("Eine Tabellenzelle ist zu lang.");
        return text;
    }
    private static string Value(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    private static string SafeSheetName(string value)
    {
        var clean = new string(value.Where(character => !"[]:*?/\\".Contains(character) && !char.IsControl(character)).ToArray()).Trim('\'');
        return clean.Length == 0 ? "Tabelle" : clean[..Math.Min(80, clean.Length)];
    }
    private static string ColumnName(int count)
    {
        var value = count; var result = "";
        while (value > 0) { value--; result = (char)('A' + value % 26) + result; value /= 26; }
        return result;
    }
    private static void WriteEntry(ZipArchive archive, string name, string content, CompressionLevel compression)
    {
        var entry = archive.CreateEntry(name, compression);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false)); writer.Write(content);
    }
}
