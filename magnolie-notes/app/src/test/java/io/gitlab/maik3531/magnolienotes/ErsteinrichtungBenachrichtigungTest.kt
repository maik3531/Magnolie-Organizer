package io.gitlab.maik3531.magnolienotes

import android.Manifest
import android.app.Application
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [34])
class ErsteinrichtungBenachrichtigungTest {
    private val app: Application get() = ApplicationProvider.getApplicationContext()

    @Test fun firstExplicitCompletionRequestsOnlyOnceAndOnlyAfterSaving() {
        assertFalse(Ersteinrichtung.abgeschlossen(app))
        shadowOf(app).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        var questions = 0
        assertTrue(Ersteinrichtung.abschliessenMitBenachrichtigungsfrage(app) {
            assertTrue(Ersteinrichtung.abgeschlossen(app))
            questions++
        })
        assertTrue(Ersteinrichtung.abschliessenMitBenachrichtigungsfrage(app) { questions++ })
        assertEquals(1, questions)
    }

    @Test fun setupAlreadyCompletedByAnOlderVersionNeverReasksAnExistingDenial() {
        assertTrue(Ersteinrichtung.abschliessen(app))
        shadowOf(app).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        assertTrue(Ersteinrichtung.abgeschlossen(app))
        assertTrue(Ersteinrichtung.abschliessenMitBenachrichtigungsfrage(app) { fail("Unexpected prompt") })
    }

    @Test fun permissionAlreadyGrantedDoesNotRequestItAgainAtFirstSetup() {
        shadowOf(app).grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        assertTrue(Ersteinrichtung.abschliessenMitBenachrichtigungsfrage(app) { fail("Unexpected prompt") })
    }

    @Test @Config(sdk = [28])
    fun preTiramisuDoesNotRequestAnUnavailablePermission() {
        assertTrue(Ersteinrichtung.abschliessenMitBenachrichtigungsfrage(app) { fail("Unexpected prompt") })
    }
}
