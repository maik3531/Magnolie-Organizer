using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DrawingSvgTests
{
    internal static Task RunAsync()
    {
        const string png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAARUlEQVR4nO3OsQEAEADAMPz/M7slI0NzQeYef1mvA7dCUkgKSSEpJIWkkBSSQlJICkkhKSSFpJAUkkJSSApJISkkhaSQHEnhAV+0eRpfAAAAAElFTkSuQmCC";
        static string Svg(string href) => "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"400\" height=\"300\" viewBox=\"0 0 400 300\"><image href=\"" + href + "\" x=\"0\" y=\"0\" width=\"400\" height=\"300\"/><path d=\"M1 2L3 4\" fill=\"none\" stroke=\"#000000\" stroke-width=\"2\"/></svg>";
        TestAssert.That(DrawingSvg.Validate(Svg(png)).Length > 100, "Self-contained opened picture/signature SVG rejected");
        foreach (var href in new[] { "https://example.invalid/private.png", "file:///private.png", "data:image/svg+xml;base64,PHN2Zy8+", "data:image/png;base64,YmFk" })
        {
            try { DrawingSvg.Validate(Svg(href)); throw new Exception("Unsafe image reference accepted: " + href); }
            catch (InvalidDataException) { }
        }
        foreach (var value in new[] { Svg(png).Replace("<path ", "<path onload=\"alert(1)\" "), Svg(png).Replace("<image ", "<foreignObject ") })
        {
            try { DrawingSvg.Validate(value); throw new Exception("Unsupported SVG content accepted"); }
            catch (Exception error) when (error is InvalidDataException or System.Xml.XmlException) { }
        }
        return Task.CompletedTask;
    }
}
