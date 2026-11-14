using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security;

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
        internal readonly string WireUid;
        internal NextcloudDavSource Catalog = null!;
        internal string Wire, ETag = "\"v1\"";
        internal bool? Permission = true;
        internal bool FailWrite, BadReadback, RequireSaved, Saved;
        internal string ReadbackUidMode = "";
        internal int Writes, Reads, Discoveries;
        internal Action? BeforeContentRead;
        private readonly string origin;
        internal Source(string name, string accountType, JsonObject data)
        {
            Directory.CreateDirectory(root); WireUid = "provider-original-" + name; origin = "https://" + name + ".invalid";
            var card = data.DeepClone().AsObject(); card["uid"] = WireUid;
            using var input = JsonDocument.Parse(new JsonArray(card).ToJsonString());
            Wire = ExchangeCodec.WriteVCard(input.RootElement).Text;
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
                if (!request.Headers.TryGetValues("Depth", out var depths) || depths.Single() != "1")
                    return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/</d:href><d:propstat><d:prop><c:addressbook-home-set><d:href>/nc/books/</d:href></c:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                var privilege = Permission is null ? "" : "<d:current-user-privilege-set><d:privilege><d:" + (Permission == true ? "write-content" : "read") + "/></d:privilege></d:current-user-privilege-set>";
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/original/</d:href><d:propstat><d:prop><d:displayname>Original</d:displayname><d:resourcetype><c:addressbook/></d:resourcetype>" + privilege + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
            }
            TestAssert.That(!RequireSaved || Saved, "Provider IO preceded the original durable SaveACK");
            if (request.Method.Method == "REPORT")
            {
                BeforeContentRead?.Invoke();
                Reads++;
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/original/person.vcf</d:href><d:propstat><d:prop><d:getetag>" + SecurityElement.Escape(ETag) + "</d:getetag><c:address-data>" + SecurityElement.Escape(Wire) + "</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
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
