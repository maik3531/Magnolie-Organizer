package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionTest {
    @Test fun `Version ist 1 0 21`() {
        val validation = System.getProperty("magnolieTarget37Validation", "false").toBooleanStrict()
        val suffix = if (validation) {
            assertEquals("release", BuildConfig.BUILD_TYPE)
            "-api37-validation"
        } else if (BuildConfig.BUILD_TYPE == "fixture") "-plaintext-fixture" else ""
        assertEquals("1.0.21$suffix", BuildConfig.VERSION_NAME)
        assertEquals(21, BuildConfig.VERSION_CODE)
    }
}
