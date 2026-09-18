package io.gitlab.maik3531.magnolietabletbeta

/** One-use SAF result routing. Codes are never reused across page/activity recreation. */
internal class DocumentRequests(var nextCode: Int = 100) {
    data class Request(val code: Int, val export: Boolean, val generation: Int, val session: DocumentSession)
    private var pending: Request? = null
    fun matches(code: Int): Boolean = pending?.code == code

    fun begin(export: Boolean, generation: Int, session: DocumentSession): Request {
        check(pending == null)
        check(nextCode in 100..65535) { "Document request codes exhausted; reopen the activity" }
        return Request(nextCode++, export, generation, session).also { pending = it }
    }

    fun take(code: Int, generation: Int, session: DocumentSession?): Request? {
        val request = pending ?: return null
        if (request.code != code) return null // An old result must not cancel a newer chooser.
        pending = null
        return request.takeIf { it.generation == generation && it.session == session }
    }

    fun cancel() { pending = null }
}
