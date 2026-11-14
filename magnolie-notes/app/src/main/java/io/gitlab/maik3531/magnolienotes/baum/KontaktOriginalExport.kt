package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.Json

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
