import Foundation

public enum CalendarExport {
    // Deliberately not a replacement for the desktop's full recurrence/roundtrip codec.
    // Refuse rich records rather than flattening them into misleading VEVENTs.
    public static func appointments(_ records: [[String: Any]]) throws -> String {
        guard !records.isEmpty else { throw BetaError("No appointments to export.") }
        var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie Organizer macOS Beta//EN", "CALSCALE:GREGORIAN"]
        let date = DateFormatter()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        date.calendar = calendar
        date.locale = Locale(identifier: "en_US_POSIX")
        date.timeZone = calendar.timeZone
        date.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        let stamp = date.string(from: Date())
        date.dateFormat = "yyyy-MM-dd"; date.isLenient = false
        let allowed: Set<String> = ["id", "uid", "titel", "datum", "zeit", "endZeit", "endDatum", "notiz", "ort",
            "ganztag", "angelegt", "geaendert", "personalGeaendert", "wiederholung", "standardErinnerung", "icsRoundtrip"]
        func meaningful(_ value: Any) -> Bool {
            if value is NSNull { return false }
            if let s = value as? String { return !s.isEmpty }
            if let a = value as? [Any] { return !a.isEmpty }
            if let d = value as? [String: Any] { return d.values.contains(where: meaningful) }
            if let n = value as? NSNumber { return n.doubleValue != 0 }
            return true
        }
        func escape(_ text: String) -> String {
            text.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\r\n", with: "\n")
                .replacingOccurrences(of: "\r", with: "\n").replacingOccurrences(of: "\n", with: "\\n")
                .replacingOccurrences(of: ";", with: "\\;").replacingOccurrences(of: ",", with: "\\,")
        }
        for record in records {
            guard !record.contains(where: { !allowed.contains($0.key) && meaningful($0.value) }) else {
                throw BetaError("ICS Beta supports simple appointments only. Use full JSON backup for lossless export.")
            }
            if let value = record["wiederholung"] {
                guard let repetition = value as? [String: Any], repetition["art"] as? String == "none",
                      repetition.allSatisfy({ $0.key == "art" || !meaningful($0.value) }) else {
                    throw BetaError("Recurring appointments require the full desktop ICS codec; export refused.")
                }
            }
            guard let day = record["datum"] as? String, let startDate = date.date(from: day), date.string(from: startDate) == day,
                  let title = record["titel"] as? String, !title.isEmpty else { throw BetaError("Invalid appointment.") }
            let endDay = (record["endDatum"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? day
            guard let endDate = date.date(from: endDay), date.string(from: endDate) == endDay, endDate >= startDate else {
                throw BetaError("Invalid appointment end date.")
            }
            let time = record["zeit"] as? String ?? "", end = record["endZeit"] as? String ?? ""
            let allDay = record["ganztag"] as? Bool == true || time.isEmpty
            let uid = (record["uid"] as? String).flatMap { $0.isEmpty ? nil : $0 }
                ?? ((record["id"] as? String ?? UUID().uuidString) + "@magnolie-macos-beta")
            let eventStart = lines.count
            lines += ["BEGIN:VEVENT", "UID:" + escape(uid), "DTSTAMP:" + stamp, "SUMMARY:" + escape(title)]
            if allDay {
                guard time.isEmpty, end.isEmpty else { throw BetaError("Ambiguous all-day appointment.") }
                let next = calendar.date(byAdding: .day, value: 1, to: endDate)!
                lines += ["DTSTART;VALUE=DATE:" + day.replacingOccurrences(of: "-", with: ""),
                          "DTEND;VALUE=DATE:" + date.string(from: next).replacingOccurrences(of: "-", with: "")]
            } else {
                let pattern = "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
                guard time.range(of: pattern, options: .regularExpression) != nil,
                      end.range(of: pattern, options: .regularExpression) != nil,
                      endDay > day || end > time else { throw BetaError("Invalid appointment time range.") }
                lines += ["DTSTART:" + day.replacingOccurrences(of: "-", with: "") + "T" + time.replacingOccurrences(of: ":", with: "") + "00",
                          "DTEND:" + endDay.replacingOccurrences(of: "-", with: "") + "T" + end.replacingOccurrences(of: ":", with: "") + "00"]
            }
            for (key, name) in [("notiz", "DESCRIPTION"), ("ort", "LOCATION")] {
                if let text = record[key] as? String, !text.isEmpty { lines.append(name + ":" + escape(text)) }
            }
            // The ordinary desktop editor mirrors LOCATION and edited times into raw ICS.
            // Reconcile only supported duplicates, preserving timezone semantics, never discard raw data blindly.
            guard let raw = (record["icsRoundtrip"] ?? [String]()) as? [String] else {
                throw BetaError("Invalid raw calendar properties.")
            }
            var seen: Set<String> = []
            var timeZones: [String: String] = [:]
            for line in raw {
                let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                let header = parts[0], name = String(header.prefix(while: { $0 != ";" }))
                guard parts.count == 2, !line.contains("\r"), !line.contains("\n"),
                      ["LOCATION", "SUMMARY", "DESCRIPTION", "UID", "DTSTART", "DTEND"].contains(name),
                      seen.insert(name).inserted,
                      let index = (eventStart..<lines.count).first(where: {
                          lines[$0].hasPrefix(name + ":") || lines[$0].hasPrefix(name + ";")
                      }) else {
                    throw BetaError("Unsupported or duplicate raw calendar property; export refused.")
                }
                let expected = lines[index].split(separator: ":", maxSplits: 1).map(String.init)
                if !["DTSTART", "DTEND"].contains(name) || allDay {
                    guard line == lines[index] else { throw BetaError("Raw calendar data contradicts structured fields or uses unsupported parameters.") }
                } else {
                    let utc = parts[1].hasSuffix("Z")
                    guard parts[1] == expected[1] + (utc ? "Z" : "") else {
                        throw BetaError("Raw calendar time contradicts structured fields.")
                    }
                    if header == name {
                        lines[index] = line
                        timeZones[name] = utc ? "UTC" : ""
                    } else if header.hasPrefix(name + ";TZID="), !utc {
                        let zone = String(header.dropFirst((name + ";TZID=").count))
                        guard zone.isEmpty || (zone.range(of: "^[A-Za-z0-9_+./-]+$", options: .regularExpression) != nil &&
                                               TimeZone(identifier: zone) != nil) else {
                            throw BetaError("Unsupported calendar timezone.")
                        }
                        // The editor emits an empty TZID for system/floating time. It carries no zone to retain.
                        lines[index] = zone.isEmpty ? name + ":" + parts[1] : line
                        timeZones[name] = zone
                    } else { throw BetaError("Unsupported calendar time parameters.") }
                }
            }
            if timeZones.values.contains(where: { !$0.isEmpty }) {
                guard timeZones.count == 2, timeZones["DTSTART"] == timeZones["DTEND"] else {
                    throw BetaError("Raw start/end timezone representations are incomplete or inconsistent.")
                }
            }
            lines.append("END:VEVENT")
        }
        lines.append("END:VCALENDAR")
        return lines.map { line in
            var result = "", width = 0
            for scalar in line.unicodeScalars {
                let text = String(scalar), size = text.utf8.count
                if width + size > 75 { result += "\r\n "; width = 1 }
                result += text; width += size
            }
            return result
        }.joined(separator: "\r\n") + "\r\n"
    }
}
