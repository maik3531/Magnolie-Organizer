using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WeatherLocationTests
{
    internal static Task RunAsync()
    {
        var loaderCalled = false;
        var saved = WeatherLocationSelector.Select(" 47051 Duisburg ", false, () =>
        {
            loaderCalled = true;
            return Result(("postalcode", "10115"), ("l", "Berlin"));
        });
        TestAssert.That(saved == new WeatherLocation("47051 Duisburg", "adresse") &&
                        saved.ShouldFetch && !loaderCalled,
            "Die gespeicherte Adresse hat nicht Vorrang vor LibreOffice.");

        var libreOffice = WeatherLocationSelector.Select("", true,
            () => Result(("postalcode", "10115"), ("l", "Berlin")));
        TestAssert.That(libreOffice == new WeatherLocation("10115 Berlin", "libreoffice") &&
                        libreOffice.ShouldFetch,
            "Der LibreOffice-Ort wurde nicht als zweiter Standortweg gewählt.");

        var unusableSaved = WeatherLocationSelector.Select(" -- ", true,
            () => Result(("postalcode", "01067"), ("l", "Dresden")));
        TestAssert.That(unusableSaved == new WeatherLocation("01067 Dresden", "libreoffice"),
            "Eine unbrauchbare gespeicherte Adresse blockiert den LibreOffice-Rückfall.");

        var cityOnly = WeatherLocationSelector.Select("", false, () => Result(("l", "Leipzig")));
        var postalCodeOnly = WeatherLocationSelector.Select("", false,
            () => Result(("postalcode", "04109")));
        TestAssert.That(cityOnly == new WeatherLocation("Leipzig", "libreoffice") &&
                        postalCodeOnly == new WeatherLocation("04109", "libreoffice"),
            "Unvollständige, aber verwendbare LibreOffice-Ortsdaten wurden verworfen.");

        var ip = WeatherLocationSelector.Select("", true,
            () => Result(("givenname", "Erika"), ("street", "Musterweg")));
        var blocked = WeatherLocationSelector.Select("", false,
            () => Result(("givenname", "Erika"), ("street", "Musterweg")));
        TestAssert.That(ip == new WeatherLocation("", "ip") && ip.ShouldFetch,
            "Ohne Ortsdaten wurde die erlaubte IP-Schätzung nicht gewählt.");
        TestAssert.That(blocked == new WeatherLocation("", "none") && !blocked.ShouldFetch,
            "Bei aktivierter Datenschutzoption würde ohne Ortsdaten abgerufen.");

        var failedReadIp = WeatherLocationSelector.Select("", true,
            () => throw new IOException("Lesefehler"));
        var failedReadBlocked = WeatherLocationSelector.Select("", false,
            () => throw new UnauthorizedAccessException("Zugriff verweigert"));
        TestAssert.That(failedReadIp == new WeatherLocation("", "ip") &&
                        failedReadBlocked == new WeatherLocation("", "none"),
            "LibreOffice-Lesefehler beachten IP-Freigabe beziehungsweise Abrufsperre nicht.");

        var malformedResult = WeatherLocationSelector.Select("", false,
            () => new LibreOfficeUserDataResult(false, null!, "", "Ungültig"));
        TestAssert.That(malformedResult == new WeatherLocation("", "none"),
            "Ein fehlerhaftes LibreOffice-Ergebnis löst trotz Abrufsperre einen Standortweg aus.");

        return Task.CompletedTask;
    }

    private static LibreOfficeUserDataResult Result(params (string Name, string Value)[] fields) =>
        new(true, fields.ToDictionary(field => field.Name, field => field.Value,
            StringComparer.Ordinal), "", "");
}
