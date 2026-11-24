package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class TelefonUpdateEmpfaengerTest {
    private val app get() = RuntimeEnvironment.getApplication() as Application
    private val settings get() = app.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE)
    private val replacement get() = Intent(Intent.ACTION_MY_PACKAGE_REPLACED).setPackage(app.packageName)

    @Suppress("DEPRECATION")
    private fun registeredReceiver(): BroadcastReceiver {
        val info = app.packageManager.queryBroadcastReceivers(replacement, 0).map { it.activityInfo }
            .singleOrNull { it.name == "${TelefonDienst::class.java.name.substringBeforeLast('.')}.TelefonUpdateEmpfaenger" }
            ?: throw AssertionError("No registered phone restart receiver for MY_PACKAGE_REPLACED")
        assertFalse(info.exported)
        return Class.forName(info.name).getDeclaredConstructor().newInstance() as BroadcastReceiver
    }

    @Test fun packageUpdateRequestsOnlyThePreviouslyEnabledPhoneServiceWithoutChangingSettings() {
        check(settings.edit().putBoolean("enabled", true).putBoolean("bluetooth_enabled", false).commit())
        val before = settings.all
        registeredReceiver().onReceive(app, replacement)
        val request = Shadows.shadowOf(app).nextStartedService
        assertNotNull(request)
        assertEquals(ComponentName(app, TelefonDienst::class.java), request!!.component)
        assertNull(Shadows.shadowOf(app).nextStartedActivity)
        assertEquals(before, settings.all)
    }

    @Test fun packageUpdateLeavesAnOffServiceOffAndIgnoresOtherBroadcasts() {
        val receiver = registeredReceiver()
        val shadow = Shadows.shadowOf(app)
        for (enabled in listOf(null, false, true)) {
            val edit = settings.edit().remove("enabled")
            if (enabled != null) edit.putBoolean("enabled", enabled)
            check(edit.commit())
            val before = settings.all
            receiver.onReceive(app, if (enabled == true) Intent(Intent.ACTION_PACKAGE_REPLACED) else replacement)
            assertNull(shadow.nextStartedService)
            assertEquals(before, settings.all)
        }
    }

    @Test fun stickyRestartCannotReenableTheServiceAfterUserStop() {
        check(settings.edit().putBoolean("enabled", false).commit())
        val service = Robolectric.buildService(TelefonDienst::class.java).create()
        try {
            assertEquals(android.app.Service.START_NOT_STICKY, service.get().onStartCommand(null, 0, 1))
            assertTrue(Shadows.shadowOf(service.get()).isStoppedBySelf)
            assertFalse(settings.getBoolean("enabled", true))
        } finally {
            service.destroy()
        }
    }
}
