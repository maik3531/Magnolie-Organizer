import XCTest
@testable import BetaCore

final class AirPlayProtocolTests: XCTestCase {
    private func data(_ string: String) -> Data { Data(string.utf8) }

    func testFragmentedStatusIsEmittedOnlyAtNewline() throws {
        var decoder = AirPlayEventDecoder()
        XCTAssertEqual(try decoder.append(data(#"{"protocol":1,"event":"rea"#)), [])
        XCTAssertEqual(try decoder.append(data(#"dy"}"#)), [])
        XCTAssertEqual(try decoder.append(data("\n")), [.ready])
        XCTAssertNoThrow(try decoder.finish())
    }

    func testEveryBoundaryOfAnAuthenticationMessage() throws {
        let bytes = data("{\"protocol\":1,\"event\":\"pin\",\"code\":\"0042\"}\n")
        for cut in 0...bytes.count {
            var decoder = AirPlayEventDecoder()
            let first = try decoder.append(Data(bytes.prefix(cut)))
            let second = try decoder.append(Data(bytes.dropFirst(cut)))
            XCTAssertEqual(first + second, [.pin("0042")], "Split at byte \(cut)")
            XCTAssertNoThrow(try decoder.finish())
        }
    }

    func testMultipleEventsAndUtf8AreNotRawLogs() throws {
        var decoder = AirPlayEventDecoder()
        let lines = [#"{"protocol":1,"event":"ready"}"#,
                     #"{"protocol":1,"event":"pin","code":"1234"}"#,
                     #"{"protocol":1,"event":"video"}"#,
                     #"{"protocol":1,"event":"audio"}"#,
                     #"{"protocol":1,"event":"disconnected"}"#,
                     #"{"protocol":1,"event":"error","code":"service_discovery"}"#]
        XCTAssertEqual(try decoder.append(data(lines.joined(separator: "\n") + "\n")),
                       [.ready, .pin("1234"), .video, .audio, .disconnected, .error("service_discovery")])
        XCTAssertThrowsError(try decoder.append(data("UxPlay: Gerät verbunden\n"))) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .invalidMessage)
        }
    }

    func testRejectsInvalidVersionsTypesUnknownFieldsAndUnboundedContent() {
        let invalid = [#"{"protocol":true,"event":"ready"}"#,
                       #"{"protocol":"1","event":"ready"}"#,
                       #"{"protocol":2,"event":"ready"}"#,
                       #"{"protocol":1.5,"event":"ready"}"#,
                       #"{"protocol":1,"event":"ready","code":"secret"}"#,
                       #"{"protocol":1,"event":"connected"}"#,
                       #"{"protocol":1,"event":"pin","code":1234}"#,
                       #"{"protocol":1,"event":"pin","code":"１２３４"}"#,
                       #"{"protocol":1,"event":"pin","code":"012"}"#,
                       #"{"protocol":1,"event":"pin","code":"12345"}"#,
                       #"{"protocol":1,"event":"pin","code":"1\n34"}"#,
                       #"{"protocol":1,"event":"pin","code":"1234","name":"phone"}"#,
                       #"{"protocol":1,"event":"error","code":"User PIN 1234"}"#,
                       #"{"protocol":1,"event":"error","code":"UPPER"}"#,
                       #"{"protocol":1,"event":"error","code":"/tmp/private"}"#,
                       #"{"protocol":1,"event":"error","code":""}"#,
                       #"{"protocol":1,"event":"error","code":null}"#,
                       #"[1,"ready"]"#, #"null"#, ""]
        for line in invalid {
            var decoder = AirPlayEventDecoder()
            XCTAssertThrowsError(try decoder.append(data(line + "\n"))) {
                XCTAssertEqual($0 as? AirPlayProtocolError, .invalidMessage)
            }
        }
        var decoder = AirPlayEventDecoder()
        let oversizedCode = String(repeating: "a", count: 49)
        XCTAssertThrowsError(try decoder.append(data("{\"protocol\":1,\"event\":\"error\",\"code\":\"\(oversizedCode)\"}\n")))
    }

    func testOversizedFragmentPoisonsStreamAndDoesNotAllocateWholeLine() throws {
        var decoder = AirPlayEventDecoder(maximumLineBytes: 64)
        XCTAssertEqual(try decoder.append(data(String(repeating: " ", count: 64))), [])
        XCTAssertThrowsError(try decoder.append(data(" "))) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .lineTooLong)
        }
        XCTAssertThrowsError(try decoder.append(data("{\"protocol\":1,\"event\":\"ready\"}\n"))) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .decoderFailed)
        }
        decoder.reset()
        XCTAssertEqual(try decoder.append(data("{\"protocol\":1,\"event\":\"ready\"}\n")), [.ready])
    }

    func testExactLineBoundAcceptsNewlineButNotOneMoreByte() throws {
        let line = #"{"protocol":1,"event":"ready"}"#
        var exact = AirPlayEventDecoder(maximumLineBytes: line.utf8.count)
        XCTAssertEqual(try exact.append(data(line + "\n")), [.ready])
        var short = AirPlayEventDecoder(maximumLineBytes: line.utf8.count - 1)
        XCTAssertThrowsError(try short.append(data(line + "\n"))) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .lineTooLong)
        }
    }

    func testEofRejectsTruncatedJsonEvenIfItIsOtherwiseComplete() throws {
        var decoder = AirPlayEventDecoder()
        XCTAssertEqual(try decoder.append(data(#"{"protocol":1,"event":"ready"}"#)), [])
        XCTAssertThrowsError(try decoder.finish()) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .truncatedMessage)
        }
        XCTAssertThrowsError(try decoder.finish()) {
            XCTAssertEqual($0 as? AirPlayProtocolError, .decoderFailed)
        }
    }

    func testInvalidUtf8AndControlBytesFailWithoutEchoingSecrets() {
        for bytes in [Data([0xff, 10]), data("PIN secret\u{0}\n"), data("{\"protocol\":1,\"event\":\"pin\",\"code\":\"1234\"}\u{0}\n")] {
            var decoder = AirPlayEventDecoder()
            XCTAssertThrowsError(try decoder.append(bytes)) {
                XCTAssertEqual($0 as? AirPlayProtocolError, .invalidMessage)
                XCTAssertFalse(String(describing: $0).contains("1234"))
                XCTAssertFalse(String(describing: $0).contains("secret"))
            }
        }
    }
}
