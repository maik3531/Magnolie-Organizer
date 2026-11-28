import Foundation
public struct BetaError: Error { let message: String; public init(_ message: String) { self.message = message } }
public struct BoundedHTTPRequest { let url: URL; let headers: [String:String]; let timeout: Double; let maximumResponseBytes: Int }
public struct BoundedHTTPResponse { let status: Int; let body: Data }
public protocol BoundedHTTPTransport { func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse }
public struct URLSessionBoundedTransport: BoundedHTTPTransport { public init() {} ; public func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse { throw BetaError("network disabled") } }
