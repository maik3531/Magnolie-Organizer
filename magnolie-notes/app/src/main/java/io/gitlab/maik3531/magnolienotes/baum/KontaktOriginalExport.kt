package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.*

/** Native observed export, not a portable mapping grant or a new wire DTO.
 * Pending transport must carry this content and quote together, then correlate
 * the real desktop save. An export cannot release a provider outcome hold.
 */
internal object KontaktOriginalExport {
    data class Stand(val freigabeId: String, val basisHash: String, val revision: Long,
                     val daten: KontaktDaten)

    private class Beleg(val grant: KontaktOriginalFreigaben.Freigabe,
        val mapping: KontaktOriginalZuordnungen.Zuordnung,
        val continuity: KontaktOriginalZuordnungen.Fortbestand,
        val attempts: KontaktOriginalVersuche, val id: String, val quote: String,
        val revision: Long, val content: String)

    class Angebot internal constructor(private val beleg: Any) {
        /** Dedicated draft only. No capability or production sender is enabled.
         * Content and quote come from the same actual native observed proof.
         */
        fun nachricht(): JsonObject {
            val proof = beleg as? Beleg ?: throw SecurityException("contact_original_native_export_required")
            val current = lesen()
            return buildJsonObject {
                put("art", "kontakt_original_export"); put("fassung", 1)
                put("share_id", current.freigabeId); put("before_basis", current.basisHash)
                put("setup_id", proof.grant.entscheidungId())
                put("native_revision", current.revision)
                put("content_sha256", KontaktSync.hash(current.daten))
                put("kontakt", Json { encodeDefaults = true }.encodeToJsonElement(KontaktDaten.serializer(), current.daten))
            }.also { lesen() }
        }

        fun lesen(): Stand {
            val proof = beleg as? Beleg ?: throw SecurityException("contact_original_native_export_required")
            proof.mapping.pruefen(proof.grant)
            // Decoding our owned immutable snapshot gives callers independent
            // containers, never the provider observation retained by this proof.
            val owned = Json.decodeFromString(KontaktDaten.serializer(), proof.content)
            return proof.attempts.ohneOffenenVersuch(proof.grant) {
                proof.continuity.pruefen(proof.grant)
                Stand(proof.id, proof.quote, proof.revision, owned)
            }
        }
    }

    fun erfassen(grant: KontaktOriginalFreigaben.Freigabe, freigabeId: String,
                 mappings: KontaktOriginalZuordnungen, attempts: KontaktOriginalVersuche): Angebot {
        val mapping = mappings.aktualisieren(grant, freigabeId, attempts)
        val native = grant.bindung.aktuell()
        val content = Json.encodeToString(KontaktDaten.serializer(), native.daten)
        val quote = mapping.basisHash(grant)
        val continuity = mapping.festhalten(grant)
        val offer = Angebot(Beleg(grant, mapping, continuity, attempts, mapping.freigabeId(),
            quote, grant.bindung.revision, content))
        offer.lesen()
        return offer
    }
}
