using System.Globalization;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// Read-only peer review against the already-built actual CoreTests assembly.
// No extraction, reimplementation, or product-source modification.
CultureInfo.CurrentUICulture = CultureInfo.InvariantCulture;
var source = Path.GetFullPath(args[0]);
var binary = Path.GetFullPath(args[1]);
var assembly = Assembly.LoadFrom(binary);
var flags = BindingFlags.NonPublic | BindingFlags.Static;
var codec = assembly.GetType("MagnolieOrganizer.Windows.ExchangeCodec", true)!;
var decode = codec.GetMethod("DecodeText", flags)!;
var localization = assembly.GetType("MagnolieOrganizer.Windows.NativeLocalization", true)!;
localization.GetMethod("SetLanguage", flags)!.Invoke(null, ["en"]);
var results = new List<object>();

string Actual(byte[] bytes)
{
    try { return (string)decode.Invoke(null, [bytes])!; }
    catch (TargetInvocationException error) when (error.InnerException is not null)
    { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error.InnerException).Throw(); throw; }
}

void Valid(string name, byte[] bytes, string expected)
{
    var actual = Actual(bytes);
    if (actual != expected) throw new Exception("Changed valid decoder result: " + name);
    results.Add(new { name, expected = "exact text preserved", passed = true });
}

void Invalid(string name, byte[] bytes)
{
    try { Actual(bytes); }
    catch (InvalidDataException error) when (error.InnerException is DecoderFallbackException)
    {
        if (error.Message != "The content is unreadable.")
            throw new Exception("Wrong content error: " + name);
        results.Add(new { name, expected = "InvalidDataException with DecoderFallbackException cause", passed = true });
        return;
    }
    throw new Exception("Malformed UTF-16 accepted: " + name);
}

foreach (var bigEndian in new[] { false, true })
{
    var label = bigEndian ? "BE" : "LE";
    var encoding = new UnicodeEncoding(bigEndian, true, true);
    foreach (var (name, text) in new[] {
        ("empty BOM", ""), ("literal U+FFFD", "\ufffd"),
        ("minimum non-BMP", "\ud800\udc00"), ("maximum non-BMP", "\udbff\udfff"),
        ("ZWJ sequence", "👩‍💻"), ("interior BOM", "A\ufeffB") })
        Valid(label + " " + name, [.. encoding.GetPreamble(), .. encoding.GetBytes(text)], text);
    byte[] Units(params ushort[] units) => [.. encoding.GetPreamble(), .. units.SelectMany(unit =>
        bigEndian ? new[] { (byte)(unit >> 8), (byte)unit } : new[] { (byte)unit, (byte)(unit >> 8) })];
    Invalid(label + " orphan high", Units(0xd800));
    Invalid(label + " orphan low", Units(0xdc00));
    Invalid(label + " high followed by ASCII", Units(0xd800, 0x0041));
    Invalid(label + " reversed surrogate pair", Units(0xdc00, 0xd800));
    Invalid(label + " odd payload after BOM", [.. encoding.GetPreamble(), 0x41]);
}
Valid("empty non-BOM", [], "");
Valid("single FF uses legacy fallback", [0xff], "ÿ");
Valid("single FE uses legacy fallback", [0xfe], "þ");
Valid("invalid UTF-8 uses Windows-1252", [0xc3, 0x28], "Ã(");
Valid("UTF-8 BOM is stripped", [0xef, 0xbb, 0xbf, 0x41], "A");
Valid("non-BOM UTF-16-like bytes retain old dispatch", [0x41, 0x00], "A\0");

Console.WriteLine(JsonSerializer.Serialize(new {
    source_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source))).ToLowerInvariant(),
    tested_assembly_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(binary))).ToLowerInvariant(),
    independent_cases = results.Count,
    passed = results.Count,
    results,
    scope = "Actual compiled C# DecodeText on .NET 8 Linux; UTF-16 BOM boundaries, valid Unicode, invalid sequences, localized error key, unchanged non-BOM fallback. No native Windows GUI or package claim."
}, new JsonSerializerOptions { WriteIndented = true }));
