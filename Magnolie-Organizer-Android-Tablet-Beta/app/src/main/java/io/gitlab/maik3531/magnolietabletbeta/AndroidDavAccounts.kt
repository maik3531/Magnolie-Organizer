package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context

/** GUI and bridge callers share one canonical native account service and its revision fence. */
internal object AndroidDavAccounts {
    private var instance: DavAccountService? = null
    @Synchronized fun service(context: Context): DavAccountService {
        instance?.let { return it }
        val ops = AndroidOsStorageFileOps
        val directory = ops.ensurePrivateDirectory(context.noBackupFilesDir)
        return DavAccountService(DavAccountFileStore(directory, fileOps = ops),
            DavStoredAccountCredentials(AndroidDavCredentials.store(context))).also { instance = it }
    }
}
