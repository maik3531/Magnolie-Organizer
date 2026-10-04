package io.gitlab.maik3531.magnolienotes.daten

import android.app.Application
import android.app.Notification
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.zeit.ZeitDienst
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28])
class ZeitStatusTest {
    @Test fun activeAndPausedStatusUseBriefcaseAndOpenTheTrackingPage() {
        val context: Context = ApplicationProvider.getApplicationContext()
        val running = Zeiteintrag(startMinute = 1000, type = "Synthetic activity")
        val notification = ZeitDienst.notification(context, running, 1060)
        assertEquals(R.drawable.ic_zeiterfassung, notification.smallIcon.resId)
        assertTrue(notification.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertTrue(notification.flags and Notification.FLAG_ONLY_ALERT_ONCE != 0)
        assertFalse(notification.extras.getBoolean(Notification.EXTRA_SHOW_CHRONOMETER))
        assertTrue(shadowOf(notification.contentIntent).savedIntent.getBooleanExtra(MainActivity.ZEIGE_ZEITERFASSUNG, false))
        val paused = ZeitDienst.notification(context, running.pause(1010), 1020)
        assertEquals(R.drawable.ic_zeiterfassung, paused.smallIcon.resId)
        assertTrue(paused.extras.getCharSequence(Notification.EXTRA_TEXT).toString().contains(context.getString(R.string.zeit_pause_aktiv)))
    }
}
