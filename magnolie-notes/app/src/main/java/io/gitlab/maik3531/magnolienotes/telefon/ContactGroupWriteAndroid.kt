package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontaktGruppen
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.JsonPrimitive
import java.util.UUID

/** Live, single-use native snapshots. Neither a reconnect nor a disk replay can reuse a write ticket. */
class ContactGroupWriteAndroid(private val context: Context, private val now: () -> Long = SystemClock::elapsedRealtime) {
    private data class Ticket(val owner: Any, val contact: AndroidKontakt, val catalog: AndroidKontaktGruppen.Angebot,
                              val account: JsonObject, val writer: AndroidKontakte, val expires: Long)
    private val tickets = mutableMapOf<String, Ticket>()
    private var probeStage = "request"
    private var probeRawCount = 0
    private var probeVersionCount = 0
    private var probeAccountCount = 0
    private var probeRawIds = emptySet<Long>()
    private val contacts get() = AndroidKontakte(context)
    fun permission(): Boolean = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS).all {
        context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    @Synchronized fun clear(owner: Any? = null) {
        if (owner == null) tickets.clear() else tickets.entries.removeAll { it.value.owner === owner }
    }

    @Synchronized fun diagnose(request: JsonObject): JsonObject {
        ContactGroupProbe.validateRequest(request)
        var available = false; var type = "None"; var reason = "none"; var readerComplete = false
        try {
            val prepare = JsonObject(request + mapOf("version" to JsonPrimitive(ContactGroupWrite.VERSION), "action" to JsonPrimitive("prepare")))
            val report = execute(prepare, Any())
            tickets.remove(report.string("token")) // Never retain a debug write permission.
            available = true; readerComplete = true; probeStage = "complete"
        } catch (error: Exception) {
            val cause = if (probeStage == "groups" && probeRawIds.isNotEmpty()) {
                val read = runCatching { AndroidKontaktGruppen(context.contentResolver).pruefeLesbarkeit(probeRawIds) }
                readerComplete = read.isSuccess
                read.exceptionOrNull() ?: error
            } else error
            type = cause.javaClass.simpleName.takeIf { Regex("[A-Za-z][A-Za-z0-9]{0,63}").matches(it) } ?: "Exception"
            reason = cause.message?.takeIf { it in setOf("contact_groups_ambiguous_account", "contact_groups_unknown", "contact_groups_unavailable", "contact_groups_incomplete") } ?: "provider_failure"
        }
        return buildJsonObject {
            put("version", ContactGroupProbe.VERSION); put("request_id", request.string("request_id")); put("action", "diagnostics"); put("uid", request.string("uid"))
            put("state", if (available) "available" else "failed"); put("stage", probeStage); put("error_type", type); put("reason", reason)
            put("raw_count", probeRawCount); put("version_count", probeVersionCount); put("account_count", probeAccountCount)
            put("reader_complete", readerComplete)
            put("mime_supported", runCatching { context.contentResolver.getType(android.provider.ContactsContract.Groups.CONTENT_URI) == android.provider.ContactsContract.Groups.CONTENT_TYPE }.getOrDefault(false))
        }.also(ContactGroupProbe::validateReport)
    }

    /** Caller must hold the current authenticated peer/generation/opt-in guard through this operation. */
    @Synchronized fun execute(request: JsonObject, owner: Any): JsonObject {
        probeStage = "request"; probeRawCount = 0; probeVersionCount = 0; probeAccountCount = 0; probeRawIds = emptySet()
        ContactGroupWrite.validateRequest(request)
        probeStage = "permission"
        check(permission()) { "contact_groups_not_granted" }
        tickets.entries.removeAll { it.value.expires <= now() }
        val uid = request.string("uid")
        if (request.string("action") == "prepare") {
            require(tickets.size < 8)
            probeStage = "snapshot"
            val snapshot = contacts.snapshot(setOf(uid))
            probeStage = "snapshot_shape"
            require(snapshot.vollstaendig && snapshot.kontakte.size == 1)
            var contact = snapshot.kontakte.single()
            probeRawCount = contact.rawContactIds.size; probeVersionCount = contact.rawVersionen.size
            probeStage = "uid"
            require(contact.lookupKey == uid)
            val accounts = contact.herkuenfte.map { Triple(it.accountName, it.accountType, it.dataSet) }.distinct()
            probeAccountCount = accounts.size; probeStage = "account_scope"
            var writer = contacts
            if (accounts.size > 1) {
                // Messaging/raw overlays commonly aggregate with the account
                // contact but own no editable contact-group catalog. Select a
                // unique actual group-bearing account, never the first raw ID
                // or a guessed provider/domain, and scope every subsequent
                // read/write/assertion to that account's bound raw rows.
                val candidates = contact.rawContactIds.map { raw ->
                    val scoped = AndroidKontakte(context, rawScope = setOf(raw)).snapshot(setOf(uid))
                    require(scoped.vollstaendig && scoped.kontakte.size == 1)
                    val row = scoped.kontakte.single()
                    val identity = row.herkuenfte.map { Triple(it.accountName, it.accountType, it.dataSet) }.distinct().single()
                    Triple(raw, identity, AndroidKontaktGruppen(context.contentResolver).angebot(raw))
                }
                val owners = candidates.filter { it.third.benutzer.isNotEmpty() }.map { it.second }.distinct()
                require(owners.size == 1) { "contact_groups_ambiguous_account" }
                val rawIds = candidates.filter { it.second == owners.single() }.map { it.first }.toSet()
                writer = AndroidKontakte(context, rawScope = rawIds)
                val scoped = writer.snapshot(setOf(uid))
                require(scoped.vollstaendig && scoped.kontakte.size == 1)
                contact = scoped.kontakte.single()
            }
            val selected = contact.herkuenfte.map { Triple(it.accountName, it.accountType, it.dataSet) }.distinct().single()
            val account = buildJsonObject { put("name", selected.first); put("type", selected.second); put("data_set", selected.third) }
            probeStage = "raw_versions"
            require(contact.rawVersionen.keys.containsAll(contact.rawContactIds))
            probeRawIds = contact.rawContactIds.toSet()
            probeStage = "groups"
            val groups = requireNotNull(contact.daten.gruppen) { "contact_groups_unknown" }
            probeStage = "catalog"
            val catalog = AndroidKontaktGruppen(context.contentResolver).angebot(contact.rawContactId)
            val token = UUID.randomUUID().toString()
            probeStage = "report"
            val response = ContactGroupWrite.report(request, token, groups, catalog.benutzer, account)
            check(permission())
            tickets[token] = Ticket(owner, contact, catalog, account, writer, now() + 30_000)
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
        val actual = ticket.writer.uebernehmen(ticket.contact, ticket.contact.daten.copy(gruppen = wanted), false, ticket.catalog.pruefungen)
        require(actual.lookupKey == uid && actual.rawContactIds == ticket.contact.rawContactIds)
        check(permission())
        return ContactGroupWrite.report(request, token, requireNotNull(actual.daten.gruppen), account = ticket.account)
    }
}
