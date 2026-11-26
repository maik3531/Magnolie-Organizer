package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class NativeWindowOwnershipPolicyTest {
    private val ready = NativeWindowOwnershipPolicy.Evidence(true, 7, 7, "app", "app", true)
    private fun result(value: NativeWindowOwnershipPolicy.Evidence) = NativeWindowOwnershipPolicy.assess(value)

    @Test fun focusedAppWithUnboundWindowsIsUnverifiedNotEnvironmentBlocked() {
        val actual = result(ready.copy(targetWindow = -1, activeWindow = -1, activePackage = "", activeRootPresent = false))
        assertEquals(NativeWindowOwnershipPolicy.Result.UNVERIFIED, actual)
        assertEquals("input-ownership-unverified", actual.classification)
        assertFalse(actual.owned)
    }

    @Test fun missingRootOrIncompleteBindingDoesNotNameAForeignCause() {
        for (value in listOf(ready.copy(targetWindow = -1), ready.copy(activeWindow = -1),
                ready.copy(activePackage = ""), ready.copy(activeWindow = -1, activeRootPresent = false))) {
            assertEquals(NativeWindowOwnershipPolicy.Result.UNVERIFIED, result(value))
        }
    }

    @Test fun rootAndTargetReadFailuresRemainFailuresWithoutInventingAnEnvironmentBlocker() {
        for (value in listOf(ready.copy(activeWindow = -1, activeReadFailed = true),
                ready.copy(targetWindow = -1, targetReadFailed = true))) {
            val actual = result(value)
            assertEquals(NativeWindowOwnershipPolicy.Result.READ_FAILED, actual)
            assertEquals("INPUT_OWNERSHIP_READ_FAILED", actual.failureCode)
            assertFalse(actual.owned)
        }
    }

    @Test fun positivelyObservedForeignPackageIsDistinguishedEvenWithoutTargetBinding() {
        val actual = result(ready.copy(targetWindow = -1, activePackage = "other.app"))
        assertEquals(NativeWindowOwnershipPolicy.Result.FOREIGN_PACKAGE, actual)
        assertEquals("environment-input-blocked", actual.classification)
        assertFalse(actual.owned)
    }

    @Test fun aDifferentKnownWindowIsNotAMissingObservation() {
        val actual = result(ready.copy(activeWindow = 9))
        assertEquals(NativeWindowOwnershipPolicy.Result.DIFFERENT_WINDOW, actual)
        assertFalse(actual.owned)
    }

    @Test fun foreignPackageWithoutAValidRootWindowRemainsUnverified() {
        for (value in listOf(ready.copy(activeWindow = -1, activePackage = "other.app"),
                ready.copy(activeRootPresent = false, activePackage = "other.app"))) {
            assertEquals(NativeWindowOwnershipPolicy.Result.UNVERIFIED, result(value))
        }
    }

    @Test fun observedOwnWindowWithoutNativeReadinessIsAnAppStateFailure() {
        val actual = result(ready.copy(nativeReady = false))
        assertEquals(NativeWindowOwnershipPolicy.Result.APP_NOT_READY, actual)
        assertEquals("app-window-not-ready", actual.classification)
        assertFalse(actual.owned)
    }

    @Test fun readFailureTakesPrecedenceOverPartialContradictoryMetadata() {
        assertEquals(NativeWindowOwnershipPolicy.Result.READ_FAILED,
            result(ready.copy(activePackage = "other.app", activeReadFailed = true)))
    }

    @Test fun theExistingOwnershipTruthTableIsUnchangedByEveryDiagnosticField() {
        // Preserve accepted IDs including zero. Metadata neither grants nor removes ownership.
        for (nativeReady in listOf(false, true)) for (target in listOf(-1, 0, 7))
        for (active in listOf(-1, 0, 7)) for (pkg in listOf("", "app", "other.app"))
        for (root in listOf(false, true)) for (rootFailure in listOf(false, true))
        for (targetFailure in listOf(false, true)) {
            val value = NativeWindowOwnershipPolicy.Evidence(nativeReady, target, active, pkg, "app", root, rootFailure, targetFailure)
            val accepted = nativeReady && pkg == "app" && (target == 0 && active == 0 || target == 7 && active == 7)
            assertEquals(value.toString(), accepted, result(value).owned)
        }
    }
}
