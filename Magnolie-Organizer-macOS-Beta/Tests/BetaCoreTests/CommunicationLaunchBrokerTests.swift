import XCTest
@testable import BetaCore

@MainActor private final class MockCommunicationSystem: CommunicationSystemOpening {
    var handler: URL? = URL(fileURLWithPath: "/Applications/Mock Handler.app")
    var resolved: [URL] = []
    var opened: [(URL, URL)] = []
    var replies: [(Error?) -> Void] = []
    func application(for destination: URL) -> URL? { resolved.append(destination); return handler }
    func open(_ destination: URL, with application: URL, completion: @escaping (Error?) -> Void) {
        opened.append((destination, application)); replies.append(completion)
    }
}
final class CommunicationLaunchBrokerTests: XCTestCase {
    @MainActor func testMockHandlerAcceptanceOnlyAndNoAutomaticSendClaim() async throws {
        let system = MockCommunicationSystem()
        XCTAssertTrue(system.resolved.isEmpty); XCTAssertTrue(system.opened.isEmpty)
        let live = CommunicationLaunchBroker(system: system)
        let target = try CommunicationLaunchPolicy.target(command: "mail", fields: ["email": "a@example.org", "name": "Ada"])
        let completed = expectation(description: "mock application accepted open")
        var response: [String: Any]?
        live.begin(target, isCurrent: { true }) { response = $0; completed.fulfill() }
        XCTAssertEqual(system.resolved, [target.url]); XCTAssertEqual(system.opened.count, 1)
        XCTAssertNil(response, "No optimistic success before the OS completion")
        system.replies[0](nil)
        await fulfillment(of: [completed], timeout: 2)
        XCTAssertEqual(response?["ok"] as? Bool, true)
        XCTAssertEqual(response?["name"] as? String, "Mock Handler")
        for key in ["sent", "gesendet", "zugestellt", "delivered", "routeCompleted"] { XCTAssertNil(response?[key]) }
    }
    @MainActor func testMissingInvalidHandlerAndClosedDocumentNeverOpen() throws {
        let target = try CommunicationLaunchPolicy.target(command: "mail", fields: ["email": "a@example.org", "name": ""])
        for handler in [nil, URL(string: "https://example.org/App.app"), URL(fileURLWithPath: "/bin/sh")] {
            let system = MockCommunicationSystem(); system.handler = handler
            let broker = CommunicationLaunchBroker(system: system); var reply: [String: Any]?
            broker.begin(target, isCurrent: { true }) { reply = $0 }
            XCTAssertEqual(reply?["ok"] as? Bool, false); XCTAssertTrue(system.opened.isEmpty)
        }
        let system = MockCommunicationSystem()
        let live = CommunicationLaunchBroker(system: system)
        live.begin(target, isCurrent: { false }) { _ in XCTFail("Stale document callback") }
        XCTAssertTrue(system.resolved.isEmpty); XCTAssertTrue(system.opened.isEmpty)
    }
    @MainActor func testReplacementCancellationAndDocumentFenceSuppressLateCompletion() async throws {
        let target = try CommunicationLaunchPolicy.target(command: "mail", fields: ["email": "a@example.org", "name": ""])
        let system = MockCommunicationSystem()
        let live = CommunicationLaunchBroker(system: system)
        var count = 0, current = true
        live.begin(target, isCurrent: { current }) { _ in count += 1 }
        live.begin(target, isCurrent: { current }) { _ in count += 1 }
        system.replies[0](nil) // Superseded native attempt.
        current = false; system.replies[1](nil) // Locked/replaced document.
        await Task.yield(); await Task.yield()
        XCTAssertEqual(count, 0)
        current = true
        live.begin(target, isCurrent: { current }) { _ in count += 1 }
        live.cancel(); system.replies[2](nil)
        await Task.yield(); await Task.yield()
        XCTAssertEqual(count, 0)
    }
    @MainActor func testSystemErrorIsNotAccepted() async throws {
        let system = MockCommunicationSystem()
        let live = CommunicationLaunchBroker(system: system)
        let target = try CommunicationLaunchPolicy.target(command: "mail", fields: ["email": "a@example.org", "name": ""])
        let completed = expectation(description: "system rejected open")
        var reply: [String: Any]?
        live.begin(target, isCurrent: { true }) { reply = $0; completed.fulfill() }
        system.replies[0](BetaError("Injected failure"))
        await fulfillment(of: [completed], timeout: 2)
        XCTAssertEqual(reply?["ok"] as? Bool, false)
    }
}
