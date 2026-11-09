package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class WebViewStartupTest {
    @Test fun capabilityIsAuthoritativeInsteadOfAndroidOrProviderVersion() {
        assertNull(WebViewStartup.terminalReason(true))
        assertEquals("UnsupportedWebViewCapability",WebViewStartup.terminalReason(false))
        assertEquals("WEB_MESSAGE_LISTENER",WebViewStartup.REQUIRED_FEATURE)
        assertEquals("69.0.3497.100",WebViewStartup.providerVersion("69.0.3497.100"))
        assertEquals("999.0",WebViewStartup.providerVersion("999.0"))
    }
    @Test fun unknownOrMalformedProviderCannotProduceAPackageUpdateTarget() {
        for(value in listOf(null,"","com..webview","file:///data/app","com.webview?id=other","com.webview\nother","../provider","x".repeat(201)))
            assertNull(WebViewStartup.providerPackage(value))
        for(value in listOf("com.android.chrome","com.google.android.webview","com.android.webview","org.example.WebView_1"))
            assertEquals(value,WebViewStartup.providerPackage(value))
        for(value in listOf(null,"","\n69.0","x".repeat(81))) assertNull(WebViewStartup.providerVersion(value))
    }
}
