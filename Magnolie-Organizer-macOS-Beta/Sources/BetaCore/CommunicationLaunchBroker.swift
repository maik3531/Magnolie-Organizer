import Foundation

/// Refs #121. Injected system boundary: test implementations never open apps.
@MainActor public protocol CommunicationSystemOpening: AnyObject {
    func application(for destination: URL) -> URL?
    func open(_ destination: URL, with application: URL, completion: @escaping (Error?) -> Void)
}

@MainActor public final class CommunicationLaunchBroker {
    private let system: CommunicationSystemOpening
    private var pending: UUID?
    public init(system: CommunicationSystemOpening) { self.system = system }
    public func cancel() { pending = nil }

    /// Success proves only the OS accepted opening this URL in its handler.
    /// The caller supplies a native document fence, never a JS gesture flag.
    public func begin(_ target: CommunicationLaunchPolicy.Target, isCurrent: @escaping () -> Bool,
                      completion: @escaping ([String: Any]) -> Void) {
        let token = UUID(); pending = token
        guard isCurrent() else { pending = nil; return }
        guard let application = system.application(for: target.url), application.isFileURL,
              application.pathExtension.lowercased() == "app" else {
            pending = nil
            completion(["ok": false, "fehler": "No application was found to open this address."])
            return
        }
        guard isCurrent(), pending == token else { return }
        system.open(target.url, with: application) { [weak self] error in
            Task { @MainActor in
                guard let self, self.pending == token, isCurrent() else { return }
                self.pending = nil
                if error != nil {
                    completion(["ok": false, "fehler": "The application could not be opened."])
                } else {
                    completion(["ok": true, "womit": target.service,
                                "name": application.deletingPathExtension().lastPathComponent,
                                "fehler": ""])
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            guard let self, self.pending == token, isCurrent() else { return }
            self.pending = nil
            completion(["ok": false, "fehler": "The application did not confirm opening this address in time."])
        }
    }
}
