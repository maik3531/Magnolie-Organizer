package io.gitlab.maik3531.magnolienotes.aktualisierung

import android.content.Context
import android.os.Build

/** Local distribution hint, never proof of APK authenticity or update authority. */
internal object NotesUpdateKanal {
    const val FDROID_PAKET = "org.fdroid.fdroid"
    const val FDROID_SEITE = "https://f-droid.org/en/packages/io.gitlab.maik3531.magnolienotes"

    fun istFdroid(fdroidBau: Boolean, installer: String?): Boolean =
        fdroidBau || installer == FDROID_PAKET

    @Suppress("DEPRECATION")
    fun installer(context: Context): String? = try {
        // Query only our own package; no installed-app inventory or new permission.
        if (Build.VERSION.SDK_INT >= 30)
            context.packageManager.getInstallSourceInfo(context.packageName).installingPackageName
        else context.packageManager.getInstallerPackageName(context.packageName)
    } catch (_: Exception) {
        // Missing/removed installer and denied metadata are unknown, not "direct APK".
        null
    }
}
