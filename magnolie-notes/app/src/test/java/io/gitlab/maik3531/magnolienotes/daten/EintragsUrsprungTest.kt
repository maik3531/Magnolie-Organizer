package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Test

class EintragsUrsprungTest {
    @Test fun legacyOriginsStayUnknownWithoutEvidence() {
        assertEquals("", EintragsUrsprung.erhalten("", null))
        assertEquals("", EintragsUrsprung.erhalten(null, "last_sender"))
    }
    @Test fun firstReliableOriginSurvivesEditsAndOlderPeers() {
        for (app in listOf("notes", "organizer")) {
            assertEquals(app, EintragsUrsprung.erhalten(app, null))
            assertEquals(app, EintragsUrsprung.erhalten(app, ""))
            assertEquals(app, EintragsUrsprung.erhalten(app, if (app == "notes") "organizer" else "notes"))
        }
    }
    @Test fun unknownHistoryCanReceiveExplicitCreationProvenance() {
        assertEquals("notes", EintragsUrsprung.erhalten("", "notes"))
        assertEquals("organizer", EintragsUrsprung.erhalten(null, "organizer"))
    }
}
