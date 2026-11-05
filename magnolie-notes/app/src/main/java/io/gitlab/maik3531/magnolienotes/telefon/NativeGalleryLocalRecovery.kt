package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal data class NativeGalleryRecoveryRow(val entry: NativeGalleryArchiveEntry, val action: NativeGalleryTrashAction?) {
    val canRestore: Boolean get() = action?.state in setOf("trashed", "restore_row_prepared") && entry.originalBytesVerified
}

/** Passive LOCAL UI owner, no TelefonWerk/connection/store/key construction.
 * It joins the SAME process-wide native source I/O lane. A missing archive is
 * empty, not an invitation to create fresh storage or replace a missing key. */
internal class NativeGalleryLocalRecovery(context: Context,
    private val protection: () -> DeviceTransferProtection = { DeviceTransferProtection.fromExistingAndroidPhoneKey() }) : AutoCloseable {
    private val app = context.applicationContext
    private val closed = AtomicBoolean(false)
    private val completion = AtomicReference<((NativeGallerySourceRun) -> Unit)?>()
    private val worker = NativeGallerySourceWorker({ _, _ -> throw PhotoFolderScopeError("gallery_recovery_source_read_not_supported") }) { run ->
        completion.getAndSet(null)?.let { callback -> Handler(Looper.getMainLooper()).post { if (!closed.get()) callback(run) } }
    }
    val present: Boolean get() = Files.exists(File(app.noBackupFilesDir, "native-media-recovery").toPath(), NOFOLLOW_LINKS)

    fun refresh(permit: NativeGalleryTrashBookPermit, result: (Result<List<NativeGalleryRecoveryRow>>) -> Unit) {
        uiThread(); permit.requireCurrent()
        val rows = AtomicReference<List<NativeGalleryRecoveryRow>>()
        begin({ run ->
            result(runCatching {
                run.nativeFailure()?.let { throw it }
                if (run.cancelRequested) throw PhotoFolderScopeError("gallery_recovery_canceled")
                permit.requireCurrent(); rows.get()
            })
        }) {
            worker.startLocalInspection { cancellation ->
                permit.requireCurrent(); cancellation.throwIfCanceled()
                rows.set(if (!present) emptyList() else NativeGalleryTrashArchive.openExistingForApplication(app, protection()).use { archive ->
                    val actions = archive.actions(permit).filter { it.state != "canceled" }.groupBy { it.archiveId }
                    archive.entries(permit).map { entry ->
                        val heads = actions[entry.id].orEmpty()
                        if (heads.size > 1) throw PhotoFolderScopeError("gallery_archive_original_action_pending")
                        NativeGalleryRecoveryRow(entry, heads.singleOrNull())
                    }
                })
                permit.requireCurrent(); cancellation.throwIfCanceled()
            }
        }
    }

    fun restore(session: NativeGalleryRestoreSession, result: (Result<NativeGalleryTrashAction>) -> Unit) {
        uiThread(); session.requireCurrent()
        begin({ run -> result(runCatching {
            run.nativeFailure()?.let { throw it }
            run.completedNativeRestoreAction() ?: throw PhotoFolderScopeError("gallery_restore_completion_not_proven")
        }) }) {
            worker.startTrash { cancellation ->
                if (!present) throw PhotoFolderScopeError("gallery_archive_original_storage_required")
                NativeGalleryTrashArchive.openExistingForApplication(app, protection()).use { archive ->
                    NativeGalleryMediaRestore(app).restore(archive, session, cancellation)
                }
            }
        }
    }

    private fun begin(callback: (NativeGallerySourceRun) -> Unit, start: () -> NativeGallerySourceRun) {
        if (closed.get() || !completion.compareAndSet(null, callback)) throw PhotoFolderScopeError("gallery_source_worker_busy")
        try { start() } catch (error: Throwable) { completion.compareAndSet(callback, null); throw error }
    }
    override fun close() { uiThread(); closed.set(true); worker.close() }
    private fun uiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) throw PhotoFolderScopeError("gallery_permission_ui_thread_required")
    }
}
