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
class DruckerEinstellungenTest {
    private lateinit var context: Context
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("magnolie_print_view", Context.MODE_PRIVATE).edit().clear().commit()
    }
    @Test fun normalPrintingRemainsAvailableForPdfAndOtherServicesByDefault() {
        assertFalse(DruckerEinstellungen.automatisch(context))
    }
    @Test fun optionalWifiVisibilitySurvivesRecreationAndCanBeDisabledAgain() {
        DruckerEinstellungen.automatisch(context, true)
        assertTrue(DruckerEinstellungen.automatisch(context))
        DruckerEinstellungen.automatisch(context, false)
        assertFalse(DruckerEinstellungen.automatisch(context))
    }
}
