package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionTest {
    @Test fun `Version ist 1 0 10`() {
        assertEquals("1.0.10", BuildConfig.VERSION_NAME.removeSuffix("-plaintext-fixture"))
        assertEquals(10, BuildConfig.VERSION_CODE)
    }
}
