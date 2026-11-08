import Foundation
import XCTest
@testable import BetaCore

private final class UnicodeIdentityJournalKeys: DAVSyncJournalKeyStore {
    private var prior: DAVSyncJournalKey?
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        if let prior { return prior }
        guard allowCreate else { throw DAVSyncJournalError.missingKey }
        let key = try DAVSyncJournalKey(id: Data(repeating: 5, count: 32), bytes: Data(repeating: 9, count: 32))
        prior = key
        return try DAVSyncJournalKey(id: key.id, bytes: key.bytes, newlyCreated: true)
    }
}

/// Refs #455. Byte identity changes no title/display semantics and opens no network.
final class OpaqueUTF8IdentityTests: XCTestCase {
    private let nfc = "caf\u{e9}", nfd = "cafe\u{301}"
    private let collection = URL(string: "https://calendar.example.test/cal/")!
    private func calendar(_ body: String) -> Data { Data(("BEGIN:VCALENDAR\nVERSION:2.0\n" + body + "END:VCALENDAR\n").utf8) }
    private func event(_ uid: String, title: String = "Title") -> String {
        "BEGIN:VEVENT\nUID:\(uid)\nDTSTART:20260101T120000Z\nSUMMARY:\(title)\nX-OPAQUE:keep\nEND:VEVENT\n"
    }
    private func source(_ href: URL? = nil) -> DAVCollection {
        let url = href ?? collection
        return DAVCollection(uid: DAVClient.sourceID(kind: .calendar, href: url), name: "Synthetic", href: url,
            kind: .calendar, supportsVtodo: true, syncToken: nil)
    }
    func testRawIdentityIsLexicalAndDoesNotChangeSwiftDisplayComparison() {
        XCTAssertEqual(nfc, nfd, "Swift display-text equality remains unchanged")
        XCTAssertNotEqual(OpaqueUTF8Identity(nfc), OpaqueUTF8Identity(nfd))
        XCTAssertEqual(Set([OpaqueUTF8Identity(nfc), OpaqueUTF8Identity(nfd)]).count, 2)
        XCTAssertEqual(OpaqueUTF8Identity(nfc).bytes, Data([0x63,0x61,0x66,0xc3,0xa9]))
        XCTAssertEqual([OpaqueUTF8Identity("z"), OpaqueUTF8Identity("aa")].sorted().map(\.bytes), [Data("aa".utf8), Data("z".utf8)])
    }
    func testCompositeFramingAndRepresentationDomainsCannotCollide() throws {
        XCTAssertNotEqual(OpaqueUTF8Identity(parts: ["a\0b", "c"]), OpaqueUTF8Identity(parts: ["a", "b\0c"]))
        XCTAssertNotEqual(OpaqueUTF8Identity(parts: ["", "a"]), OpaqueUTF8Identity(parts: ["a"]))
        let composite = OpaqueUTF8Identity(parts: ["ab", "c"])
        let raw = OpaqueUTF8Identity(try XCTUnwrap(String(data: composite.bytes, encoding: .utf8)))
        XCTAssertEqual(composite.bytes, raw.bytes)
        XCTAssertNotEqual(composite, raw)
        XCTAssertEqual(Set([composite, raw]).count, 2)
        XCTAssertLessThan(OpaqueUTF8Identity(parts: ["same", "aa"]), OpaqueUTF8Identity(parts: ["same", "z"]), "Composite ordering compares component UTF8, not framed lengths")
    }
    func testResourcePatchSeparatesUidAndRidAndKeepsUntouchedBytes() throws {
        typealias Patch = ICalendarResourcePatch
        let original = calendar(event(nfc, title: "NFC original") + event(nfd, title: "NFD original"))
        XCTAssertEqual(try Patch.keys(from: original).count, 2)
        let changed = try Patch.apply(original: original,
            replacements: [.init(key: .init(kind: "VEVENT", uid: nfd), calendar: calendar(event(nfd, title: "NFD changed")))])
        let text = try XCTUnwrap(String(data: changed.data, encoding: .utf8))
        XCTAssertTrue(text.contains(event(nfc, title: "NFC original")))
        XCTAssertTrue(text.contains("SUMMARY:NFD changed"))
        let removed = try Patch.apply(original: original, deletions: [.init(kind: "VEVENT", uid: nfd)])
        XCTAssertEqual(try Patch.keys(from: removed.data), [.init(kind: "VEVENT", uid: nfc)])
        let first = Patch.Key(kind: "VEVENT", uid: "series", recurrenceID: "RECURRENCE-ID;TZID=Custom/\(nfc):20260101T120000")
        let second = Patch.Key(kind: "VEVENT", uid: "series", recurrenceID: "RECURRENCE-ID;TZID=Custom/\(nfd):20260101T120000")
        XCTAssertNotEqual(first, second); XCTAssertEqual(Set([first, second]).count, 2)
        XCTAssertNotEqual(Patch.Key(kind: "VEVENT", uid: "series"), Patch.Key(kind: "VEVENT", uid: "series", recurrenceID: ""))
        XCTAssertThrowsError(try Patch.keys(from: calendar(event(nfc) + event(nfc))))
    }
    func testResourcePatchPreservesDistinctLexicalTimezoneDefinitions() throws {
        func zone(_ id: String, offset: String) -> String {
            "BEGIN:VTIMEZONE\nTZID:Custom/\(id)\nBEGIN:STANDARD\nDTSTART:19700101T000000\nTZOFFSETFROM:\(offset)\nTZOFFSETTO:\(offset)\nEND:STANDARD\nEND:VTIMEZONE\n"
        }
        let first = zone(nfc, offset: "+0000"), second = zone(nfd, offset: "+0100")
        let original = calendar(first + second + event("event"))
        let replacement = calendar(second + event("event", title: "Changed"))
        let result = try ICalendarResourcePatch.apply(original: original,
            replacements: [.init(key: .init(kind: "VEVENT", uid: "event"), calendar: replacement)])
        let text = try XCTUnwrap(String(data: result.data, encoding: .utf8))
        XCTAssertTrue(text.contains(first)); XCTAssertTrue(text.contains(second))
    }
    func testPlannerDoesNotStripDistinctUnicodeTimezoneAsExistingDefinition() throws {
        func zone(_ id: String) -> String {
            "BEGIN:VTIMEZONE\nTZID:Custom/\(id)\nBEGIN:STANDARD\nDTSTART:19700101T000000\nTZOFFSETFROM:+0000\nTZOFFSETTO:+0000\nEND:STANDARD\nEND:VTIMEZONE\n"
        }
        let generated = calendar(zone(nfd) + event("event"))
        let actual = DAVSyncPlanner.stripExistingZones(generated, definitions: [zone(nfc).split(separator: "\n").map(String.init)])
        XCTAssertNotNil(actual.range(of: Data(("TZID:Custom/" + nfd + "\r\n").utf8)))
        let identical = DAVSyncPlanner.stripExistingZones(generated, definitions: [zone(nfd).split(separator: "\n").map(String.init)])
        XCTAssertNil(identical.range(of: Data(("TZID:Custom/" + nfd + "\r\n").utf8)))
    }
    func testSnapshotDistinguishesResourcePathsAndRejectsEquivalentLookingOtherSource() throws {
        let first = URL(string: "https://calendar.example.test/cal/caf%C3%A9.ics")!
        let second = URL(string: "https://calendar.example.test/cal/cafe%CC%81.ics")!
        let values = [DAVResource(href: first, etag: "\"one\"", data: String(decoding: calendar(event("one")), as: UTF8.self)),
                      DAVResource(href: second, etag: "\"two\"", data: String(decoding: calendar(event("two")), as: UTF8.self))]
        XCTAssertEqual(try DAVCalendarSnapshot.decode(source: source(), resources: values, displayTimeZone: "UTC").resources.count, 2)
        let sameWireUID = [values[0], DAVResource(href: second, etag: "\"two\"", data: values[0].data)]
        XCTAssertThrowsError(try DAVCalendarSnapshot.decode(source: source(), resources: sameWireUID, displayTimeZone: "UTC")) {
            XCTAssertEqual($0 as? DAVCalendarSnapshotError, .ambiguousWireUID)
        }
        let selected = source(URL(string: "https://calendar.example.test/cal/caf%C3%A9/")!)
        let outside = DAVResource(href: URL(string: "https://calendar.example.test/cal/cafe%CC%81/item.ics")!, etag: "\"one\"", data: values[0].data)
        XCTAssertThrowsError(try DAVCalendarSnapshot.decode(source: selected, resources: [outside], displayTimeZone: "UTC")) {
            XCTAssertEqual($0 as? DAVCalendarSnapshotError, .resourceOutsideCollection)
        }
    }
    func testPlannerLookupAndFinalizationKeepBothOpaqueLocalUids() throws {
        let chosen = source(), href = collection.appendingPathComponent("mixed.ics")
        func row(_ uid: String) -> DAVCalendarSnapshot.Record {
            .init(kind: .appointment, sourceUID: chosen.uid, href: href, etag: "\"one\"",
                wireKey: .init(kind: "VEVENT", uid: uid), value: ["uid": uid, "titel": "Title", "datum": "2026-01-01", "zeit": "12:00", "endZeit": "12:30"])
        }
        let rows = [row(nfc), row(nfd)]
        let resource = DAVCalendarSnapshot.Resource(href: href, etag: "\"one\"", bytes: calendar(event(nfc) + event(nfd)),
            wireKeys: rows.map(\.wireKey), calendarProperties: [], sourceSHA256: "", records: rows)
        let remote = DAVCalendarSnapshot.Result(source: chosen, resources: [resource], appointments: rows, tasks: [], anniversaries: [], byteCount: resource.bytes.count, projectedByteCount: 0)
        let plan = try DAVSyncPlanner.plan(snapshot: remote, local: .init(appointments: [], tasks: [], anniversaries: []), baseline: nil,
            restoreAdditive: false, syncEpoch: "epoch", createdAt: Date(timeIntervalSince1970: 1_700_000_000))
        XCTAssertTrue(plan.operations.isEmpty)
        let final = try plan.finalize(acknowledgements: [])
        XCTAssertEqual(Set(final.state.appointments.compactMap { ($0["uid"] as? String).map(OpaqueUTF8Identity.init) }).count, 2)
        XCTAssertEqual(final.baseline.entries.count, 2)
    }
    private func binding(_ sourceHref: URL, book: String = "book") -> DAVSyncJournalStore.Binding {
        let input = Data("input".utf8)
        return .init(accountIdentity: String(repeating: "a", count: 64), accountRevision: String(repeating: "b", count: 64),
            server: URL(string: "https://calendar.example.test/")!, bookIdentity: book, bookGeneration: "generation", syncEpoch: "epoch",
            inputDigest: DAVSyncJournalStore.digest(input), sources: [.init(uid: "calendar", href: sourceHref, supportsVtodo: true)])
    }
    func testJournalBindingOpaqueBookAndSourceValuesDoNotNormalize() {
        XCTAssertNotEqual(binding(collection, book: nfc), binding(collection, book: nfd))
        XCTAssertNotEqual(DAVSyncJournalStore.Source(uid: nfc, href: collection, supportsVtodo: true),
                          DAVSyncJournalStore.Source(uid: nfd, href: collection, supportsVtodo: true))
    }
    func testJournalRejectsUnicodeEquivalentSiblingCollectionBeforePermit() async throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("unicode-journal-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let journal = try DAVSyncJournalStore(files: DAVSyncJournalFiles(profileDirectory: directory), keys: UnicodeIdentityJournalKeys())
        let sourceHref = URL(string: "https://calendar.example.test/cal/caf%C3%A9/")!
        func frozen(_ href: String) -> DAVSyncJournalStore.PreparedRun {
            .init(id: String(repeating: "c", count: 64), binding: binding(sourceHref), input: Data("input".utf8), plan: Data("plan".utf8),
                operations: [.init(id: String(repeating: "d", count: 64), sourceUID: "calendar", method: .update,
                    href: URL(string: href)!, ifMatch: "\"before\"", body: Data("body".utf8))])
        }
        do { _ = try await journal.prepare(frozen("https://calendar.example.test/cal/cafe%CC%81/item.ics")); XCTFail("Outside source accepted") }
        catch { XCTAssertEqual(error as? DAVSyncJournalError, .invalidInput) }
        let valid = frozen("https://calendar.example.test/cal/caf%C3%A9/item.ics")
        let handle = try await journal.prepare(valid)
        let permit = try await journal.beginAttempt(handle, operationID: valid.operations[0].id, currentBinding: valid.binding)
        XCTAssertEqual(permit.operation.href.absoluteString, valid.operations[0].href.absoluteString)
    }
}
