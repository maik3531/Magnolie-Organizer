import Foundation

/// Refs #455. A key for opaque protocol identities, never a replacement for UI text.
/// Swift String equality is canonically equivalent; UID/TZID/path identity must retain
/// the decoded scalar sequence. Original model strings and request URLs stay unchanged.
public struct OpaqueUTF8Identity: Hashable, Comparable, Sendable {
    public let bytes: Data
    private let components: [Data]?
    public init(_ raw: String) { bytes = Data(raw.utf8); components = nil }
    /// Count + fixed-width byte lengths make components unambiguous, including NULs.
    public init(parts: [String]) {
        var encoded = Data()
        func appendLength(_ value: Int) {
            var length = UInt64(value).bigEndian
            withUnsafeBytes(of: &length) { encoded.append(contentsOf: $0) }
        }
        let encodedParts = parts.map { Data($0.utf8) }
        appendLength(encodedParts.count)
        for part in encodedParts { appendLength(part.count); encoded.append(part) }
        bytes = encoded; components = encodedParts
    }
    public static func == (lhs: Self, rhs: Self) -> Bool { (lhs.components == nil) == (rhs.components == nil) && lhs.bytes == rhs.bytes }
    public func hash(into hasher: inout Hasher) { hasher.combine(components == nil); hasher.combine(bytes) }
    public static func < (lhs: Self, rhs: Self) -> Bool {
        if let left = lhs.components, let right = rhs.components {
            return left.lexicographicallyPrecedes(right) { $0.lexicographicallyPrecedes($1) }
        }
        if (lhs.components == nil) != (rhs.components == nil) { return lhs.components == nil }
        return lhs.bytes.lexicographicallyPrecedes(rhs.bytes)
    }
}
