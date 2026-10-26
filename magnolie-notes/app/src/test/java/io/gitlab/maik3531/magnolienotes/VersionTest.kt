package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionTest {
    @Test fun `Version ist 1 0 21`() {
        assertEquals("1.0.21", BuildConfig.VERSION_NAME.removeSuffix("-plaintext-fixture"))
        assertEquals(21, BuildConfig.VERSION_CODE)
    }
}
