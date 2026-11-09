import Foundation
import CryptoKit
import Darwin

/// Additive, transport-independent preparation only. The shared note normalizer,
/// explicit preview approval and durable save protocol still own the commit.
public enum NoteFileImport {
    public static let maximumFiles = 32
    public static let maximumBytes = 8 * 1024 * 1024
    public static let maximumTextBytes = 1024 * 1024
    public struct Input {
        public let name: String, data: Data, declaredMIME: String?
        public init(name: String, data: Data, declaredMIME: String? = nil) {
            self.name = name; self.data = data; self.declaredMIME = declaredMIME
        }
    }
    public struct Item {
        public let sourceName: String, sourceSHA256: String, sourceBytes: Int
        public let warnings: [String]
        /// Existing canonical fields only: titel, text, anhaenge. No notebook,
        /// existing record ID or profile replacement authority is inferred.
        public let noteFields: [String: Any]
    }
    public struct Proposal { public let items: [Item]; public let totalBytes: Int }
    private static func failure(_ text: String) -> BetaError { BetaError("Note file import: " + text) }
    private static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    /// Read an explicitly selected regular file through a no-follow descriptor.
    /// Callers retain the selection and must revalidate its digest before commit.
    public static func readSelected(_ url: URL) throws -> Input {
        try readSelected(url, budget: maximumBytes)
    }
    public static func readSelected(_ urls: [URL]) throws -> [Input] {
        guard !urls.isEmpty, urls.count <= maximumFiles else { throw failure("file count limit") }
        var inputs: [Input] = [], remaining = maximumBytes
        for url in urls {
            let input = try readSelected(url, budget: remaining)
            remaining -= input.data.count; inputs.append(input)
        }
        return inputs
    }
    private static func readSelected(_ url: URL, budget: Int) throws -> Input {
        guard url.isFileURL, url.host == nil || url.host == "" else { throw failure("local selected file required") }
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        guard descriptor >= 0 else { throw failure("selected file unavailable or symbolic link") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat(), after = stat()
        guard fstat(descriptor, &before) == 0, before.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              before.st_size > 0, before.st_size <= budget else { throw failure("regular file within byte limit required") }
        var data = Data()
        while true {
            let chunk = try handle.read(upToCount: min(65536, budget - data.count + 1)) ?? Data()
            if chunk.isEmpty { break }
            guard data.count + chunk.count <= budget else { throw failure("file grew beyond byte limit") }
            data.append(chunk)
        }
        guard fstat(descriptor, &after) == 0, before.st_dev == after.st_dev, before.st_ino == after.st_ino,
              before.st_size == after.st_size, data.count == before.st_size,
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec,
              before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec,
              before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec else { throw failure("selected file changed while reading") }
        return Input(name: url.lastPathComponent, data: data)
    }
    public static func revalidate(_ url: URL, sourceSHA256: String) throws {
        guard digest(try readSelected(url).data) == sourceSHA256 else { throw failure("selected source changed before approval") }
    }
    public static func prepare(_ files: [Input]) throws -> Proposal {
        guard !files.isEmpty, files.count <= maximumFiles else { throw failure("file count limit") }
        // Reject the aggregate before base64 or text allocation.
        var total = 0
        for file in files {
            guard !file.data.isEmpty, file.data.count <= maximumBytes - total else { throw failure("aggregate byte limit") }
            total += file.data.count
        }
        var items: [Item] = []
        for file in files {
            guard !file.name.isEmpty, file.name != ".", file.name != "..", file.name.count <= 180,
                  !file.name.contains("/"), !file.name.contains("\\"),
                  file.name.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }) else { throw failure("invalid source filename") }
            let suffix = (file.name as NSString).pathExtension.lowercased()
            let bytes = [UInt8](file.data.prefix(12))
            func starts(_ prefix: [UInt8]) -> Bool { bytes.starts(with: prefix) }
            var mime: String?, kind: String?, extensions: Set<String> = []
            // Same supported signatures and canonical attachment representation
            // as notizAnhangLesen/saubereNotizAnhaenge in the shared application.
            if starts([0xff, 0xd8, 0xff]) { mime = "image/jpeg"; kind = "image"; extensions = ["jpg", "jpeg"] }
            else if starts([137, 80, 78, 71, 13, 10, 26, 10]) { mime = "image/png"; kind = "image"; extensions = ["png"] }
            else if starts([82, 73, 70, 70]), bytes.count >= 12, Array(bytes[8..<12]) == [87, 69, 66, 80] { mime = "image/webp"; kind = "image"; extensions = ["webp"] }
            else if starts([71, 73, 70, 56]), bytes.count >= 6, [55, 57].contains(bytes[4]), bytes[5] == 97 { mime = "image/gif"; kind = "image"; extensions = ["gif"] }
            else if starts([37, 80, 68, 70, 45]) { mime = "application/pdf"; kind = "pdf"; extensions = ["pdf"] }
            var fields: [String: Any], warnings: [String] = []
            let expectedMIME: String
            if let mime, let kind {
                guard extensions.contains(suffix) else { throw failure("signature and filename disagree") }
                let encodedBytes = ((file.data.count + 2) / 3) * 4 + "data:\(mime);base64,".utf8.count
                guard encodedBytes <= 12_000_000 else { throw failure("canonical attachment byte limit") }
                let attachment: [String: Any] = ["id": UUID().uuidString, "name": file.name, "art": kind,
                    "daten": "data:\(mime);base64," + file.data.base64EncodedString()]
                fields = ["titel": file.name, "text": "", "anhaenge": [attachment]]
                expectedMIME = mime
                warnings = ["Original file is imported as an attachment. Apple Notes ink, text structure and metadata are not converted to editable Magnolie objects."]
            } else {
                guard ["txt", "md", "markdown"].contains(suffix), file.data.count <= maximumTextBytes,
                      let text = String(data: file.data, encoding: .utf8),
                      text.unicodeScalars.allSatisfy({ ($0.value >= 32 && $0.value != 127) || $0 == "\n" || $0 == "\r" || $0 == "\t" }) else { throw failure("supported UTF-8 text or attachment required") }
                fields = ["titel": file.name, "text": text, "anhaenge": [[String: Any]]()]
                expectedMIME = suffix == "txt" ? "text/plain" : "text/markdown"
                if suffix != "txt" { warnings = ["Markdown is imported as literal editable source text. Rendered formatting and referenced files are not imported."] }
            }
            if let declared = file.declaredMIME?.lowercased().split(separator: ";").first?.trimmingCharacters(in: .whitespaces),
               declared != expectedMIME && declared != "application/octet-stream" {
                throw failure("declared MIME and content disagree")
            }
            items.append(Item(sourceName: file.name, sourceSHA256: digest(file.data), sourceBytes: file.data.count,
                              warnings: warnings, noteFields: fields))
        }
        return Proposal(items: items, totalBytes: total)
    }
}
