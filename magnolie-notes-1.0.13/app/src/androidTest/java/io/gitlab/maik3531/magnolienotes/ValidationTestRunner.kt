package io.gitlab.maik3531.magnolienotes

import android.app.Activity
import android.app.Instrumentation
import android.os.Build
import android.os.Bundle
import org.junit.runner.JUnitCore
import org.junit.runner.Request

/** Cannot execute against the production package or a physical device. */
class ValidationTestRunner : Instrumentation() {
    private var phase = "core"
    var hostPicker = false
        private set
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        check(targetContext.packageName == "io.gitlab.maik3531.magnolienotes.validation")
        check(Build.HARDWARE in setOf("ranchu", "goldfish"))
        instance = this
        phase = arguments?.getString("phase") ?: "core"
        hostPicker = phase == "saf-host"
        start()
    }
    override fun onStart() {
        val names = when (phase) {
            "storage" -> listOf("directorySyncUsesReadableDescriptorAndPropagatesErrors", "ambiguousCommitRefusesWritesUntilRecovery")
            "background" -> listOf("foregroundLifecycleIsIdempotentAndStopsInBackground", "journalOffCancelsAndReenableSchedules",
                "doneBroadcastPersistsThroughRealWorkManager", "masterOffPurgesEncryptedNotificationQueueAndRejectsCapture",
                "backupWorkerMissingFolderAndGrantFailSafely")
            "background-restart" -> listOf("disabledServicesStayDisabledAfterProcessRestart")
            "core" -> listOf("startupAndKeystore", "safAutomaticBackup", "contactsInIsolatedAccount", "authenticatedUpgradeAndReplay", "editorBackSaves")
            "seed" -> listOf("seedDraftAndRotate")
            "restart" -> listOf("verifyDraftAfterProcessDeath")
            "editor" -> listOf("editorBackSaves")
            "saf" -> listOf("safAutomaticBackup")
            "saf-host" -> listOf("startupAndKeystore", "safAutomaticBackup")
            "saf-restart" -> listOf("safBackupAfterRestart")
            "saf-metadata" -> listOf("safProviderMetadata")
            else -> error("Unknown validation phase")
        }
        var count = 0; var failures = 0
        val summary = StringBuilder()
        names.forEach { name ->
            val target = when {
                phase == "storage" -> StorageDurabilityInstrumentationTest::class.java
                phase.startsWith("background") -> BackgroundServiceInstrumentationTest::class.java
                else -> NativeValidationTest::class.java
            }
            val result = JUnitCore().run(Request.method(target, name))
            val passed = result.wasSuccessful() && result.runCount == 1 && result.ignoreCount == 0 && result.assumptionFailureCount == 0
            count += result.runCount
            if (!passed) failures += maxOf(1, result.failureCount)
            summary.append(name).append(if (passed) ": PASS\n" else ": FAIL\n")
            result.failures.forEach { failure ->
                summary.append(failure.exception.javaClass.name).append(" at ")
                    .append(failure.exception.stackTrace.filter { it.className.contains("magnolienotes") }.take(4).joinToString("; ")).append('\n')
            }
        }
        finish(if (failures == 0) Activity.RESULT_OK else Activity.RESULT_CANCELED, Bundle().apply {
            putString("stream", summary.toString()); putInt("numtests", count); putInt("failures", failures)
        })
    }
    companion object { lateinit var instance: ValidationTestRunner; private set }
}
