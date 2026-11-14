package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import io.gitlab.maik3531.magnolienotes.journal.KontaktOriginalSicherungen
import io.gitlab.maik3531.magnolienotes.journal.vorhandenerJournalKey
import kotlinx.serialization.json.*
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import javax.crypto.SecretKey

/** Durable per-original unknown holds and native verified receipts. A loaded
 * record never authorizes apply: only fresh reservation returns a one-use token.
 * A verified pinned before-image and exact native readback precede receipt save.
 * Desktop baseline ACK and actual transport/setup integration remain separate.
 * Outcome history uses the existing journal key, NEVER the revocable consent key.
 */
internal class KontaktOriginalVersuche private constructor(root: File, existingJournalKey: () -> SecretKey?,
                                                          stage: (String) -> Unit = {}) {
    private val files = KontaktOriginalDateien(root, stage = stage)
    private val cipher = DatenDateiKrypto({ existingJournalKey() ?: error("contact_original_journal_key_unavailable") })
    private class Beleg(val store: KontaktOriginalVersuche, val key: String, val hash: String, val record: JsonObject)
    private class AusgangsBeleg(val result: Beleg, val grant: KontaktOriginalFreigaben.Freigabe,
                               val mapping: KontaktOriginalZuordnungen.Zuordnung)
    /** Native outgoing result data only, not a negotiated wire frame or ACK.
     * Every read rechecks actual consent, native result and private continuity.
     */
    class Ausgang internal constructor(private val beleg: Any) {
        fun lesen(): JsonObject {
            val proof = beleg as? AusgangsBeleg ?: throw SecurityException("contact_original_native_result_required")
            return proof.result.store.ergebnis(proof)
        }
    }
    private class AnwendeBeleg(val store: KontaktOriginalVersuche, val key: String,
        val grant: KontaktOriginalFreigaben.Freigabe, val hold: Offen,
        val protection: KontaktOriginalSicherungen.Sicherung, val targetHash: String, val target: KontaktDaten,
        val mapping: KontaktOriginalZuordnungen.Fortbestand) {
        var consumed = false
    }
    /** Only a freshly persisted reservation mints this one-use in-process token.
     * Loading an unknown outcome NEVER returns one. Native readback and durable
     * verification are required before returning; desktop baseline SaveACK is separate.
     */
    class Vorbereitet internal constructor(private val beleg: Any) {
        fun anwenden(ziel: KontaktDaten, lifetime: () -> Unit): Verifiziert {
            val native = beleg as? AnwendeBeleg ?: throw SecurityException("contact_original_fresh_attempt_required")
            synchronized(native) {
                check(!native.consumed) { "contact_original_attempt_consumed" }
                native.consumed = true
            }
            val json = Json
            val owned = json.decodeFromString(KontaktDaten.serializer(), json.encodeToString(KontaktDaten.serializer(), ziel))
            require(owned == native.target && KontaktSync.hash(owned) == native.targetHash) { "contact_original_attempt_target_changed" }
            native.grant.pruefen()
            fun protected() {
                native.mapping.pruefen(native.grant)
                native.hold.pruefen()
                native.protection.pruefen(native.grant.bindung)
            }
            protected()
            val result = KontaktOriginalInhalt(native.grant).uebernehmen(owned, {
                protected(); lifetime(); protected()
            }, { protected() })
            native.grant.pruefenNachSchreiben()
            require(native.grant.bindung.ruecklesenNachSchreiben() == result) { "contact_original_receipt_readback_changed" }
            val saved = native.store.bestaetigen(native, result)
            native.grant.pruefenNachSchreiben(); saved.pruefen()
            return saved
        }
    }
    class Offen internal constructor(private val beleg: Any) {
        private fun native(): Beleg = (beleg as? Beleg) ?: throw SecurityException("contact_original_native_attempt_required")
        fun pruefen() { native().let { it.store.pruefen(it) } }
        fun anfrageId(): String = native().also { pruefen() }.record.getValue("request_id").jsonPrimitive.content
        fun anfrageHash(): String = native().also { pruefen() }.record.getValue("request_sha256").jsonPrimitive.content
        fun zielHash(): String = native().also { pruefen() }.record.getValue("target_sha256").jsonPrimitive.content
        fun freigabeId(): String? = native().also { pruefen() }.record["share_id"]?.jsonPrimitive?.contentOrNull
        fun basisHash(): String? = native().also { pruefen() }.record["mapping_sha256"]?.jsonPrimitive?.contentOrNull
        fun folgebasisHash(): String? = native().also { pruefen() }.record["next_mapping"]?.jsonObject?.get("next_basis")?.jsonPrimitive?.content
        fun bestaetigung(): Verifiziert? = native().also { pruefen() }.let {
            if (it.record["state"] == JsonPrimitive("verified")) Verifiziert(it) else null
        }
        internal fun passt(owner: KontaktOriginalVersuche, key: String, blob: ByteArray): Boolean = native().let {
            it.store === owner && it.key == key && it.hash == hash(blob)
        }
    }
    /** Native provider verification durably saved, NOT desktop baseline SaveACK. */
    class Verifiziert internal constructor(private val beleg: Any) {
        private fun native(): Beleg = (beleg as? Beleg)?.takeIf { it.record["state"] == JsonPrimitive("verified") }
            ?: throw SecurityException("contact_original_verified_receipt_required")
        fun pruefen() { native().let { it.store.pruefen(it) } }
        fun anfrageId(): String = native().also { pruefen() }.record.getValue("request_id").jsonPrimitive.content
        fun zielHash(): String = native().also { pruefen() }.record.getValue("target_sha256").jsonPrimitive.content
        fun freigabeId(): String? = native().also { pruefen() }.record["share_id"]?.jsonPrimitive?.contentOrNull
        fun basisHash(): String? = native().also { pruefen() }.record["mapping_sha256"]?.jsonPrimitive?.contentOrNull
        fun folgebasisHash(): String? = native().also { pruefen() }.record["next_mapping"]?.jsonObject?.get("next_basis")?.jsonPrimitive?.content
        fun ausgang(grant: KontaktOriginalFreigaben.Freigabe, mapping: KontaktOriginalZuordnungen.Zuordnung): Ausgang =
            Ausgang(AusgangsBeleg(native(), grant, mapping)).also { it.lesen() }
        fun desktopHash(): String? = native().also { pruefen() }.record["desktop_saved_sha256"]?.jsonPrimitive?.content

        /** Only the authenticated native receive controller calls this phase.
         * It durably records desktop SaveACK correlation, but does NOT install
         * the next map, archive history or release the physical attempt slot.
         */
        internal fun bestaetigenDesktop(grant: KontaktOriginalFreigaben.Freigabe,
            mapping: KontaktOriginalZuordnungen.Zuordnung, body: JsonObject, lifetime: () -> Unit): Verifiziert =
            native().let { it.store.desktopBestaetigen(AusgangsBeleg(it, grant, mapping), body, lifetime) }
    }

    private fun ergebnis(proof: AusgangsBeleg): JsonObject {
        val record = proof.result.record
        require(record["state"] == JsonPrimitive("verified") && record["next_mapping"] is JsonObject) {
            "contact_original_complete_verified_result_required"
        }
        val exactHash = record["target_exact_sha256"]?.jsonPrimitive?.contentOrNull
        require(exactHash != null && digest(exactHash)) { "contact_original_exact_verified_result_required" }
        proof.grant.pruefen()
        require(record["original"] == identitaet(proof.grant)) { "contact_original_result_identity_changed" }
        val shareId = record.getValue("share_id").jsonPrimitive.content
        val beforeBasis = record.getValue("mapping_sha256").jsonPrimitive.content
        proof.mapping.pruefeErgebniskontext(proof.grant, shareId, beforeBasis)
        val receipt = record.getValue("receipt").jsonObject
        val native = proof.grant.bindung.aktuell()
        require(receipt["revision"] == JsonPrimitive(proof.grant.bindung.revision) &&
            receipt["lookup"] == JsonPrimitive(native.lookupKey) && receipt["contact_id"] == JsonPrimitive(native.contactId) &&
            record["target_sha256"] == JsonPrimitive(KontaktSync.hash(native.daten)) && exactTargetHash(native.daten) == exactHash) {
            "contact_original_result_native_frame_changed"
        }
        pruefen(proof.result)
        proof.mapping.pruefeErgebniskontext(proof.grant, shareId, beforeBasis)
        pruefen(proof.result)
        return buildJsonObject {
            put("request_id", record.getValue("request_id")); put("request_sha256", record.getValue("request_sha256"))
            put("share_id", shareId); put("before_basis", beforeBasis); put("target_sha256", record.getValue("target_sha256"))
            put("receipt_id", receipt.getValue("id")); put("native_revision", receipt.getValue("revision"))
            put("next_basis", record.getValue("next_mapping").jsonObject.getValue("next_basis"))
        }
    }

    private fun desktopBestaetigen(proof: AusgangsBeleg, body: JsonObject, lifetime: () -> Unit): Verifiziert {
        lifetime()
        val result = ergebnis(proof)
        require(body.keys == result.keys + setOf("art", "fassung", "desktop_sha256") &&
            body["art"] == JsonPrimitive("kontakt_original_saveack") && body["fassung"] == JsonPrimitive(1) &&
            result.all { (key, value) -> body[key] == value }) { "contact_original_saveack_correlation_changed" }
        val desktop = (body["desktop_sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        require(desktop != null && digest(desktop)) { "contact_original_desktop_save_hash_required" }
        val previous = proof.result.record["desktop_saved_sha256"]
        require(previous == null || previous == JsonPrimitive(desktop)) { "contact_original_desktop_save_already_held" }
        lifetime(); ergebnis(proof)
        if (previous != null) return Verifiziert(proof.result)
        val record = JsonObject(proof.result.record + ("desktop_saved_sha256" to JsonPrimitive(desktop)))
        val clear = record.toString().toByteArray(Charsets.UTF_8)
        val encrypted = try { cipher.verschluesseln(clear, domain(proof.result.key)) } finally { clear.fill(0) }
        val saved = requireNotNull(files.mitSperre(create = false) {
            val current = requireNotNull(files.lesen("${proof.result.key}.bin"))
            require(hash(current) == proof.result.hash && decode(proof.result.key, current) == proof.result.record) {
                "contact_original_attempt_changed"
            }
            files.schreiben("${proof.result.key}.bin", encrypted)
            val written = requireNotNull(files.lesen("${proof.result.key}.bin"))
            require(written.contentEquals(encrypted) && decode(proof.result.key, written) == record)
            Beleg(this, proof.result.key, hash(written), record)
        })
        lifetime(); ergebnis(AusgangsBeleg(saved, proof.grant, proof.mapping))
        return Verifiziert(saved)
    }

    fun laden(grant: KontaktOriginalFreigaben.Freigabe): Offen? {
        grant.pruefen()
        val identity = identitaet(grant)
        val key = originalPlatz(identity)
        val result = files.mitSperre(create = false) {
            val blob = files.lesen("$key.bin") ?: return@mitSperre null
            val record = decode(key, blob)
            require(record["original"] == identity) { "contact_original_attempt_identity_changed" }
            Offen(Beleg(this, key, hash(blob), record))
        }
        grant.pruefen()
        return result
    }

    /** Controller admission: reject invalid scope/ambiguous native operations or
     * oversized Binder parcels BEFORE creating protection and persistent holds.
     * The ordinary apply path still repeats the native plan and atomic assertions.
     */
    fun vorbereitenGeplant(grant: KontaktOriginalFreigaben.Freigabe, mapping: KontaktOriginalZuordnungen.Zuordnung,
                          expectedBasis: String, requestId: String, requestHash: String, ziel: KontaktDaten,
                          sichern: () -> KontaktOriginalSicherungen.Sicherung): Vorbereitet {
        require(uuid(requestId) && digest(requestHash) && digest(expectedBasis))
        val owned = Json.decodeFromString(KontaktDaten.serializer(), Json.encodeToString(KontaktDaten.serializer(), ziel))
        grant.pruefen()
        require(mapping.basisHash(grant) == expectedBasis) { "contact_original_expected_baseline_changed" }
        check(laden(grant) == null) { "contact_original_attempt_held" }
        KontaktOriginalInhalt(grant).pruefePlan(owned)
        val protection = sichern()
        return vorbereiten(grant, mapping, expectedBasis, requestId, requestHash, owned, protection)
    }

    fun vorbereiten(grant: KontaktOriginalFreigaben.Freigabe, mapping: KontaktOriginalZuordnungen.Zuordnung,
                    expectedBasis: String, requestId: String, requestHash: String,
                    ziel: KontaktDaten, sicherung: KontaktOriginalSicherungen.Sicherung): Vorbereitet {
        // A semantic/legacy contact fingerprint is not an exact target witness.
        // Every fresh apply token owns the full admitted model, even when native
        // callers already captured protection. There is no hash-only overload.
        val owned = Json.decodeFromString(KontaktDaten.serializer(), Json.encodeToString(KontaktDaten.serializer(), ziel))
        val targetHash = KontaktSync.hash(owned)
        grant.pruefen()
        check(laden(grant) == null) { "contact_original_attempt_held" }
        val pinnedMapping = mapping.festhalten(grant)
        require(digest(expectedBasis) && pinnedMapping.hash(grant) == expectedBasis) { "contact_original_expected_baseline_changed" }
        KontaktOriginalInhalt(grant).pruefePlan(owned)
        val held = vormerken(grant, requestId, requestHash, targetHash, sicherung, pinnedMapping, owned)
        grant.pruefen(); held.pruefen(); sicherung.pruefen(grant.bindung)
        pinnedMapping.pruefen(grant)
        return Vorbereitet(AnwendeBeleg(this, originalPlatz(identitaet(grant)), grant, held, sicherung, targetHash, owned, pinnedMapping))
    }

    private fun bestaetigen(native: AnwendeBeleg, result: AndroidKontakt): Verifiziert {
        native.hold.pruefen(); native.protection.pruefen(native.grant.bindung)
        native.mapping.pruefen(native.grant)
        val shareId = native.mapping.freigabeId(native.grant)
        val mappingHash = native.mapping.hash(native.grant)
        val nextMapping = native.mapping.naechste(native.grant, result).manifest()
        require(KontaktSync.hash(result.daten) == native.targetHash)
        val saved = requireNotNull(files.mitSperre(create = false) {
            val blob = requireNotNull(files.lesen("${native.key}.bin"))
            require(native.store === this && native.hold.passt(this, native.key, blob)) { "contact_original_attempt_changed" }
            val held = decode(native.key, blob)
            require(held["state"] == JsonPrimitive("held"))
            require(held["share_id"] == JsonPrimitive(shareId) && held["mapping_sha256"] == JsonPrimitive(mappingHash))
            require(held["target_exact_sha256"] == JsonPrimitive(exactTargetHash(native.target)))
            val beforeRevision = held.getValue("before_revision").jsonPrimitive.long
            val revision = result.rawVersionen.getValue(native.grant.bindung.rawContactId)
            require(revision > beforeRevision) { "contact_original_receipt_revision_required" }
            val receipt = JsonObject(held + mapOf("state" to JsonPrimitive("verified"), "next_mapping" to nextMapping, "receipt" to buildJsonObject {
                put("id", UUID.randomUUID().toString()); put("revision", revision)
                put("lookup", result.lookupKey); put("contact_id", result.contactId)
                put("content_sha256", native.targetHash)
            }))
            val clear = receipt.toString().toByteArray(Charsets.UTF_8)
            val encrypted = try { cipher.verschluesseln(clear, domain(native.key)) } finally { clear.fill(0) }
            files.schreiben("${native.key}.bin", encrypted)
            val written = requireNotNull(files.lesen("${native.key}.bin"))
            require(written.contentEquals(encrypted) && decode(native.key, written) == receipt)
            Verifiziert(Beleg(this, native.key, hash(written), receipt))
        })
        return saved
    }

    fun vormerken(grant: KontaktOriginalFreigaben.Freigabe, requestId: String, requestHash: String,
                  targetHash: String, sicherung: KontaktOriginalSicherungen.Sicherung,
                  mapping: KontaktOriginalZuordnungen.Fortbestand? = null, exactTarget: KontaktDaten? = null): Offen {
        grant.pruefen()
        require(uuid(requestId) && digest(requestHash) && digest(targetHash))
        require(exactTarget == null || KontaktSync.hash(exactTarget) == targetHash)
        mapping?.pruefen(grant)
        sicherung.pruefen(grant.bindung)
        val protection = sicherung.manifest(grant.bindung)
        require(protection.type == "magnolie-snapshot" && protection.version == 1 && protection.platform == "android" &&
            protection.domain == "android-system-contacts" && protection.reason == "contact-original-return" &&
            protection.pinned && protection.mutationId == requestId && uuid(protection.uuid) &&
            digest(protection.payload.hash) && protection.payload.schema == 1 && protection.payload.size > 0) {
            "contact_original_pinned_protection_reference_required"
        }
        val identity = identitaet(grant)
        val key = originalPlatz(identity)
        val current = grant.bindung.aktuell()
        val record = buildJsonObject {
            put("format", 1); put("state", "held"); put("attempt_id", UUID.randomUUID().toString())
            put("request_id", requestId); put("request_sha256", requestHash); put("target_sha256", targetHash)
            put("target_exact_sha256", exactTarget?.let { JsonPrimitive(exactTargetHash(it)) } ?: JsonNull)
            put("share_id", mapping?.freigabeId(grant)?.let(::JsonPrimitive) ?: JsonNull)
            put("mapping_sha256", mapping?.hash(grant)?.let(::JsonPrimitive) ?: JsonNull)
            put("original", identity); put("before_revision", grant.bindung.revision)
            put("before_sha256", KontaktSync.hash(current.daten))
            put("lookup", grant.bindung.lookupKey); put("contact_id", grant.bindung.contactId)
            put("protection", buildJsonObject { put("id", protection.uuid); put("sha256", protection.payload.hash) })
        }
        val clear = record.toString().toByteArray(Charsets.UTF_8)
        require(clear.size <= 256 * 1024)
        val blob = try { cipher.verschluesseln(clear, domain(key)) } finally { clear.fill(0) }
        grant.pruefen(); sicherung.pruefen(grant.bindung); mapping?.pruefen(grant)
        val result = requireNotNull(files.mitSperre(create = true) {
            // A new request ID cannot bypass an old unknown attempt on this original.
            check(files.lesen("$key.bin") == null) { "contact_original_attempt_held" }
            files.schreiben("$key.bin", blob)
            val saved = requireNotNull(files.lesen("$key.bin"))
            require(saved.contentEquals(blob) && decode(key, saved) == record)
            Offen(Beleg(this, key, hash(saved), record))
        })
        grant.pruefen(); sicherung.pruefen(grant.bindung); mapping?.pruefen(grant)
        return result
    }

    /** Serialize a native baseline refresh against reservations on the physical
     * original, including holds from another peer/source identity. No provider
     * or source-consent callbacks may run inside this private file lock.
     */
    internal fun <T> ohneOffenenVersuch(grant: KontaktOriginalFreigaben.Freigabe, refresh: () -> T): T {
        grant.pruefen()
        val key = originalPlatz(identitaet(grant))
        return requireNotNull(files.mitSperre(create = true) {
            check(files.lesen("$key.bin") == null) { "contact_original_attempt_held" }
            refresh()
        })
    }

    private fun identitaet(grant: KontaktOriginalFreigaben.Freigabe): JsonObject {
        val peer = grant.partner(); val binding = grant.bindung
        return buildJsonObject {
            put("peer", peer.kennung); put("peer_key", peer.schluessel)
            put("database", binding.datenbankErstellt); put("raw_id", binding.rawContactId)
            put("source_id", binding.sourceId?.let(::JsonPrimitive) ?: JsonNull)
            put("name", binding.quelle.kontoName?.let(::JsonPrimitive) ?: JsonNull)
            put("type", binding.quelle.kontoTyp?.let(::JsonPrimitive) ?: JsonNull)
            put("data_set", binding.quelle.datenSatz?.let(::JsonPrimitive) ?: JsonNull)
        }
    }

    private fun pruefen(beleg: Beleg) {
        val matches = files.mitSperre(create = false) {
            val blob = files.lesen("${beleg.key}.bin") ?: return@mitSperre false
            hash(blob) == beleg.hash && decode(beleg.key, blob) == beleg.record
        }
        if (beleg.store !== this || matches != true) throw SecurityException("contact_original_attempt_changed")
    }

    private fun decode(key: String, blob: ByteArray): JsonObject {
        val clear = cipher.entschluesseln(blob, domain(key))
        try {
            val value = Json.parseToJsonElement(clear.decodeToString(throwOnInvalidSequence = true)) as? JsonObject ?: error("contact_original_attempt_schema")
            val verified = value["state"] == JsonPrimitive("verified")
            val hasMapping = "share_id" in value || "mapping_sha256" in value
            val hasNextMapping = "next_mapping" in value
            val hasExactTarget = "target_exact_sha256" in value
            val hasDesktopSave = "desktop_saved_sha256" in value
            require(value.keys == setOf("format", "state", "attempt_id", "request_id", "request_sha256", "target_sha256",
                "original", "before_revision", "before_sha256", "lookup", "contact_id", "protection") +
                (if (verified) setOf("receipt") else emptySet()) +
                (if (hasNextMapping && verified) setOf("next_mapping") else emptySet()) +
                (if (hasExactTarget) setOf("target_exact_sha256") else emptySet()) +
                (if (hasDesktopSave && verified) setOf("desktop_saved_sha256") else emptySet()) +
                (if (hasMapping) setOf("share_id", "mapping_sha256") else emptySet()) &&
                value["format"] == JsonPrimitive(1) && (verified || value["state"] == JsonPrimitive("held")))
            fun text(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("contact_original_attempt_text")
            require(uuid(text("attempt_id")) && uuid(text("request_id")) && listOf("request_sha256", "target_sha256", "before_sha256").all { digest(text(it)) })
            if (hasExactTarget && value["target_exact_sha256"] != JsonNull) {
                val exact = value["target_exact_sha256"] as? JsonPrimitive
                require(exact?.isString == true && digest(exact.content)) { "contact_original_exact_target_schema" }
            }
            if (hasDesktopSave) require(verified && hasExactTarget && value["target_exact_sha256"] != JsonNull &&
                hasNextMapping && digest(text("desktop_saved_sha256")))
            if (hasMapping && value["share_id"] != JsonNull) {
                require(text("share_id").isNotBlank() && text("share_id").codePointCount(0, text("share_id").length) <= 128 && text("share_id").none(Char::isISOControl) &&
                    text("share_id").codePoints().noneMatch { it in 0xD800..0xDFFF } && digest(text("mapping_sha256")))
            } else if (hasMapping) require(value["mapping_sha256"] == JsonNull)
            val original = value["original"] as? JsonObject ?: error("contact_original_attempt_original")
            require(original.keys == setOf("peer", "peer_key", "database", "raw_id", "source_id", "name", "type", "data_set"))
            require(originalPlatz(original) == key)
            fun positive(obj: JsonObject, field: String, zero: Boolean = false) {
                val number = (obj[field] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                require(number != null && number >= if (zero) 0 else 1)
            }
            positive(original, "database"); positive(original, "raw_id")
            positive(value, "before_revision", true); positive(value, "contact_id")
            require(text("lookup").isNotBlank())
            val protection = value["protection"] as? JsonObject ?: error("contact_original_attempt_protection")
            require(protection.keys == setOf("id", "sha256") &&
                (protection["id"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.let(::uuid) == true &&
                (protection["sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.let(::digest) == true)
            if (verified) {
                if (hasNextMapping) {
                    val pending = value["next_mapping"] as? JsonObject ?: error("contact_original_next_mapping_schema")
                    require(pending.keys == setOf("before_basis", "next_basis", "ciphertext") &&
                        pending["before_basis"] == value["mapping_sha256"])
                    fun pendingText(name: String) = (pending[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
                        ?: error("contact_original_next_mapping_text")
                    require(hasMapping && value["share_id"] != JsonNull && digest(pendingText("before_basis")) &&
                        digest(pendingText("next_basis")) && pending["next_basis"] != pending["before_basis"])
                    require(pendingText("ciphertext").length <= 350_000)
                    val encrypted = requireNotNull(Krypto.b64Roh(pendingText("ciphertext")))
                    require(encrypted.size in 1..256 * 1024 && hash(encrypted) == pendingText("next_basis") &&
                        Krypto.b64(encrypted) == pendingText("ciphertext"))
                }
                val receipt = value["receipt"] as? JsonObject ?: error("contact_original_receipt_schema")
                require(receipt.keys == setOf("id", "revision", "lookup", "contact_id", "content_sha256"))
                require((receipt["id"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.let(::uuid) == true)
                positive(receipt, "revision"); positive(receipt, "contact_id")
                require(receipt.getValue("revision").jsonPrimitive.long > value.getValue("before_revision").jsonPrimitive.long &&
                    receipt["content_sha256"] == value["target_sha256"] && receipt["contact_id"] == value["contact_id"] &&
                    (receipt["lookup"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.isNotBlank() == true)
            }
            require(value.toString().toByteArray(Charsets.UTF_8).contentEquals(clear))
            return value
        } finally { clear.fill(0) }
    }

    companion object {
        // Ownership/peer changes require clarification, not another empty slot
        // for a still-unknown write against the same physical native original.
        private fun originalPlatz(identity: JsonObject): String = hash(buildJsonObject {
            put("database", identity.getValue("database"))
            put("raw_id", identity.getValue("raw_id"))
        }.toString().toByteArray(Charsets.UTF_8))
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        private fun exactTargetHash(target: KontaktDaten) = hash(Json.encodeToString(KontaktDaten.serializer(), target).toByteArray(Charsets.UTF_8))
        private fun digest(value: String) = value.matches(Regex("[0-9a-f]{64}"))
        private fun uuid(value: String) = runCatching { UUID.fromString(value).let { it.toString() == value && it.version() == 4 } }.getOrDefault(false)
        private fun domain(key: String) = "kontakt-original-versuch-v1:$key"
        fun ausBestehendemJournal(context: Context) = KontaktOriginalVersuche(File(context.filesDir, "kontakt-original-versuche"), ::vorhandenerJournalKey)
        internal fun fuerTest(root: File, stage: (String) -> Unit = {}, key: () -> SecretKey?) = KontaktOriginalVersuche(root, key, stage)
    }
}
