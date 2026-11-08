import Foundation
import CoreFoundation
import CryptoKit

/// Immutable synchronous rule engine. Production callers supply verified bundle
/// bytes explicitly; this type never reads source paths, environment or OS rules.
public final class NormativeTimeZoneDatabase: Sendable {
    public enum Failure: Error, Equatable, LocalizedError {
        case invalidDatabase, unknownZone, unsupportedZone, invalidInstant, nonexistentWall, ambiguousWall, unresolvedWall
        public var errorDescription: String? {
            switch self {
            case .invalidDatabase: return "Approved timezone data is missing, corrupted or inconsistent."
            case .unknownZone: return "The requested timezone is not in the approved database."
            case .unsupportedZone: return "This timezone explicitly has no defined local-time rules."
            case .invalidInstant: return "Timezone instant is outside the supported calculation range."
            case .nonexistentWall: return "The local clock falls in a timezone gap."
            case .ambiguousWall: return "The local clock has more than one matching instant."
            case .unresolvedWall: return "The local clock cannot be resolved from the approved rules."
            }
        }
    }
    public enum Fold: Sendable { case earlier, later, reject }
    public enum Gap: Sendable { case reject, forward, omit }
    public struct Zone: Hashable, Sendable { public let identifier: String; fileprivate let index: Int, identity: String }
    public struct State: Equatable, Sendable { public let offsetSeconds: Int, abbreviation: String; public let daylight: Bool }
    public static let approvedVersion = "2026egtz"
    public static let approvedPayloadSHA256 = "2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c"
    public static let approvedArchiveSHA256 = "0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d"
    public let version: String, payloadSHA256: String, identifiers: [String]
    private let models: [Model], registry: [String: Int], rejected: Set<String>
    struct ZoneType: Equatable, Sendable { let state: State; let standardFlag: Int, utcFlag: Int }
    struct Transition: Sendable { let second: Int64, type: Int }
    struct Rule: Equatable, Sendable {
        let kind: String, a: Int, b: Int, c: Int, clock: Int
        func wallSecond(year: Int) -> Int64 {
            let day: Int64
            if kind == "M" {
                let first = ProlepticGregorian.days(year, a, 1)
                let weekday = Int((first + 4) % 7 + 7) % 7
                var date = 1 + (c - weekday + 7) % 7 + (b - 1) * 7
                if date > ProlepticGregorian.daysInMonth(year, a) { date -= 7 }
                day = ProlepticGregorian.days(year, a, date)
            } else {
                let ordinal = kind == "J" ? a - 1 + (ProlepticGregorian.isLeapYear(year) && a >= 60 ? 1 : 0) : a
                day = ProlepticGregorian.days(year, 1, 1) + Int64(ordinal)
            }
            return day * 86400 + Int64(clock)
        }
    }
    struct Tail: Equatable, Sendable {
        let standard: State, daylight: State?, start: Rule?, end: Rule?, original: String
    }
    struct Model: Sendable {
        let initial: Int, types: [ZoneType], history: [Transition], tail: Tail, offsets: [Int]
    }
    private struct Edge { let at: Int64; let before: State, after: State }
    private static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    public static func load(payload: Data, manifest: Data) throws -> NormativeTimeZoneDatabase {
        guard payload.count == 428473, manifest.count <= 65536, hash(payload) == approvedPayloadSHA256 else { throw Failure.invalidDatabase }
        guard let manifestText = String(data: manifest, encoding: .utf8) else { throw Failure.invalidDatabase }
        let proof = try Document.object(manifestText)
        guard try integer(proof["schema"]) == 2, proof["tzdbVersion"] as? String == approvedVersion,
              proof["payloadSHA256"] as? String == approvedPayloadSHA256, try integer(proof["payloadBytes"]) == payload.count,
              proof["archiveSHA256"] as? String == approvedArchiveSHA256, proof["payload"] as? String == "tzdb-2026egtz.json",
              try integer(proof["namedZones"]) == 597, try integer(proof["uniqueRuleData"]) == 439 else { throw Failure.invalidDatabase }
        return try decode(payload)
    }
    /// Internal parser is independently negative-tested; public load ALWAYS checks the release SHA first.
    static func decode(_ payload: Data) throws -> NormativeTimeZoneDatabase {
        guard payload.count <= 1_048_576 else { throw Failure.invalidDatabase }
        guard let payloadText = String(data: payload, encoding: .utf8) else { throw Failure.invalidDatabase }
        let root = try Document.object(payloadText)
        guard Set(root.keys) == ["schema", "tzdbVersion", "sourceArchiveSHA256", "zones", "rules", "rejectedZones"],
              try integer(root["schema"]) == 2, root["tzdbVersion"] as? String == approvedVersion,
              root["sourceArchiveSHA256"] as? String == approvedArchiveSHA256,
              let rows = root["rules"] as? [[Any]], !rows.isEmpty, rows.count <= 1024,
              let names = root["zones"] as? [String: Any], names.count <= 2048,
              let exclusions = root["rejectedZones"] as? [String: String], exclusions.count <= 16 else { throw Failure.invalidDatabase }
        var typeCount = 0, transitionCount = 0, stringUnits = 0
        func text(_ value: Any?, limit: Int, empty: Bool = false) throws -> String {
            guard let text = value as? String, text.utf8.count <= limit, empty || !text.isEmpty else { throw Failure.invalidDatabase }
            stringUnits += text.utf16.count
            guard stringUnits <= 1_048_576 else { throw Failure.invalidDatabase }; return text
        }
        // Preflight aggregate counts before allocating parsed models/history.
        for row in rows {
            guard row.count == 4, let types = row[1] as? [[Any]], !types.isEmpty, types.count <= 256,
                  let history = row[2] as? [Any], history.count % 2 == 0, let tail = row[3] as? [Any], tail.count == 7 else { throw Failure.invalidDatabase }
            typeCount += types.count; transitionCount += history.count / 2
            guard typeCount <= 8192, transitionCount <= 100000 else { throw Failure.invalidDatabase }
        }
        var parsed: [Model] = []
        for row in rows {
            let rawTypes = row[1] as! [[Any]], rawHistory = row[2] as! [Any], rawTail = row[3] as! [Any]
            let initial = try integer(row[0]); guard rawTypes.indices.contains(initial) else { throw Failure.invalidDatabase }
            let types: [ZoneType] = try rawTypes.map { type in
                guard type.count == 5 else { throw Failure.invalidDatabase }
                let offset = try integer(type[0]), dst = try integer(type[1]), standard = try integer(type[3]), utc = try integer(type[4])
                let name = try text(type[2], limit: 64, empty: true)
                guard offsetOK(offset), [0, 1].contains(dst), [0, 1].contains(standard), [0, 1].contains(utc),
                      name.utf8.allSatisfy({ (32...126).contains($0) }) else { throw Failure.invalidDatabase }
                return ZoneType(state: State(offsetSeconds: offset, abbreviation: name, daylight: dst == 1), standardFlag: standard, utcFlag: utc)
            }
            var history: [Transition] = []
            for index in stride(from: 0, to: rawHistory.count, by: 2) {
                let second = try int64(rawHistory[index]), type = try integer(rawHistory[index + 1])
                guard (-9_007_199_254_740...9_007_199_254_740).contains(second), types.indices.contains(type),
                      history.last.map({ second > $0.second }) ?? true else { throw Failure.invalidDatabase }
                history.append(Transition(second: second, type: type))
            }
            let std = State(offsetSeconds: try integer(rawTail[0]), abbreviation: try text(rawTail[1], limit: 64), daylight: false)
            let original = try text(rawTail[6], limit: 512)
            let dst: State?, start: Rule?, end: Rule?
            if rawTail[2] is NSNull {
                guard rawTail[3] is NSNull, rawTail[4] is NSNull, rawTail[5] is NSNull,
                      types[history.last?.type ?? initial].state.offsetSeconds == std.offsetSeconds else { throw Failure.invalidDatabase }
                dst = nil; start = nil; end = nil
            } else {
                dst = State(offsetSeconds: try integer(rawTail[2]), abbreviation: try text(rawTail[3], limit: 64), daylight: true)
                start = try rule(rawTail[4]); end = try rule(rawTail[5])
            }
            guard offsetOK(std.offsetSeconds), dst.map({ offsetOK($0.offsetSeconds) }) ?? true else { throw Failure.invalidDatabase }
            let tail = Tail(standard: std, daylight: dst, start: start, end: end, original: original)
            var parser = POSIX(original)
            guard try parser.parse() == tail else { throw Failure.invalidDatabase }
            let offsets = Array(Set(types.map { $0.state.offsetSeconds } + [std.offsetSeconds] + (dst.map { [$0.offsetSeconds] } ?? []))).sorted()
            parsed.append(Model(initial: initial, types: types, history: history, tail: tail, offsets: offsets))
        }
        var registry: [String: Int] = [:]
        for (name, raw) in names {
            _ = try text(name, limit: 255)
            let index = try integer(raw)
            guard validIdentifier(name), parsed.indices.contains(index) else { throw Failure.invalidDatabase }; registry[name] = index
        }
        for (name, reason) in exclusions { _ = try text(name, limit: 255); _ = try text(reason, limit: 128); guard validIdentifier(name), registry[name] == nil else { throw Failure.invalidDatabase } }
        return NormativeTimeZoneDatabase(models: parsed, registry: registry, rejected: Set(exclusions.keys), digest: hash(payload))
    }
    private init(models: [Model], registry: [String: Int], rejected: Set<String>, digest: String) {
        self.models = models; self.registry = registry; self.rejected = rejected
        version = Self.approvedVersion; payloadSHA256 = digest; identifiers = registry.keys.sorted()
    }
    private static func validIdentifier(_ name: String) -> Bool {
        !name.isEmpty && !name.contains("..") && name.utf8.allSatisfy { (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || [95, 43, 46, 47, 45].contains($0) }
    }
    private static func offsetOK(_ value: Int) -> Bool { (-89999...93599).contains(value) }
    private static func int64(_ value: Any?) throws -> Int64 {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
              number.doubleValue.rounded() == number.doubleValue, abs(number.doubleValue) <= 9_007_199_254_740_991 else { throw Failure.invalidDatabase }
        return number.int64Value
    }
    private static func integer(_ value: Any?) throws -> Int { Int(try int64(value)) }
    private static func rule(_ raw: Any) throws -> Rule {
        guard let fields = raw as? [Any], fields.count == 5, let kind = fields[0] as? String else { throw Failure.invalidDatabase }
        let a = try integer(fields[1]), b = try integer(fields[2]), c = try integer(fields[3]), clock = try integer(fields[4])
        guard abs(clock) <= 604799,
              kind == "M" ? (1...12).contains(a) && (1...5).contains(b) && (0...6).contains(c) :
              ["J", "N"].contains(kind) && ((kind == "J" ? 1 : 0)...365).contains(a) && b == 0 && c == 0 else { throw Failure.invalidDatabase }
        return Rule(kind: kind, a: a, b: b, c: c, clock: clock)
    }
    private struct POSIX {
        let original: String, bytes: [UInt8]; var position = 0
        init(_ text: String) { original = text; bytes = Array(text.utf8) }
        var peek: UInt8? { position < bytes.count ? bytes[position] : nil }
        mutating func consume(_ byte: UInt8) throws { guard peek == byte else { throw Failure.invalidDatabase }; position += 1 }
        mutating func number(_ digits: Int) throws -> Int {
            let start = position
            while let byte = peek, (48...57).contains(byte) { position += 1 }
            guard position > start, position - start <= digits, let result = Int(String(decoding: bytes[start..<position], as: UTF8.self)) else { throw Failure.invalidDatabase }; return result
        }
        mutating func token() throws -> String {
            let start: Int
            if peek == 60 {
                position += 1; start = position
                while let byte = peek, byte != 62 { guard (65...90).contains(byte) || (97...122).contains(byte) || (48...57).contains(byte) || byte == 43 || byte == 45 else { throw Failure.invalidDatabase }; position += 1 }
                let end = position; try consume(62)
                guard end - start >= 3 else { throw Failure.invalidDatabase }; return String(decoding: bytes[start..<end], as: UTF8.self)
            }
            start = position
            while let byte = peek, (65...90).contains(byte) || (97...122).contains(byte) { position += 1 }
            guard position - start >= 3 else { throw Failure.invalidDatabase }; return String(decoding: bytes[start..<position], as: UTF8.self)
        }
        mutating func clock(_ limit: Int) throws -> Int {
            var sign = 1
            if peek == 43 { position += 1 } else if peek == 45 { sign = -1; position += 1 }
            let hour = try number(3); var minute = 0, second = 0
            if peek == 58 { position += 1; minute = try number(2); if peek == 58 { position += 1; second = try number(2) } }
            guard hour <= limit, minute <= 59, second <= 59 else { throw Failure.invalidDatabase }
            return sign * (hour * 3600 + minute * 60 + second)
        }
        mutating func dateRule() throws -> Rule {
            let kind: String, a: Int, b: Int, c: Int
            if peek == 77 { position += 1; kind = "M"; a = try number(2); try consume(46); b = try number(1); try consume(46); c = try number(1) }
            else { kind = peek == 74 ? "J" : "N"; if kind == "J" { position += 1 }; a = try number(3); b = 0; c = 0 }
            let seconds: Int
            if peek == 47 { position += 1; seconds = try clock(167) } else { seconds = 7200 }
            return try NormativeTimeZoneDatabase.rule([kind, a, b, c, seconds])
        }
        mutating func parse() throws -> Tail {
            let name = try token(), offset = -(try clock(24))
            let standard = State(offsetSeconds: offset, abbreviation: name, daylight: false)
            if position == bytes.count { return Tail(standard: standard, daylight: nil, start: nil, end: nil, original: original) }
            let daylightName = try token(); let daylightOffset: Int
            if let byte = peek, (48...57).contains(byte) || byte == 43 || byte == 45 { daylightOffset = -(try clock(24)) }
            else { daylightOffset = offset + 3600 }
            try consume(44); let start = try dateRule(); try consume(44); let end = try dateRule()
            guard position == bytes.count else { throw Failure.invalidDatabase }
            return Tail(standard: standard, daylight: State(offsetSeconds: daylightOffset, abbreviation: daylightName, daylight: true), start: start, end: end, original: original)
        }
    }
    public func named(_ identifier: String) throws -> Zone {
        if rejected.contains(identifier) { throw Failure.unsupportedZone }
        if let index = registry[identifier] { return Zone(identifier: identifier, index: index, identity: payloadSHA256) }
        if ["UTC", "GMT", "UT", "Z"].contains(identifier) { return Zone(identifier: identifier, index: -1, identity: payloadSHA256) }
        throw Failure.unknownZone
    }
    func completeModel(for zone: Zone) throws -> Model? {
        guard zone.identity == payloadSHA256 else { throw Failure.invalidDatabase }
        return zone.index == -1 ? nil : models[zone.index]
    }
    private func validateInstant(_ milliseconds: Int64) throws {
        guard milliseconds >= ProlepticGregorian.days(0, 12, 29) * 86400000,
              milliseconds <= ProlepticGregorian.days(10000, 1, 3) * 86400000 else { throw Failure.invalidInstant }
    }
    private func edges(_ model: Model, year: Int) -> [Edge] {
        guard let daylight = model.tail.daylight, let start = model.tail.start, let end = model.tail.end else { return [] }
        return ((year - 1)...(year + 1)).flatMap { year in
            [Edge(at: start.wallSecond(year: year) - Int64(model.tail.standard.offsetSeconds), before: model.tail.standard, after: daylight),
             Edge(at: end.wallSecond(year: year) - Int64(daylight.offsetSeconds), before: daylight, after: model.tail.standard)]
        }
    }
    private func historyIndex(_ model: Model, _ second: Int64) -> Int {
        var low = 0, high = model.history.count
        while low < high { let middle = (low + high) / 2; if model.history[middle].second <= second { low = middle + 1 } else { high = middle } }
        return low
    }
    public func offset(at milliseconds: Int64, in zone: Zone) throws -> State {
        try validateInstant(milliseconds)
        guard let model = try completeModel(for: zone) else { return State(offsetSeconds: 0, abbreviation: "UTC", daylight: false) }
        let second = ProlepticGregorian.floorDiv(milliseconds, 1000), index = historyIndex(model, second)
        let afterHistory = model.history.last.map { milliseconds > $0.second * 1000 } ?? true
        if afterHistory {
            if model.tail.daylight == nil { return model.tail.standard }
            let boundary = model.history.last?.second ?? Int64.min
            let year = ProlepticGregorian.uncheckedParts(milliseconds).year
            if let latest = edges(model, year: year).filter({ $0.at > boundary && $0.at <= second }).max(by: { $0.at < $1.at }) { return latest.after }
        }
        return model.types[index > 0 ? model.history[index - 1].type : model.initial].state
    }
    public func wall(at milliseconds: Int64, in zone: Zone) throws -> ProlepticGregorian.Civil {
        let state = try offset(at: milliseconds, in: zone)
        return try ProlepticGregorian.civil(at: milliseconds + Int64(state.offsetSeconds) * 1000)
    }
    public func resolve(_ wall: ProlepticGregorian.Civil, in zone: Zone, fold: Fold = .earlier, gap: Gap = .reject) throws -> Int64? {
        let model = try completeModel(for: zone), value = wall.epochMilliseconds
        let offsets = model?.offsets ?? [0]
        var candidates: [Int64] = []
        for seconds in offsets {
            let instant = value - Int64(seconds) * 1000
            if try offset(at: instant, in: zone).offsetSeconds == seconds { candidates.append(instant) }
        }
        candidates.sort()
        if let first = candidates.first {
            if candidates.count > 1 && fold == .reject { throw Failure.ambiguousWall }
            return fold == .later ? candidates.last! : first
        }
        guard let model else { throw Failure.unresolvedWall }
        let boundary = model.history.last?.second ?? Int64.min
        var transitions = edges(model, year: wall.year).filter { $0.at > boundary }
        let low = value - Int64(offsets.max()!) * 1000, high = value - Int64(offsets.min()!) * 1000
        var index = historyIndex(model, ProlepticGregorian.floorDiv(low - 1, 1000))
        while index < model.history.count && model.history[index].second * 1000 <= high {
            let transition = model.history[index]
            transitions.append(Edge(at: transition.second,
                before: model.types[index > 0 ? model.history[index - 1].type : model.initial].state, after: model.types[transition.type].state))
            index += 1
        }
        guard let edge = transitions.first(where: { $0.after.offsetSeconds > $0.before.offsetSeconds && value >= ($0.at + Int64($0.before.offsetSeconds)) * 1000 && value < ($0.at + Int64($0.after.offsetSeconds)) * 1000 }) else { throw Failure.unresolvedWall }
        switch gap {
        case .reject: throw Failure.nonexistentWall
        case .omit: return nil
        case .forward: return value - Int64(edge.before.offsetSeconds) * 1000
        }
    }
}
