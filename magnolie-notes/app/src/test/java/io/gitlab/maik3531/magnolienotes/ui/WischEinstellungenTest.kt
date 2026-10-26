package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class WischEinstellungenTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    @Before fun clear() { context.getSharedPreferences("magnolie_swipe_view", Context.MODE_PRIVATE).edit().clear().commit() }
    @Test fun defaultsAreEnabledWithPhysicalLeftSyncAndRightDelete() {
        assertEquals(WischAnzeige(true, WischAktion.ABGLEICHEN, WischAktion.LOESCHEN), WischEinstellungen(context).lesen())
    }
    @Test fun disabledStateAndIndependentActionChoicesSurviveRecreation() {
        val changed = WischAnzeige(false, WischAktion.KEINE, WischAktion.ABGLEICHEN)
        WischEinstellungen(context).speichern(changed)
        assertEquals(changed, WischEinstellungen(context).lesen())
        WischEinstellungen(context).speichern(changed.copy(aktiv = true))
        assertEquals(changed.copy(aktiv = true), WischEinstellungen(context).lesen())
    }
}
