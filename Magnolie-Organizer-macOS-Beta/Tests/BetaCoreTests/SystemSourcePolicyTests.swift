import XCTest
@testable import BetaCore

final class SystemSourcePolicyTests: XCTestCase {
    func testNativeSourceBridgeContractRejectsAmbiguousFields() throws {
        XCTAssertEqual(try Request(#"{"cmd":"eds_status"}"#).command, .eds_status)
        XCTAssertEqual(try Request(#"{"cmd":"eds_status","requestId":"source-1"}"#).command, .eds_status)
        for kind in SystemSourcePolicy.Kind.allCases {
            let request = try Request(Document.encode(["cmd": "macos_systemzugriff", "art": kind.rawValue, "requestId": "consent-1"]))
            XCTAssertEqual(request.command, .macos_systemzugriff)
        }
        for text in [#"{"cmd":"macos_systemzugriff","art":"events"}"#,
                     #"{"cmd":"macos_systemzugriff","art":"passwords","requestId":"x"}"#,
                     #"{"cmd":"macos_systemzugriff","art":"events","requestId":""}"#,
                     #"{"cmd":"eds_status","requestId":1}"#,
                     #"{"cmd":"eds_status","requestId":"x","path":"/tmp/private"}"#] {
            XCTAssertThrowsError(try Request(text))
        }
    }
    func testOpaqueIdentifiersCannotCrossSourceKinds() throws {
        for kind in SystemSourcePolicy.Kind.allCases {
            let id = "账户:/calendar?opaque=ä"
            let uid = SystemSourcePolicy.uid(kind, id)
            XCTAssertEqual(try SystemSourcePolicy.identifier(uid, kind: kind), id)
            XCTAssertThrowsError(try SystemSourcePolicy.identifier(uid + "=", kind: kind))
            for other in SystemSourcePolicy.Kind.allCases where other != kind {
                XCTAssertThrowsError(try SystemSourcePolicy.identifier(uid, kind: other))
            }
        }
        XCTAssertThrowsError(try SystemSourcePolicy.identifier("macos-events:", kind: .events))
    }
    func testRevisionRejectsConcurrentEditsAndMissingBaseline() throws {
        let revision = try SystemSourcePolicy.revision(["title": "A", "modified": 1])
        XCTAssertEqual(revision, try SystemSourcePolicy.revision(["modified": 1, "title": "A"]))
        try SystemSourcePolicy.requireRevision(revision, actual: revision)
        XCTAssertThrowsError(try SystemSourcePolicy.requireRevision("", actual: revision))
        XCTAssertThrowsError(try SystemSourcePolicy.requireRevision(revision,
            actual: SystemSourcePolicy.revision(["title": "B", "modified": 1])))
    }
    func testDeniedRestrictedUnrequestedAndWriteOnlyAreNotReadAccess() throws {
        for kind in SystemSourcePolicy.Kind.allCases {
            try SystemSourcePolicy.requireAccess("authorized", kind: kind)
            for state in ["denied", "restricted", "not_determined", "write_only", "limited", ""] {
                XCTAssertThrowsError(try SystemSourcePolicy.requireAccess(state, kind: kind))
            }
        }
    }
    func testReadCancellationAndExpiredDeadlineRejectResults() throws {
        let active = SystemSourceReadControl(timeout: 20)
        try active.check()
        active.cancel()
        XCTAssertThrowsError(try active.check()) { XCTAssertTrue($0 is CancellationError) }
        let expired = SystemSourceReadControl(timeout: 0)
        XCTAssertThrowsError(try expired.check()) { XCTAssertFalse($0 is CancellationError) }
    }
    func testCalendarFetchCannotBeUnboundedOrReversed() throws {
        let start = Date(timeIntervalSince1970: 0)
        try SystemSourcePolicy.requireWindow(start: start, end: start.addingTimeInterval(86400))
        for end in [start, start.addingTimeInterval(-1), start.addingTimeInterval(366 * 86400 * 5)] {
            XCTAssertThrowsError(try SystemSourcePolicy.requireWindow(start: start, end: end))
        }
    }
}
