package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import java.io.File
import java.time.YearMonth
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class ZeitMonatsDruckTest {
    @Test fun headerPrintUsesTheReviewedNameAndWaitsForTheRealSaveCallback() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val input = ZeiterfassungStand(reportName = "Before")
        val choice = ZeitMonatsDruckAuswahl(YearMonth.of(2026, 11), setOf(1, 5), "Synthetic month report")
        var calls = 0
        var completion: (() -> Unit)? = null
        zeitMonatDrucken(context, input, choice) { change, success ->
            assertEquals(input.copy(reportName = choice.name), change(input))
            calls++; completion = success
            // No successful SaveACK: no real printer/job is opened by this test.
        }
        assertEquals(1, calls); assertNotNull(completion)
    }

    @Test fun monthlyPrintUsesTheExistingDiscoveryIconAndClearsStaleSelectionsOnNavigation() {
        val root = File("app/src/main/java/io/gitlab/maik3531/magnolienotes")
        val main = File(root, "MainActivity.kt").readText()
        assertTrue(main.contains("if (blatt == 6 && zeitAnsicht == \"settings\") zeitDruckAuswahl?.let"))
        assertTrue(main.contains("EintragDruckKnopf(!zeitSpeichert && auswahl.tage.isNotEmpty())"))
        assertTrue(main.contains("zeitMonatDrucken(zusammenhang, bestand.zeiterfassung, auswahl, zeitSpeichern)"))
        val months = File(root, "ui/ZeitMonate.kt").readText()
        assertFalse(months.contains("R.string.zeit_drucken"))
        assertTrue(months.contains("onDispose { aktuelleDruckAuswahl(null) }"))
        val icon = File(root, "ui/EintragDrucken.kt").readText()
        assertTrue(icon.contains("if (automatic && !available) return"))
        assertTrue(icon.contains("search.erreichbar.collect { available = it }"))
        assertTrue(icon.contains("Lifecycle.State.RESUMED"))
    }
}
