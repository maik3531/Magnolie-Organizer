package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.journal.KontaktOriginalSicherungen
import kotlinx.serialization.json.*
import java.util.UUID

/** Full-return receive controller. Production dispatch remains disabled until
 * negotiated desktop sending/restoration and genuine native setup are connected.
 * Connection policy is a native callback, never a field supplied by the peer.
 */
internal class KontaktOriginalEmpfang(
    private val context: Context,
    private val handlung: Server.Handlung,
    private val consent: KontaktOriginalDauerfreigaben,
    private val mappings: KontaktOriginalZuordnungen,
    private val attempts: KontaktOriginalVersuche,
    private val protection: () -> KontaktOriginalSicherungen,
    private val verbindungFreigegeben: () -> Boolean
) {
    /** Protocol support only; no source grant, book/provider access or SaveACK. */
    fun aushandeln(origin: Server.FsEmpfang, body: JsonObject, transportId: String): JsonObject =
        synchronized(Ablage.SCHREIBSPERRE) {
            val peerId = origin.partnerKennung()
            fun lifetime() {
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
                val peer = handlung.partner(peerId)
                require(handlung.istAn() && peer?.bestaetigt == true && peer.vertraut && peer.kontaktSync &&
                    verbindungFreigegeben()) { "contact_original_receive_not_available" }
            }
            lifetime()
            val challenge = (body["challenge"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            require(body.keys == setOf("art", "fassung", "challenge", "antwort", "profil") &&
                body["art"] == JsonPrimitive(AUSHANDLUNG) && body["fassung"] == JsonPrimitive(1) &&
                body["antwort"] == JsonPrimitive(false) && body["profil"] == JsonPrimitive(PROFIL) &&
                challenge != null && runCatching { UUID.fromString(challenge).toString() == challenge }.getOrDefault(false)) {
                "contact_original_protocol_offer_schema"
            }
            JsonObject(body + ("antwort" to JsonPrimitive(true))).also { lifetime() }
        }

    fun bestaetigen(origin: Server.FsEmpfang, body: JsonObject, transportId: String) =
        synchronized(Ablage.SCHREIBSPERRE) {
            val peerId = origin.partnerKennung()
            fun lifetime() {
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
                val remote = handlung.partner(peerId)
                require(handlung.istAn() && remote?.bestaetigt == true && remote.vertraut && remote.kontaktSync &&
                    verbindungFreigegeben()) { "contact_original_receive_not_available" }
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
            }
            lifetime()
            require(body.keys == setOf("art", "fassung", "request_id", "request_sha256", "share_id", "before_basis",
                "target_sha256", "receipt_id", "native_revision", "next_basis", "desktop_sha256") &&
                body["art"] == JsonPrimitive(BESTAETIGUNG) && body["fassung"] == JsonPrimitive(1)) {
                "contact_original_saveack_schema"
            }
            val share = (body["share_id"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            require(share != null && share.isNotBlank() && share.codePointCount(0, share.length) <= 128 &&
                share.none(Char::isISOControl) && share.codePoints().noneMatch { it in 0xD800..0xDFFF })
            val peer = KontaktOriginalFreigaben.Partner(peerId, origin.partnerSchluessel())
            val scope = KontaktOriginalFreigaben(consent) {
                lifetime()
                handlung.partner(peerId)?.takeIf { it.bestaetigt && it.vertraut && it.kontaktSync }?.let {
                    KontaktOriginalFreigaben.Partner(it.kennung, it.oeffentlich)
                }
            }
            val stored = consent.laden() ?: throw SecurityException("contact_original_source_not_granted")
            require(scope.wiederherstellen(stored)) { "contact_original_source_not_granted" }
            lifetime()
            val binding = mappings.beobachten(context, peer, share)
                ?: throw SecurityException("contact_original_native_mapping_required")
            val grant = scope.freigabe(binding)
            attempts.abschliessen(grant, mappings, body) { lifetime() }
            lifetime()
        }

    fun empfangen(origin: Server.FsEmpfang, body: JsonObject, transportId: String): JsonObject =
        synchronized(Ablage.SCHREIBSPERRE) {
            val peerId = origin.partnerKennung()
            fun lifetime() {
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
                val peer = handlung.partner(peerId)
                require(handlung.istAn() && peer?.bestaetigt == true && peer.vertraut && peer.kontaktSync &&
                    verbindungFreigegeben()) { "contact_original_receive_not_available" }
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
            }
            lifetime()
            val request = anfrage(body)
            val peer = KontaktOriginalFreigaben.Partner(peerId, origin.partnerSchluessel())
            val scope = KontaktOriginalFreigaben(consent) {
                lifetime()
                val current = handlung.partner(peerId)
                current?.takeIf { it.bestaetigt && it.vertraut && it.kontaktSync }?.let {
                    KontaktOriginalFreigaben.Partner(it.kennung, it.oeffentlich)
                }
            }
            val stored = consent.laden() ?: throw SecurityException("contact_original_source_not_granted")
            require(scope.wiederherstellen(stored)) { "contact_original_source_not_granted" }
            lifetime()
            val binding = mappings.beobachten(context, peer, request.share)
                ?: throw SecurityException("contact_original_native_mapping_required")
            val grant = scope.freigabe(binding)
            val mapping = mappings.finden(peer, request.share)
                ?: throw SecurityException("contact_original_native_mapping_required")
            val requestHash = Krypto.sha256(Kanonisch.bytes(body)).joinToString("") { "%02x".format(it.toInt() and 255) }
            attempts.abschlussstatus(grant, mappings, request.id, requestHash, request.share, request.basis, request.targetHash)?.let {
                lifetime()
                return@synchronized it
            }
            attempts.pruefeNeueAnfrage(grant, request.id)
            val before = binding.aktuell().daten
            // Only the explicitly modeled full-content fields are a patch.
            // Phone/email/photo/groups cannot be requested or silently changed.
            val shell = KontaktSync.inhalt(KontaktNachricht(request.share, 1,
                requireNotNull(handlung.eigen()).kennung, 0, before, 2))
            val targetJson = JsonObject(shell.getValue("kontakt").jsonObject + request.patch)
            val target = requireNotNull(KontaktSync.lies(JsonObject(shell + ("kontakt" to targetJson)))) {
                "contact_original_content_invalid"
            }.kontakt.copy(gruppen = before.gruppen)
            require(KontaktSync.hash(target) == request.targetHash) { "contact_original_requested_target_changed" }
            val previous = attempts.laden(grant)
            val verified = if (previous != null) {
                require(previous.anfrageId() == request.id && previous.anfrageHash() == requestHash &&
                    previous.freigabeId() == request.share && previous.basisHash() == request.basis &&
                    previous.zielHash() == request.targetHash) { "contact_original_attempt_held" }
                previous.bestaetigung() ?: error("contact_original_attempt_held")
            } else {
                // Never refresh a sender's old quote behind the request.
                val token = attempts.vorbereitenGeplant(grant, mapping, request.basis, request.id, requestHash, target) {
                    lifetime()
                    protection().sichern(grant, request.id).also { lifetime() }
                }
                token.anwenden(target) { lifetime() }
            }
            lifetime()
            // The old binding's provider revision advanced. Resolve the SAME
            // private original again; do not reuse it as a fresh native grant.
            val after = mappings.beobachten(context, peer, request.share)
                ?: throw SecurityException("contact_original_native_mapping_required")
            val result = verified.ausgang(scope.freigabe(after), mapping).lesen()
            lifetime()
            buildJsonObject {
                put("art", ERGEBNIS); put("fassung", 1)
                result.forEach { (key, value) -> put(key, value) }
            }
        }

    /** Explicit query without a target: even missing history cannot cause apply. */
    fun statusabfragen(origin: Server.FsEmpfang, body: JsonObject, transportId: String): JsonObject =
        synchronized(Ablage.SCHREIBSPERRE) {
            val peerId = origin.partnerKennung()
            fun lifetime() {
                origin.pruefen(handlung.eigen(), handlung.partner(peerId), body, transportId)
                val peer = handlung.partner(peerId)
                require(handlung.istAn() && peer?.bestaetigt == true && peer.vertraut && peer.kontaktSync &&
                    verbindungFreigegeben()) { "contact_original_receive_not_available" }
            }
            lifetime()
            require(body.keys == setOf("art", "fassung", "request_id", "request_sha256", "share_id", "before_basis", "target_sha256") &&
                body["art"] == JsonPrimitive(STATUSANFRAGE) && body["fassung"] == JsonPrimitive(1)) {
                "contact_original_status_query_schema"
            }
            fun text(name: String) = (body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw IllegalArgumentException("contact_original_status_query_text")
            val id = text("request_id"); val share = text("share_id")
            require(runCatching { UUID.fromString(id).let { it.version() == 4 && it.toString() == id } }.getOrDefault(false))
            require(share.isNotBlank() && share.codePointCount(0, share.length) <= 128 &&
                share.none(Char::isISOControl) && share.codePoints().noneMatch { it in 0xD800..0xDFFF })
            val hash = text("request_sha256"); val basis = text("before_basis"); val target = text("target_sha256")
            require(listOf(hash, basis, target).all { it.matches(Regex("[0-9a-f]{64}")) })
            val peer = KontaktOriginalFreigaben.Partner(peerId, origin.partnerSchluessel())
            val scope = KontaktOriginalFreigaben(consent) {
                lifetime()
                handlung.partner(peerId)?.takeIf { it.bestaetigt && it.vertraut && it.kontaktSync }?.let {
                    KontaktOriginalFreigaben.Partner(it.kennung, it.oeffentlich)
                }
            }
            val stored = consent.laden() ?: throw SecurityException("contact_original_source_not_granted")
            require(scope.wiederherstellen(stored)) { "contact_original_source_not_granted" }
            val binding = mappings.beobachten(context, peer, share)
                ?: throw SecurityException("contact_original_native_mapping_required")
            val grant = scope.freigabe(binding)
            attempts.abschlussstatus(grant, mappings, id, hash, share, basis, target)?.let {
                lifetime(); return@synchronized it
            }
            val previous = attempts.laden(grant) ?: error("contact_original_status_unknown")
            require(previous.anfrageId() == id && previous.anfrageHash() == hash && previous.freigabeId() == share &&
                previous.basisHash() == basis && previous.zielHash() == target) { "contact_original_status_query_changed" }
            val verified = previous.bestaetigung() ?: error("contact_original_status_unknown")
            val mapping = mappings.finden(peer, share) ?: error("contact_original_native_mapping_required")
            val result = verified.ausgang(grant, mapping).lesen()
            lifetime()
            buildJsonObject {
                put("art", ERGEBNIS); put("fassung", 1)
                result.forEach { (key, value) -> put(key, value) }
            }
        }

    private data class Anfrage(val id: String, val share: String, val basis: String,
                               val targetHash: String, val patch: JsonObject)

    private fun anfrage(body: JsonObject): Anfrage {
        require(body.keys == setOf("art", "fassung", "request_id", "share_id", "before_basis", "target_sha256", "ziel") &&
            body["art"] == JsonPrimitive(ANFRAGE) && body["fassung"] == JsonPrimitive(1)) {
            "contact_original_request_schema"
        }
        fun text(name: String) = (body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: error("contact_original_request_text")
        val id = text("request_id")
        require(runCatching { UUID.fromString(id).let { it.version() == 4 && it.toString() == id } }.getOrDefault(false))
        val share = text("share_id")
        require(share.isNotBlank() && share.codePointCount(0, share.length) <= 128 &&
            share.none(Char::isISOControl) && share.codePoints().noneMatch { it in 0xD800..0xDFFF })
        val basis = text("before_basis"); val target = text("target_sha256")
        require(listOf(basis, target).all { it.matches(Regex("[0-9a-f]{64}")) })
        val patch = body["ziel"] as? JsonObject ?: error("contact_original_request_target")
        require(patch.keys == setOf("vorname", "nachname", "anzeigename", "vcardName", "firma", "notiz", "geburtstag", "jubilaeum", "anschriften"))
        return Anfrage(id, share, basis, target, patch)
    }

    companion object {
        const val ANFRAGE = "kontakt_original_anfrage"
        const val ERGEBNIS = "kontakt_original_ergebnis"
        const val BESTAETIGUNG = "kontakt_original_saveack"
        const val ABSCHLUSSSTATUS = "kontakt_original_abschlussstatus"
        const val AUSHANDLUNG = "kontakt_original_aushandlung"
        const val PROFIL = "notes-original-return-draft1"
        const val STATUSANFRAGE = "kontakt_original_statusanfrage"
    }
}
