package io.gitlab.maik3531.magnolienotes.telefon

import android.net.Uri
import android.provider.MediaStore

/** Native media domain, not a remotely supplied Android permission. Existing
 * photo policy/workflows default to IMAGES; VIDEO needs its own native request. */
internal enum class GalleryMediaType(val uriSegment: String, private val mimePrefix: String) {
    IMAGES("images", "image"), VIDEO("video", "video");

    fun acceptsMime(value: String): Boolean = Regex("$mimePrefix/[a-z0-9][a-z0-9.+-]{0,126}").matches(value)
    fun acceptsCoverage(value: GalleryReadCoverage): Boolean = value in setOf(GalleryReadCoverage.NONE,
        GalleryReadCoverage.SELECTED_ONLY, if (this == IMAGES) GalleryReadCoverage.FULL_IMAGES else GalleryReadCoverage.FULL_VIDEOS)

    fun collection(volume: String, modern: Boolean): Uri = if (this == IMAGES) {
        if (modern) MediaStore.Images.Media.getContentUri(volume) else MediaStore.Images.Media.EXTERNAL_CONTENT_URI
    } else {
        if (modern) MediaStore.Video.Media.getContentUri(volume) else MediaStore.Video.Media.EXTERNAL_CONTENT_URI
    }
}
