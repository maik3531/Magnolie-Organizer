package io.gitlab.maik3531.magnolietabletbeta

/** Public provider metadata only. Capability, not Android/Chrome version, gates the bridge. */
object WebViewStartup {
    const val REQUIRED_FEATURE = "WEB_MESSAGE_LISTENER"
    const val TERMINAL_REASON = "UnsupportedWebViewCapability"
    fun terminalReason(messageListenerSupported: Boolean): String? = if (messageListenerSupported) null else TERMINAL_REASON
    fun providerPackage(value: String?): String? = value?.takeIf {
        it.length <= 200 && Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+").matches(it)
    }
    fun providerVersion(value: String?): String? = value?.takeIf {
        it.isNotBlank() && it.length <= 80 && it.all { character -> character.code in 32..126 }
    }
}
