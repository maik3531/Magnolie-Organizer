// Refs #785: native process boundary only. This probe is never put in the app.
// The driver compiles the original FileImportProcess.swift beside this file.
#if os(macOS)
import Foundation
import Darwin
import BetaCore

private struct ProbeFailure: Error {
    let message: String
    init(_ message: String) { self.message = message }
}

private func require(_ condition: Bool, _ message: String) throws {
    guard condition else { throw ProbeFailure(message) }
}

private func requireRejection(_ expected: String, _ label: String,
                              _ operation: () throws -> Void) throws {
    do {
        try operation()
        throw ProbeFailure(label + " was accepted")
    } catch let error as BetaError {
        try require(error.errorDescription == expected, label + " returned a different error")
    }
}

private func equalJSONValue(_ actual: Any, _ expected: Any) throws -> Bool {
    // A wrapper preserves the JSON distinction between booleans and numbers.
    try JSONSerialization.data(withJSONObject: ["value": actual], options: [.sortedKeys]) ==
        JSONSerialization.data(withJSONObject: ["value": expected], options: [.sortedKeys])
}

private func exercise(bundle: URL, directory: URL) throws -> [String: Any] {
    let oracleBytes = try Data(contentsOf: directory.appendingPathComponent("expected.json"))
    try require(oracleBytes.count <= 65536, "fixture oracle size")
    guard let oracle = try JSONSerialization.jsonObject(with: oracleBytes) as? [String: Any],
          let expected = oracle["expected"] as? [String: [String: Any]],
          let sourceHash = oracle["sourceSHA256"] as? String,
          let byteCount = oracle["bytes"] as? Int else {
        throw ProbeFailure("fixture oracle shape")
    }
    try require(Set(expected.keys) == Set(["contact", "appointment", "task", "note"]),
                "fixture oracle collections")
    let hostileKeys = ["PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP",
                       "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__", "PYTHONTZPATH"]
    try require(hostileKeys.allSatisfy {
        ProcessInfo.processInfo.environment[$0]?.hasSuffix("/not-a-python-grant") == true
    }, "hostile parent Python environment was not installed")

    let selected = directory.appendingPathComponent("known-values.or6")
    let bytes = try FileImportProcess.readSelected(selected)
    try require(bytes.count == byteCount && bytes.count > 65536 &&
                FileImportProtocol.digest(bytes) == sourceHash, "native selected-file identity")
    let input = try FileImportProtocol.Input(bytes: bytes, format: "lotus", name: "known-values.or6",
        language: "en", timeZone: "Europe/Berlin", homeCountry: "DE")
    let result = try FileImportProcess.run(input, bundle: bundle)
    let collections = [("contact", "kontakte"), ("appointment", "termine"),
                       ("task", "aufgaben"), ("note", "notizen")]
    var fieldsVerified = 0
    for (kind, collection) in collections {
        guard let rows = result[collection] as? [[String: Any]], rows.count == 1,
              let values = expected[kind], !values.isEmpty else {
            throw ProbeFailure("real helper collection " + collection)
        }
        for (key, value) in values {
            guard let actual = rows[0][key] else { throw ProbeFailure("missing known fixture field") }
            try require(try equalJSONValue(actual, value), "known fixture field differs: " + collection + "." + key)
            fieldsVerified += 1
        }
    }

    // This valid native request reaches the real helper, which returns a framed,
    // hash-bound error. The original Swift response decoder must reject it.
    let unavailableZone = try FileImportProtocol.Input(bytes: bytes, format: "lotus", name: "known-values.or6",
        language: "en", timeZone: "Magnolie-Probe/Unavailable", homeCountry: "DE")
    try requireRejection("The calendar timezone is unavailable.", "structured helper error") {
        _ = try FileImportProcess.run(unavailableZone, bundle: bundle)
    }
    try requireRejection("The selected file is unavailable or is a symbolic link.", "selected symlink") {
        _ = try FileImportProcess.readSelected(directory.appendingPathComponent("selected-symlink.or6"))
    }
    for name in ["empty.or6", "oversized.or6"] {
        try requireRejection("Select a regular import file no larger than 32 MiB.", name) {
            _ = try FileImportProcess.readSelected(directory.appendingPathComponent(name))
        }
    }
    let after = try FileImportProcess.readSelected(selected)
    try require(after == bytes, "selected fixture changed during native import")
    return [
        "schema": 1, "ok": true,
        "sourceSHA256": sourceHash, "selectedBytes": byteCount,
        "knownFieldsVerified": fieldsVerified, "knownCollectionsVerified": collections.count,
        "checks": ["selectedRegularFileRead": true, "originalSwiftProcessWithBundledRuntime": true,
                   "knownOR6FieldsPreserved": true, "hostileParentPythonEnvironment": true,
                   "structuredHelperErrorRejected": true, "selectedSymlinkRejected": true,
                   "emptySelectedFileRejected": true, "oversizedSelectedFileRejected": true,
                   "selectedFixtureUnchanged": true],
        "scope": "Original Swift process and response decoder with the app's private interpreter/helper; public OR6 fixture only.",
        "pickerExercised": false, "editorExercised": false, "profileSaveExercised": false,
        "systemPermissionsExercised": false, "nativeAcceptance": false, "productionRelease": false
    ]
}

private final class ResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var result: Result<[String: Any], Error>?
    func store(_ value: Result<[String: Any], Error>) { lock.lock(); result = value; lock.unlock() }
    func read() -> Result<[String: Any], Error>? { lock.lock(); defer { lock.unlock() }; return result }
}

@main private struct NativeFileImportProbe {
    static func main() {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let bundle = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let directory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        let completed = DispatchSemaphore(value: 0), box = ResultBox()
        // Match the product's worker-queue requirement; its pipe readers and
        // Process termination handler retain their original implementation.
        DispatchQueue(label: "magnolie-native-file-import-probe", qos: .userInitiated).async {
            box.store(Result { try exercise(bundle: bundle, directory: directory) })
            completed.signal()
        }
        guard completed.wait(timeout: .now() + 140) == .success, let result = box.read() else {
            // The external driver owns this entire process group and kills any
            // descendant after timeout/failure, including a surviving helper.
            exit(3)
        }
        do {
            let proof = try result.get()
            var data = try JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys])
            data.append(10)
            try require(data.count <= 65536, "probe output bound")
            FileHandle.standardOutput.write(data)
        } catch {
            let message = (error as? ProbeFailure)?.message ?? (error as? BetaError)?.errorDescription ?? "native process probe failed"
            FileHandle.standardError.write(Data((String(message.prefix(512)) + "\n").utf8))
            exit(1)
        }
    }
}
#else
import Foundation
@main private struct UnsupportedNativeFileImportProbe { static func main() { exit(2) } }
#endif
