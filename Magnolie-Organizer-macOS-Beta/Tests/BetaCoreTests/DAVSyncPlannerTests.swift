import Foundation
import XCTest
@testable import BetaCore

final class DAVSyncPlannerTests: XCTestCase {
    typealias Planner = DAVSyncPlanner
    private let url = URL(string: "https://calendar.example.test/cal/")!
    private let epoch = "fixture-epoch"
    private let time = Date(timeIntervalSince1970: 1_793_491_200)
    private func source(tasks: Bool = true) -> DAVCollection {
        DAVCollection(uid: DAVClient.sourceID(kind: .calendar, href: url), name: "Fixture", href: url,
            kind: .calendar, supportsVtodo: tasks, syncToken: nil)
    }
    private func event(_ uid: String = "event-one", title: String = "Original") -> String {
        "BEGIN:VEVENT\nUID:\(uid)\nDTSTART:20260328T100000Z\nSUMMARY:\(title)\nX-OPAQUE:keep-event\nEND:VEVENT\n"
    }
    private func task(_ uid: String = "task-one", title: String = "Task") -> String {
        "BEGIN:VTODO\nUID:\(uid)\nDUE:20260329T120000Z\nSUMMARY:\(title)\nX-OPAQUE:keep-task\nEND:VTODO\n"
    }
    private func anniversary(_ title: String = "Birthday") -> String {
        "BEGIN:VEVENT\nUID:anniversary\nDTSTART;VALUE=DATE:20000203\nRRULE:FREQ=YEARLY\nSUMMARY:\(title)\nX-MAGNOLIE-JAHRESTAG-TYP:birthday\nEND:VEVENT\n"
    }
    private func snapshot(_ body: String, etag: String = "\"v1\"", tasks: Bool = true) throws -> DAVCalendarSnapshot.Result {
        let resources = body.isEmpty ? [] : [DAVResource(href: url.appendingPathComponent("mixed.ics"), etag: etag,
            data: "BEGIN:VCALENDAR\nVERSION:2.0\nX-CALENDAR-OPAQUE:preserve\n" + body + "END:VCALENDAR\n")]
        return try DAVCalendarSnapshot.decode(context: try CalendarTestContext.make(), source: source(tasks: tasks), resources: resources, displayTimeZone: "UTC")
    }
    private func state(_ original: Planner.LocalState, appointments: [[String: Any]]? = nil,
                       tasks: [[String: Any]]? = nil, anniversaries: [[String: Any]]? = nil, deletions: [Planner.Deletion]? = nil) -> Planner.LocalState {
        Planner.LocalState(appointments: appointments ?? original.appointments, tasks: tasks ?? original.tasks,
            anniversaries: anniversaries ?? original.anniversaries, deletions: deletions ?? original.deletions)
    }
    private func plan(_ snapshot: DAVCalendarSnapshot.Result, _ state: Planner.LocalState, _ baseline: Planner.Baseline?,
                      restore: Bool = false) throws -> Planner.Plan {
        try Planner.plan(context: try CalendarTestContext.make(), snapshot: snapshot, local: state, baseline: baseline, restoreAdditive: restore, syncEpoch: epoch, createdAt: time)
    }
    private func seed(_ snapshot: DAVCalendarSnapshot.Result) throws -> Planner.Finalized {
        try plan(snapshot, .init(appointments: [], tasks: [], anniversaries: []), nil).finalize(acknowledgements: [])
    }
    private func ack(_ plan: Planner.Plan, etag: String = "\"v2\"") -> [Planner.Acknowledgement] {
        plan.operations.map { .init(operationID: $0.id, href: $0.href, status: $0.kind == .create ? 201 : 204,
            etag: $0.kind == .delete ? nil : etag) }
    }
    private func expect(_ expected: DAVSyncPlannerError, action: () throws -> Void, file: StaticString = #filePath, line: UInt = #line) {
        do { try action(); XCTFail("Expected planner rejection", file: file, line: line) }
        catch let error as DAVSyncPlannerError { XCTAssertEqual(error, expected, file: file, line: line) }
        catch { XCTFail("Unexpected error type: \(type(of: error))", file: file, line: line) }
    }
    func testCanonicalNativeAndReleasedLinuxFingerprintVectors() throws {
        let file = Bundle.module.url(forResource: "dav-sync-baseline-vectors", withExtension: "json", subdirectory: "Fixtures")!
        let root = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        XCTAssertEqual(root["linuxSourceCommit"] as? String, "067c38934b539943d8e1720abafd8a80b401d797")
        for fixture in root["cases"] as! [[String: Any]] {
            let kind = DAVCalendarSnapshot.Kind(rawValue: fixture["kind"] as! String)!, value = fixture["input"] as! [String: Any]
            XCTAssertEqual(try DAVSyncBaseline.hash(value, kind: kind), fixture["nativeHash"] as? String, fixture["name"] as! String)
            if let expected = fixture["linuxHash"] as? String { XCTAssertEqual(try DAVSyncBaseline.linuxCompatibilityHash(value, kind: kind), expected) }
        }
    }
    func testBaselineIgnoresTransportBookMetadataButDetectsRawAndVisibleChanges() throws {
        let original = try snapshot(event()).appointments[0].value
        let hash = try DAVSyncBaseline.hash(original, kind: .appointment)
        var metadata = original; metadata["id"] = "other"; metadata["geaendert"] = 123; metadata["davEtag"] = "\"other\""; metadata["sync"] = true
        XCTAssertEqual(try DAVSyncBaseline.hash(metadata, kind: .appointment), hash)
        metadata["titel"] = "Changed"
        XCTAssertNotEqual(try DAVSyncBaseline.hash(metadata, kind: .appointment), hash)
        metadata = original; metadata["icsRoundtrip"] = ["X-OPAQUE:changed"]
        XCTAssertNotEqual(try DAVSyncBaseline.hash(metadata, kind: .appointment), hash)
    }
    func testDefaultNormalizationDoesNotFabricateChangesAndCanonicalJSONUsesLiteralKeyOrder() throws {
        let original = try snapshot(task()).tasks![0].value
        let hash = try DAVSyncBaseline.hash(original, kind: .task)
        var normalized=original
        normalized["icsTimezones"]=[] as [String];normalized["icsStatus"]="";normalized["icsSequence"]=0
        normalized["icsRangeOverrides"]=[] as [[String]];normalized["personen"]=[] as [String]
        normalized["erinnerungsMinute"]=480;normalized["wiederholung"]=["art":"none","bis":""]
        XCTAssertEqual(try DAVSyncBaseline.hash(normalized,kind:.task),hash)
        XCTAssertEqual(String(data:try DAVSyncBaseline.canonicalJSON(["a2":"two","a10":"ten","Z":"upper","ä":"unicode"]),encoding:.utf8),
                       "{\"Z\":\"upper\",\"a10\":\"ten\",\"a2\":\"two\",\"ä\":\"unicode\"}")
    }
    func testFirstRunAndRestoreAreAdditiveAndPreserveExplicitDeletionIntents() throws {
        let remote = try snapshot(event() + task() + anniversary())
        let deletion = Planner.Deletion(domain: .appointment, sourceUID: source().uid, key: .init(kind: "VEVENT", uid: "event-one"),
            href: url.appendingPathComponent("mixed.ics"), etag: "\"v1\"", syncEpoch: epoch)
        let local = Planner.LocalState(appointments: [], tasks: [], anniversaries: [], deletions: [deletion])
        let first = try plan(remote, local, nil)
        XCTAssertTrue(first.operations.isEmpty); XCTAssertEqual(first.quarantinedDeletions, 1)
        XCTAssertEqual(first.preview.appointments.count, 1); XCTAssertEqual(first.preview.tasks.count, 1); XCTAssertEqual(first.preview.anniversaries.count, 1)
        XCTAssertEqual(first.preview.deletions.count, 1)
        let seeded = try seed(remote)
        let restored = try plan(remote, local, seeded.baseline, restore: true)
        XCTAssertTrue(restored.operations.isEmpty); XCTAssertEqual(restored.preview.deletions.count, 1)
        XCTAssertNil(first.preview.appointments[0]["syncQuellen"])
        let finalized = try first.finalize(acknowledgements: [])
        XCTAssertEqual(finalized.state.appointments[0]["sync"] as? Bool, true)
        XCTAssertEqual(finalized.baseline.entries.count, 3)
    }
    func testLocalEditPatchesOnlyItsComponentAndAllSiblingETagsAdvanceAfterAck() throws {
        let before = try snapshot(event() + task()), saved = try seed(before)
        var local = saved.state.appointments; local[0]["titel"] = "Changed"
        let result = try plan(before, state(saved.state, appointments: local), saved.baseline)
        XCTAssertEqual(result.operations.count, 1); XCTAssertEqual(result.operations[0].kind, .update)
        XCTAssertEqual(result.operations[0].expectedETag, "\"v1\"")
        let bytes = result.operations[0].bytes!, text = String(data: bytes, encoding: .utf8)!
        XCTAssertTrue(text.contains("SUMMARY:Changed")); XCTAssertTrue(text.contains(task()))
        XCTAssertTrue(text.contains("X-CALENDAR-OPAQUE:preserve\n"))
        XCTAssertEqual(try ICalendarImport.decode(bytes, context: try CalendarTestContext.make(), displayTimeZone: "UTC").tasks.count, 1)
        let final = try result.finalize(acknowledgements: ack(result))
        XCTAssertEqual(final.state.appointments[0]["davEtag"] as? String, "\"v2\"")
        XCTAssertEqual(final.state.tasks[0]["davEtag"] as? String, "\"v2\"")
        XCTAssertTrue(final.baseline.entries.allSatisfy { $0.etag == "\"v2\"" })
    }
    func testFreshRemoteEditReplacesKnownFieldsAndKeepsUnknownLocalMetadata() throws {
        let original = try snapshot(event()), seeded = try seed(original)
        var local = seeded.state.appointments; local[0]["futureOpaque"] = ["keep": "unchanged"]
        let changed = try snapshot(event(title: "Remote changed"), etag: "\"remote-v2\"")
        let result = try plan(changed, state(seeded.state, appointments: local), seeded.baseline)
        XCTAssertTrue(result.operations.isEmpty); XCTAssertEqual(result.preview.appointments[0]["titel"] as? String, "Remote changed")
        XCTAssertEqual((result.preview.appointments[0]["futureOpaque"] as? [String: String])?["keep"], "unchanged")
    }
    func testConcurrentEditsPreserveDeterministicConflictCopyAndRemoteOriginal() throws {
        let original = try snapshot(event()), seeded = try seed(original)
        var local = seeded.state.appointments; local[0]["titel"] = "Local changed"
        let changed = try snapshot(event(title: "Remote changed"), etag: "\"remote-v2\"")
        let one = try plan(changed, state(seeded.state, appointments: local), seeded.baseline)
        let two = try plan(changed, state(seeded.state, appointments: local), seeded.baseline)
        XCTAssertEqual(one.conflictCopies, 1); XCTAssertEqual(one.preview.appointments.count, 2)
        XCTAssertTrue(one.operations.isEmpty)
        let copied = one.preview.appointments.first { $0["titel"] as? String == "Local changed" }!
        XCTAssertEqual(copied["uid"] as? String, two.preview.appointments.first { $0["titel"] as? String == "Local changed" }?["uid"] as? String)
        XCTAssertNotEqual(copied["uid"] as? String, "event-one"); XCTAssertNil(copied["syncQuellen"])
        XCTAssertTrue(one.preview.appointments.contains { $0["titel"] as? String == "Remote changed" })
    }
    func testProviderReclassificationPreservesOldTypedRecordAsConflictAndImportsActualType() throws {
        let original=try snapshot(anniversary()),saved=try seed(original)
        let changed=try snapshot(event("anniversary",title:"Now an ordinary appointment"),etag:"\"v2\"")
        let result=try plan(changed,saved.state,saved.baseline)
        XCTAssertEqual(result.conflictCopies,1);XCTAssertTrue(result.operations.isEmpty)
        XCTAssertEqual(result.preview.appointments.count,1);XCTAssertEqual(result.preview.anniversaries.count,1)
        XCTAssertEqual(result.preview.appointments[0]["titel"] as? String,"Now an ordinary appointment")
        XCTAssertNil(result.preview.appointments[0]["name"])
        XCTAssertEqual(result.preview.anniversaries[0]["name"] as? String,"Birthday")
        XCTAssertNotEqual(result.preview.anniversaries[0]["uid"] as? String,"anniversary")
    }
    func testSourceScopedRemoteDeletionKeepsOtherProviderBindingAndUnknownFields() throws {
        let original = try snapshot(event()), seeded = try seed(original)
        var local = seeded.state.appointments
        var bindings = local[0]["syncQuellen"] as! [String: Any]; bindings["other-calendar:fixture"] = ["id": "other-id", "etag": "other-etag"]
        local[0]["syncQuellen"] = bindings; local[0]["futureOpaque"] = "keep"
        let result = try plan(snapshot(""), state(seeded.state, appointments: local), seeded.baseline)
        XCTAssertTrue(result.operations.isEmpty); XCTAssertEqual(result.preview.appointments.count, 1)
        XCTAssertEqual(result.preview.appointments[0]["syncKalenderUid"] as? String, "other-calendar:fixture")
        XCTAssertEqual(result.preview.appointments[0]["futureOpaque"] as? String, "keep")
        XCTAssertNil((result.preview.appointments[0]["syncQuellen"] as? [String: Any])?[source().uid])
    }
    func testMissingRemoteWithDirtyLocalPlansConditionalCreateUsingFrozenBody() throws {
        let original = try snapshot(event()), seeded = try seed(original)
        var local = seeded.state.appointments; local[0]["titel"] = "Keep local edit"
        let empty = try snapshot("")
        let one = try plan(empty, state(seeded.state, appointments: local), seeded.baseline)
        let two = try plan(empty, state(seeded.state, appointments: local), seeded.baseline)
        XCTAssertEqual(one.operations.count, 1); XCTAssertEqual(one.operations[0].kind, .create)
        XCTAssertEqual(one.operations[0].ifNoneMatch, "*"); XCTAssertNil(one.operations[0].expectedETag)
        XCTAssertEqual(one.operations[0].bytes, two.operations[0].bytes); XCTAssertEqual(one.operations[0].id, two.operations[0].id)
        expect(.invalidAcknowledgement) { _ = try one.finalize(acknowledgements: []) }
        let final = try one.finalize(acknowledgements: ack(one))
        XCTAssertEqual(final.state.appointments[0]["titel"] as? String, "Keep local edit")
    }
    func testExplicitVersionBoundDeletionPatchesSiblingInsteadOfDeletingWholeResource() throws {
        let original = try snapshot(event() + task()), seeded = try seed(original)
        let deletion = Planner.Deletion(domain: .appointment, sourceUID: source().uid, key: .init(kind: "VEVENT", uid: "event-one"),
            href: original.resources[0].href, etag: original.resources[0].etag, syncEpoch: epoch)
        let result = try plan(original, state(seeded.state, appointments: [], deletions: [deletion]), seeded.baseline)
        XCTAssertEqual(result.operations.count, 1); XCTAssertEqual(result.operations[0].kind, .update)
        let parsed = try ICalendarImport.decode(result.operations[0].bytes!, context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertTrue(parsed.appointments.isEmpty); XCTAssertEqual(parsed.tasks.count, 1)
        XCTAssertTrue(try result.finalize(acknowledgements: ack(result)).state.deletions.isEmpty)
        let changed = try snapshot(event() + task(), etag: "\"concurrent\"")
        expect(.deletionConflict) { _ = try plan(changed, state(seeded.state, appointments: [], deletions: [deletion]), seeded.baseline) }
    }
    func testOtherProviderDeletionIntentAndOpaquePayloadAreNotConsumed() throws {
        let original=try snapshot(event()),saved=try seed(original),key=Planner.Key(kind:"VEVENT",uid:"event-one")
        let selected=Planner.Deletion(domain:.appointment,sourceUID:source().uid,key:key,href:original.resources[0].href,etag:"\"v1\"",syncEpoch:epoch)
        let other=Planner.Deletion(domain:.appointment,sourceUID:"other-calendar:fixture",key:key,
            href:URL(string:"https://other.example.test/cal/item.ics")!,etag:"\"other\"",syncEpoch:epoch,payload:["future":"keep"])
        let result=try plan(original,state(saved.state,appointments:[],deletions:[selected,other]),saved.baseline)
        let final=try result.finalize(acknowledgements:ack(result))
        XCTAssertEqual(final.state.deletions.count,1)
        XCTAssertEqual(final.state.deletions[0].sourceUID,"other-calendar:fixture")
        XCTAssertEqual(final.state.deletions[0].payload["future"] as? String,"keep")
    }
    func testLastComponentDeletionUsesDeleteAndExplicitAnniversaryDeletionIsSupported() throws {
        let original = try snapshot(anniversary()), seeded = try seed(original)
        let deletion = Planner.Deletion(domain: .anniversary, sourceUID: source().uid, key: .init(kind: "VEVENT", uid: "anniversary"),
            href: original.resources[0].href, etag: original.resources[0].etag, syncEpoch: epoch)
        let result = try plan(original, state(seeded.state, anniversaries: [], deletions: [deletion]), seeded.baseline)
        XCTAssertEqual(result.operations[0].kind, .delete); XCTAssertNil(result.operations[0].bytes)
        let final = try result.finalize(acknowledgements: ack(result))
        XCTAssertTrue(final.state.anniversaries.isEmpty); XCTAssertTrue(final.state.deletions.isEmpty)
        let missingIntent = try plan(original, state(seeded.state, anniversaries: []), seeded.baseline)
        XCTAssertTrue(missingIntent.operations.isEmpty); XCTAssertEqual(missingIntent.preview.anniversaries.count, 1)
    }
    func testUnsupportedTaskCapabilityPreservesTasksAndPriorTaskCursorEntries() throws {
        let original = try snapshot(task()), seeded = try seed(original)
        let noTasks = try snapshot(event(), tasks: false)
        let result = try plan(noTasks, seeded.state, seeded.baseline)
        XCTAssertEqual(result.preview.tasks.count, 1)
        let final = try result.finalize(acknowledgements: [])
        XCTAssertTrue(final.baseline.tasksInitialized)
        XCTAssertEqual(final.baseline.entries.filter { $0.domain == .task }.count, 1)
    }
    func testUnsupportedTasksDoNotCarryOldRestoreDeleteAuthorityIntoNewEpoch() throws {
        let original=try snapshot(task()),saved=try seed(original)
        let result=try plan(snapshot(event(),tasks:false),saved.state,saved.baseline,restore:true)
        let finalized=try result.finalize(acknowledgements:[])
        XCTAssertFalse(finalized.baseline.tasksInitialized)
        XCTAssertEqual(finalized.state.tasks.count,1)
        XCTAssertEqual(finalized.baseline.entries.filter{$0.domain == .task}.count,1)
    }
    func testTaskAndMarkedAnniversaryLocalEditsShareOneVersionBoundResourcePatch() throws {
        let original=try snapshot(task()+anniversary()),saved=try seed(original)
        var tasks=saved.state.tasks, anniversaries=saved.state.anniversaries
        tasks[0]["notiz"]="Changed task note";anniversaries[0]["name"]="Changed birthday"
        let result=try plan(original,state(saved.state,tasks:tasks,anniversaries:anniversaries),saved.baseline)
        XCTAssertEqual(result.operations.count,1)
        let parsed=try ICalendarImport.decode(result.operations[0].bytes!, context: try CalendarTestContext.make(),displayTimeZone:"UTC")
        XCTAssertEqual(parsed.tasks[0]["notiz"] as? String,"Changed task note")
        XCTAssertEqual(parsed.anniversaries[0]["name"] as? String,"Changed birthday")
        let finalized=try result.finalize(acknowledgements:ack(result))
        XCTAssertEqual(finalized.baseline.entries.count,2)
    }
    func testAcknowledgementsMustMatchEveryOperationAndSpecificETags() throws {
        let original = try snapshot(event()), seeded = try seed(original)
        var local = seeded.state.appointments; local[0]["titel"] = "Changed"
        let result = try plan(original, state(seeded.state, appointments: local), seeded.baseline), operation = result.operations[0]
        for etag in ["", "*", " * ", "\"v2\"\r\nInjected: header"] {
            expect(.invalidAcknowledgement) { _ = try result.finalize(acknowledgements: [.init(operationID: operation.id, href: operation.href, status: 204, etag: etag)]) }
        }
        expect(.invalidAcknowledgement) { _ = try result.finalize(acknowledgements: [.init(operationID: "wrong", href: operation.href, status: 204, etag: "\"v2\"")]) }
        expect(.invalidAcknowledgement) { _ = try result.finalize(acknowledgements: [.init(operationID: operation.id, href: operation.href, status: 412, etag: "\"v2\"")]) }
    }
    func testPlannerCancellationNeverReturnsPartialCandidate() throws {
        let remote = try snapshot(event() + task())
        do {
            _ = try Planner.plan(context: try CalendarTestContext.make(), snapshot: remote, local: .init(appointments: [], tasks: [], anniversaries: []), baseline: nil,
                restoreAdditive: false, syncEpoch: epoch, createdAt: time, cancellation: { true })
            XCTFail("Expected cancellation")
        } catch is CancellationError { }
    }
    func testFirstRunAndRestoreUploadSelectedLocalOnlyRecordsConditionally() throws {
        let populated = try snapshot(event() + task() + anniversary()), seeded = try seed(populated)
        let empty = try snapshot("")
        for restore in [false, true] {
            let result = try plan(empty, seeded.state, restore ? seeded.baseline : nil, restore: restore)
            XCTAssertEqual(result.operations.count, 3)
            XCTAssertTrue(result.operations.allSatisfy { $0.kind == .create && $0.ifNoneMatch == "*" && $0.expectedETag == nil })
            XCTAssertEqual(try result.finalize(acknowledgements: ack(result)).baseline.entries.count, 3)
        }
        var foreign = seeded.state.appointments[0]
        foreign["syncKalenderUid"] = "other"; foreign["syncQuellen"] = ["other": ["id": "foreign"]]
        XCTAssertTrue(try plan(empty, .init(appointments: [foreign], tasks: [], anniversaries: []), nil).operations.isEmpty)
        var unbound = seeded.state.appointments[0]
        for field in ["syncKalenderUid", "syncQuellen", "davHref", "davEtag"] { unbound.removeValue(forKey: field) }
        XCTAssertEqual(try plan(empty, .init(appointments: [unbound], tasks: [], anniversaries: [], assignUnboundAppointments: true), nil).operations.count, 1)
    }
    func testColorOnlyUIEditWritesAndSurvivesRepeatedReimportForEventsAndTasks() throws {
        let remote = try snapshot(event() + task()), seeded = try seed(remote)
        var appointments = seeded.state.appointments, tasks = seeded.state.tasks
        // Actual editor probe changes only this field plus geaendert; raw ICS is unchanged.
        appointments[0]["akzentFarbe"] = "#112233"; tasks[0]["akzentFarbe"] = "#112233"
        appointments[0]["geaendert"] = 1; tasks[0]["geaendert"] = 1
        let result = try plan(remote, state(seeded.state, appointments: appointments, tasks: tasks), seeded.baseline)
        XCTAssertEqual(result.operations.count, 1)
        let written = String(data: result.operations[0].bytes!, encoding: .utf8)!
        XCTAssertEqual(written.components(separatedBy: "X-MAGNOLIE-ACCENT-COLOR:#112233").count - 1, 2)
        let updated = try DAVCalendarSnapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [.init(href: remote.resources[0].href, etag: "\"v2\"", data: written)], displayTimeZone: "UTC")
        XCTAssertEqual(updated.appointments[0].value["akzentFarbe"] as? String, "#112233")
        XCTAssertEqual(updated.tasks![0].value["akzentFarbe"] as? String, "#112233")
        let saved = try result.finalize(acknowledgements: ack(result))
        var next = saved.state.appointments; next[0]["akzentFarbe"] = "#445566"
        let second = try plan(updated, state(saved.state, appointments: next), saved.baseline)
        XCTAssertEqual(second.operations.count, 1)
        XCTAssertTrue(String(data: second.operations[0].bytes!, encoding: .utf8)!.contains("X-MAGNOLIE-ACCENT-COLOR:#445566"))
        let parameterized = try snapshot(event().replacingOccurrences(of: "END:VEVENT", with: "X-MAGNOLIE-ACCENT-COLOR;X-FUTURE=keep:#112233\nEND:VEVENT"))
        let parameterSeed = try seed(parameterized)
        var parameterLocal = parameterSeed.state.appointments; parameterLocal[0]["titel"] = "Changed title"
        let preserving = try plan(parameterized, state(parameterSeed.state, appointments: parameterLocal), parameterSeed.baseline)
        XCTAssertTrue(String(data: preserving.operations[0].bytes!, encoding: .utf8)!.contains("X-MAGNOLIE-ACCENT-COLOR;X-FUTURE=keep:#112233"))
        for color in ["#445566", ""] {
            parameterLocal[0]["akzentFarbe"] = color
            expect(.unsupportedRecord) { _ = try plan(parameterized, state(parameterSeed.state, appointments: parameterLocal), parameterSeed.baseline) }
        }
    }
    func testLegacyHashCannotSilentlyAdoptOverUntrackedLocalColor() throws {
        for domain in [Planner.Domain.appointment, .task] {
            let remote = try snapshot(domain == .task ? task() : event()), seeded = try seed(remote)
            let prior = seeded.baseline.entries[0]
            let original = domain == .task ? seeded.state.tasks[0] : seeded.state.appointments[0]
            let legacyHash = try DAVSyncBaseline.linuxCompatibilityHash(original, kind: domain)
            let legacy = Planner.Baseline(sourceUID: source().uid, syncEpoch: epoch, appointmentsInitialized: true, tasksInitialized: true,
                anniversariesInitialized: true, entries: [.init(domain: domain, key: prior.key, localUID: prior.localUID,
                    href: prior.href, etag: prior.etag, format: domain == .task ? "linux-1" : "linux-calendar-2", localHash: legacyHash, remoteHash: legacyHash)])
            var edited = original; edited["akzentFarbe"] = "#112233"
            let local = domain == .task ? state(seeded.state, tasks: [edited]) : state(seeded.state, appointments: [edited])
            let result = try plan(remote, local, legacy)
            XCTAssertEqual(result.conflictCopies, 1)
            let preserved = domain == .task ? result.preview.tasks : result.preview.appointments
            XCTAssertTrue(preserved.contains { $0["akzentFarbe"] as? String == "#112233" })
        }
    }
    func testAliasedTaskUpdateKeepsOriginalIdentityAndParentAcrossReimport() throws {
        let alias = "urn:magnolie:task:d84279835cf61466e9d6378231ec4d63fc01a40d30729c0c8ae9bf4766b1e225"
        func identity(_ uid: String, parent: String) throws -> String {
            try Document.encode(["v": 1, "source": "imported-original-source", "uid": uid, "parent": parent,
                                 "parentSource": "imported-original-source"]).replacingOccurrences(of: ",", with: "\\,")
        }
        let body = "BEGIN:VTODO\nUID:\(alias)\nSUMMARY:Parent\nX-MAGNOLIE-TASK-IDENTITY:\(try identity("original-parent", parent: ""))\nEND:VTODO\n" +
            "BEGIN:VTODO\nUID:child\nSUMMARY:Child\nRELATED-TO;RELTYPE=PARENT:original-parent\nX-MAGNOLIE-TASK-IDENTITY:\(try identity("child", parent: "original-parent"))\nEND:VTODO\n"
        let remote = try snapshot(body), seeded = try seed(remote)
        var tasks = seeded.state.tasks
        let index = tasks.firstIndex { $0["uid"] as? String == "original-parent" }!
        tasks[index]["titel"] = "Edited parent"
        let result = try plan(remote, state(seeded.state, tasks: tasks), seeded.baseline)
        XCTAssertEqual(result.operations.count, 1)
        let text = String(data: result.operations[0].bytes!, encoding: .utf8)!
        let fresh = try DAVCalendarSnapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [.init(href: remote.resources[0].href, etag: "\"v2\"", data: text)], displayTimeZone: "UTC")
        XCTAssertEqual(fresh.tasks!.first { $0.value["uid"] as? String == "original-parent" }?.wireKey.uid, alias)
        XCTAssertEqual(fresh.tasks!.first { $0.value["uid"] as? String == "child" }?.value["elternUid"] as? String, "original-parent")
        let saved = try result.finalize(acknowledgements: ack(result))
        let next = try plan(fresh, saved.state, saved.baseline)
        XCTAssertTrue(next.operations.isEmpty)
        XCTAssertEqual(Set(next.preview.tasks.compactMap { $0["uid"] as? String }), ["original-parent", "child"])
    }
    func testOversizedBaselineRejectedBeforePlanning() throws {
        let remote = try snapshot(event()), seeded = try seed(remote), entry = seeded.baseline.entries[0]
        let oversized = Planner.Baseline(sourceUID: source().uid, syncEpoch: epoch, appointmentsInitialized: true,
            tasksInitialized: true, anniversariesInitialized: true, entries: Array(repeating: entry, count: ICalendarImport.maximumRecords + 1))
        expect(.limit) { _ = try plan(remote, seeded.state, oversized) }
    }
    func testExplicitEncoderTimestampIsRepeatableAndOnlyGeneratedStampChanges() throws {
        let record = try snapshot(event()).appointments[0].value
        let one = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments, timestamp: time)
        XCTAssertEqual(one, try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments, timestamp: time))
        XCTAssertNotEqual(one, try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments, timestamp: time.addingTimeInterval(3600)))
        XCTAssertTrue(one.contains("X-OPAQUE:keep-event"))
    }
}
