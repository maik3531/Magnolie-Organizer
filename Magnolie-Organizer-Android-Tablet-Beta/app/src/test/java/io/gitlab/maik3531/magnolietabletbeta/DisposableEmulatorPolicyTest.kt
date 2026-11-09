package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class DisposableEmulatorPolicyTest {
    @Test fun existingGoogleAndGenericEmulatorsAndTheObservedAOSPImageAreAllowed() {
        assertTrue(DisposableEmulatorPolicy.accepts("google/sdk_gphone64_x86_64/emu64xa", "sdk_gphone64_x86_64", "google"))
        assertTrue(DisposableEmulatorPolicy.accepts("generic_x86_64", "Emulator", "Android"))
        assertTrue(DisposableEmulatorPolicy.accepts("Android/aosp_x86_64/emulator64_x86_64", "Android SDK built for x86_64", "Android"))
    }
    @Test fun physicalModelsAndUnprovenAOSPBrandModelCombinationsAreRejected() {
        for ((model, brand) in listOf("Pixel 9" to "google", "SM-X910" to "samsung", "iPhone" to "Apple",
            "Android SDK built for x86_64" to "google", "Android SDK built for x86_64" to "android",
            "Android SDK built for arm64" to "Android", "Android SDK built for X86_64" to "Android")) {
            assertFalse("Unexpected device scope: $model / $brand", DisposableEmulatorPolicy.accepts("release/device/physical", model, brand))
        }
    }
}
