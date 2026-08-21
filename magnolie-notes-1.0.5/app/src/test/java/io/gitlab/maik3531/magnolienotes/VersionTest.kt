package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionTest {
    @Test fun `Version ist 1 0 5`() {
        assertEquals("1.0.5", BuildConfig.VERSION_NAME)
        assertEquals(5, BuildConfig.VERSION_CODE)
    }
}
