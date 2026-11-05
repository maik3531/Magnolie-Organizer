package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.UUID
import java.util.IdentityHashMap
import java.util.concurrent.atomic.AtomicBoolean

internal class NativeGalleryAlbumSelection internal constructor(internal val catalog: NativeGalleryAlbumCatalog,
    internal val album: GalleryAlbumCandidate, internal val desktopChoice: Boolean)

/** Native run owner admitted while its metadata selection is still fresh.
 * Not serializable; it cannot create a new selection after the metadata TTL.
 * close only revokes authority, never releases provider I/O or removes a job.
 */
internal class NativeGalleryAlbumLease internal constructor(private val owner: Any,
    private val selection: NativeGalleryAlbumSelection) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    internal val isClosed: Boolean get() = closed.get()
    private val album = selection.catalog.retain(owner, selection, this)

    fun resolve(currentOwner: Any): GalleryAlbumCandidate {
        if (currentOwner !== owner || closed.get()) DeviceFileControl.fail("gallery_album_owner_not_current")
        try {
            val actual = selection.catalog.resolveRetained(owner, this)
            if (closed.get() || actual !== album) DeviceFileControl.fail("gallery_album_owner_not_current")
            return actual
        } catch (error: Exception) { closed.set(true); throw error }
    }

    override fun close() { closed.set(true) }
}

/** Short-lived native discovery snapshot. Wire metadata/opaque IDs are not READ
 * grants; only this live native mapping can resolve an actual discovered album.
 * Page reads never mint a source lease or open photo bytes.
 */
internal class NativeGalleryAlbumCatalog internal constructor(internal val source: GalleryAlbumCatalog,
    private val workflowOwner: Any, private val current: () -> Boolean,
    private val monotonicMs: () -> Long = { DeviceFileControl.monotonicMs() }) : AutoCloseable {
    private val id = UUID.randomUUID().toString()
    private val issued = monotonicMs()
    private val expires = issued + DeviceFileControl.MAX_TTL_MS
    private val entries = source.albums.map { UUID.randomUUID().toString() to it }
    private var closed = false
    private var metadataExpired = false
    private var lastChecked = issued
    private val retained = IdentityHashMap<NativeGalleryAlbumLease, NativeGalleryAlbumSelection>()
    init {
        require(issued >= 0 && issued <= Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS)
        require(entries.size <= AndroidGalleryAlbumDiscovery.MAX_ALBUMS)
    }

    @Synchronized fun page(catalogId: String? = null, after: Int = 0): JsonObject {
        fresh()
        if (catalogId != null && catalogId != id || after !in 0..entries.size || after != 0 && catalogId == null)
            DeviceFileControl.fail("gallery_catalog_page_not_current")
        val albums = mutableListOf<JsonObject>()
        var cursor = after
        fun body() = buildJsonObject {
            put("format", JsonPrimitive(1)); put("catalog_id", JsonPrimitive(id)); put("after", JsonPrimitive(after))
            put("next_cursor", if (cursor < entries.size) JsonPrimitive(cursor) else JsonNull)
            put("coverage", JsonPrimitive(source.coverage.name.lowercase(java.util.Locale.ROOT)))
            put("proves_deletion", JsonPrimitive(false)); put("albums", JsonArray(albums.toList()))
        }
        while (cursor < entries.size) {
            val (key, album) = entries[cursor]
            albums += buildJsonObject {
                put("album_id", JsonPrimitive(key)); put("kind", JsonPrimitive(album.kind.name.lowercase(java.util.Locale.ROOT)))
                put("display_name", JsonPrimitive(album.displayName)); put("visible_images", JsonPrimitive(album.visibleImageCount))
                put("needs_choice", JsonPrimitive(album.needsAlbumChoice))
            }
            cursor++
            // Reserve generous space for the complete ordinary message header,
            // correlation fields and outer result metadata. No raw paths/IDs.
            if (TelefonKanonisch.bytes(body()).size > DeviceFileControl.MAX_WIRE_BYTES - 2048) {
                albums.removeAt(albums.lastIndex); cursor--
                if (albums.isEmpty()) DeviceFileControl.fail("gallery_catalog_entry_too_large")
                break
            }
        }
        fresh()
        return body()
    }

    @Synchronized fun select(catalogId: String, albumId: String, desktopChoice: Boolean): NativeGalleryAlbumSelection {
        fresh()
        if (catalogId != id) DeviceFileControl.fail("gallery_catalog_selection_not_current")
        val album = entries.singleOrNull { it.first == albumId }?.second
            ?: DeviceFileControl.fail("gallery_catalog_selection_not_current")
        if (album.needsAlbumChoice && !desktopChoice) DeviceFileControl.fail("gallery_source_choice_not_current")
        return NativeGalleryAlbumSelection(this, album, desktopChoice)
    }

    @Synchronized internal fun resolve(owner: Any, selection: NativeGalleryAlbumSelection): GalleryAlbumCandidate {
        fresh()
        checkSelection(owner, selection)
        return selection.album
    }

    private fun checkSelection(owner: Any, selection: NativeGalleryAlbumSelection) {
        if (owner !== workflowOwner || selection.catalog !== this || entries.none { it.second === selection.album } ||
            selection.album.needsAlbumChoice && !selection.desktopChoice) DeviceFileControl.fail("gallery_catalog_selection_not_current")
    }

    @Synchronized internal fun retain(owner: Any, selection: NativeGalleryAlbumSelection, lease: NativeGalleryAlbumLease): GalleryAlbumCandidate {
        fresh(); checkSelection(owner, selection)
        retained.keys.removeAll { it.isClosed }
        if (retained.size >= 4 || retained.containsKey(lease)) DeviceFileControl.fail("gallery_album_owner_bound")
        retained[lease] = selection
        return selection.album
    }

    @Synchronized internal fun resolveRetained(owner: Any, lease: NativeGalleryAlbumLease): GalleryAlbumCandidate {
        val selection = retained[lease] ?: DeviceFileControl.fail("gallery_album_owner_not_current")
        checkSelection(owner, selection)
        if (lease.isClosed) DeviceFileControl.fail("gallery_album_owner_not_current")
        // Actual permission/access epoch, native album namespace and workflow
        // lifetime stay live. Only the already-earned owner's metadata TTL is
        // not reapplied to a long-running transfer/continuation.
        live()
        return selection.album
    }

    private fun live() {
        if (closed) DeviceFileControl.fail("gallery_catalog_not_current")
        try {
            val now = monotonicMs()
            if (now < issued || now < lastChecked || !current()) DeviceFileControl.fail("gallery_catalog_not_current")
            val checked = monotonicMs()
            if (checked < now) DeviceFileControl.fail("gallery_catalog_not_current")
            lastChecked = checked
        } catch (error: Exception) { closed = true; throw error }
    }

    private fun fresh() {
        if (closed || metadataExpired) DeviceFileControl.fail("gallery_catalog_not_current")
        try {
            val now = monotonicMs()
            if (now < issued || now < lastChecked) DeviceFileControl.fail("gallery_catalog_not_current")
            if (now >= expires) { lastChecked = now; metadataExpired = true; DeviceFileControl.fail("gallery_catalog_not_current") }
            if (!current()) DeviceFileControl.fail("gallery_catalog_not_current")
            val checked = monotonicMs()
            if (checked < now) DeviceFileControl.fail("gallery_catalog_not_current")
            if (checked >= expires) { lastChecked = checked; metadataExpired = true; DeviceFileControl.fail("gallery_catalog_not_current") }
            lastChecked = checked
        } catch (error: Exception) { if (!metadataExpired) closed = true; throw error }
    }
    @Synchronized override fun close() { closed = true }
}
