using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

// Core only: private synthetic files, native saved-book/scope fixtures and an
// explicit authenticated test protector. Windows additionally uses real DPAPI
// for a dedicated synthetic native key/account case. No application/IO grant.
internal static class ContactSourceApprovalStoreTests
{
    private sealed class Protector : ISecretProtector
    {
        private readonly byte[] key = RandomNumberGenerator.GetBytes(32);
        internal bool Unavailable, NoProtection;
        internal Action? OnRead;
        internal readonly List<byte[]> Buffers = [];
        public byte[] Protect(byte[] plain)
        {
            Buffers.Add(plain);
            if (NoProtection) return plain.ToArray();
            var output = new byte[12 + plain.Length + 16]; RandomNumberGenerator.Fill(output.AsSpan(0, 12));
            using var aes = new AesGcm(key, 16);
            aes.Encrypt(output.AsSpan(0, 12), plain, output.AsSpan(12, plain.Length), output.AsSpan(12 + plain.Length, 16));
            return output;
        }
        public byte[] Unprotect(byte[] cipher)
        {
            Buffers.Add(cipher);
            if (Unavailable) throw new CryptographicException("Controlled credential/key unavailability");
            var plain = new byte[cipher.Length - 28];
            using var aes = new AesGcm(key, 16);
            aes.Decrypt(cipher.AsSpan(0, 12), cipher.AsSpan(12, plain.Length), cipher.AsSpan(12 + plain.Length, 16), plain);
            Buffers.Add(plain); OnRead?.Invoke(); return plain;
        }
        internal void RequireCleared() => TestAssert.That(Buffers.All(buffer => buffer.All(value => value == 0)), "Native consent retained owned key/credential buffers");
        internal void ClearFixtureKey() => CryptographicOperations.ZeroMemory(key);
    }

    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "magnolie-contact-approval-" + Guid.NewGuid().ToString("N"));
        internal readonly Protector Credentials = new(), Keys = new();
        internal NextcloudMailboxSettingsStore Account;
        internal readonly ContactSourcePrivateFiles Files;
        internal NativeBookOwnerScope Owner = new();
        internal string Text = "{\"version\":6,\"kontakte\":[],\"fraction\":1.25,\"sourceAdmissions\":[\"document-only\"],\"saved\":true}";
        internal string Binding = "synthetic-private-native-book";
        internal bool BlockBook;
        internal int Captures, FailWrite, Writes;
        internal Action<int>? OnCapture;
        internal readonly ContactSourceApprovalScope Scope;
        internal readonly ContactSourceApprovalStore Store;
        internal readonly NextcloudDavSource Source;
        internal readonly bool ActualDpapi;
        internal Func<ContactSourcePrimaryBook?>? PrimaryCapture;
        internal Fixture(bool actualDpapi = false)
        {
            ActualDpapi = actualDpapi;
            var settings = Path.Combine(Root, "account.json"); var credential = Path.Combine(Root, "credential.dat");
            Account = actualDpapi ? new(settings, credential) : new(settings, credential, Credentials);
            Account.Save(new(true, false, "https://source.invalid/nc", "synthetic") { AccountType = "generic-dav" });
            Account.SetApplicationPassword("synthetic-only-core-consent-password");
            Owner.SetReady(true); Save(Text);
            Scope = new(Current, Account.ReadSnapshot);
            var href = new Uri("https://source.invalid/nc/books/original/");
            Source = new(NextcloudDavClient.StableSourceId("addressbook", href, "generic-dav"), "Synthetic source", "addressbook", href, CanUpdate: true);
            Files = new ContactSourcePrivateFiles(Path.Combine(Root, "consent"), new AtomicStore(stage =>
            {
                if (stage == AtomicStore.WriteStage.TemporaryFlushed && FailWrite != 0 && ++Writes == FailWrite)
                    throw new IOException("Controlled native consent write failure");
            }), controlledUnix: !OperatingSystem.IsWindows());
            Store = NewStore();
        }
        internal NativeBookSaveState? Current() => Owner.SaveState("native-actual-session-binding", true);
        internal NativeActorBookSnapshot? Capture()
        {
            if (BlockBook) throw new InvalidOperationException("Controlled forbidden book observation");
            OnCapture?.Invoke(++Captures);
            return NativeActorBookSnapshot.Capture(Current, () => Text);
        }
        internal void Save(string text)
        { Text = text; Owner.RecordSaved("native-actual-session-binding", true, BaumSyncSnapshot.Hash(text)); }
        internal ContactSourceApprovalStore NewStore() => new(Files, Account, Capture, () => Binding, ActualDpapi ? null : Keys,
            () => PrimaryCapture?.Invoke());
        internal async Task<(NativeActorBookSnapshot Book, NativeDavContactUpdateApproval[] Approvals)> DecisionAsync()
        {
            await Scope.ConfigureAsync([Source], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([Source.Uid]));
            return (Capture()!, Scope.Capture().ToArray());
        }
        internal async Task<StoredContactSourceApproval> ApproveAsync()
        {
            var decision = await DecisionAsync();
            return await Store.ApproveAsync(decision.Book, decision.Approvals) ?? throw new InvalidOperationException("Controlled native approval missing");
        }
        internal void Write(string name, string value)
        { using var session = Files.Open()!; session.Write(name, value, 128 * 1024); }
        internal string State => File.ReadAllText(Path.Combine(Root, "consent", "approval.json"));
        internal void WriteSignedMalformed(JsonObject payload)
        {
            using var session = Files.Open()!;
            var cipher = Convert.FromBase64String(session.Read(".key.dpapi", 16 * 1024)!);
            byte[] key;
            try { key = Keys.Unprotect(cipher); } finally { CryptographicOperations.ZeroMemory(cipher); }
            try
            {
                var prefix = "Magnolie/native-original-contact-consent/windows/v1\0record\0"u8.ToArray();
                var body = NativeBookJson.Canonical(payload); var input = new byte[prefix.Length + body.Length];
                prefix.CopyTo(input, 0); body.CopyTo(input, prefix.Length);
                var signature = Convert.ToHexString(HMACSHA256.HashData(key, input)).ToLowerInvariant();
                session.Write("approval.json", new JsonObject { ["payload"] = payload, ["mac"] = signature }.ToJsonString(), 128 * 1024);
            }
            finally { CryptographicOperations.ZeroMemory(key); }
        }
        public void Dispose()
        {
            try { Credentials.RequireCleared(); Keys.RequireCleared(); }
            finally
            {
                Credentials.ClearFixtureKey(); Keys.ClearFixtureKey();
                if (Directory.Exists(Root)) Directory.Delete(Root, true);
            }
        }
    }

    private static async Task FailsAsync(Func<Task> operation, string reason)
    {
        Exception? failure = null;
        try { await operation(); } catch (Exception error) { failure = error; }
        TestAssert.That(failure is not null && !failure.Message.Contains("synthetic-only-core-consent-password", StringComparison.Ordinal), reason);
    }
    private static Task Require(StoredContactSourceApproval approval) => approval.RequireCurrentAsync(CancellationToken.None);

    internal static async Task RunAsync()
    {
        foreach (var mode in new[] { "default", "empty-scope-no-context", "success", "restart-owner", "same-content-new-save", "changed-content", "changed-binding",
            "changed-user", "changed-server", "changed-provider", "changed-slot", "credential-unavailable-resume", "credential-renewal",
            "revoked-decision", "forged-source", "foreign-collection", "encoded-traversal", "duplicate", "wrong-revision", "unconfirmed-book",
            "forged-native-token", "unminted-record", "retarget-same-origin", "revoked-guard-bypass", "wrapped-native-guard",
            "foreign-native-catalog", "encoded-native-catalog", "canonicalized-unsafe-native-choice", "oversized-native-selection",
            "book-during-approval", "revoke-during-approval", "corrupt-state", "corrupt-key", "pending", "missing-marker", "key-unavailable", "unknown-save-intent", "revoke-clears-save-intent",
            "tampered-sources", "duplicate-json", "signed-malformed-version", "signed-extra-field", "signed-empty-source", "signed-revoked-content",
            "revoke-replay", "reapprove-replay", "empty-revoke", "callbacks-outside-lock", "newer-generation-preserved", "unprotected-key",
            "write-failed-1", "write-failed-2", "write-failed-3", "write-failed-4" })
        {
            using var fixture = new Fixture();
            var store = fixture.Store;
            if (mode == "default")
            {
                fixture.BlockBook = true; fixture.Credentials.Unavailable = true; fixture.Keys.Unavailable = true;
                TestAssert.That(store.LoadCurrent() is null && !Directory.Exists(Path.Combine(fixture.Root, "consent")), "Default durable read minted state or observed a book/account");
            }
            else if (mode == "empty-scope-no-context")
            {
                var empty = new ContactSourceApprovalScope(() => throw new InvalidOperationException("No default book observation"),
                    () => throw new InvalidOperationException("No default account observation"));
                TestAssert.That(empty.Capture().Count == 0, "Default native source scope observed context without any human grant");
            }
            else if (mode is "foreign-native-catalog" or "encoded-native-catalog" or "canonicalized-unsafe-native-choice" or "oversized-native-selection")
            {
                string? originalState = null;
                if (mode == "oversized-native-selection") { await fixture.ApproveAsync(); originalState = fixture.State; }
                Uri[] hrefs = mode == "oversized-native-selection" ? Enumerable.Range(0, 25).Select(index =>
                    new Uri("https://source.invalid/nc/books/" + new string('x', 6000) + index + "/")).ToArray() :
                    [new Uri(mode == "foreign-native-catalog" ? "https://foreign.invalid/book/" : "https://source.invalid/nc/%2e%2e/other/")];
                var catalog = hrefs.Select(href => new NextcloudDavSource(NextcloudDavClient.StableSourceId("addressbook", href, "generic-dav"),
                    "Synthetic native catalog", "addressbook", href, CanUpdate: true)).ToArray();
                await fixture.Scope.ConfigureAsync(catalog, (choices, _, _) => Task.FromResult<IReadOnlyList<string>?>(choices.Select(item => item.Uid).ToArray()));
                var snapshot = fixture.Capture()!;
                var nativeApprovals = fixture.Scope.Capture();
                if (mode == "canonicalized-unsafe-native-choice")
                    nativeApprovals = nativeApprovals.Select(item => item with { Collection = new Uri(item.Collection.AbsoluteUri) }).ToArray();
                await FailsAsync(async () => { await store.ApproveAsync(snapshot, nativeApprovals); }, "Unsafe/oversized native catalog became durable consent");
                if (originalState is not null)
                    TestAssert.That(fixture.State == originalState, "Oversized invalid reconfiguration changed existing signed human intent");
                else TestAssert.That(!Directory.Exists(Path.Combine(fixture.Root, "consent")), "Rejected native catalog created private files");
            }
            else if (mode is "revoked-decision" or "forged-source" or "foreign-collection" or "encoded-traversal" or "duplicate" or "wrong-revision" or "unconfirmed-book" or
                "forged-native-token" or "unminted-record" or "retarget-same-origin" or "revoked-guard-bypass" or "wrapped-native-guard")
            {
                var decision = await fixture.DecisionAsync(); var approvals = decision.Approvals;
                if (mode == "revoked-decision") fixture.Scope.Revoke();
                if (mode == "forged-source") approvals = [approvals[0] with { Source = "document-only" }];
                if (mode is "foreign-collection" or "encoded-traversal")
                {
                    var href = new Uri(mode == "foreign-collection" ? "https://foreign.invalid/book/" : "https://source.invalid/nc/%2e%2e/other/");
                    approvals = [approvals[0] with { Collection = href, Source = NextcloudDavClient.StableSourceId("addressbook", href, "generic-dav") }];
                }
                if (mode == "duplicate") approvals = [approvals[0], approvals[0]];
                if (mode == "wrong-revision") approvals = [approvals[0] with { AccountRevision = "document-only" }];
                if (mode == "unconfirmed-book") fixture.Owner.InvalidateSaved();
                if (mode == "forged-native-token") approvals = [approvals[0] with { NativeConsent = new object() }];
                if (mode == "unminted-record") approvals = [new(approvals[0].Source, approvals[0].Collection, approvals[0].AccountRevision, _ => Task.CompletedTask)];
                if (mode == "retarget-same-origin")
                {
                    var href = new Uri("https://source.invalid/nc/books/not-selected/");
                    approvals = [approvals[0] with { Collection = href, Source = NextcloudDavClient.StableSourceId("addressbook", href, "generic-dav") }];
                }
                if (mode == "revoked-guard-bypass") { fixture.Scope.Revoke(); approvals = [approvals[0] with { RequireApproved = _ => Task.CompletedTask }]; }
                if (mode == "wrapped-native-guard")
                {
                    var original = approvals[0]; var calls = 0;
                    approvals = [original with { RequireApproved = async cancellation => { calls++; await original.RequireApproved(cancellation); } }];
                    var stored = await store.ApproveAsync(decision.Book, approvals);
                    TestAssert.That(stored is not null && calls > 0, "Legitimate native lifetime/permission wrapper lost its minted decision");
                    await Require(stored!);
                    Console.WriteLine("CONTACT SOURCE APPROVAL STORE PASS " + mode);
                    continue;
                }
                await FailsAsync(async () => { await store.ApproveAsync(decision.Book, approvals); }, "Untrusted/stale native decision granted durable authority");
                TestAssert.That(!Directory.Exists(Path.Combine(fixture.Root, "consent")), "Rejected native decision created consent files");
            }
            else if (mode is "book-during-approval" or "revoke-during-approval" or "newer-generation-preserved")
            {
                var decision = await fixture.DecisionAsync(); fixture.Captures = 0;
                StoredContactSourceApproval? newer = null;
                fixture.OnCapture = count =>
                {
                    if (count != 2) return;
                    fixture.OnCapture = null;
                    if (mode == "book-during-approval") fixture.Save("{\"kontakte\":[],\"newer\":true}");
                    if (mode == "revoke-during-approval") fixture.Scope.Revoke();
                    if (mode == "newer-generation-preserved") newer = fixture.ApproveAsync().GetAwaiter().GetResult();
                };
                await FailsAsync(async () => { await store.ApproveAsync(decision.Book, decision.Approvals); }, "Changed native decision context survived approval publication");
                if (mode == "newer-generation-preserved")
                    TestAssert.That(newer is not null && store.LoadCurrent()?.Generation == newer.Generation, "Stale approval failure revoked the newer native decision");
                else TestAssert.That(store.LoadCurrent() is null, "Stale approval remained active");
            }
            else if (mode.StartsWith("write-failed-", StringComparison.Ordinal) || mode == "unprotected-key")
            {
                if (mode == "unprotected-key") fixture.Keys.NoProtection = true;
                else fixture.FailWrite = int.Parse(mode[^1..], System.Globalization.CultureInfo.InvariantCulture);
                await FailsAsync(async () => { await fixture.ApproveAsync(); }, "Unconfirmed/unprotected native approval publication succeeded");
                await FailsAsync(() => { _ = store.LoadCurrent(); return Task.CompletedTask; }, "Pending native publication granted usable permission");
            }
            else
            {
                if (mode == "callbacks-outside-lock")
                {
                    fixture.OnCapture = _ => { using var session = fixture.Files.Open(); };
                    fixture.Credentials.OnRead = () => { using var session = fixture.Files.Open(); };
                }
                var original = await fixture.ApproveAsync();
                await Require(original);
                var savedState = fixture.State;
                TestAssert.That(!savedState.Contains("synthetic-only-core-consent-password", StringComparison.Ordinal) &&
                    !savedState.Contains(fixture.Binding, StringComparison.Ordinal) && !savedState.Contains(original.AccountRevision, StringComparison.Ordinal) &&
                    !savedState.Contains(original.Snapshot.SavedBook.BookSource, StringComparison.Ordinal) && !savedState.Contains("document-only", StringComparison.Ordinal),
                    "Private consent serialized secrets, document claims or ephemeral authority");
                if (mode == "restart-owner")
                { fixture.Owner = new NativeBookOwnerScope(); fixture.Owner.SetReady(true); fixture.Save(fixture.Text); store = fixture.NewStore(); }
                if (mode == "same-content-new-save") fixture.Save(fixture.Text);
                if (mode == "changed-content") fixture.Save("{\"kontakte\":[],\"unknown\":true}");
                if (mode == "changed-binding") fixture.Binding = "different-native-book";
                if (mode is "changed-user" or "changed-server" or "changed-provider")
                {
                    var settings = fixture.Account.Load()!;
                    fixture.Account.Save(mode == "changed-user" ? settings with { User = "other" } : mode == "changed-server" ?
                        settings with { ServerBase = "https://other.invalid/nc" } : settings with { AccountType = "nextcloud" });
                }
                if (mode == "changed-slot")
                {
                    var other = Path.Combine(fixture.Root, "other-credential.dat"); File.Copy(Path.Combine(fixture.Root, "credential.dat"), other);
                    fixture.Account = new(Path.Combine(fixture.Root, "account.json"), other, fixture.Credentials); store = fixture.NewStore();
                }
                if (mode == "credential-renewal") fixture.Account.SetApplicationPassword("renewed-synthetic-core-only");
                if (mode == "credential-unavailable-resume")
                {
                    fixture.Credentials.Unavailable = true;
                    await FailsAsync(() => Require(original), "Unavailable actual credentials retained usable native permission");
                    TestAssert.That(fixture.State == savedState, "Temporary account unavailability erased human consent");
                    fixture.Credentials.Unavailable = false;
                }
                if (mode == "key-unavailable") fixture.Keys.Unavailable = true;
                if (mode == "corrupt-state") fixture.Write("approval.json", "{broken");
                if (mode == "corrupt-key") fixture.Write(".key.dpapi", "not-base64");
                if (mode == "duplicate-json") fixture.Write("approval.json", "{\"payload\":{},\"mac\":\"x\",\"mac\":\"y\"}");
                if (mode == "tampered-sources")
                {
                    var envelope = JsonNode.Parse(savedState)!.AsObject();
                    envelope["payload"]!["sources"]![0]!["href"] = "https://source.invalid/nc/books/other/";
                    fixture.Write("approval.json", envelope.ToJsonString());
                }
                if (mode.StartsWith("signed-", StringComparison.Ordinal))
                {
                    var payload = JsonNode.Parse(savedState)!["payload"]!.DeepClone().AsObject();
                    if (mode == "signed-malformed-version") payload["version"] = true;
                    if (mode == "signed-extra-field") payload["rendererGrant"] = true;
                    if (mode == "signed-empty-source") payload["sources"]![0]!["source"] = "";
                    if (mode == "signed-revoked-content") payload["sources"] = new JsonArray();
                    fixture.WriteSignedMalformed(payload);
                }
                if (mode == "pending") fixture.Write(".transaction", "pending\n");
                if (mode == "missing-marker") { using var session = fixture.Files.Open()!; session.Delete(".transaction"); }
                if (mode is "unknown-save-intent" or "revoke-clears-save-intent")
                {
                    fixture.Write(".save-intent.json", "{}");
                    if (mode == "revoke-clears-save-intent")
                    {
                        store.Revoke();
                        TestAssert.That(!File.Exists(Path.Combine(fixture.Root, "consent", ".save-intent.json")) && store.LoadCurrent() is null,
                            "Explicit native revoke did not clear a pending save intent");
                        Console.WriteLine("CONTACT SOURCE APPROVAL STORE PASS " + mode);
                        continue;
                    }
                }
                if (mode is "revoke-replay" or "reapprove-replay" or "empty-revoke")
                {
                    if (mode == "reapprove-replay") await fixture.ApproveAsync();
                    else if (mode == "empty-revoke")
                    { fixture.BlockBook = true; fixture.Credentials.Unavailable = true; await store.ApproveAsync(original.Snapshot, []); }
                    else store.Revoke();
                    await FailsAsync(() => Require(original), "Old operation witness survived native key rotation");
                    if (mode != "reapprove-replay") TestAssert.That(store.LoadCurrent() is null, "Durable revocation was not empty");
                    fixture.Write("approval.json", savedState);
                }
                if (mode is "corrupt-state" or "corrupt-key" or "pending" or "missing-marker" or "key-unavailable" or "revoke-replay" or "reapprove-replay" or "empty-revoke" or "tampered-sources" or "duplicate-json" or "unknown-save-intent" || mode.StartsWith("signed-", StringComparison.Ordinal))
                    await FailsAsync(() => { _ = store.LoadCurrent(); return Task.CompletedTask; }, "Corrupt/replayed/unknown native consent became usable");
                else if (mode is "changed-content" or "changed-binding" or "changed-user" or "changed-server" or "changed-provider" or "changed-slot")
                    TestAssert.That(store.LoadCurrent() is null && fixture.State == savedState, "Changed native identity/content was adopted or consent erased");
                else
                {
                    var current = store.LoadCurrent();
                    TestAssert.That(current is not null && current.Generation == original.Generation && current.Sources.SequenceEqual(original.Sources), "Valid persisted native decision did not restore");
                    await Require(current!);
                    if (mode is "restart-owner" or "same-content-new-save" or "credential-renewal")
                        await FailsAsync(() => Require(original), "Old operation witness survived new native save/credential context");
                }
            }
            Console.WriteLine("CONTACT SOURCE APPROVAL STORE PASS " + mode);
        }
        await SaveChainAsync();
        await PrimaryChainAsync();
        await ScopeRestoreAsync();
        await ActualWriterAsync();
        if (OperatingSystem.IsWindows())
        {
            using var fixture = new Fixture(actualDpapi: true);
            var before = await fixture.ApproveAsync();
            fixture.Owner = new NativeBookOwnerScope(); fixture.Owner.SetReady(true); fixture.Save(fixture.Text);
            var current = fixture.NewStore().LoadCurrent();
            TestAssert.That(current is not null && current.Generation == before.Generation && current.Sources.SequenceEqual(before.Sources),
                "Actual Windows DPAPI native key/account did not restore the synthetic persisted decision");
            await Require(current!);
            fixture.Write(".key.dpapi", File.ReadAllText(Path.Combine(fixture.Root, "credential.dat")));
            await FailsAsync(() => Require(current!), "Account DPAPI ciphertext was accepted as the dedicated consent key (wrong entropy/domain)");
            fixture.Store.Revoke();
            TestAssert.That(fixture.NewStore().LoadCurrent() is null, "Actual DPAPI native consent revoke did not persist");
            Console.WriteLine("CONTACT SOURCE APPROVAL STORE PASS actual-windows-dpapi-key-account-synthetic-only");
        }
    }

    private static async Task SaveChainAsync()
    {
        const string next = "{\"version\":6,\"kontakte\":[],\"fraction\":1.25,\"ordinaryEdit\":true}";
        foreach (var mode in new[] { "disabled-no-io", "advance", "same-content", "old-outcome", "new-outcome", "unknown-outcome",
            "pending-no-permission", "unconfirmed", "wrong-snapshot", "wrong-store", "wrong-token", "wrong-generation", "wrong-key",
            "wrong-next", "revoked", "reapproved", "credential-locked", "changed-binding", "replayed-intent", "tampered-intent",
            "malformed-intent", "prepare-failure", "advance-failure", "no-rollback", "callbacks-outside-lock", "new-owner-confirm",
            "changed-before-intent", "changed-after-intent", "duplicate-intent", "no-intent-recovery", "fake-save-witness", "unminted-save" })
        {
            using var fixture = new Fixture();
            if (mode == "disabled-no-io")
            {
                var snapshot = fixture.Capture()!; fixture.BlockBook = true; fixture.Credentials.Unavailable = true;
                TestAssert.That(!fixture.Store.HasDesiredConsent() && fixture.Store.PrepareSave(snapshot, next) is null &&
                    fixture.Store.RecoverSaved(snapshot) is null && !Directory.Exists(Path.Combine(fixture.Root, "consent")),
                    "Disabled save chain observed book/account or created consent");
                Console.WriteLine("CONTACT SOURCE APPROVAL SAVE PASS " + mode); continue;
            }
            var original = await fixture.ApproveAsync();
            var old = fixture.Capture()!;
            if (mode == "no-intent-recovery")
            {
                TestAssert.That(fixture.Store.RecoverSaved(old) is null, "No-intent recovery invented a save advancement");
                Console.WriteLine("CONTACT SOURCE APPROVAL SAVE PASS " + mode); continue;
            }
            if (mode == "changed-before-intent") fixture.Save(next);
            if (mode == "changed-after-intent")
            {
                fixture.Captures = 0;
                fixture.OnCapture = count => { if (count == 2) fixture.Save(next); };
            }
            if (mode == "prepare-failure") { fixture.FailWrite = 1; fixture.Writes = 0; }
            if (mode is "changed-before-intent" or "changed-after-intent" or "prepare-failure")
            {
                await FailsAsync(() => { fixture.Store.PrepareSave(old, next); return Task.CompletedTask; }, "Unconfirmed/stale save preparation succeeded");
                fixture.FailWrite = 0;
                if (mode == "changed-after-intent")
                    await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Uncertain prepared intent released permission");
                Console.WriteLine("CONTACT SOURCE APPROVAL SAVE PASS " + mode); continue;
            }
            if (mode == "callbacks-outside-lock") fixture.OnCapture = _ => { using var session = fixture.Files.Open(); };
            if (mode == "credential-locked") fixture.Credentials.Unavailable = true;
            var proposed = mode == "same-content" ? fixture.Text : next;
            var intent = fixture.Store.PrepareSave(old, proposed) ?? throw new InvalidOperationException("Controlled save intent missing");
            TestAssert.That(fixture.Store.HasDesiredConsent(), "Signed human intent disappeared during autosave");
            await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Pending signed save became usable permission");
            var intentText = File.ReadAllText(Path.Combine(fixture.Root, "consent", ".save-intent.json"));
            if (mode == "duplicate-intent")
            {
                await FailsAsync(() => { fixture.Store.PrepareSave(old, proposed); return Task.CompletedTask; }, "Second writer replaced the pending intent");
                TestAssert.That(File.ReadAllText(Path.Combine(fixture.Root, "consent", ".save-intent.json")) == intentText, "Rejected second preparation changed signed intent");
            }
            if (mode == "pending-no-permission") { Console.WriteLine("CONTACT SOURCE APPROVAL SAVE PASS " + mode); continue; }
            if (mode != "unconfirmed" && mode != "old-outcome") fixture.Save(mode == "unknown-outcome" ? "{\"unrelated\":true}" : proposed);
            if (mode == "new-owner-confirm") { fixture.Owner = new NativeBookOwnerScope(); fixture.Owner.SetReady(true); fixture.Save(proposed); }
            var confirmed = fixture.Capture()!;
            if (mode == "wrong-snapshot") confirmed = old;
            if (mode == "wrong-store") intent = intent with { Store = fixture.NewStore() };
            if (mode == "wrong-token") intent = intent with { Token = new string('a', 64) };
            if (mode == "wrong-generation") intent = intent with { Generation = new string('a', 64) };
            if (mode == "wrong-key") intent = intent with { KeyIdentity = new string('a', 64) };
            if (mode == "wrong-next") intent = intent with { NextContent = new string('a', 64) };
            if (mode == "fake-save-witness") intent = intent with { NativeWitness = new object() };
            if (mode == "unminted-save") intent = new(fixture.Store, intent.KeyIdentity, intent.Generation, intent.Token, intent.Previous, intent.NextContent);
            if (mode == "revoked") fixture.Store.Revoke();
            if (mode == "reapproved") await fixture.ApproveAsync();
            if (mode == "changed-binding") fixture.Binding = "different-native-book";
            if (mode == "tampered-intent")
            {
                var envelope = JsonNode.Parse(intentText)!; envelope["payload"]!["new"] = new string('a', 64);
                fixture.Write(".save-intent.json", envelope.ToJsonString());
            }
            if (mode == "malformed-intent") fixture.Write(".save-intent.json", "{}");
            if (mode is "advance-failure" or "no-rollback") { fixture.FailWrite = 1; fixture.Writes = 0; }
            if (mode is "old-outcome" or "new-outcome" or "unknown-outcome")
            {
                if (mode == "unknown-outcome")
                    await FailsAsync(() => { fixture.Store.RecoverSaved(confirmed); return Task.CompletedTask; }, "Recovery adopted unrelated unknown book");
                else TestAssert.That(fixture.NewStore().RecoverSaved(confirmed) == NativeBookJson.Hash(JsonNode.Parse(fixture.Text)!), "Known saved outcome did not recover across store reconstruction");
            }
            else if (mode is "unconfirmed" or "wrong-snapshot" or "wrong-store" or "wrong-token" or "wrong-generation" or "wrong-key" or "wrong-next" or
                "revoked" or "reapproved" or "changed-binding" or "tampered-intent" or "malformed-intent" or "advance-failure" or "no-rollback" or "new-owner-confirm" or "fake-save-witness" or "unminted-save")
            {
                if (mode == "no-rollback")
                {
                    // Preserve signed intent but install a confirmed new record,
                    // simulating interruption between readback and intent delete.
                    fixture.FailWrite = 0;
                    fixture.Store.ConfirmSave(intent, confirmed);
                    fixture.Write(".save-intent.json", intentText);
                    fixture.Save(old.Text);
                    await FailsAsync(() => { fixture.Store.RecoverSaved(fixture.Capture()!); return Task.CompletedTask; }, "Recovery rolled an advanced consent record back to old content");
                }
                else await FailsAsync(() => { fixture.Store.ConfirmSave(intent, confirmed); return Task.CompletedTask; }, "Unconfirmed/changed save advanced native consent");
                if (mode == "advance-failure")
                {
                    fixture.FailWrite = 0;
                    await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Failed advance cleared the pending hold");
                    fixture.Store.RecoverSaved(confirmed);
                }
            }
            else
            {
                fixture.Store.ConfirmSave(intent, confirmed);
                TestAssert.That(!File.Exists(Path.Combine(fixture.Root, "consent", ".save-intent.json")), "Confirmed native save retained its pending marker");
                await FailsAsync(() => { fixture.Store.ConfirmSave(intent, confirmed); return Task.CompletedTask; }, "Consumed save token was reusable");
                if (mode == "replayed-intent")
                {
                    fixture.Write(".save-intent.json", intentText);
                    await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Replayed save intent granted IO");
                    fixture.Store.RecoverSaved(confirmed);
                }
                fixture.Credentials.Unavailable = false;
                var current = fixture.Store.LoadCurrent();
                TestAssert.That(current?.Generation == original.Generation && current.Sources.SequenceEqual(original.Sources), "Ordinary save changed human source selection or generation");
                await Require(current!);
                await FailsAsync(() => Require(original), "Old pre-save operation witness remained usable");
            }
            Console.WriteLine("CONTACT SOURCE APPROVAL SAVE PASS " + mode);
        }
    }

    private static async Task PrimaryChainAsync()
    {
        const string next = "{\"version\":6,\"kontakte\":[],\"fraction\":1.25,\"restartNormalized\":true}";
        foreach (var mode in new[] { "encrypted-restart", "plaintext-restart", "locked", "corrupt-cipher", "other-key", "missing-primary",
            "substituted-clear", "changed-during-read", "unavailable", "wrong-binding", "no-primary-callback", "still-saved-owner",
            "known-old", "known-new", "unknown-outcome", "stale-observation", "no-saved-witness-from-primary", "callbacks-outside-lock", "retarget-save-witness" })
        {
            using var fixture = new Fixture();
            var path = Path.Combine(fixture.Root, "actual-primary.json"); fixture.Binding = path;
            var atomic = new AtomicStore(); var encryption = new EncryptionService();
            try
            {
                var raw = mode == "plaintext-restart" ? fixture.Text : encryption.Enable(fixture.Text, "synthetic-primary-password");
                atomic.Write(path, raw);
                var available = true;
                fixture.PrimaryCapture = () => ContactSourcePrimaryBook.Capture(path, atomic, encryption, () => available);
                var original = await fixture.ApproveAsync();
                if (mode == "retarget-save-witness")
                {
                    var saved = fixture.Capture()!;
                    var primary = fixture.PrimaryCapture()!;
                    var token = fixture.Store.PrepareSave(saved, fixture.Text)!;
                    var copied = token with { Previous = null, PreviousPrimary = primary };
                    await FailsAsync(() => { fixture.Store.ConfirmSave(copied, saved); return Task.CompletedTask; },
                        "Copied saved intent substituted a primary observation to bypass later native save sequence");
                    Console.WriteLine("CONTACT SOURCE APPROVAL PRIMARY PASS " + mode); continue;
                }
                if (mode is "known-old" or "known-new" or "unknown-outcome") fixture.Store.PrepareSave(fixture.Capture()!, next);
                if (mode != "still-saved-owner") { fixture.Owner = new NativeBookOwnerScope(); fixture.Owner.SetReady(true); }
                if (mode == "callbacks-outside-lock")
                {
                    fixture.PrimaryCapture = () =>
                    {
                        using (fixture.Files.Open()) { }
                        return ContactSourcePrimaryBook.Capture(path, atomic, encryption, () => available);
                    };
                }
                if (mode == "locked") encryption.Clear();
                if (mode == "unavailable") available = false;
                if (mode == "missing-primary") File.Delete(path);
                if (mode == "substituted-clear") atomic.Write(path, fixture.Text);
                if (mode == "corrupt-cipher")
                {
                    var envelope = JsonNode.Parse(raw)!; var cipher = Convert.FromBase64String(envelope["daten"]!.GetValue<string>());
                    cipher[^1] ^= 1; envelope["daten"] = Convert.ToBase64String(cipher); CryptographicOperations.ZeroMemory(cipher);
                    atomic.Write(path, envelope.ToJsonString());
                }
                if (mode == "other-key")
                {
                    var other = new EncryptionService();
                    try { atomic.Write(path, other.Enable(fixture.Text, "different-synthetic-primary-password")); }
                    finally { other.Clear(); }
                }
                if (mode == "changed-during-read")
                {
                    var calls = 0;
                    fixture.PrimaryCapture = () => ContactSourcePrimaryBook.Capture(path, atomic, encryption, () =>
                    {
                        if (++calls == 2) atomic.Write(path, encryption.EncryptData(next));
                        return true;
                    });
                }
                if (mode is "locked" or "corrupt-cipher" or "other-key" or "missing-primary" or "substituted-clear" or "changed-during-read" or "unavailable")
                {
                    await FailsAsync(() => { fixture.PrimaryCapture(); return Task.CompletedTask; }, "Unauthenticated/unavailable native primary produced an observation");
                }
                else
                {
                    if (mode is "known-new" or "unknown-outcome") atomic.Write(path, encryption.EncryptData(mode == "known-new" ? next : "{\"foreign\":true}"));
                    var observed = fixture.PrimaryCapture()!;
                    if (mode == "wrong-binding") fixture.Binding = "another-native-book";
                    if (mode == "no-primary-callback") fixture.PrimaryCapture = null;
                    if (mode == "stale-observation") atomic.Write(path, encryption.EncryptData(next));
                    if (mode is "wrong-binding" or "no-primary-callback" or "stale-observation" or "still-saved-owner")
                    {
                        await FailsAsync(() => { fixture.Store.PreparePrimarySave(observed, next); return Task.CompletedTask; }, "Stale/incorrect primary context prepared native restart save");
                    }
                    else if (mode is "known-old" or "known-new" or "unknown-outcome")
                    {
                        if (mode == "unknown-outcome") await FailsAsync(() => { fixture.Store.RecoverPrimary(observed); return Task.CompletedTask; }, "Primary recovery adopted an unrelated book");
                        else TestAssert.That(fixture.Store.RecoverPrimary(observed) == observed.Content, "Authenticated known primary outcome did not recover");
                        TestAssert.That(fixture.Capture() is null, "Primary recovery manufactured a native saved-book witness");
                        await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Primary recovery granted IO before actual save");
                    }
                    else
                    {
                        if (mode == "no-saved-witness-from-primary")
                        {
                            TestAssert.That(fixture.Store.RecoverPrimary(observed) is null && fixture.Capture() is null,
                                "Primary no-intent recovery fabricated a saved witness");
                            await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Primary observation alone granted IO");
                        }
                        var intent = fixture.Store.PreparePrimarySave(observed, next) ?? throw new InvalidOperationException("Controlled primary intent missing");
                        await FailsAsync(() => { fixture.Store.LoadCurrent(); return Task.CompletedTask; }, "Primary prepare released usable authority");
                        atomic.Write(path, mode == "plaintext-restart" ? next : encryption.EncryptData(next));
                        fixture.Save(next); // Actual native saved witness is separate from the primary observation.
                        fixture.Store.ConfirmSave(intent, fixture.Capture()!);
                        var restored = fixture.Store.LoadCurrent();
                        TestAssert.That(restored is not null && restored.Generation == original.Generation && restored.Sources.SequenceEqual(original.Sources),
                            "First confirmed save after authenticated primary recovery lost native consent");
                        await Require(restored!);
                    }
                }
                Console.WriteLine("CONTACT SOURCE APPROVAL PRIMARY PASS " + mode);
            }
            finally { encryption.Clear(); }
        }
    }

    private static async Task ScopeRestoreAsync()
    {
        foreach (var mode in new[] { "success", "new-owner", "new-save", "changed-book", "renewed-credential", "stale-credential",
            "locked-credential", "durable-revoked", "volatile-revoked-during-restore", "final-guard-rejected", "final-guard-revokes",
            "final-guard-changes-book", "canceled", "operation-revoke", "operation-book-change", "operation-new-save",
            "operation-keyring-lock", "operation-guard-replaced", "explicit-reconfigure", "cancel-preserves-durable" })
        {
            using var fixture = new Fixture();
            var lease = await fixture.ApproveAsync();
            if (mode == "new-owner") { fixture.Owner = new NativeBookOwnerScope(); fixture.Owner.SetReady(true); fixture.Save(fixture.Text); lease = fixture.Store.LoadCurrent()!; }
            if (mode == "new-save") { fixture.Save(fixture.Text); lease = fixture.Store.LoadCurrent()!; }
            if (mode == "changed-book") fixture.Save("{\"different\":true}");
            if (mode is "renewed-credential" or "stale-credential")
            { fixture.Account.SetApplicationPassword("renewed-synthetic-restore-secret"); if (mode == "renewed-credential") lease = fixture.Store.LoadCurrent()!; }
            if (mode == "locked-credential") fixture.Credentials.Unavailable = true;
            if (mode == "durable-revoked") fixture.Store.Revoke();
            var fresh = new ContactSourceApprovalScope(fixture.Current, fixture.Account.ReadSnapshot);
            if (mode == "volatile-revoked-during-restore") fixture.Credentials.OnRead = () => fresh.Revoke();
            Action? guard = mode switch
            {
                "final-guard-rejected" => () => throw new InvalidOperationException("Controlled native application generation changed"),
                "final-guard-revokes" => () => fresh.Revoke(),
                "final-guard-changes-book" => () => fixture.Save("{\"changedDuringFinalGuard\":true}"),
                _ => null
            };
            using var cancel = new CancellationTokenSource(); if (mode == "canceled") cancel.Cancel();
            if (mode is "changed-book" or "stale-credential" or "locked-credential" or "durable-revoked" or "volatile-revoked-during-restore" or
                "final-guard-rejected" or "final-guard-revokes" or "final-guard-changes-book" or "canceled")
            {
                await FailsAsync(() => fresh.RestoreAsync(lease, guard, cancel.Token), "Stale/revoked/unavailable native durable lease restored a scope");
                TestAssert.That(fresh.Capture().Count == 0, "Failed restore left a usable scope grant");
            }
            else
            {
                await fresh.RestoreAsync(lease, guard, cancel.Token);
                var approved = fresh.Capture().Single();
                ContactSourceApprovalScope.RequireNativeDecision(approved, CancellationToken.None);
                await approved.RequireApproved(CancellationToken.None);
                if (mode is "operation-revoke" or "operation-guard-replaced") fixture.Store.Revoke();
                if (mode == "operation-book-change") fixture.Save("{\"laterEdit\":true}");
                if (mode == "operation-new-save") fixture.Save(fixture.Text);
                if (mode == "operation-keyring-lock") fixture.Credentials.Unavailable = true;
                if (mode == "operation-guard-replaced") approved = approved with { RequireApproved = _ => Task.CompletedTask };
                if (mode.StartsWith("operation-", StringComparison.Ordinal))
                    await FailsAsync(() => { ContactSourceApprovalScope.RequireNativeDecision(approved, CancellationToken.None); return Task.CompletedTask; },
                        "Restored native consent token survived durable revoke/new save/credential loss or callback replacement");
                if (mode == "explicit-reconfigure")
                {
                    await fresh.ConfigureAsync([fixture.Source], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([fixture.Source.Uid]));
                    var selected = fresh.Capture();
                    var renewed = await fixture.Store.ApproveAsync(fixture.Capture()!, selected);
                    TestAssert.That(renewed is not null && renewed.Generation != lease.Generation, "Genuine new decision retained the old durable scope dependency");
                }
                if (mode == "cancel-preserves-durable")
                {
                    var changed = await fresh.ConfigureAsync([fixture.Source], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>(null));
                    TestAssert.That(!changed, "Cancel was interpreted as a new decision");
                    fixture.Store.Revoke();
                    await FailsAsync(() => approved.RequireApproved(CancellationToken.None), "Cancel dropped the original durable revocation dependency");
                }
            }
            Console.WriteLine("CONTACT SOURCE APPROVAL SCOPE RESTORE PASS " + mode);
        }
    }

    private static async Task ActualWriterAsync()
    {
        foreach (var mode in new[] { "disabled", "ordinary", "same-content", "restart", "locked-credential", "corrupt-sidecar",
            "prepare-failed", "advance-failed", "primary-failed", "changed-binding", "recover-old", "recover-new", "unknown-primary", "result-save" })
        {
            using var fixture = new Fixture();
            if (mode == "result-save")
            {
                var seed = JsonNode.Parse(fixture.Text)!.AsObject();
                seed["kontakte"] = new JsonArray(new JsonObject { ["id"] = "synthetic-local-person", ["uid"] = "synthetic-canonical-person", ["notiz"] = "before" });
                fixture.Text = seed.ToJsonString();
            }
            var host = new PersonalActorNativeSaveHost(fixture.Root, fixture.Text);
            var binding = host.DataPath; var captures = 0;
            ContactSourceApprovalStore NewStore() => new(fixture.Files, fixture.Account, () => { captures++; return host.Snapshot(); },
                () => binding, fixture.Keys, host.Primary);
            host.ApprovalStore = NewStore();
            var original = host.Snapshot()!;
            StoredContactSourceApproval? approved = null;
            if (mode != "disabled")
            {
                var scope = new ContactSourceApprovalScope(host.Saved, fixture.Account.ReadSnapshot);
                await scope.ConfigureAsync([fixture.Source], (_, _, _) => Task.FromResult<IReadOnlyList<string>?>([fixture.Source.Uid]));
                approved = await host.ApprovalStore.ApproveAsync(original, scope.Capture());
            }
            captures = 0;
            var candidate = JsonNode.Parse(fixture.Text)!.AsObject();
            if (mode is not ("same-content" or "result-save")) candidate["ordinaryWriterEdit"] = true;
            ContactSourceCommitOffer? resultOffer = null;
            if (mode == "result-save")
            {
                var contacts = candidate["kontakte"]!.DeepClone().AsArray(); contacts[0]!["notiz"] = "confirmed synthetic result";
                resultOffer = host.StageOriginalContactResult(new(original.SavedBook, contacts, new Dictionary<string, ContactSyncCounts>()));
                candidate["kontakte"] = resultOffer.Contacts.DeepClone();
            }
            if (mode is "recover-old" or "recover-new" or "unknown-primary")
            {
                host.ApprovalStore.PrepareSave(host.Snapshot()!, candidate.ToJsonString());
                if (mode is "recover-new" or "unknown-primary")
                {
                    var encryption = new EncryptionService();
                    try
                    {
                        encryption.Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password);
                        new AtomicStore().WriteRecoverableJson(host.DataPath, encryption.EncryptData(mode == "recover-new" ?
                            candidate.ToJsonString() : "{\"unrelatedPrimary\":true}"));
                    }
                    finally { encryption.Clear(); }
                }
            }
            if (mode is "restart" or "recover-old" or "recover-new" or "unknown-primary")
            {
                host = new PersonalActorNativeSaveHost(fixture.Root, "not-a-saved-witness", reopen: true);
                host.ApprovalStore = NewStore();
                TestAssert.That(host.Snapshot() is null, "Restarted actual writer fabricated a native saved witness");
            }
            if (mode is "disabled" or "locked-credential") fixture.Credentials.Unavailable = true;
            if (mode == "corrupt-sidecar") fixture.Write("approval.json", "{broken");
            if (mode is "prepare-failed" or "advance-failed") { fixture.FailWrite = mode == "prepare-failed" ? 1 : 2; fixture.Writes = 0; }
            if (mode == "primary-failed") host.FailAfterPrimary = true;
            if (mode == "changed-binding") binding = "different-native-book";
            var message = new JsonObject { ["cmd"] = "speichern", ["id"] = 71, ["text"] = candidate.ToJsonString() };
            if (resultOffer is not null) message["kontaktOriginalLauf"] = resultOffer.Token;
            var ack = await host.SaveBridgeEnvelopeAsync(message);
            var held = mode is "corrupt-sidecar" or "prepare-failed" or "advance-failed" or "primary-failed" or "changed-binding" or "unknown-primary";
            if (mode == "primary-failed")
            {
                TestAssert.That(ack["ok"]!.GetValue<bool>() == false && host.Snapshot() is null && ack["kontaktQuellenDauerhaft"] is null,
                    "Failed actual primary save acknowledged contact delivery");
            }
            else
            {
                TestAssert.That(ack["ok"]!.GetValue<bool>() && ack["committed"]!.GetValue<bool>() && !ack["repairPending"]!.GetValue<bool>() &&
                    ack["standSha256"]!.GetValue<string>() == BaumSyncSnapshot.Hash(candidate.ToJsonString()) &&
                    host.Snapshot()?.Text == candidate.ToJsonString(), "Consent sidecar changed ordinary actual native save semantics");
                TestAssert.That(ack["kontaktQuellenDauerhaft"]!.GetValue<bool>() == (!held && mode != "disabled") &&
                    ack["kontaktQuellenFehler"]!.GetValue<bool>() == held, "Actual writer claimed unconfirmed native consent advancement");
            }
            var verification = new EncryptionService();
            try { TestAssert.That(verification.Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password) == candidate.ToJsonString(),
                "Actual encrypted writer did not persist the user candidate despite held consent"); }
            finally { verification.Clear(); }
            fixture.FailWrite = 0; fixture.Credentials.Unavailable = false;
            if (mode == "disabled")
                TestAssert.That(captures == 0 && !Directory.Exists(Path.Combine(fixture.Root, "consent")), "Disabled actual writer observed book/account or created private state");
            else if (!held)
            {
                var restored = host.ApprovalStore.LoadCurrent();
                TestAssert.That(restored is not null && restored.Generation == approved!.Generation && restored.Sources.SequenceEqual(approved.Sources),
                    "Actual confirmed writer lost original durable selection across ordinary/restart save");
                await Require(restored!);
                await FailsAsync(() => Require(approved!), "Pre-save durable operation witness survived actual writer advancement");
                if (resultOffer is not null)
                {
                    TestAssert.That(ack["kontaktOriginalGespeichert"]!.GetValue<string>() == resultOffer.Token, "Durable save advancement lost actual native result confirmation");
                    var bytes = File.ReadAllBytes(host.DataPath); var saved = host.Saved();
                    var replay = await host.SaveBridgeEnvelopeAsync(message);
                    TestAssert.That(!replay["ok"]!.GetValue<bool>() && host.Saved() == saved && bytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)),
                        "Durable result SaveACK permitted a consumed result token to write again");
                }
            }
            Console.WriteLine("CONTACT SOURCE APPROVAL ACTUAL WRITER PASS " + mode);
        }
    }
}
