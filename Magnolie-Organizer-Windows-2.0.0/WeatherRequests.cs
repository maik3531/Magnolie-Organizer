using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class WeatherRequests
{
    internal static async Task<JsonElement> FetchAsync(HttpClient client, string location, string language)
    {
        using var total = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        async Task<JsonElement> Read(string url)
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(total.Token);
            deadline.CancelAfter(TimeSpan.FromSeconds(8));
            using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, deadline.Token);
            response.EnsureSuccessStatusCode();
            await using var input = await response.Content.ReadAsStreamAsync(deadline.Token);
            using var bytes = new MemoryStream();
            var buffer = new byte[8192];
            int read;
            while ((read = await input.ReadAsync(buffer, deadline.Token)) > 0)
            {
                if (bytes.Length + read > 1024 * 1024) throw new IOException("Weather response exceeds one MiB.");
                bytes.Write(buffer, 0, read);
            }
            using var document = JsonDocument.Parse(bytes.ToArray());
            return document.RootElement.Clone();
        }
        Exception? last = null;
        var suffix = "/" + Uri.EscapeDataString(location) + "?format=j1&lang=" + language;
        foreach (var origin in new[] { "https://wttr.in", "http://wttr.in" })
        {
            try
            {
                var result = await Read(origin + suffix);
                if (!result.TryGetProperty("weather", out var days) || days.ValueKind != JsonValueKind.Array ||
                    !days.EnumerateArray().Any(ValidDay)) throw new IOException("No usable weather forecast.");
                var normalized = JsonNode.Parse(result.GetRawText())!.AsObject();
                normalized["provider"] = "wttr.in";
                return JsonSerializer.SerializeToElement(normalized);
            }
            catch (Exception error) when (error is HttpRequestException or IOException or JsonException or OperationCanceledException or InvalidOperationException)
            { last = error; }
        }
        if (location.Length == 0) throw new IOException("Weather providers are unavailable.", last);
        var name = Regex.Replace(location, @"^\d{4,6}\s+", "").Trim();
        var geo = await Read("https://geocoding-api.open-meteo.com/v1/search?name=" + Uri.EscapeDataString(name) +
            "&count=1&language=" + language + "&format=json");
        if (!geo.TryGetProperty("results", out var places) || places.ValueKind != JsonValueKind.Array || places.GetArrayLength() == 0)
            throw new IOException("No location found for the weather forecast.");
        var place = places[0];
        var latitude = place.GetProperty("latitude").GetDouble();
        var longitude = place.GetProperty("longitude").GetDouble();
        if (!double.IsFinite(latitude) || !double.IsFinite(longitude) || latitude is < -90 or > 90 || longitude is < -180 or > 180)
            throw new IOException("Invalid weather coordinates.");
        var forecast = await Read("https://api.open-meteo.com/v1/forecast?latitude=" + latitude.ToString(CultureInfo.InvariantCulture) +
            "&longitude=" + longitude.ToString(CultureInfo.InvariantCulture) +
            "&forecast_days=3&timezone=auto&daily=weather_code,temperature_2m_max,temperature_2m_min");
        var daily = forecast.GetProperty("daily");
        var dates = daily.GetProperty("time");
        var minima = daily.GetProperty("temperature_2m_min");
        var maxima = daily.GetProperty("temperature_2m_max");
        var codes = daily.GetProperty("weather_code");
        var mapping = new Dictionary<int,int> { [0]=113,[1]=116,[2]=116,[3]=119,[45]=143,[48]=248,
            [51]=266,[53]=266,[55]=266,[56]=281,[57]=284,[61]=296,[63]=302,[65]=308,[66]=311,[67]=314,
            [71]=326,[73]=329,[75]=332,[77]=335,[80]=353,[81]=356,[82]=359,[85]=368,[86]=371,[95]=200,[96]=386,[99]=389 };
        var converted = new JsonArray();
        var count = new[] { 3, dates.GetArrayLength(), minima.GetArrayLength(), maxima.GetArrayLength(), codes.GetArrayLength() }.Min();
        for (var i = 0; i < count; i++)
        {
            if (dates[i].ValueKind != JsonValueKind.String ||
                !DateOnly.TryParseExact(dates[i].GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _) ||
                minima[i].ValueKind != JsonValueKind.Number || maxima[i].ValueKind != JsonValueKind.Number ||
                codes[i].ValueKind != JsonValueKind.Number ||
                !minima[i].TryGetDouble(out var low) || !maxima[i].TryGetDouble(out var high) ||
                !codes[i].TryGetInt32(out var code) || !double.IsFinite(low) || !double.IsFinite(high)) continue;
            converted.Add(new JsonObject { ["date"] = dates[i].GetString(),
                ["mintempC"] = low.ToString(CultureInfo.InvariantCulture), ["maxtempC"] = high.ToString(CultureInfo.InvariantCulture),
                ["hourly"] = new JsonArray(new JsonObject { ["time"] = "1200", ["weatherCode"] = mapping.GetValueOrDefault(code).ToString(CultureInfo.InvariantCulture) }) });
        }
        if (converted.Count == 0) throw new IOException("No usable weather forecast.");
        return JsonSerializer.SerializeToElement(new JsonObject { ["weather"] = converted, ["provider"] = "Open-Meteo",
            ["nearest_area"] = new JsonArray(new JsonObject { ["areaName"] = new JsonArray(new JsonObject {
                ["value"] = place.TryGetProperty("name", out var label) ? label.GetString() : name }) }) });
    }

    private static bool ValidDay(JsonElement day) => day.ValueKind == JsonValueKind.Object &&
        day.TryGetProperty("date", out var date) && date.ValueKind == JsonValueKind.String && DateOnly.TryParseExact(date.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _) &&
        day.TryGetProperty("mintempC", out var low) && double.TryParse(low.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var minimum) && double.IsFinite(minimum) &&
        day.TryGetProperty("maxtempC", out var high) && double.TryParse(high.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var maximum) && double.IsFinite(maximum);
}
