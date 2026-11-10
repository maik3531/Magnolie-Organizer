package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamForegroundTest {
    @Test fun noRegisteredActivityDoesNotLaunchUiOrPersistAnOriginalRequest() {
        val request = PhoneWebcamCaptureRequest("c".repeat(32), false, false, {})
        try {
            assertThrows(IllegalStateException::class.java) { PhoneWebcamForeground.request(request) {} }
        } finally { request.close() }
    }

    @Test fun registrationAloneDoesNotPromptAndExplicitOriginalRequestUsesRealOsResult() {
        PhoneWebcamPermissionHostTest.Fixture().use { f ->
            PhoneWebcamForeground.register(f.host)
            try {
                assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
                PhoneWebcamForeground.request(f.request()) { f.results += it }
                f.grant(); f.result()
                assertTrue(f.results.single().isSuccess)
            } finally { PhoneWebcamForeground.unregister(f.host) }
        }
    }

    @Test fun stoppedActivityAndEachCompetingPermissionSlotCannotBeUsedAsBackgroundStart() {
        // The same guard backs each of the four actual gallery slots in MainActivity.
        repeat(4) {
            PhoneWebcamPermissionHostTest.Fixture().use { f ->
                PhoneWebcamForeground.register(f.host)
                try {
                    f.competing = true
                    assertThrows(IllegalStateException::class.java) { PhoneWebcamForeground.request(f.request()) {} }
                    assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
                    f.competing = false; f.controller.pause().stop()
                    assertThrows(IllegalStateException::class.java) { PhoneWebcamForeground.request(f.request()) {} }
                    assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
                    f.controller.start().resume()
                } finally { PhoneWebcamForeground.unregister(f.host) }
            }
        }
    }

    @Test fun oldActivityDestructionCannotUnregisterANewerOriginalHost() {
        val old = Robolectric.buildActivity(ComponentActivity::class.java).create()
        val oldHost = PhoneWebcamPermissionHost(old.get()) { false }
        PhoneWebcamForeground.register(oldHost)
        try {
            PhoneWebcamPermissionHostTest.Fixture().use { f ->
                PhoneWebcamForeground.register(f.host)
                try {
                    PhoneWebcamForeground.unregister(oldHost)
                    oldHost.close(); old.destroy()
                    PhoneWebcamForeground.request(f.request()) { f.results += it }
                    f.grant(); f.result()
                    assertTrue(f.results.single().isSuccess)
                } finally { PhoneWebcamForeground.unregister(f.host) }
            }
        } finally { PhoneWebcamForeground.unregister(oldHost) }
    }
}
