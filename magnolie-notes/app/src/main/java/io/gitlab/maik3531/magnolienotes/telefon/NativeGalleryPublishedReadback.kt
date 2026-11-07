package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import android.os.Looper
import kotlinx.serialization.json.*
import java.security.SecureRandom
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Explicit private native producer, not a listener/dispatcher or Saved factory.
 * Sending is possible only inside the rows owner's unexported actual-completion
 * permit, after full original readback and native media inspection. */
internal class NativeGalleryPublishedReadback private constructor(internal val owner: NativeGalleryPublishedInspection,
    private val offer: JsonObject, private val channel: TelefonSecureChannel) : AutoCloseable {
    private val origin = owner.selected.body.getValue("origin").jsonObject
    private val nonce = NativeHex.lower(ByteArray(32).also(SecureRandom()::nextBytes))
    private val offerSha256 = DeviceFileControl.digest("magnolie-published-readback-offer-v1\u0000", offer)
    private val started = AtomicBoolean(false)
    private val ended = AtomicBoolean(false)
    private val output = AtomicReference<JsonObject?>()
    internal val grantsWriteAuthority: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false
    init { current() }

    private fun current(): DeviceFileManifest {
        if (ended.get() || Looper.myLooper() == Looper.getMainLooper()) fail()
        owner.requireChannel(channel)
        if (DeviceFileControl.digest("magnolie-published-readback-offer-v1\u0000", offer) != offerSha256) fail()
        val binding = owner.bindingForReadback(origin.string("manifest_sha256"))
        val now = System.currentTimeMillis()
        val manifest = DeviceFileOfferEnvelope.validate(offer, binding.senderId, binding.receiverId, now)
        if (now < offer.long("created_ms") || now >= offer.long("expires_ms")) fail()
        val file = manifest.files.singleOrNull() ?: fail()
        val body = owner.selected.body
        if (manifest.fingerprint != origin.string("manifest_sha256") || manifest.transferId != origin.string("transfer_id") ||
            manifest.sourceId != origin.string("source_id") || file.id != origin.string("file_id") ||
            file.size != body.long("size") || file.sha256 != body.string("sha256")) fail()
        owner.requireCurrent(); return manifest
    }
    internal fun perform(rows: NativeGalleryIncomingRows, cancellation: CancellationSignal = CancellationSignal()): JsonObject =
        rows.recoverPublished(this, cancellation)
    internal fun requireCurrent() { current() }

    internal fun sendVerified(rows: NativeGalleryIncomingRows, selectedOwner: NativeGalleryPublishedInspection,
        observation: NativeIncomingMediaObservation, cancellation: CancellationSignal, verifyRow: () -> Unit) {
        rows.requireVerifiedRead(this, selectedOwner, observation)
        if (selectedOwner !== owner || !started.compareAndSet(false, true)) fail()
        fun check() {
            cancellation.throwIfCanceled(); current(); rows.requireVerifiedRead(this, owner, observation); verifyRow()
        }
        check()
        val manifest = current(); val file = manifest.files.single(); val publication = owner.selected
        if (observation.mediaType != owner.kind || observation.mimeType != publication.body.string("mime_type")) fail()
        val context = buildJsonObject {
            put("format", 1); put("offer_id", offer.string("message_id")); put("manifest_sha256", manifest.fingerprint)
            put("transfer_id", manifest.transferId); put("source_id", manifest.sourceId); put("file_id", file.id)
            put("size", file.size); put("sha256", file.sha256); put("media_type", owner.kind.uriSegment); put("mime_type", observation.mimeType)
            put("publication_sha256", publication.fingerprint)
            put("row_sha256", DeviceFileControl.digest("magnolie-published-row-v1\u0000", publication.row!!))
            put("permission_epoch", owner.bindingForReadback(manifest.fingerprint).permissionEpoch); put("readback_nonce", nonce)
        }
        val binding = owner.bindingForReadback(DevicePublishedReadbackEnvelope.destinationToken(context))
        val body = DevicePublishedReadbackEnvelope.encodeBody(context, binding)
        val now = System.currentTimeMillis(); val remaining = minOf(DeviceFileControl.MAX_TTL_MS, offer.long("expires_ms") - now)
        if (remaining <= 0) fail()
        val message = TelefonNachrichten.message(DevicePublishedReadbackEnvelope.KIND, body, remaining, now)
        DevicePublishedReadbackEnvelope.parse(message, offer, binding, owner.kind, now)
        check(); channel.send(message); check(); output.set(message)
    }
    internal fun actualOutput(): JsonObject? = output.get()
    override fun close() { ended.set(true); owner.close() }
    companion object {
        internal fun capture(owner: NativeGalleryPublishedInspection, offer: JsonObject, channel: TelefonSecureChannel): NativeGalleryPublishedReadback =
            try { NativeGalleryPublishedReadback(owner, offer, channel) } catch (error: Throwable) { owner.close(); throw error }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_published_native_readback_required")
    }
}
