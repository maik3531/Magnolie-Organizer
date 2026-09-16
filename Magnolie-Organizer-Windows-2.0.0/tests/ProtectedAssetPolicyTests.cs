using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ProtectedAssetPolicyTests
{
    internal static Task RunAsync()
    {
        const string host = "appassets.magnolie.invalid";
        IReadOnlySet<string> paths = new HashSet<string>(["/kaffee-qr.png"], StringComparer.Ordinal);
        TestAssert.That(ProtectedAssetPolicy.TryGetAllowedPath(
                $"https://{host}/kaffee-qr.png", host, paths, out var path) && path == "/kaffee-qr.png",
            "Ein erlaubtes geschütztes Asset wurde abgelehnt.");
        TestAssert.That(ProtectedAssetPolicy.TryGetAllowedPath(
                $"https://APPASSETS.MAGNOLIE.INVALID:443/kaffee-qr.png", host, paths, out _),
            "Eine semantisch identische HTTPS-URL wurde ohne den Raw-URL-Vergleich abgelehnt.");

        foreach (var target in new[]
        {
            $"http://{host}/kaffee-qr.png",
            $"https://other.invalid/kaffee-qr.png",
            $"https://user@{host}/kaffee-qr.png",
            $"https://{host}:444/kaffee-qr.png",
            $"https://{host}/nicht-erlaubt.png",
            $"https://{host}/kaffee-qr.png?download=1",
            $"https://{host}/kaffee-qr.png#fragment"
        })
            TestAssert.That(!ProtectedAssetPolicy.TryGetAllowedPath(target, host, paths, out _),
                $"Nicht erlaubte Asset-URL wurde angenommen: {target}");

        var headers = ProtectedAssetPolicy.ResponseHeaders("image/png", 123);
        TestAssert.That(headers.Contains("Content-Length: 123\r\n", StringComparison.Ordinal) &&
                        headers.Contains("X-Content-Type-Options: nosniff\r\n", StringComparison.Ordinal) &&
                        headers.EndsWith("Cache-Control: no-store", StringComparison.Ordinal),
            "Sichere Header für geschützte Assets fehlen.");
        TestAssert.Throws<InvalidDataException>(() =>
                ProtectedAssetPolicy.ResponseHeaders("image/png\r\nX-Injected: yes", 1),
            "Eine Header-Injektion über den Inhaltstyp wurde angenommen.");

        var source = File.ReadAllText("ProtectedAssetReader.cs");
        TestAssert.That(source.Contains("CoreWebView2WebResourceContext.All", StringComparison.Ordinal) &&
                         !source.Contains("eventArgs.Request.Uri.Equals", StringComparison.Ordinal) &&
                         source.Contains("new MemoryStream(data, writable: false)", StringComparison.Ordinal) &&
                          !source.Contains("ClearingMemoryStream", StringComparison.Ordinal) &&
                          source.Contains("diagnostic?.Invoke", StringComparison.Ordinal) &&
                          source.Contains("core.WebResourceResponseReceived +=", StringComparison.Ordinal) &&
                          source.Contains("eventArgs.Response.StatusCode", StringComparison.Ordinal) &&
                          source.Contains("ProtectedAssetPolicy.EmptyResponseHeaders", StringComparison.Ordinal),
             "ProtectedAssetReader verwendet keine stabile, diagnostizierbare WebView2-Antwort.");
        var uiTest = File.ReadAllText("UiSelfTest.cs");
        TestAssert.That(!uiTest.Contains("new Image()", StringComparison.Ordinal) &&
                        uiTest.Contains("Handbuch.blaettereZuId('support-with-a-coffee')", StringComparison.Ordinal) &&
                        uiTest.Contains("Handbuch.blaettereZuId('about-maik-walter')", StringComparison.Ordinal) &&
                        uiTest.Contains("#seiten .autorenfoto", StringComparison.Ordinal) &&
                        uiTest.Contains("image.naturalWidth", StringComparison.Ordinal) &&
                        uiTest.Contains("image.checkVisibility", StringComparison.Ordinal) &&
                        uiTest.Contains("document.elementFromPoint", StringComparison.Ordinal) &&
                        uiTest.Contains("source.GetString() == expectedSource", StringComparison.Ordinal) &&
                        uiTest.Contains("visible.GetBoolean()", StringComparison.Ordinal),
            "Der native Bildtest muss echte sichtbare Handbuchseiten statt losgeloester Bilder pruefen.");
        return Task.CompletedTask;
    }
}
