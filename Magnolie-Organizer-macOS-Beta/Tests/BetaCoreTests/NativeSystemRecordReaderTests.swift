#if os(macOS)
import Foundation
import XCTest
import EventKit
import Contacts
@testable import BetaCore

/// Only unsaved native objects. Never enumerate accounts or request permission.
final class NativeSystemRecordReaderTests: XCTestCase {
    func testUnsavedEventPublicRecurrenceAndAlarmsAreRetainedAsUnsupported() throws {
        let store = EKEventStore()
        let event = EKEvent(eventStore: store)
        event.title = "Synthetic unsaved event 🌼"; event.notes = "Retain"
        event.startDate = Date(timeIntervalSince1970: 1_767_225_600)
        event.endDate = event.startDate.addingTimeInterval(3600)
        event.timeZone = TimeZone(identifier: "Europe/Berlin")
        event.recurrenceRules = [EKRecurrenceRule(recurrenceWith: .weekly, interval: 2, end: EKRecurrenceEnd(occurrenceCount: 4))]
        event.alarms = [EKAlarm(relativeOffset: -900)]
        let source = try SystemSourceSnapshot.Source(uid: SystemSourcePolicy.uid(.events, "synthetic"), kind: .events,
            title: "Synthetic", nativeType: "calendar:0", permission: "authorized", readOnly: true)
        let record = try NativeSystemRecordReader.event(event, source: source)
        XCTAssertEqual(record.fields["title"] as? String, event.title)
        let rules = try XCTUnwrap(record.fields["recurrenceRules"] as? [[String: Any]])
        XCTAssertEqual(rules.first?["interval"] as? Int, 2)
        XCTAssertEqual(rules.first?["occurrenceCount"] as? Int, 4)
        let alarms = try XCTUnwrap(record.fields["alarms"] as? [[String: Any]])
        XCTAssertEqual(alarms.first?["relativeOffset"] as? Double, -900)
        XCTAssertTrue(record.unsupported.contains("native-series-projection-not-lossless"))
        XCTAssertEqual(record.revisionCoverage, "serialized-fields-only")
        XCTAssertTrue((record.fields["metadataIncomplete"] as? [String] ?? []).contains("alarm-action-sound-email-procedure-details"))
        guard case .unsupported = try SystemRecordNormalizer.project(record, source: source, displayTimeZone: "UTC") else { return XCTFail("Never flatten an unsaved recurring native event") }
    }
    func testUnsavedReminderKeepsPublicDateComponentsWithoutInventedMidnight() throws {
        let store = EKEventStore()
        let reminder = EKReminder(eventStore: store)
        reminder.title = "Synthetic due-only reminder"
        var due = DateComponents(); due.calendar = Calendar(identifier: .gregorian); due.year = 2026; due.month = 11; due.day = 30
        reminder.dueDateComponents = due
        reminder.priority = 5
        let startBefore = SystemDateComponents.fields(reminder.startDateComponents)
        let dueBefore = SystemDateComponents.fields(reminder.dueDateComponents)
        let fields = NativeSystemRecordReader.reminderFields(reminder)
        let startAfter = SystemDateComponents.fields(reminder.startDateComponents)
        let dueAfter = SystemDateComponents.fields(reminder.dueDateComponents)
        XCTAssertEqual(try Document.encode(["value": startBefore as Any? ?? NSNull()]), try Document.encode(["value": startAfter as Any? ?? NSNull()]))
        XCTAssertEqual(try Document.encode(["value": dueBefore as Any? ?? NSNull()]), try Document.encode(["value": dueAfter as Any? ?? NSNull()]))
        XCTAssertEqual(try Document.encode(["value": fields["startComponents"]!]), try Document.encode(["value": startBefore as Any? ?? NSNull()]))
        XCTAssertEqual(try Document.encode(["value": fields["dueComponents"]!]), try Document.encode(["value": dueBefore as Any? ?? NSNull()]))
        let components = try XCTUnwrap(fields["dueComponents"] as? [String: Any])
        XCTAssertEqual(components["year"] as? Int, 2026)
        for key in ["hour", "minute", "second", "timeZone"] {
            if let expected = dueBefore?[key] {
                XCTAssertEqual(try Document.encode(["value": components[key] as Any? ?? NSNull()]), try Document.encode(["value": expected]))
            } else { XCTAssertNil(components[key], "Reader must preserve actual getter absence: " + key) }
        }
        XCTAssertEqual(fields["hierarchyAvailable"] as? Bool, false)
    }
    func testUnsavedContactYearlessLeapAndNonGregorianDateDoNotAcquireYear() throws {
        let contact = CNMutableContact()
        contact.givenName = "Synthetic"; contact.familyName = "Fixture"
        var birthday = DateComponents(); birthday.calendar = Calendar(identifier: .gregorian); birthday.month = 2; birthday.day = 29
        contact.birthday = birthday
        var lunar = DateComponents(); lunar.calendar = Calendar(identifier: .chinese); lunar.month = 4; lunar.day = 1; lunar.isLeapMonth = true
        var anniversary = DateComponents(); anniversary.calendar = Calendar(identifier: .gregorian); anniversary.month = 6; anniversary.day = 7
        contact.dates = [CNLabeledValue(label: "Custom public label", value: anniversary as NSDateComponents)]
        let source = try SystemSourceSnapshot.Source(uid: SystemSourcePolicy.uid(.contacts, "synthetic-container"), kind: .contacts,
            title: "Synthetic", nativeType: "container:0", permission: "authorized", readOnly: false)
        let gregorian = try NativeSystemRecordReader.contact(contact, source: source)
        XCTAssertNotNil(gregorian.fields["vcard"] as? String)
        contact.nonGregorianBirthday = lunar
        let record = try NativeSystemRecordReader.contact(contact, source: source)
        let raw = try XCTUnwrap(record.fields["birthday"] as? [String: Any])
        XCTAssertNil(raw["year"]); XCTAssertEqual(raw["day"] as? Int, 29)
        let nonGregorian = try XCTUnwrap(record.fields["nonGregorianBirthday"] as? [String: Any])
        XCTAssertEqual(nonGregorian["calendar"] as? String, "chinese")
        XCTAssertEqual(nonGregorian["isLeapMonth"] as? Bool, true)
        XCTAssertEqual(record.fields["unification"] as? String, "unknown")
        XCTAssertTrue(record.fields["vcard"] is String || record.unsupported.contains("public-vcard-serialization-failed"), "A public serializer failure must be explicit; native date components remain retained")
        XCTAssertTrue(source.readOnly)
        guard case .unsupported(let retained, _) = try SystemRecordNormalizer.project(record, source: source, displayTimeZone: "UTC") else { return XCTFail("No invented contact writer") }
        XCTAssertEqual(retained.revision, record.revision)
    }
}
#endif
