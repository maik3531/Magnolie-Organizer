package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Build
import android.provider.MediaStore
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Locale

/** Actual native observations, never deserialized grants. */
internal data class GalleryAccessObservation(val coverage: GalleryReadCoverage, val accessEpoch: String,
    val mediaStoreVersion: String?, val volumeMounted: Boolean)

internal interface GalleryAccessEnvironment {
    fun observe(volume: String): GalleryAccessObservation
}

/** Epoch is owned by the native permission controller, not a desktop packet.
 * It must rotate on permission/selected-photo access changes and selected-only
 * refresh when resuming the native permission UI. No permission is requested here.
 */
internal class AndroidGalleryAccessEnvironment(context: Context, private val accessEpoch: () -> String) : GalleryAccessEnvironment {
    private val app = context.applicationContext
    override fun observe(volume: String): GalleryAccessObservation {
        val before = accessEpoch()
        require(Regex("[0-9a-f]{64}").matches(before) && Regex("[A-Za-z0-9_-]{1,128}").matches(volume))
        val coverage = AndroidGalleryReadPermissions.observe(app)
        if (coverage == GalleryReadCoverage.NONE) return GalleryAccessObservation(coverage, before, null, false)
        val mounted = if (Build.VERSION.SDK_INT >= 29) volume in MediaStore.getExternalVolumeNames(app) else volume == "external"
        val version = when {
            !mounted -> null
            Build.VERSION.SDK_INT >= 29 -> MediaStore.getVersion(app, volume)
            // Legacy getVersion(context) is only a schema version on old
            // Android, not a reliable rebuilt-volume namespace (AOSP Android8).
            else -> null
        }
        if (before != accessEpoch() || coverage != AndroidGalleryReadPermissions.observe(app))
            throw PhotoFolderScopeError("gallery_access_observation_changed")
        return GalleryAccessObservation(coverage, before, version, mounted)
    }
}

internal class GalleryPhotoSourceLease internal constructor(val album: GalleryAlbumCandidate,
    internal val activation: NativeGalleryRequest, internal val access: GalleryAccessObservation,
    internal val authority: Any, override val sourceKey: String, override val version: String,
    override val readGrantToken: String) : NativePhotoSourceLease {
    override val receiver: NativePhotoReceiver get() = activation.receiver
    override val sourceEpoch: String get() = activation.policyEpoch
    // An album lease is not a completed authoritative file inventory.
    val provesFileDeletion: Boolean get() = false
}

/** Desktop-enabled album scope, separate from SAF trees. No phone settings,
 * MediaStore writes, source crawling or consent inferred from album labels.
 */
internal class GalleryPhotoSourceScope(private val current: () -> NativeGalleryRequest?,
    private val environment: GalleryAccessEnvironment) : NativePhotoSourceAuthority {
    private val authority = Any()
    private val runtimeNamespace = ByteArray(32).also(SecureRandom()::nextBytes).let(::hash)

    /** Metadata freshness only. Unlike capture, this does not claim an explicit
     * desktop album choice and never constructs a source READ lease.
     */
    internal fun isCatalogCurrent(catalog: GalleryAlbumCatalog): Boolean = runCatching {
        val activation = catalog.activation ?: return false
        if (!same(activation, current()) || catalog.albums.any { it.kind !in activation.kinds }) return false
        for (volume in catalog.albums.map { it.volume }.distinct()) {
            val observed = environment.observe(volume)
            validate(observed)
            if (!observed.volumeMounted || observed.coverage == GalleryReadCoverage.NONE || observed.coverage != catalog.coverage ||
                catalog.accessEpoch?.let { it != observed.accessEpoch } == true) return false
        }
        same(activation, current())
    }.getOrDefault(false)

    fun capture(catalog: GalleryAlbumCatalog, album: GalleryAlbumCandidate, desktopAlbumChoice: Boolean = false): GalleryPhotoSourceLease {
        val activation = catalog.activation ?: fail("gallery_source_not_activated")
        if (!catalog.albums.any { it === album } || album.kind !in activation.kinds ||
            !same(activation, current()) || album.needsAlbumChoice && !desktopAlbumChoice)
            fail("gallery_source_choice_not_current")
        if (!Regex("[A-Za-z0-9_-]{1,128}").matches(album.volume) || !Regex("[A-Za-z0-9_-]{1,128}").matches(album.bucketId))
            fail("gallery_source_invalid_album")
        val observed = environment.observe(album.volume)
        validate(observed)
        if (!observed.volumeMounted || observed.coverage == GalleryReadCoverage.NONE || observed.coverage != catalog.coverage ||
            catalog.accessEpoch?.let { it != observed.accessEpoch } == true)
            fail("gallery_source_visibility_changed")
        val sourceKey = "gallery-album-v1:" + digest(mapOf("kind" to album.kind.name, "volume" to album.volume,
            "bucket" to album.bucketId, "path" to (album.relativePath?.lowercase(Locale.ROOT) ?: "")))
        val stamp = stamp(observed)
        val version = digest(mapOf("source" to sourceKey, "policy" to activation.policyEpoch, "access" to stamp,
            "kinds" to activation.kinds.sortedBy { it.ordinal }.joinToString(",") { it.name }))
        val lease = GalleryPhotoSourceLease(album, activation, observed, authority, sourceKey, version, stamp)
        if (!isCurrent(lease)) fail("gallery_source_choice_not_current")
        return lease
    }

    override fun isCurrent(lease: NativePhotoSourceLease): Boolean {
        if (lease !is GalleryPhotoSourceLease || lease.authority !== authority) return false
        return runCatching {
            if (!same(lease.activation, current())) return false
            val observed = environment.observe(lease.album.volume)
            validate(observed)
            observed.volumeMounted && observed == lease.access && observed.coverage != GalleryReadCoverage.NONE &&
                stamp(observed) == lease.readGrantToken && same(lease.activation, current())
        }.getOrDefault(false)
    }
    private fun same(first: NativeGalleryRequest, second: NativeGalleryRequest?): Boolean = second != null &&
        first.receiver.allowed && second.receiver.allowed && first.policyEpoch == second.policyEpoch && first.kinds == second.kinds &&
        first.receiver.owner === second.receiver.owner && first.receiver.peerId == second.receiver.peerId &&
        first.receiver.identitySha256 == second.receiver.identitySha256 && first.receiver.permissionEpoch == second.receiver.permissionEpoch &&
        first.receiver.pairingEpoch == second.receiver.pairingEpoch

    private fun stamp(observation: GalleryAccessObservation): String = digest(mapOf(
        "coverage" to observation.coverage.name, "access_epoch" to observation.accessEpoch,
        "media_namespace" to (observation.mediaStoreVersion ?: "unknown"),
        // No reliable persistent namespace on legacy Android, or stable complete
        // visibility with selected-only access: do not resume old runtime proofs.
        "runtime" to if (observation.mediaStoreVersion == null || observation.coverage == GalleryReadCoverage.SELECTED_ONLY) runtimeNamespace else ""))

    private fun validate(observation: GalleryAccessObservation) {
        if (!Regex("[0-9a-f]{64}").matches(observation.accessEpoch) || observation.mediaStoreVersion?.let {
                it.length !in 1..1024 || it.any { character -> character.code < 32 || character.code == 127 } } == true)
            fail("gallery_source_invalid_access_observation")
    }
    companion object {
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun digest(fields: Map<String, String>) = hash(TelefonKanonisch.bytes(JsonObject(fields.mapValues { JsonPrimitive(it.value) })))
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
