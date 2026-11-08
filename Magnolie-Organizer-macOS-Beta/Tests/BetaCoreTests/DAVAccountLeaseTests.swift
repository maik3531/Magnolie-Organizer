import Foundation
import CryptoKit
import XCTest
import Darwin
@testable import BetaCore

private final class LeaseConfiguration: DAVAccountConfigurationStore {
    let revisionNamespace: String
    var value: DAVAccountConfiguration?
    var failNextReplace = false
    init(_ value: DAVAccountConfiguration?, namespace: String = "fixture-account-store") { self.value = value; revisionNamespace = namespace }
    func read() throws -> DAVAccountConfiguration? { value }
    func replace(_ value: DAVAccountConfiguration?) throws {
        if failNextReplace { failNextReplace = false; throw DAVAccountError.storageUnavailable }
        self.value = value
    }
}
private final class LeaseCredentials: DAVCredentialStore {
    var items: [String: String] = [:]
    var locked = false
    var afterRead: (() -> Void)?
    func read(for identity: DAVCredentialIdentity) throws -> String? {
        if locked { throw DAVAccountError.credentialUnavailable }
        let result = items[identity.storageKey]; afterRead?(); return result
    }
    func write(_ secret: String, for identity: DAVCredentialIdentity) throws { items[identity.storageKey] = secret }
    func delete(for identity: DAVCredentialIdentity) throws -> Bool { items.removeValue(forKey: identity.storageKey) != nil }
}
private final class LeaseKeys: DAVSyncJournalKeyStore {
    var key: DAVSyncJournalKey?
    var missing = false
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        if missing { throw DAVSyncJournalError.missingKey }
        if let key { return key }
        guard allowCreate else { throw DAVSyncJournalError.missingKey }
        let new = try DAVSyncJournalKey(id: Data(repeating: 4, count: 32), bytes: Data(repeating: 7, count: 32))
        key = new
        return try DAVSyncJournalKey(id: new.id, bytes: new.bytes, newlyCreated: true)
    }
}
private final class LeaseClock { var value: TimeInterval = 100 }
private actor LeaseBarrier {
    private var entered = false, opened = false
    private var entry: CheckedContinuation<Void, Never>?, release: CheckedContinuation<Void, Never>?
    func wait() async {
        entered = true; entry?.resume(); entry = nil
        if !opened { await withCheckedContinuation { release = $0 } }
    }
    func started() async { if !entered { await withCheckedContinuation { entry = $0 } } }
    func open() { opened = true; release?.resume(); release = nil }
}
private actor LeaseTransport: BoundedHTTPTransport {
    var responses: [BoundedHTTPResponse]
    var requests = 0
    var gate: LeaseBarrier?
    init(_ responses: [BoundedHTTPResponse]) { self.responses = responses }
    func append(_ values: [BoundedHTTPResponse], gate: LeaseBarrier? = nil) { responses += values; self.gate = gate }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests += 1
        if let gate { self.gate = nil; await gate.wait() }
        guard !responses.isEmpty else { throw DAVError.invalidResponse }; return responses.removeFirst()
    }
}

private actor OverlappingLeaseDiscovery: BoundedHTTPTransport {
    let seed: [BoundedHTTPResponse], older: [BoundedHTTPResponse], newer: [BoundedHTTPResponse], barrier: LeaseBarrier
    var count = 0
    init(seed: [BoundedHTTPResponse], older: [BoundedHTTPResponse], newer: [BoundedHTTPResponse], barrier: LeaseBarrier) {
        self.seed = seed; self.older = older; self.newer = newer; self.barrier = barrier
    }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        let index = count; count += 1
        if index < 4 { return seed[index] }
        if index == 4 { await barrier.wait(); return older[0] }
        if index < 9 { return newer[index - 5] }
        guard index - 8 < older.count else { throw DAVError.invalidResponse }; return older[index - 8]
    }
}

final class DAVAccountLeaseTests: XCTestCase {
    private func directory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("dav-lease-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }; return root
    }
    private func config(active: Bool = true) throws -> DAVAccountConfiguration {
        try DAVAccountConfiguration(davAktiv: active, server: "https://cloud.example/nextcloud", benutzer: "person")
    }
    private func replies(taskSupport: Bool = true) -> [BoundedHTTPResponse] {
        func xml(_ content: String) -> BoundedHTTPResponse { .init(status: 207, body: Data(("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:a='urn:ietf:params:xml:ns:carddav'>" + content + "</d:multistatus>").utf8)) }
        func row(_ href: String, _ props: String) -> String { "<d:response><d:href>\(href)</d:href><d:propstat><d:prop>\(props)</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" }
        let components = "<c:supported-calendar-component-set><c:comp name='VEVENT'/>" + (taskSupport ? "<c:comp name='VTODO'/>" : "") + "</c:supported-calendar-component-set>"
        return [xml(row("/.well-known/caldav", "<c:calendar-home-set><d:href>/cal/person/</d:href></c:calendar-home-set>")),
                xml(row("/cal/person/a/", "<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>A</d:displayname>" + components) + row("/cal/person/b/", "<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>B</d:displayname>" + components)),
                xml(row("/.well-known/carddav", "<a:addressbook-home-set><d:href>/contacts/person/</d:href></a:addressbook-home-set>")), xml("")]
    }
    private func service(_ store: LeaseConfiguration, secrets: LeaseCredentials, transport: LeaseTransport, clock: LeaseClock = LeaseClock()) -> DAVAccountService {
        DAVAccountService(configuration: store, credentials: secrets, transport: transport, monotonicTime: { clock.value })
    }
    private func prepared(_ service: DAVAccountService) async throws -> (String, [String]) {
        let revision = await service.status().revision!
        let discovery = try await service.discover(expectedRevision: revision)
        return (revision, discovery.status.calendars.map(\.uid))
    }
    private func expect(_ expectedError: DAVAccountLeaseError, _ operation: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await operation(); XCTFail("Expected lease error", file: file, line: line) }
        catch { XCTAssertEqual(error as? DAVAccountLeaseError, expectedError, file: file, line: line) }
    }
    func testPinFreezesOrderedSourcesAndMetadataWithoutAdditionalNetworkingOrPublicDigest() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), network = LeaseTransport(replies())
        secrets.items[try store.value!.identity.storageKey] = "fixture-app-secret"
        let account = service(store, secrets: secrets, transport: network), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, sources) = try await prepared(account)
        let before = await network.requests
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: Array(sources.reversed()), signer: signer)
        let binding = try await account.binding(lease)
        XCTAssertEqual(binding.calendars.map(\.uid), Array(sources.reversed())); XCTAssertTrue(binding.calendars.allSatisfy(\.supportsVtodo))
        XCTAssertEqual(binding.sessionRevision, revision); XCTAssertEqual(binding.persistentAccountBinding.count, 64)
        let after = await network.requests; XCTAssertEqual(before, after)
        let payload = await account.status().payload()
        XCTAssertNil(payload["persistentAccountBinding"]); XCTAssertNil(payload["applicationPassword"])
        XCTAssertFalse(try Document.encode(payload).contains("fixture-app-secret"))
    }
    func testFreshServiceChangesSessionCASButPreservesJournalDerivedAccountBinding() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys()), signer = try await journal.accountBindingSigner()
        let first = service(store, secrets: secrets, transport: LeaseTransport(replies())), second = service(store, secrets: secrets, transport: LeaseTransport(replies()))
        let (one, ids) = try await prepared(first), (two, ids2) = try await prepared(second)
        let leaseA = try await first.pinForSync(expectedRevision: one, orderedCalendarUIDs: ids, signer: signer)
        let leaseB = try await second.pinForSync(expectedRevision: two, orderedCalendarUIDs: ids2, signer: signer)
        let a = try await first.binding(leaseA), b = try await second.binding(leaseB)
        XCTAssertNotEqual(one, two); XCTAssertEqual(a.persistentAccountBinding, b.persistentAccountBinding)
        XCTAssertEqual(a.discoveryFingerprint, b.discoveryFingerprint)
    }
    func testStaleAndInvalidSaveRequestsDoNotRevokeValidLease() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies())), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        do { _ = try await account.save(expectedRevision: "stale", configuration: store.value!); XCTFail("Stale save accepted") } catch { XCTAssertEqual(error as? DAVAccountError, .conflict) }
        try await account.revalidate(lease)
        do { _ = try await account.save(expectedRevision: revision, configuration: store.value!, clearPassword: true); XCTFail("Invalid clear accepted") } catch { XCTAssertEqual(error as? DAVAccountError, .invalidConfiguration) }
        try await account.revalidate(lease)
    }
    func testFirstActualMutationRevokesEvenWhenRollbackRestoresPublicCAS() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies())), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        store.failNextReplace = true
        do { _ = try await account.save(expectedRevision: revision, configuration: store.value!); XCTFail("Injected replace must fail") } catch { }
        let after = await account.status(); XCTAssertEqual(after.revision, revision)
        await expect(.invalidLease) { try await account.revalidate(lease) }
    }
    func testExternalSecretChangeAndTornDoubleCollectCannotPinOrRevalidate() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), identity = try store.value!.identity
        secrets.items[identity.storageKey] = "first-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies())), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        secrets.items[identity.storageKey] = "second-secret"
        await expect(.bindingChanged) { try await account.revalidate(lease) }
        secrets.items[identity.storageKey] = "first-secret"
        secrets.afterRead = { secrets.afterRead = nil; secrets.items[identity.storageKey] = "torn-secret" }
        await expect(.bindingChanged) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer) }
    }
    func testDiscoveryRefreshRevokesBeforeAwaitAndFailedRefreshCannotResurrectOldSources() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), transport = LeaseTransport(replies())
        secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: transport), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        let gate = LeaseBarrier(); await transport.append([.init(status: 401)], gate: gate)
        let refresh = Task { try await account.discover(expectedRevision: revision) }
        await gate.started()
        await expect(.invalidLease) { try await account.revalidate(lease) }
        await expect(.discoveryRequired) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer) }
        await gate.open(); _ = try await refresh.value
        await expect(.discoveryRequired) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer) }
    }
    func testOlderDiscoveryCompletingLastCannotOverwriteNewerCapabilities() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), barrier = LeaseBarrier()
        secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let transport = OverlappingLeaseDiscovery(seed: replies(), older: replies(taskSupport: true), newer: replies(taskSupport: false), barrier: barrier)
        let account = DAVAccountService(configuration: store, credentials: secrets, transport: transport)
        let journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let oldRefresh = Task { try await account.discover(expectedRevision: revision) }
        await barrier.started()
        let newer = try await account.discover(expectedRevision: revision)
        XCTAssertFalse(newer.status.calendars[0].supportsVtodo)
        await barrier.open()
        do { _ = try await oldRefresh.value; XCTFail("Old refresh published after newer generation") }
        catch { XCTAssertEqual(error as? DAVAccountError, .conflict) }
        let current = await account.status()
        XCTAssertFalse(current.calendars[0].supportsVtodo); XCTAssertEqual(current.errorCode, "none")
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        let binding = try await account.binding(lease); XCTAssertFalse(binding.calendars[0].supportsVtodo)
    }
    func testCapabilityChangeIsFrozenAndOrderedSelectionChangesFingerprint() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), network = LeaseTransport(replies())
        secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: network), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let firstLease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        let first = try await account.binding(firstLease)
        let reverseLease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: Array(ids.reversed()), signer: signer)
        let reverse = try await account.binding(reverseLease); XCTAssertNotEqual(first.discoveryFingerprint, reverse.discoveryFingerprint)
        await network.append(replies(taskSupport: false)); _ = try await account.discover(expectedRevision: revision)
        await expect(.invalidLease) { try await account.revalidate(firstLease) }
        let updatedLease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        let updated = try await account.binding(updatedLease)
        XCTAssertFalse(updated.calendars[0].supportsVtodo); XCTAssertNotEqual(first.discoveryFingerprint, updated.discoveryFingerprint)
        XCTAssertEqual(first.persistentAccountBinding, updated.persistentAccountBinding)
    }
    func testUnknownDuplicateAbsentDiscoveryInactiveAndMissingPasswordCannotPin() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies())), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), before = await account.status()
        await expect(.discoveryRequired) { _ = try await account.pinForSync(expectedRevision: before.revision!, orderedCalendarUIDs: ["unknown"], signer: signer) }
        let (revision, ids) = try await prepared(account)
        for selected in [[], ["unknown"], [ids[0], ids[0]]] {
            await expect(.invalidSelection) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: selected, signer: signer) }
        }
        secrets.items.removeAll()
        let missing = await account.status()
        do { _ = try await account.pinForSync(expectedRevision: missing.revision!, orderedCalendarUIDs: ids, signer: signer); XCTFail("Missing secret accepted") } catch { XCTAssertEqual(error as? DAVAccountError, .missingPassword) }
        store.value = try config(active: false)
        let inactive = await account.status()
        do { _ = try await account.pinForSync(expectedRevision: inactive.revision!, orderedCalendarUIDs: ids, signer: signer); XCTFail("Inactive accepted") } catch { XCTAssertEqual(error as? DAVAccountError, .notActive) }
    }
    func testRegistryCountExpirationReleaseAndForeignHandleNeverResurrect() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(), clock = LeaseClock()
        secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies()), clock: clock), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        var leases: [DAVSyncAccountLease] = []
        for _ in 0..<16 { leases.append(try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)) }
        await expect(.capacity) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer) }
        await account.release(leases[0]); await expect(.invalidLease) { try await account.revalidate(leases[0]) }
        _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        clock.value += 300
        await expect(.expired) { try await account.revalidate(leases[1]) }
        clock.value = 100
        await expect(.invalidLease) { try await account.revalidate(leases[1]) }
        let other = service(store, secrets: secrets, transport: LeaseTransport([]))
        await expect(.invalidLease) { try await other.revalidate(leases[2]) }
    }
    func testJournalMissingChangedKeyOrPoisonedStateRevokesSignerWithoutReset() async throws {
        let root = try directory(), keys = LeaseKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let journal = try DAVSyncJournalStore(files: files, keys: keys), signer = try await journal.accountBindingSigner()
        keys.missing = true
        await expect(.signerUnavailable) { try await signer.ensureCurrent() }
        keys.missing = false
        await expect(.signerUnavailable) { try await signer.ensureCurrent() }
        do { _ = try await journal.accountBindingSigner(); XCTFail("Poisoned journal issued signer") } catch { }
        let secondRoot = try directory(), secondKeys = LeaseKeys(), second = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: secondRoot), keys: secondKeys)
        let otherSigner = try await second.accountBindingSigner()
        XCTAssertEqual(unlink(secondRoot.appendingPathComponent("DAVSync-Journal/journal-v1.enc").path), 0)
        await expect(.signerUnavailable) { try await otherSigner.ensureCurrent() }
        XCTAssertEqual(secondKeys.key?.id.count, 32)
        let thirdRoot = try directory(), thirdKeys = LeaseKeys(), third = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: thirdRoot), keys: thirdKeys)
        let thirdSigner = try await third.accountBindingSigner()
        let cipherPath = thirdRoot.appendingPathComponent("DAVSync-Journal/journal-v1.enc"), cipher = try AtomicStore.read(cipherPath)
        thirdKeys.key = try DAVSyncJournalKey(id: Data(repeating: 4, count: 32), bytes: Data(repeating: 8, count: 32))
        await expect(.signerUnavailable) { try await thirdSigner.ensureCurrent() }
        XCTAssertEqual(try AtomicStore.read(cipherPath), cipher)
    }
    func testJournalReopenRepinKeepsStableBindingButOldSignerCannotResurrect() async throws {
        let root = try directory(), keys = LeaseKeys(), store = LeaseConfiguration(try config()), secrets = LeaseCredentials()
        secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        var files: DAVSyncJournalFiles? = try DAVSyncJournalFiles(profileDirectory: root)
        var journal: DAVSyncJournalStore? = try DAVSyncJournalStore(files: files!, keys: keys)
        let oldSigner = try await journal!.accountBindingSigner(), first = service(store, secrets: secrets, transport: LeaseTransport(replies()))
        let (revision, ids) = try await prepared(first)
        let oldLease = try await first.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: oldSigner)
        let oldBinding = try await first.binding(oldLease)
        journal = nil; files = nil
        await expect(.signerUnavailable) { try await oldSigner.ensureCurrent() }
        let reopened = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: root), keys: keys)
        let signer = try await reopened.accountBindingSigner(), second = service(store, secrets: secrets, transport: LeaseTransport(replies()))
        let (freshRevision, freshSources) = try await prepared(second)
        let freshLease = try await second.pinForSync(expectedRevision: freshRevision, orderedCalendarUIDs: freshSources, signer: signer)
        let freshBinding = try await second.binding(freshLease)
        XCTAssertEqual(oldBinding.persistentAccountBinding, freshBinding.persistentAccountBinding)
        XCTAssertNotEqual(oldBinding.sessionRevision, freshBinding.sessionRevision)
    }
    func testIndependentPythonHKDFHMACVectorAndOpaqueCredentialBytes() throws {
        // Independently generated with Python stdlib HKDF-expand/HMAC + big-endian lengths.
        let namespace = String(repeating: "0", count: 64)
        let derived = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: Data(repeating: 7, count: 32)),
            salt: Data(repeating: 4, count: 32), info: Data(("Magnolie-DAV-account-binding-v1\0" + namespace).utf8), outputByteCount: 32)
        let hex = derived.withUnsafeBytes { $0.map { String(format: "%02x", $0) }.joined() }
        XCTAssertEqual(hex, "4aea1b4a276b04de6de45dc690b3231f00d22cc3156cd45eff268d46e130e908")
        let signer = DAVAccountBindingSigner(namespace: namespace, key: derived, validateJournal: {})
        let configuration = try config()
        let binding = try signer.bind(configuration: configuration, secret: "fixture-secret", storeNamespace: "fixture-account-store")
        XCTAssertEqual(binding, "f2c82dbed20d7280c68e6312aad06972d6f648d7b0658db8edc69d63a41ffa3c")
        XCTAssertNotEqual(binding, try signer.bind(configuration: configuration, secret: "different-secret", storeNamespace: "fixture-account-store"))
        XCTAssertNotEqual(binding, try signer.bind(configuration: configuration, secret: "fixture-secret", storeNamespace: "other-store"))
        XCTAssertNotEqual(try signer.bind(configuration: configuration, secret: "caf\u{e9}", storeNamespace: "fixture-account-store"),
                          try signer.bind(configuration: configuration, secret: "cafe\u{301}", storeNamespace: "fixture-account-store"))
    }
    func testSameRawJournalKeyInDifferentNamespacesCannotShareAccountBinding() async throws {
        let root = try directory(), one = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: root), keys: LeaseKeys())
        let two = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let cipherPath = root.appendingPathComponent("DAVSync-Journal/journal-v1.enc"), before = try AtomicStore.read(cipherPath)
        let first = try await one.accountBindingSigner(), second = try await two.accountBindingSigner(), configuration = try config()
        XCTAssertEqual(try AtomicStore.read(cipherPath), before, "Deriving/validating a signer never rewrites the journal")
        XCTAssertNotEqual(try first.bind(configuration: configuration, secret: "fixture-secret", storeNamespace: "same-store"),
                          try second.bind(configuration: configuration, secret: "fixture-secret", storeNamespace: "same-store"))
    }
    func testMalformedOrDuplicateDiscoveredSourceAndLockedCredentialCannotGrantLease() async throws {
        for replacement in ["/cal/person/a/", "/cal/person/%00/"] {
            var responses = replies()
            let collectionBody = String(data: responses[1].body, encoding: .utf8)!.replacingOccurrences(of: "/cal/person/b/", with: replacement)
            responses[1] = .init(status: 207, body: Data(collectionBody.utf8))
            let store = LeaseConfiguration(try config()), secrets = LeaseCredentials()
            secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
            let account = service(store, secrets: secrets, transport: LeaseTransport(responses)), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
            let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
            await expect(.invalidSelection) { _ = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: [ids[0]], signer: signer) }
        }
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies())), journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory()), keys: LeaseKeys())
        let signer = try await journal.accountBindingSigner(), (revision, ids) = try await prepared(account)
        let lease = try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer)
        secrets.locked = true
        do { try await account.revalidate(lease); XCTFail("Locked Keychain accepted") } catch { XCTAssertEqual(error as? DAVAccountError, .credentialUnavailable) }
        secrets.locked = false
        await expect(.invalidLease) { try await account.revalidate(lease) }
    }
    func testMutationWhileSignerValidationSuspendsCannotCompleteOldPin() async throws {
        let store = LeaseConfiguration(try config()), secrets = LeaseCredentials(); secrets.items[try store.value!.identity.storageKey] = "fixture-secret"
        let account = service(store, secrets: secrets, transport: LeaseTransport(replies()))
        let (revision, ids) = try await prepared(account), barrier = LeaseBarrier()
        let signer = DAVAccountBindingSigner(namespace: "test-only", key: SymmetricKey(data: Data(repeating: 1, count: 32)), validateJournal: { await barrier.wait() })
        let pin = Task { try await account.pinForSync(expectedRevision: revision, orderedCalendarUIDs: ids, signer: signer) }
        await barrier.started(); _ = try await account.save(expectedRevision: revision, configuration: store.value!)
        await barrier.open()
        await expect(.bindingChanged) { _ = try await pin.value }
    }
}
