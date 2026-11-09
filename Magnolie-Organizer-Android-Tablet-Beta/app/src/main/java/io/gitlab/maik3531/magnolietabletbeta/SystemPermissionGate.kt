package io.gitlab.maik3531.magnolietabletbeta

/** Non-authorizing OS-dialog slot. No document/session/request ID is restored. */
internal class SystemPermissionGate private constructor(var nextCode: Int, private var slot: Slot?) {
    data class Slot(val code: Int, val kind: SystemSourcePolicy.Kind)
    val pending: Slot? get()=slot
    fun begin(kind: SystemSourcePolicy.Kind): Int {
        check(slot==null) { "permission_request_pending" }
        check(nextCode<65_000) { "Permission request capacity reached" }
        val code=nextCode++;slot=Slot(code,kind);return code
    }
    fun finish(code: Int): Boolean {
        if(slot?.code!=code) return false
        slot=null;return true
    }
    /** Only used for a restored quarantine, never to authorize a native reply. */
    fun clearIfAlreadyGranted(granted: (SystemSourcePolicy.Kind)->Boolean) {
        slot?.let {if(granted(it.kind)) slot=null}
    }
    companion object {
        fun restore(next: Int=1000, code: Int?=null, kind: String?=null, savedProcess: String?=null,
                    currentProcess: String): SystemPermissionGate {
            require(next in 1000..65_000)
            val parsed=SystemSourcePolicy.Kind.entries.firstOrNull {it.wire==kind}
            // After process death no live request object survives. Keep monotonically
            // increasing codes, discard the obsolete dialog slot, and permit retry.
            val restored=if(savedProcess==currentProcess && code!=null && code in 1000 until next && parsed!=null) Slot(code,parsed) else null
            return SystemPermissionGate(next,restored)
        }
    }
}
