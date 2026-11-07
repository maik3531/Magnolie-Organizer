package io.gitlab.maik3531.magnolienotes.telefon

import java.util.concurrent.atomic.AtomicReference

/** Exact process-wide media IO ownership shared by source, local recovery and
 * incoming publication. Cancellation alone never releases a descriptor owner. */
internal object NativeGalleryMediaIoLane {
    private val owner = AtomicReference<Any?>()
    internal fun acquire(selected: Any): Boolean = owner.compareAndSet(null, selected)
    internal fun release(selected: Any) { owner.compareAndSet(selected, null) }
}
