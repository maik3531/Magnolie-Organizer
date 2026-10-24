package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.Entwicklermodus
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
@LooperMode(LooperMode.Mode.PAUSED)
class VersionsKlicksTest {
    private fun advance(ms: Long) = shadowOf(Looper.getMainLooper()).idleFor(ms, TimeUnit.MILLISECONDS)

    @Test fun singleClickWaitsAFullSecondAndOnlyOpensOnce() {
        var about = 0
        var versions = 0
        val clicks = VersionsKlicks({ about++ }, { versions++ })
        clicks.klicken(); advance(999)
        assertEquals(0, about); assertEquals(1, versions)
        advance(1); assertEquals(1, about)
        advance(2_000); assertEquals(1, about)
    }

    @Test fun multipleClicksSuppressAboutAndKeepTheExistingTenClickDeveloperGesture() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("magnolie_developer", Context.MODE_PRIVATE).edit().clear().commit()
        val developer = Entwicklermodus(context)
        var about = 0
        val clicks = VersionsKlicks({ about++ }, { developer.versionAngeklickt() })
        repeat(9) { clicks.klicken(); advance(90); assertFalse(developer.an) }
        clicks.klicken(); assertTrue(developer.an)
        advance(1_000); assertEquals(0, about)
        clicks.klicken(); advance(1_000); assertEquals(1, about)
        assertFalse(developer.wlan)
    }

    @Test fun navigationOrLifecycleCancellationPreventsDelayedAboutAndAllowsANewSingleClick() {
        var about = 0
        val clicks = VersionsKlicks({ about++ }, {})
        clicks.klicken(); advance(500); clicks.abbrechen()
        advance(1_000); assertEquals(0, about)
        clicks.klicken(); advance(1_000); assertEquals(1, about)
        clicks.klicken(); clicks.klicken(); advance(1_000); assertEquals(1, about)
    }
}
