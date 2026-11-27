import XCTest
@testable import BetaCore

final class AirPlaySessionTests: XCTestCase {
    func testPassiveAvailabilityDoesNotStartReceiver() {
        var session = AirPlaySession(available: false)
        XCTAssertEqual(session.phase, .unavailable)
        XCTAssertFalse(session.isRunning)
        XCTAssertFalse(session.canStart)
        XCTAssertThrowsError(try session.beginStart()) {
            XCTAssertEqual($0 as? AirPlayFailure, .unavailable)
        }
        XCTAssertTrue(session.setAvailability(true))
        XCTAssertEqual(session.phase, .idle)
        XCTAssertNil(session.token)
        XCTAssertTrue(session.canStart)
        XCTAssertNil(session.requestStop())
    }

    func testLaunchIsNotReadinessAndReadinessIsNotMedia() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        XCTAssertEqual(session.phase, .starting)
        XCTAssertTrue(session.isRunning)
        XCTAssertFalse(session.receivingVideo)
        XCTAssertFalse(session.receivingAudio)
        XCTAssertTrue(session.receive(.ready, token: token))
        XCTAssertEqual(session.phase, .ready)
        XCTAssertFalse(session.receivingVideo)
        XCTAssertFalse(session.receivingAudio)
        XCTAssertTrue(session.receive(.video, token: token))
        XCTAssertEqual(session.phase, .receiving)
        XCTAssertTrue(session.receivingVideo)
        XCTAssertFalse(session.receivingAudio)
        XCTAssertTrue(session.receive(.audio, token: token))
        XCTAssertTrue(session.receivingAudio)
        XCTAssertFalse(session.receive(.ready, token: token))
        XCTAssertEqual(session.phase, .receiving)
    }

    func testPinCanArriveDuringStartupAndClearsOnMediaAndDisconnect() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        XCTAssertTrue(session.receive(.pin("0042"), token: token))
        XCTAssertEqual(session.pin, "0042")
        XCTAssertEqual(session.phase, .starting)
        session.receive(.ready, token: token)
        XCTAssertEqual(session.pin, "0042")
        session.receive(.audio, token: token)
        XCTAssertNil(session.pin)
        session.receive(.pin("5678"), token: token)
        session.receive(.disconnected, token: token)
        XCTAssertEqual(session.phase, .ready)
        XCTAssertNil(session.pin)
        XCTAssertFalse(session.receivingVideo)
        XCTAssertFalse(session.receivingAudio)
        XCTAssertTrue(session.isRunning)
    }

    func testLateCallbacksCannotReviveStoppedReceiver() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        session.receive(.pin("1234"), token: token)
        XCTAssertEqual(session.requestStop(), token)
        XCTAssertEqual(session.phase, .stopping)
        XCTAssertNil(session.pin)
        for event in [AirPlayEvent.ready, .pin("5678"), .video, .audio, .disconnected, .error("network_start")] {
            XCTAssertFalse(session.receive(event, token: token))
        }
        XCTAssertFalse(session.startupTimedOut(token: token))
        XCTAssertFalse(session.fail(.protocolViolation, token: token))
        XCTAssertEqual(session.phase, .stopping)
        XCTAssertTrue(session.processExited(token: token, exitStatus: 15))
        XCTAssertEqual(session.phase, .idle)
        XCTAssertNil(session.failure)
        XCTAssertNil(session.token)
    }

    func testEarlierSessionCallbacksCannotChangeReplacementSession() throws {
        var session = AirPlaySession(available: true)
        let earlier = try session.beginStart()
        session.requestStop()
        session.processExited(token: earlier, exitStatus: 0)
        let current = try session.beginStart()
        XCTAssertNotEqual(earlier, current)
        XCTAssertFalse(session.receive(.ready, token: earlier))
        XCTAssertFalse(session.receive(.pin("1234"), token: earlier))
        XCTAssertFalse(session.processExited(token: earlier, exitStatus: 1))
        XCTAssertFalse(session.startupTimedOut(token: earlier))
        XCTAssertFalse(session.fail(.launchFailed, token: earlier))
        XCTAssertEqual(session.token, current)
        XCTAssertEqual(session.phase, .starting)
        XCTAssertNil(session.pin)
        XCTAssertTrue(session.receive(.ready, token: current))
    }

    func testRejectsOverlappingStartsIncludingWhileStoppingOrFailed() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        XCTAssertThrowsError(try session.beginStart())
        XCTAssertFalse(session.setAvailability(false))
        session.fail(.protocolViolation, token: token)
        XCTAssertThrowsError(try session.beginStart())
        XCTAssertTrue(session.isRunning)
        session.requestStop()
        XCTAssertThrowsError(try session.beginStart())
        session.processExited(token: token, exitStatus: 0)
        XCTAssertEqual(session.phase, .failed)
        XCTAssertNoThrow(try session.beginStart())
    }

    func testUnexpectedZeroExitNeverSignalsSuccess() throws {
        for ready in [false, true] {
            var session = AirPlaySession(available: true)
            let token = try session.beginStart()
            if ready { session.receive(.ready, token: token) }
            XCTAssertTrue(session.processExited(token: token, exitStatus: 0))
            XCTAssertEqual(session.phase, .failed)
            XCTAssertEqual(session.failure, .unexpectedExit(0))
            XCTAssertFalse(session.isRunning)
            XCTAssertTrue(session.canStart)
        }
    }

    func testStartupDeadlineCannotFailReadyOrNewSession() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        XCTAssertTrue(session.startupTimedOut(token: token))
        XCTAssertEqual(session.failure, .startupTimeout)
        session.requestStop()
        session.processExited(token: token, exitStatus: 15)
        let next = try session.beginStart()
        XCTAssertFalse(session.startupTimedOut(token: token))
        session.receive(.ready, token: next)
        XCTAssertFalse(session.startupTimedOut(token: next))
        XCTAssertNil(session.failure)
    }

    func testFailureClearsSensitiveStateAndKeepsFirstCauseThroughExit() throws {
        var session = AirPlaySession(available: true)
        let token = try session.beginStart()
        session.receive(.ready, token: token)
        session.receive(.video, token: token)
        session.receive(.pin("1234"), token: token)
        XCTAssertTrue(session.receive(.error("registration_store"), token: token))
        XCTAssertEqual(session.phase, .failed)
        XCTAssertNil(session.pin)
        XCTAssertFalse(session.receivingVideo)
        XCTAssertFalse(session.fail(.protocolViolation, token: token))
        session.requestStop()
        session.processExited(token: token, exitStatus: 9)
        XCTAssertEqual(session.phase, .failed)
        XCTAssertEqual(session.failure, .receiverError("registration_store"))
        _ = try session.beginStart()
        XCTAssertNil(session.failure)
        XCTAssertEqual(session.phase, .starting)
    }

    func testPrematureMediaAndInvalidTypedPinFailClosed() throws {
        for event in [AirPlayEvent.video, .audio, .disconnected, .pin("１２３４"), .pin("12345")] {
            var session = AirPlaySession(available: true)
            let token = try session.beginStart()
            XCTAssertTrue(session.receive(event, token: token))
            XCTAssertEqual(session.phase, .failed)
            XCTAssertEqual(session.failure, .protocolViolation)
            XCTAssertNil(session.pin)
            XCTAssertFalse(session.receivingAudio)
            XCTAssertFalse(session.receivingVideo)
        }
    }

    func testErrorDescriptionsNeverExposeHelperMessagesOrPin() {
        XCTAssertEqual(AirPlayFailure.receiverError("1234 secret /private/data").description,
                       "The AirPlay receiver reported an error.")
        XCTAssertEqual(AirPlayFailure.unexpectedExit(-1234).description,
                       "The AirPlay receiver stopped unexpectedly.")
    }
}
