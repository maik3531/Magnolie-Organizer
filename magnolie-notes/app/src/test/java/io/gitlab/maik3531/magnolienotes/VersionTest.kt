package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionTest {
    @Test fun `Version ist 1 0 16`() {
        assertEquals("1.0.16", BuildConfig.VERSION_NAME.removeSuffix("-plaintext-fixture"))
        assertEquals(16, BuildConfig.VERSION_CODE)
    }
}
