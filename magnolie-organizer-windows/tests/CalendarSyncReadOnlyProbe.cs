using System.Net;
using System.Reflection;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

/** Executes the real calendar planner, but blocks EVERY mutation before the transport. */
internal static class CalendarSyncReadOnlyProbe
{
    private sealed class MutationCaptured : Exception { }
    private sealed class ReadFixture : HttpMessageHandler
    {
        internal int Calls;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation)
        { Calls++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("fixture") }); }
    }
    private sealed class ReadOnlyHandler(HttpMessageHandler inner) : DelegatingHandler(inner)
    {
        internal JsonObject? Mutation;
        internal int Reads;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation)
        {
            if (request.Method != HttpMethod.Get && request.Method.Method is not ("REPORT" or "PROPFIND"))
            {
                Mutation = new JsonObject
                {
                    ["method"] = request.Method.Method, ["url"] = request.RequestUri!.AbsoluteUri,
                    ["ifMatch"] = request.Headers.TryGetValues("If-Match", out var matches) ? matches.Single() : null,
                    ["ifNoneMatch"] = request.Headers.TryGetValues("If-None-Match", out var none) ? none.Single() : null,
                    ["mediaType"] = request.Content?.Headers.ContentType?.ToString(),
                    ["body"] = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellation)
                };
                throw new MutationCaptured();
            }
            Reads++;
            return await base.SendAsync(request, cancellation);
        }
    }

    internal static async Task SafetyAsync()
    {
        using var transport = new ReadFixture();
        using var handler = new ReadOnlyHandler(transport);
        using var http = new HttpClient(handler);
        using var read = await http.GetAsync("https://calendar.example.invalid/events/");
        TestAssert.That(transport.Calls == 1, "Read-only diagnosis did not forward a GET.");
        foreach (var method in new[] { HttpMethod.Put, HttpMethod.Delete, HttpMethod.Post })
        {
            using var request = new HttpRequestMessage(method, "https://calendar.example.invalid/events/fixture.ics") { Content = new StringContent("synthetic") };
            await TestAssert.ThrowsAsync<MutationCaptured>(() => http.SendAsync(request), "A diagnostic mutation reached the provider.");
            TestAssert.That(transport.Calls == 1 && handler.Mutation?["method"]?.GetValue<string>() == method.Method,
                "A write escaped the diagnostic recorder.");
        }
    }

    internal static async Task<int> RunAsync(string sourceUid, string receiptPath)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!ThunderbirdBridge.IsManagedSource(sourceUid) || !sourceUid.StartsWith("thunderbird-calendar:", StringComparison.Ordinal))
            throw new ArgumentException("An explicit existing managed calendar source is required.");
        if (File.Exists(receiptPath)) throw new IOException("Receipt already exists.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var paths = new WindowsPaths();
        var prefix = Path.GetFileName(paths.NextcloudSyncJournal);
        var saved = Directory.EnumerateFiles(paths.Root, prefix + "*", SearchOption.TopDirectoryOnly)
            .Where(file => Regex.IsMatch(Path.GetFileName(file), "^" + Regex.Escape(prefix) + @"(?:\.[a-fA-F0-9]{64})?$"))
            .OrderByDescending(File.GetLastWriteTimeUtc).Take(16)
            .Select(file => new NextcloudSyncJournal(file).Load())
            .FirstOrDefault(item => item?.Payload["termine"] is JsonArray) ?? throw new InvalidDataException("No bounded saved synchronization input exists.");
        var data = saved.Payload.DeepClone().AsObject();
        var sources = await ThunderbirdBridge.SourcesAsync(deadline.Token, managed: true);
        var source = sources.Single(value => value.Uid == sourceUid && value.Kind == "calendar");
        var handlerType = typeof(ThunderbirdBridge).GetNestedType("ThunderbirdHttpHandler", BindingFlags.NonPublic)!;
        var transport = (HttpMessageHandler)Activator.CreateInstance(handlerType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, [source, null], null)!;
        using var handler = new ReadOnlyHandler(transport);
        using var http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(30) };
        var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false, source.Href.GetLeftPart(UriPartial.Authority), "Thunderbird")
            { AccountType = "generic-dav" }, null);
        var temporary = Directory.CreateTempSubdirectory("magnolie-calendar275-readonly-");
        var journal = new NextcloudSyncJournal(Path.Combine(temporary.FullName, "fixture.dpapi"));
        using var client = new NextcloudDavClient(context, http, journal, new string('a', 64));
        var terms = NextcloudDavSelection.SplitCalendarItems(data["termine"] as JsonArray ?? [], sourceUid, true).Selected;
        var anniversaries = NextcloudDavSelection.SplitCalendarItems(data["jahrestage"] as JsonArray ?? [], sourceUid, true).Selected;
        var dead = NextcloudDavSelection.SplitCalendarTombstones(data["geloescht"]?["termine"] as JsonArray ?? [], sourceUid, true).Selected;
        var metadata = data["syncMetadaten"]?["nextcloud"]?["kalender"]?[sourceUid];
        var first = metadata?["initialisiert"]?.GetValue<bool>() != true;
        var cursor = data["letzteSyncs"]?["kalender"]?[sourceUid]?.GetValue<long>() ?? data["letzterSync"]?.GetValue<long>() ?? 0;
        var epoch = data["syncEpoch"]?.GetValue<string>() ?? "";
        string? failure = null;
        try
        {
            await new NextcloudCalendarSync(client, journal.BirthdayArchive(sourceUid, epoch)).SyncAsync(source,
                terms, anniversaries, dead, cursor, first || data["syncMetadaten"]?["ersteSyncLoeschungsfrei"]?.GetValue<bool>() == true, deadline.Token);
        }
        catch (MutationCaptured) { }
        catch (Exception error) { failure = error.GetType().Name; }
        JsonObject? remoteBefore = null;
        JsonArray? changedFields = null;
        JsonArray? modelChangedFields = null;
        string? localStatus = null;
        JsonObject? locationShape = null;
        JsonObject? uidFacts = null;
        if (handler.Mutation?["method"]?.GetValue<string>() == "PUT" && !deadline.IsCancellationRequested)
        {
            try
            {
                using var readRequest = new HttpRequestMessage(HttpMethod.Get, handler.Mutation["url"]!.GetValue<string>());
                if (handler.Mutation["ifMatch"] is JsonValue match && match.TryGetValue<string>(out var etag))
                    readRequest.Headers.TryAddWithoutValidation("If-Match", etag);
                using var response = await http.SendAsync(readRequest, deadline.Token);
                var text = response.StatusCode == HttpStatusCode.OK ? await response.Content.ReadAsStringAsync(deadline.Token) : "";
                if (Encoding.UTF8.GetByteCount(text) > 2 * 1024 * 1024) throw new InvalidDataException("Bounded original event limit.");
                remoteBefore = new JsonObject { ["status"] = (int)response.StatusCode, ["etag"] = response.Headers.ETag?.ToString(), ["body"] = text };
                var proposedItems = ExchangeCodec.ParseIcs(handler.Mutation["body"]!.GetValue<string>());
                var proposedUids = proposedItems.Termine.Concat(proposedItems.Jahrestage).OfType<JsonObject>()
                    .Select(value => ContactFields.Text(value, "uid")).ToHashSet(StringComparer.Ordinal);
                var freshSnapshot = await client.ReadCalendarAsync(source, deadline.Token);
                var uidMatches = freshSnapshot.SelectMany(item => {
                    var parsed = ExchangeCodec.ParseIcs(item.Text);
                    return parsed.Termine.OfType<JsonObject>().Select(value => (Value: value, Anniversary: false))
                        .Concat(parsed.Jahrestage.OfType<JsonObject>().Select(value => (Value: value, Anniversary: true)))
                        .Select(value => (item.Href, Uid: ContactFields.Text(value.Value, "uid"), value.Anniversary, Data: value.Value));
                }).ToArray();
                static string ResourceName(Uri uri) => Uri.UnescapeDataString(uri.AbsolutePath.Split('/').Last()).Replace(".ics", "", StringComparison.Ordinal);
                uidFacts = new JsonObject { ["resources"] = freshSnapshot.Count,
                    ["localUidCopies"] = terms.Concat(anniversaries).OfType<JsonObject>().Count(value => proposedUids.Contains(ContactFields.Text(value, "uid"))),
                    ["localUidMappedCopies"] = terms.Concat(anniversaries).OfType<JsonObject>().Count(value => proposedUids.Contains(ContactFields.Text(value, "uid")) && ContactFields.Source(value, sourceUid) is not null),
                    ["matchingExistingUid"] = uidMatches.Count(value => proposedUids.Contains(value.Uid)),
                    ["matchingAnniversaryUid"] = uidMatches.Count(value => value.Anniversary && proposedUids.Contains(value.Uid)),
                    ["matchingAppointmentUid"] = uidMatches.Count(value => !value.Anniversary && proposedUids.Contains(value.Uid)),
                    ["existingNamesMatchUid"] = uidMatches.Count(value => ResourceName(value.Href) == value.Uid),
                    ["proposedNameMatchesUid"] = proposedUids.Contains(ResourceName(new Uri(handler.Mutation["url"]!.GetValue<string>()))) };
                var matchingRemote = uidMatches.Where(value => proposedUids.Contains(value.Uid)).ToArray();
                if (matchingRemote.Length == 1) uidFacts["localCopies"] = new JsonArray(terms.Concat(anniversaries).OfType<JsonObject>()
                    .Where(value => proposedUids.Contains(ContactFields.Text(value, "uid"))).Select(value => (JsonNode)new JsonObject {
                        ["hasMapping"] = ContactFields.Source(value, sourceUid) is not null,
                        ["mappingMatchesExistingResource"] = ContactFields.Text(ContactFields.Source(value, sourceUid) ?? new JsonObject(), "id") == NextcloudCalendarSync.RemoteKey(matchingRemote[0].Href, matchingRemote[0].Data),
                        ["differentFields"] = new JsonArray(NextcloudCalendarSync.Fields.Where(field => SyncBaseline.Hash(value, [field]) != SyncBaseline.Hash(matchingRemote[0].Data, [field])).Select(field => JsonValue.Create(field)).ToArray())
                    }).ToArray());
                if (response.StatusCode == HttpStatusCode.OK)
                {
                    var proposed = ExchangeCodec.ParseIcs(handler.Mutation["body"]!.GetValue<string>());
                    var prior = ExchangeCodec.ParseIcs(text);
                    var proposedValues = proposed.Termine.Concat(proposed.Jahrestage).OfType<JsonObject>().ToArray();
                    var priorValues = prior.Termine.Concat(prior.Jahrestage).OfType<JsonObject>().ToArray();
                    if (proposedValues.Length == 1 && priorValues.Length == 1)
                    {
                        changedFields = new JsonArray(NextcloudCalendarSync.Fields.Where(field =>
                            SyncBaseline.Hash(proposedValues[0], [field]) != SyncBaseline.Hash(priorValues[0], [field]))
                            .Select(field => JsonValue.Create(field)).ToArray());
                        var matching = terms.Concat(anniversaries).OfType<JsonObject>().Where(value =>
                            ContactFields.Text(value, "uid") == ContactFields.Text(proposedValues[0], "uid")).ToArray();
                        if (matching.Length == 1)
                        {
                            modelChangedFields = new JsonArray(NextcloudCalendarSync.Fields.Where(field =>
                                SyncBaseline.Hash(matching[0], [field]) != SyncBaseline.Hash(priorValues[0], [field]))
                                .Select(field => JsonValue.Create(field)).ToArray());
                            var status = ContactFields.Text(matching[0], "icsStatus");
                            localStatus = status.Length == 0 ? "missing" : status is "CONFIRMED" or "TENTATIVE" or "CANCELLED" ? status : "other";
                            locationShape = new JsonObject { ["localPresent"] = matching[0].ContainsKey("ort"),
                                ["localLength"] = ContactFields.Text(matching[0], "ort").Length,
                                ["remoteLength"] = ContactFields.Text(priorValues[0], "ort").Length,
                                ["serializedLength"] = ContactFields.Text(proposedValues[0], "ort").Length,
                                ["roundtripLocation"] = (matching[0]["icsRoundtrip"] as JsonArray)?.Any(line =>
                                    line is JsonValue part && part.TryGetValue<string>(out var lineText) &&
                                    Regex.IsMatch(lineText, @"^LOCATION(?:;[^:]*)?:", RegexOptions.IgnoreCase)) == true };
                        }
                    }
                }
            }
            catch (Exception error) { remoteBefore = new JsonObject { ["failureType"] = error.GetType().Name }; }
        }
        var result = new JsonObject { ["writes"] = false, ["reads"] = handler.Reads, ["source"] = sourceUid,
            ["savedPhase"] = saved.Phase, ["firstCalendarRun"] = first, ["cursor"] = cursor,
            ["failureType"] = failure, ["plannedMutation"] = handler.Mutation, ["remoteBefore"] = remoteBefore, ["changedFields"] = changedFields,
            ["modelChangedFields"] = modelChangedFields, ["localStatus"] = localStatus, ["locationShape"] = locationShape, ["uidFacts"] = uidFacts };
        await File.WriteAllTextAsync(receiptPath, result.ToJsonString(), CancellationToken.None);
        Console.WriteLine(new JsonObject { ["writes"] = false, ["reads"] = handler.Reads,
            ["captured"] = handler.Mutation is not null, ["failureType"] = failure }.ToJsonString());
        return failure is null ? 0 : 1;
    }
}
