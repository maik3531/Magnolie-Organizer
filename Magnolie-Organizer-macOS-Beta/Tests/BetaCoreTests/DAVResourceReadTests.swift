import Foundation
import XCTest
@testable import BetaCore

private final class ResourceScript: BoundedHTTPTransport {
    var requests: [BoundedHTTPRequest] = []
    var responses: [BoundedHTTPResponse]
    var failure: DAVError?
    init(_ responses: [BoundedHTTPResponse]) { self.responses = responses }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests.append(request)
        if let failure { throw failure }
        guard !responses.isEmpty else { throw DAVError.invalidResponse }; return responses.removeFirst()
    }
}
private actor ResourceStartBarrier {
    private var opened = false
    private var waiter: CheckedContinuation<Void, Never>?
    func wait() async { if !opened { await withCheckedContinuation { waiter = $0 } } }
    func open() { opened = true; waiter?.resume(); waiter = nil }
}
private actor ResourceNonCooperativeTransport: BoundedHTTPTransport {
    private var response: CheckedContinuation<BoundedHTTPResponse, Never>?
    private var startWaiter: CheckedContinuation<Void, Never>?
    private var sent = false
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        await withCheckedContinuation { continuation in
            response = continuation; sent = true; startWaiter?.resume(); startWaiter = nil
        }
    }
    func started() async { if !sent { await withCheckedContinuation { startWaiter = $0 } } }
    func release() { response?.resume(returning: .init(status: 200, headers: ["ETag": "\"after\""], body: Data("raw".utf8))); response = nil }
}

final class DAVResourceReadTests: XCTestCase {
    private let collectionURL = URL(string: "https://cloud.example/cal/people/personal/")!
    private let itemURL = URL(string: "https://cloud.example/cal/people/personal/item.ics")!
    private func collection(_ href: URL? = nil, kind: DAVKind = .calendar, uid: String? = nil) -> DAVCollection {
        let href = href ?? collectionURL
        return .init(uid: uid ?? DAVClient.sourceID(kind: kind, href: href), name: "Synthetic", href: href, kind: kind, supportsVtodo: true, syncToken: nil)
    }
    private func client(_ transport: any BoundedHTTPTransport) throws -> DAVClient {
        try DAVClient(server: "https://cloud.example/nextcloud", username: "synthetic", password: "fixture-only", transport: transport)
    }
    private func expect(_ expected: DAVError, _ operation: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await operation(); XCTFail("Expected resource-read rejection", file: file, line: line) }
        catch { XCTAssertEqual(error as? DAVError, expected, file: file, line: line) }
    }
    func testExactAndDifferentRawBytesAreReturnedWithoutInferringWriteRecovery() async throws {
        let frozen = Data([0, 255, 13, 10, 0xc3, 0xa4])
        for body in [frozen, Data("different\n".utf8), Data()] {
            let transport = ResourceScript([.init(status: 200, headers: ["ETag": " \"specific\" ", "Content-Encoding": "identity"], body: body)])
            guard case .present(let resource) = try await client(transport).getResource(href: itemURL, in: collection()) else { return XCTFail("Expected present resource") }
            XCTAssertEqual(resource.bytes, body); XCTAssertEqual(resource.etag, " \"specific\" ")
            XCTAssertEqual(resource.binding.sourceUID, collection().uid)
            XCTAssertEqual(resource.binding.resourcePathBytes, Data("/cal/people/personal/item.ics".utf8))
            let request = transport.requests[0]
            XCTAssertEqual(request.method, "GET"); XCTAssertTrue(request.body.isEmpty)
            XCTAssertEqual(request.headers["Accept-Encoding"], "identity"); XCTAssertEqual(request.headers["Cache-Control"], "no-cache, no-store")
            XCTAssertNil(request.headers["If-Match"]); XCTAssertNil(request.headers["If-None-Match"])
            XCTAssertEqual(request.maximumResponseBytes, DAVClient.itemLimit); XCTAssertLessThanOrEqual(request.timeout, 60)
        }
    }
    func test404IsExplicitBoundAbsenceAndNotAnETagOrWriteAcknowledgement() async throws {
        let transport = ResourceScript([.init(status: 404)])
        guard case .absent(let binding) = try await client(transport).getResource(href: itemURL, in: collection()) else { return XCTFail("Expected explicit absence") }
        XCTAssertEqual(binding.resourcePathBytes, Data("/cal/people/personal/item.ics".utf8))
        XCTAssertEqual(transport.requests.count, 1)
    }
    func testAuthConflictAndUnexpectedStatusRemainExplicitErrors() async throws {
        for (status, error) in [(401, DAVError.unauthorized), (403, .forbidden), (409, .conflict(status: 409)), (412, .conflict(status: 412)), (206, .httpStatus(206)), (304, .httpStatus(304))] {
            let transport = ResourceScript([.init(status: status)])
            await expect(error) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection()) }
            XCTAssertEqual(transport.requests.count, 1)
        }
    }
    func testMissingWildcardMalformedAndWeakETagsNeverBecomeStrongEvidence() async throws {
        for tag in [nil, "", "*", " * ", "\t*\t", "unquoted", "\"bad\"quote\"", "\"line\"\n", String(repeating: "x", count: 8193)] as [String?] {
            let transport = ResourceScript([.init(status: 200, headers: tag.map { ["ETag": $0] } ?? [:])])
            await expect(.missingETag) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection()) }
        }
        for tag in ["W/\"weak\"", " W/\"weak\" "] {
            let transport = ResourceScript([.init(status: 200, headers: ["ETag": tag])])
            await expect(.weakETag) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection()) }
        }
        let quotedStar = ResourceScript([.init(status: 200, headers: ["ETag": "\"*\""])])
        guard case .present(let resource) = try await client(quotedStar).getResource(href: itemURL, in: collection()) else { return XCTFail("Quoted star is a specific ETag") }
        XCTAssertEqual(resource.etag, "\"*\"")
    }
    func testUnexpectedContentEncodingCannotMasqueradeAsExactFrozenBytes() async throws {
        for encoding in ["gzip", "br", "identity, gzip", ""] {
            let transport = ResourceScript([.init(status: 200, headers: ["ETag": "\"specific\"", "Content-Encoding": encoding], body: Data("already decompressed".utf8))])
            await expect(.unexpectedContentEncoding) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection()) }
        }
    }
    func testInitialUnsafeOriginScopeRawTraversalAndSourceMismatchNeverSendAuth() async throws {
        for href in ["https://other.example/cal/people/personal/item.ics", "https://cloud.example/cal/other/item.ics", "https://cloud.example/cal/people/personalish/item.ics", "https://cloud.example/cal/people/personal/../personal/item.ics", "https://cloud.example/cal/people/personal/%2e%2e/personal/item.ics", "https://cloud.example/cal/people/personal/%2fitem.ics", "https://cloud.example/cal/people/personal/%5citem.ics", "https://user:secret@cloud.example/cal/people/personal/item.ics", "https://cloud.example/cal/people/personal/item.ics?token=secret"] {
            let transport = ResourceScript([])
            do { _ = try await client(transport).getResource(href: URL(string: href)!, in: collection()); XCTFail("Unsafe scope accepted") } catch { }
            XCTAssertTrue(transport.requests.isEmpty)
        }
        let transport = ResourceScript([])
        await expect(.resourceScopeRejected) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection(uid: "unbound-source")) }
        XCTAssertTrue(transport.requests.isEmpty)
    }
    func testRedirectsValidateRawReferenceScopeAndSameResourceBeforeSecondAuthRequest() async throws {
        for location in ["https://other.example/cal/people/personal/item.ics", "/cal/other/item.ics", "sibling.ics", "../personal/item.ics", "%2e%2e/personal/item.ics", "%2fitem.ics", "item.ics?token=secret"] {
            let transport = ResourceScript([.init(status: 302, headers: ["Location": location]), .init(status: 404)])
            do { _ = try await client(transport).getResource(href: itemURL, in: collection()); XCTFail("Unsafe redirect accepted") } catch { }
            XCTAssertEqual(transport.requests.count, 1)
        }
        let valid = ResourceScript([.init(status: 307, headers: ["Location": "https://CLOUD.example:443/cal/people/personal/%69tem.ics"]), .init(status: 200, headers: ["ETag": "\"after\""], body: Data("raw".utf8))])
        guard case .present(let result) = try await client(valid).getResource(href: itemURL, in: collection()) else { return XCTFail("Expected same-identity redirect") }
        XCTAssertEqual(valid.requests.count, 2); XCTAssertEqual(result.binding.resourcePathBytes, Data("/cal/people/personal/item.ics".utf8))
        XCTAssertNotNil(valid.requests[1].headers["Authorization"])
    }
    func testNFCAndNFDFileNamesAreDifferentResourceIdentitiesDespiteSwiftStringEquality() async throws {
        let nfc = "caf\u{e9}.ics", nfd = "cafe\u{301}.ics"
        XCTAssertEqual(nfc, nfd); XCTAssertNotEqual(Data(nfc.utf8), Data(nfd.utf8))
        let requested = URL(string: "https://cloud.example/cal/people/personal/caf%C3%A9.ics")!
        for location in ["cafe%CC%81.ics", "cafe\u{301}.ics", "https://cloud.example/cal/people/personal/cafe\u{301}.ics"] {
            let transport = ResourceScript([.init(status: 302, headers: ["Location": location]), .init(status: 404)])
            await expect(.resourceScopeRejected) { _ = try await self.client(transport).getResource(href: requested, in: self.collection()) }
            XCTAssertEqual(transport.requests.count, 1)
        }
    }
    func testOversizedHrefCollectionAndRawLocationAreRejectedBeforeParsingOrDispatch() async throws {
        let oversized = "https://cloud.example/cal/people/personal/" + String(repeating: "x", count: 16_385)
        let transport = ResourceScript([])
        await expect(.resourceScopeRejected) { _ = try await self.client(transport).getResource(href: URL(string: oversized)!, in: self.collection()) }
        XCTAssertTrue(transport.requests.isEmpty)
        await expect(.resourceScopeRejected) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection(URL(string: oversized + "/")!)) }
        XCTAssertTrue(transport.requests.isEmpty)
        for location in [String(repeating: "x", count: 16_385), String(repeating: "é", count: 8193)] {
            let redirect = ResourceScript([.init(status: 302, headers: ["Location": location]), .init(status: 404)])
            await expect(.resourceScopeRejected) { _ = try await self.client(redirect).getResource(href: self.itemURL, in: self.collection()) }
            XCTAssertEqual(redirect.requests.count, 1)
        }
    }
    func testByteBudgetBoundaryAndInvalidLimitsAreEnforced() async throws {
        let boundary = ResourceScript([.init(status: 200, headers: ["ETag": "\"after\""], body: Data([1, 2, 3]))])
        _ = try await client(boundary).getResource(href: itemURL, in: collection(), maximumBytes: 3)
        XCTAssertEqual(boundary.requests[0].maximumResponseBytes, 3)
        let over = ResourceScript([.init(status: 200, headers: ["ETag": "\"after\""], body: Data([1, 2, 3, 4]))])
        await expect(.responseTooLarge) { _ = try await self.client(over).getResource(href: self.itemURL, in: self.collection(), maximumBytes: 3) }
        for limit in [0, -1, DAVClient.itemLimit + 1] {
            let transport = ResourceScript([])
            await expect(.invalidConfiguration) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection(), maximumBytes: limit) }
            XCTAssertTrue(transport.requests.isEmpty)
        }
    }
    func testCancellationBeforeDispatchNeverSendsRequest() async throws {
        let transport = ResourceScript([]), barrier = ResourceStartBarrier(), client = try client(transport), source = collection(), href = itemURL
        let work = Task { await barrier.wait(); return try await client.getResource(href: href, in: source) }
        work.cancel(); await barrier.open()
        do { _ = try await work.value; XCTFail("Cancelled read returned evidence") } catch is CancellationError { }
        XCTAssertTrue(transport.requests.isEmpty)
    }
    func testCancelledNonCooperativeResponseNeverReturnsEvidence() async throws {
        let transport = ResourceNonCooperativeTransport(), client = try client(transport), source = collection(), href = itemURL
        let work = Task { try await client.getResource(href: href, in: source) }
        await transport.started(); work.cancel(); await transport.release()
        do { _ = try await work.value; XCTFail("Cancelled response returned evidence") } catch is CancellationError { }
    }
    func testTransportTimeoutRemainsFailureWithoutFurtherRequests() async throws {
        let transport = ResourceScript([]); transport.failure = .timeout
        await expect(.timeout) { _ = try await self.client(transport).getResource(href: self.itemURL, in: self.collection()) }
        XCTAssertEqual(transport.requests.count, 1)
    }
}
