package io.gitlab.maik3531.magnolienotes.aktualisierung

import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 30])
class NotesInstallSourceTest {
    @Suppress("DEPRECATION")
    @Test fun ownInstallerMetadataUsesBothSupportedAndroidApiPaths() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val manager = context.packageManager
        fun installSource(installer: String?) {
            // Robolectric stores modern InstallSourceInfo separately from its
            // legacy installer map; populate the actual API under test.
            if (Build.VERSION.SDK_INT >= 30)
                shadowOf(manager).setInstallSourceInfo(context.packageName, "unrelated.initiator", installer)
            else manager.setInstallerPackageName(context.packageName, installer)
        }
        installSource(NotesUpdateKanal.FDROID_PAKET)
        assertEquals(NotesUpdateKanal.FDROID_PAKET, NotesUpdateKanal.installer(context))
        assertTrue(NotesUpdateKanal.istFdroid(false, NotesUpdateKanal.installer(context)))
        installSource(null)
        assertNull(NotesUpdateKanal.installer(context))
        assertFalse(NotesUpdateKanal.istFdroid(false, NotesUpdateKanal.installer(context)))
    }

    @Test fun deniedInstallerMetadataRemainsUnknown() {
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getPackageManager(): PackageManager = throw SecurityException("unavailable")
        }
        assertNull(NotesUpdateKanal.installer(context))
        assertFalse(NotesUpdateKanal.istFdroid(false, NotesUpdateKanal.installer(context)))
        assertTrue(NotesUpdateKanal.istFdroid(true, NotesUpdateKanal.installer(context)))
    }
}
