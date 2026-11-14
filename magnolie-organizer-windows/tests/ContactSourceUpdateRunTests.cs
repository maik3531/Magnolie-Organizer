using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security;
using System.Diagnostics;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContactSourceUpdateRunTests
{
    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] plain) => plain.Select(value => (byte)(value ^ 0x5a)).ToArray();
        public byte[] Unprotect(byte[] encrypted) => Protect(encrypted);
    }
    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handle) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) => handle(request);
    }
    private sealed class Source : IDisposable
    {
        private readonly string root = Path.Combine(Path.GetTempPath(), "magnolie-contact-source-" + Guid.NewGuid().ToString("N"));
        private readonly HttpClient http;
        internal NextcloudMailboxSettingsStore Settings = null!;
        internal readonly NextcloudDavClient Client;
        internal HttpClient Transport => http;
        internal readonly string WireUid;
        internal NextcloudDavSource Catalog = null!;
        internal string Wire, ETag = "\"v1\"";
        internal bool? Permission = true;
        internal bool FailWrite, FailDiscovery, BadReadback, RequireSaved, Saved;
        internal string ReadbackUidMode = "";
        internal bool ExtraBook;
        internal string ExtraWire = "", ExtraETag = "\"extra-v1\"";
        internal NextcloudDavSource ExtraCatalog = null!;
        internal int ExtraWrites;
        internal int Writes, Reads, Discoveries;
        internal Action? BeforeContentRead;
        internal Action? BeforeDiscovery;
        private readonly string origin;
        internal Source(string name, string accountType, JsonObject data)
        {
            Directory.CreateDirectory(root); WireUid = "provider-original-" + name; origin = "https://" + name + ".invalid";
            var card = data.DeepClone().AsObject(); card["uid"] = WireUid;
            using var input = JsonDocument.Parse(new JsonArray(card).ToJsonString());
            Wire = ExchangeCodec.WriteVCard(input.RootElement).Text;
            ExtraWire = Wire.Replace("UID:" + WireUid + "\r\n", "UID:other-original-" + name + "\r\n", StringComparison.Ordinal);
            var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"), Path.Combine(root, "secret.dat"), new Protector());
            Settings = settings;
            settings.SaveConfiguration(new NextcloudMailboxSettings(true, false, origin + "/nc", "synthetic") { AccountType = accountType }, "synthetic-only", false);
            http = new HttpClient(new Handler(Handle)); Client = new NextcloudDavClient(settings, http);
        }
        private static HttpResponseMessage Xml(string text) => new(HttpStatusCode.MultiStatus) { Content = new StringContent(text) };
        private async Task<HttpResponseMessage> Handle(HttpRequestMessage request)
        {
            if (request.Method.Method == "PROPFIND")
            {
                Discoveries++;
                BeforeDiscovery?.Invoke();
                if (FailDiscovery) throw new HttpRequestException("controlled discovery failure");
                if (!request.Headers.TryGetValues("Depth", out var depths) || depths.Single() != "1")
                    return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/</d:href><d:propstat><d:prop><c:addressbook-home-set><d:href>/nc/books/</d:href></c:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                var privilege = Permission is null ? "" : "<d:current-user-privilege-set><d:privilege><d:" + (Permission == true ? "write-content" : "read") + "/></d:privilege></d:current-user-privilege-set>";
                var entry = "<d:response><d:href>/nc/books/original/</d:href><d:propstat><d:prop><d:displayname>Original</d:displayname><d:resourcetype><c:addressbook/></d:resourcetype>" + privilege + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>";
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\">" + entry +
                    (ExtraBook ? entry.Replace("/original/", "/secondary/", StringComparison.Ordinal) : "") + "</d:multistatus>");
            }
            TestAssert.That(!RequireSaved || Saved, "Provider IO preceded the original durable SaveACK");
            if (request.Method.Method == "REPORT")
            {
                BeforeContentRead?.Invoke();
                Reads++;
                if (ExtraBook && request.RequestUri!.AbsolutePath.Contains("/secondary/", StringComparison.Ordinal))
                    return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/secondary/person.vcf</d:href><d:propstat><d:prop><d:getetag>" + SecurityElement.Escape(ExtraETag) + "</d:getetag><c:address-data>" + SecurityElement.Escape(ExtraWire) + "</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/original/person.vcf</d:href><d:propstat><d:prop><d:getetag>" + SecurityElement.Escape(ETag) + "</d:getetag><c:address-data>" + SecurityElement.Escape(Wire) + "</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
            }
            if (ExtraBook && request.Method == HttpMethod.Put && request.RequestUri!.AbsoluteUri == origin + "/nc/books/secondary/person.vcf")
            {
                TestAssert.That(request.Headers.IfMatch.Single().ToString() == ExtraETag, "Second original source revision lost");
                ExtraWire = await request.Content!.ReadAsStringAsync();
                TestAssert.That(ExtraWire.Contains("UID:other-original-", StringComparison.Ordinal) && !ExtraWire.Contains("UID:canonical-person", StringComparison.Ordinal), "Second native source UID was replaced");
                ExtraWrites++; ExtraETag = "\"extra-write-" + ExtraWrites + "\"";
                return new(HttpStatusCode.NoContent) { Headers = { ETag = new EntityTagHeaderValue(ExtraETag) } };
            }
            TestAssert.That(request.Method == HttpMethod.Put && request.RequestUri!.AbsoluteUri == origin + "/nc/books/original/person.vcf" &&
                request.Headers.IfMatch.Single().ToString() == ETag, "Original provider resource/revision lost or create/delete attempted");
            if (FailWrite) throw new HttpRequestException("controlled provider failure");
            var text = await request.Content!.ReadAsStringAsync();
            TestAssert.That(text.Contains("UID:" + WireUid + "\r\n", StringComparison.Ordinal) && !text.Contains("UID:canonical-person", StringComparison.Ordinal),
                "Provider's original vCard UID was overwritten by canonical UID");
            Wire = BadReadback ? text.Replace("Canonical note", "Independent change", StringComparison.Ordinal) : text;
            if (ReadbackUidMode.Length > 0) Wire = Wire.Replace("UID:" + WireUid + "\r\n",
                ReadbackUidMode == "missing" ? "" : "UID:unexpected-source-identity\r\n", StringComparison.Ordinal);
            Writes++; ETag = "\"write-" + Writes + "\"";
            return new(HttpStatusCode.NoContent) { Headers = { ETag = new EntityTagHeaderValue(ETag) } };
        }
        internal async Task<RemoteContact> OriginalAsync()
        {
            Catalog = (await Client.ListSourcesAsync(default, calendars: false)).AddressBooks.Single();
            return (await new NextcloudCardDavRemote(Client, Catalog).ReadAsync(default)).Single();
        }
        internal async Task<RemoteContact> ExtraOriginalAsync()
        {
            ExtraBook = true;
            ExtraCatalog = (await Client.ListSourcesAsync(default, calendars: false)).AddressBooks.Single(item => item.Href.AbsolutePath.EndsWith("/secondary/", StringComparison.Ordinal));
            return (await new NextcloudCardDavRemote(Client, ExtraCatalog).ReadAsync(default)).Single();
        }
        internal ContactSourceAdmission Admit() => new(Catalog.Uid, new NextcloudCardDavRemote(Client, Catalog), Catalog.CanUpdate, async token => {
            var current = (await Client.ListSourcesAsync(token, calendars: false)).AddressBooks.SingleOrDefault(source => source.Uid == Catalog.Uid);
            if (current?.CanUpdate != true || current.Href != Catalog.Href) throw new UnauthorizedAccessException("Original source permission withdrawn");
        });
        internal Task<ContactSourceDavFactory> OpenFactoryAsync(NativeDavContactUpdateApproval approval,
            Action current, Func<CancellationToken, Task> protect, CancellationToken cancellation = default) =>
            ContactSourceDavFactory.OpenAsync(Settings, approval, current, protect, cancellation, http);
        public void Dispose()
        { Client.Dispose(); http.Dispose(); Directory.Delete(root, recursive: true); }
    }
    internal static async Task RunAsync()
    {
        foreach (var mode in new[] { "success", "failure", "readback", "readonly", "unknown", "revoked", "conflict", "ambiguous", "save-failed", "book-changed", "readback-uid", "readback-uid-missing" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var first = new Source("first", "generic-dav", original);
            using var second = new Source("second", "nextcloud", original);
            var a = await first.OriginalAsync(); var b = await second.OriginalAsync();
            var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, first.Catalog.Uid, a, remoteBaseline: true);
            ContactFields.SetSource(local, second.Catalog.Uid, b, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var unrelated = new JsonObject { ["id"] = "unbound", ["uid"] = "unbound", ["sync"] = true, ["notiz"] = "Do not export" };
            var contacts = new JsonArray(local, unrelated); var before = contacts.ToJsonString();
            if (mode == "ambiguous")
            {
                var duplicate = local.DeepClone().AsObject(); duplicate["id"] = "duplicate"; duplicate["uid"] = "other-canonical";
                duplicate["syncQuellen"]!.AsObject().Remove(second.Catalog.Uid); contacts.Add(duplicate);
                before = contacts.ToJsonString();
            }
            var admission = first.Admit();
            if (mode is "readonly" or "unknown") admission = admission with { CanUpdate = mode == "readonly" ? false : null };
            first.FailWrite = mode == "failure"; first.BadReadback = mode == "readback";
            if (mode is "readback-uid" or "readback-uid-missing") first.ReadbackUidMode = mode == "readback-uid" ? "changed" : "missing";
            if (mode == "revoked") first.Permission = false;
            if (mode == "conflict") { first.Wire = first.Wire.Replace("NOTE:Original", "NOTE:Concurrent source edit", StringComparison.Ordinal); first.ETag = "\"concurrent\""; }
            first.RequireSaved = second.RequireSaved = true;
            var saved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var aReads = first.Reads; var bReads = second.Reads;
            var current = true;
            var running = ContactSourceUpdateRun.RunAsync(contacts, [admission, second.Admit()], () => saved.Task,
                () => { if (!current) throw new InvalidOperationException("Original book changed"); });
            TestAssert.That(!running.IsCompleted && first.Reads == aReads && second.Reads == bReads && first.Writes + second.Writes == 0,
                "Two-source planner bypassed SaveACK before provider IO");
            if (mode is "save-failed" or "book-changed")
            {
                if (mode == "save-failed") saved.TrySetException(new IOException("Controlled durable save failure"));
                else { current = false; saved.TrySetResult(); }
                try { await running; throw new Exception("Unconfirmed/stale original save reached provider execution"); }
                catch (Exception error) when (mode == "save-failed" && error is IOException || mode == "book-changed" && error is InvalidOperationException) { }
                TestAssert.That(first.Writes + second.Writes == 0 && first.Reads == aReads && second.Reads == bReads && contacts.ToJsonString() == before,
                    "Missing SaveACK/changed original book performed provider IO or changed contacts");
                continue;
            }
            first.Saved = second.Saved = true; saved.TrySetResult();
            var result = await running;
            TestAssert.That(contacts.ToJsonString() == before && result.Contacts.Count == contacts.Count &&
                result.Contacts[0]!["uid"]!.GetValue<string>() == "canonical-person" && JsonNode.DeepEquals(result.Contacts[1], unrelated),
                "Source run changed input, canonical identity or unbound contact");
            TestAssert.That(second.Writes == 1 && result.Sources[second.Catalog.Uid].Errors == 0 && second.Wire.Contains("NOTE:Canonical note", StringComparison.Ordinal),
                "Independent authorized second provider was skipped after first-provider hold/conflict/failure");
            if (mode == "success") TestAssert.That(first.Writes == 1 && result.Sources[first.Catalog.Uid].Errors == 0, "Both bound providers did not receive canonical update");
            else if (mode == "conflict") TestAssert.That(first.Writes == 0 && result.Sources[first.Catalog.Uid].Conflicts == 1,
                "Concurrent source value was overwritten");
            else TestAssert.That(result.Sources[first.Catalog.Uid].Errors > 0 &&
                JsonNode.DeepEquals(result.Contacts[0]!["syncQuellen"]![first.Catalog.Uid], local["syncQuellen"]![first.Catalog.Uid]),
                "Failed/unknown/read-only source acquired a successful baseline");
            if (mode is "readonly" or "unknown" or "revoked") TestAssert.That(first.Writes == 0 && first.Reads == aReads, "Unadmitted source received content IO");
            if (mode == "success")
            {
                var writes = first.Writes + second.Writes;
                await ContactSourceUpdateRun.RunAsync(result.Contacts, [first.Admit(), second.Admit()], () => Task.CompletedTask, () => { });
                TestAssert.That(first.Writes + second.Writes == writes, "Already acknowledged sources were rewritten on repeat");
            }
        }
        await SavedBookBoundaryAsync();
        await DavFactoryAsync();
        await ApprovalScopeAsync();
        ContactSourceAccountTests.Run();
        await SavedDavOrchestrationAsync();
        await SavedResultCommitAsync();
        await NativeSessionAsync();
        var dialogProduct = Environment.GetEnvironmentVariable("MAGNOLIE_CONTACT_DIALOG_PRODUCT");
        if (OperatingSystem.IsWindows() && !string.IsNullOrEmpty(dialogProduct)) await ContactSourceNativeDialogTests.RunAsync(dialogProduct);
        if (!OperatingSystem.IsWindows()) await NativeFrontendWireAsync();
    }

    private static async Task NativeSessionAsync()
    {
        using (BridgeDispatcherContract.Parse("{\"cmd\":\"kontakt_originalquellen_freigabe\",\"requestId\":\"native-dialog\"}")) { }
        using (BridgeDispatcherContract.Parse("{\"cmd\":\"kontakt_originalquellen_widerrufen\"}")) { }
        using (BridgeDispatcherContract.Parse("{\"cmd\":\"kontakt_originalquellen_update\",\"requestId\":\"native-run\",\"standSha256\":\"context-not-grant\"}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"kontakt_originalquellen_update\",\"requestId\":\"native-run\",\"standSha256\":\"context-not-grant\",\"sources\":[\"unapproved\"]}"),
            "Native source command accepted renderer source grants");
        foreach (var mode in new[] { "success", "no-grant", "cancel-dialog", "empty-selection", "no-wlan", "wlan-during-read",
            "wlan-during-protect", "revoke-during-protect", "snapshot-failed", "changed-book", "restore", "forged-hash", "revoked", "stale-dialog", "cancel-run" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var source = new Source("session", "generic-dav", original);
            var remote = await source.OriginalAsync(); var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, source.Catalog.Uid, remote, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var document = new JsonObject { ["kontakte"] = new JsonArray(local), ["syncEpoch"] = "native-session-epoch",
                ["notizen"] = new JsonArray(new JsonObject { ["text"] = "Unchanged synthetic native session" }) };
            if (mode == "restore") document["syncNachRestore"] = new JsonObject { ["loeschungsfrei"] = true };
            var root = Path.Combine(Path.GetTempPath(), "magnolie-native-source-session-" + Guid.NewGuid().ToString("N"));
            try
            {
                var host = new PersonalActorNativeSaveHost(root, document.ToJsonString());
                var wlan = true; var protections = 0; ContactSourceNativeSession? session = null;
                session = new(host.Snapshot, host.Saved, source.Settings, host.SourceResultCommit, () => wlan, snapshot =>
                {
                    protections++;
                    if (mode == "snapshot-failed") throw new IOException("Controlled actual native protection failure");
                    new AtomicStore().WriteRecoverableJson(Path.Combine(root, "pre-contact.json"), snapshot.Text);
                    if (mode == "wlan-during-protect") wlan = false;
                    if (mode == "revoke-during-protect") session!.Revoke();
                }, source.Transport);
                TestAssert.That(session.GrantCount == 0, "New native source session was not default OFF");
                var originalHash = host.Saved()!.Sha256;
                if (mode is not ("no-grant" or "restore"))
                {
                    try
                    {
                        var changed = await session.ConfigureAsync(async (catalog, selected, token) =>
                        {
                            TestAssert.That(catalog.Count == 1 && selected.Count == 0, "Native session preselected a discovered source");
                            if (mode == "stale-dialog")
                            {
                                var edited = document.DeepClone().AsObject(); edited["changedWhileDialogOpen"] = true;
                                await host.SaveOriginalContactResultAsync("", edited);
                            }
                            return mode == "cancel-dialog" ? null : new[] { catalog.Single().Uid };
                        });
                        if (mode == "stale-dialog") throw new Exception("Stale native decision granted access");
                        TestAssert.That(changed == (mode != "cancel-dialog") && session.GrantCount == (mode == "cancel-dialog" ? 0 : 1),
                            "Native dialog cancel/affirmation had wrong grant result");
                    }
                    catch (InvalidOperationException error) when (mode == "stale-dialog" && error.Message == "contact_source_approval_context_changed")
                    { TestAssert.That(session.GrantCount == 0 && source.Writes == 0, "Stale native dialog retained an approval"); continue; }
                    if (mode == "empty-selection") await session.ConfigureAsync((_, _, _) => Task.FromResult<IReadOnlyList<string>?>(Array.Empty<string>()));
                }
                var reads = source.Reads; var discoveries = source.Discoveries;
                if (mode == "no-wlan") wlan = false;
                if (mode == "wlan-during-read") source.BeforeContentRead = () => wlan = false;
                if (mode == "revoked") session.Revoke();
                if (mode == "forged-hash") originalHash = new string('0', 64);
                if (mode == "changed-book")
                {
                    var edited = document.DeepClone().AsObject(); edited["newUserData"] = true;
                    await host.SaveOriginalContactResultAsync("", edited);
                }
                using var cancel = new CancellationTokenSource(); if (mode == "cancel-run") cancel.Cancel();
                try
                {
                    var result = await session.RunAsync(originalHash, cancel.Token);
                    if (mode is "no-wlan" or "changed-book" or "restore" or "forged-hash" or "cancel-run" or "revoke-during-protect")
                        throw new Exception("Invalid native source session completed: " + mode);
                    if (mode == "success")
                    {
                        TestAssert.That(source.Writes == 1 && protections == 1 && result.SourceErrors == 0 && result.Offer is not null,
                            "Native session did not protect/write/readback/stage its source");
                        document["kontakte"] = result.Offer!.Contacts.DeepClone();
                        var saved = await host.SaveOriginalContactResultAsync(result.Offer.Token, document);
                        TestAssert.That(saved["ok"]!.GetValue<bool>() && saved["kontaktOriginalGespeichert"]!.GetValue<string>() == result.Offer.Token,
                            "Actual native session stage did not reach actual SaveAsync commit");
                        var priorReads = source.Reads; var priorDiscovery = source.Discoveries;
                        var repeated = await session.RunAsync(host.Saved()!.Sha256);
                        TestAssert.That(repeated.Offer is null && repeated.SourceErrors == 0 && source.Reads == priorReads &&
                            source.Discoveries == priorDiscovery && source.Writes == 1 && protections == 1, "Clean native session retried provider IO");
                    }
                    else if (mode is "no-grant" or "cancel-dialog" or "empty-selection" or "revoked")
                        TestAssert.That(result.Offer is null && result.Grants == 0 && source.Writes == 0 && source.Reads == reads &&
                            source.Discoveries == discoveries && protections == 0, "Native session IO occurred without actual approval");
                    else TestAssert.That(result.SourceErrors == 1 && result.Offer is null && source.Writes == 0,
                        "Native Wi-Fi/protection hold acquired a successful result: " + mode);
                }
                catch (InvalidOperationException error) when (mode is "no-wlan" or "changed-book" or "restore" or "forged-hash" &&
                    error.Message is "contact_source_wlan_required" or "contact_source_saved_book_changed" or "contact_source_restore_pending")
                {
                    TestAssert.That(source.Writes == 0 && source.Reads == reads && source.Discoveries == discoveries && protections == 0,
                        "Invalid native saved/Wi-Fi state reached provider IO");
                }
                catch (OperationCanceledException) when (mode is "cancel-run" or "revoke-during-protect")
                {
                    TestAssert.That(source.Writes == 0 && (mode != "cancel-run" || source.Discoveries == discoveries), "Cancelled native session wrote/discovered");
                    if (mode == "revoke-during-protect") TestAssert.That(session.GrantCount == 0 && protections == 1, "Native revoke failed to stop its in-flight run");
                }
            }
            finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
        }
    }

    private static async Task NativeFrontendWireAsync()
    {
        // Host uses the existing Node runtime. Windows checks the same common
        // native command/session and actual writer separately; no installed GUI
        // or real modal-consent acceptance is inferred from this controlled UI.
        var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
            ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
        using var source = new Source("wire", "generic-dav", original);
        var remote = await source.OriginalAsync(); var local = original.DeepClone().AsObject();
        ContactFields.SetSource(local, source.Catalog.Uid, remote, remoteBaseline: true);
        var other = await source.ExtraOriginalAsync();
        ContactFields.SetSource(local, source.ExtraCatalog.Uid, other, remoteBaseline: true);
        var document = new JsonObject { ["kontakte"] = new JsonArray(local), ["syncEpoch"] = "native-frontend-wire-epoch",
            ["notizen"] = new JsonArray(new JsonObject { ["id"] = "keep-note", ["titel"] = "Keep", ["text"] = "Other domains unchanged" }) };
        var root = Path.Combine(Path.GetTempPath(), "magnolie-frontend-native-source-wire-" + Guid.NewGuid().ToString("N"));
        Process? process = null;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(55));
        try
        {
            var host = new PersonalActorNativeSaveHost(root, document.ToJsonString()); var protections = 0;
            var session = new ContactSourceNativeSession(host.Snapshot, host.Saved, source.Settings, host.SourceResultCommit,
                () => true, snapshot => { protections++; new AtomicStore().WriteRecoverableJson(Path.Combine(root, "pre-contact.json"), snapshot.Text); }, source.Transport);
            var repository = TestSource.Root("contracts/contact-provider-labels.md");
            var windows = File.Exists(Path.Combine(repository, "MagnolieOrganizer.Windows.csproj")) ? repository : Path.Combine(repository, "magnolie-organizer-windows");
            var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("NODE") ?? "node") {
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
            start.ArgumentList.Add(Path.Combine(windows, "tests", "contact-original-source-updates.js")); start.ArgumentList.Add("--wire");
            process = Process.Start(start) ?? throw new InvalidOperationException("Existing Node runtime required");
            var errors = process.StandardError.ReadToEndAsync();
            async Task Reply(string callback, object value) { await process.StandardInput.WriteLineAsync(System.Text.Json.JsonSerializer.Serialize(new { callback, value })); await process.StandardInput.FlushAsync(); }
            await process.StandardInput.WriteLineAsync(new JsonObject { ["type"] = "init", ["daten"] = document }.ToJsonString()); await process.StandardInput.FlushAsync();
            var completed = false; var saves = 0; var configured = 0; var updates = 0;
            while (await process.StandardOutput.ReadLineAsync(timeout.Token) is { } line)
            {
                var packet = JsonNode.Parse(line)!.AsObject();
                if (packet["type"]!.GetValue<string>() == "complete")
                {
                    TestAssert.That(saves >= 3 && configured == 1 && updates == 1 && source.Writes == 1 && source.ExtraWrites == 1 && protections == 1 &&
                        host.Responses.Last().Value["kontaktOriginalGespeichert"]!.GetValue<string>() == packet["token"]!.GetValue<string>() &&
                        new EncryptionService().Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password) == packet["text"]!.GetValue<string>(),
                        "Actual frontend→native SaveACK→native session/provider→actual encrypted result SaveACK wire incomplete");
                    var proofPath = Environment.GetEnvironmentVariable("MAGNOLIE_CONTACT_SOURCE_WIRE_PROOF");
                    if (!string.IsNullOrEmpty(proofPath)) await File.WriteAllTextAsync(proofPath, new JsonObject {
                        ["sourceCount"] = 2, ["providerWrites"] = source.Writes + source.ExtraWrites,
                        ["nativeProtectionCalls"] = protections, ["actualNativeSaveCommands"] = saves,
                        ["explicitSyntheticNativeDecisions"] = configured, ["nativeSourceRunCommands"] = updates,
                        ["savedPayloadSha256"] = BaumSyncSnapshot.Hash(packet["text"]!.GetValue<string>()),
                        ["frontendSourceSha256"] = BaumSyncSnapshot.Hash(File.ReadAllText(Path.Combine(windows, "app/web/anwendung.js"))),
                        ["actualResultCommitAckVerified"] = true, ["actualEncryptedFileVerified"] = true,
                        ["twoDistinctProviderAccounts"] = false, ["installedNativeDialogAcceptance"] = false,
                        ["nativeWlanDetectionAcceptance"] = false, ["liveProviderOrPrivateInputs"] = false
                    }.ToJsonString());
                    completed = true; break;
                }
                var command = packet["value"]!.AsObject();
                switch (command["cmd"]!.GetValue<string>())
                {
                    case "speichern":
                        saves++; await Reply("gespeichert", await host.SaveBridgeEnvelopeAsync(command)); break;
                    case "kontakt_originalquellen_freigabe":
                    {
                        using var consentEnvelope = BridgeDispatcherContract.Parse(command.ToJsonString());
                        TestAssert.That(host.Snapshot() is not null && JsonNode.Parse(host.Snapshot()!.Text)!["kontakte"]![0]!["notiz"]!.GetValue<string>() == "Canonical note" &&
                            session.GrantCount == 0, "Actual frontend requested source consent before its actual edited SaveACK");
                        configured++;
                        var changed = await session.ConfigureAsync((catalog, selected, token) => Task.FromResult<IReadOnlyList<string>?>(catalog.Select(item => item.Uid).ToArray()), timeout.Token);
                        await Reply("originalKontaktFreigabe", new { requestId = command["requestId"]!.GetValue<string>(), ok = true, changed, freigaben = session.GrantCount }); break;
                    }
                    case "kontakt_originalquellen_update":
                    {
                        using var updateEnvelope = BridgeDispatcherContract.Parse(command.ToJsonString());
                        updates++;
                        var result = await session.RunAsync(command["standSha256"]!.GetValue<string>(), timeout.Token);
                        TestAssert.That(result.SourceErrors == 0 && result.Offer is not null, "Actual frontend's native source run was held unexpectedly");
                        await Reply("originalKontaktErgebnis", new { requestId = command["requestId"]!.GetValue<string>(), ok = true,
                            token = result.Offer!.Token, originalSha256 = result.Offer.OriginalSha256, kontakte = result.Offer.Contacts,
                            fehlerQuellen = result.SourceErrors, freigaben = result.Grants }); break;
                    }
                    case "kontakt_originalquellen_widerrufen": session.Revoke(); break;
                }
            }
            await process.WaitForExitAsync(timeout.Token);
            TestAssert.That(completed && process.ExitCode == 0, "Controlled actual frontend/native source wire failed: " + await errors);
        }
        finally
        {
            if (process is not null) { if (!process.HasExited) { process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); } process.Dispose(); }
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static async Task SavedDavOrchestrationAsync()
    {
        foreach (var mode in new[] { "success", "no-grants", "unbound", "readonly", "unknown", "offline", "revoked",
            "wrong-account", "restore", "not-saved", "book-during-discovery", "book-during-read", "snapshot-failed",
            "revoke-during-snapshot", "cancel-during-snapshot", "bad-readback", "clean", "duplicate-approvals", "native-writer" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var first = new Source("first", "generic-dav", original);
            using var second = new Source("second", "nextcloud", original);
            var a = await first.OriginalAsync(); var b = await second.OriginalAsync();
            var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, first.Catalog.Uid, a, remoteBaseline: true);
            ContactFields.SetSource(local, second.Catalog.Uid, b, remoteBaseline: true);
            var baseline = ContactFields.Source(local, first.Catalog.Uid)!.ToJsonString();
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            if (mode == "clean") { local["notiz"] = "Original"; local["geaendert"] = 1000L; }
            if (mode == "unbound") local["syncQuellen"]!.AsObject().Remove(first.Catalog.Uid);
            var document = new JsonObject { ["kontakte"] = new JsonArray(local,
                new JsonObject { ["id"] = "unbound", ["uid"] = "unbound", ["sync"] = true, ["notiz"] = "Never export" }),
                ["syncEpoch"] = "not-an-approval", ["notizen"] = new JsonArray(new JsonObject { ["text"] = "Unchanged synthetic note" }) };
            if (mode == "restore") document["syncNachRestore"] = new JsonObject { ["additiv"] = true };
            var root = Path.Combine(Path.GetTempPath(), "magnolie-saved-dav-run-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var path = Path.Combine(root, "synthetic.json"); var snapshotPath = Path.Combine(root, "pre-contact.json");
                var store = new AtomicStore(); var owner = new NativeBookOwnerScope(); owner.SetReady(true);
                var text = document.ToJsonString(); store.WriteRecoverableJson(path, text);
                owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(text));
                var nativeHost = mode == "native-writer" ? new PersonalActorNativeSaveHost(Path.Combine(root, "encrypted"), text) : null;
                NativeBookSaveState? Current() => nativeHost is null ? owner.SaveState(path, true) : nativeHost.Saved();
                NativeActorBookSnapshot? Capture() => nativeHost is null ? NativeActorBookSnapshot.Capture(Current, () => text) : nativeHost.Snapshot();
                var firstScope = new ContactSourceApprovalScope(Current, first.Settings.ReadSnapshot);
                var secondScope = new ContactSourceApprovalScope(Current, second.Settings.ReadSnapshot);
                await firstScope.ConfigureAsync([first.Catalog], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([first.Catalog.Uid]));
                await secondScope.ConfigureAsync([second.Catalog], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([second.Catalog.Uid]));
                var approvals = firstScope.Capture().Concat(secondScope.Capture()).ToArray();
                if (mode == "no-grants") approvals = [];
                if (mode == "duplicate-approvals") approvals = [approvals[0], approvals[0], approvals[1]];
                if (mode == "readonly") first.Permission = false;
                if (mode == "unknown") first.Permission = null;
                if (mode == "offline") first.FailDiscovery = true;
                if (mode == "revoked") firstScope.Revoke();
                if (mode == "not-saved") owner.InvalidateSaved();
                if (mode == "book-during-discovery") first.BeforeDiscovery = owner.InvalidateSaved;
                if (mode == "book-during-read") first.BeforeContentRead = owner.InvalidateSaved;
                if (mode == "bad-readback") first.BadReadback = true;
                first.RequireSaved = second.RequireSaved = first.Saved = second.Saved = true;
                var reads = first.Reads + second.Reads; var discoveries = first.Discoveries + second.Discoveries;
                using var cancel = new CancellationTokenSource(); var protections = 0;
                async Task Protect(NativeActorBookSnapshot snapshot, CancellationToken token)
                {
                    token.ThrowIfCancellationRequested(); protections++;
                    await Task.Yield();
                    if (mode == "snapshot-failed" && protections == 1) throw new IOException("controlled snapshot failure");
                    store.WriteRecoverableJson(snapshotPath, snapshot.Text);
                    TestAssert.That(store.Read(snapshotPath) == text && snapshot.SavedBook == Current(), "Protection lost native original book");
                    if (mode == "revoke-during-snapshot" && protections == 1) firstScope.Revoke();
                    if (mode == "cancel-during-snapshot") cancel.Cancel();
                }
                NextcloudMailboxSettingsStore Account(NativeDavContactUpdateApproval approval) =>
                    approval.Source == first.Catalog.Uid && mode != "wrong-account" ? first.Settings : second.Settings;
                HttpClient Transport(NativeDavContactUpdateApproval approval) =>
                    approval.Source == first.Catalog.Uid ? first.Transport : second.Transport;
                try
                {
                    var result = await ContactSourceSavedDavRun.RunAsync(Capture, Current, approvals, Account, Protect,
                        cancel.Token, transportForApproval: Transport);
                    TestAssert.That(mode is not ("restore" or "not-saved" or "book-during-discovery" or "book-during-read" or "cancel-during-snapshot"),
                        "Invalid native book/lifetime completed orchestration: " + mode);
                    var firstWrites = mode is "success" or "native-writer" or "bad-readback" ? 1 : 0;
                    TestAssert.That(first.Writes == firstWrites && second.Writes == (mode is "no-grants" or "clean" ? 0 : 1),
                        "Saved DAV orchestration lost source failure isolation: " + mode);
                    TestAssert.That(result.OriginalBook == Current() && result.Contacts.Count == 2 &&
                        ContactFields.Text(result.Contacts[0]!.AsObject(), "uid") == "canonical-person" &&
                        JsonNode.DeepEquals(result.Contacts[1], document["kontakte"]![1]), "Original identity/unbound contact changed");
                    if (mode is "no-grants" or "unbound" or "clean")
                    {
                        TestAssert.That(!result.Sources.ContainsKey(first.Catalog.Uid), "Clean/unbound/unapproved source acquired a result");
                        if (mode is "no-grants" or "clean") TestAssert.That(first.Reads + second.Reads == reads &&
                            first.Discoveries + second.Discoveries == discoveries && protections == 0, "No grants caused provider IO/protection");
                    }
                    else if (mode is not ("success" or "native-writer")) TestAssert.That(result.Sources[first.Catalog.Uid].Errors > 0 &&
                        ContactFields.Source(result.Contacts[0]!.AsObject(), first.Catalog.Uid)!.ToJsonString() == baseline,
                        "Held original source acquired a baseline/success: " + mode);
                    TestAssert.That(store.Read(path) == text, "Returning provider results silently persisted baselines");
                    if (mode is "success" or "native-writer")
                    {
                        TestAssert.That(result.Sources.Values.All(count => count.Errors == 0) && protections == 2 &&
                            store.Read(snapshotPath) == text, "Saved DAV run skipped actual synthetic protection/readback");
                        if (nativeHost is not null)
                        {
                            var offer = nativeHost.StageOriginalContactResult(result);
                            document["kontakte"] = offer.Contacts.DeepClone();
                            var response = await nativeHost.SaveOriginalContactResultAsync(offer.Token, document);
                            text = document.ToJsonString();
                            TestAssert.That(response["ok"]!.GetValue<bool>() && response["kontaktOriginalGespeichert"]!.GetValue<string>() == offer.Token &&
                                new EncryptionService().Unlock(File.ReadAllText(nativeHost.DataPath), PersonalActorNativeSaveHost.Password) == text,
                                "Provider readback did not reach actual encrypted SaveAsync/result commit acknowledgment");
                        }
                        else
                        {
                            var commit = new ContactSourceSavedCommit(Current);
                            var offer = commit.Stage(Capture()!, result);
                            document["kontakte"] = offer.Contacts.DeepClone();
                            var proposed = document.ToJsonString();
                            var invocation = commit.Prepare(offer.Token, document);
                            invocation.Write(proposed, payload =>
                            {
                                owner.InvalidateSaved(); store.WriteRecoverableJson(path, payload); text = payload;
                                owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(payload));
                            });
                            TestAssert.That(invocation.Completed && invocation.Token == offer.Token, "Native result-save invocation lacked a durable witness");
                        }
                        var beforeReads = first.Reads + second.Reads; var beforeDiscovery = first.Discoveries + second.Discoveries;
                        var repeated = await ContactSourceSavedDavRun.RunAsync(Capture, Current,
                            firstScope.Capture().Concat(secondScope.Capture()).ToArray(), Account, Protect,
                            cancel.Token, transportForApproval: Transport);
                        TestAssert.That(repeated.Sources.Count == 0 && first.Writes + second.Writes == 2 &&
                            first.Reads + second.Reads == beforeReads && first.Discoveries + second.Discoveries == beforeDiscovery && protections == 2,
                            "Durably saved clean result performed redundant provider IO");
                    }
                }
                catch (InvalidOperationException error) when (mode is "restore" or "not-saved" or "book-during-discovery" or "book-during-read" &&
                    error.Message is "contact_source_restore_pending" or "contact_source_book_not_saved" or "contact_source_saved_book_changed")
                {
                    TestAssert.That(first.Writes + second.Writes == 0 && protections == 0, "Invalid native context performed writes/protection");
                    if (mode is "restore" or "not-saved") TestAssert.That(first.Reads + second.Reads == reads &&
                        first.Discoveries + second.Discoveries == discoveries, "Invalid saved/restore state reached discovery");
                }
                catch (OperationCanceledException) when (mode == "cancel-during-snapshot")
                { TestAssert.That(first.Writes + second.Writes == 0 && protections == 1, "Cancelled protection allowed writes/another source"); }
                catch (InvalidDataException error) when (mode == "duplicate-approvals" && error.Message == "contact_source_admission_ambiguous")
                {
                    TestAssert.That(first.Writes + second.Writes == 0 && first.Reads + second.Reads == reads &&
                        first.Discoveries + second.Discoveries == discoveries && protections == 0, "Ambiguous approval reached provider IO");
                }
            }
            finally { Directory.Delete(root, recursive: true); }
        }
    }

    private static async Task SavedResultCommitAsync()
    {
        using (BridgeDispatcherContract.Parse("{\"cmd\":\"speichern\",\"id\":1,\"text\":\"{}\"}")) { }
        using (BridgeDispatcherContract.Parse("{\"cmd\":\"speichern\",\"id\":1,\"text\":\"{}\",\"kontaktOriginalLauf\":\"opaque-native-token\"}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"speichern\",\"id\":1,\"text\":\"{}\",\"kontaktOriginalLauf\":{\"saved\":true}}"),
            "A document-claimed saved flag was accepted as a native result token");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"speichern\",\"id\":1,\"text\":\"{}\",\"sourceAdmissions\":[]}"),
            "Save envelope accepted renderer source admissions");
        foreach (var mode in new[] { "success", "forged-token", "mixed-content", "changed-before-prepare", "changed-before-write",
            "replaced-offer", "invalid-identity", "failed-primary-write", "throw-after-confirm", "unconfirmed-write",
            "wrong-hash", "extra-save", "other-book", "invalidated" })
        {
            var root = Path.Combine(Path.GetTempPath(), "magnolie-source-commit-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var path = Path.Combine(root, "synthetic.json"); var store = new AtomicStore();
                var document = new JsonObject { ["kontakte"] = new JsonArray(new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["notiz"] = "Original" }),
                    ["notizen"] = new JsonArray(new JsonObject { ["text"] = "Never alter other domains" }) };
                var text = document.ToJsonString(); var owner = new NativeBookOwnerScope(); owner.SetReady(true);
                store.WriteRecoverableJson(path, text); owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(text));
                NativeBookSaveState? Current() => owner.SaveState(path, true);
                var snapshot = NativeActorBookSnapshot.Capture(Current, () => text)!;
                var contacts = document["kontakte"]!.DeepClone().AsArray(); contacts[0]!["notiz"] = "Confirmed source result";
                if (mode == "invalid-identity") contacts[0]!["uid"] = "different-person";
                var result = new SavedContactSourceUpdateResult(snapshot.SavedBook, contacts, new Dictionary<string, ContactSyncCounts>());
                var commit = new ContactSourceSavedCommit(Current); var writes = 0;
                ContactSourceSavedCommit.SaveInvocation? invocation = null;
                try
                {
                    var offer = commit.Stage(snapshot, result);
                    if (mode == "invalid-identity") throw new Exception("Commit staged changed canonical identity");
                    document["kontakte"] = offer.Contacts.DeepClone();
                    if (mode == "forged-token") offer = offer with { Token = new string('0', 64) };
                    if (mode == "mixed-content") document["notizen"]![0]!["text"] = "Unexpected other-domain mutation";
                    if (mode == "changed-before-prepare") owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(text));
                    if (mode == "replaced-offer") commit.Stage(snapshot, result);
                    if (mode == "invalidated") commit.Invalidate();
                    invocation = commit.Prepare(offer.Token, document);
                    if (mode == "changed-before-write") owner.InvalidateSaved();
                    var proposed = document.ToJsonString();
                    invocation.Write(proposed, payload =>
                    {
                        writes++; owner.InvalidateSaved();
                        if (mode == "failed-primary-write")
                        {
                            new AtomicStore(stage => { if (stage == AtomicStore.WriteStage.PrimaryReplaced) throw new IOException("controlled failed result write"); })
                                .WriteRecoverableJson(path, payload);
                            return;
                        }
                        store.WriteRecoverableJson(path, payload); text = payload;
                        if (mode == "unconfirmed-write") return;
                        if (mode == "other-book") owner.Invalidate();
                        owner.RecordSaved(path, true, mode == "wrong-hash" ? new string('0', 64) : BaumSyncSnapshot.Hash(payload));
                        if (mode == "extra-save") owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(payload));
                        if (mode == "throw-after-confirm") throw new IOException("controlled unknown terminal result");
                    });
                    TestAssert.That(mode == "success" && writes == 1 && invocation.Completed &&
                        store.Read(path) == proposed && Current()!.Sequence == snapshot.SavedBook.Sequence + 1,
                        "Unconfirmed/stale/mixed result acquired durable acknowledgment: " + mode);
                    try { invocation.Write(proposed, _ => writes++); throw new Exception("Committed source result was replayed"); }
                    catch (InvalidOperationException) { TestAssert.That(writes == 1, "Replayed result reached native writer"); }
                }
                catch (Exception error) when (mode != "success" && error is InvalidOperationException or InvalidDataException or IOException)
                {
                    var attempted = mode is "failed-primary-write" or "throw-after-confirm" or "unconfirmed-write" or "wrong-hash" or "extra-save" or "other-book";
                    TestAssert.That(writes == (attempted ? 1 : 0) && invocation?.Completed != true, "Invalid result save was acknowledged/wrote prematurely: " + mode);
                    if (invocation is not null)
                    {
                        try { invocation.Write(document.ToJsonString(), _ => writes++); throw new Exception("Failed/stale result was reused"); }
                        catch (InvalidOperationException) { TestAssert.That(writes == (attempted ? 1 : 0), "Failed/stale result retry reached writer"); }
                    }
                }
            }
            finally { Directory.Delete(root, recursive: true); }
        }
        await PersonalActorNativeSaveHost.VerifyOriginalContactResultAsync(new JsonObject {
            ["kontakte"] = new JsonArray(new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["notiz"] = "Original" }),
            ["notizen"] = new JsonArray(new JsonObject { ["text"] = "Other domains remain unchanged" }),
            ["syncEpoch"] = "native-source-result-save-epoch"
        }.ToJsonString());
    }

    private static async Task ApprovalScopeAsync()
    {
        foreach (var mode in new[] { "later-save", "cancel", "empty-selection", "invalid-selection", "duplicate-selection",
            "revoke", "lock", "other-book", "account-change", "inactive", "missing-credential", "revoke-during-dialog",
            "save-during-dialog", "account-during-dialog", "cancel-during-dialog", "reapprove" })
        {
            NativeBookSaveState? book = new("native-synthetic-book", 1, new string('a', 64));
            var account = new NextcloudSettingsSnapshot(new NextcloudMailboxSettings(true, false, "https://first.invalid/nc", "synthetic")
                { AccountType = "generic-dav" }, true, "native-account-revision");
            var href = new Uri("https://first.invalid/nc/books/original/");
            var source = new NextcloudDavSource(NextcloudDavClient.StableSourceId("addressbook", href, "generic-dav"),
                "Synthetic source", "addressbook", href, false, false) { CanUpdate = true };
            var scope = new ContactSourceApprovalScope(() => book, () => account);
            TestAssert.That(scope.Capture().Count == 0, "New native approval scope was not default OFF");
            await scope.ConfigureAsync([source, source with { ReadOnly = true }, source with { CanUpdate = null },
                source with { Uid = "thunderbird-addressbook:unrelated" }], (choices, selected, _) =>
            {
                TestAssert.That(choices.Count == 1 && selected.Count == 0, "Discovery implicitly selected a source");
                return Task.FromResult<IReadOnlyList<string>?>([source.Uid]);
            });
            var captured = scope.Capture().Single();
            await captured.RequireApproved(default);
            if (mode is "cancel" or "empty-selection" or "invalid-selection" or "duplicate-selection" || mode.EndsWith("during-dialog", StringComparison.Ordinal))
            {
                using var cancel = new CancellationTokenSource();
                try
                {
                    var changed = await scope.ConfigureAsync([source], async (_, selected, token) =>
                    {
                        TestAssert.That(selected.SequenceEqual(new[] { source.Uid }), "Native dialog lost explicit current selection");
                        await Task.Yield();
                        if (mode == "revoke-during-dialog") scope.Revoke();
                        if (mode == "save-during-dialog") book = book! with { Sequence = 2 };
                        if (mode == "account-during-dialog") account = account with { Revision = "changed" };
                        if (mode == "cancel-during-dialog") cancel.Cancel();
                        return mode switch {
                            "cancel" => null,
                            "empty-selection" => Array.Empty<string>(),
                            "invalid-selection" => new[] { "imported-not-approved-source" },
                            "duplicate-selection" => new[] { source.Uid, source.Uid },
                            _ => new[] { source.Uid }
                        };
                    }, cancel.Token);
                    TestAssert.That(mode is "cancel" or "empty-selection" && changed == (mode == "empty-selection"), "Invalid/stale decision granted a source: " + mode);
                }
                catch (InvalidDataException) when (mode is "invalid-selection" or "duplicate-selection") { }
                catch (InvalidOperationException error) when (mode is "revoke-during-dialog" or "save-during-dialog" or "account-during-dialog" &&
                    error.Message == "contact_source_approval_context_changed") { }
                catch (OperationCanceledException) when (mode == "cancel-during-dialog") { }
            }
            if (mode == "later-save") book = book! with { Sequence = 2, Sha256 = new string('b', 64) };
            if (mode == "revoke") scope.Revoke();
            if (mode == "lock") book = null;
            if (mode == "other-book") book = book! with { BookSource = "different-native-book" };
            if (mode == "account-change") account = account with { Revision = "changed" };
            if (mode == "inactive") account = account with { Settings = account.Settings! with { DavActive = false } };
            if (mode == "missing-credential") account = account with { CredentialPresent = false };
            if (mode == "reapprove")
            {
                scope.Revoke();
                await scope.ConfigureAsync([source], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([source.Uid]));
                await scope.Capture().Single().RequireApproved(default);
            }
            var retained = mode is "later-save" or "cancel" or "invalid-selection" or "duplicate-selection" or "save-during-dialog" or "cancel-during-dialog";
            TestAssert.That(scope.Capture().Count == (retained || mode == "reapprove" ? 1 : 0), "Native approval context/decision not fenced: " + mode);
            try
            {
                await captured.RequireApproved(default);
                TestAssert.That(retained, "Previously captured native approval survived revocation: " + mode);
            }
            catch (UnauthorizedAccessException) when (!retained) { }
        }
    }

    private static async Task DavFactoryAsync()
    {
        foreach (var mode in new[] { "success", "no-grant", "wrong-account", "wrong-href", "thunderbird",
            "readonly", "unknown", "revoked-during-read", "account-changed", "snapshot-failed",
            "revoked-during-snapshot", "privilege-during-snapshot", "account-during-snapshot", "book-during-snapshot", "cancelled", "cancel-during-snapshot" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var first = new Source("first", "generic-dav", original);
            using var second = new Source("second", "nextcloud", original);
            var a = await first.OriginalAsync(); var b = await second.OriginalAsync();
            var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, first.Catalog.Uid, a, remoteBaseline: true);
            ContactFields.SetSource(local, second.Catalog.Uid, b, remoteBaseline: true);
            var baseline = ContactFields.Source(local, first.Catalog.Uid)!.ToJsonString();
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var contacts = new JsonArray(local);
            var approved = mode != "no-grant"; var current = true; var snapshots = 0;
            var revision = first.Settings.ReadSnapshot().Revision;
            var consentBook = new NativeBookSaveState("native-factory-consent-book", 1, new string('a', 64));
            var scope = new ContactSourceApprovalScope(() => current ? consentBook : null, first.Settings.ReadSnapshot);
            await scope.ConfigureAsync([first.Catalog], (_, _, _) =>
                Task.FromResult<IReadOnlyList<string>?>(approved ? new[] { first.Catalog.Uid } : Array.Empty<string>()));
            var approval = new NativeDavContactUpdateApproval(first.Catalog.Uid, first.Catalog.Href, revision,
                _ => approved ? Task.CompletedTask : Task.FromException(new UnauthorizedAccessException("explicit approval withdrawn")));
            if (approved) approval = scope.Capture().Single();
            if (mode == "wrong-account") approval = approval with { AccountRevision = "unrelated-revision" };
            if (mode == "wrong-href") approval = approval with { Collection = new Uri("https://first.invalid/nc/books/other/") };
            if (mode == "thunderbird") approval = approval with { Source = "thunderbird-addressbook:unrelated" };
            if (mode == "readonly") first.Permission = false;
            if (mode == "unknown") first.Permission = null;
            var reads = first.Reads; var discoveries = first.Discoveries;
            using var cancel = new CancellationTokenSource();
            if (mode == "cancelled") cancel.Cancel();
            void Current() { if (!current) throw new InvalidOperationException("factory book changed"); }
            async Task Protect(CancellationToken token)
            {
                token.ThrowIfCancellationRequested(); snapshots++;
                await Task.Yield();
                if (mode == "snapshot-failed") throw new IOException("controlled snapshot failure");
                if (mode == "revoked-during-snapshot") { approved = false; scope.Revoke(); }
                if (mode == "privilege-during-snapshot") first.Permission = false;
                if (mode == "account-during-snapshot") first.Settings.SaveConfiguration(first.Settings.Load()!, "changed-during-snapshot", false);
                if (mode == "book-during-snapshot") current = false;
                if (mode == "cancel-during-snapshot") cancel.Cancel();
            }
            ContactSourceDavFactory? factory = null;
            try
            {
                factory = await first.OpenFactoryAsync(approval, Current, Protect, cancel.Token);
                TestAssert.That(mode is not ("no-grant" or "wrong-account" or "wrong-href" or "thunderbird" or "readonly" or "unknown" or "cancelled"),
                    "Factory admitted an unapproved/misrouted/non-writable source: " + mode);
                if (mode == "revoked-during-read") first.BeforeContentRead = () => { approved = false; scope.Revoke(); };
                if (mode == "account-changed") first.Settings.SaveConfiguration(first.Settings.Load()!, "changed-synthetic-secret", false);
                var result = await ContactSourceUpdateRun.RunAsync(contacts, [factory.Admission, second.Admit()], () => Task.CompletedTask, Current);
                TestAssert.That(first.Writes == (mode == "success" ? 1 : 0) && second.Writes == 1,
                    "Factory failed to isolate source authorization/snapshot failure: " + mode);
                if (mode == "success")
                {
                    TestAssert.That(snapshots == 1 && result.Sources.Values.All(count => count.Errors == 0), "Factory skipped protection/readback");
                    await ContactSourceUpdateRun.RunAsync(result.Contacts, [factory.Admission, second.Admit()], () => Task.CompletedTask, Current);
                    TestAssert.That(first.Writes == 1 && second.Writes == 1 && snapshots == 1, "Factory run was not idempotent");
                }
                else TestAssert.That(ContactFields.Source(result.Contacts[0]!.AsObject(), first.Catalog.Uid)!.ToJsonString() == baseline,
                    "Held factory source advanced its baseline: " + mode);
            }
            catch (UnauthorizedAccessException) when (mode is "no-grant" or "wrong-account" or "wrong-href" or "thunderbird" or "readonly" or "unknown")
            {
                TestAssert.That(first.Writes == 0 && first.Reads == reads, "Rejected factory source performed content IO");
                if (mode is not ("readonly" or "unknown")) TestAssert.That(first.Discoveries == discoveries, "Unapproved source performed discovery");
                await ContactSourceUpdateRun.RunAsync(contacts, [second.Admit()], () => Task.CompletedTask, Current);
                TestAssert.That(second.Writes == 1, "Rejected factory source blocked an independent source");
            }
            catch (InvalidOperationException error) when (mode == "book-during-snapshot" && error.Message == "factory book changed")
            { TestAssert.That(first.Writes + second.Writes == 0 && snapshots == 1, "Book invalidation failed to stop the entire run"); }
            catch (OperationCanceledException) when (mode is "cancelled" or "cancel-during-snapshot")
            {
                TestAssert.That(first.Writes + second.Writes == 0, "Cancelled factory performed writes");
                if (mode == "cancelled") TestAssert.That(first.Discoveries == discoveries, "Cancelled factory performed discovery");
            }
            finally { factory?.Dispose(); }
        }
    }

    private static async Task SavedBookBoundaryAsync()
    {
        foreach (var mode in new[] { "success", "not-saved", "locked", "hash-mismatch", "changed-before-io", "changed-during-read", "restore", "imported-grant", "failed-save" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var first = new Source("first", "generic-dav", original);
            using var second = new Source("second", "nextcloud", original);
            var a = await first.OriginalAsync(); var b = await second.OriginalAsync();
            var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, first.Catalog.Uid, a, remoteBaseline: true);
            ContactFields.SetSource(local, second.Catalog.Uid, b, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var document = new JsonObject { ["kontakte"] = new JsonArray(local), ["syncEpoch"] = "serialized-epoch-is-not-native-authority" };
            if (mode == "restore") document["syncNachRestore"] = new JsonObject { ["additiv"] = true };
            if (mode == "imported-grant") document["einstellungen"] = new JsonObject { ["sync"] = new JsonObject {
                ["kontaktOriginalQuellen"] = new JsonArray(first.Catalog.Uid, second.Catalog.Uid) } };
            var directory = Path.Combine(Path.GetTempPath(), "magnolie-contact-saved-book-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                var path = Path.Combine(directory, "synthetic.json"); var store = new AtomicStore();
                var owner = new NativeBookOwnerScope(); owner.SetReady(true);
                var text = document.ToJsonString();
                store.WriteRecoverableJson(path, text);
                if (mode != "not-saved") owner.RecordSaved(path, true, BaumSyncSnapshot.Hash(text));
                first.RequireSaved = second.RequireSaved = true; first.Saved = second.Saved = mode != "not-saved";
                if (mode == "locked") owner.SetReady(false);
                if (mode == "hash-mismatch") text = document.DeepClone().ToJsonString() + " ";
                if (mode == "failed-save")
                {
                    owner.InvalidateSaved();
                    try
                    {
                        new AtomicStore(stage => { if (stage == AtomicStore.WriteStage.PrimaryReplaced) throw new IOException("Controlled save failure after primary replacement"); })
                            .WriteRecoverableJson(path, text + " ");
                        throw new Exception("Controlled failed save did not fail");
                    }
                    catch (IOException) { }
                }
                NativeBookSaveState? Current() => owner.SaveState(path, true);
                NativeActorBookSnapshot? Capture()
                {
                    var snapshot = NativeActorBookSnapshot.Capture(Current, () => text);
                    if (mode == "changed-before-io") owner.Invalidate();
                    return snapshot;
                }
                if (mode == "changed-during-read") first.BeforeContentRead = owner.InvalidateSaved;
                var aReads = first.Reads; var bReads = second.Reads;
                try
                {
                    var result = await ContactSourceUpdateRun.RunSavedAsync(Capture, Current,
                        mode == "imported-grant" ? [] : [first.Admit(), second.Admit()]);
                    TestAssert.That(mode is "success" or "imported-grant", "Unsaved/changed/restored native book reached source updates: " + mode);
                    if (mode == "success") TestAssert.That(first.Writes == 1 && second.Writes == 1 && result.OriginalBook == Current() &&
                        result.Sources.Values.All(count => count.Errors == 0), "Native saved-book boundary lost two-source update/readback");
                    else TestAssert.That(first.Writes + second.Writes == 0 && first.Reads == aReads && second.Reads == bReads && result.Sources.Count == 0,
                        "Serialized/imported source list was treated as native admission");
                }
                catch (InvalidOperationException error) when (mode is not ("success" or "imported-grant") &&
                    error.Message is "contact_source_book_not_saved" or "contact_source_saved_book_changed" or "contact_source_restore_pending")
                {
                    TestAssert.That(first.Writes + second.Writes == 0 && second.Reads == bReads &&
                        first.Reads == aReads + (mode == "changed-during-read" ? 1 : 0), "Invalid native saved witness performed provider writes/extra reads");
                }
            }
            finally { Directory.Delete(directory, recursive: true); }
        }
    }
}
