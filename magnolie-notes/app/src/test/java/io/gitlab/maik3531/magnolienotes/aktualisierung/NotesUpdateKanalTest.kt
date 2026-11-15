package io.gitlab.maik3531.magnolienotes.aktualisierung

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

class NotesUpdateKanalTest {
    @Test fun onlyExactKnownInstallerSelectsFdroidForOrdinaryBuilds() {
        assertTrue(NotesUpdateKanal.istFdroid(false, "org.fdroid.fdroid"))
        for (installer in listOf(null, "", "com.android.packageinstaller", "com.android.vending",
            "org.fdroid.fdroid.fake", "ORG.FDROID.FDROID", "org.fdroid.fdroid ")) {
            assertFalse(installer, NotesUpdateKanal.istFdroid(false, installer))
        }
    }

    @Test fun fdroidDistributionStaysOnItsChannelEvenWithoutInstallerMetadata() {
        for (installer in listOf(null, "", "com.android.packageinstaller", "org.fdroid.fdroid"))
            assertTrue(NotesUpdateKanal.istFdroid(true, installer))
        assertEquals("https://f-droid.org/en/packages/io.gitlab.maik3531.magnolienotes", NotesUpdateKanal.FDROID_SEITE)
    }

    @Test fun bothChannelMessagesArePresentInAllTwentyLanguages() {
        val files = File("app/src/main/res").listFiles()!!.map { File(it, "fdroid.xml") }.filter { it.isFile }
        assertEquals(20, files.size)
        for (file in files) {
            val nodes = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file).getElementsByTagName("string")
            val strings = (0 until nodes.length).associate { nodes.item(it).attributes.getNamedItem("name").nodeValue to nodes.item(it).textContent }
            for (key in listOf("about_update_fdroid", "about_update_fdroid_unknown"))
                assertTrue("$file: $key", strings[key]?.contains("F-Droid") == true)
        }
    }
}
