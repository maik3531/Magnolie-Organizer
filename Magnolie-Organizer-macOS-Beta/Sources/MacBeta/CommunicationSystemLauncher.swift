#if os(macOS)
import AppKit
import BetaCore

/// Resolve the configured system handler; never invoke a shell or executable.
@MainActor final class CommunicationSystemLauncher: CommunicationSystemOpening {
    func application(for destination: URL) -> URL? {
        NSWorkspace.shared.urlForApplication(toOpen: destination)
    }
    func open(_ destination: URL, with application: URL, completion: @escaping (Error?) -> Void) {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        configuration.addsToRecentItems = false
        NSWorkspace.shared.open([destination], withApplicationAt: application,
                                configuration: configuration) { runningApplication, error in
            guard error == nil, let runningApplication,
                  let actualBundle = runningApplication.bundleURL,
                  actualBundle.standardizedFileURL.resolvingSymlinksInPath() == application.standardizedFileURL.resolvingSymlinksInPath() else {
                completion(error ?? BetaError("The system did not confirm opening the selected application."))
                return
            }
            completion(nil)
        }
    }
}
#endif
