package io.gitlab.maik3531.magnolietabletbeta

/** Test-only scope: preserve the existing Google/generic emulator checks and
 * admit the single additional official AOSP model/brand observed in CI. */
internal object DisposableEmulatorPolicy {
    fun accepts(fingerprint: String, model: String, brand: String): Boolean =
        fingerprint.contains("generic") || model.contains("sdk") ||
            model == "Android SDK built for x86_64" && brand == "Android"
}
