package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Native historical correlation only. Current control, book, local consent
 * and fresh paired ownership must independently authorize each incoming run. */
internal class GalleryIncomingScope private constructor(internal val collectionMode: String,
    associations: Map<String, GalleryKnownPhoneMedia>, pcOrigins: Map<String, GalleryPcMediaOrigin> = emptyMap()) {
    internal val associations: Map<String, GalleryKnownPhoneMedia> = java.util.Collections.unmodifiableMap(associations.toMap())
    internal val pcOrigins: Map<String, GalleryPcMediaOrigin> = java.util.Collections.unmodifiableMap(pcOrigins.toMap())
    internal fun fingerprint(manifest: DeviceFileManifest): String = DeviceFileControl.digest(
        if (pcOrigins.isEmpty()) "magnolie-gallery-incoming-scope-v1\u0000" else "magnolie-gallery-incoming-scope-v2\u0000",
        buildJsonObject {
            put("collection_mode", collectionMode); put("manifest_sha256", manifest.fingerprint)
            put("originals", JsonArray(manifest.files.map { file -> JsonArray(listOf(JsonPrimitive(file.id),
                associations[file.id]?.let { JsonPrimitive(it.id) } ?: JsonNull)) }))
            if (pcOrigins.isNotEmpty()) put("pc_origins", JsonArray(manifest.files.map { file ->
                JsonArray(listOf(JsonPrimitive(file.id), pcOrigins[file.id]?.body ?: JsonNull)) }))
        })
    companion object {
        internal fun capture(manifest: DeviceFileManifest, kind: GalleryMediaType, collectionMode: String,
             peerIdentity: String, references: Map<String, GalleryPhoneMediaReference>,
             known: () -> List<GalleryKnownPhoneMedia>): GalleryIncomingScope = capture(manifest, kind, collectionMode, peerIdentity, references, emptyMap(), known)

        internal fun capture(manifest: DeviceFileManifest, kind: GalleryMediaType, collectionMode: String,
            peerIdentity: String, references: Map<String, GalleryPhoneMediaReference>, pcOrigins: Map<String, GalleryPcMediaOrigin>,
            known: () -> List<GalleryKnownPhoneMedia>): GalleryIncomingScope {
            val ids = manifest.files.map { it.id }.toSet()
            if (collectionMode !in setOf("phone_inventory", "entire_collection") || references.size > DeviceFileManifest.MAX_FILES ||
                references.keys.any { it !in ids } || collectionMode == "phone_inventory" && references.keys != ids)
                fail()
            if (pcOrigins.isNotEmpty() && (collectionMode != "entire_collection" || pcOrigins.keys.any { it !in ids || it in references } ||
                pcOrigins.keys + references.keys != ids || pcOrigins.values.map { it.origin }.distinct().size != pcOrigins.size)) fail()
            if (references.isEmpty()) return GalleryIncomingScope(collectionMode, emptyMap(), pcOrigins)
            // Original pairing belongs to the stored proof, not current rights.
            // Fresh current re-pair consent can correlate SAME phone/PC/key
            // history without turning the old pairing into write authority.
            val candidates = known().filter {
                it.body.string("phone_id") == manifest.receiverId && it.body.string("peer_id") == manifest.senderId &&
                    it.body.string("peer_identity_sha256") == peerIdentity &&
                    it.reference.body.string("media_type") == kind.uriSegment
            }
            val selected = references.mapValues { (_, reference) ->
                val matches = candidates.filter { it.reference.body == reference.body }
                if (matches.isEmpty()) fail()
                // Equivalent confirmations across original pairings are valid
                // history; choose deterministically, never adopt unknown proof.
                matches.minBy { it.id }
            }
            if (selected.values.map { it.reference.body }.distinct().size != selected.size) fail()
            return GalleryIncomingScope(collectionMode, selected, pcOrigins)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_incoming_inventory_reference_required")
    }
}
