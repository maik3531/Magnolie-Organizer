package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.app.Service
import android.content.Intent
import android.media.projection.MediaProjection
import android.os.IBinder
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** Real ActivityResult/lifecycle path in Robolectric, not device consent or capture. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneScreenConsentTest {
    class OrdinaryService : Service() {
        var projectionLookups = 0
        override fun onBind(intent: Intent?): IBinder? = null
        override fun getSystemService(name: String): Any? {
            if (name == MEDIA_PROJECTION_SERVICE) projectionLookups++
            return super.getSystemService(name)
        }
    }

    private class Fixture : AutoCloseable {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val activity = controller.get()
        private val shadow = Shadows.shadowOf(activity)
        var live = true
        var competing = false
        var now = 100L
        val host = PhoneScreenConsentHost(activity) { competing }
        val outcomes = mutableListOf<Result<PhoneScreenViewConsent>>()
        fun original() = PhoneScreenViewRequest({ check(live) }, { now })
        fun lock() {
            Shadows.shadowOf(activity.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(true)
        }
        fun noPrompt() = shadow.nextStartedActivityForResult == null
        fun prompt(request: PhoneScreenViewRequest): Int {
            host.request(request) { outcomes += it }
            val launched = checkNotNull(shadow.nextStartedActivityForResult)
            assertNotNull(launched.intent.component) // Android's actual capture intent, not a Notes settings Activity.
            assertNotEquals(activity.packageName, launched.intent.component!!.packageName)
            return launched.requestCode
        }
        fun result(code: Int, result: Int = Activity.RESULT_OK, data: Intent? = Intent()) {
            activity.activityResultRegistry.dispatchResult(code, result, data)
        }
        override fun close() {
            outcomes.forEach { it.getOrNull()?.close() }
            host.close()
            controller.pause().stop().destroy()
        }
    }

    @Test fun onlyExplicitVisibleRequestLaunchesScreenDialog() {
        Fixture().use { f ->
            assertTrue(f.noPrompt())
            val first = f.original()
            f.controller.pause()
            assertThrows(IllegalStateException::class.java) { f.host.request(first) {} }
            assertTrue(f.noPrompt())
            f.controller.resume()
            f.competing = true
            assertThrows(IllegalStateException::class.java) { f.host.request(first) {} }
            assertTrue(f.noPrompt())
            f.competing = false
            val code = f.prompt(first)
            assertTrue(f.host.requestPending)
            assertThrows(IllegalStateException::class.java) { f.host.request(f.original()) {} }
            f.result(code, Activity.RESULT_CANCELED)
            assertTrue(f.outcomes.single().isFailure)
            assertThrows(IllegalStateException::class.java) { f.host.request(first) {} }
        }
    }

    @Test fun delayedOriginalResultOnlyCompletesAfterResumeAndStaleResultCannotRetarget() {
        Fixture().use { f ->
            val first = f.prompt(f.original())
            f.controller.pause()
            f.result(first)
            assertTrue(f.outcomes.isEmpty())
            f.controller.resume()
            assertTrue(f.outcomes.single().isSuccess)
            f.outcomes.single().getOrThrow().close()
            val second = f.prompt(f.original())
            assertNotEquals(first, second)
            f.result(first)
            assertEquals(1, f.outcomes.size)
            f.result(second, data = null)
            assertTrue(f.outcomes.last().isFailure)
        }
    }

    @Test fun peerLossDeadlineAndHostCloseDenyOriginalResult() {
        for (change in listOf("peer", "deadline", "close", "revocation", "lock")) Fixture().use { f ->
            val request = f.original()
            val code = f.prompt(request)
            when (change) {
                "peer" -> f.live = false
                "deadline" -> f.now += 60_000
                "close" -> f.host.close()
                "revocation" -> request.close()
                "lock" -> f.lock()
            }
            f.result(code)
            assertTrue(change, f.outcomes.single().isFailure)
        }
    }

    @Test fun runningRequestStillRequiresOriginalContextAfterConsentWindow() {
        Fixture().use { f ->
            val original = f.original()
            original.claimPrompt()
            original.markProjectionStarted() // Lifecycle unit check, no Android token or projection.
            f.now += 60_000
            original.requireCurrent()
            f.live = false
            assertThrows(IllegalStateException::class.java) { original.requireCurrent() }
            f.live = true
            assertThrows(IllegalStateException::class.java) { original.requireCurrent() }
            f.lock()
            assertThrows(IllegalStateException::class.java) { f.host.request(f.original()) {} }
            assertTrue(f.noPrompt())
        }
    }

    @Test fun wrongOriginalAndNotForegroundAreRejectedBeforeProjectionLookupAndNoRetry() {
        Fixture().use { f ->
            val original = f.original()
            f.result(f.prompt(original))
            val consent = f.outcomes.single().getOrThrow()
            val service = Robolectric.buildService(OrdinaryService::class.java).create().get()
            val callback = object : MediaProjection.Callback() {}
            assertThrows(IllegalStateException::class.java) { consent.open(f.original(), service, callback) }
            val failure = assertThrows(IllegalStateException::class.java) { consent.open(original, service, callback) }
            assertEquals("screen_actual_projection_foreground_required", failure.message)
            val retry = assertThrows(IllegalStateException::class.java) { consent.open(original, service, callback) }
            assertEquals("screen_os_result_already_consumed", retry.message)
            assertEquals(0, service.projectionLookups)
        }
    }
}
