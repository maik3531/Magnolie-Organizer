package io.gitlab.maik3531.magnolietabletbeta
import java.net.URI
import org.json.JSONArray
class DavCancellation { fun check() {} }
class DavException(val code:String): Exception(code)
data class BoundedHttpRequest(val uri: URI, val headers:Map<String,String>, val timeoutMillis:Long, val maxResponseBytes:Int)
data class Response(val status:Int,val body:ByteArray)
fun interface BoundedHttpTransport { fun send(request:BoundedHttpRequest,cancellation:DavCancellation):Response }
object Fixtures { val responses=mutableMapOf<String,JSONArray>() }
