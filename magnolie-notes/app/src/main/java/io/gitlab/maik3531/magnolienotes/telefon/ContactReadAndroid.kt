package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.ContentUris
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.CommonDataKinds.Im
import android.provider.ContactsContract.CommonDataKinds.GroupMembership
import android.provider.ContactsContract.CommonDataKinds.Website
import android.provider.ContactsContract.Groups
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.io.ByteArrayOutputStream
import java.util.Base64

/** READ_CONTACTS only. No provider mutation or messenger-network access. */
interface ContactReadSource {
    fun permission(): Boolean
    fun read(request: JsonObject): JsonObject
}

class ContactReadAndroid(private val context: Context) : ContactReadSource {
    override fun permission(): Boolean = context.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED

    override fun read(request: JsonObject): JsonObject {
        check(permission())
        val uids = ContactRead.validateRequest(request)
        if (request.string("action") == "profile") {
            val diagnostics = if (request["version"] == JsonPrimitive(ContactRead.PROFILE_DIAGNOSTIC_VERSION)) mutableListOf<JsonObject>() else null
            val card = readOwnProfile(diagnostics)
            return ContactRead.profileReport(request, card, diagnostics.orEmpty())
        }
        if (request.string("action") == "index") {
            val entries = mutableListOf<Pair<String, Long>>()
            context.contentResolver.query(Contacts.CONTENT_URI,
                arrayOf(Contacts.LOOKUP_KEY, Contacts.CONTACT_LAST_UPDATED_TIMESTAMP), "${Contacts.IS_USER_PROFILE}=0", null, null)?.use { cursor ->
                while (cursor.moveToNext()) {
                    val uid = cursor.getString(0).orEmpty()
                    require(ContactRead.validUid(uid) && entries.size < ContactRead.MAX_CONTACTS)
                    entries += uid to cursor.getLong(1).coerceIn(0, 253402300799999L)
                }
            } ?: error("contacts_unavailable")
            require(entries.map { it.first }.distinct().size == entries.size)
            val offset = request.long("offset").toInt()
            require(offset <= entries.size)
            val page = entries.sortedWith(compareBy { it.first }).drop(offset).take(ContactRead.PAGE_SIZE).map { (uid, timestamp) ->
                buildJsonObject { put("uid", JsonPrimitive(uid)); put("timestamp", JsonPrimitive(timestamp)) }
            }
            check(permission())
            return ContactRead.report(request, entries.size, page)
        }
        val snapshot = AndroidKontakte(context).snapshot(uids.toSet())
        require(snapshot.vollstaendig && snapshot.kontakte.map { it.lookupKey }.toSet() == uids.toSet())
        val groupsByContact = mutableMapOf<Long, List<String>>()
        val socialByContact = mutableMapOf<Long, List<JsonObject>>()
        val cards = uids.map { uid ->
            val contact = snapshot.kontakte.single { it.lookupKey == uid }
            val social = messengerRows(contact.contactId)
            socialByContact[contact.contactId] = social
            val groups = groupRows(contact.contactId); groupsByContact[contact.contactId] = groups
            val card = vcard(contact, displayPhoto(contact), social, groups)
            buildJsonObject {
                put("uid", JsonPrimitive(uid)); put("timestamp", JsonPrimitive(contact.providerGeaendert))
                put("vcard", JsonPrimitive(card))
            }
        }
        // Refuse a provider edit in the middle of the read instead of attaching
        // the previous provider timestamp to a different card.
        val after = AndroidKontakte(context).snapshot(uids.toSet())
        require(after.vollstaendig && after.kontakte.size == snapshot.kontakte.size && snapshot.kontakte.all { before ->
            after.kontakte.any { it.lookupKey == before.lookupKey && it.providerGeaendert == before.providerGeaendert &&
                it.rawVersionen == before.rawVersionen }
        })
        require(groupsByContact.all { (id, groups) -> groupRows(id) == groups })
        require(socialByContact.all { (id, social) -> messengerRows(id) == social })
        check(permission())
        return ContactRead.report(request, cards.size, cards)
    }

    private fun readOwnProfile(diagnostics: MutableList<JsonObject>? = null): String {
        var stage = "canonical_header"
        fun observe(step: String, rows: Int, outcome: String) {
            if (diagnostics != null && diagnostics.size < 32) diagnostics.add(buildJsonObject {
                put("stage", JsonPrimitive(step)); put("rows", JsonPrimitive(rows.coerceIn(-1, 1000))); put("outcome", JsonPrimitive(outcome))
            })
        }
        val uri = android.provider.ContactsContract.Profile.CONTENT_URI
        fun headerQuery(columns: Array<String>, marked: Boolean): List<String>? {
            stage = if (marked) "marked_header" else "canonical_header"
            try {
                val cursor = context.contentResolver.query(if (marked) Contacts.CONTENT_URI else uri, columns,
                    if (marked) "${Contacts.IS_USER_PROFILE}=1" else null, null, null)
                if (cursor == null) { observe(stage, -1, "no_cursor"); return null }
                return cursor.use {
                    val count = it.count
                    if (count != 1 || !it.moveToFirst()) {
                        observe(stage, count, if (count == 0) "empty" else "ambiguous"); null
                    } else if (it.getLong(0) < 0 || marked && it.getInt(columns.lastIndex) != 1) {
                        observe(stage, count, "invalid_identity"); null
                    } else {
                        observe(stage, count, "ok")
                        listOf(it.getString(0).orEmpty(), it.getString(1).orEmpty(),
                            if (columns.size > if (marked) 3 else 2) it.getString(2).orEmpty() else "", if (marked) "marked" else "profile")
                    }
                }
            } catch (error: SecurityException) { observe(stage, -1, "permission_denied"); throw error }
            catch (error: IllegalArgumentException) { observe(stage, -1, "unsupported_or_invalid"); throw error }
        }
        fun header(): List<String>? {
            val canonical = try {
                headerQuery(arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY, Contacts.CONTACT_LAST_UPDATED_TIMESTAMP), false)
            } catch (_: IllegalArgumentException) {
                headerQuery(arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY), false)
            }
            if (canonical != null) return canonical
            return try {
                headerQuery(arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY, Contacts.CONTACT_LAST_UPDATED_TIMESTAMP, Contacts.IS_USER_PROFILE), true)
            } catch (_: IllegalArgumentException) {
                headerQuery(arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY, Contacts.IS_USER_PROFILE), true)
            }
        }
        return try {
            val initial = header() ?: run { observe("finish", -1, "no_profile"); return "" }
            val sourceUri = if (initial[3] == "profile") uri else ContentUris.withAppendedId(Contacts.CONTENT_URI, initial[0].toLong())
            val dataUri = if (initial[3] == "profile") android.net.Uri.withAppendedPath(uri, "data") else Data.CONTENT_URI
            fun escape(text: String) = text.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
                .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")
            fun rows(): List<String> {
                stage = "data"
                val lines = mutableListOf<String>()
                val types = mutableSetOf<String>()
                context.contentResolver.query(dataUri,
                 arrayOf(Data.MIMETYPE, Data.DATA1, Data.DATA2, Data.DATA3, Data.DATA4, Data.DATA7, Data.DATA8, Data.DATA9, Data.DATA10, Data.DATA15),
                if (initial[3] == "profile") null else "${Data.CONTACT_ID}=?",
                if (initial[3] == "profile") null else arrayOf(initial[0]), null)?.use { cursor ->
                var count = 0
                while (cursor.moveToNext()) {
                    require(++count <= 1000)
                    fun text(index: Int) = cursor.getString(index).orEmpty()
                    val mime = text(0); types.add(mime)
                    when (mime) {
                        android.provider.ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE ->
                            lines.add("N:" + escape(text(3)) + ";" + escape(text(2)) + ";;;")
                        android.provider.ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE ->
                            lines.add("TEL;VALUE=text;TYPE=" + (if (text(2) == "2") "CELL" else "VOICE") + ":" + escape(text(1)))
                        android.provider.ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE -> lines.add("EMAIL:" + escape(text(1)))
                        android.provider.ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE -> lines.add("ORG:" + escape(text(1)))
                        android.provider.ContactsContract.CommonDataKinds.StructuredPostal.CONTENT_ITEM_TYPE ->
                            lines.add("ADR:;;" + listOf(text(4), text(5), text(6), text(7), text(8)).joinToString(";", transform = ::escape))
                         android.provider.ContactsContract.CommonDataKinds.Photo.CONTENT_ITEM_TYPE -> {
                            val photo = runCatching { cursor.getBlob(9)?.takeIf { it.isNotEmpty() }?.let(::thumbnailBytes) }.getOrNull()
                            if (!photo.isNullOrEmpty()) lines.add("PHOTO:data:image/jpeg;base64," + photo)
                         }
                         android.provider.ContactsContract.CommonDataKinds.Event.CONTENT_ITEM_TYPE -> {
                            val field = when (text(2).toIntOrNull()) {
                                android.provider.ContactsContract.CommonDataKinds.Event.TYPE_BIRTHDAY -> "BDAY"
                                android.provider.ContactsContract.CommonDataKinds.Event.TYPE_ANNIVERSARY -> "ANNIVERSARY"
                                else -> null
                            }
                            val date = text(1).trim()
                            if (field != null && Regex("(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|--[0-9]{2}-?[0-9]{2})").matches(date))
                                lines.add(field + ":" + date.replace("-", "").let { if (date.startsWith("--")) "--$it" else it })
                         }
                    }
                 }
                observe("data", count, "ok")
                } ?: run { observe("data", -1, "no_cursor"); return emptyList() }
                // Capability metadata only: no medical values are transferred
                // without a separate, explicitly requested medical-data path.
                val medicalTypes = types.filter { it.contains("medical", true) || it.contains("emergency", true) }
                if (medicalTypes.isNotEmpty()) lines.add("X-MAGNOLIE-PROFILE-MEDICAL-TYPES:" + medicalTypes.sorted().joinToString(",", transform = ::escape))
                return lines
            }
            val data = rows()
            stage = "photo"
            val preferredPhoto = runCatching {
                Contacts.openContactPhotoInputStream(context.contentResolver, sourceUri, true)?.use { input ->
                    val output = ByteArrayOutputStream(); val buffer = ByteArray(8192)
                    while (true) { val length = input.read(buffer); if (length < 0) break
                        require(output.size() + length <= 8 * 1024 * 1024); output.write(buffer, 0, length) }
                    thumbnailBytes(output.toByteArray())
                }
            }.getOrNull()
            observe("photo", if (preferredPhoto.isNullOrEmpty()) 0 else 1, "ok")
            stage = "finish"
            check(permission() && header() == initial)
            if (initial[2].isEmpty()) check(rows() == data)
            val lines = mutableListOf("BEGIN:VCARD", "VERSION:4.0", "FN:" + escape(initial[1]))
            lines.addAll(if (preferredPhoto.isNullOrEmpty()) data else data.filterNot { it.startsWith("PHOTO:") } + ("PHOTO:data:image/jpeg;base64," + preferredPhoto))
            val card = (lines + "END:VCARD").joinToString("\r\n", postfix = "\r\n")
            if (card.toByteArray().size > ContactRead.MAX_CARD_BYTES) { observe("finish", -1, "too_large"); "" }
            else { observe("finish", -1, "ok"); card }
        } catch (_: SecurityException) { observe(stage, -1, "permission_denied"); "" }
        catch (_: IllegalArgumentException) { observe(stage, -1, "unsupported_or_invalid"); "" }
        catch (error: IllegalStateException) {
            if (diagnostics == null) throw error
            observe(stage, -1, "provider_changed"); ""
        } catch (error: Exception) {
            if (diagnostics == null) throw error
            observe(stage, -1, "provider_failure"); ""
        }
    }

    private fun groupRows(contactId: Long): List<String> {
        val ids = mutableSetOf<Long>()
        context.contentResolver.query(Data.CONTENT_URI, arrayOf(GroupMembership.GROUP_ROW_ID),
            "${Data.CONTACT_ID}=? AND ${Data.MIMETYPE}=?", arrayOf(contactId.toString(), GroupMembership.CONTENT_ITEM_TYPE), null)?.use { cursor ->
            while (cursor.moveToNext()) {
                if (!cursor.isNull(0)) cursor.getLong(0).takeIf { it > 0 }?.let(ids::add)
                require(ids.size <= ContactRead.MAX_CONTACTS)
            }
        } ?: return emptyList()
        val names = mutableSetOf<String>()
        for (chunk in ids.sorted().chunked(256)) context.contentResolver.query(Groups.CONTENT_URI,
            arrayOf(Groups.TITLE), "${Groups.DELETED}=0 AND ${Groups._ID} IN (${chunk.joinToString(",") { "?" }})",
            chunk.map(Long::toString).toTypedArray(), null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val title = cursor.getString(0).orEmpty().trim()
                if (title.isNotEmpty() && !title.any(Char::isISOControl)) names.add(title)
            }
        }
        return names.sorted()
    }

    private fun messengerRows(contactId: Long): List<JsonObject> {
        val result = mutableListOf<JsonObject>()
        val types = listOf(Im.CONTENT_ITEM_TYPE, "vnd.android.cursor.item/vnd.com.whatsapp.profile", Website.CONTENT_ITEM_TYPE) + threemaProfileTypes
        context.contentResolver.query(Data.CONTENT_URI,
            arrayOf(Data.MIMETYPE, Data.DATA1, Im.PROTOCOL, Im.CUSTOM_PROTOCOL), "${Data.CONTACT_ID}=? AND ${Data.MIMETYPE} IN (${types.joinToString(",") { "?" }})",
            (listOf(contactId.toString()) + types).toTypedArray(), null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val row = messenger(cursor.getString(0).orEmpty(), cursor.getString(1).orEmpty(),
                    cursor.getString(2).orEmpty(), cursor.getString(3).orEmpty()) ?: continue
                if (row !in result) result += row
                require(result.size <= 100)
            }
        } ?: error("contacts_unavailable")
        return result.sortedBy { it.toString() }
    }

    private fun thumbnail(data: String): String {
        if (data.isEmpty()) return ""
        val bytes = Base64.getDecoder().decode(data.substringAfter(","))
        return thumbnailBytes(bytes)
    }

    private fun displayPhoto(contact: AndroidKontakt): String {
        // The aggregated contact's selected display picture can differ from
        // the first nonempty photo among its linked raw-account contacts.
        val stream = try {
            Contacts.openContactPhotoInputStream(context.contentResolver,
                ContentUris.withAppendedId(Contacts.CONTENT_URI, contact.contactId), true)
        } catch (_: java.io.IOException) { null }
        if (stream == null) return thumbnail(contact.daten.foto)
        val bytes = stream.use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val length = input.read(buffer)
                if (length < 0) break
                require(output.size() + length <= 8 * 1024 * 1024)
                output.write(buffer, 0, length)
            }
            output.toByteArray()
        }
        return if (bytes.isEmpty()) thumbnail(contact.daten.foto) else thumbnailBytes(bytes)
    }

    private fun thumbnailBytes(bytes: ByteArray): String {
        require(bytes.size <= 8 * 1024 * 1024)
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        require(bounds.outWidth in 1..16384 && bounds.outHeight in 1..16384)
        val options = BitmapFactory.Options().apply {
            inSampleSize = 1
            while (bounds.outWidth / inSampleSize > 256 || bounds.outHeight / inSampleSize > 256) inSampleSize *= 2
        }
        val source = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options) ?: error("invalid_contact_photo")
        val scale = minOf(1.0, 128.0 / maxOf(source.width, source.height))
        val small = Bitmap.createScaledBitmap(source, maxOf(1, (source.width * scale).toInt()), maxOf(1, (source.height * scale).toInt()), true)
        try {
            val output = ByteArrayOutputStream()
            check(small.compress(Bitmap.CompressFormat.JPEG, 75, output))
            require(output.size() <= 16 * 1024)
            return Base64.getEncoder().encodeToString(output.toByteArray())
        } finally { if (small !== source) small.recycle(); source.recycle() }
    }

    companion object {
        // Threema's AndroidContactUtil stores the actual identity in DATA1.
        private val threemaProfileTypes = listOf("ch.threema.app", "ch.threema.app.work", "ch.threema.app.green", "ch.threema.app.onprem",
            "ch.threema.app.blue", "ch.threema.app.hms", "ch.threema.app.work.hms", "ch.threema.app.libre")
            .map { "vnd.android.cursor.item/vnd.$it.profile" }
        fun messenger(mime: String, value: String, protocol: String, custom: String): JsonObject? {
            if (mime == Website.CONTENT_ITEM_TYPE) return profileLink(value)
            val service: String
            val identifier: String
            if (mime == "vnd.android.cursor.item/vnd.com.whatsapp.profile") {
                // A readable WhatsApp provider row, not a guessed membership
                // based on another phone-number field.
                identifier = when {
                    Regex("[0-9]{5,20}@s\\.whatsapp\\.net").matches(value) -> "+" + value.substringBefore('@')
                    Regex("\\+[0-9]{5,20}").matches(value) -> value
                    Regex("[0-9]{5,20}").matches(value) -> "+$value"
                    else -> return null
                }
                service = "WhatsApp"
            } else if (mime in threemaProfileTypes) {
                identifier = value.trim().uppercase()
                if (!Regex("(?:[A-Z0-9]{8}|\\*[A-Z0-9]{7})").matches(identifier)) return null
                service = "Threema"
            } else if (mime == Im.CONTENT_ITEM_TYPE && protocol == Im.PROTOCOL_CUSTOM.toString()) {
                service = listOf("WhatsApp", "Signal", "Telegram", "Threema", "Facebook", "Instagram", "Teams",
                    "Snapchat", "TikTok", "YouTube", "Mastodon", "X", "LinkedIn", "Reddit")
                    .firstOrNull { it.equals(custom.trim(), ignoreCase = true) }
                    ?: if (custom.equals("Twitter", ignoreCase = true)) "X" else return null
                identifier = value.trim()
                if (identifier.isEmpty() || identifier.length > 2048 || identifier.any(Char::isISOControl)) return null
                if (Regex("(?i)^https?://").containsMatchIn(identifier)) return profileLink(identifier, service.lowercase())
            } else return null
            return buildJsonObject { put("dienst", JsonPrimitive(service.lowercase())); put("wert", JsonPrimitive(identifier)) }
        }

        fun profileLink(raw: String, declared: String? = null): JsonObject? {
            val value = raw.trim()
            if (value.length !in 1..2048 || value.any(Char::isISOControl)) return null
            val uri = runCatching { java.net.URI(value) }.getOrNull() ?: return null
            if (uri.scheme?.lowercase() !in setOf("http", "https") || uri.rawUserInfo != null || uri.port !in setOf(-1, 80, 443)) return null
            val host = uri.host?.lowercase()?.removePrefix("www.") ?: return null
            val path = uri.path.orEmpty().trim('/'); val pieces = path.split('/').filter(String::isNotBlank)
            var fragment: String? = null; var query: String? = null
            fun single(pattern: String, excluded: Set<String> = emptySet()) = pieces.size == 1 && Regex(pattern).matches(pieces[0]) && pieces[0].lowercase() !in excluded
            val service = when {
                host == "instagram.com" && single("[A-Za-z0-9._]{1,30}", setOf("accounts", "explore", "direct", "stories", "reels", "reel", "p", "about")) -> "instagram"
                host in setOf("facebook.com", "m.facebook.com") && path == "profile.php" -> {
                    val id = uri.rawQuery.orEmpty().split('&').singleOrNull { it.startsWith("id=") }?.removePrefix("id=") ?: return null
                    if (!Regex("[0-9]+").matches(id)) return null
                    query = "id=$id"; "facebook"
                }
                host in setOf("facebook.com", "m.facebook.com") && single("[A-Za-z0-9.]+", setOf("login", "help", "pages", "groups", "watch", "share", "sharer", "privacy", "settings", "marketplace", "events", "photo", "photos", "reel")) -> "facebook"
                host in setOf("facebook.com", "m.facebook.com") && pieces.size == 3 && pieces[0] == "people" && Regex("[0-9]+").matches(pieces[2]) -> "facebook"
                host in setOf("x.com", "twitter.com") && single("[A-Za-z0-9_]{1,15}", setOf("home", "explore", "search", "settings", "intent", "i", "compose", "messages", "notifications")) -> "x"
                host in setOf("t.me", "telegram.me") && single("[A-Za-z][A-Za-z0-9_]{4,31}", setOf("share", "joinchat", "addstickers", "proxy", "login")) -> "telegram"
                host == "wa.me" && single("[0-9]{5,20}") -> "whatsapp"
                host == "threema.id" && single("[A-Za-z0-9]{8}") -> "threema"
                host == "signal.me" && Regex("p/\\+[0-9]{5,20}|eu/[A-Za-z0-9_-]+").matches(uri.fragment.orEmpty()) -> { fragment = uri.fragment; "signal" }
                host == "linkedin.com" && pieces.size == 2 && pieces[0] in setOf("in", "company") -> "linkedin"
                host == "youtube.com" && (single("@[A-Za-z0-9._-]+") || pieces.size == 2 && pieces[0] == "channel") -> "youtube"
                host == "tiktok.com" && single("@[A-Za-z0-9._]+") -> "tiktok"
                host == "snapchat.com" && pieces.size == 2 && pieces[0] == "add" -> "snapchat"
                host == "reddit.com" && pieces.size == 2 && pieces[0] in setOf("u", "user") -> "reddit"
                declared == "mastodon" && (single("@[A-Za-z0-9_.-]+") || pieces.size == 2 && pieces[0] == "users") -> "mastodon"
                else -> return null
            }
            if (declared != null && declared != service) return null
            val clean = java.net.URI("https", null, host, -1, uri.path.orEmpty(), query, fragment).toASCIIString()
            return buildJsonObject { put("dienst", JsonPrimitive(service)); put("wert", JsonPrimitive(clean)) }
        }

        fun vcard(contact: AndroidKontakt, jpegBase64: String, social: List<JsonObject>, groups: List<String> = emptyList()): String {
            fun text(value: String) = value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
                .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")
            fun type(value: String): String {
                val normalized = when (value.lowercase()) {
                    "privat", "home" -> "HOME"
                    "arbeit", "work" -> "WORK"
                    "mobil", "mobile", "cell" -> "CELL"
                    "sonstige", "other" -> "OTHER"
                    else -> value.uppercase()
                }
                return normalized.takeIf { Regex("[A-Z0-9-]{1,32}").matches(it) }?.let { ";TYPE=$it" }.orEmpty()
            }
            val data = contact.daten
            val lines = mutableListOf("BEGIN:VCARD", "VERSION:3.0", "UID:" + text(contact.lookupKey))
            if (data.vcardName.isNotEmpty()) lines += data.vcardName else {
                lines += "N:${text(data.nachname)};${text(data.vorname)};;;"
                lines += "FN:" + text(data.anzeigename.ifBlank { listOf(data.vorname, data.nachname).filter(String::isNotBlank).joinToString(" ").ifBlank { data.firma } })
            }
            if (data.firma.isNotEmpty()) lines += "ORG:" + text(data.firma)
            if (data.notiz.isNotEmpty()) lines += "NOTE:" + text(data.notiz)
            if (data.geburtstag.isNotEmpty()) lines += "BDAY:" + text(data.geburtstag)
            if (data.jubilaeum.isNotEmpty()) lines += "ANNIVERSARY:" + text(data.jubilaeum)
            if (groups.isNotEmpty()) lines += "CATEGORIES:" + groups.distinct().joinToString(",", transform = ::text)
            data.telefone.forEach { lines += "TEL${type(it.art)}:" + text(it.wert) }
            data.emailEintraege.forEach { lines += "EMAIL${type(it.art)}:" + text(it.wert) }
            data.anschriften.forEach { lines += "ADR${type(it.art)}:;;${text(it.strasse)};${text(it.ort)};${text(it.region)};${text(it.plz)};${text(it.land)}" }
            if (jpegBase64.isNotEmpty()) lines += "PHOTO;ENCODING=b;TYPE=JPEG:$jpegBase64"
            social.forEach { lines += "X-MAGNOLIE-SOZIALES-MEDIUM:" + text(it.toString()) }
            if (contact.providerGeaendert > 0) lines += "REV:" + java.time.Instant.ofEpochMilli(contact.providerGeaendert).toString()
            lines += "END:VCARD"
            val card = lines.joinToString("\r\n") { line ->
                buildString {
                    var width = 0
                    line.codePoints().forEach { point ->
                        val part = String(Character.toChars(point)); val size = part.toByteArray(Charsets.UTF_8).size
                        if (width + size > 75) { append("\r\n "); width = 1 }
                        append(part); width += size
                    }
                }
            } + "\r\n"
            require(card.toByteArray(Charsets.UTF_8).size <= ContactRead.MAX_CARD_BYTES)
            return card
        }
    }
}
