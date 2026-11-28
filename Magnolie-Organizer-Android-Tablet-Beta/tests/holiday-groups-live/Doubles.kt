package io.gitlab.maik3531.magnolietabletbeta
import java.net.URI

// Refs #857: only transport and cancellation are controlled. Query, JSON,
// date validation, parsing, aggregation and callback models are product code.
class DavCancellation { fun check() {} }
class DavException(val code:String): Exception(code)
data class BoundedHttpRequest(val uri: URI, val headers:Map<String,String>, val timeoutMillis:Long, val maxResponseBytes:Int)
data class Response(val status:Int,val body:ByteArray)
fun interface BoundedHttpTransport { fun send(request:BoundedHttpRequest,cancellation:DavCancellation):Response }
class OkHttpBoundedTransport: BoundedHttpTransport {
    override fun send(request:BoundedHttpRequest,cancellation:DavCancellation):Response = error("Network disabled in this host")
}
