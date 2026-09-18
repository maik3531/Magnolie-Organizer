package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TelefonNummernTest {
    @Test fun `nationale DE und AT Nummern werden mit SIM Land E164`() {
        assertEquals("+4930123456", TelefonNummern.e164("030 123456", "DE"))
        assertEquals("+431234567", TelefonNummern.e164("01 234567", "AT"))
        assertEquals("+431234567", TelefonNummern.e164("+43 1 234567", null))
        assertEquals("", TelefonNummern.e164("030 123456", null))
    }

    @Test fun `SIM Land gewinnt und roaming verhindert Netzwerk Fallback`() {
        assertEquals("AT", TelefonNummern.land("at", "DE", true))
        assertNull(TelefonNummern.land(null, "DE", true))
        assertEquals("DE", TelefonNummern.land(null, "de", false))
        assertNull(TelefonNummern.land(null, null, false))
    }

    @Test fun `Status unterscheidet ungueltig nichtleer von unterdrueckt`() {
        assertEquals("available", TelefonNummern.status(true, true, true, "030 123456", "+4930123456", true))
        assertEquals("unavailable", TelefonNummern.status(true, true, true, "nicht gueltig", "", true))
        assertEquals("withheld", TelefonNummern.status(true, true, true, "", "", true))
        assertEquals("unavailable", TelefonNummern.status(true, true, true, "", "", false))
        assertEquals("permission_missing", TelefonNummern.status(true, false, true, "", "", true))
        assertEquals("not_shared", TelefonNummern.status(false, true, true, "", "", true))
    }

    @Test fun `widerspruechliche SIM Laender behaupten ohne Bindung kein Land`() {
        assertNull(TelefonNummern.land(null, listOf("DE", "AT"), "DE", false))
        assertEquals("DE", TelefonNummern.land(null, listOf("DE", "de"), "AT", false))
        assertEquals("AT", TelefonNummern.land("AT", listOf("DE", "AT"), "DE", false))
    }
}
