import Foundation
import BetaCore

/// Test utility only. Explicit argv paths; the production database has no path
/// lookup or environment fallback. Protocol matches check-independent.py.
@main private struct Worker {
    static func civil(_ raw: Any) throws -> ProlepticGregorian.Civil {
        guard let fields = raw as? [Int], fields.count == 7 else { throw BetaError("Invalid oracle civil vector.") }
        return try .init(year: fields[0], month: fields[1], day: fields[2], hour: fields[3], minute: fields[4], second: fields[5], millisecond: fields[6])
    }
    static func main() {
        do {
            guard [3, 4].contains(CommandLine.arguments.count) else { throw BetaError("Explicit payload and manifest arguments required.") }
            let db = try NormativeTimeZoneDatabase.load(payload: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])), manifest: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
            if CommandLine.arguments.count == 4 {
                guard CommandLine.arguments[3] == "--definitions" else { throw BetaError("Unknown oracle mode.") }
                for identifier in db.identifiers {
                    let lines = try NormativeTimeZoneDefinition.definition(identifier, database: db)
                    let reply = try Document.encode(["identifier": identifier, "lines": lines]) + "\n"
                    try FileHandle.standardOutput.write(contentsOf: Data(reply.utf8))
                }
                return
            }
            while let line = readLine() {
                guard line.utf8.count <= 2 * 1024 * 1024,
                      let rows = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [[Any]], rows.count <= 2000 else { throw BetaError("Oracle batch limit/shape.") }
                var failures: [[String: Any]] = []
                for row in rows {
                    do {
                        guard let code = row.first as? String else { throw BetaError("Missing oracle operation.") }
                        func require(_ condition: Bool, _ message: String) throws { if !condition { throw BetaError(message) } }
                        if code == "c" {
                            guard row.count == 4, let expected = row[2] as? NSNumber, let weekday = row[3] as? Int else { throw BetaError("Invalid civil oracle.") }
                            let input = try civil(row[1])
                            try require(input.epochMilliseconds == expected.int64Value, "Civil epoch differs from Python")
                            try require(try ProlepticGregorian.civil(at: expected.int64Value) == input, "Civil roundtrip differs from Python")
                            try require(ProlepticGregorian.weekday(input) == weekday, "Gregorian weekday differs from Python")
                        } else if code == "o" {
                            guard row.count == 5, let identifier = row[1] as? String, let instant = row[2] as? NSNumber,
                                  let offset = row[3] as? Int, let parts = row[4] as? [Int] else { throw BetaError("Invalid offset oracle.") }
                            let zone = try db.named(identifier)
                            try require(try db.offset(at: instant.int64Value, in: zone).offsetSeconds == offset, "Offset differs from independent zic/ZoneInfo")
                            try require(try db.wall(at: instant.int64Value, in: zone).fields == parts, "Wall fields differ from independent zic/ZoneInfo")
                        } else if code == "w" {
                            guard row.count == 5, let identifier = row[1] as? String, let valid = row[3] as? [Int64] else { throw BetaError("Invalid wall oracle.") }
                            let zone = try db.named(identifier), wall = try civil(row[2])
                            if !valid.isEmpty {
                                try require(try db.resolve(wall, in: zone, fold: .earlier) == valid.first!, "Earlier fold differs from Python")
                                try require(try db.resolve(wall, in: zone, fold: .later) == valid.last!, "Later fold differs from Python")
                                if valid.count > 1 {
                                    do { _ = try db.resolve(wall, in: zone, fold: .reject); throw BetaError("Ambiguous wall was accepted") }
                                    catch NormativeTimeZoneDatabase.Failure.ambiguousWall { }
                                }
                            } else {
                                do { _ = try db.resolve(wall, in: zone); throw BetaError("Nonexistent wall was accepted") }
                                catch NormativeTimeZoneDatabase.Failure.nonexistentWall { }
                                try require(try db.resolve(wall, in: zone, gap: .omit) == nil, "Gap omit must return nil")
                                guard let forward = row[4] as? NSNumber else { throw BetaError("Missing forward gap oracle.") }
                                try require(try db.resolve(wall, in: zone, gap: .forward) == forward.int64Value, "Forward gap differs from Python")
                            }
                        } else { throw BetaError("Unknown oracle operation.") }
                    } catch {
                        failures.append(["identifier": row.count > 1 ? String(describing: row[1]) : "missing", "sample": row, "error": String(describing: error)])
                    }
                }
                let reply = try Document.encode(["checked": rows.count, "failures": failures]) + "\n"
                try FileHandle.standardOutput.write(contentsOf: Data(reply.utf8))
            }
        } catch {
            print((try? Document.encode(["error": String(describing: error)])) ?? "{\"error\":\"oracle worker failed\"}"); exit(1)
        }
    }
}
