package io.gitlab.maik3531.magnolienotes

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseSigningKonfigurationTest {
    @Test
    fun `Gradle Signingpruefung ist fail closed und Release Build haengt davon ab`() {
        val gradle = File("app/build.gradle.kts").readText()

        assertFalse(gradle.contains("signingConfig == null ||"))
        assertTrue(gradle.contains("signingConfig != null && signingConfig.name == \"freigabe\""))
        assertTrue(gradle.contains("keyStore.isKeyEntry(alias)"))
        assertTrue(gradle.contains("it.value.toString() == \"Android Debug\""))
        assertTrue(gradle.contains("dependsOn(pruefeReleaseSigningKonfiguration)"))
    }

    @Test
    fun `Release Gate prueft Signing in eigener Phase vor dem Build`() {
        val gate = File("werkzeuge/release-gate.sh").readText()
        val integrationstest = File("werkzeuge/test-release-signing.sh").readText()
        val pruefung = gate.indexOf("pruefeReleaseSigningKonfiguration")
        val build = gate.indexOf("clean testReleaseUnitTest lintRelease")

        assertTrue(pruefung >= 0)
        assertTrue(build > pruefung)
        assertTrue(gate.contains("--signing-only"))
        assertTrue(integrationstest.contains("nicht-vorhanden.properties"))
        assertTrue(integrationstest.contains("nicht-vorhanden.jks"))
        assertTrue(integrationstest.contains("CN=Android Debug"))
    }
}
