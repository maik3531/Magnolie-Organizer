package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.CommonDataKinds.Im
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
        if (request.string("action") == "index") {
            val entries = mutableListOf<Pair<String, Long>>()
            context.contentResolver.query(Contacts.CONTENT_URI,
                arrayOf(Contacts.LOOKUP_KEY, Contacts.CONTACT_LAST_UPDATED_TIMESTAMP), null, null, null)?.use { cursor ->
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
        val cards = uids.map { uid ->
            val contact = snapshot.kontakte.single { it.lookupKey == uid }
            val social = messengerRows(contact.contactId)
            val card = vcard(contact, thumbnail(contact.daten.foto), social)
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
        check(permission())
        return ContactRead.report(request, cards.size, cards)
    }

    private fun messengerRows(contactId: Long): List<JsonObject> {
        val result = mutableListOf<JsonObject>()
        context.contentResolver.query(Data.CONTENT_URI,
            arrayOf(Data.MIMETYPE, Data.DATA1, Im.PROTOCOL, Im.CUSTOM_PROTOCOL), "${Data.CONTACT_ID}=? AND ${Data.MIMETYPE} IN (?,?)",
            arrayOf(contactId.toString(), Im.CONTENT_ITEM_TYPE, "vnd.android.cursor.item/vnd.com.whatsapp.profile"), null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val row = messenger(cursor.getString(0).orEmpty(), cursor.getString(1).orEmpty(),
                    cursor.getString(2).orEmpty(), cursor.getString(3).orEmpty()) ?: continue
                if (row !in result) result += row
                require(result.size <= 100)
            }
        } ?: error("contacts_unavailable")
        return result
    }

    private fun thumbnail(data: String): String {
        if (data.isEmpty()) return ""
        val bytes = Base64.getDecoder().decode(data.substringAfter(","))
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
        fun messenger(mime: String, value: String, protocol: String, custom: String): JsonObject? {
            val service: String
            val identifier: String
            if (mime == "vnd.android.cursor.item/vnd.com.whatsapp.profile") {
                // A readable WhatsApp provider row, not a guessed membership
                // based on another phone-number field.
                if (!Regex("[0-9]{5,20}@s\\.whatsapp\\.net").matches(value)) return null
                service = "WhatsApp"; identifier = "+" + value.substringBefore('@')
            } else if (mime == Im.CONTENT_ITEM_TYPE && protocol == Im.PROTOCOL_CUSTOM.toString()) {
                service = listOf("WhatsApp", "Signal", "Telegram", "Threema", "Facebook", "Instagram")
                    .firstOrNull { it.equals(custom, ignoreCase = true) } ?: return null
                identifier = value.trim()
                if (identifier.isEmpty() || identifier.length > 2048 || identifier.any(Char::isISOControl)) return null
            } else return null
            return buildJsonObject { put("dienst", JsonPrimitive(service.lowercase())); put("wert", JsonPrimitive(identifier)) }
        }

        fun vcard(contact: AndroidKontakt, jpegBase64: String, social: List<JsonObject>): String {
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
