#if os(macOS)
import AppKit
import Foundation
import BetaCore

/// Refs #772. Explicit, read-only Apple Notes text-copy input. Initializing this
/// object performs no Automation request and retains no Notes data. The fixed
/// script and Notes dictionary still require compilation/runtime checks on a Mac.
/// NSAppleScript runs on one serial queue (Apple DTS thread/759287), never on the
/// AppKit thread. Cancellation invalidates a result; it cannot stop an Apple event
/// already executing. A busy reader rejects new work instead of queuing it.
final class AppleNotesReader {
    struct Summary {
        let identifier: String
        let title: String
        let passwordProtected: Bool?
    }

    private static let queue = DispatchQueue(label: "io.gitlab.maik3531.magnolie.apple-notes-reader", qos: .userInitiated)
    private static let stateLock = NSLock()
    private static var busy = false
    private static let maximumTextBytes = 1_048_576
    private static let maximumReadBytes = 8 * 1_048_576
    private static let maximumSeconds: TimeInterval = 45

    private final class Cancellation {
        private let lock = NSLock()
        private var cancelled = false
        func cancel() { lock.lock(); cancelled = true; lock.unlock() }
        func check() throws {
            lock.lock(); let value = cancelled; lock.unlock()
            if value { throw CancellationError() }
        }
    }

    func sources() async throws -> [AppleNotesImport.Source] {
        try await perform(handler: "magnolie_sources", arguments: []) { reply in
            let envelope = try Self.list(reply, count: 2)
            try Self.version(envelope[0])
            let rows = try Self.list(envelope[1], maximum: 512)
            var budget = 0, seen = Set<OpaqueUTF8Identity>()
            return try rows.map { row in
                let source = try Self.source(row, budget: &budget)
                guard seen.insert(OpaqueUTF8Identity(parts: [source.accountID, source.folderID])).inserted else {
                    throw Self.invalidReply()
                }
                return source
            }
        }
    }

    /// Metadata only. No plaintext/body/attachment data is requested by this handler.
    func notes(in source: AppleNotesImport.Source) async throws -> [Summary] {
        try Self.requireSourceIDs(source)
        return try await perform(handler: "magnolie_notes", arguments: [
            NSAppleEventDescriptor(string: source.accountID), NSAppleEventDescriptor(string: source.folderID)
        ]) { reply in
            let envelope = try Self.list(reply, count: 3)
            try Self.version(envelope[0])
            var budget = 0
            let current = try Self.source(envelope[1], budget: &budget)
            try Self.requireSameSourceIDs(current, source)
            let rows = try Self.list(envelope[2], maximum: 1000)
            var seen = Set<OpaqueUTF8Identity>()
            return try rows.map { row in
                let fields = try Self.list(row, count: 3)
                let identifier = try Self.text(fields[0], maximum: 16_384, empty: false, budget: &budget)
                guard seen.insert(OpaqueUTF8Identity(identifier)).inserted else { throw Self.invalidReply() }
                return Summary(identifier: identifier,
                    title: try Self.text(fields[1], maximum: 4096, budget: &budget),
                    passwordProtected: try Self.optional(fields[2], decode: Self.boolean))
            }
        }
    }

    /// Always resolves the supplied opaque IDs again. The returned source labels
    /// are fresh, allowing AppleNotesImport.Plan to compare a second complete read.
    func snapshot(source: AppleNotesImport.Source, identifiers: [String]) async throws -> AppleNotesImport.Snapshot {
        try Self.requireSourceIDs(source)
        try Self.requireIdentifiers(identifiers, maximum: 32)
        let selected = NSAppleEventDescriptor.list()
        for (index, identifier) in identifiers.enumerated() {
            selected.insert(NSAppleEventDescriptor(string: identifier), at: index + 1)
        }
        return try await perform(handler: "magnolie_snapshot", arguments: [
            NSAppleEventDescriptor(string: source.accountID), NSAppleEventDescriptor(string: source.folderID), selected
        ]) { reply in
            let envelope = try Self.list(reply, count: 3)
            try Self.version(envelope[0])
            var budget = 0
            let current = try Self.source(envelope[1], budget: &budget)
            try Self.requireSameSourceIDs(current, source)
            let rows = try Self.list(envelope[2], count: identifiers.count)
            var records: [AppleNotesImport.Record] = []
            for (row, expected) in zip(rows, identifiers) {
                let fields = try Self.list(row, count: 8)
                let identifier = try Self.text(fields[0], maximum: 16_384, empty: false, budget: &budget)
                guard Self.same(identifier, expected) else { throw Self.invalidReply() }
                let title = try Self.text(fields[1], maximum: 4096, budget: &budget)
                let protected = try Self.optional(fields[2], decode: Self.boolean)
                let attachments = try Self.optional(fields[3], decode: Self.nonnegativeInteger)
                let plainDescriptor = try Self.optional(fields[4], decode: { $0 })
                let htmlDescriptor = try Self.optional(fields[5], decode: { $0 })
                let modified = try Self.optional(fields[6], decode: Self.date)
                let failureDescriptor = try Self.optional(fields[7], decode: { $0 })
                var failure = try failureDescriptor.map { try Self.text($0, maximum: 128, empty: false, budget: &budget) }
                guard failure == nil || failure!.hasPrefix("apple-notes-") else { throw Self.invalidReply() }
                // The script must not return content for protected, attachment-
                // bearing, or unreadable notes. Treat a violation as a bad reply.
                if protected != false || attachments != 0 || failure != nil {
                    guard plainDescriptor == nil, htmlDescriptor == nil else { throw Self.invalidReply() }
                }
                var plaintext: String?, bodyHTML: String?
                if let plainDescriptor, let htmlDescriptor {
                    do {
                        plaintext = try Self.text(plainDescriptor, maximum: Self.maximumTextBytes, budget: &budget)
                        bodyHTML = try Self.text(htmlDescriptor, maximum: Self.maximumTextBytes, budget: &budget)
                    } catch ReadFailure.textTooLarge {
                        // Never truncate. The identified note remains visible as
                        // an exclusion; neither partially read body is delivered.
                        plaintext = nil; bodyHTML = nil; failure = "apple-notes-content-too-large"
                    }
                } else if plainDescriptor != nil || htmlDescriptor != nil { throw Self.invalidReply() }
                records.append(AppleNotesImport.Record(identifier: identifier, title: title,
                    passwordProtected: protected, attachmentCount: attachments,
                    plaintext: plaintext, bodyHTML: bodyHTML, modified: modified, failure: failure))
            }
            return AppleNotesImport.Snapshot(source: current, records: records)
        }
    }

    private static func reserve() throws {
        stateLock.lock(); defer { stateLock.unlock() }
        guard !busy else { throw BetaError("Apple Notes is still reading. Wait for that read to finish before trying again.") }
        busy = true
    }
    private static func release() { stateLock.lock(); busy = false; stateLock.unlock() }

    private func perform<T>(handler: String, arguments: [NSAppleEventDescriptor],
                            decode: @escaping (NSAppleEventDescriptor) throws -> T) async throws -> T {
        try Task.checkCancellation()
        try Self.reserve()
        defer { Self.release() }
        let available = await MainActor.run {
            NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Notes") != nil
        }
        guard available else { throw BetaError("Apple Notes is not available on this Mac.") }
        try Task.checkCancellation()
        let cancellation = Cancellation()
        let value: T = try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                Self.queue.async {
                    let result: Result<T, Error> = autoreleasepool {
                        Result {
                            try cancellation.check()
                            let started = ProcessInfo.processInfo.systemUptime
                            let deadline = Date().addingTimeInterval(Self.maximumSeconds)
                            guard let script = NSAppleScript(source: Self.script) else {
                                throw BetaError("The built-in Apple Notes reader could not be created.")
                            }
                            var error: NSDictionary?
                            guard script.compileAndReturnError(&error) else {
                                throw Self.scriptError(error, compilation: true)
                            }
                            try cancellation.check()
                            guard ProcessInfo.processInfo.systemUptime - started <= Self.maximumSeconds else {
                                throw Self.scriptError(nil, compilation: true)
                            }
                            let event = NSAppleEventDescriptor(eventClass: 0x61736372, eventID: 0x70736272,
                                targetDescriptor: nil, returnID: -1, transactionID: 0) // ascr/psbr
                            event.setParam(NSAppleEventDescriptor(string: handler), forKeyword: 0x736e616d) // snam
                            let parameters = NSAppleEventDescriptor.list()
                            for (index, argument) in arguments.enumerated() { parameters.insert(argument, at: index + 1) }
                            parameters.insert(NSAppleEventDescriptor(date: deadline), at: arguments.count + 1)
                            event.setParam(parameters, forKeyword: 0x2d2d2d2d) // direct object
                            error = nil
                            let possibleReply: NSAppleEventDescriptor? = script.executeAppleEvent(event, error: &error)
                            try cancellation.check()
                            guard error == nil, let reply = possibleReply else { throw Self.scriptError(error, compilation: false) }
                            // A monotonic post-check also rejects a late result if
                            // the script's wall-clock loop deadline was disturbed.
                            guard ProcessInfo.processInfo.systemUptime - started <= Self.maximumSeconds else {
                                throw BetaError("Reading Apple Notes timed out. Select fewer notes and try again.")
                            }
                            // These are post-read bounds. AppleScript/Notes can
                            // allocate an individual reply before we inspect it;
                            // no pre-allocation or hard process bound is claimed.
                            guard reply.data.count <= 24 * 1_048_576 else {
                                throw BetaError("Apple Notes returned too much data. Select a smaller source.")
                            }
                            let decoded = try decode(reply)
                            try cancellation.check()
                            guard ProcessInfo.processInfo.systemUptime - started <= Self.maximumSeconds else {
                                throw BetaError("Reading Apple Notes timed out. Select fewer notes and try again.")
                            }
                            return decoded
                        }
                    }
                    continuation.resume(with: result)
                }
            }
        }, onCancel: { cancellation.cancel() })
        try Task.checkCancellation()
        return value
    }

    private enum ReadFailure: LocalizedError {
        case textTooLarge
        var errorDescription: String? { "Apple Notes text exceeds the read limits. Select fewer or smaller notes." }
    }
    private static func invalidReply() -> BetaError {
        BetaError("Apple Notes returned unsupported or inconsistent data. No notes were copied.")
    }
    private static func same(_ left: String, _ right: String) -> Bool { left.utf8.elementsEqual(right.utf8) }
    private static func requireSourceIDs(_ source: AppleNotesImport.Source) throws {
        // Account and folder are separate identity domains; equal bytes across
        // those two roles are not an ambiguity in a selected source pair.
        try requireIdentifiers([source.accountID], maximum: 1)
        try requireIdentifiers([source.folderID], maximum: 1)
    }
    private static func requireIdentifiers(_ values: [String], maximum: Int) throws {
        guard !values.isEmpty, values.count <= maximum,
              values.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 16_384 }),
              Set(values.map(OpaqueUTF8Identity.init)).count == values.count else {
            throw BetaError("Select unambiguous Apple Notes source identities within the copy limit.")
        }
    }
    private static func requireSameSourceIDs(_ left: AppleNotesImport.Source, _ right: AppleNotesImport.Source) throws {
        guard same(left.accountID, right.accountID), same(left.folderID, right.folderID) else {
            throw BetaError("The selected Apple Notes account or folder changed. Choose it again.")
        }
    }
    private static func list(_ descriptor: NSAppleEventDescriptor, count: Int? = nil,
                             maximum: Int = 1000) throws -> [NSAppleEventDescriptor] {
        guard descriptor.descriptorType == 0x6c697374, descriptor.numberOfItems <= maximum,
              count == nil || descriptor.numberOfItems == count else { throw invalidReply() } // list
        return try (0..<descriptor.numberOfItems).map { offset in
            guard let item = descriptor.atIndex(offset + 1) else { throw invalidReply() }
            return item
        }
    }
    private static func optional<T>(_ descriptor: NSAppleEventDescriptor,
                                     decode: (NSAppleEventDescriptor) throws -> T) throws -> T? {
        let items = try list(descriptor, maximum: 1)
        return try items.first.map(decode)
    }
    private static func version(_ descriptor: NSAppleEventDescriptor) throws {
        guard try nonnegativeInteger(descriptor) == 1 else { throw invalidReply() }
    }
    private static func text(_ descriptor: NSAppleEventDescriptor, maximum: Int,
                             empty: Bool = true, budget: inout Int) throws -> String {
        guard [UInt32(0x75747874), 0x75746638, 0x75743136, 0x54455854].contains(descriptor.descriptorType) else {
            throw invalidReply() // utxt/utf8/ut16/TEXT only; no arbitrary coercion
        }
        guard descriptor.data.count <= maximum * 2 + 4 else { throw ReadFailure.textTooLarge }
        guard let value = descriptor.stringValue, empty || !value.isEmpty else { throw invalidReply() }
        let bytes = value.utf8.count
        guard bytes <= maximum else { throw ReadFailure.textTooLarge }
        guard bytes <= maximumReadBytes - budget else {
            throw BetaError("Apple Notes returned more than 8 MiB. Select fewer notes.")
        }
        budget += bytes
        return value
    }
    private static func boolean(_ descriptor: NSAppleEventDescriptor) throws -> Bool {
        // Use Foundation's public constructors as the canonical byte layout,
        // rather than guessing C scalar widths. booleanValue returns false on
        // some failures, so it is deliberately not used for untrusted replies.
        let bytes = descriptor.data
        switch descriptor.descriptorType {
        case 0x626f6f6c: // bool
            for value in [false, true] {
                let canonical = NSAppleEventDescriptor(boolean: value)
                if canonical.descriptorType == descriptor.descriptorType, bytes == canonical.data { return value }
            }
            throw invalidReply()
        case 0x74727565, 0x66616c73: // true/fals, if Foundation supports this representation
            let value = descriptor.descriptorType == 0x74727565
            guard let canonical = NSAppleEventDescriptor(boolean: value).coerce(toDescriptorType: descriptor.descriptorType),
                  canonical.descriptorType == descriptor.descriptorType, bytes == canonical.data else { throw invalidReply() }
            return value
        default: throw invalidReply()
        }
    }
    private static func nonnegativeInteger(_ descriptor: NSAppleEventDescriptor) throws -> Int {
        let canonicalZero = NSAppleEventDescriptor(int32: 0), bytes = descriptor.data
        guard descriptor.descriptorType == 0x6c6f6e67, // long
              descriptor.descriptorType == canonicalZero.descriptorType,
              bytes.count == canonicalZero.data.count else { throw invalidReply() }
        let value = descriptor.int32Value
        guard value >= 0, bytes == NSAppleEventDescriptor(int32: value).data else { throw invalidReply() }
        return Int(value)
    }
    private static func date(_ descriptor: NSAppleEventDescriptor) throws -> Double {
        let canonicalEpoch = NSAppleEventDescriptor(date: Date(timeIntervalSince1970: 0)), bytes = descriptor.data
        guard descriptor.descriptorType == 0x6c647420, // ldt-space
              descriptor.descriptorType == canonicalEpoch.descriptorType,
              bytes.count == canonicalEpoch.data.count else { throw invalidReply() }
        guard let value = descriptor.dateValue, value.timeIntervalSince1970.isFinite,
              bytes == NSAppleEventDescriptor(date: value).data else { throw invalidReply() }
        return value.timeIntervalSince1970
    }
    private static func source(_ descriptor: NSAppleEventDescriptor, budget: inout Int) throws -> AppleNotesImport.Source {
        let fields = try list(descriptor, count: 4)
        return AppleNotesImport.Source(
            accountID: try text(fields[0], maximum: 16_384, empty: false, budget: &budget),
            accountTitle: try text(fields[1], maximum: 4096, budget: &budget),
            folderID: try text(fields[2], maximum: 16_384, empty: false, budget: &budget),
            folderTitle: try text(fields[3], maximum: 4096, budget: &budget))
    }
    private static func scriptError(_ error: NSDictionary?, compilation: Bool) -> BetaError {
        let number = (error?[NSAppleScript.errorNumber] as? NSNumber)?.intValue
        if number == -1743 || number == -10004 {
            return BetaError("macOS did not allow access to Apple Notes. Enable Magnolie for Notes in System Settings → Privacy & Security → Automation, then retry the copy.")
        }
        if compilation {
            return BetaError("The built-in Apple Notes script could not be compiled. This build needs native validation with this macOS Notes dictionary.")
        }
        switch number ?? Int.min {
        case -1712, 77204: return BetaError("Reading Apple Notes timed out. Select a smaller source and try again.")
        case -600, -609, 77201: return BetaError("The selected Apple Notes account, folder or note is no longer available. Choose the source again.")
        case 77202, 77207: return BetaError("Apple Notes source identities are missing or ambiguous. No notes were copied.")
        case 77203: return BetaError("The selected Apple Notes source exceeds the read limits. Choose a smaller folder or selection.")
        case 77206: return BetaError("Apple Notes changed during reading. Review a new copy proposal.")
        case 77205, 77208, -1708: return BetaError("This version of Apple Notes did not provide the required scripting fields. No notes were copied.")
        default: return BetaError("Apple Notes could not be read. No notes were copied. Error code: \(number.map { String($0) } ?? "unavailable").")
        }
    }

    // Fixed product code, never assembled from note text, names or opaque IDs.
    // [] means unavailable; [value] means a successfully read, typed property.
    // All Apple events target the installed Notes app. Only read operations occur.
    // `with timeout` bounds waiting for each event, not Notes' own operation.
    private static let script = """
    on sameText(leftValue, rightValue)
        -- AppleScript text equality can ignore case/Unicode distinctions. Compare
        -- the documented text.id code-point sequences instead; Swift checks UTF-8.
        return (id of leftValue) is equal to (id of rightValue)
    end sameText

    on requiredText(valueToCheck, maximumLength, allowEmpty)
        if class of valueToCheck is not text then error "Unsupported text property" number 77208
        set characterCount to length of valueToCheck
        if characterCount > maximumLength then error "Read limit" number 77203
        if allowEmpty is false and characterCount is 0 then error "Missing identity" number 77202
        return valueToCheck
    end requiredText

    on checkDeadline(deadlineValue)
        if class of deadlineValue is not date then error "Invalid deadline" number 77208
        if (current date) > deadlineValue then error "Read deadline" number 77204
    end checkDeadline

    on rethrowFatal(errorNumber)
        if errorNumber is in {-1743, -10004, -1712, -600, -609, 77201, 77202, 77203, 77204, 77206, 77207} then
            error "Read could not finish" number errorNumber
        end if
    end rethrowFatal

    on folderOwner(folderObject, deadlineValue)
        set currentObject to folderObject
        repeat 32 times
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set parentObject to get container of currentObject
                    if class of parentObject is account then
                        set ownerID to get id of parentObject
                        set ownerTitle to get name of parentObject
                        return {my requiredText(ownerID, 16384, false), my requiredText(ownerTitle, 4096, true)}
                    end if
                    if class of parentObject is not folder then error "Unsupported source parent" number 77205
                end timeout
            end tell
            set currentObject to parentObject
        end repeat
        error "Folder depth limit" number 77203
    end folderOwner

    on sourceRow(folderObject, deadlineValue)
        set ownerRow to my folderOwner(folderObject, deadlineValue)
        my checkDeadline(deadlineValue)
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set folderID to get id of folderObject
                set folderTitle to get name of folderObject
            end timeout
        end tell
        return {item 1 of ownerRow, item 2 of ownerRow, my requiredText(folderID, 16384, false), my requiredText(folderTitle, 4096, true)}
    end sourceRow

    on sameSource(leftRow, rightRow)
        repeat fieldIndex from 1 to 4
            if not (my sameText(item fieldIndex of leftRow, item fieldIndex of rightRow)) then return false
        end repeat
        return true
    end sameSource

    on collectFolders(parentObject, expectedAccountID, depthValue, deadlineValue, entries)
        my checkDeadline(deadlineValue)
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set folderCount to count folders of parentObject
            end timeout
        end tell
        if class of folderCount is not integer or folderCount < 0 or folderCount > 512 then error "Folder count limit" number 77203
        if folderCount > 0 and depthValue > 32 then error "Folder depth limit" number 77203
        repeat folderIndex from 1 to folderCount
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set folderObject to get folder folderIndex of parentObject
                end timeout
            end tell
            set details to my sourceRow(folderObject, deadlineValue)
            if not (my sameText(item 1 of details, expectedAccountID)) then error "Folder account changed" number 77206
            set alreadySeen to false
            repeat with oldEntry in entries
                my checkDeadline(deadlineValue)
                set oldDetails to item 1 of oldEntry
                if (my sameText(item 1 of oldDetails, item 1 of details)) and (my sameText(item 3 of oldDetails, item 3 of details)) then
                    if not (my sameSource(oldDetails, details)) then error "Folder changed" number 77206
                    set alreadySeen to true
                    exit repeat
                end if
            end repeat
            -- Some dictionary versions may enumerate descendants at account
            -- scope too. Do not re-traverse the same exact account/folder pair.
            if alreadySeen is false then
                if (count entries) >= 512 then error "Folder count limit" number 77203
                set end of entries to {details, folderObject}
                set entries to my collectFolders(folderObject, expectedAccountID, depthValue + 1, deadlineValue, entries)
            end if
        end repeat
        return entries
    end collectFolders

    on allSources(deadlineValue)
        my checkDeadline(deadlineValue)
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set accountCount to count accounts
            end timeout
        end tell
        if class of accountCount is not integer or accountCount < 0 or accountCount > 64 then error "Account count limit" number 77203
        set entries to {}
        set accountIDs to {}
        repeat accountIndex from 1 to accountCount
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set accountObject to get account accountIndex
                    set accountID to get id of accountObject
                end timeout
            end tell
            my requiredText(accountID, 16384, false)
            repeat with previousID in accountIDs
                my checkDeadline(deadlineValue)
                if (my sameText(contents of previousID, accountID)) then error "Duplicate account identity" number 77207
            end repeat
            set end of accountIDs to accountID
            set entries to my collectFolders(accountObject, accountID, 1, deadlineValue, entries)
        end repeat
        return entries
    end allSources

    on selectedSource(accountID, folderID, deadlineValue)
        my requiredText(accountID, 16384, false)
        my requiredText(folderID, 16384, false)
        set entries to my allSources(deadlineValue)
        set matches to {}
        repeat with sourceEntry in entries
            my checkDeadline(deadlineValue)
            set details to item 1 of sourceEntry
            if (my sameText(item 1 of details, accountID)) and (my sameText(item 3 of details, folderID)) then set end of matches to contents of sourceEntry
        end repeat
        if (count matches) is 0 then error "Source unavailable" number 77201
        if (count matches) is not 1 then error "Ambiguous source" number 77207
        return item 1 of matches
    end selectedSource

    on noteIdentity(noteObject, expectedSource, deadlineValue)
        my checkDeadline(deadlineValue)
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set identifierValue to get id of noteObject
                set containingFolder to get container of noteObject
            end timeout
        end tell
        set currentSource to my sourceRow(containingFolder, deadlineValue)
        if not (my sameSource(currentSource, expectedSource)) then error "Note source changed" number 77206
        return my requiredText(identifierValue, 16384, false)
    end noteIdentity

    on noteCount(folderObject, deadlineValue)
        my checkDeadline(deadlineValue)
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set foundCount to count notes of folderObject
            end timeout
        end tell
        if class of foundCount is not integer or foundCount < 0 or foundCount > 1000 then error "Note metadata count limit" number 77203
        return foundCount
    end noteCount

    on readNote(noteObject, expectedID, expectedSource, deadlineValue)
        set identifierValue to my noteIdentity(noteObject, expectedSource, deadlineValue)
        if not (my sameText(identifierValue, expectedID)) then error "Note identity changed" number 77206
        tell application id "com.apple.Notes"
            with timeout of 10 seconds
                set titleValue to get name of noteObject
            end timeout
        end tell
        my requiredText(titleValue, 4096, true)
        set resultRow to {identifierValue, titleValue, {}, {}, {}, {}, {}, {}}
        try
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set protectedValue to get password protected of noteObject
                end timeout
            end tell
            if class of protectedValue is not boolean then error "Unknown protection property" number 77208
            set item 3 of resultRow to {protectedValue}
            if protectedValue is false then
                tell application id "com.apple.Notes"
                    with timeout of 10 seconds
                        set attachmentCount to count attachments of noteObject
                    end timeout
                end tell
                if class of attachmentCount is not integer or attachmentCount < 0 then error "Unknown attachment count" number 77208
                set item 4 of resultRow to {attachmentCount}
                if attachmentCount is 0 then
                    my checkDeadline(deadlineValue)
                    tell application id "com.apple.Notes"
                        with timeout of 10 seconds
                            set modifiedValue to get modification date of noteObject
                        end timeout
                    end tell
                    if class of modifiedValue is not date then error "Unknown modification date" number 77208
                    set item 7 of resultRow to {modifiedValue}
                    tell application id "com.apple.Notes"
                        with timeout of 10 seconds
                            set plainValue to get plaintext of noteObject
                        end timeout
                    end tell
                    if class of plainValue is not text then error "Unknown plaintext" number 77208
                    if (length of plainValue) > 1048576 then error "Note content limit" number 77209
                    my checkDeadline(deadlineValue)
                    tell application id "com.apple.Notes"
                        with timeout of 10 seconds
                            set htmlValue to get body of noteObject
                        end timeout
                    end tell
                    if class of htmlValue is not text then error "Unknown HTML representation" number 77208
                    if (length of htmlValue) > 1048576 then error "Note content limit" number 77209
                    my checkDeadline(deadlineValue)
                    tell application id "com.apple.Notes"
                        with timeout of 10 seconds
                            set finalModified to get modification date of noteObject
                            set finalProtected to get password protected of noteObject
                            set finalAttachmentCount to count attachments of noteObject
                            set finalTitle to get name of noteObject
                        end timeout
                    end tell
                    if class of finalModified is not date or class of finalProtected is not boolean or class of finalAttachmentCount is not integer then error "Unknown recheck properties" number 77208
                    my requiredText(finalTitle, 4096, true)
                    if finalModified is not equal to modifiedValue or finalProtected is not false or finalAttachmentCount is not 0 or not (my sameText(finalTitle, titleValue)) then error "Note changed" number 77206
                    set item 5 of resultRow to {plainValue}
                    set item 6 of resultRow to {htmlValue}
                end if
            end if
        on error ignoredMessage number errorNumber
            my rethrowFatal(errorNumber)
            set item 5 of resultRow to {}
            set item 6 of resultRow to {}
            if errorNumber is 77209 then
                set item 8 of resultRow to {"apple-notes-content-too-large"}
            else
                set item 8 of resultRow to {"apple-notes-property-error:" & (errorNumber as text)}
            end if
        end try
        if not (my sameText(my noteIdentity(noteObject, expectedSource, deadlineValue), expectedID)) then error "Note identity changed" number 77206
        return resultRow
    end readNote

    on magnolie_sources(deadlineValue)
        set entries to my allSources(deadlineValue)
        set rows to {}
        repeat with sourceEntry in entries
            my checkDeadline(deadlineValue)
            set end of rows to item 1 of sourceEntry
        end repeat
        return {1, rows}
    end magnolie_sources

    on magnolie_notes(accountID, folderID, deadlineValue)
        set chosen to my selectedSource(accountID, folderID, deadlineValue)
        set expectedSource to item 1 of chosen
        set folderObject to item 2 of chosen
        set metadataCount to my noteCount(folderObject, deadlineValue)
        set rows to {}
        set identities to {}
        repeat noteIndex from 1 to metadataCount
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set noteObject to get note noteIndex of folderObject
                    set titleValue to get name of noteObject
                end timeout
            end tell
            my requiredText(titleValue, 4096, true)
            set identifierValue to my noteIdentity(noteObject, expectedSource, deadlineValue)
            repeat with previousID in identities
                my checkDeadline(deadlineValue)
                if (my sameText(contents of previousID, identifierValue)) then error "Duplicate note identity" number 77207
            end repeat
            set end of identities to identifierValue
            set protectedField to {}
            try
                tell application id "com.apple.Notes"
                    with timeout of 10 seconds
                        set protectedValue to get password protected of noteObject
                    end timeout
                end tell
                if class of protectedValue is boolean then set protectedField to {protectedValue}
            on error ignoredMessage number errorNumber
                my rethrowFatal(errorNumber)
            end try
            set end of rows to {identifierValue, titleValue, protectedField}
        end repeat
        if (my noteCount(folderObject, deadlineValue)) is not metadataCount then error "Folder changed" number 77206
        if not (my sameSource(my sourceRow(folderObject, deadlineValue), expectedSource)) then error "Source changed" number 77206
        return {1, expectedSource, rows}
    end magnolie_notes

    on magnolie_snapshot(accountID, folderID, selectedIDs, deadlineValue)
        my checkDeadline(deadlineValue)
        if class of selectedIDs is not list then error "Invalid selection" number 77202
        if (count selectedIDs) is 0 or (count selectedIDs) > 32 then error "Selection count limit" number 77203
        set checkedIDs to {}
        repeat with selectedID in selectedIDs
            my checkDeadline(deadlineValue)
            set checkedID to my requiredText(contents of selectedID, 16384, false)
            repeat with previousID in checkedIDs
                my checkDeadline(deadlineValue)
                if (my sameText(contents of previousID, checkedID)) then error "Duplicate selected identity" number 77207
            end repeat
            set end of checkedIDs to checkedID
        end repeat
        set chosen to my selectedSource(accountID, folderID, deadlineValue)
        set expectedSource to item 1 of chosen
        set folderObject to item 2 of chosen
        set metadataCount to my noteCount(folderObject, deadlineValue)
        -- Resolve metadata first; never use mutable list positions as identity.
        set knownIDs to {}
        set knownObjects to {}
        repeat noteIndex from 1 to metadataCount
            my checkDeadline(deadlineValue)
            tell application id "com.apple.Notes"
                with timeout of 10 seconds
                    set noteObject to get note noteIndex of folderObject
                end timeout
            end tell
            set identifierValue to my noteIdentity(noteObject, expectedSource, deadlineValue)
            repeat with previousID in knownIDs
                my checkDeadline(deadlineValue)
                if (my sameText(contents of previousID, identifierValue)) then error "Duplicate note identity" number 77207
            end repeat
            set end of knownIDs to identifierValue
            set end of knownObjects to noteObject
        end repeat
        set rows to {}
        set contentCharacters to 0
        repeat with selectedID in checkedIDs
            my checkDeadline(deadlineValue)
            set matchedIndex to 0
            repeat metadataIndex from 1 to (count knownIDs)
                my checkDeadline(deadlineValue)
                if (my sameText(item metadataIndex of knownIDs, contents of selectedID)) then
                    set matchedIndex to metadataIndex
                    exit repeat
                end if
            end repeat
            if matchedIndex is 0 then error "Selected note unavailable" number 77201
            set resultRow to my readNote(item matchedIndex of knownObjects, contents of selectedID, expectedSource, deadlineValue)
            repeat fieldIndex from 5 to 6
                set contentField to item fieldIndex of resultRow
                if (count contentField) is 1 then set contentCharacters to contentCharacters + (length of item 1 of contentField)
            end repeat
            if contentCharacters > 8388608 then error "Selection content limit" number 77203
            set end of rows to resultRow
        end repeat
        if (my noteCount(folderObject, deadlineValue)) is not metadataCount then error "Folder changed" number 77206
        set currentSource to my sourceRow(folderObject, deadlineValue)
        if not (my sameSource(currentSource, expectedSource)) then error "Source changed" number 77206
        return {1, currentSource, rows}
    end magnolie_snapshot
    """
}
#endif
