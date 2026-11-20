package io.gitlab.maik3531.magnolienotes

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.Entwicklermodus.Medienphase
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class MedienDiagnoseTest {
    @Test fun mediaDiagnosticsAreLocalOptInBoundedAndClearedOnWithdrawal() {
        val context = ApplicationProvider.getApplicationContext<Application>()
        val writer = Entwicklermodus(context)
        val ui = Entwicklermodus(context)
        try {
            writer.deaktivieren()
            writer.medienEreignis(Medienphase.WEBCAM_FEHLER)
            ui.aktivieren()
            writer.medienEreignis(Medienphase.FOTO_DATEIKANAL_FEHLER)
            ui.wlanSetzen(true)
            assertTrue(ui.lokalerBericht().getValue("media_events").jsonArray.isEmpty())
            repeat(35) { writer.medienEreignis(Medienphase.FOTO_DATEIKANAL_BEREIT) }
            writer.medienEreignis(Medienphase.WEBCAM_SEND_BESTAETIGT)
            writer.medienEreignis(Medienphase.SPIEGELUNG_SEND_BESTAETIGT)
            val events = ui.lokalerBericht().getValue("media_events").jsonArray.map { it.jsonPrimitive.content }
            assertEquals(List(30) { "FOTO_DATEIKANAL_BEREIT" } +
                listOf("WEBCAM_SEND_BESTAETIGT", "SPIEGELUNG_SEND_BESTAETIGT"), events)
            assertFalse("media_events" in writer.bericht())
            assertFalse("media_events" in writer.bericht(mitAbsturz = true))
            ui.wlanSetzen(false)
            writer.medienEreignis(Medienphase.WEBCAM_FEHLER)
            ui.wlanSetzen(true)
            assertTrue(ui.lokalerBericht().getValue("media_events").jsonArray.isEmpty())
        } finally { ui.deaktivieren() }
    }
}
