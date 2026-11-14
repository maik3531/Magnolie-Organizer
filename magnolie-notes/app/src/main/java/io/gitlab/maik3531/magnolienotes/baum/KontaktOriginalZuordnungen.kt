package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import io.gitlab.maik3531.magnolienotes.journal.vorhandenerJournalKey
import kotlinx.serialization.json.*
import java.io.File
import java.security.MessageDigest
import javax.crypto.SecretKey

/** Nonportable exact canonical-share/native-original bindings, NOT source consent.
 * Portable KontaktSpur/baumKontakt values are at most native setup suggestions.
 * Only the exact mappings selected in a live native setup decision may be saved.
 * Existing journal key only: no default-on key generation or read repair.
 */
internal class KontaktOriginalZuordnungen private constructor(root: File, existingKey: () -> SecretKey?) {
    private val files = KontaktOriginalDateien(root)
    private val cipher = DatenDateiKrypto({ existingKey() ?: error("contact_original_journal_key_unavailable") })
    private class Beleg(val store: KontaktOriginalZuordnungen, val key: String, val hash: String, val record: JsonObject)
    private class FolgeBeleg(val original: Beleg, val grant: KontaktOriginalFreigaben.Freigabe)
    /** Mapping-file continuity only, not fresh provider/source permission. This
     * remains checkable after the guarded provider revision has advanced.
     */
    class Fortbestand internal constructor(private val beleg: Any) {
        private fun native(grant: KontaktOriginalFreigaben.Freigabe): FolgeBeleg {
            val native = beleg as? FolgeBeleg ?: throw SecurityException("contact_original_native_mapping_required")
            if (native.grant !== grant) throw SecurityException("contact_original_mapping_retargeted")
            return native
        }
        fun pruefen(grant: KontaktOriginalFreigaben.Freigabe) { native(grant).original.let { it.store.pruefen(it) } }
        internal fun freigabeId(grant: KontaktOriginalFreigaben.Freigabe): String = native(grant).also { pruefen(grant) }.original.record.getValue("share").jsonPrimitive.content
        internal fun hash(grant: KontaktOriginalFreigaben.Freigabe): String = native(grant).also { pruefen(grant) }.original.hash
    }
    class Zuordnung internal constructor(private val beleg: Any) {
        private fun native(): Beleg = (beleg as? Beleg) ?: throw SecurityException("contact_original_native_mapping_required")
        fun freigabeId(): String = native().also { it.store.pruefen(it) }.record.getValue("share").jsonPrimitive.content
        /** Exportable revision quote, not permission. The incoming return must
         * quote this observed baseline; never fill it from current state for a peer.
         */
        fun basisHash(grant: KontaktOriginalFreigaben.Freigabe): String {
            pruefen(grant)
            return native().hash
        }
        internal fun festhalten(grant: KontaktOriginalFreigaben.Freigabe): Fortbestand {
            pruefen(grant)
            return Fortbestand(FolgeBeleg(native(), grant))
        }
        fun pruefen(grant: KontaktOriginalFreigaben.Freigabe) {
            val proof = native()
            grant.pruefen()
            val observed = record(grant.partner(), freigabeId(), grant.bindung, grant.entscheidungId())
            require(observed == proof.record) { "contact_original_mapping_changed" }
            proof.store.pruefen(proof)
            grant.pruefen()
            proof.store.pruefen(proof)
        }
    }

    /** No provider IO or source permission is inferred while reading history. */
    fun finden(peer: KontaktOriginalFreigaben.Partner, freigabeId: String): Zuordnung? =
        findenBeleg(peer, freigabeId)?.let(::Zuordnung)

    private fun findenBeleg(peer: KontaktOriginalFreigaben.Partner, freigabeId: String): Beleg? {
        require(text(peer.kennung) && peer.kennung.isNotBlank() && text(peer.schluessel) && peer.schluessel.isNotBlank())
        require(share(freigabeId))
        val key = slot(peer.kennung, freigabeId)
        return files.mitSperre(create = false) {
            val bytes = files.lesen("$key.bin") ?: return@mitSperre null
            val value = decode(key, bytes)
            require(value["peer"] == peerJson(peer) && value["share"] == JsonPrimitive(freigabeId)) { "contact_original_mapping_peer_changed" }
            Beleg(this, key, hash(bytes), value)
        }
    }

    /** Run as an exact-original setup dependency before source publication. */
    fun speichern(decision: KontaktOriginalFreigaben.Entscheidung): List<Zuordnung> {
        decision.pruefen()
        val selected = decision.zuordnungen()
        if (selected.isEmpty()) return emptyList() // Source-only/empty decision grants no mapping, creates nothing.
        val peer = decision.partner()
        val decisionId = decision.kennung()
        val records = selected.map { original ->
            val value = record(peer, original.freigabeId, original.bindung, decisionId)
            val key = slot(peer.kennung, original.freigabeId)
            val plain = value.toString().toByteArray(Charsets.UTF_8)
            require(plain.size <= 256 * 1024)
            val encrypted = try { cipher.verschluesseln(plain, domain(key)) } finally { plain.fill(0) }
            Triple(key, value, encrypted)
        }
        decision.pruefen()
        val result = requireNotNull(files.mitSperre(create = true) {
            // Preflight all conflicts before the first map is changed. A partial
            // IO failure cannot publish the subsequent owned source permission.
            records.forEach { (key, value, _) ->
                files.lesen("$key.bin")?.let { previous ->
                    require(decode(key, previous)["original"] == value["original"]) { "contact_original_mapping_retargeted" }
                }
            }
            records.map { (key, value, encrypted) ->
                files.schreiben("$key.bin", encrypted)
                val saved = requireNotNull(files.lesen("$key.bin"))
                require(saved.contentEquals(encrypted) && decode(key, saved) == value)
                Zuordnung(Beleg(this, key, hash(saved), value))
            }
        })
        decision.pruefen()
        result.forEach { it.freigabeId() } // Recheck files after the last native context callback.
        return result
    }

    /** Refresh a previously explicitly selected original from a fresh native
     * observation, without another human setup. Never register a missing map,
     * change its source/peer/setup, or advance past an unknown/verified attempt.
     * Actual authenticated export/desktop-save acknowledgement is separate.
     */
    fun aktualisieren(grant: KontaktOriginalFreigaben.Freigabe, freigabeId: String,
                      versuche: KontaktOriginalVersuche): Zuordnung {
        grant.pruefen()
        val peer = grant.partner()
        val proof = findenBeleg(peer, freigabeId)
            ?: throw SecurityException("contact_original_native_mapping_required")
        val observed = record(peer, freigabeId, grant.bindung, grant.entscheidungId())
        require(listOf("original", "peer", "share", "decision_id").all { observed[it] == proof.record[it] }) {
            "contact_original_mapping_retargeted"
        }
        require(observed == proof.record ||
            observed.getValue("revision").jsonPrimitive.long > proof.record.getValue("revision").jsonPrimitive.long) {
            "contact_original_mapping_revision_regressed"
        }
        val plain = observed.toString().toByteArray(Charsets.UTF_8)
        val encrypted = try { cipher.verschluesseln(plain, domain(proof.key)) } finally { plain.fill(0) }
        grant.pruefen()
        val result = versuche.ohneOffenenVersuch(grant) {
            requireNotNull(files.mitSperre(create = false) {
                val bytes = files.lesen("${proof.key}.bin") ?: error("contact_original_mapping_unavailable")
                require(hash(bytes) == proof.hash && decode(proof.key, bytes) == proof.record) {
                    "contact_original_mapping_changed"
                }
                if (observed == proof.record) Zuordnung(proof) // Unchanged exports keep their exact quoted basis.
                else {
                    files.schreiben("${proof.key}.bin", encrypted)
                    val saved = requireNotNull(files.lesen("${proof.key}.bin"))
                    require(saved.contentEquals(encrypted) && decode(proof.key, saved) == observed)
                    Zuordnung(Beleg(this, proof.key, hash(saved), observed))
                }
            })
        }
        result.pruefen(grant)
        return result
    }

    private fun pruefen(proof: Beleg) {
        val valid = files.mitSperre(create = false) {
            val bytes = files.lesen("${proof.key}.bin") ?: return@mitSperre false
            hash(bytes) == proof.hash && decode(proof.key, bytes) == proof.record
        }
        if (proof.store !== this || valid != true) throw SecurityException("contact_original_mapping_unavailable")
    }

    private fun decode(key: String, bytes: ByteArray): JsonObject {
        val plain = cipher.entschluesseln(bytes, domain(key))
        try {
            val value = Json.parseToJsonElement(plain.decodeToString(throwOnInvalidSequence = true)) as? JsonObject
                ?: error("contact_original_mapping_schema")
            require(value.keys == setOf("format", "peer", "share", "original", "lookup", "contact_id", "revision", "before_sha256", "decision_id") && value["format"] == JsonPrimitive(1))
            fun string(obj: JsonObject, name: String, nullable: Boolean = false): String? {
                if (nullable && obj[name] == JsonNull) return null
                return (obj[name] as? JsonPrimitive)?.takeIf { it.isString && text(it.content) }?.content
                    ?: error("contact_original_mapping_text")
            }
            fun number(obj: JsonObject, name: String, zero: Boolean = false): Long {
                val value = (obj[name] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                require(value != null && value >= if (zero) 0 else 1)
                return value
            }
            val peer = value["peer"] as? JsonObject ?: error("contact_original_mapping_peer")
            require(peer.keys == setOf("id", "key"))
            require(!string(peer, "id").isNullOrBlank() && !string(peer, "key").isNullOrBlank())
            val id = requireNotNull(string(value, "share")); require(share(id) && slot(requireNotNull(string(peer, "id")), id) == key)
            val decisionId = requireNotNull(string(value, "decision_id"))
            require(java.util.UUID.fromString(decisionId).toString() == decisionId)
            val original = value["original"] as? JsonObject ?: error("contact_original_mapping_original")
            require(original.keys == setOf("database", "raw_id", "name", "type", "data_set", "source_id"))
            number(original, "database"); number(original, "raw_id")
            listOf("name", "type", "data_set", "source_id").forEach { string(original, it, true) }
            number(value, "contact_id"); number(value, "revision", true)
            require(!string(value, "lookup").isNullOrBlank() && string(value, "before_sha256")?.matches(Regex("[0-9a-f]{64}")) == true)
            require(value.toString().toByteArray(Charsets.UTF_8).contentEquals(plain))
            return value
        } finally { plain.fill(0) }
    }

    companion object {
        private fun text(value: String) = value.length <= 2048 && value.none(Char::isISOControl) && value.codePoints().noneMatch { it in 0xD800..0xDFFF }
        private fun share(value: String) = value.isNotBlank() && value.codePointCount(0, value.length) <= 128 && text(value)
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        private fun slot(peerId: String, share: String) = hash(JsonArray(listOf(JsonPrimitive(peerId), JsonPrimitive(share))).toString().toByteArray(Charsets.UTF_8))
        private fun domain(key: String) = "kontakt-original-zuordnung-v1:$key"
        private fun peerJson(peer: KontaktOriginalFreigaben.Partner) = buildJsonObject { put("id", peer.kennung); put("key", peer.schluessel) }
        private fun record(peer: KontaktOriginalFreigaben.Partner, shareId: String, binding: KontaktOriginalBindung, decisionId: String): JsonObject {
            require(share(shareId) && text(peer.kennung) && peer.kennung.isNotBlank() && text(peer.schluessel) && peer.schluessel.isNotBlank())
            val current = binding.aktuell()
            return buildJsonObject {
                put("format", 1); put("peer", peerJson(peer)); put("share", shareId)
                put("decision_id", decisionId)
                put("original", buildJsonObject {
                    put("database", binding.datenbankErstellt); put("raw_id", binding.rawContactId)
                    fun optional(name: String, value: String?) {
                        require(value == null || text(value))
                        put(name, value?.let(::JsonPrimitive) ?: JsonNull)
                    }
                    optional("name", binding.quelle.kontoName); optional("type", binding.quelle.kontoTyp)
                    optional("data_set", binding.quelle.datenSatz); optional("source_id", binding.sourceId)
                })
                put("lookup", binding.lookupKey); put("contact_id", binding.contactId)
                put("revision", binding.revision); put("before_sha256", KontaktSync.hash(current.daten))
            }
        }
        fun ausBestehendemJournal(context: Context) = KontaktOriginalZuordnungen(File(context.filesDir, "kontakt-original-zuordnungen"), ::vorhandenerJournalKey)
        internal fun fuerTest(root: File, key: () -> SecretKey?) = KontaktOriginalZuordnungen(root, key)
    }
}
