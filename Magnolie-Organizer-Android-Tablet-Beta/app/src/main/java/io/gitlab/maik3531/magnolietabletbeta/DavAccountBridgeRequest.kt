package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.json.JSONArray

/** Exact native account envelope; never log this object or stringify its secret fields. */
internal class DavAccountBridgeRequest private constructor(
    val command: String, val requestId: String?, val expectedRevision: String?,
    val configuration: DavAccountConfiguration?, val applicationPassword: String,
    val clearPassword: Boolean
) {
    val callback: String get() = callback(command)
    val discovery: Boolean get() = command == "baum_briefkasten_pruefen" || command == "baum_dav_pruefen"
    companion object {
        val commands = setOf("baum_briefkasten_status", "baum_briefkasten_speichern",
            "baum_briefkasten_pruefen", "baum_dav_pruefen", "eds_status")
        fun callback(command: String): String = when (command) {
            "baum_briefkasten_status" -> "baumBriefkastenStatus"
            "baum_briefkasten_speichern" -> "baumBriefkastenGespeichert"
            "baum_briefkasten_pruefen" -> "baumBriefkastenPruefung"
            "baum_dav_pruefen" -> "baumDavPruefung"
            "eds_status" -> "edsStatus"
            else -> throw DavAccountException("invalid_request")
        }
        fun sources(status: DavAccountStatus, requestId: String?): JSONObject {
            val actual = status.payload()
            val calendars = actual.getValue("kalender") as Collection<*>
            val books = actual.getValue("adressbuecher") as Collection<*>
            return JSONObject().put("android",true).put("systemAccountSyncImplemented",false)
                .put("verfuegbar",status.calendars.isNotEmpty() || status.addressBooks.isNotEmpty())
                .put("buchOk",status.addressBooks.isNotEmpty()).put("kalender",JSONArray(calendars))
                .put("adressbuecher",JSONArray(books)).put("alleKalender",JSONArray(calendars))
                .put("alleAdressbuecher",JSONArray(books)).put("nextcloud",JSONObject(actual))
                .put("fehler",actual.getValue("fehler")).put("fehlerCode",status.errorCode)
                .also { if (requestId != null) it.put("requestId",requestId) }
        }
        fun failure(command: String, requestId: String?, status: DavAccountStatus?, code: String): JSONObject {
            val payload = if (status == null) JSONObject().put("android",true).put("systemAccountSyncImplemented",false)
                else if (command == "eds_status") sources(status,requestId)
                else JSONObject(status.payload(requestId,if (command == "baum_briefkasten_speichern") false else null))
            payload.put("ok",false).put("fehlerCode",code).put("fehler","The DAV account operation failed.")
            if (requestId != null) payload.put("requestId",requestId)
            if (command == "baum_briefkasten_speichern") payload.put("persisted",false).put("verified",false)
            if (command == "baum_dav_pruefen") payload.put("errorCode",code).put("reachable",false).put("partial",false)
            return payload
        }
        fun parse(message: JSONObject): DavAccountBridgeRequest {
            fun invalid(): Nothing = throw DavAccountException("invalid_request")
            fun string(key: String, maximum: Int, empty: Boolean = true): String {
                val value = message.opt(key) as? String ?: invalid()
                if ((!empty && value.isEmpty()) || value.toByteArray(Charsets.UTF_8).size > maximum) invalid()
                return value
            }
            fun boolean(key: String) = message.opt(key) as? Boolean ?: invalid()
            val command = string("cmd", 64, false)
            if (command !in commands) invalid()
            val base = setOf("cmd", "session", "revision", "requestId")
            val expected = command == "baum_briefkasten_speichern" || command == "baum_briefkasten_pruefen" || command == "baum_dav_pruefen"
            val save = command == "baum_briefkasten_speichern"
            val extra = if (save) setOf("kontoArt", "davAktiv", "briefkastenAktiv", "url", "benutzer",
                "anwendungskennwort", "kennwortLoeschen", "expectedRevision") else if (expected) setOf("expectedRevision") else emptySet()
            val keys = message.keys().asSequence().toSet()
            if (!keys.all { it in base + extra } || !keys.containsAll((base - "requestId") + extra)) invalid()
            string("session", 1024, false); string("revision", 1024, false)
            val requestId = if (message.has("requestId")) string("requestId", 1024, false) else null
            if (command == "baum_dav_pruefen" && requestId == null) invalid()
            val revision = if (expected) string("expectedRevision", 64, false).also {
                if (!it.matches(Regex("[a-f0-9]{64}"))) invalid()
            } else null
            val configuration = if (save) {
                val typeName = string("kontoArt", 64, false)
                val type = DavAccountType.entries.firstOrNull { it.wireName == typeName } ?: invalid()
                DavAccountConfiguration(type, boolean("davAktiv"), boolean("briefkastenAktiv"),
                    string("url", 4096, false), string("benutzer", 1024, false))
            } else null
            return DavAccountBridgeRequest(command, requestId, revision, configuration,
                if (save) string("anwendungskennwort", 16384) else "", if (save) boolean("kennwortLoeschen") else false)
        }
    }
}
