using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Separate protected proof survives the ordinary sync transaction's completion.
internal sealed class CalendarBirthdayArchive(string path, string binding, ISecretProtector protector)
{
    private const long MaximumBytes = 16 * 1024 * 1024;
    internal bool Exists => File.Exists(path);
    internal IDisposable Acquire()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        return new FileStream(path + ".lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    }
    internal JsonObject Load()
    {
        if (!Exists) return new JsonObject();
        if (new FileInfo(path).Length > MaximumBytes) throw new InvalidDataException("Calendar cleanup archive limit exceeded.");
        var saved = new NextcloudSyncJournal(path, protector).Load();
        if (saved is null || saved.Value.Id != binding || saved.Value.Phase != "birthday-cleanup")
            throw new InvalidDataException("Invalid calendar cleanup binding.");
        return saved.Value.Payload;
    }
    internal void Save(JsonObject state)
    {
        if (Encoding.UTF8.GetByteCount(state.ToJsonString()) > MaximumBytes / 2)
            throw new InvalidDataException("Calendar cleanup archive limit exceeded.");
        new NextcloudSyncJournal(path, protector).Save(binding, "birthday-cleanup", state);
    }
}

internal static class CalendarBirthdayCleanup
{
    internal sealed record Plan(string Contact, string Date, string KeepUid, string RemoveUid,
        NextcloudDavObject Keep, NextcloudDavObject Remove);
    private sealed record Node(string Kind, List<CalendarRecurrence.Property> Properties, List<Node> Children);
    private sealed record Candidate(string Uid, Node Event, string Date, string MonthDay, NextcloudDavObject Resource);
    private static readonly HashSet<string> Metadata = new(StringComparer.Ordinal)
        { "UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "X-EVOLUTION-CALDAV-ETAG", "X-EVOLUTION-ALARM-UID" };
    private static string Text(JsonObject value, string key) => ContactFields.Text(value, key);
    private static string Hash(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
    private static bool Birthday(string value) => value.Equals("birthday", StringComparison.OrdinalIgnoreCase) || value.Equals("Geburtstag", StringComparison.OrdinalIgnoreCase);

    private static Node Parse(string text)
    {
        var stack = new Stack<Node>(); Node? root = null;
        foreach (var line in Regex.Replace(text, @"\r?\n[ \t]", "").Replace("\r\n", "\n").Split('\n'))
        {
            if (line.Length == 0) continue;
            if (line.StartsWith("BEGIN:", StringComparison.OrdinalIgnoreCase))
            {
                var node = new Node(line[6..].ToUpperInvariant(), [], []);
                if (stack.TryPeek(out var parent)) parent.Children.Add(node);
                else if (root is null) root = node;
                else throw new InvalidDataException("Ambiguous calendar root.");
                stack.Push(node);
            }
            else if (line.StartsWith("END:", StringComparison.OrdinalIgnoreCase))
            {
                if (!stack.TryPop(out var node) || node.Kind != line[4..].ToUpperInvariant()) throw new InvalidDataException("Unbalanced calendar component.");
            }
            else if (stack.TryPeek(out var current) && CalendarRecurrence.ParseProperty(line) is { } property) current.Properties.Add(property);
            else throw new InvalidDataException("Invalid calendar property.");
        }
        if (stack.Count != 0 || root is null) throw new InvalidDataException("Incomplete calendar resource.");
        return root;
    }
    private static IEnumerable<Node> Events(Node node) => (node.Kind == "VEVENT" ? new[] { node } : []).Concat(node.Children.SelectMany(Events));
    private static string One(Node node, string name)
    {
        var values = node.Properties.Where(value => value.Name == name).ToArray();
        if (values.Length > 1) throw new InvalidDataException("Ambiguous calendar property.");
        return values.Length == 0 ? "" : values[0].Value;
    }
    private static string Canonical(Node node, bool unknown = false)
    {
        var fields = new List<string>();
        foreach (var property in node.Properties)
        {
            if (Metadata.Contains(property.Name)) continue;
            if (unknown && property.Name == "X-MAGNOLIE-DATE" && Regex.IsMatch(property.Value, @"^--\d{2}-\d{2}$")) continue;
            var value = unknown && property.Name is "DTSTART" or "DTEND" && Regex.IsMatch(property.Value, @"^\d{8}$") ? property.Value[4..] : property.Value;
            fields.Add(JsonSerializer.Serialize(new object[] { property.Name, property.Parameters.Order(StringComparer.Ordinal).ToArray(), value }));
        }
        return JsonSerializer.Serialize(new object[] { node.Kind, fields.Order(StringComparer.Ordinal).ToArray(), node.Children.Select(child => Canonical(child, unknown)).Order(StringComparer.Ordinal).ToArray() });
    }
    internal static Dictionary<string, NextcloudDavObject> Index(IReadOnlyList<NextcloudDavObject> resources)
    {
        var result = new Dictionary<string, NextcloudDavObject>(StringComparer.Ordinal); var hrefs = new HashSet<Uri>();
        foreach (var resource in resources)
        {
            var root = Parse(resource.Text);
            if (root.Kind != "VCALENDAR" || !hrefs.Add(resource.Href)) throw new InvalidDataException("Ambiguous DAV resource.");
            foreach (var uid in Events(root).Select(node => One(node, "UID")).Distinct(StringComparer.Ordinal))
                if (uid.Length == 0 || !result.TryAdd(uid, resource)) throw new InvalidDataException("Ambiguous DAV UID.");
        }
        return result;
    }
    private static bool Bound(JsonObject item, string source) => Text(item, "syncKalenderUid") == source || Text(item, "icsQuelleId") == source;
    private static bool Clean(JsonObject item, string source) => ContactFields.Source(item, source) is { } mapping && Text(mapping, "inhaltFormat") == "windows-1" && Text(mapping, "inhaltSha256") == SyncBaseline.Hash(item, NextcloudCalendarSync.Fields);
    private static IEnumerable<string> Uids(JsonObject item) => new[] { Text(item, "uid"), Text(item, "icsSerienUid") }.Where(uid => uid.Length > 0).Distinct(StringComparer.Ordinal);
    private static string Key(Uri href, string uid) => NextcloudCalendarSync.RemoteKey(href, new JsonObject { ["uid"] = uid });

    internal static IReadOnlyList<Plan> PlanCleanup(JsonArray local, IReadOnlyList<NextcloudDavObject> resources, string source)
    {
        var candidates = new Dictionary<string, Candidate>(StringComparer.Ordinal);
        try
        {
            _ = Index(resources);
            foreach (var resource in resources)
            {
                var root = Parse(resource.Text); var events = Events(root).ToArray();
                if (events.Length != 1 || root.Children.Any(child => child.Kind != "VEVENT") || root.Properties.Any(property => property.Name is not ("VERSION" or "PRODID" or "CALSCALE"))) continue;
                var node = events[0]; var uid = One(node, "UID");
                if (node.Properties.Any(property => property.Name is "RECURRENCE-ID" or "RDATE" or "EXDATE" or "EXRULE" or "ATTENDEE" or "ORGANIZER") || One(node, "RRULE").ToUpperInvariant() != "FREQ=YEARLY" || One(node, "STATUS").ToUpperInvariant() is not ("" or "CONFIRMED") || node.Children.Any(child => child.Kind != "VALARM")) continue;
                var kind = new[] { "X-MAGNOLIE-TYPE-ID", "X-MAGNOLIE-JAHRESTAG-TYP", "X-MAGNOLIE-TYP" }.Select(key => One(node, key)).FirstOrDefault(value => value.Length > 0) ?? "";
                if (!Birthday(kind)) continue;
                var start = One(node, "DTSTART"); var end = One(node, "DTEND");
                if (!DateTime.TryParseExact(start, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var startDate)) continue;
                if (end.Length > 0)
                {
                    if (!DateTime.TryParseExact(end, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var endDate) || (endDate - startDate).Days != 1) continue;
                }
                else if (One(node, "DURATION") is not ("" or "P1D")) continue;
                var date = One(node, "X-MAGNOLIE-DATE");
                candidates.Add(uid, new Candidate(uid, node, date.Length > 0 ? date : startDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), startDate.ToString("MM-dd", CultureInfo.InvariantCulture), resource));
            }
        }
        catch (InvalidDataException) { return []; }
        var bound = local.OfType<JsonObject>().Where(item => Bound(item, source)).ToArray();
        var claims = bound.SelectMany(item => Uids(item).Select(uid => (Uid: uid, Item: item))).GroupBy(value => value.Uid, StringComparer.Ordinal).ToDictionary(group => group.Key, group => group.Select(value => value.Item).ToArray(), StringComparer.Ordinal);
        var plans = new List<Plan>();
        foreach (var group in bound.Where(item => Birthday(Text(item, "typ")) && Text(item, "kontaktId").Length > 0 && Text(item, "kontaktId") == Text(item, "kontaktId").Trim() && Regex.IsMatch(Text(item, "datum"), @"^(?:\d{4}|-)-\d{2}-\d{2}$")).GroupBy(item => (Contact: Text(item, "kontaktId"), Date: Text(item, "datum"))))
        {
            var uids = group.SelectMany(Uids).ToHashSet(StringComparer.Ordinal);
            var matches = uids.Where(candidates.ContainsKey).Select(uid => candidates[uid]).ToArray();
            if (matches.Length < 2 || matches.Any(item => item.MonthDay != group.Key.Date[^5..])) continue;
            if (uids.Any(uid => claims[uid].Any(item => Text(item, "kontaktId") != group.Key.Contact || Text(item, "datum") != group.Key.Date || !Birthday(Text(item, "typ")) || !Clean(item, source)))) continue;
            // Let the ordinary merge import remote changes first. A clean local
            // baseline alone does not prove that it describes this remote revision.
            if (matches.Any(candidate => claims[candidate.Uid].Any(item =>
                    Text(ContactFields.Source(item, source)!, "etag") != candidate.Resource.ETag))) continue;
            if (matches.Any(candidate => !group.Any(item => Uids(item).Contains(candidate.Uid) && Text(ContactFields.Source(item, source)!, "id") == Key(candidate.Resource.Href, candidate.Uid)))) continue;
            var exact = matches.Select(item => Canonical(item.Event)).Distinct(StringComparer.Ordinal).Count() == 1;
            var unknown = group.Key.Date.StartsWith("--", StringComparison.Ordinal) && matches.All(item => One(item.Event, "X-MAGNOLIE-DATE") is "" || One(item.Event, "X-MAGNOLIE-DATE") == group.Key.Date) && matches.Select(item => Canonical(item.Event, true)).Distinct(StringComparer.Ordinal).Count() == 1;
            var keeper = matches.Where(item => item.Date == group.Key.Date).OrderBy(item => One(item.Event, "CREATED"), StringComparer.Ordinal).ThenBy(item => item.Uid, StringComparer.Ordinal).FirstOrDefault();
            if (keeper is null || !(exact || unknown)) continue;
            plans.AddRange(matches.Where(item => item.Uid != keeper.Uid).Select(item => new Plan(group.Key.Contact, group.Key.Date, keeper.Uid, item.Uid, keeper.Resource, item.Resource)));
        }
        return plans;
    }

    internal static async Task<HashSet<string>> ApplyAsync(NextcloudDavClient client, NextcloudDavSource source, JsonArray local, IReadOnlyList<NextcloudDavObject> snapshot, CalendarBirthdayArchive archive, CancellationToken token)
    {
        var plans = PlanCleanup(local, snapshot, source.Uid); var affected = new HashSet<string>(StringComparer.Ordinal);
        if (plans.Count == 0 && !archive.Exists) return affected;
        using var lease = archive.Acquire();
        var state = archive.Load();
        if (state.Count == 0) { state["source"] = source.Uid; state["operations"] = new JsonObject(); }
        if (Text(state, "source") != source.Uid || state["operations"] is not JsonObject operations) throw new InvalidDataException("Invalid birthday cleanup journal.");
        async Task<NextcloudDavObject?> Read(string uid) => Index(await client.ReadCalendarAsync(source, token).ConfigureAwait(false)).GetValueOrDefault(uid);
        void Rebind(Plan plan, NextcloudDavObject keeper)
        {
            var parsed = ExchangeCodec.ParseIcs(keeper.Text).Jahrestage.OfType<JsonObject>().Single(item => Text(item, "uid") == plan.KeepUid);
            foreach (var item in local.OfType<JsonObject>().Where(item => Bound(item, source.Uid) && Uids(item).Contains(plan.RemoveUid)))
            {
                if (Text(item, "kontaktId") != plan.Contact || Text(item, "datum") != plan.Date || !Clean(item, source.Uid) || Text(ContactFields.Source(item, source.Uid)!, "id") != Key(plan.Remove.Href, plan.RemoveUid)) throw new InvalidDataException("A birthday cleanup binding changed.");
                NextcloudCalendarSync.CopyCalendar(item, parsed);
                NextcloudCalendarSync.SetSource(item, source.Uid, Key(keeper.Href, plan.KeepUid), keeper.ETag, parsed);
            }
            affected.Add(plan.KeepUid);
        }
        foreach (var entry in operations)
        {
            if (entry.Value is not JsonObject operation || Text(operation, "phase") is not ("prepared" or "removed")) throw new InvalidDataException("Invalid birthday cleanup operation.");
            var plan = operation["plan"]?.Deserialize<Plan>() ?? throw new InvalidDataException("Missing birthday cleanup plan.");
            if (plan.RemoveUid != entry.Key || plan.KeepUid == plan.RemoveUid || !plan.Keep.Href.AbsoluteUri.StartsWith(source.Href.AbsoluteUri.TrimEnd('/') + "/", StringComparison.Ordinal) || !plan.Remove.Href.AbsoluteUri.StartsWith(source.Href.AbsoluteUri.TrimEnd('/') + "/", StringComparison.Ordinal)) throw new InvalidDataException("Invalid birthday cleanup identity.");
            if (!local.OfType<JsonObject>().Any(item => Bound(item, source.Uid) && Uids(item).Contains(plan.RemoveUid))) continue;
            if (await Read(plan.RemoveUid).ConfigureAwait(false) is null && await Read(plan.KeepUid).ConfigureAwait(false) is { } keeper)
            {
                if (Hash(keeper.Text) != Hash(plan.Keep.Text)) throw new InvalidDataException("Birthday survivor changed during recovery.");
                operation["phase"] = "removed"; archive.Save(state); Rebind(plan, keeper);
            }
        }
        foreach (var plan in PlanCleanup(local, snapshot, source.Uid))
        {
            var keeper = await Read(plan.KeepUid).ConfigureAwait(false); var extra = await Read(plan.RemoveUid).ConfigureAwait(false);
            if (keeper is null || extra is null || Hash(keeper.Text) != Hash(plan.Keep.Text) || Hash(extra.Text) != Hash(plan.Remove.Text)) throw new InvalidDataException("Birthday cleanup snapshot changed.");
            if (!Regex.IsMatch(extra.ETag, "^\"[^\"\\x00-\\x20\\x7f]*\"$")) throw new InvalidDataException("Birthday cleanup requires a strong ETag.");
            var current = plan with { Keep = keeper, Remove = extra };
            var operation = new JsonObject { ["phase"] = "prepared", ["plan"] = JsonSerializer.SerializeToNode(current) };
            operations[plan.RemoveUid] = operation; archive.Save(state);
            await client.DeleteAsync(extra.Href, extra.ETag, token).ConfigureAwait(false);
            if (await Read(plan.RemoveUid).ConfigureAwait(false) is not null || await Read(plan.KeepUid).ConfigureAwait(false) is not { } retained || Hash(retained.Text) != Hash(keeper.Text)) throw new InvalidDataException("Birthday cleanup readback failed.");
            operation["phase"] = "removed"; archive.Save(state); Rebind(current, retained);
        }
        // A later replay must not export a second local alias of a proven survivor.
        foreach (var entry in operations.Select(pair => pair.Value).OfType<JsonObject>())
            if (Text(entry, "phase") == "removed" && entry["plan"]?.Deserialize<Plan>() is { } plan) affected.Add(plan.KeepUid);
        return affected;
    }
}
