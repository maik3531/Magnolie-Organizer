package io.gitlab.maik3531.magnolienotes.baum

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QrPaarungsBestaetigungTest {
    @Test
    fun exportierterQrLinkErfordertSichtbareBestaetigungVorPaarung() {
        val source = File(
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        val baumwerk = File(
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Baumwerk.kt").readText()

        assertTrue(source.contains("AlertDialog("))
        assertTrue(source.contains("bestaetigteQrPaarung.value = vorschau.text"))
        assertTrue(source.contains("vorschau.fingerabdruck"))
        assertTrue(source.contains("absicht?.data = null"))
        assertTrue(source.contains("override fun onSaveInstanceState"))
        assertTrue(source.contains("zustand.getString(QR_PAARUNG)"))
        assertTrue(source.contains("zustand.getString(QR_PAARUNG_BESTAETIGT)"))
        assertTrue(source.contains("if (absicht?.dataString != null)"))
        assertFalse(source.contains("paareMitDatei(qrText)"))
        assertTrue(baumwerk.contains("@Synchronized\n    fun paareMitDatei"))
        assertTrue(baumwerk.contains("abgeschlosseneDateipaarungen[einladung]?.let { return it }"))
    }
}
