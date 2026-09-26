package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.NotizQuelle
import io.gitlab.maik3531.magnolienotes.daten.NotizVorlagen
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Source identities survive local duplicate consolidation in both directions. */
object NotizQuellen {
    fun lokaleAenderung(old: Notiz?, next: Notiz): Notiz =
        if (old?.baumFreigabe != null) next.copy(baumFreigabe = old.baumFreigabe,
            baumVersion = old.baumVersion, baumQuelle = old.baumQuelle, baumGeaendert = old.baumGeaendert,
            persoenlichVerknuepft = old.persoenlichVerknuepft,
            baumInhaltVersion = old.baumInhaltVersion + if (gleicherInhalt(old, next)) 0 else 1) else next

    fun konflikt(note: Notiz, partner: String, id: String, incoming: Notiz): Boolean {
        val source = quelle(note, partner, id) ?: return false
        return source.stand != note.baumInhaltVersion && !gleicherInhalt(note, incoming)
    }

    fun gleicherInhalt(left: Notiz, right: Notiz): Boolean {
        fun value(note: Notiz): List<Any>? {
            val text = note.text.replace("\r\n", "\n").replace("\r", "\n")
            val escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            val plain = note.html in setOf("", escaped, escaped.replace("\n", "<br>"),
                "<p>$escaped</p>", "<div>$escaped</div>", "<span>$escaped</span>")
            val attachments = note.anhaenge.map { attachment ->
                val descriptor = PersonalSync.attachmentDescriptor(attachment)?.descriptor ?: return null
                JsonObject(descriptor.filterKeys { it != "attachment_id" })
            }.sortedBy { PersonalSync.canonical(it).toString(Charsets.UTF_8) }
            return listOf(note.titel, if (plain && attachments.isEmpty()) NotizVorlagen.vergleichsText(note.titel, text) else text,
                if (plain) "" else note.html, attachments)
        }
        val a = value(left) ?: return false
        return a == value(right)
    }

    fun quelle(note: Notiz, partner: String, id: String): NotizQuelle? {
        val share = note.baumFreigabe ?: return null
        if (partner !in share.partner) return null
        return share.quellen.firstOrNull { it.partner == partner && it.id == id }
            ?: if (share.id == id && share.quellen.none { it.partner == partner })
                NotizQuelle(partner, id, note.baumVersion, note.baumQuelle) else null
    }

    fun inhalte(note: Notiz, art: String, eigen: String, partner: String): List<JsonObject> {
        val share = note.baumFreigabe ?: return emptyList()
        if (partner !in share.partner) return emptyList()
        val ids = share.quellen.filter { it.partner == partner }.map { it.id }.distinct().ifEmpty { listOf(share.id) }
        val base = Nutzlast.notizInhalt(note, art, eigen)
        return ids.map { JsonObject(base + ("freigabeId" to JsonPrimitive(it))) }
    }
}
