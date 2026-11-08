import Foundation
import CryptoKit
import XCTest
@testable import BetaCore

private final class DispatchURLProtocol: URLProtocol {
    static let lock = NSLock()
    static var bodies: [String: Data] = [:], hanging = Set<String>(), starts: [String: Int] = [:]
    static func add(_ path: String, hanging: Bool) {
        lock.lock(); bodies[path] = Data("synthetic-raw".utf8); starts[path] = 0
        if hanging { self.hanging.insert(path) }; lock.unlock()
    }
    static func count(_ path: String) -> Int { lock.lock(); defer { lock.unlock() }; return starts[path] ?? 0 }
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "dispatch-fixture.invalid" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url!.path
        Self.lock.lock(); Self.starts[path, default: 0] += 1
        let body = Self.bodies[path]!, hang = Self.hanging.contains(path); Self.lock.unlock()
        if hang { return }
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["ETag": "\"specific\"", "Content-Encoding": "identity"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
private final class DispatchCancelProbe: DAVReadOperationCancellation {
    let block: () -> Void
    init(_ block: @escaping () -> Void) { self.block = block }
    func cancel() { block() }
}
private actor DispatchBarrier {
    private var reached = 0, opened = false, failed = false
    private var entries: [UUID: (Int, CheckedContinuation<Void, Error>)] = [:]
    private var releases: [UUID: CheckedContinuation<Void, Error>] = [:]
    private var timers: [UUID: Task<Void, Never>] = [:]
    private func arm(_ id: UUID) {
        timers[id] = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
            await self?.expire(id)
        }
    }
    private func expire(_ id: UUID) {
        guard entries[id] != nil || releases[id] != nil else { return }
        failed = true
        let pending = entries.values.map { $0.1 } + Array(releases.values)
        entries.removeAll(); releases.removeAll()
        for timer in timers.values { timer.cancel() }; timers.removeAll()
        for continuation in pending { continuation.resume(throwing: DAVError.timeout) }
    }
    func wait() async throws {
        guard !failed else { throw DAVError.timeout }
        reached += 1
        let ready = entries.filter { $0.value.0 <= reached }
        for (id, entry) in ready { entries.removeValue(forKey: id); timers.removeValue(forKey: id)?.cancel(); entry.1.resume() }
        if !opened {
            let id = UUID()
            try await withCheckedThrowingContinuation { releases[id] = $0; arm(id) }
        }
    }
    func started(_ count: Int = 1) async throws {
        guard !failed else { throw DAVError.timeout }
        if reached < count {
            let id = UUID()
            try await withCheckedThrowingContinuation { entries[id] = (count, $0); arm(id) }
        }
    }
    func open() {
        guard !failed else { return }
        opened = true
        let waiting = releases; releases.removeAll()
        for (id, item) in waiting { timers.removeValue(forKey: id)?.cancel(); item.resume() }
    }
}
private final class DispatchConfig: DAVAccountConfigurationStore {
    let revisionNamespace = "dispatch-account"
    var value = try! DAVAccountConfiguration(davAktiv: true, server: "https://cloud.example", benutzer: "person")
    func read() throws -> DAVAccountConfiguration? { value }
    func replace(_ configuration: DAVAccountConfiguration?) throws { value = configuration! }
}
private final class DispatchSecrets: DAVCredentialStore {
    var value: String? = "immutable-synthetic-secret"
    func read(for identity: DAVCredentialIdentity) throws -> String? { value }
    func write(_ secret: String, for identity: DAVCredentialIdentity) throws { value = secret }
    func delete(for identity: DAVCredentialIdentity) throws -> Bool { let existed = value != nil; value = nil; return existed }
}
private final class DispatchKeys: DAVSyncJournalKeyStore {
    var existing = false
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        guard existing || allowCreate else { throw DAVSyncJournalError.missingKey }
        let fresh = !existing; existing = true
        return try .init(id: Data(repeating: 3, count: 32), bytes: Data(repeating: 9, count: 32), newlyCreated: fresh)
    }
}
private actor FencedDispatchScript: DispatchFencedHTTPTransport {
    var discovery: [BoundedHTTPResponse]
    var responses: [BoundedHTTPResponse] = []
    var before: DispatchBarrier?, after: DispatchBarrier?
    var beforeAt: Int?, afterAt: Int?, sequence = 0
    var resumes = 0
    var requests: [BoundedHTTPRequest] = []
    init(_ replies: [BoundedHTTPResponse]) { discovery = replies }
    func set(_ responses: [BoundedHTTPResponse], before: DispatchBarrier? = nil, after: DispatchBarrier? = nil, beforeAt: Int? = nil, afterAt: Int? = nil) {
        self.responses = responses; self.before = before; self.after = after
        self.beforeAt = beforeAt; self.afterAt = afterAt; sequence = 0
    }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        guard !discovery.isEmpty else { throw DAVError.invalidResponse }; return discovery.removeFirst()
    }
    func send(_ request: BoundedHTTPRequest, authorization: DAVReadDispatchAuthorization) async throws -> BoundedHTTPResponse {
        requests.append(request)
        guard !responses.isEmpty else { throw DAVError.invalidResponse }
        let response = responses.removeFirst()
        sequence += 1
        let pre = beforeAt == nil || beforeAt == sequence ? before : nil
        let post = afterAt == nil || afterAt == sequence ? after : nil
        if let pre { try await pre.wait() }
        try authorization.start(request) { resumes += 1 }
        if let post { try await post.wait() }
        return response
    }
}

private actor UnfencedDispatchScript: BoundedHTTPTransport {
    var responses: [BoundedHTTPResponse], count = 0
    init(_ responses: [BoundedHTTPResponse]) { self.responses = responses }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        count += 1
        guard !responses.isEmpty else { throw DAVError.invalidResponse }; return responses.removeFirst()
    }
}

final class DAVReadDispatchTests: XCTestCase {
    private func gate(clock: DAVReadClock = .testing(100), expires: TimeInterval = 400) throws -> (DAVAccountBindingSigner, DAVReadLeaseGate) {
        let signer = DAVAccountBindingSigner(namespace: "test-only", key: SymmetricKey(data: Data(repeating: 1, count: 32)), validateJournal: {})
        let gate = DAVReadLeaseGate(signer: signer, expires: expires, clock: clock); try signer.registerReadGate(gate)
        return (signer, gate)
    }
    private func request(_ path: String = UUID().uuidString) -> BoundedHTTPRequest {
        BoundedHTTPRequest(url: URL(string: "https://dispatch-fixture.invalid/" + path)!, headers: ["Authorization": "Basic synthetic-only"], maximumResponseBytes: 1024)
    }
    private func replies() -> [BoundedHTTPResponse] {
        func xml(_ content: String) -> BoundedHTTPResponse { .init(status: 207, body: Data(("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:a='urn:ietf:params:xml:ns:carddav'>" + content + "</d:multistatus>").utf8)) }
        func row(_ href: String, _ props: String) -> String { "<d:response><d:href>\(href)</d:href><d:propstat><d:prop>\(props)</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" }
        return [xml(row("/", "<c:calendar-home-set><d:href>/cal/</d:href></c:calendar-home-set>")),
            xml(row("/cal/selected/", "<d:resourcetype><c:calendar/></d:resourcetype>")),
            xml(row("/", "<a:addressbook-home-set><d:href>/cards/</d:href></a:addressbook-home-set>")), xml("")]
    }
    private func asyncFixture() async throws -> (DAVSyncJournalStore, DAVAccountService, DAVSyncAccountLease, String, DispatchConfig, DispatchSecrets, FencedDispatchScript, DAVReadClock) {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("dispatch-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: root), keys: DispatchKeys())
        let configuration = DispatchConfig(), secrets = DispatchSecrets(), network = FencedDispatchScript(replies()), clock = DAVReadClock.testing(100)
        let service = DAVAccountService(configuration: configuration, credentials: secrets, transport: network, readClock: clock)
        let revision = await service.status().revision!, sources = try await service.discover(expectedRevision: revision)
        let uid = sources.status.calendars[0].uid, signer = try await journal.accountBindingSigner()
        let lease = try await service.pinForSync(expectedRevision: revision, orderedCalendarUIDs: [uid], signer: signer)
        return (journal, service, lease, uid, configuration, secrets, network, clock)
    }
    func testAuthorizationIsExactAndOneShotAndOnlyReadMethodsAreEligible() throws {
        let (_, gate) = try gate(), req = request()
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: req)
        var starts = 0
        try auth.start(req) { starts += 1 }
        XCTAssertThrowsError(try auth.start(req) { starts += 1 }); XCTAssertEqual(starts, 1)
        let changed = BoundedHTTPRequest(url: req.url, headers: ["Authorization": "Basic changed"], maximumResponseBytes: 1024)
        let other = try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: req)
        XCTAssertThrowsError(try other.start(changed) { starts += 1 }); XCTAssertEqual(starts, 1)
        XCTAssertThrowsError(try other.start(req) { starts += 1 })
        for method in ["PUT", "DELETE", "POST"] { XCTAssertThrowsError(try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: .init(url: req.url, method: method))) }
    }
    func testRevocationExpiryAndDeadlineCannotAuthorizeLateOrResurrectedStarts() throws {
        let clock = DAVReadClock.testing(100), (signer, lease) = try gate(clock: clock), req = request()
        let auth = try DAVReadDispatchAuthorization(gate: lease, deadline: 1000, request: req)
        clock.setForTesting(400)
        XCTAssertThrowsError(try auth.start(req) { XCTFail("Expired resume") })
        clock.setForTesting(100)
        XCTAssertThrowsError(try auth.start(req) { XCTFail("Resurrected expired resume") })
        signer.invalidate()
        XCTAssertThrowsError(try auth.start(req) { XCTFail("Revoked signer resume") })
        let (_, fresh) = try gate(clock: clock)
        let timed = try DAVReadDispatchAuthorization(gate: fresh, deadline: 101, request: req)
        clock.setForTesting(101); XCTAssertThrowsError(try timed.start(req) { XCTFail("Read deadline ignored") })
        clock.setForTesting(100); XCTAssertThrowsError(try timed.start(req) { XCTFail("Reused timeout authorization") })
    }
    func testSharedSignerCancellationRunsAfterEveryGateUnlocks() throws {
        let (signer, gate) = try gate(), done = DispatchSemaphore(value: 0)
        let operation = DispatchCancelProbe {
            do { try signer.withReadStartGate {}; XCTFail("Revoked signer remained usable inside cancellation") }
            catch { XCTAssertEqual(error as? DAVAccountLeaseError, .signerUnavailable) }
            do { try gate.checkState(); XCTFail("Revoked lease remained usable inside cancellation") }
            catch { XCTAssertEqual(error as? DAVAccountLeaseError, .invalidLease) }
            done.signal()
        }
        _ = try gate.register(operation)
        DispatchQueue.global().async { signer.invalidate() }
        XCTAssertEqual(done.wait(timeout: .now() + 3), .success)
    }
    func testActualURLSessionSuspendedTaskCannotResumeAfterLeaseOrJournalRevocation() async throws {
        for revokeSigner in [false, true] {
            let (signer, gate) = try gate(), req = request(), probe = DAVHTTPStartProbe(holdBeforeStart: true)
            DispatchURLProtocol.add(req.url.path, hanging: false)
            let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: req)
            let transport = URLSessionBoundedTransport(startProbe: probe, protocolClasses: [DispatchURLProtocol.self])
            let work = Task { try await transport.send(req, authorization: auth) }
            defer { work.cancel() }
            let suspended = await Task.detached { probe.waitUntilSuspended() }.value; XCTAssertTrue(suspended)
            if revokeSigner { signer.invalidate() } else { gate.revoke() }; probe.allowStart()
            do { _ = try await work.value; XCTFail("Revoked suspended URLSession task started") } catch { }
            XCTAssertEqual(probe.resumes, 0); XCTAssertEqual(DispatchURLProtocol.count(req.url.path), 0)
        }
    }
    func testActualURLSessionStartWinsOnceThenJournalRevocationCancelsInFlight() async throws {
        let (signer, gate) = try gate(), req = request(), probe = DAVHTTPStartProbe(holdBeforeStart: false)
        DispatchURLProtocol.add(req.url.path, hanging: true)
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: req)
        let transport = URLSessionBoundedTransport(startProbe: probe, protocolClasses: [DispatchURLProtocol.self])
        let work = Task { try await transport.send(req, authorization: auth) }
        defer { work.cancel() }
        let resumed = await Task.detached { probe.waitUntilResumed() }.value; XCTAssertTrue(resumed)
        signer.invalidate()
        do { _ = try await work.value; XCTFail("Revoked in-flight read returned") } catch { }
        XCTAssertEqual(probe.resumes, 1); XCTAssertLessThanOrEqual(DispatchURLProtocol.count(req.url.path), 1)
    }
    func testActualURLSessionExpiryWhileSuspendedDeniesResume() async throws {
        let clock = DAVReadClock.testing(100), (_, gate) = try gate(clock: clock), req = request(), probe = DAVHTTPStartProbe(holdBeforeStart: true)
        DispatchURLProtocol.add(req.url.path, hanging: false)
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 500, request: req)
        let transport = URLSessionBoundedTransport(startProbe: probe, protocolClasses: [DispatchURLProtocol.self])
        let work = Task { try await transport.send(req, authorization: auth) }
        defer { work.cancel() }
        let suspended = await Task.detached { probe.waitUntilSuspended() }.value; XCTAssertTrue(suspended)
        clock.setForTesting(400); probe.allowStart()
        do { _ = try await work.value; XCTFail("Expired URLSession read returned") } catch { }
        XCTAssertEqual(probe.resumes, 0)
    }
    func testLeasedGETReturnsRawDataAndREPORTHasPinnedSourceWithoutWrites() async throws {
        let (journal, service, lease, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let body = Data([0, 255, 13, 10])
        await network.set([.init(status: 200, headers: ["ETag": "\"raw\""], body: body)])
        guard case .present(let read) = try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) else { return XCTFail("Expected raw GET") }
        XCTAssertEqual(read.bytes, body)
        let xml = "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'><d:response><d:href>/cal/selected/item.ics</d:href><d:propstat><d:prop><d:getetag>\"raw\"</d:getetag><c:calendar-data>BEGIN:VCALENDAR</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"
        await network.set([.init(status: 207, body: Data(xml.utf8))])
        let report = try await service.readReport(lease, sourceUID: uid)
        XCTAssertEqual(report.source.uid, uid); XCTAssertEqual(report.resources.count, 1)
        let requests = await network.requests
        XCTAssertEqual(requests.map(\.method), ["GET", "REPORT"])
        XCTAssertEqual(requests[0].headers["Authorization"], requests[1].headers["Authorization"])
    }
    func testActorPrecheckToTransportStartRaceDeniesAfterValidMutation() async throws {
        let (journal, service, lease, uid, configuration, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let barrier = DispatchBarrier()
        await network.set([.init(status: 404)], before: barrier)
        let work = Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) }
        defer { work.cancel() }
        try await barrier.started()
        let status = await service.status(); _ = try await service.save(expectedRevision: status.revision!, configuration: configuration.value)
        await barrier.open()
        do { _ = try await work.value; XCTFail("Revoked actor-to-start gap returned evidence") } catch { }
        let starts = await network.resumes; XCTAssertEqual(starts, 0)
    }
    func testNoncooperativeResponseAfterReleaseIsDiscardedAndReadSlotIsReleased() async throws {
        let (journal, service, lease, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let barrier = DispatchBarrier()
        await network.set([.init(status: 404)], after: barrier)
        let work = Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) }
        defer { work.cancel() }
        try await barrier.started(); await service.release(lease); await barrier.open()
        do { _ = try await work.value; XCTFail("Released read published stale response") } catch { }
        let starts = await network.resumes; XCTAssertEqual(starts, 1)
    }
    func testRedirectRequiresFreshContextAndInvalidScopeNeverGetsSecondStart() async throws {
        let (journal, service, lease, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        await network.set([.init(status: 302, headers: ["Location": "/cal/other/item.ics"]), .init(status: 404)])
        do { _ = try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!); XCTFail("Cross-source redirect followed") } catch { }
        let starts = await network.resumes; XCTAssertEqual(starts, 1)
        // Same active lease can make a later independent valid read: terminal slots are released.
        await network.set([.init(status: 404)])
        _ = try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!)
    }
    func testPerLeaseCapacityAndReadDeadlineConsumeNoAdditionalStart() async throws {
        let (journal, service, lease, uid, _, _, network, clock) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let barrier = DispatchBarrier()
        await network.set([.init(status: 404)], after: barrier)
        let work = Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) }
        defer { work.cancel() }
        try await barrier.started()
        do { _ = try await service.readReport(lease, sourceUID: uid); XCTFail("Per-lease concurrent read accepted") }
        catch { XCTAssertEqual(error as? DAVAccountLeaseError, .capacity) }
        clock.setForTesting(161); await barrier.open()
        do { _ = try await work.value; XCTFail("Read deadline ignored by noncooperative transport") }
        catch { XCTAssertEqual(error as? DAVError, .timeout) }
        let starts = await network.resumes; XCTAssertEqual(starts, 1)
    }
    func testUnfencedTransportAndPublicCustomClockCannotSilentlyDispatch() async throws {
        let (journal, _, _, _, configuration, secrets, _, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let signer = try await journal.accountBindingSigner()
        let plain = UnfencedDispatchScript(replies())
        let unfenced = DAVAccountService(configuration: configuration, credentials: secrets, transport: plain)
        let revision = await unfenced.status().revision!, discovery = try await unfenced.discover(expectedRevision: revision), uid = discovery.status.calendars[0].uid
        let lease = try await unfenced.pinForSync(expectedRevision: revision, orderedCalendarUIDs: [uid], signer: signer)
        do { _ = try await unfenced.readReport(lease, sourceUID: uid); XCTFail("Unfenced transport accepted") }
        catch { XCTAssertEqual(error as? DAVAccountLeaseError, .unsupportedTransport) }
        let count = await plain.count; XCTAssertEqual(count, 4)
        let scripted = FencedDispatchScript(replies())
        let custom = DAVAccountService(configuration: configuration, credentials: secrets, transport: scripted, monotonicTime: { 100 })
        let customRevision = await custom.status().revision!, customSources = try await custom.discover(expectedRevision: customRevision), customUID = customSources.status.calendars[0].uid
        let customLease = try await custom.pinForSync(expectedRevision: customRevision, orderedCalendarUIDs: [customUID], signer: signer)
        try await custom.revalidate(customLease) // Existing metadata-only custom-clock behavior remains.
        do { _ = try await custom.readReport(customLease, sourceUID: customUID); XCTFail("Arbitrary clock called under start gates") }
        catch { XCTAssertEqual(error as? DAVAccountLeaseError, .unsupportedClock) }
        let starts = await scripted.resumes; XCTAssertEqual(starts, 0)
    }
    func testAccountReadCapacityIsFourAndAllTerminalSlotsAreReleased() async throws {
        let (journal, service, first, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let revision = await service.status().revision!, signer = try await journal.accountBindingSigner()
        var leases = [first]
        for _ in 0..<4 { leases.append(try await service.pinForSync(expectedRevision: revision, orderedCalendarUIDs: [uid], signer: signer)) }
        let barrier = DispatchBarrier(); await network.set(Array(repeating: .init(status: 404), count: 4), after: barrier)
        let works = leases.prefix(4).map { lease in Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) } }
        defer { for work in works { work.cancel() } }
        try await barrier.started(4)
        do { _ = try await service.readReport(leases[4], sourceUID: uid); XCTFail("Fifth active read accepted") }
        catch { XCTAssertEqual(error as? DAVAccountLeaseError, .capacity) }
        await barrier.open()
        for work in works { _ = try await work.value }
        await network.set([.init(status: 404)])
        _ = try await service.readResource(leases[4], sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!)
        let starts = await network.resumes; XCTAssertEqual(starts, 5)
    }
    func testRedirectSecondStartIsRevokedAndCredentialsAreNeverSubstituted() async throws {
        let (journal, service, lease, uid, configuration, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let barrier = DispatchBarrier()
        await network.set([.init(status: 302, headers: ["Location": "/cal/selected/%69tem.ics"]), .init(status: 404)], before: barrier, beforeAt: 2)
        let work = Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) }
        defer { work.cancel() }
        try await barrier.started()
        let revision = await service.status().revision!
        _ = try await service.save(expectedRevision: revision, configuration: configuration.value, applicationPassword: "new-synthetic-secret")
        await barrier.open()
        do { _ = try await work.value; XCTFail("Redirect continued with changed credentials") } catch { }
        let requests = await network.requests, starts = await network.resumes
        XCTAssertEqual(starts, 1); XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[0].headers["Authorization"], requests[1].headers["Authorization"])
    }
    func testCancellationAfterNoncooperativeStartCannotPublishReadResult() async throws {
        let (journal, service, lease, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        let barrier = DispatchBarrier(); await network.set([.init(status: 404)], after: barrier)
        let work = Task { try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!) }
        defer { work.cancel() }
        try await barrier.started(); work.cancel(); await barrier.open()
        do { _ = try await work.value; XCTFail("Cancelled noncooperative read returned") } catch is CancellationError { }
        let starts = await network.resumes; XCTAssertEqual(starts, 1)
    }

    func testScopedREPORTValidatesRawRowsBeforeResolutionAndKeepsDistinctUnicodeFilenames() async throws {
        let href = URL(string: "https://cloud.example/cal/caf%C3%A9/")!
        let source = DAVCollection(uid: DAVClient.sourceID(kind: .calendar, href: href), name: "Fixture", href: href, kind: .calendar, supportsVtodo: true, syncToken: nil)
        func response(_ references: [String]) -> BoundedHTTPResponse {
            let rows = references.map { reference in "<d:response><d:href>\(reference)</d:href><d:propstat><d:prop><d:getetag>\"specific\"</d:getetag><c:calendar-data>BEGIN:VCALENDAR</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" }.joined()
            return .init(status: 207, body: Data(("<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>" + rows + "</d:multistatus>").utf8))
        }
        for row in ["../caf%C3%A9/item.ics", "/cal/caf%C3%A9/%2e%2e/caf%C3%A9/item.ics", "%2fitem.ics", "%5citem.ics", "/cal/cafe\u{301}/item.ics"] {
            let script = UnfencedDispatchScript([response([row])])
            let client = try DAVClient(server: "https://cloud.example", username: "fixture", password: "synthetic", transport: script)
            do { _ = try await client.reportScoped(in: source); XCTFail("Raw out-of-scope REPORT row accepted") } catch { }
            let count = await script.count; XCTAssertEqual(count, 1)
        }
        let duplicate = UnfencedDispatchScript([response(["item.ics", "%69tem.ics"])])
        let duplicateClient = try DAVClient(server: "https://cloud.example", username: "fixture", password: "synthetic", transport: duplicate)
        do { _ = try await duplicateClient.reportScoped(in: source); XCTFail("Byte alias duplicate accepted") } catch { }
        let separate = UnfencedDispatchScript([response(["caf%C3%A9.ics", "cafe%CC%81.ics"])])
        let client = try DAVClient(server: "https://cloud.example", username: "fixture", password: "synthetic", transport: separate)
        let resources = try await client.reportScoped(in: source)
        XCTAssertEqual(resources.count, 2)
        XCTAssertNotEqual(try DAVClient.recoveryPath(resources[0].href.absoluteString), try DAVClient.recoveryPath(resources[1].href.absoluteString))
        let redirect = UnfencedDispatchScript([.init(status: 302, headers: ["Location": "/cal/cafe\u{301}/"]), response([])])
        let redirectClient = try DAVClient(server: "https://cloud.example", username: "fixture", password: "synthetic", transport: redirect)
        do { _ = try await redirectClient.reportScoped(in: source); XCTFail("Collection-byte redirect accepted") } catch { }
        let count = await redirect.count; XCTAssertEqual(count, 1)
    }
    func testActualURLSessionCancellationWhileSuspendedCannotResume() async throws {
        let (_, gate) = try gate(), req = request(), probe = DAVHTTPStartProbe(holdBeforeStart: true)
        DispatchURLProtocol.add(req.url.path, hanging: false)
        let authorization = try DAVReadDispatchAuthorization(gate: gate, deadline: 160, request: req)
        let transport = URLSessionBoundedTransport(startProbe: probe, protocolClasses: [DispatchURLProtocol.self])
        let work = Task { try await transport.send(req, authorization: authorization) }
        defer { work.cancel() }
        let suspended = await Task.detached { probe.waitUntilSuspended() }.value; XCTAssertTrue(suspended)
        work.cancel(); probe.allowStart()
        do { _ = try await work.value; XCTFail("Cancelled suspended task returned") } catch is CancellationError { }
        XCTAssertEqual(probe.resumes, 0)
    }

    func testOversizedSelectedSourceUIDRejectsBeforeAwaitDispatchAndDoesNotLeakSlot() async throws {
        let (journal, service, lease, uid, _, _, network, _) = try await asyncFixture()
        defer { withExtendedLifetime(journal) {} }
        for invalid in ["", String(repeating: "x", count: 1025), String(repeating: "é", count: 513)] {
            do { _ = try await service.readReport(lease, sourceUID: invalid); XCTFail("Oversized REPORT source accepted") }
            catch { XCTAssertEqual(error as? DAVAccountLeaseError, .invalidSelection) }
            do { _ = try await service.readResource(lease, sourceUID: invalid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!); XCTFail("Oversized GET source accepted") }
            catch { XCTAssertEqual(error as? DAVAccountLeaseError, .invalidSelection) }
        }
        let before = await network.resumes; XCTAssertEqual(before, 0)
        await network.set([.init(status: 404)])
        _ = try await service.readResource(lease, sourceUID: uid, href: URL(string: "https://cloud.example/cal/selected/item.ics")!)
        let after = await network.resumes; XCTAssertEqual(after, 1)
    }

}
