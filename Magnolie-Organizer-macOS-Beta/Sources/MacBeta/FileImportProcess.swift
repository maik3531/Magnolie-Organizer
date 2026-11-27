#if os(macOS)
import Foundation
import Darwin
import BetaCore

/// One process per file, no shell, no inherited Python paths, no output on disk.
/// Call on a worker queue. The stdin descriptor is unlinked before any source
/// bytes are written, avoiding both a visible plaintext copy and pipe deadlocks.
enum FileImportProcess {
    private final class Output {
        private let lock = NSLock()
        private var bytes = Data()
        private var failed = false
        func append(_ block: Data, limit: Int, retain: Bool) -> Bool {
            lock.lock(); defer { lock.unlock() }
            guard !failed, block.count <= limit - bytes.count else { failed = true; return false }
            if retain { bytes.append(block) }
            else { bytes.append(contentsOf: repeatElement(UInt8(0), count: block.count)) }
            return true
        }
        func result() throws -> Data {
            lock.lock(); defer { lock.unlock() }
            guard !failed else { throw BetaError("The import helper exceeded its output limit.") }
            return bytes
        }
    }

    private static func fixedFile(_ root: URL, _ relative: String) throws -> URL {
        let canonicalRoot = root.resolvingSymlinksInPath().standardizedFileURL
        let file = canonicalRoot.appendingPathComponent(relative).standardizedFileURL
        guard file.resolvingSymlinksInPath() == file, file.path.hasPrefix(canonicalRoot.path + "/"),
              (try file.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else {
            throw BetaError("The private import runtime is missing or linked outside the app.")
        }
        return file
    }

    static func readSelected(_ url: URL) throws -> Data {
        guard url.isFileURL, url.host == nil || url.host == "" else { throw BetaError("A local selected file is required.") }
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        guard descriptor >= 0 else { throw BetaError("The selected file is unavailable or is a symbolic link.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat(), after = stat()
        guard fstat(descriptor, &before) == 0, before.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              before.st_size > 0, before.st_size <= Int64(FileImportProtocol.maximumInputBytes) else {
            throw BetaError("Select a regular import file no larger than 32 MiB.")
        }
        var bytes = Data()
        while true {
            let block = try handle.read(upToCount: min(65536, FileImportProtocol.maximumInputBytes - bytes.count + 1)) ?? Data()
            if block.isEmpty { break }
            guard bytes.count + block.count <= FileImportProtocol.maximumInputBytes else { throw BetaError("The selected file grew beyond the import limit.") }
            bytes.append(block)
        }
        guard fstat(descriptor, &after) == 0, before.st_dev == after.st_dev, before.st_ino == after.st_ino,
              before.st_size == after.st_size, Int64(bytes.count) == before.st_size,
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec,
              before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec,
              before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec else {
            throw BetaError("The selected file changed while it was read.")
        }
        return bytes
    }

    static func run(_ input: FileImportProtocol.Input, bundle: URL) throws -> [String: Any] {
        let contents = bundle.resolvingSymlinksInPath().appendingPathComponent("Contents")
        let executable = try fixedFile(contents, "Helpers/ImportPython.app/Contents/MacOS/python3.15")
        let helper = try fixedFile(contents, "Resources/ImportHelper/helper.py")
        let manifest = try fixedFile(contents, "Resources/ImportHelper/manifest.json")
        let manifestBytes = try Data(contentsOf: manifest, options: [.mappedIfSafe])
        guard manifestBytes.count <= 512 * 1024 else { throw BetaError("Invalid import manifest size.") }
        let manifestHash = FileImportProtocol.digest(manifestBytes)
        var template = Array((NSTemporaryDirectory() + "magnolie-import-XXXXXX").utf8CString)
        let descriptor = template.withUnsafeMutableBufferPointer { mkstemp($0.baseAddress!) }
        guard descriptor >= 0 else { throw BetaError("Cannot prepare the private import stream.") }
        let standardInput = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? standardInput.close() }
        guard template.withUnsafeBufferPointer({ unlink($0.baseAddress!) }) == 0 else {
            throw BetaError("Cannot unlink the private import stream.")
        }
        guard fcntl(descriptor, F_SETFD, FD_CLOEXEC) == 0 else {
            throw BetaError("Cannot prepare the private import stream.")
        }
        try standardInput.write(contentsOf: input.header)
        try standardInput.write(contentsOf: input.bytes)
        try standardInput.seek(toOffset: 0)

        let process = Process(), stdout = Pipe(), stderr = Pipe()
        process.executableURL = executable
        process.arguments = ["-I", "-S", "-B", helper.path]
        process.environment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"]
        process.currentDirectoryURL = helper.deletingLastPathComponent()
        process.standardInput = standardInput; process.standardOutput = stdout; process.standardError = stderr
        let ended = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in ended.signal() }
        let output = Output(), diagnostics = Output(), readers = DispatchGroup()
        try process.run()
        for (handle, accumulator, limit, retain) in [
            (stdout.fileHandleForReading, output, FileImportProtocol.maximumOutputBytes, true),
            (stderr.fileHandleForReading, diagnostics, 65536, false)
        ] {
            readers.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                defer { try? handle.close(); readers.leave() }
                do {
                    while let block = try handle.read(upToCount: 65536), !block.isEmpty {
                        if !accumulator.append(block, limit: limit, retain: retain) {
                            if process.isRunning { process.terminate() }
                            return
                        }
                    }
                } catch {
                    _ = accumulator.append(Data([0]), limit: 0, retain: false)
                    if process.isRunning { process.terminate() }
                }
            }
        }
        if ended.wait(timeout: .now() + 60) == .timedOut {
            if process.isRunning { process.terminate() }
            if ended.wait(timeout: .now() + 1) == .timedOut, process.isRunning { kill(process.processIdentifier, SIGKILL) }
            _ = ended.wait(timeout: .now() + 2)
            _ = readers.wait(timeout: .now() + 2)
            throw BetaError("The file import exceeded its time limit. No import result was applied.")
        }
        guard readers.wait(timeout: .now() + 2) == .success else {
            throw BetaError("The import helper did not close its response streams.")
        }
        _ = try diagnostics.result() // Never expose source-containing stderr.
        let bytes = try output.result()
        guard process.terminationReason == .exit, process.terminationStatus == 0 else {
            // A well-formed helper error may explain unsupported/corrupt data.
            _ = try FileImportProtocol.response(bytes, input: input, manifestSHA256: manifestHash)
            throw BetaError("The import helper exited without a successful result.")
        }
        return try FileImportProtocol.response(bytes, input: input, manifestSHA256: manifestHash)
    }
}
#endif
