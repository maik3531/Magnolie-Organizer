import XCTest
@testable import BetaCore

private final class AccountMemoryConfiguration: DAVAccountConfigurationStore {
    let revisionNamespace = "fixture-store"
    var value: DAVAccountConfiguration?
    var failAfterReplaceOnce = false
    var failEveryReplace = false
    func read() throws -> DAVAccountConfiguration? { value }
    func replace(_ configuration: DAVAccountConfiguration?) throws {
        if failEveryReplace { throw DAVAccountError.storageUnavailable }
        value = configuration
        if failAfterReplaceOnce { failAfterReplaceOnce = false; throw DAVAccountError.storageUnavailable }
    }
}
private final class AccountMemoryCredentials: DAVCredentialStore {
    var items: [String: String] = [:]
    var failAfterWriteOnce = false
    var failAfterDeleteOnce = false
    var locked = false
    func read(for identity: DAVCredentialIdentity) throws -> String? {
        if locked { throw DAVAccountError.credentialUnavailable }
        return items[identity.storageKey]
    }
    func write(_ secret: String, for identity: DAVCredentialIdentity) throws {
        if locked { throw DAVAccountError.credentialUnavailable }
        items[identity.storageKey] = secret
        if failAfterWriteOnce { failAfterWriteOnce = false; throw DAVAccountError.credentialUnavailable }
    }
    @discardableResult func delete(for identity: DAVCredentialIdentity) throws -> Bool {
        if locked { throw DAVAccountError.credentialUnavailable }
        let existed = items.removeValue(forKey: identity.storageKey) != nil
        if failAfterDeleteOnce { failAfterDeleteOnce = false; throw DAVAccountError.credentialUnavailable }
        return existed
    }
}
private func accountXML(_ content: String) -> BoundedHTTPResponse {
    BoundedHTTPResponse(status: 207, body: Data("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:a='urn:ietf:params:xml:ns:carddav'>\(content)</d:multistatus>".utf8))
}
private func accountRow(_ href: String, _ properties: String) -> String {
    "<d:response><d:href>\(href)</d:href><d:propstat><d:prop>\(properties)</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
}
private actor AccountScriptTransport: BoundedHTTPTransport {
    private var replies: [BoundedHTTPResponse]
    private var requests: [BoundedHTTPRequest] = []
    private let gate: Bool
    private var entered = false
    private var enteredWaiter: CheckedContinuation<Void, Never>?
    private var releaseWaiter: CheckedContinuation<Void, Never>?
    init(_ replies: [BoundedHTTPResponse], gate: Bool = false) { self.replies = replies; self.gate = gate }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests.append(request)
        if gate && requests.count == 1 {
            entered = true; enteredWaiter?.resume(); enteredWaiter = nil
            await withCheckedContinuation { releaseWaiter = $0 }
        }
        guard !replies.isEmpty else { throw DAVError.invalidResponse }
        return replies.removeFirst()
    }
    func waitUntilEntered() async {
        if !entered { await withCheckedContinuation { enteredWaiter = $0 } }
    }
    func release() { releaseWaiter?.resume(); releaseWaiter = nil }
    func requestCount() -> Int { requests.count }
}

final class DAVAccountServiceTests: XCTestCase {
    private func configuration(server: String = "https://cloud.example/nextcloud", user: String = "person", active: Bool = true) throws -> DAVAccountConfiguration {
        try DAVAccountConfiguration(davAktiv: active, server: server, benutzer: user)
    }
    private func expect(_ expected: DAVAccountError, action: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await action(); XCTFail("Expected account error", file: file, line: line) }
        catch let error as DAVAccountError { XCTAssertEqual(error, expected, file: file, line: line) }
        catch { XCTFail("Unexpected error type: \(type(of: error))", file: file, line: line) }
    }
    private func discoveryReplies() -> [BoundedHTTPResponse] {
        [accountXML(accountRow("/.well-known/caldav", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>")),
         accountXML(accountRow("/calendars/person/personal/", "<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>Personal</d:displayname>")),
         accountXML(accountRow("/.well-known/carddav", "<a:addressbook-home-set><d:href>/addressbooks/person/</d:href></a:addressbook-home-set>")),
         accountXML(accountRow("/addressbooks/person/contacts/", "<d:resourcetype><a:addressbook/></d:resourcetype><d:displayname>Contacts</d:displayname>"))]
    }
    func testCanonicalConfigurationAndLegacyShapesRejectSecretsAndWrongTypes() throws {
        let configuration = try configuration()
        XCTAssertEqual(try DAVAccountConfiguration(dictionary: configuration.dictionary), configuration)
        let legacy = try DAVAccountConfiguration(dictionary: ["aktiv": false, "server": "https://CLOUD.example:443/nextcloud/", "benutzer": " person "])
        XCTAssertEqual(legacy.server, configuration.server); XCTAssertFalse(legacy.davAktiv)
        let invalidChanges: [[String: Any]] = [["appKennwort": "never-persist"], ["davAktiv": 1], ["kontoArt": 1], ["kontoArt": "unknown"]]
        for changes in invalidChanges {
            var value = configuration.dictionary
            value.merge(changes) { _, value in value }
            XCTAssertThrowsError(try DAVAccountConfiguration(dictionary: value))
        }
    }
    func testLocalStatusAndSavedPayloadNeverExposeSecretOrClaimConnectivity() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        XCTAssertEqual(initial.state, "nicht_eingerichtet"); XCTAssertEqual(initial.revision?.count, 64)
        let wanted = try configuration()
        let saved = try await service.save(expectedRevision: initial.revision!, configuration: wanted, applicationPassword: "fixture-app-password")
        XCTAssertEqual(config.value, wanted); XCTAssertTrue(saved.credentialPresent == true)
        XCTAssertNotEqual(saved.revision, initial.revision); XCTAssertFalse(saved.connectivityChecked)
        let payload = saved.payload(requestID: "request-1", persisted: true)
        XCTAssertEqual(payload["requestId"] as? String, "request-1")
        XCTAssertEqual(payload["persisted"] as? Bool, true)
        let publicJSON = String(data: try JSONSerialization.data(withJSONObject: payload), encoding: .utf8)!
        XCTAssertFalse(publicJSON.contains("fixture-app-password")); XCTAssertFalse(publicJSON.contains("Authorization"))
        XCTAssertFalse(publicJSON.contains("synced")); XCTAssertFalse(wanted.dictionary.keys.contains("password"))
    }
    func testKeyedRevisionsChangeForCredentialEditsAndCannotCrossServiceSessions() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        let identity = try config.value!.identity
        secrets.items[identity.storageKey] = "first-fixture-secret"
        let first = DAVAccountService(configuration: config, credentials: secrets)
        let second = DAVAccountService(configuration: config, credentials: secrets)
        let one = await first.status(), two = await second.status()
        XCTAssertNotEqual(one.revision, two.revision)
        secrets.items[identity.storageKey] = "externally-replaced-fixture-secret"
        let changed = await first.status()
        XCTAssertNotEqual(one.revision, changed.revision)
        await expect(.conflict) { _ = try await first.save(expectedRevision: one.revision!, configuration: config.value!) }
    }
    func testEndpointChangeRequiresExplicitPasswordAndPreservesOldContextOnRejection() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        let identity = try config.value!.identity
        secrets.items[identity.storageKey] = "old-fixture-secret"
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        let new = try configuration(server: "https://other.example")
        await expect(.missingPassword) { _ = try await service.save(expectedRevision: initial.revision!, configuration: new) }
        XCTAssertEqual(config.value?.server, "https://cloud.example/nextcloud")
        XCTAssertEqual(secrets.items[identity.storageKey], "old-fixture-secret")
        let saved = try await service.save(expectedRevision: initial.revision!, configuration: new, applicationPassword: "new-fixture-secret")
        XCTAssertEqual(saved.configuration, new); XCTAssertNil(secrets.items[identity.storageKey])
        XCTAssertEqual(try secrets.read(for: new.identity), "new-fixture-secret")
    }
    func testExplicitPasswordDeletionRequiresDisabledServicesAndKeepsConfiguration() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        let identity = try config.value!.identity
        secrets.items[identity.storageKey] = "fixture-secret"
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        await expect(.invalidConfiguration) { _ = try await service.save(expectedRevision: initial.revision!, configuration: config.value!, clearPassword: true) }
        let disabled = try configuration(active: false)
        let saved = try await service.save(expectedRevision: initial.revision!, configuration: disabled, clearPassword: true)
        XCTAssertEqual(saved.configuration, disabled); XCTAssertEqual(saved.credentialPresent, false); XCTAssertEqual(saved.state, "aus")
        XCTAssertTrue(secrets.items.isEmpty())
    }
    func testFailedConfigurationWriteAndCredentialWriteRollBackCompleteOldContext() async throws {
        for failCredential in [false, true] {
            let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
            config.value = try configuration()
            let old = config.value!, identity = try old.identity
            secrets.items[identity.storageKey] = "old-fixture-secret"
            let service = DAVAccountService(configuration: config, credentials: secrets)
            let initial = await service.status()
            config.failAfterReplaceOnce = !failCredential; secrets.failAfterWriteOnce = failCredential
            do { _ = try await service.save(expectedRevision: initial.revision!, configuration: try configuration(server: "https://other.example"), applicationPassword: "new-fixture-secret"); XCTFail("Expected injected failure") }
            catch { }
            XCTAssertEqual(config.value, old)
            XCTAssertEqual(secrets.items, [identity.storageKey: "old-fixture-secret"])
            let actual = await service.status()
            XCTAssertEqual(actual.revision, initial.revision); XCTAssertEqual(actual.errorCode, "none")
        }
    }
    func testOldCredentialDeletionFailureRestoresBothCredentialsAndOldConfiguration() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        let old = config.value!, oldIdentity = try old.identity
        secrets.items[oldIdentity.storageKey] = "old-fixture-secret"
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        secrets.failAfterDeleteOnce = true
        do { _ = try await service.save(expectedRevision: initial.revision!, configuration: try configuration(server: "https://other.example"), applicationPassword: "new-fixture-secret"); XCTFail("Expected delete failure") }
        catch { }
        XCTAssertEqual(config.value, old); XCTAssertEqual(secrets.items, [oldIdentity.storageKey: "old-fixture-secret"])
    }
    func testFailedInitialSetupRestoresAbsentConfigurationAndNoCredential() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        config.failAfterReplaceOnce = true
        do { _ = try await service.save(expectedRevision: initial.revision!, configuration: try configuration(), applicationPassword: "new-fixture-secret"); XCTFail("Expected failure") }
        catch { }
        XCTAssertNil(config.value); XCTAssertTrue(secrets.items.isEmpty())
    }
    func testUnverifiableRollbackFencesFurtherMutationsAndReportsExplicitFailure() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let initial = await service.status()
        config.failEveryReplace = true
        await expect(.verificationFailed) { _ = try await service.save(expectedRevision: initial.revision!, configuration: try self.configuration(), applicationPassword: "fixture-secret") }
        let failed = await service.status()
        XCTAssertNil(failed.revision); XCTAssertEqual(failed.errorCode, "verification_failed"); XCTAssertNil(failed.credentialPresent)
        await expect(.verificationFailed) { _ = try await service.save(expectedRevision: initial.revision!, configuration: try self.configuration(), applicationPassword: "fixture-secret") }
    }
    func testLockedCredentialAndUnsupportedMailboxNeverPretendToBeConfiguredSuccessfully() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        secrets.locked = true
        let service = DAVAccountService(configuration: config, credentials: secrets)
        let locked = await service.status()
        XCTAssertNil(locked.revision); XCTAssertNil(locked.credentialPresent); XCTAssertEqual(locked.errorCode, "secret_service_unavailable")
        secrets.locked = false
        let initial = await service.status()
        let mailbox = try DAVAccountConfiguration(davAktiv: true, briefkastenAktiv: true, server: "https://cloud.example", benutzer: "person")
        await expect(.unsupportedFeature) { _ = try await service.save(expectedRevision: initial.revision!, configuration: mailbox, applicationPassword: "fixture-secret") }
        XCTAssertTrue(secrets.items.isEmpty())
    }
    func testDiscoveryReturnsRealStableSourcesAndReadOnlyConnectionReceipt() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration()
        secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
        let transport = AccountScriptTransport(discoveryReplies())
        let service = DAVAccountService(configuration: config, credentials: secrets, transport: transport)
        let initial = await service.status()
        let result = try await service.discover(expectedRevision: initial.revision!)
        XCTAssertTrue(result.reachable); XCTAssertFalse(result.partial); XCTAssertEqual(result.status.errorCode, "none")
        XCTAssertTrue(result.status.connectivityChecked); XCTAssertEqual(result.status.calendars.count, 1); XCTAssertEqual(result.status.addressBooks.count, 1)
        XCTAssertEqual(result.status.calendars[0].uid, "nextcloud-calendar:6541706891c0a0615cbaad7ae060941cecf7aec6e453a3ed28f8785050229ae4")
        let receipt = result.connectionTestPayload(requestID: "request-1")
        XCTAssertEqual(receipt["revision"] as? String, initial.revision); XCTAssertEqual(receipt["calendars"] as? Int, 1)
        XCTAssertNil(receipt["synced"]); XCTAssertNil(receipt["persisted"])
        let count = await transport.requestCount(); XCTAssertEqual(count, 4)
    }
    func testDiscoveryAuthenticationFailureAndPartialResultsRemainExplicit() async throws {
        for partial in [false, true] {
            let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
            config.value = try configuration(); secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
            let replies = (partial ? Array(discoveryReplies().prefix(2)) : []) + [BoundedHTTPResponse(status: 401)]
            let service = DAVAccountService(configuration: config, credentials: secrets, transport: AccountScriptTransport(replies))
            let before = await service.status()
            let result = try await service.discover(expectedRevision: before.revision!)
            XCTAssertEqual(result.partial, partial); XCTAssertEqual(result.reachable, partial)
            XCTAssertEqual(result.status.errorCode, "http_401"); XCTAssertEqual(result.status.state, "fehler")
            XCTAssertEqual(result.status.calendars.count, partial ? 1 : 0)
            let after = await service.status(); XCTAssertEqual(before.revision, after.revision)
        }
    }
    func testAccountChangeDuringDiscoveryRejectsLateResultsWithoutTouchingSources() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration(); secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
        let transport = AccountScriptTransport(discoveryReplies(), gate: true)
        let service = DAVAccountService(configuration: config, credentials: secrets, transport: transport)
        let before = await service.status()
        let task = Task { try await service.discover(expectedRevision: before.revision!) }
        await transport.waitUntilEntered()
        _ = try await service.save(expectedRevision: before.revision!, configuration: try configuration(active: false))
        await transport.release()
        await expect(.conflict) { _ = try await task.value }
        XCTAssertEqual(config.value?.davAktiv, false)
    }
    func testStatusReusesOnlyDiscoveryForTheExactCurrentSnapshot() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration(); secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
        let transport = AccountScriptTransport(discoveryReplies())
        let service = DAVAccountService(configuration: config, credentials: secrets, transport: transport)
        let before = await service.status()
        _ = try await service.discover(expectedRevision: before.revision!)
        let cached = await service.status()
        XCTAssertEqual(cached.calendars.count, 1); XCTAssertEqual(cached.addressBooks.count, 1)
        XCTAssertTrue(cached.connectivityChecked); XCTAssertEqual(cached.revision, before.revision)
        let cachedAgain = await service.status()
        XCTAssertEqual(cachedAgain.calendars, cached.calendars)
        let count = await transport.requestCount(); XCTAssertEqual(count, 4)
        _ = try await service.save(expectedRevision: cached.revision!, configuration: try configuration(active: false))
        let disabled = await service.status()
        XCTAssertTrue(disabled.calendars.isEmpty); XCTAssertTrue(disabled.addressBooks.isEmpty)
        XCTAssertFalse(disabled.connectivityChecked); XCTAssertNotEqual(disabled.revision, cached.revision)
    }
    func testExternalCredentialAndConfigurationChangesInvalidateCachedDiscovery() async throws {
        for changeCredential in [false, true] {
            let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
            config.value = try configuration(); let identity = try config.value!.identity
            secrets.items[identity.storageKey] = "fixture-secret"
            let service = DAVAccountService(configuration: config, credentials: secrets,
                transport: AccountScriptTransport(discoveryReplies()))
            let before = await service.status()
            _ = try await service.discover(expectedRevision: before.revision!)
            if changeCredential { secrets.items[identity.storageKey] = "externally-replaced-secret" }
            else { config.value = try configuration(active: false) }
            let changed = await service.status()
            XCTAssertNotEqual(changed.revision, before.revision)
            XCTAssertTrue(changed.calendars.isEmpty); XCTAssertTrue(changed.addressBooks.isEmpty)
            XCTAssertFalse(changed.connectivityChecked)
        }
    }
    func testFailedAndPartialDiscoveryRemainVisibleInPassiveStatus() async throws {
        for partial in [false, true] {
            let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
            config.value = try configuration(); secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
            let replies = (partial ? Array(discoveryReplies().prefix(2)) : []) + [BoundedHTTPResponse(status: 403)]
            let service = DAVAccountService(configuration: config, credentials: secrets, transport: AccountScriptTransport(replies))
            let before = await service.status()
            _ = try await service.discover(expectedRevision: before.revision!)
            let cached = await service.status()
            XCTAssertEqual(cached.errorCode, "http_403"); XCTAssertEqual(cached.state, "fehler")
            XCTAssertTrue(cached.connectivityChecked); XCTAssertEqual(cached.calendars.count, partial ? 1 : 0)
            XCTAssertTrue(cached.addressBooks.isEmpty)
            let payload = cached.payload()
            XCTAssertEqual((payload["kalender"] as? [[String: Any]])?.count, partial ? 1 : 0)
            XCTAssertFalse((payload["fehler"] as? String ?? "").isEmpty)
        }
    }
    func testLockedCredentialsDiscardPreviouslyCachedSourceMetadata() async throws {
        let config = AccountMemoryConfiguration(), secrets = AccountMemoryCredentials()
        config.value = try configuration(); secrets.items[try config.value!.identity.storageKey] = "fixture-secret"
        let service = DAVAccountService(configuration: config, credentials: secrets,
            transport: AccountScriptTransport(discoveryReplies()))
        let before = await service.status()
        _ = try await service.discover(expectedRevision: before.revision!)
        secrets.locked = true
        let locked = await service.status()
        XCTAssertNil(locked.revision); XCTAssertTrue(locked.calendars.isEmpty)
        XCTAssertEqual(locked.errorCode, "secret_service_unavailable")
        secrets.locked = false
        let unlocked = await service.status()
        XCTAssertEqual(unlocked.revision, before.revision)
        XCTAssertTrue(unlocked.calendars.isEmpty); XCTAssertFalse(unlocked.connectivityChecked)
    }
    func testNativeFileStoreKeepsCanonicalSettingsPrivateAndLeavesOrganizerBytesUntouched() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let organizer = directory.appendingPathComponent("organizer.json")
        let original = Data("{\"termine\":[{\"sourceUid\":\"nextcloud-calendar:existing\"}],\"unknown\":true}".utf8)
        try original.write(to: organizer)
        let store = try DAVAccountFileStore(directory: directory)
        XCTAssertNil(try store.read())
        let wanted = try configuration()
        try store.replace(wanted)
        XCTAssertEqual(try store.read(), wanted)
        XCTAssertEqual(Set(try Document.object(String(contentsOf: store.file)).keys), ["kontoArt", "davAktiv", "briefkastenAktiv", "server", "benutzer"])
        let attributes = try FileManager.default.attributesOfItem(atPath: store.file.path)
        XCTAssertEqual((attributes[.posixPermissions] as! NSNumber).intValue & 0o777, 0o600)
        XCTAssertEqual(try Data(contentsOf: organizer), original)
        try store.replace(nil); XCTAssertNil(try store.read()); XCTAssertEqual(try Data(contentsOf: organizer), original)
    }
}
