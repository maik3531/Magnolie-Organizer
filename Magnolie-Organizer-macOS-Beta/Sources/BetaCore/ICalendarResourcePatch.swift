import Foundation

/// Surgical resource editing. Identities never imply series-wide deletion.
/// Untouched bytes (including opaque components) remain the server's original bytes.
public enum ICalendarResourcePatch {
    public struct Key: Hashable {
        public let kind: String, uid: String, recurrenceID: String?
        /// recurrenceID is the complete unfolded RECURRENCE-ID content line, including parameters.
        public init(kind: String, uid: String, recurrenceID: String? = nil) {
            self.kind = kind; self.uid = uid; self.recurrenceID = recurrenceID
        }
        private var identity: OpaqueUTF8Identity {
            OpaqueUTF8Identity(parts: [kind, uid, recurrenceID == nil ? "absent" : "present", recurrenceID ?? ""])
        }
        public static func == (lhs: Self, rhs: Self) -> Bool { lhs.identity == rhs.identity }
        public func hash(into hasher: inout Hasher) { hasher.combine(identity) }
    }
    public struct Replacement {
        public let key: Key, calendar: Data
        public init(key: Key, calendar: Data) { self.key = key; self.calendar = calendar }
    }
    public struct Result {
        public let data: Data
        /// True only if no non-timezone components remain. Caller still owns HTTP preconditions.
        public let safeCanDeleteResource: Bool
    }
    private struct Line { var text: String; let start: Int; var end: Int; var unfoldedBytes: Int }
    private struct Part { let name: String, range: Range<Int>, properties: [String]; let key: Key? }
    private struct Calendar { let bytes: Data, parts: [Part], end: Int }
    private static func fail(_ message: String) -> BetaError { BetaError("Calendar resource patch: " + message) }
    private static func property(_ line: String) throws -> (String, String, String) {
        var quoted = false
        for i in line.indices {
            if line[i] == "\"" { quoted.toggle() }
            if line[i] == ":" && !quoted {
                let header = String(line[..<i]), value = String(line[line.index(after: i)...])
                let name = String(header.prefix { $0 != ";" }).uppercased()
                guard !name.isEmpty, name.utf8.allSatisfy({ (65...90).contains($0) || (48...57).contains($0) || $0 == 45 }) else { throw fail("invalid property") }
                return (name, header, value)
            }
        }
        throw fail("invalid property separator")
    }
    private static func text(_ value: String) throws -> String {
        var result = "", escaped = false
        for character in value {
            if escaped {
                switch character {
                case "n", "N": result.append("\n")
                case "\\", ",", ";": result.append(character)
                default: throw fail("invalid UID escape")
                }
                escaped = false
            } else if character == "\\" { escaped = true } else { result.append(character) }
        }
        guard !escaped, !result.isEmpty else { throw fail("invalid UID") }
        return result
    }
    private static func canonical(_ key: Key) throws -> Key {
        guard ["VEVENT", "VTODO"].contains(key.kind), !key.uid.isEmpty else { throw fail("invalid target kind/UID") }
        var rid: String?
        if let line = key.recurrenceID {
            let (name, header, value) = try property(line)
            guard name == "RECURRENCE-ID", !value.isEmpty, !line.contains("\r"), !line.contains("\n") else { throw fail("invalid recurrence identity") }
            // Parameter order and name case do not distinguish component identities.
            // RANGE changes behavior, not identity. TZID values remain case-sensitive.
            var fields: [String] = [], field = "", quoted = false
            for c in header {
                if c == "\"" { quoted.toggle() }
                if c == ";" && !quoted { fields.append(field); field = "" } else { field.append(c) }
            }
            guard !quoted else { throw fail("invalid recurrence quoting") }
            fields.append(field)
            var normalized: [String] = [], names = Set<String>()
            for parameter in fields.dropFirst() {
                let pair = parameter.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
                guard pair.count == 2, !pair[0].isEmpty, !pair[1].isEmpty, names.insert(String(pair[0]).uppercased()).inserted else { throw fail("invalid recurrence parameter") }
                let parameterName = String(pair[0]).uppercased()
                var parameterValue = String(pair[1])
                if parameterValue.hasPrefix("\"") {
                    guard parameterValue.hasSuffix("\""), parameterValue.count >= 2 else { throw fail("invalid recurrence quoting") }
                    parameterValue = String(parameterValue.dropFirst().dropLast())
                }
                if parameterName == "RANGE" { continue }
                if parameterName == "VALUE" && parameterValue.uppercased() == "DATE-TIME" { continue }
                if parameterName == "VALUE" { parameterValue = parameterValue.uppercased() }
                let quotedValue = parameterValue.contains(";") || parameterValue.contains(":") || parameterValue.contains(",")
                normalized.append(parameterName + "=" + (quotedValue ? "\"" + parameterValue + "\"" : parameterValue))
            }
            rid = name + normalized.sorted().map { ";" + $0 }.joined() + ":" + value
        }
        return Key(kind: key.kind, uid: key.uid, recurrenceID: rid)
    }
    private static func parse(_ data: Data) throws -> Calendar {
        guard !data.isEmpty, data.count <= ICalendarImport.maximumBytes, String(data: data, encoding: .utf8) != nil else { throw fail("invalid size/UTF-8") }
        let bytes = [UInt8](data); var lines: [Line] = [], offset = 0, physicalLines = 0
        let maximumLines = 250_000, maximumLineBytes = 1024 * 1024
        while offset < bytes.count {
            physicalLines += 1
            guard physicalLines <= maximumLines else { throw fail("physical line limit") }
            let start = offset
            while offset < bytes.count && bytes[offset] != 10 {
                offset += 1
                // Allow a single trailing CR before LF without allocating its String.
                guard offset - start <= maximumLineBytes + 1 else { throw fail("physical line size limit") }
            }
            var stop = offset
            if offset < bytes.count && stop > start && bytes[stop - 1] == 13 { stop -= 1 }
            guard stop - start <= maximumLineBytes else { throw fail("physical line size limit") }
            guard bytes[start..<stop].allSatisfy({ ($0 >= 32 && $0 != 127) || $0 == 9 }) else { throw fail("invalid control character") }
            if offset < bytes.count { offset += 1 }
            let value = String(decoding: bytes[start..<stop], as: UTF8.self)
            if value.hasPrefix(" ") || value.hasPrefix("\t") {
                guard !lines.isEmpty else { throw fail("orphan fold") }
                let unfoldedBytes = lines[lines.count - 1].unfoldedBytes + stop - start - 1
                guard unfoldedBytes <= maximumLineBytes else { throw fail("unfolded line size limit") }
                lines[lines.count - 1].text += value.dropFirst(); lines[lines.count - 1].end = offset
                lines[lines.count - 1].unfoldedBytes = unfoldedBytes
            } else {
                guard lines.count < maximumLines else { throw fail("logical line limit") }
                lines.append(Line(text: value, start: start, end: offset, unfoldedBytes: stop - start))
            }
        }
        guard lines.first?.text.uppercased() == "BEGIN:VCALENDAR", lines.last?.text.uppercased() == "END:VCALENDAR" else { throw fail("single calendar wrapper required") }
        var stack: [String] = [], parts: [Part] = [], start = 0, properties: [String] = [], end = 0
        for line in lines {
            let (name, header, value) = try property(line.text)
            if name == "BEGIN" {
                guard header.uppercased() == name, !value.isEmpty else { throw fail("invalid component") }
                if stack.isEmpty { guard line.start == 0, value.uppercased() == "VCALENDAR" else { throw fail("multiple wrappers") } }
                else {
                    guard value.uppercased() != "VCALENDAR" else { throw fail("nested calendar") }
                    if stack.count == 1 { start = line.start; properties = [] }
                }
                stack.append(value.uppercased())
                guard stack.count <= 32 else { throw fail("nesting limit") }
            } else if name == "END" {
                guard header.uppercased() == name, stack.last == value.uppercased() else { throw fail("unbalanced component") }
                if stack.count == 2 {
                    let kind = stack.last!; var key: Key?
                    if kind == "VEVENT" || kind == "VTODO" {
                        let ids = try properties.filter { try property($0).0 == "UID" }
                        let rids = try properties.filter { try property($0).0 == "RECURRENCE-ID" }
                        guard ids.count == 1, rids.count <= 1 else { throw fail("ambiguous UID/recurrence identity") }
                        key = try canonical(Key(kind: kind, uid: text(property(ids[0]).2), recurrenceID: rids.first))
                    }
                    parts.append(Part(name: kind, range: start..<line.end, properties: properties, key: key))
                    guard parts.count <= ICalendarImport.maximumRecords else { throw fail("component limit") }
                }
                stack.removeLast()
                if stack.isEmpty { end = line.start }
            } else {
                guard !stack.isEmpty else { throw fail("property outside wrapper") }
                if stack.count == 2 { properties.append(line.text) }
            }
        }
        guard stack.isEmpty else { throw fail("unclosed component") }
        var identities = Set<Key>()
        for part in parts { if let key = part.key, !identities.insert(key).inserted { throw fail("duplicate identity") } }
        return Calendar(bytes: data, parts: parts, end: end)
    }
    private static func zones(_ calendar: Calendar) throws -> [OpaqueUTF8Identity: Data] {
        var result: [OpaqueUTF8Identity: Data] = [:]
        for part in calendar.parts where part.name == "VTIMEZONE" {
            let ids = try part.properties.filter { try property($0).0 == "TZID" }
            guard ids.count == 1 else { throw fail("ambiguous timezone") }
            let id = OpaqueUTF8Identity(try text(property(ids[0]).2))
            guard result[id] == nil else { throw fail("duplicate timezone") }
            result[id] = calendar.bytes.subdata(in: part.range)
        }
        return result
    }
    /// Canonical wire identities only: UTC, floating and TZID forms are never equated.
    public static func keys(from original: Data) throws -> [Key] {
        try parse(original).parts.compactMap { $0.key }
    }
    /// Extract selected components in one parse. Returned keys use the same canonical identity
    /// as keys(from:). Wrapper properties and source VTIMEZONE bytes are retained exactly;
    /// other components are intentionally excluded from these single-component calendars.
    public static func extract(original: Data, keys requested: [Key], maximumOutputBytes: Int = ICalendarImport.maximumProjectedBytes) throws -> [Key: Data] {
        guard maximumOutputBytes > 0, maximumOutputBytes <= ICalendarImport.maximumProjectedBytes,
              requested.count <= ICalendarImport.maximumRecords else { throw fail("extraction limit") }
        let calendar = try parse(original)
        var selected: [Key] = [], seen = Set<Key>()
        let indexed = Dictionary(uniqueKeysWithValues: calendar.parts.compactMap { part in part.key.map { ($0, part) } })
        for input in requested {
            let key = try canonical(input)
            guard seen.insert(key).inserted, indexed[key] != nil else { throw fail("duplicate or missing extraction target") }
            selected.append(key)
        }
        var prefix = Data(), cursor = 0
        for part in calendar.parts {
            prefix.append(calendar.bytes.subdata(in: cursor..<part.range.lowerBound))
            if part.name == "VTIMEZONE" { prefix.append(calendar.bytes.subdata(in: part.range)) }
            cursor = part.range.upperBound
        }
        prefix.append(calendar.bytes.subdata(in: cursor..<calendar.end))
        let suffix = calendar.bytes.subdata(in: calendar.end..<calendar.bytes.count)
        var total = 0
        for key in selected {
            let size = prefix.count + indexed[key]!.range.count + suffix.count
            guard size <= ICalendarImport.maximumBytes, size <= maximumOutputBytes - total else { throw fail("aggregate extraction size limit") }
            total += size
        }
        var result: [Key: Data] = [:]
        for key in selected {
            var output = prefix
            output.append(calendar.bytes.subdata(in: indexed[key]!.range)); output.append(suffix)
            result[key] = output
        }
        return result
    }
    /// Replacements require an existing key; insertions require an absent key.
    /// Conflicting timezone definitions are refused rather than rewritten.
    public static func apply(original: Data, replacements: [Replacement], insertions: [Replacement] = [], deletions: [Key] = []) throws -> Result {
        guard replacements.reduce(0, { $0 + $1.calendar.count }) + insertions.reduce(0, { $0 + $1.calendar.count }) <= ICalendarImport.maximumBytes else { throw fail("aggregate input size limit") }
        let old = try parse(original)
        guard replacements.count + insertions.count + deletions.count <= ICalendarImport.maximumRecords else { throw fail("operation limit") }
        var timezoneDefinitions = try zones(old), edited = Set<Key>(), remove = Set<Key>(), updates: [Key: Data] = [:], appended = Data()
        let existing = Set(old.parts.compactMap { $0.key })
        for key in deletions {
            let target = try canonical(key)
            guard existing.contains(target), edited.insert(target).inserted else { throw fail("missing/duplicate deletion") }
            remove.insert(target)
        }
        for (replacement, inserting) in replacements.map({ ($0, false) }) + insertions.map({ ($0, true) }) {
            let target = try canonical(replacement.key)
            guard existing.contains(target) != inserting, edited.insert(target).inserted else { throw fail("missing replacement/existing insertion/conflicting operations") }
            let input = try parse(replacement.calendar)
            let components = input.parts.filter { $0.name != "VTIMEZONE" }
            guard components.count == 1, components[0].key == target else { throw fail("replacement identity mismatch/opaque component") }
            for (id, definition) in try zones(input).sorted(by: { $0.key < $1.key }) {
                if let prior = timezoneDefinitions[id] { guard prior == definition else { throw fail("conflicting timezone definition") } }
                else { timezoneDefinitions[id] = definition; appended.append(definition) }
            }
            let component = input.bytes.subdata(in: components[0].range)
            if existing.contains(target) { updates[target] = component } else { appended.append(component) }
        }
        var output = Data(), cursor = 0
        for part in old.parts {
            output.append(old.bytes.subdata(in: cursor..<part.range.lowerBound))
            if let key = part.key, remove.contains(key) { /* exact deletion */ }
            else if let key = part.key, let update = updates[key] { output.append(update) }
            else { output.append(old.bytes.subdata(in: part.range)) }
            cursor = part.range.upperBound
        }
        output.append(old.bytes.subdata(in: cursor..<old.end)); output.append(appended)
        output.append(old.bytes.subdata(in: old.end..<old.bytes.count))
        guard output.count <= ICalendarImport.maximumBytes else { throw fail("result size limit") }
        let result = try parse(output)
        return Result(data: output, safeCanDeleteResource: result.parts.allSatisfy { $0.name == "VTIMEZONE" })
    }
}
