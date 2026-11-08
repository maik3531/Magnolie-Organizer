package io.gitlab.maik3531.magnolietabletbeta

/** Test-only: preserve the actual assertion/cause when strict fixture cleanup also fails. */
internal fun cleanupPreservingFailure(primary: Throwable?, cleanup: () -> Unit) {
    try { cleanup() }
    catch (failure: Throwable) {
        if (primary == null) throw failure
        if (primary !== failure) primary.addSuppressed(failure)
    }
}
