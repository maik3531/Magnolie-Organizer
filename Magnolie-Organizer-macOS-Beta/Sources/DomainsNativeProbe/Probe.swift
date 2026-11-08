import Foundation
#if os(macOS)
import AppKit
import WebKit
import BetaCore

/// Shared forms and actual WebKit/AppKit input, backed by a disposable real
/// AtomicStore. This does not automate the production Host's permission dialogs.
@MainActor private final class Probe: NSObject, NSApplicationDelegate, WKScriptMessageHandler {
    private let uiRoot: URL, harnessURL: URL, directory: URL
    private var phase = "starting"
    private var proof: [String: Any] = ["ok": false, "productionHostDialogsTested": false]
    init(uiRoot: URL, harnessURL: URL, directory: URL) {
        self.uiRoot = uiRoot; self.harnessURL = harnessURL; self.directory = directory
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { do { try await run(); finish(nil) } catch { finish(error) } }
    }
    private func mark(_ value: String) { phase = value; proof["phase"] = value; writeProof() }
    private func writeProof() {
        if let data = try? JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys]) {
            try? data.write(to: directory.appendingPathComponent("proof.json"), options: .atomic)
        }
    }
    private func finish(_ error: Error?) {
        proof["ok"] = error == nil; proof["phase"] = phase
        if let error { proof["error"] = error.localizedDescription }
        writeProof(); exit(error == nil ? 0 : 1)
    }
    private func unwrap<T>(_ value: T?) throws -> T {
        guard let value else { throw BetaError("Missing domain probe value at " + phase) }; return value
    }
    private func require(_ value: Bool, _ message: String) throws {
        guard value else { throw BetaError(message) }
    }
    private var store: AtomicStore!
    private var initialDocument: String!
    private var web: WKWebView!
    private var pendingReplies = 0
    private var savedCount = 0
    private var transportError: Error?
    private let seed = #"{"termine":[],"aufgaben":[],"kontakte":[],"notizen":[],"futureRoot":{"domains":"preserve unchanged"},"einstellungen":{"allgemein":{"handbuchHinweisGezeigt":true}}}"#
    private func reply(_ method: String, _ payload: [String: Any]) {
        pendingReplies += 1
        web.callAsyncJavaScript("window.MacBeta.receive(method,payload); if (method === 'init') window.OrganizerTest.speichereJetzt(); return true;", arguments: ["method": method, "payload": payload], in: nil, in: .page) { (result: Result<Any, Error>) in
            if case .failure(let error) = result { self.transportError = error }
            self.pendingReplies -= 1
        }
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        do {
            guard message.frameInfo.isMainFrame, let raw = message.body as? String else { return }
            let request = try Request(raw)
            switch request.command {
            case .bereit:
                reply("init", ["daten": try Document.object(initialDocument), "neu": false, "regional": ["language": "en", "timeZone": "UTC"]])
            case .speichern:
                try store.commit(request.text("text")); savedCount += 1
                initialDocument = request.text("text")
                reply("gespeichert", ["ok": true, "id": request.fields["id"]!])
            case .mutations_snapshot:
                _ = try store.checkpoint()
                reply("mutationsSnapshot", ["ok": true, "token": request.text("token")])
            default: break
            }
        } catch { transportError = error }
    }
    private func javascript(_ source: String, arguments: [String: Any] = [:]) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            var finished = false
            let timeout = DispatchWorkItem {
                guard !finished else { return }; finished = true
                continuation.resume(throwing: BetaError("Native domains JavaScript phase exceeded 45 seconds."))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: timeout)
            web.callAsyncJavaScript(source, arguments: arguments, in: nil, in: .page) { (result: Result<Any, Error>) in
                guard !finished else { return }; finished = true; timeout.cancel(); continuation.resume(with: result)
            }
        }
    }
    private func settle() async throws -> String {
        let deadline = ProcessInfo.processInfo.systemUptime + 10
        while ProcessInfo.processInfo.systemUptime < deadline {
            if let error = transportError { throw error }
            if savedCount > 0, pendingReplies == 0 {
                let value = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
                guard let current = value as? String else { throw BetaError("Domain UI snapshot is not a JSON string.") }
                let saved = try String(contentsOf: store.file, encoding: .utf8)
                if saved == current { return saved }
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        throw BetaError("Domain UI did not reach matching durable native save/ACK within 10 seconds.")
    }
    private func drawingDiagnostics(_ phase: String) async throws {
        let value = try await javascript("""
            const canvas=document.querySelector('.custom-zeichenblatt');
            const rect=canvas?.getBoundingClientRect();
            const module=window.OrganizerTest.daten().customOrganizer.modules.find(item=>item.type==='drawing');
            return JSON.stringify({phase,viewport:{width:innerWidth,height:innerHeight,devicePixelRatio},
              geometry:rect?{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,width:rect.width,height:rect.height}:null,
              canvas:canvas?{width:canvas.width,height:canvas.height,pointerEvents:getComputedStyle(canvas).pointerEvents,touchAction:getComputedStyle(canvas).touchAction}:null,
              valid:window.MagnolieZeichnen.valid(module?.drawing),drawing:JSON.stringify(module?.drawing??null).slice(0,6000),
              pixelChanged:canvas?canvas.toDataURL('image/png')!==window.__domainCanvasBefore:null,
              pointerCounts:window.__domainPointers,receipts:window.__domainEventReceipts||[]});
            """, arguments: ["phase": phase])
        if let text = value as? String { proof["drawing-" + phase] = try? Document.object(text); writeProof() }
        print("Mac drawing diagnostics: " + (value as? String ?? "invalid diagnostic result"))
    }
    private func nativeClick(_ target: [String: Any], window: NSWindow) async throws {
        let x = try unwrap(target["x"] as? Double), y = try unwrap(target["y"] as? Double)
        let local = NSPoint(x: x, y: web.isFlipped ? y : web.bounds.height - y)
        let location = web.convert(local, to: nil)
        for (step, type) in [NSEvent.EventType.leftMouseDown, .leftMouseUp].enumerated() {
            let event = try unwrap(NSEvent.mouseEvent(with: type, location: location, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                context: nil, eventNumber: step + 1, clickCount: 1, pressure: step == 0 ? 0.5 : 0))
            NSApp.postEvent(event, atStart: false)
            try await Task.sleep(nanoseconds: 25_000_000)
        }
    }
    private func stroke(_ rect: [String: Any], window: NSWindow) async throws {
        let x1 = try unwrap(rect["x1"] as? Double), x2 = try unwrap(rect["x2"] as? Double), y = try unwrap(rect["y"] as? Double)
        var receipts: [[String: Any]] = []
        for step in 0...25 {
            let fraction = Double(step) / 25
            let client = NSPoint(x: x1 + (x2 - x1) * fraction, y: y + sin(fraction * .pi) * 8)
            let local = NSPoint(x: client.x, y: web.isFlipped ? client.y : web.bounds.height - client.y)
            let location = web.convert(local, to: nil)
            let eventType: NSEvent.EventType = step == 0 ? .leftMouseDown : step == 25 ? .leftMouseUp : .leftMouseDragged
            let event = try unwrap(NSEvent.mouseEvent(with: eventType, location: location, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                context: nil, eventNumber: step + 1, clickCount: 1, pressure: step == 25 ? 0 : 0.5))
            let hitPoint = web.superview?.convert(location, from: nil) ?? location
            let hit = web.hitTest(hitPoint)
            receipts.append(["step": step, "type": eventType.rawValue,
                "client": [Double(client.x), Double(client.y)], "webLocal": [Double(local.x), Double(local.y)],
                "windowPoint": [Double(location.x), Double(location.y)], "webFlipped": web.isFlipped, "delivery": "NSApplication.postEvent",
                "windowNumber": window.windowNumber, "eventWindowNumber": event.windowNumber,
                "windowVisible": window.isVisible, "windowKey": window.isKeyWindow, "appActive": NSApp.isActive,
                "appRunning": NSApp.isRunning, "pressedMouseButtons": NSEvent.pressedMouseButtons,
                "currentEventType": NSApp.currentEvent.map { String($0.type.rawValue) } ?? "none",
                "firstResponderClass": window.firstResponder.map { String(describing: type(of: $0)) } ?? "none",
                "hitViewClass": hit.map { String(describing: type(of: $0)) } ?? "none"])
            NSApp.postEvent(event, atStart: false)
            try await Task.sleep(nanoseconds: 25_000_000)
        }
        proof["nativeEventReceipts"] = receipts; writeProof()
        print("Mac drawing native event receipts: " + (try Document.encode(receipts)))
    }
    private func run() async throws {
        mark("initializing")
        let profile = directory.appendingPathComponent("profile", isDirectory: true)
        store = try AtomicStore(directory: profile)
        initialDocument = try store.load() ?? seed // exactly once per store lease
        let configuration = WKWebViewConfiguration(); configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "domainsTest")
        configuration.userContentController.addUserScript(WKUserScript(source: "window.__MAGNOLIE_BRUECKE__='domainsTest';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1300, height: 900), configuration: configuration)
        let window = NSWindow(contentRect: web.frame, styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = web
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        defer {
            web.stopLoading(); configuration.userContentController.removeScriptMessageHandler(forName: "domainsTest")
            window.orderOut(nil); window.close(); web = nil; store = nil
        }
        mark("loading")
        web.loadFileURL(uiRoot.appendingPathComponent("web/index.html"), allowingReadAccessTo: uiRoot)
        _ = try await settle()
        let harness = try String(contentsOf: harnessURL, encoding: .utf8)
        _ = try await javascript(harness + "\nreturn true;")
        mark("book-cover-target")
        let coverValue = try await javascript("return window.NativeDomains.coverTarget();")
        let cover = try unwrap(coverValue as? [String: Any])
        try require(NSApp.isRunning && NSApp.isActive && window.isKeyWindow, "Native cover input requires the running foreground application")
        try await nativeClick(cover, window: window)
        mark("book-opening")
        proof["bookOpening"] = try await javascript("return await window.NativeDomains.opened();")
        writeProof()
        for stage in ["prepare", "health", "custom"] {
            mark(stage)
            _ = try await javascript("return await window.NativeDomains[stage]();", arguments: ["stage": stage])
            _ = try await settle()
        }
        mark("drawing-prepare")
        let rectangleValue = try await javascript("return await window.NativeDomains.drawing();")
        let rectangle = try unwrap(rectangleValue as? [String: Any])
        _ = try await javascript("""
            window.__domainEventReceipts=[];
            for(const type of ['pointerdown','pointermove','pointerup','pointercancel','gotpointercapture','lostpointercapture','mousedown','mousemove','mouseup']) {
              document.addEventListener(type,event=>{
                if(window.__domainEventReceipts.length>=100)return;
                const target=event.target;
                window.__domainEventReceipts.push({type:event.type,trusted:event.isTrusted,button:event.button??null,buttons:event.buttons??null,
                  pointerType:event.pointerType??null,pointerId:event.pointerId??null,x:event.clientX??null,y:event.clientY??null,
                  target:{tag:target?.tagName??'',id:target?.id??'',className:String(target?.className??'').slice(0,160)}});
              },true);
            }
            return true;
            """)
        mark("drawing-input")
        proof["applicationLifecycle"] = ["running": NSApp.isRunning, "active": NSApp.isActive, "keyWindow": window.isKeyWindow, "visible": window.isVisible]
        try await drawingDiagnostics("before-native-input")
        try require(NSApp.isRunning && NSApp.isActive && window.isKeyWindow, "Domain probe must have a running foreground application and key input window")
        proof["drawingTarget"] = try await javascript("return window.NativeDomains.drawingTargetReady(target);", arguments: ["target": rectangle])
        writeProof()
        try await stroke(rectangle, window: window)
        try await drawingDiagnostics("after-native-input")
        mark("drawing-proof")
        let drawingValue = try await javascript("return await window.NativeDomains.drawingProof();")
        let drawing = try unwrap(drawingValue as? [String: Any])
        try require(drawing["strokeCount"] as? Int == 1, "Exactly one valid native stroke required")
        try require(drawing["pixelChange"] as? Bool == true, "Actual canvas pixels must change")
        try require(drawing["undoRedo"] as? Bool == true, "Actual canvas Undo/Redo must preserve pixels")
        mark("saving")
        let saved = try await settle()
        let original = try Document.object(saved)
        let expectedValue = try await javascript("return JSON.stringify(window.NativeDomains.expectedAfterReopen(book));", arguments: ["book": original])
        let expected = try unwrap(expectedValue as? String)
        store = nil // real reopen: release the original private profile lease
        store = try AtomicStore(directory: profile)
        let reopenedBytes = try unwrap(store.load())
        try require(reopenedBytes == saved, "Fresh native store must read exact committed bytes")
        let reopenedBook = try Document.object(reopenedBytes)
        _ = try await javascript("window.MacBeta.receive('init',{daten:book,neu:false,regional:{language:'en',timeZone:'UTC'}}); window.OrganizerTest.speichereJetzt(); return true;", arguments: ["book": reopenedBook])
        mark("reopening")
        let reopened = try await settle()
        try require(try Document.encode(Document.object(reopened)) == Document.encode(Document.object(expected)), "Only agreed absent vital.sauerstoff=0 enrichment may differ")
        try require((try Document.object(reopened)["futureRoot"] as? [String: Any])?["domains"] as? String == "preserve unchanged", "Unknown root fields must survive")
        proof.merge( ["healthForms": true, "customDesignerForms": true, "drawing": drawing,
            "nativeDurableSaves": savedCount, "strictReopen": true, "productionHostDialogsTested": false]) { _, value in value }
        mark("completed")
        print("Mac native domain acceptance: " + (try Document.encode(proof)))
    }
}

@main private struct Entry {
    @MainActor static func main() {
        guard CommandLine.arguments.count == 4 else { exit(2) }
        let probe = Probe(uiRoot: URL(fileURLWithPath: CommandLine.arguments[1]),
                          harnessURL: URL(fileURLWithPath: CommandLine.arguments[2]), directory: URL(fileURLWithPath: CommandLine.arguments[3]))
        let app = NSApplication.shared
        app.setActivationPolicy(.regular); app.delegate = probe
        withExtendedLifetime(probe) { app.run() }
    }
}
#else
@main private struct Unsupported { static func main() { exit(2) } }
#endif
