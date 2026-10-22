using System.Globalization;
using System.Text.Json.Nodes;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record TimeZoneCandidate(string? Zone, long? CapturedMs = null);
internal sealed record TimeZoneObservation(string Zone, string Source, long CapturedMs, bool Fallback, bool Automatic);
internal sealed record TimeZoneLocation(double Latitude, double Longitude, long CapturedMs);

// Source selection only. Date/recurrence conversion remains in the existing calendar engines.
internal static class TimeZoneManagement
{
    internal const string IpUrl = "https://ipapi.co/json/";
    private static readonly SemaphoreSlim RefreshGate = new(1, 1);

    internal static string? ZoneId(string? value, bool allowSystem = false)
    {
        value = value?.Trim();
        if (value is null || value.Length > 128) return null;
        if (allowSystem && value == "system") return value;
        if (value is "GMT" or "Etc/UTC" or "Etc/GMT" or "Z") value = "UTC";
        if (value != "UTC" && (value.Contains("..", StringComparison.Ordinal) || !Regex.IsMatch(value, @"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+$"))) return null;
        try { _ = TimeZoneInfo.FindSystemTimeZoneById(value); return value; }
        catch (Exception error) when (error is TimeZoneNotFoundException or InvalidTimeZoneException) { return null; }
    }

    internal static string? SystemZone()
    {
        var id = TimeZoneInfo.Local.Id;
        if (ZoneId(id) is { } iana) return iana;
        return TimeZoneInfo.TryConvertWindowsIdToIanaId(id, out var converted) ? ZoneId(converted) : null;
    }

    internal static async Task<TimeZoneObservation> DetectAsync(JsonObject settings,
        IReadOnlyDictionary<string, Func<CancellationToken, Task<TimeZoneCandidate?>>> sources,
        CancellationToken cancellationToken, long? nowMs = null)
    {
        var now = nowMs ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var mode = ContactFields.Text(settings, "timeZoneManagement");
        var manual = ZoneId(ContactFields.Text(settings, "timeZoneManual") is { Length: > 0 } saved ? saved : ContactFields.Text(settings, "timeZone"), true);
        if (mode != "automatic") return new((mode is "off" or "" ? ZoneId(ContactFields.Text(settings, "timeZone"), true) : manual) ?? "system", "manual", now, false, false);
        if (manual is null) throw new InvalidDataException("invalid_time_zone");
        var preference = ContactFields.Text(settings, "timeZoneDetection");
        string[] order = preference is "" or "auto" ? ["phone", "gps", "ip", "system"] : [preference];
        foreach (var source in order)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (source is not ("phone" or "gps" or "ip" or "system") || !sources.TryGetValue(source, out var load)) continue;
            try
            {
                var value = await load(cancellationToken).ConfigureAwait(false);
                var captured = value?.CapturedMs ?? now;
                if (captured < now - 300000 || captured > now + 30000) continue;
                if (ZoneId(value?.Zone, source == "system") is { } zone) return new(zone, source, captured, false, true);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch (Exception) { /* Optional sources can be absent, denied, offline or busy. */ }
        }
        if (manual == "system" && sources.TryGetValue("system", out var system))
        {
            try
            {
                var value = await system(cancellationToken).ConfigureAwait(false);
                if (ZoneId(value?.Zone, true) is { } zone) return new(zone, "system", now, true, true);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch (Exception) { }
        }
        return new(manual, "manual", now, true, true);
    }

    internal static async Task<TimeZoneCandidate?> FromIpAsync(Func<string, CancellationToken, Task<JsonObject>> fetch, CancellationToken cancellationToken)
    {
        var value = await fetch(IpUrl, cancellationToken).ConfigureAwait(false);
        if (value["error"]?.GetValue<bool>() == true) return null;
        return ZoneId(ContactFields.Text(value, "timezone")) is { } zone ? new(zone) : null;
    }

    internal static async Task<TimeZoneCandidate?> FromCoordinatesAsync(TimeZoneLocation point,
        Func<string, CancellationToken, Task<JsonObject>> fetch, CancellationToken cancellationToken, long? nowMs = null)
    {
        var now = nowMs ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        if (!double.IsFinite(point.Latitude) || !double.IsFinite(point.Longitude) || point.Latitude is < -90 or > 90 || point.Longitude is < -180 or > 180 ||
            point.CapturedMs < now - 300000 || point.CapturedMs > now + 30000) throw new InvalidDataException("invalid_timezone_location");
        var url = "https://api.open-meteo.com/v1/forecast?latitude=" + point.Latitude.ToString("R", CultureInfo.InvariantCulture) +
            "&longitude=" + point.Longitude.ToString("R", CultureInfo.InvariantCulture) + "&current=temperature_2m&forecast_days=1&timezone=auto";
        var value = await fetch(url, cancellationToken).ConfigureAwait(false);
        return ZoneId(ContactFields.Text(value, "timezone")) is { } zone ? new(zone, point.CapturedMs) : null;
    }

    internal static async Task<JsonObject> RefreshAsync(string path, JsonElement expected,
        Func<CancellationToken, Task<JsonObject?>> phone, Func<bool> permitted, CancellationToken cancellationToken,
        Func<string, CancellationToken, Task<JsonObject>>? fetch = null, Func<CancellationToken, Task<TimeZoneLocation?>>? location = null)
    {
        if (!await RefreshGate.WaitAsync(0, cancellationToken).ConfigureAwait(false)) throw new InvalidOperationException("time_zone_busy");
        try
        {
            var before = RegionalSettings.ReadVerified(path);
            if (expected.ValueKind != JsonValueKind.Object || !JsonNode.DeepEquals(before, JsonNode.Parse(expected.GetRawText()))) throw new InvalidOperationException("regional_conflict");
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (ContactFields.Text(before, "timeZoneManagement") != "automatic") return new JsonObject
            { ["regional"] = before, ["automatic"] = false, ["native_changed"] = false, ["time_zone"] = before["timeZone"]!.DeepClone(), ["source"] = "manual", ["checked_at_ms"] = now, ["fallback"] = false };
            using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            lifetime.CancelAfter(TimeSpan.FromSeconds(20)); var token = lifetime.Token;
            using var client = DeadlineHttp.Create(TimeSpan.FromSeconds(3), maximum: 65536);
            async Task<JsonObject> Fetch(string url, CancellationToken ct)
            {
                Check();
                if (fetch is not null) return await fetch(url, ct).ConfigureAwait(false);
                using var response = await client.GetAsync(url, ct).ConfigureAwait(false); response.EnsureSuccessStatusCode();
                return JsonNode.Parse(await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false)) as JsonObject ?? throw new InvalidDataException("timezone_source_unavailable");
            }
            void Check()
            {
                token.ThrowIfCancellationRequested();
                if (!permitted()) throw new InvalidOperationException("locked");
                if (!JsonNode.DeepEquals(before, RegionalSettings.ReadVerified(path))) throw new InvalidOperationException("regional_conflict");
            }
            var sources = new Dictionary<string, Func<CancellationToken, Task<TimeZoneCandidate?>>>
            {
                ["phone"] = async ct =>
                {
                    Check(); var value = await phone(ct).ConfigureAwait(false);
                    if (value is null || !TelefonProtocolContract.TryInteger(value["captured_ms"], out var captured)) return null;
                    return new(ContactFields.Text(value, "zone"), captured);
                },
                ["gps"] = async ct =>
                {
                    Check(); var point = await (location ?? WindowsLocationAsync)(ct).ConfigureAwait(false);
                    return point is null ? null : await FromCoordinatesAsync(point, Fetch, ct).ConfigureAwait(false);
                },
                ["ip"] = ct => FromIpAsync(Fetch, ct),
                ["system"] = _ => { Check(); return Task.FromResult<TimeZoneCandidate?>(new(SystemZone() ?? "system")); }
            };
            var observation = await DetectAsync(before, sources, token, now).ConfigureAwait(false);
            Check();
            var changed = ContactFields.Text(before, "timeZone") != observation.Zone || ContactFields.Text(before, "timeZoneDetectedSource") != observation.Source || ContactFields.Text(before, "timeZoneDetectedAt") == "0";
            var actual = before;
            if (changed)
            {
                var wanted = before.DeepClone().AsObject(); wanted["timeZone"] = observation.Zone;
                wanted["timeZoneDetectedSource"] = observation.Source; wanted["timeZoneDetectedAt"] = observation.CapturedMs.ToString(CultureInfo.InvariantCulture);
                actual = RegionalSettings.WriteChecked(path, JsonSerializer.SerializeToElement(wanted), JsonSerializer.SerializeToElement(before));
            }
            return new JsonObject { ["regional"] = actual, ["automatic"] = true, ["native_changed"] = changed,
                ["time_zone"] = observation.Zone, ["source"] = observation.Source, ["captured_ms"] = observation.CapturedMs,
                ["checked_at_ms"] = now, ["fallback"] = observation.Fallback };
        }
        finally { RefreshGate.Release(); }
    }

    internal static Task<TimeZoneLocation?> WindowsLocationAsync(CancellationToken cancellationToken)
    {
#if WINDOWS
        return Task.Run<TimeZoneLocation?>(() =>
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            deadline.CancelAfter(TimeSpan.FromSeconds(3));
            var locator = new global::Windows.Devices.Geolocation.Geolocator();
            var position = locator.GetGeopositionAsync(TimeSpan.FromMinutes(2), TimeSpan.FromSeconds(2)).AsTask(deadline.Token).GetAwaiter().GetResult();
            return new(position.Coordinate.Point.Position.Latitude, position.Coordinate.Point.Position.Longitude,
                position.Coordinate.Timestamp.ToUnixTimeMilliseconds());
        }, cancellationToken);
#else
        return Task.FromResult<TimeZoneLocation?>(null);
#endif
    }
}
