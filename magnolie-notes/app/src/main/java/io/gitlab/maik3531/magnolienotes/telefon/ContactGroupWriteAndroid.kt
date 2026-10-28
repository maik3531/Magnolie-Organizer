package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontaktGruppen
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import kotlinx.serialization.json.JsonObject
import java.util.UUID

/** Live, single-use native snapshots. Neither a reconnect nor a disk replay can reuse a write ticket. */
class ContactGroupWriteAndroid(private val context: Context, private val now: () -> Long = SystemClock::elapsedRealtime) {
    private data class Ticket(val owner: Any, val contact: AndroidKontakt, val catalog: AndroidKontaktGruppen.Angebot, val expires: Long)
    private val tickets = mutableMapOf<String, Ticket>()
    private val contacts get() = AndroidKontakte(context)
    fun permission(): Boolean = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS).all {
        context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    @Synchronized fun clear() = tickets.clear()

    /** Caller must hold the current authenticated peer/generation/opt-in guard through this operation. */
    @Synchronized fun execute(request: JsonObject, owner: Any): JsonObject {
        ContactGroupWrite.validateRequest(request)
        check(permission()) { "contact_groups_not_granted" }
        tickets.entries.removeAll { it.value.expires <= now() }
        val uid = request.string("uid")
        if (request.string("action") == "prepare") {
            require(tickets.size < 8)
            val snapshot = contacts.snapshot(setOf(uid))
            require(snapshot.vollstaendig && snapshot.kontakte.size == 1)
            val contact = snapshot.kontakte.single()
            require(contact.lookupKey == uid && contact.rawVersionen.keys.containsAll(contact.rawContactIds))
            val groups = requireNotNull(contact.daten.gruppen) { "contact_groups_unknown" }
            val catalog = AndroidKontaktGruppen(context.contentResolver).angebot(contact.rawContactId)
            val token = UUID.randomUUID().toString()
            val response = ContactGroupWrite.report(request, token, groups, catalog.benutzer)
            check(permission())
            tickets[token] = Ticket(owner, contact, catalog, now() + 30_000)
            return response
        }
        val token = request.string("token")
        val ticket = requireNotNull(tickets[token]) { "contact_groups_stale" }
        require(ticket.owner === owner && ticket.contact.lookupKey == uid && ticket.expires > now())
        val wanted = ContactGroupWrite.names(request, "groups")
        val system = ticket.catalog.system
        require(wanted.none { name -> system.any { it.equals(name, ignoreCase = true) } }) { "contact_groups_system" }
        // Consume before provider I/O. On an uncertain failure, prepare/read again;
        // never retry a destructive membership replacement from a persisted queue.
        tickets.remove(token)
        val actual = contacts.uebernehmen(ticket.contact, ticket.contact.daten.copy(gruppen = wanted), false, ticket.catalog.pruefungen)
        require(actual.lookupKey == uid && actual.rawContactIds == ticket.contact.rawContactIds)
        check(permission())
        return ContactGroupWrite.report(request, token, requireNotNull(actual.daten.gruppen))
    }
}
