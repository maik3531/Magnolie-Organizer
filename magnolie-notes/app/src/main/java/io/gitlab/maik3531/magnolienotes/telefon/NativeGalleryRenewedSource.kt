package io.gitlab.maik3531.magnolienotes.telefon

/** Keeps the ACTUAL new native lease; historical cryptographic metadata never
 * becomes a reconstructed permission/owner object. */
internal class NativeGalleryRenewalAuthority(private val scope: GalleryPhotoSourceScope,
    private val freshLease: GalleryPhotoSourceLease, private val permitted: () -> Unit) : NativePhotoSourceAuthority {
    override fun isCurrent(lease: NativePhotoSourceLease): Boolean = lease === freshLease && runCatching {
        permitted(); scope.isCurrent(freshLease)
    }.getOrDefault(false)
}

/** Local read-only source. Deliberately has NO offer/acceptance/wire/cleanup API.
 * A separate native run and bounded resume-attempt protocol are still required. */
internal class NativeGalleryRenewedSource internal constructor(val job: PhotoSourceJob,
    private val snapshot: ProtectedPhotoSourceSnapshot, private val original: PhotoSourceRemoteAcceptance) {
    val manifest: DeviceFileManifest get() = snapshot.manifest
    fun readChunk(fileId: String, chunk: Int): ByteArray = snapshot.readChunk(fileId, chunk)
    fun mediaPage(after: Int, ensureNative: () -> Unit = {}): kotlinx.serialization.json.JsonObject =
        NativeGalleryMediaProjection.page(snapshot, snapshot.lease, after, ::readChunk, ensureNative)
    val allowsOfferOutput: Boolean get() = false
    internal fun originalAcceptance(): PhotoSourceRemoteAcceptance { snapshot.manifest; return original }
}
