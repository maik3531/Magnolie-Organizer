import io.gitlab.maik3531.magnolienotes.baum.*
import kotlinx.serialization.json.*

fun main() {
    val keys = Krypto.neuesSchluesselpaar()
    val identity = EigeneIdentitaet("android-interop", "Synthetic Android", Krypto.b64(keys.second), Krypto.b64(keys.first), 8737)
    var peer: JsonObject? = null
    var start: Sitzung.Start? = null
    var session: Sitzung.Offen? = null
    var envelope: JsonObject? = null
    val received = mutableListOf<JsonObject>()
    generateSequence(::readLine).forEach { line ->
        val result = runCatching {
            val r = Kanonisch.json.parseToJsonElement(line).jsonObject
            val data = r["data"]?.jsonObject
            when (r.getValue("op").jsonPrimitive.content) {
                "init" -> identity.alsZweig()
                "pair" -> { peer = data; JsonPrimitive(true) }
                "start" -> { start = Sitzung.baueStart(identity, peer!!.getValue("kennung").jsonPrimitive.content, peer!!.getValue("oeffentlich").jsonPrimitive.content); start!!.nachricht }
                "message" -> {
                    session = Sitzung.oeffneAntwort(identity, peer!!.getValue("kennung").jsonPrimitive.content, peer!!.getValue("oeffentlich").jsonPrimitive.content, start!!, data!!)
                    envelope = Sitzung.baueUmschlag(session!!, identity.kennung, peer!!.getValue("kennung").jsonPrimitive.content, r.getValue("content").jsonObject, Krypto.b64(Krypto.zufallsbytes(16)))
                    envelope!!
                }
                "ack" -> JsonPrimitive(Sitzung.pruefeQuittung(session!!, envelope!!, data)).also { session!!.loeschen() }
                "request" -> {
                    val body = if (r["text"]?.jsonPrimitive?.content == "/magnolie/v2/sitzung") {
                        val answer = Sitzung.baueAntwort(identity, peer!!.getValue("kennung").jsonPrimitive.content, peer!!.getValue("oeffentlich").jsonPrimitive.content, data!!)
                        session = answer.sitzung; answer.nachricht
                    } else {
                        val opened = Sitzung.oeffneUmschlag(session!!, identity.kennung, peer!!.getValue("kennung").jsonPrimitive.content, data!!).first
                        if (opened["art"] == JsonPrimitive("kontakt_faehigkeiten")) requireNotNull(KontaktFaehigkeiten.lesen(opened))
                        else requireNotNull(KontaktSync.lies(opened))
                        received += opened
                        Sitzung.baueQuittung(session!!, data).also { session!!.loeschen() }
                    }
                    buildJsonObject { put("Status", JsonPrimitive(200)); put("Body", body) }
                }
                "received" -> JsonArray(received)
                "capabilities" -> KontaktFaehigkeiten.inhalt(false)
                "import" -> {
                    val n = requireNotNull(KontaktSync.lies(data!!))
                    val sent = mutableListOf<JsonObject>()
                    val flow = KontaktImportAblauf { _, message -> sent += message }
                    val preview = flow.vorschau(KontaktSnapshot(listOf(AndroidKontakt("synthetic-lookup", 1, n.kontakt)), true), "desktop", identity.kennung, n.fassung)
                    flow.bestaetigen(preview.id)
                    JsonArray(sent)
                }
                "validate" -> JsonPrimitive(if (data!!["art"] == JsonPrimitive("kontakt_faehigkeiten"))
                    KontaktFaehigkeiten.lesen(data) != null else KontaktSync.lies(data) != null)
                "roundtrip" -> {
                    val n = requireNotNull(KontaktSync.lies(data!!))
                    // Exercise the actual generated, persisted DTO serializer as well as the wire codec.
                    val stored = Kanonisch.json.encodeToString(KontaktDaten.serializer(), n.kontakt)
                    val restored = Kanonisch.json.decodeFromString(KontaktDaten.serializer(), stored)
                    require(restored == n.kontakt)
                    KontaktSync.inhalt(n.copy(kontakt = restored))
                }
                "hash" -> JsonPrimitive(KontaktSync.hash(requireNotNull(KontaktSync.lies(data!!)).kontakt))
                else -> error("unknown operation")
            }
        }
        println(buildJsonObject {
            result.fold({ put("value", it) }, { put("error", JsonPrimitive(it.toString())) })
        })
    }
}
