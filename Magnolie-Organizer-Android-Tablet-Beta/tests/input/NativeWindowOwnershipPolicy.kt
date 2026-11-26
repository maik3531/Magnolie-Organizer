package io.gitlab.maik3531.magnolietabletbeta

/** Test-runner diagnosis only. Missing accessibility evidence is not a proven foreign blocker. Refs #463. */
internal object NativeWindowOwnershipPolicy {
    data class Evidence(val nativeReady: Boolean, val targetWindow: Int, val activeWindow: Int,
                        val activePackage: String, val expectedPackage: String,
                        val activeRootPresent: Boolean, val activeReadFailed: Boolean = false,
                        val targetReadFailed: Boolean = false)

    enum class Result(val classification: String?, val failureCode: String?) {
        OWNED(null, null),
        READ_FAILED("input-ownership-read-failed", "INPUT_OWNERSHIP_READ_FAILED"),
        UNVERIFIED("input-ownership-unverified", "INPUT_OWNERSHIP_UNVERIFIED"),
        FOREIGN_PACKAGE("environment-input-blocked", "ENVIRONMENT_INPUT_BLOCKED"),
        DIFFERENT_WINDOW("environment-input-blocked", "ENVIRONMENT_INPUT_BLOCKED"),
        APP_NOT_READY("app-window-not-ready", "APP_WINDOW_NOT_READY");

        val owned: Boolean get() = this == OWNED
    }

    fun assess(evidence: Evidence): Result = with(evidence) {
        // Exactly the existing ownership predicate; diagnostic metadata cannot relax it.
        val owned = nativeReady && targetWindow >= 0 && activeWindow == targetWindow && activePackage == expectedPackage
        if (owned) return@with Result.OWNED
        if (activeReadFailed || targetReadFailed) return@with Result.READ_FAILED
        if (activeRootPresent && activeWindow >= 0) {
            if (activePackage.isNotEmpty() && activePackage != expectedPackage) return@with Result.FOREIGN_PACKAGE
            if (targetWindow >= 0 && activeWindow != targetWindow) return@with Result.DIFFERENT_WINDOW
        }
        if (!activeRootPresent || targetWindow < 0 || activeWindow < 0 || activePackage.isEmpty()) return@with Result.UNVERIFIED
        Result.APP_NOT_READY
    }
}
