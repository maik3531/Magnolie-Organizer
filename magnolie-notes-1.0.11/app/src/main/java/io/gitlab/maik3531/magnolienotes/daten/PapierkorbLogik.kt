package io.gitlab.maik3531.magnolienotes.daten

import java.util.UUID

object PapierkorbLogik {
    private const val MAX = 3000
    private fun neu(art: String, name: String, parent: String = "", notiz: Notiz? = null,
                    aufgabe: Aufgabe? = null, buch: Notizbuch? = null, anhang: Anhang? = null,
                    mappings: Map<String, String> = emptyMap(), now: Long = System.currentTimeMillis()) =
        PapierkorbEintrag(UUID.randomUUID().toString(), art, name, now, parent,
            notiz, aufgabe, buch, anhang, mappings)

    private fun add(input: Bestand, item: PapierkorbEintrag): List<PapierkorbEintrag> =
        if (!input.papierkorbEinstellungen.an) input.papierkorb
        else (input.papierkorb + item).takeLast(MAX)

    fun loescheNotiz(input: Bestand, id: String, now: Long = System.currentTimeMillis()): Bestand {
        val value = input.notizen.firstOrNull { it.id == id } ?: return input
        return input.copy(notizen = input.notizen.filterNot { it.id == id },
            papierkorb = add(input, neu("note", value.anzeigeTitel, notiz = value.copy(), now = now)))
    }

    fun loescheAufgabe(input: Bestand, id: String, now: Long = System.currentTimeMillis()): Bestand {
        val value = input.aufgaben.firstOrNull { it.id == id } ?: return input
        return input.copy(aufgaben = input.aufgaben.filterNot { it.id == id },
            papierkorb = add(input, neu("task", value.anzeigeTitel, aufgabe = value.copy(), now = now)))
    }

    fun loescheAnhang(input: Bestand, noteId: String, id: String,
                      now: Long = System.currentTimeMillis()): Bestand {
        val note = input.notizen.firstOrNull { it.id == noteId } ?: return input
        val value = note.anhaenge.firstOrNull { it.id == id } ?: return input
        val changed = note.copy(anhaenge = note.anhaenge.filterNot { it.id == id }, geaendert = now)
        return input.copy(notizen = input.notizen.map { if (it.id == noteId) changed else it },
            papierkorb = add(input, neu("attachment", value.name, noteId, anhang = value.copy(), now = now)))
    }

    /** Nonempty notebooks are never cascaded, including confirmed remote deletion. */
    fun loescheNotizbuch(input: Bestand, id: String, now: Long = System.currentTimeMillis()): Bestand? {
        val value = input.notizbuecher.firstOrNull { it.id == id } ?: return input
        if (input.notizen.any { it.notizbuchId == id }) return null
        return input.copy(notizbuecher = input.notizbuecher.filterNot { it.id == id },
            papierkorb = add(input, neu("notebook", value.name, buch = value.copy(), now = now)))
    }

    fun bereinigen(input: Bestand, now: Long = System.currentTimeMillis()): Bestand {
        val days = input.papierkorbEinstellungen.tage
        val valid = input.papierkorb.filter { item -> item.art in setOf("note", "task", "notebook", "attachment") &&
            item.geloescht_ms >= 0 && listOfNotNull(item.notiz, item.aufgabe, item.notizbuch, item.anhang).size == 1 &&
            (item.art != "attachment" || item.parent_id.isNotBlank()) }
        val retained = if (days == 0) valid else valid.filter { it.geloescht_ms > now - days * 86_400_000L }
        return input.copy(papierkorb = retained.takeLast(MAX))
    }

    fun wiederherstellen(input: Bestand, trashId: String, now: Long = System.currentTimeMillis()): Bestand? {
        val item = input.papierkorb.firstOrNull { it.id == trashId } ?: return null
        var result = input.copy(papierkorb = input.papierkorb.filterNot { it.id == trashId })
        val entityId = when (item.art) {
            "note" -> item.notiz!!.id
            "task" -> item.aufgabe!!.id
            "notebook" -> item.notizbuch!!.id
            else -> item.anhang!!.id
        }
        val collision = when (item.art) {
            "note" -> result.notizen.any { it.id == entityId }
            "task" -> result.aufgaben.any { it.id == entityId }
            "notebook" -> result.notizbuecher.any { it.id == entityId }
            else -> result.notizen.firstOrNull { it.id == item.parent_id }?.anhaenge?.any { it.id == entityId } != false
        }
        if (collision) return null
        result = when (item.art) {
            "note" -> result.copy(notizen = result.notizen + item.notiz!!)
            "task" -> result.copy(aufgaben = result.aufgaben + item.aufgabe!!)
            "notebook" -> result.copy(notizbuecher = result.notizbuecher + item.notizbuch!!,
                notizen = result.notizen.map { note -> item.notiz_zuordnungen[note.id]?.let { note.copy(notizbuchId = it) } ?: note })
            else -> { val parent = result.notizen.firstOrNull { it.id == item.parent_id } ?: return null
                result.copy(notizen = result.notizen.map { if (it.id == parent.id) it.copy(
                    anhaenge = it.anhaenge + item.anhang!!, geaendert = now) else it }) }
        }
        val key = if (item.art == "attachment") "attachment\u0000${item.parent_id}\u0000$entityId" else "${item.art}\u0000$entityId"
        val old = result.personalSync.entities[key]
        if (old != null && old.state == "deleted") {
            val actor = result.personalSync.actor_id.ifBlank { UUID.randomUUID().toString() }
            val counter = result.personalSync.counter + 1
            val clock = (old.clock + PersonalSyncClock(actor, counter)).groupBy { it.actor_id }
                .map { PersonalSyncClock(it.key, it.value.maxOf(PersonalSyncClock::counter)) }.sortedBy { it.actor_id }
            result = result.copy(personalSync = result.personalSync.copy(actor_id = actor, counter = counter,
                entities = result.personalSync.entities + (key to old.copy(clock = clock, state = "live",
                    status = "restored", hash = "", acknowledged_by_peer = false, proposal_id = "")),
                restoration_requests = (result.personalSync.restoration_requests + key).distinct()))
        }
        return result
    }
}
