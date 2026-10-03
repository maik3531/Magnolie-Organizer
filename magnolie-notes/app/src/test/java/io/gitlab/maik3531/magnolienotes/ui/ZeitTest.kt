package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.content.res.Configuration
import android.provider.Settings
import androidx.test.core.app.ApplicationProvider
import java.util.Calendar
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class ZeitTest {
    private fun context(locale: Locale, clock: String?): Context {
        val base: Context = ApplicationProvider.getApplicationContext()
        Settings.System.putString(base.contentResolver, Settings.System.TIME_12_24, clock)
        return base.createConfigurationContext(Configuration(base.resources.configuration).apply { setLocale(locale) })
    }

    @Test fun explicitAndroidClockOverridesLanguageAndKeepsMinutes() {
        val english24 = context(Locale.US, "24")
        assertEquals("14:35", Zeit.erinnerungsUhrzeit(english24, 14 * 60 + 35))
        assertEquals("00:00", Zeit.erinnerungsUhrzeit(english24, 0))
        assertEquals("12:00", Zeit.erinnerungsUhrzeit(english24, 720))
        val german12 = context(Locale.GERMANY, "12")
        val afternoon = Zeit.erinnerungsUhrzeit(german12, 14 * 60 + 35)
        assertTrue(afternoon, afternoon.contains("2:35"))
        assertFalse(afternoon, afternoon.contains("14:35"))
        assertTrue(afternoon, afternoon.contains("PM"))
    }

    @Test fun localeDefaultAndNoonMidnightRemainUnambiguous() {
        val us = context(Locale.US, null)
        assertTrue(Zeit.erinnerungsUhrzeit(us, 0).contains("AM"))
        assertTrue(Zeit.erinnerungsUhrzeit(us, 720).contains("PM"))
        assertTrue(Zeit.erinnerungsUhrzeit(us, 23 * 60 + 59).contains("11:59"))
        val german = context(Locale.GERMANY, null)
        assertEquals("23:59", Zeit.erinnerungsUhrzeit(german, 1439))
    }

    @Test fun noteTimestampOmitsSecondsAndUsesSystemClock() {
        val context = context(Locale.US, "12")
        val time = Calendar.getInstance().apply {
            set(2026, Calendar.OCTOBER, 4, 14, 35, 47)
        }
        val shown = Zeit.uhrzeit(context, time.timeInMillis)
        assertTrue(shown, shown.contains("2:35"))
        assertTrue(shown, shown.contains("PM"))
        assertFalse(shown, shown.contains(":47"))
    }
}
