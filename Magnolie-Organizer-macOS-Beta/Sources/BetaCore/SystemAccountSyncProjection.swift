import Foundation

/// Refs #786. Reuse the already bounded, explicit native copy projections as a
/// codec, not as write authorization. No name/phone/mail deduplication occurs.
public enum SystemAccountSyncProjection {
    public typealias Sync = SystemAccountSync
    struct Group { let name: String, keys: [String], writable: Bool }
    static func groups(_ kind: SystemSourcePolicy.Kind) -> [Group] {
        switch kind {
        case .events:
            return [Group(name: "title", keys: ["titel"], writable: true), Group(name: "notes", keys: ["notiz"], writable: true),
                Group(name: "location", keys: ["ort"], writable: true),
                Group(name: "dates", keys: ["datum", "endDatum", "zeit", "endZeit", "ganztag", "icsAnzeigeZeitzone", "icsRoundtrip", "icsNullDauer", "icsEndeFehlt"], writable: true),
                Group(name: "event-status", keys: ["vorlaeufig"], writable: false),
                Group(name: "recurrence-and-alarms", keys: ["wiederholung", "alarme", "standardErinnerung", "individuelleErinnerungTage"], writable: false)]
        case .reminders:
            return [Group(name: "title", keys: ["titel"], writable: true), Group(name: "notes", keys: ["notiz"], writable: true),
                Group(name: "completed", keys: ["erledigt"], writable: true), Group(name: "priority", keys: ["prio"], writable: true),
                Group(name: "dates", keys: ["startDatum", "startZeit", "faellig", "faelligZeit", "icsRoundtrip", "icsAnzeigeZeitzone"], writable: true),
                Group(name: "hierarchy-and-alarms", keys: ["elternUid", "erinnern", "individuelleErinnerungTage", "vorlaufTage", "erinnerungsMinute"], writable: false)]
        case .contacts:
            return [Group(name: "givenName", keys: ["vorname"], writable: true), Group(name: "familyName", keys: ["nachname"], writable: true),
                Group(name: "organizationName", keys: ["firma"], writable: true), Group(name: "phones", keys: ["telefone"], writable: true),
                Group(name: "emails", keys: ["emailEintraege"], writable: true), Group(name: "addresses", keys: ["anschriften"], writable: true),
                Group(name: "birthday", keys: ["geburtstag", "geburtstagJahrUnbekannt"], writable: true),
                Group(name: "formatted-name", keys: ["anzeigename"], writable: false), Group(name: "photo", keys: ["foto"], writable: false),
                Group(name: "vcard-extra-fields", keys: ["vcardRoundtrip"], writable: false)]
        }
    }
    static func managedKeys(_ kind: SystemSourcePolicy.Kind) -> [String] { groups(kind).flatMap(\.keys) }
    static func select(_ object: [String: Any], _ keys: [String]) -> [String: Any] {
        Dictionary(uniqueKeysWithValues: keys.map { key in
            if key == "icsRoundtrip", let lines = object[key] as? [String] {
                // LOCATION is already its own group. Property order is not a
                // field change. Keep exact clock properties: the visible UI has
                // minute precision, while the raw source may retain seconds.
                let retained = lines.filter { line in
                    let name = line.prefix { $0 != ";" && $0 != ":" }.uppercased()
                    return name != "LOCATION"
                }.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }
                return (key, retained as Any)
            }
            return (key, object[key] ?? NSNull())
        })
    }
    static func fields(_ object: [String: Any], kind: SystemSourcePolicy.Kind) -> [String: Any] { select(object, managedKeys(kind)) }
    static func copyEvidence(from source: [String: Any], to target: inout [String: Any]) {
        for key in ["nativeSourceReadOnly", "nativeSystemRecord", "nativeCalendarImport", "nativeContactImport", "nativeContactRecord", "nativeReminderImport", "nativeReminderRecord"] {
            if let value = source[key] { target[key] = value }
        }
    }

    public static func events(_ snapshot: SystemSourceSnapshot, context: CalendarTimeContext, displayTimeZone: String) throws -> Sync.Snapshot {
        guard case .boundedWindow(let start, let end) = snapshot.scope, snapshot.source.kind == .events,
              !snapshot.source.readOnly else { throw Sync.failure("select a writable calendar") }
        let source = try eventSource(snapshot.source, start: start, end: end, displayTimeZone: displayTimeZone)
        let plan = try SystemCalendarImport.prepare(snapshot, context: context, displayTimeZone: displayTimeZone)
        var records: [Sync.Record] = []
        for canonical in plan.appointments {
            guard let evidence = canonical["nativeSystemRecord"] as? [String: Any], let identifier = evidence["identifier"] as? String,
                  let fields = evidence["fields"] as? [String: Any] else { throw Sync.failure("native event evidence is missing") }
            records.append(try Sync.Record(identifier: identifier, source: source, canonicalRecord: canonical, nativeFields: fields))
        }
        return try Sync.Snapshot(source: source, records: records, excluded: plan.excluded)
    }
    public static func eventSource(_ source: SystemSourceSnapshot.Source, start: Date, end: Date, displayTimeZone: String) throws -> Sync.Source {
        guard source.kind == .events, !source.readOnly, source.permission == "authorized" else { throw Sync.failure("select a writable authorized calendar") }
        return try Sync.Source(kind: .events, sourceUID: source.uid, title: source.title,
            metadata: ["parentUID": source.parentUID.map { $0 as Any } ?? NSNull(), "parentTitle": source.parentTitle.map { $0 as Any } ?? NSNull(),
                       "parentType": source.parentType.map { $0 as Any } ?? NSNull(), "nativeType": source.nativeType,
                       "permission": source.permission, "readOnly": source.readOnly, "writePolicy": "existing-event-fields"],
            scope: ["start": start.timeIntervalSince1970, "end": end.timeIntervalSince1970], displayTimeZone: displayTimeZone)
    }
    public static func reminders(_ snapshot: SystemReminderImport.Snapshot, context: CalendarTimeContext, displayTimeZone: String) throws -> Sync.Snapshot {
        let native = snapshot.source
        guard !native.readOnly, native.permission == "authorized" else { throw Sync.failure("select a writable reminder list") }
        let source = try Sync.Source(kind: .reminders, sourceUID: native.sourceUID, title: native.title,
            metadata: ["calendarID": native.calendarID, "parentUID": native.parentUID, "parentTitle": native.parentTitle,
                       "parentType": native.parentType, "nativeType": native.nativeType, "readOnly": native.readOnly,
                       "permission": native.permission, "writePolicy": "existing-reminder-fields"],
            scope: ["kind": "full-source"], displayTimeZone: displayTimeZone)
        let plan = try SystemReminderImport.prepare(snapshot, context: context, displayTimeZone: displayTimeZone)
        guard let rows = plan.payload["tasks"] as? [[String: Any]], let excluded = plan.payload["excluded"] as? [[String: Any]] else { throw Sync.failure("invalid reminder projection") }
        let records = try rows.map { row -> Sync.Record in
            guard var canonical = row["task"] as? [String: Any], let raw = row["nativeRecord"] as? [String: Any],
                  let fields = raw["fields"] as? [String: Any] else { throw Sync.failure("missing reminder evidence") }
            let identifier = try Sync.text(row, "identifier")
            canonical["nativeReminderRecord"] = raw
            canonical["nativeReminderImport"] = ["version": 1, "identity": row["identity"]!, "sourceUID": native.sourceUID,
                "calendarID": native.calendarID, "sourceTitle": native.title, "parentUID": native.parentUID,
                "parentTitle": native.parentTitle, "parentType": native.parentType, "nativeType": native.nativeType,
                "readOnly": native.readOnly, "permission": native.permission, "identifier": identifier, "revision": row["revision"]!,
                "copyKind": "standalone-public-fields", "revisionCoverage": "serialized-fields-only"]
            canonical["elternUid"] = ""; canonical["reihenfolge"] = 0
            return try Sync.Record(identifier: identifier, source: source, canonicalRecord: canonical, nativeFields: fields)
        }
        return try Sync.Snapshot(source: source, records: records, excluded: excluded)
    }
    public static func contacts(_ snapshot: SystemContactImport.Snapshot, displayTimeZone: String) throws -> Sync.Snapshot {
        let native = snapshot.source
        // CNContainer exposes no per-container writability flag. This capability
        // means a narrowly scoped CNSaveRequest is attempted after consent; it
        // does not convert the old contacts discovery's readOnly flag to false.
        let source = try Sync.Source(kind: .contacts, sourceUID: native.sourceUID, title: native.title,
            metadata: ["containerID": native.containerID, "nativeType": native.nativeType, "permission": "authorized",
                       "writePolicy": "existing-nonunified-contact-fields"],
            scope: ["kind": "full-source"], displayTimeZone: displayTimeZone)
        let plan = try SystemContactImport.prepare(snapshot)
        guard let rows = plan.payload["contacts"] as? [[String: Any]], let excluded = plan.payload["excluded"] as? [[String: Any]] else { throw Sync.failure("invalid contact projection") }
        let records = try rows.map { row -> Sync.Record in
            guard var canonical = row["contact"] as? [String: Any], let raw = row["nativeRecord"] as? [String: Any],
                  let fields = raw["fields"] as? [String: Any] else { throw Sync.failure("missing contact evidence") }
            let identifier = try Sync.text(row, "identifier")
            // Same explicit normalization as the established copy path. The raw
            // native spelling remains in the baseline; an unchanged lowercase
            // local email must never cause an outbound write.
            for name in ["telefone", "emailEintraege", "anschriften"] {
                guard var values = canonical[name] as? [[String: Any]] else { throw Sync.failure("invalid contact values") }
                for index in values.indices {
                    for key in ["label", "postfach", "zusatz"] where values[index][key] as? String == "" { values[index].removeValue(forKey: key) }
                    if name == "emailEintraege", let value = values[index]["wert"] as? String { values[index]["wert"] = value.lowercased() }
                }
                canonical[name] = values
            }
            canonical["nativeContactRecord"] = raw
            canonical["nativeContactImport"] = ["version": 1, "identity": row["identity"]!, "sourceUID": native.sourceUID,
                "containerID": native.containerID, "sourceTitle": native.title, "nativeType": native.nativeType,
                "identifier": identifier, "revision": row["revision"]!, "copyKind": "public-fields",
                "revisionCoverage": "serialized-fields-only", "birthdayPolicy": "contact-only"]
            return try Sync.Record(identifier: identifier, source: source, canonicalRecord: canonical, nativeFields: fields)
        }
        return try Sync.Snapshot(source: source, records: records, excluded: excluded)
    }

    public static func nativePatch(record: Sync.Record, desired: [String: Any], changedGroups: [String], source: Sync.Source,
                                   context: CalendarTimeContext) throws -> [String: Any] {
        guard Sync.same(record.sourceFingerprint, source.fingerprint), !changedGroups.isEmpty,
              Set(changedGroups).isSubset(of: Set(groups(source.kind).filter(\.writable).map(\.name))) else { throw Sync.failure("unsupported field update") }
        try validateLocal(desired, record: record, source: source, context: context)
        var patch: [String: Any] = [:]
        for group in changedGroups {
            switch (source.kind, group) {
            case (.events, "title"), (.reminders, "title"):
                patch["title"] = try safeText(desired, "titel", maximum: source.kind == .events ? 65_536 : 4096, nonempty: true)
            case (.events, "notes"), (.reminders, "notes"):
                patch["notes"] = try safeText(desired, "notiz", maximum: 1_048_576, multiline: true)
            case (.events, "location"):
                patch["location"] = try safeText(desired, "ort", maximum: 65_536)
            case (.events, "dates"):
                patch.merge(try eventDates(desired, original: record.nativeFields, previous: record.canonicalRecord, source: source, context: context)) { _, value in value }
            case (.reminders, "completed"):
                guard let completed = Sync.boolean(desired["erledigt"]) else { throw Sync.failure("invalid completed state") }; patch["completed"] = completed
            case (.reminders, "priority"):
                guard let priority = Sync.integer(desired["prio"]), (1...3).contains(priority) else { throw Sync.failure("invalid reminder priority") }
                patch["priority"] = [1: 1, 2: 5, 3: 9][priority]!
            case (.reminders, "dates"):
                guard try Sync.text(desired, "icsAnzeigeZeitzone") == source.displayTimeZone else { throw Sync.failure("display timezone changed") }
                patch["startComponents"] = try reminderDate(day: Sync.text(desired, "startDatum"), clock: Sync.text(desired, "startZeit"),
                    original: record.nativeFields["startComponents"], displayZone: source.displayTimeZone, context: context)
                patch["dueComponents"] = try reminderDate(day: Sync.text(desired, "faellig"), clock: Sync.text(desired, "faelligZeit"),
                    original: record.nativeFields["dueComponents"], displayZone: source.displayTimeZone, context: context)
            case (.contacts, "givenName"): patch["givenName"] = try safeText(desired, "vorname")
            case (.contacts, "familyName"): patch["familyName"] = try safeText(desired, "nachname")
            case (.contacts, "organizationName"): patch["organizationName"] = try safeText(desired, "firma")
            case (.contacts, "phones"):
                patch["phoneNumbers"] = try contactValues(localKey: "telefone", nativeKey: "phoneNumbers", record: record, desired: desired)
            case (.contacts, "emails"):
                patch["emailAddresses"] = try contactValues(localKey: "emailEintraege", nativeKey: "emailAddresses", record: record, desired: desired)
            case (.contacts, "addresses"):
                patch["postalAddresses"] = try contactValues(localKey: "anschriften", nativeKey: "postalAddresses", record: record, desired: desired)
            case (.contacts, "birthday"):
                patch["birthday"] = try birthday(desired, original: record.nativeFields["birthday"])
            default: throw Sync.failure("unsupported field update")
            }
        }
        var native = record.nativeFields
        native.merge(patch) { _, value in value }
        if let notes = patch["notes"] as? String { native["hasNotes"] = !notes.isEmpty }
        if source.kind == .events { native.removeValue(forKey: "hasNotes") }
        if Sync.boolean(patch["completed"]) == false { native["completionDate"] = NSNull() }
        let projected = try reproject(record: record, nativeFields: native, source: source, context: context)
        // This catches trimmed text, unsupported list edits, duration/date
        // ambiguity and changes to raw ICS properties outside the field codec.
        for group in groups(source.kind) where changedGroups.contains(group.name) {
            let comparedKeys = source.kind == .reminders && group.name == "dates" ? group.keys.filter { $0 != "icsRoundtrip" } : group.keys
            guard try Sync.equal(select(projected.canonicalRecord, comparedKeys), select(desired, comparedKeys)) else {
                throw Sync.failure("the native codec cannot retain the requested local field: " + group.name)
            }
            if source.kind == .reminders && group.name == "dates" {
                func extras(_ row: [String: Any]) -> [String] {
                    (row["icsRoundtrip"] as? [String] ?? []).filter {
                        !["DTSTART", "DUE"].contains($0.prefix { $0 != ";" && $0 != ":" }.uppercased())
                    }.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }
                }
                guard try Sync.equal(extras(projected.canonicalRecord), extras(desired)) else { throw Sync.failure("unsupported reminder source fields changed") }
            }
        }
        return try Sync.frozen(patch)
    }

    static func validateLocal(_ row: [String: Any], record: Sync.Record, source: Sync.Source, context: CalendarTimeContext) throws {
        guard source.kind != .contacts else { return }
        if source.kind == .reminders {
            // Generic calendar export resolves floating clocks through a display
            // zone. Reminder DATE/floating fields instead retain civil values,
            // including clocks inside a display-zone DST gap or fold.
            var native = record.nativeFields
            native["startComponents"] = try reminderDate(day: Sync.text(row, "startDatum"), clock: Sync.text(row, "startZeit"),
                original: native["startComponents"], displayZone: source.displayTimeZone, context: context)
            native["dueComponents"] = try reminderDate(day: Sync.text(row, "faellig"), clock: Sync.text(row, "faelligZeit"),
                original: native["dueComponents"], displayZone: source.displayTimeZone, context: context)
            let expected = try reproject(record: record, nativeFields: native, source: source, context: context)
            func times(_ value: [String: Any]) throws -> [[String: Any]] {
                try (value["icsRoundtrip"] as? [String] ?? []).filter {
                    ["DTSTART", "DUE"].contains($0.prefix { $0 != ";" && $0 != ":" }.uppercased())
                }.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }.map { try reminderTimeEvidence($0, context: context) }
            }
            guard try Sync.equal(times(expected.canonicalRecord), times(row)) else { throw Sync.failure("reminder source times contradict the visible civil date fields") }
            return
        }
        var fields = Dictionary(uniqueKeysWithValues: managedKeys(source.kind).compactMap { key in row[key].map { (key, $0) } })
        fields["uid"] = row["uid"] as? String ?? "native-field-validation"
        // These UI-only reminder options are intentionally outside ICS, while
        // their changes are separately stopped by the readonly field group.
        fields.removeValue(forKey: "vorlaufTage")
        _ = try ICalendarExport.encode([fields], context: context, kind: source.kind == .events ? .appointments : .tasks,
            defaultTimeZone: source.displayTimeZone, timestamp: Date(timeIntervalSince1970: 1_800_000_000))
    }

    public static func reproject(record: Sync.Record, nativeFields: [String: Any], source: Sync.Source, context: CalendarTimeContext) throws -> Sync.Record {
        let result: Sync.Snapshot
        switch source.kind {
        case .events:
            let typed = try eventSource(source)
            let native = try SystemSourceSnapshot.Record(source: typed, identifier: record.identifier,
                occurrenceDate: Sync.number(nativeFields["occurrenceDate"]).map { Date(timeIntervalSince1970: $0) }, fields: nativeFields)
            result = try events(SystemSourceSnapshot(source: typed,
                scope: .boundedWindow(start: Date(timeIntervalSince1970: Sync.number(source.scope["start"])!), end: Date(timeIntervalSince1970: Sync.number(source.scope["end"])!)),
                records: [native]), context: context, displayTimeZone: source.displayTimeZone)
        case .reminders:
            result = try reminders(SystemReminderImport.Snapshot(source: reminderSource(source), records: [
                .init(identifier: record.identifier, fields: nativeFields)]), context: context, displayTimeZone: source.displayTimeZone)
        case .contacts:
            result = try contacts(SystemContactImport.Snapshot(source: contactSource(source), records: [
                .init(identifier: record.identifier, title: record.canonicalRecord["anzeigename"] as? String ?? "", fields: nativeFields)]), displayTimeZone: source.displayTimeZone)
        }
        guard result.records.count == 1, result.excluded.isEmpty, let projected = result.records.first else { throw Sync.failure("the changed native fields are not losslessly representable") }
        return projected
    }
    public static func eventSource(_ source: Sync.Source) throws -> SystemSourceSnapshot.Source {
        guard source.kind == .events else { throw Sync.failure("wrong source kind") }
        return try .init(uid: source.sourceUID, kind: .events, title: source.title,
            parentUID: source.metadata["parentUID"] as? String, parentTitle: source.metadata["parentTitle"] as? String,
            parentType: source.metadata["parentType"] as? String, nativeType: Sync.text(source.metadata, "nativeType"),
            permission: Sync.text(source.metadata, "permission"), readOnly: Sync.boolean(source.metadata["readOnly"]) ?? true)
    }
    public static func reminderSource(_ source: Sync.Source) throws -> SystemReminderImport.Source {
        guard source.kind == .reminders else { throw Sync.failure("wrong source kind") }
        return try .init(sourceUID: source.sourceUID, calendarID: Sync.text(source.metadata, "calendarID"), title: source.title,
            parentUID: Sync.text(source.metadata, "parentUID"), parentTitle: Sync.text(source.metadata, "parentTitle"),
            parentType: Sync.text(source.metadata, "parentType"), nativeType: Sync.text(source.metadata, "nativeType"),
            readOnly: Sync.boolean(source.metadata["readOnly"]) ?? true, permission: Sync.text(source.metadata, "permission"))
    }
    public static func contactSource(_ source: Sync.Source) throws -> SystemContactImport.Source {
        guard source.kind == .contacts else { throw Sync.failure("wrong source kind") }
        return try .init(sourceUID: source.sourceUID, containerID: Sync.text(source.metadata, "containerID"), title: source.title,
                         nativeType: Sync.text(source.metadata, "nativeType"))
    }

    private static func safeText(_ object: [String: Any], _ key: String, maximum: Int = 65_536, nonempty: Bool = false, multiline: Bool = false) throws -> String {
        let value = try Sync.text(object, key, empty: !nonempty, maximum: maximum)
        guard value.unicodeScalars.allSatisfy({ $0.value >= 32 && !(0x7F...0x9F).contains($0.value) || multiline && [9, 10, 13].contains($0.value) }),
              !nonempty || !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw Sync.failure("unsupported text") }
        return value
    }
    private static func civil(_ date: String, _ time: String) throws -> ProlepticGregorian.Civil {
        let day = try CalendarCivil.day(date)
        if time.isEmpty { return try ProlepticGregorian.civil(at: day.milliseconds) }
        return try ProlepticGregorian.civil(at: CalendarCivil.wall(date, time, zone: .utc).milliseconds)
    }
    private static func resolve(_ civil: ProlepticGregorian.Civil, _ zone: String, _ context: CalendarTimeContext) throws -> Int64 {
        guard let result = try context.database.resolve(civil, in: context.database.named(zone), fold: .reject, gap: .reject) else {
            throw Sync.failure("ambiguous or nonexistent local time")
        }
        return result
    }
    private static func eventDates(_ desired: [String: Any], original: [String: Any], previous: [String: Any], source: Sync.Source, context: CalendarTimeContext) throws -> [String: Any] {
        let day = try Sync.text(desired, "datum"), lastDay = try Sync.text(desired, "endDatum")
        let clock = try Sync.text(desired, "zeit"), lastClock = try Sync.text(desired, "endZeit")
        guard let allDay = Sync.boolean(desired["ganztag"]), allDay == clock.isEmpty,
              try Sync.text(desired, "icsAnzeigeZeitzone") == (allDay ? (original["timeZone"] as? String ?? source.displayTimeZone) : source.displayTimeZone) else {
            throw Sync.failure("calendar date mode or display zone changed ambiguously")
        }
        let zone = allDay ? original["timeZone"] as? String ?? source.displayTimeZone : source.displayTimeZone
        let start = try civil(day, clock)
        var end = try civil(lastDay.isEmpty ? day : lastDay, allDay ? "" : lastClock.isEmpty ? clock : lastClock)
        if allDay { guard lastClock.isEmpty else { throw Sync.failure("all-day event has a clock") }; end = try end.addingDays(1) }
        let sameMode = Sync.boolean(previous["ganztag"]) == allDay
        let sameStart = sameMode && (previous["datum"] as? String ?? "") == day && (previous["zeit"] as? String ?? "") == clock
        let oldEndDay = (previous["endDatum"] as? String ?? "").isEmpty ? previous["datum"] as? String ?? "" : previous["endDatum"] as? String ?? ""
        let sameEnd = sameMode && oldEndDay == (lastDay.isEmpty ? day : lastDay) && (previous["endZeit"] as? String ?? "") == lastClock
        let first = sameStart ? Int64((Sync.number(original["start"])! * 1000).rounded()) : try resolve(start, zone, context)
        let last = sameEnd ? Int64((Sync.number(original["end"])! * 1000).rounded()) : try resolve(end, zone, context)
        guard last >= first, !allDay || last > first else { throw Sync.failure("invalid event date range") }
        return ["start": Double(first) / 1000, "end": Double(last) / 1000, "allDay": allDay,
                "timeZone": original["timeZone"] ?? (allDay ? zone as Any : NSNull())]
    }
    private static func reminderTimeEvidence(_ line: String, context: CalendarTimeContext) throws -> [String: Any] {
        let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 2 else { throw Sync.failure("invalid reminder source time") }
        let header = parts[0].split(separator: ";", omittingEmptySubsequences: false).map(String.init), value = parts[1]
        guard let name = header.first, ["DTSTART", "DUE"].contains(name), header.count <= 2 else { throw Sync.failure("unsupported reminder source time") }
        if header.count == 2 && header[1] == "VALUE=DATE" {
            guard value.utf8.count == 8 else { throw Sync.failure("invalid reminder DATE") }
            return ["name": name, "mode": "date", "value": try CalendarCivil.parse(value).milliseconds]
        }
        let utc = value.hasSuffix("Z"), digits = utc ? String(value.dropLast()) : value
        guard digits.utf8.count == 15 else { throw Sync.failure("invalid reminder clock") }
        let wall = try CalendarCivil.parse(digits)
        if utc {
            guard header.count == 1 else { throw Sync.failure("UTC reminder clock has a second timezone") }
            return ["name": name, "mode": "instant", "value": wall.milliseconds]
        }
        if header.count == 1 { return ["name": name, "mode": "floating", "value": wall.milliseconds] }
        guard header[1].hasPrefix("TZID=") else { throw Sync.failure("unsupported reminder source timezone") }
        var zone = String(header[1].dropFirst(5))
        if zone.hasPrefix("\""), zone.hasSuffix("\""), zone.count >= 2 { zone = String(zone.dropFirst().dropLast()) }
        return ["name": name, "mode": "instant", "value": try resolve(ProlepticGregorian.civil(at: wall.milliseconds), zone, context)]
    }
    private static func reminderDate(day: String, clock: String, original: Any?, displayZone: String, context: CalendarTimeContext) throws -> Any {
        if day.isEmpty { guard clock.isEmpty else { throw Sync.failure("reminder clock has no date") }; return NSNull() }
        var value = original as? [String: Any] ?? ["calendar": "gregorian"]
        var date = try civil(day, clock)
        guard date.year >= 1000, date.second == 0 else { throw Sync.failure("reminder date is not editable") }
        if !clock.isEmpty, let zone = value["timeZone"] as? String {
            let instant = try resolve(date, displayZone, context)
            date = try context.database.wall(at: instant, in: context.database.named(zone))
            guard try resolve(date, zone, context) == instant else { throw Sync.failure("ambiguous reminder time") }
        }
        value["year"] = date.year; value["month"] = date.month; value["day"] = date.day
        if clock.isEmpty { for key in ["hour", "minute", "second", "nanosecond"] { value.removeValue(forKey: key) } }
        else { value["hour"] = date.hour; value["minute"] = date.minute; value["second"] = 0; value.removeValue(forKey: "nanosecond") }
        return value
    }
    private static func birthday(_ desired: [String: Any], original: Any?) throws -> Any {
        let text = try Sync.text(desired, "geburtstag")
        guard let unknown = Sync.boolean(desired["geburtstagJahrUnbekannt"]) else { throw Sync.failure("missing birthday year semantics") }
        if text.isEmpty { guard !unknown else { throw Sync.failure("empty birthday has an unknown year flag") }; return NSNull() }
        let yearless = text.hasPrefix("--")
        guard yearless == unknown else { throw Sync.failure("birthday year semantics changed") }
        let date = try civil(yearless ? "2000" + text.dropFirst() : text, "")
        guard date.year >= 1000 else { throw Sync.failure("birthday year is not editable") }
        var value = original as? [String: Any] ?? ["calendar": "gregorian"]
        value["month"] = date.month; value["day"] = date.day
        if yearless { value.removeValue(forKey: "year") } else { value["year"] = date.year }
        return value
    }
    private static func contactValues(localKey: String, nativeKey: String, record: Sync.Record, desired: [String: Any]) throws -> [[String: Any]] {
        guard let current = record.canonicalRecord[localKey] as? [[String: Any]], let next = desired[localKey] as? [[String: Any]],
              var native = record.nativeFields[nativeKey] as? [[String: Any]], current.count == next.count, native.count == next.count else {
            throw Sync.failure("adding/removing contact values needs a separate identity-aware operation")
        }
        for index in next.indices {
            guard try Sync.equal(current[index]["typen"] ?? NSNull(), next[index]["typen"] ?? NSNull()),
                  try Sync.equal(current[index]["label"] ?? NSNull(), next[index]["label"] ?? NSNull()) else { throw Sync.failure("contact value labels or order changed") }
            if localKey != "anschriften" {
                guard Set(next[index].keys).isSubset(of: ["wert", "typen", "label"]) else { throw Sync.failure("unsupported contact value") }
                native[index]["value"] = try safeText(next[index], "wert", nonempty: true)
            } else {
                guard var address = native[index]["value"] as? [String: Any] else { throw Sync.failure("invalid native postal address") }
                guard (next[index]["postfach"] as? String ?? "").isEmpty, (next[index]["zusatz"] as? String ?? "").isEmpty,
                      try Sync.equal(current[index]["land"] ?? NSNull(), next[index]["land"] ?? NSNull()) else {
                    throw Sync.failure("postal additions or a country change need an explicit native mapping")
                }
                for (local, remote) in [("strasse", "street"), ("ort", "city"), ("region", "state"), ("plz", "postalCode")] {
                    address[remote] = try safeText(next[index], local, multiline: local == "strasse")
                }
                native[index]["value"] = address
            }
        }
        return native
    }
}
