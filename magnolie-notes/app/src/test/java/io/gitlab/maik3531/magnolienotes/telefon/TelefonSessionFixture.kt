package io.gitlab.maik3531.magnolienotes.telefon

/** Synthetic fixture equivalent of session()'s authenticated original-pipe binding. */
internal fun bindSyntheticPhoneSession(work: TelefonWerk, channel: TelefonSecureChannel) {
    val transportField = TelefonWerk::class.java.getDeclaredField("activeTransport").apply { isAccessible = true }
    @Suppress("UNCHECKED_CAST")
    val transport = requireNotNull(transportField.get(work) as Pair<TelefonTransportArt, TelefonRoehre>?)
    val pipesField = TelefonWerk::class.java.getDeclaredField("sessionPipes").apply { isAccessible = true }
    @Suppress("UNCHECKED_CAST")
    val pipes = pipesField.get(work) as MutableMap<TelefonSecureChannel, TelefonRoehre>
    pipes[channel] = transport.second
}
