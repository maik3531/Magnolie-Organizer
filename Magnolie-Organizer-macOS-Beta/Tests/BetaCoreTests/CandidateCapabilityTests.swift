import XCTest
@testable import BetaCore

/// #783: shared UI updates do not implement new native transports or grants.
/// These describe today's adapter; future intentional implementations update it.
final class CandidateCapabilityTests: XCTestCase {
    func testUnimplementedDesktopCommandsCannotBypassTheNativeBoundary() throws {
        for command in ["sync", "notes_original_ready", "notes_original_save_cancel", "notes_setup_prepared",
                        "telefon_ein", "telefon_pairing_bestaetigen", "telefon_kontakte", "telefon_medien_senden",
                        "personal_sync_senden", "personal_sync_gemeinsam_initialisieren", "background_settings_set"] {
            XCTAssertNil(Command(rawValue: command))
            XCTAssertThrowsError(try Request(Document.encode(["cmd": command])))
        }
    }

    func testOrdinarySaveCannotAcquireDesktopSyncAuthority() throws {
        XCTAssertEqual(try Request(#"{"cmd":"speichern","id":1,"text":"{}","baumSyncLauf":null}"#).command, .speichern)
        for field in ["notesOriginalLauf", "kontaktOriginalLauf"] {
            XCTAssertThrowsError(try Request(Document.encode([
                "cmd": "speichern", "id": 1, "text": "{}", field: "untrusted-token"])))
        }
        XCTAssertThrowsError(try Request(#"{"cmd":"speichern","id":1,"text":"{}","baumSyncLauf":{"run":"untrusted"}}"#))
    }
}
