using System.Net;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WeatherRequestsTests
{
    private sealed class Handler(int failures) : HttpMessageHandler
    {
        internal readonly List<Uri> Requests = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Requests.Add(request.RequestUri!);
            if (Requests.Count <= failures) throw new HttpRequestException("Synthetic unavailable provider");
            var json = request.RequestUri!.Host switch
            {
                "geocoding-api.open-meteo.com" => """{"results":[{"name":"Berlin","latitude":52.5,"longitude":13.4}]}""",
                "api.open-meteo.com" => """{"daily":{"time":["2026-09-15"],"temperature_2m_min":[10],"temperature_2m_max":[20],"weather_code":[0]}}""",
                _ => """{"weather":[{"date":"2026-09-15","mintempC":"10","maxtempC":"20","hourly":[{"time":"1200","weatherCode":"113"}]}]}"""
            };
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json) });
        }
    }
    internal static async Task RunAsync()
    {
        foreach (var failed in new[] { 0, 1, 2 })
        {
            using var handler = new Handler(failed);
            using var client = new HttpClient(handler);
            var result = await WeatherRequests.FetchAsync(client, "10115 Berlin", "de");
            TestAssert.That(result.GetProperty("weather").GetArrayLength() == 1, "Forecast lost");
            TestAssert.That(handler.Requests[0].Scheme == "https", "HTTPS must be tried first");
            if (failed > 0) TestAssert.That(handler.Requests[1].Scheme == "http" && handler.Requests[1].Host == "wttr.in", "Wrong HTTP fallback");
            TestAssert.That(handler.Requests.Count == (failed == 2 ? 4 : failed + 1), "Unexpected fallback requests");
            if (failed == 2) TestAssert.That(result.GetProperty("provider").GetString() == "Open-Meteo", "Missing alternative attribution");
        }
    }
}
