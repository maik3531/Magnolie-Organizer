package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class AblageAtomicSourceTest {
    @Test fun `durable writes have no non atomic overwrite fallback`() {
        for (path in listOf(
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/Ablage.kt",
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonAblage.kt")) {
            val source = File(path).readText()
            assertTrue(source.contains("fd.sync()"))
            assertTrue(source.contains("StandardCopyOption.ATOMIC_MOVE"))
            assertFalse(source.contains("AtomicMoveNotSupportedException"))
        }
        val source = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/Ablage.kt").readText()
        val function = source.indexOf("private fun schreibeBestand")
        val durableWrite = source.indexOf("schreiben(notizDatei", function)
        assertTrue(durableWrite < source.indexOf("_bestand.value = neu", durableWrite))
    }
}
