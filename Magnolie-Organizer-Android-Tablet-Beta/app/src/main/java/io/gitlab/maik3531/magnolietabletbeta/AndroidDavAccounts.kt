package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermission

/** GUI and bridge callers share one canonical native account service and its revision fence. */
internal object AndroidDavAccounts {
    private var instance: DavAccountService? = null
    @Synchronized fun service(context: Context): DavAccountService {
        instance?.let { return it }
        // Android may provision an app-private child with group traversal bits. Keep account
        // metadata private at this boundary as well as at its already private app-data parent.
        val directory = context.noBackupFilesDir
        Files.setPosixFilePermissions(directory.toPath(), setOf(PosixFilePermission.OWNER_READ,
            PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE))
        return DavAccountService(DavAccountFileStore(directory),
            DavStoredAccountCredentials(AndroidDavCredentials.store(context))).also { instance = it }
    }
}
