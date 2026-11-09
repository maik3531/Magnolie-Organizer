package io.gitlab.maik3531.magnolietabletbeta

internal enum class ImportFormat { JSON, ICS }
internal enum class ExportFormat { JSON, ICS }

/** One-use SAF result routing, including the selected file's background decode lifetime.
 * Codes are never reused across page/activity recreation; a new request invalidates old work.
 */
internal class DocumentRequests(var nextCode: Int = 100) {
    data class Request(val code: Int, val export: Boolean, val generation: Int, val session: DocumentSession,
                       val format: ImportFormat = ImportFormat.JSON, val requestId: String? = null, val exportFormat: ExportFormat = ExportFormat.JSON)
    private var pending: Request? = null
    private var selected: Request? = null
    @Synchronized fun matches(code: Int): Boolean = pending?.code == code
    @Synchronized fun active(): Request? = pending ?: selected
    @Synchronized fun isActive(request: Request): Boolean = pending == request || selected == request

    @Synchronized fun begin(export: Boolean, generation: Int, session: DocumentSession,
                            format: ImportFormat = ImportFormat.JSON, requestId: String? = null, exportFormat: ExportFormat = ExportFormat.JSON): Request {
        check(pending == null)
        check(!export || format == ImportFormat.JSON)
        check(export || exportFormat == ExportFormat.JSON)
        check(nextCode in 100..65535) { "Document request codes exhausted; reopen the activity" }
        selected = null
        return Request(nextCode++, export, generation, session, format, requestId, exportFormat).also { pending = it }
    }

    @Synchronized fun take(code: Int, generation: Int, session: DocumentSession?): Request? {
        val request = pending ?: return null
        if (request.code != code) return null // An old result must not cancel a newer chooser.
        pending = null
        return request.takeIf { it.generation == generation && it.session == session }?.also { selected = it }
    }
    @Synchronized fun finish(code: Int): Boolean {
        if (selected?.code != code) return false
        selected = null; return true
    }
    @Synchronized fun cancel() { pending = null; selected = null }
}
