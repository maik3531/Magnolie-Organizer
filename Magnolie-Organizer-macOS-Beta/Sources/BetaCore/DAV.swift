import Foundation
import CryptoKit
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(FoundationXML)
import FoundationXML
#endif

/// The transport never follows redirects. Callers must validate a new target before retrying.
public struct BoundedHTTPRequest {
    public let url: URL
    public let method: String
    public let headers: [String: String]
    public let body: Data
    public let timeout: TimeInterval
    public let maximumResponseBytes: Int

    public init(url: URL, method: String = "GET", headers: [String: String] = [:],
                body: Data = Data(), timeout: TimeInterval = 30,
                maximumResponseBytes: Int = 2 * 1024 * 1024) {
        self.url = url; self.method = method; self.headers = headers; self.body = body
        self.timeout = timeout; self.maximumResponseBytes = maximumResponseBytes
    }
}

public struct BoundedHTTPResponse {
    public let status: Int
    /// Header names are case insensitive; the initializer normalizes them to lowercase.
    public let headers: [String: String]
    public let body: Data
    public init(status: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.status = status
        self.headers = headers.reduce(into: [:]) { $0[$1.key.lowercased()] = $1.value }
        self.body = body
    }
}

public protocol BoundedHTTPTransport {
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse
}

public enum DAVError: Error, Equatable {
    case invalidConfiguration
    case originRejected
    case responseTooLarge
    case timeout
    case malformedXML
    case partialMultistatus
    case incompleteReport
    case reportOutsideCollection
    case homeMissing
    case missingETag
    case localAttachment
    case unauthorized
    case forbidden
    case conflict(status: Int)
    case httpStatus(Int)
    case invalidResponse
}

/// Uses the operating system's HTTPS trust evaluation, without a trust challenge override.
/// An ephemeral session avoids persisting credentials, DAV payloads or HTTP cookies to disk.
public struct URLSessionBoundedTransport: BoundedHTTPTransport {
    public init() {}
    public func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        let operation = BoundedHTTPOperation(request)
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { operation.start($0) }
        }, onCancel: { operation.cancel() })
    }
}

private final class BoundedHTTPOperation: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let input: BoundedHTTPRequest
    private let lock = NSLock()
    private var continuation: CheckedContinuation<BoundedHTTPResponse, Error>?
    private var finished = false
    private var cancelled = false
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var deadline: DispatchWorkItem?
    private var response: HTTPURLResponse?
    private var data = Data()
    init(_ request: BoundedHTTPRequest) { input = request }

    func start(_ continuation: CheckedContinuation<BoundedHTTPResponse, Error>) {
        lock.lock()
        self.continuation = continuation
        if cancelled { lock.unlock(); finish(.failure(CancellationError())); return }
        guard let parts = URLComponents(url: input.url, resolvingAgainstBaseURL: false),
              parts.scheme?.lowercased() == "https", parts.host?.isEmpty == false,
              parts.user == nil, parts.password == nil, parts.fragment == nil,
              input.timeout.isFinite, input.timeout > 0, input.timeout <= 60,
              input.maximumResponseBytes > 0, input.maximumResponseBytes <= DAVClient.itemLimit else {
            lock.unlock(); finish(.failure(DAVError.invalidConfiguration)); return
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = input.timeout
        configuration.timeoutIntervalForResource = input.timeout
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        self.session = session
        var request = URLRequest(url: input.url, timeoutInterval: input.timeout)
        request.httpMethod = input.method
        request.httpBody = input.body.isEmpty ? nil : input.body
        for (name, value) in input.headers { request.setValue(value, forHTTPHeaderField: name) }
        let task = session.dataTask(with: request)
        self.task = task
        let deadline = DispatchWorkItem { [weak self] in self?.finish(.failure(DAVError.timeout)) }
        self.deadline = deadline
        DispatchQueue.global().asyncAfter(deadline: .now() + input.timeout, execute: deadline)
        task.resume()
        lock.unlock()
    }

    func cancel() {
        lock.lock(); cancelled = true; let started = continuation != nil; lock.unlock()
        if started { finish(.failure(CancellationError())) }
    }

    private func finish(_ result: Result<BoundedHTTPResponse, Error>) {
        lock.lock()
        guard !finished, let continuation else { lock.unlock(); return }
        finished = true; self.continuation = nil
        let session = self.session; self.session = nil
        let task = self.task; self.task = nil
        deadline?.cancel(); deadline = nil
        lock.unlock()
        task?.cancel(); session?.invalidateAndCancel()
        continuation.resume(with: result)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse else {
            completionHandler(.cancel); finish(.failure(DAVError.invalidResponse)); return
        }
        guard response.expectedContentLength <= Int64(input.maximumResponseBytes) else {
            completionHandler(.cancel); finish(.failure(DAVError.responseTooLarge)); return
        }
        self.response = http
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard data.count <= input.maximumResponseBytes - self.data.count else {
            finish(.failure(DAVError.responseTooLarge)); return
        }
        self.data.append(data)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error {
            finish(.failure((error as? URLError)?.code == .timedOut ? DAVError.timeout : error))
        } else if let response {
            var headers: [String: String] = [:]
            for (key, value) in response.allHeaderFields {
                headers[String(describing: key).lowercased()] = String(describing: value)
            }
            finish(.success(BoundedHTTPResponse(status: response.statusCode, headers: headers, body: data)))
        } else { finish(.failure(DAVError.invalidResponse)) }
    }
}

public enum DAVKind: String { case calendar, addressbook }
public enum DAVAccountType: String { case nextcloud; case genericDAV = "generic-dav" }

public struct DAVCollection: Equatable {
    /// Compatible with the canonical v2.0.30 source_id: provider/kind + SHA256(absolute href).
    public let uid: String
    public let name: String
    public let href: URL
    public let kind: DAVKind
    public let supportsVtodo: Bool
    public let syncToken: String?
}

public struct DAVResource: Equatable {
    public let href: URL
    public let etag: String
    /// Raw server ICS/vCard is preserved, including unknown properties and recurrence exceptions.
    public let data: String
}

/// DAV resource transfer only. Scheduling, local merge/deletion journals and atomic profile saves
/// belong to the sync coordinator, which must not report sync success on transfer alone.
public final class DAVClient {
    public static let xmlLimit = 2 * 1024 * 1024
    public static let itemLimit = 42 * 1024 * 1024
    public static let listLimit = 10_000
    public let server: URL
    public let username: String
    public let accountType: DAVAccountType
    private let password: String
    private let transport: any BoundedHTTPTransport
    private let timeout: TimeInterval
    private static let dav = "DAV:"
    private static let cal = "urn:ietf:params:xml:ns:caldav"
    private static let card = "urn:ietf:params:xml:ns:carddav"

    public init(server: String, username: String, password: String,
                accountType: DAVAccountType = .nextcloud,
                transport: any BoundedHTTPTransport = URLSessionBoundedTransport(),
                timeout: TimeInterval = 60) throws {
        let trimmed = server.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var parts = URLComponents(string: trimmed),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.port.map({ (1...65535).contains($0) }) ?? true,
              !trimmed.contains("\\"), !trimmed.unicodeScalars.contains(where: { $0.value < 32 }),
              timeout.isFinite, timeout > 0 else { throw DAVError.invalidConfiguration }
        let user = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !user.isEmpty, user.count <= 256, !user.contains(":"),
              !user.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else {
            throw DAVError.invalidConfiguration
        }
        parts.scheme = "https"; parts.host = host.lowercased()
        if parts.port == 443 { parts.port = nil }
        parts.percentEncodedPath = parts.percentEncodedPath == "/" ? "" : parts.percentEncodedPath
        while parts.percentEncodedPath.hasSuffix("/") { parts.percentEncodedPath.removeLast() }
        guard let url = parts.url else { throw DAVError.invalidConfiguration }
        self.server = url; self.username = user; self.password = password
        self.accountType = accountType; self.transport = transport; self.timeout = min(timeout, 60)
    }

    public func sameOriginURL(_ value: String, relativeTo base: URL? = nil) throws -> URL {
        guard !value.contains("\\"), !value.unicodeScalars.contains(where: { $0.value < 32 }),
              let url = URL(string: value, relativeTo: base ?? URL(string: server.absoluteString + "/"))?.absoluteURL,
              var parts = URLComponents(url: url, resolvingAgainstBaseURL: true),
              parts.scheme?.lowercased() == "https", parts.host?.lowercased() == server.host?.lowercased(),
              (parts.port ?? 443) == (server.port ?? 443), parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil else { throw DAVError.originRejected }
        parts.scheme = "https"; parts.host = server.host; parts.port = server.port
        guard let safe = parts.url else { throw DAVError.originRejected }
        return safe.standardized
    }

    public static func sourceID(kind: DAVKind, href: URL, accountType: DAVAccountType = .nextcloud) -> String {
        let hash = SHA256.hash(data: Data(href.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
        return "\(accountType.rawValue)-\(kind.rawValue):\(hash)"
    }

    private func request(_ method: String, url: URL, body: Data = Data(), headers: [String: String] = [:],
                         limit: Int = DAVClient.xmlLimit, expected: Set<Int>) async throws -> (BoundedHTTPResponse, URL) {
        var target = try sameOriginURL(url.absoluteString)
        var headers = headers
        headers["Authorization"] = "Basic " + Data("\(username):\(password)".utf8).base64EncodedString()
        headers["User-Agent"] = "Magnolie-Organizer-macOS/2.0.30"
        let started = ProcessInfo.processInfo.systemUptime
        for attempt in 0...1 {
            try Task.checkCancellation()
            let remaining = timeout - (ProcessInfo.processInfo.systemUptime - started)
            guard remaining > 0 else { throw DAVError.timeout }
            let response = try await transport.send(BoundedHTTPRequest(url: target, method: method,
                headers: headers, body: body, timeout: remaining, maximumResponseBytes: limit))
            guard (ProcessInfo.processInfo.systemUptime - started) <= timeout else { throw DAVError.timeout }
            guard response.body.count <= limit else { throw DAVError.responseTooLarge }
            if (300..<400).contains(response.status) {
                guard attempt == 0, let location = response.headers["location"] else {
                    throw DAVError.httpStatus(response.status)
                }
                target = try sameOriginURL(location, relativeTo: target)
                continue
            }
            switch response.status {
            case 401: throw DAVError.unauthorized
            case 403: throw DAVError.forbidden
            case 409, 412: throw DAVError.conflict(status: response.status)
            default: break
            }
            guard expected.contains(response.status) else { throw DAVError.httpStatus(response.status) }
            return (response, target)
        }
        throw DAVError.invalidResponse
    }

    private func propfind(_ url: URL, properties: String, depth: String = "0") async throws -> ([DAVRow], URL) {
        let body = "<d:propfind xmlns:d=\"DAV:\" xmlns:c=\"\(Self.cal)\" xmlns:a=\"\(Self.card)\"><d:prop>\(properties)</d:prop></d:propfind>"
        let (response, target) = try await request("PROPFIND", url: url, body: Data(body.utf8),
            headers: ["Depth": depth, "Content-Type": "application/xml; charset=utf-8"], expected: [207])
        return (try DAVXML.rows(response.body, strict: false), target)
    }

    public func home(for kind: DAVKind) async throws -> URL {
        let tag = kind == .calendar ? "c:calendar-home-set" : "a:addressbook-home-set"
        let homeKey = kind == .calendar ? Self.cal + "|calendar-home-set" : Self.card + "|addressbook-home-set"
        var origin = URLComponents(url: server, resolvingAgainstBaseURL: false)!
        origin.path = ""
        let known = origin.url!.appendingPathComponent(".well-known").appendingPathComponent(kind == .calendar ? "caldav" : "carddav")
        let encodedUser = username.addingPercentEncoding(withAllowedCharacters: .alphanumerics)!
        let fallback = try sameOriginURL(server.absoluteString + "/remote.php/dav/principals/users/" + encodedUser + "/")
        let targets = [known, accountType == .nextcloud ? fallback : URL(string: server.absoluteString + "/")!]
        for target in targets {
            do {
                let (rows, finalURL) = try await propfind(target, properties: "<d:current-user-principal/><\(tag)/>")
                guard let row = rows.first else { throw DAVError.partialMultistatus }
                if let href = row.properties[homeKey]?.child(Self.dav, "href")?.text, !href.isEmpty {
                    return try sameOriginURL(href, relativeTo: finalURL)
                }
                if let href = row.properties[Self.dav + "|current-user-principal"]?.child(Self.dav, "href")?.text, !href.isEmpty {
                    let principal = try sameOriginURL(href, relativeTo: finalURL)
                    let (principalRows, principalURL) = try await propfind(principal, properties: "<\(tag)/>")
                    if let home = principalRows.first?.properties[homeKey]?.child(Self.dav, "href")?.text, !home.isEmpty {
                        return try sameOriginURL(home, relativeTo: principalURL)
                    }
                }
            } catch DAVError.httpStatus(let status) where [301, 302, 303, 307, 308, 404, 405].contains(status) {
                continue
            } catch DAVError.originRejected { continue }
        }
        guard accountType == .nextcloud else { throw DAVError.homeMissing }
        let suffix = kind == .calendar ? "/remote.php/dav/calendars/" : "/remote.php/dav/addressbooks/users/"
        return try sameOriginURL(server.absoluteString + suffix + encodedUser + "/")
    }

    public func collections(for kind: DAVKind) async throws -> [DAVCollection] {
        let homeURL = try await home(for: kind)
        let components = kind == .calendar ? "<c:supported-calendar-component-set/>" : ""
        let (rows, finalURL) = try await propfind(homeURL,
            properties: "<d:displayname/><d:resourcetype/><d:sync-token/>" + components, depth: "1")
        let namespace = kind == .calendar ? Self.cal : Self.card
        var result: [DAVCollection] = []
        for row in rows {
            guard row.properties[Self.dav + "|resourcetype"]?.child(namespace, kind.rawValue) != nil else { continue }
            let href = try sameOriginURL(row.href, relativeTo: finalURL)
            let name = row.properties[Self.dav + "|displayname"]?.text.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let supported = row.properties[Self.cal + "|supported-calendar-component-set"]
            let vtodo = supported == nil || supported!.children.contains { $0.attributes["name"]?.uppercased() == "VTODO" }
            result.append(DAVCollection(uid: Self.sourceID(kind: kind, href: href, accountType: accountType),
                name: name.isEmpty ? href.lastPathComponent : name, href: href, kind: kind,
                supportsVtodo: kind == .calendar && vtodo, syncToken: row.properties[Self.dav + "|sync-token"]?.text))
        }
        return result.sorted { ($0.name.lowercased(), $0.uid) < ($1.name.lowercased(), $1.uid) }
    }

    public func report(collection: URL, kind: DAVKind) async throws -> [DAVResource] {
        let collection = try sameOriginURL(collection.absoluteString)
        let calendar = kind == .calendar
        let namespace = calendar ? Self.cal : Self.card
        let query = calendar ? "calendar-query" : "addressbook-query"
        let dataTag = calendar ? "calendar-data" : "address-data"
        let filter = calendar ? "<x:filter><x:comp-filter name=\"VCALENDAR\"/></x:filter>" : "<x:filter/>"
        let body = "<x:\(query) xmlns:d=\"DAV:\" xmlns:x=\"\(namespace)\"><d:prop><d:getetag/><x:\(dataTag)/></d:prop>\(filter)</x:\(query)>"
        let (response, finalURL) = try await request("REPORT", url: collection, body: Data(body.utf8),
            headers: ["Depth": "1", "Content-Type": "application/xml; charset=utf-8"], limit: Self.itemLimit, expected: [207])
        let rows = try DAVXML.rows(response.body, strict: true)
        var result: [DAVResource] = []
        var seen = Set<URL>()
        let prefix = (finalURL.path as NSString).standardizingPath.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let collectionPrefix = prefix.isEmpty ? "/" : "/" + prefix + "/"
        for row in rows {
            guard let raw = row.properties[namespace + "|" + dataTag]?.text,
                  !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw DAVError.incompleteReport }
            let href = try sameOriginURL(row.href, relativeTo: finalURL)
            let path = (href.path as NSString).standardizingPath
            guard path.hasPrefix(collectionPrefix), seen.insert(href).inserted else { throw DAVError.reportOutsideCollection }
            result.append(DAVResource(href: href, etag: row.properties[Self.dav + "|getetag"]?.text ?? "", data: raw))
        }
        return result
    }

    /// A 412 remains an explicit conflict: callers may compare/refetch without overwriting local data.
    public func put(href: URL, data: String, etag: String? = nil, create: Bool = false) async throws -> String {
        guard create || Self.validETag(etag) else { throw DAVError.missingETag }
        let bytes = Data(data.utf8)
        guard bytes.count <= Self.itemLimit else { throw DAVError.responseTooLarge }
        let calendar = data.trimmingCharacters(in: .whitespacesAndNewlines).uppercased().hasPrefix("BEGIN:VCALENDAR")
        if calendar { try Self.rejectLocalAttachments(data) }
        let headers = ["Content-Type": calendar ? "text/calendar; charset=utf-8" : "text/vcard; charset=utf-8",
                       (create ? "If-None-Match" : "If-Match"): create ? "*" : etag!]
        let (response, _) = try await request("PUT", url: href, body: bytes, headers: headers, expected: [200, 201, 204])
        return response.headers["etag"] ?? ""
    }

    @discardableResult public func delete(href: URL, etag: String) async throws -> Bool {
        guard Self.validETag(etag) else { throw DAVError.missingETag }
        let (response, _) = try await request("DELETE", url: href, headers: ["If-Match": etag], expected: [200, 204, 404])
        return response.status != 404
    }

    private static func validETag(_ etag: String?) -> Bool {
        guard let etag else { return false }
        let trimmed = etag.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != "*" &&
            !etag.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 })
    }

    private static func rejectLocalAttachments(_ text: String) throws {
        var unfolded: [String] = []
        for line in text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n").components(separatedBy: "\n") {
            if (line.hasPrefix(" ") || line.hasPrefix("\t")), !unfolded.isEmpty { unfolded[unfolded.count - 1] += line.dropFirst() }
            else { unfolded.append(line) }
        }
        for line in unfolded where line.uppercased().hasPrefix("ATTACH:") || line.uppercased().hasPrefix("ATTACH;") {
            var quoted = false
            for index in line.indices {
                if line[index] == "\"" { quoted.toggle() }
                if line[index] == ":", !quoted {
                    let value = String(line[line.index(after: index)...]).trimmingCharacters(in: .whitespacesAndNewlines)
                    if value.lowercased().hasPrefix("file:") || value.hasPrefix("/") || value.hasPrefix("\\\\") ||
                        value.hasPrefix("~/") || value.hasPrefix("~\\") || value.range(of: "^[A-Za-z]:[\\\\/]", options: .regularExpression) != nil {
                        throw DAVError.localAttachment
                    }
                    break
                }
            }
        }
    }
}

private final class DAVXMLNode {
    let key: String
    let attributes: [String: String]
    var text = ""
    var children: [DAVXMLNode] = []
    init(key: String, attributes: [String: String]) { self.key = key; self.attributes = attributes }
    func child(_ namespace: String, _ name: String) -> DAVXMLNode? { children.first { $0.key == namespace + "|" + name } }
}
private struct DAVRow { let href: String; let properties: [String: DAVXMLNode] }

private final class DAVXML: NSObject, XMLParserDelegate {
    private var stack: [DAVXMLNode] = []
    private var root: DAVXMLNode?
    private var failed = false
    private var nodes = 0
    private var textBytes = 0
    static func rows(_ data: Data, strict: Bool) throws -> [DAVRow] {
        guard data.count <= DAVClient.itemLimit else { throw DAVError.responseTooLarge }
        // Only UTF-8 DAV XML is accepted. This also prevents alternate-encoding DTD bypasses.
        guard let text = String(data: data, encoding: .utf8), !text.contains("\0"),
              text.range(of: "<!DOCTYPE", options: .caseInsensitive) == nil,
              text.range(of: "<!ENTITY", options: .caseInsensitive) == nil else { throw DAVError.malformedXML }
        let delegate = DAVXML()
        let parser = XMLParser(data: data)
        parser.shouldProcessNamespaces = true
        parser.shouldResolveExternalEntities = false
        parser.delegate = delegate
        guard parser.parse(), !delegate.failed, let root = delegate.root else { throw DAVError.malformedXML }
        guard root.key == "DAV:|multistatus" else { throw DAVError.partialMultistatus }
        let responses = root.children.filter { $0.key == "DAV:|response" }
        guard responses.count <= DAVClient.listLimit else { throw DAVError.responseTooLarge }
        var rows: [DAVRow] = []
        for response in responses {
            let href = response.child("DAV:", "href")?.text ?? ""
            let status = response.child("DAV:", "status")?.text
            let propstats = response.children.filter { $0.key == "DAV:|propstat" }
            if strict && (href.isEmpty || (status == nil && propstats.isEmpty) || (status != nil && !success(status!))) {
                throw DAVError.partialMultistatus
            }
            var properties: [String: DAVXMLNode] = [:]
            for propstat in propstats {
                guard success(propstat.child("DAV:", "status")?.text ?? "") else {
                    if strict { throw DAVError.partialMultistatus }; continue
                }
                guard let prop = propstat.child("DAV:", "prop") else {
                    if strict { throw DAVError.partialMultistatus }; continue
                }
                for child in prop.children { properties[child.key] = child }
            }
            rows.append(DAVRow(href: href, properties: properties))
        }
        return rows
    }
    private static func success(_ status: String) -> Bool {
        let parts = status.split(whereSeparator: { $0.isWhitespace })
        return parts.count >= 2 && parts[0].hasPrefix("HTTP/") && parts[1] == "200"
    }
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes attributeDict: [String: String]) {
        nodes += 1
        guard stack.count < 64, nodes <= 100_000 else { failed = true; parser.abortParsing(); return }
        let node = DAVXMLNode(key: (namespaceURI ?? "") + "|" + elementName, attributes: attributeDict)
        if let parent = stack.last { parent.children.append(node) }
        else if root == nil { root = node } else { failed = true; parser.abortParsing(); return }
        stack.append(node)
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { append(string, parser: parser) }
    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
        guard let text = String(data: CDATABlock, encoding: .utf8) else { failed = true; parser.abortParsing(); return }
        append(text, parser: parser)
    }
    private func append(_ text: String, parser: XMLParser) {
        textBytes += text.utf8.count
        guard textBytes <= DAVClient.itemLimit else { failed = true; parser.abortParsing(); return }
        stack.last?.text += text
    }
    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) { if !stack.isEmpty { stack.removeLast() } }
    func parser(_ parser: XMLParser, foundInternalEntityDeclarationWithName name: String, value: String?) { failed = true; parser.abortParsing() }
    func parser(_ parser: XMLParser, foundExternalEntityDeclarationWithName name: String, publicID: String?, systemID: String?) { failed = true; parser.abortParsing() }
    func parser(_ parser: XMLParser, resolveExternalEntityName name: String, systemID: String?) -> Data? { failed = true; parser.abortParsing(); return nil }
}
