package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.UUID

internal class NativeGalleryAlbumSelection internal constructor(internal val catalog: NativeGalleryAlbumCatalog,
    internal val album: GalleryAlbumCandidate, internal val desktopChoice: Boolean)

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
        if (owner !== workflowOwner || selection.catalog !== this || entries.none { it.second === selection.album } ||
            selection.album.needsAlbumChoice && !selection.desktopChoice) DeviceFileControl.fail("gallery_catalog_selection_not_current")
        return selection.album
    }

    private fun fresh() {
        if (closed) DeviceFileControl.fail("gallery_catalog_not_current")
        try {
            val now = monotonicMs()
            if (now < issued || now >= expires || !current()) DeviceFileControl.fail("gallery_catalog_not_current")
            val checked = monotonicMs()
            if (checked < now || checked >= expires) DeviceFileControl.fail("gallery_catalog_not_current")
        } catch (error: Exception) { closed = true; throw error }
    }
    @Synchronized override fun close() { closed = true }
}
