package io.gitlab.maik3531.magnolienotes.baum

import android.content.ContentProviderOperation
import android.content.ContentUris
import android.provider.ContactsContract
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.CommonDataKinds.*

/** Low-level native full-content writer, NOT an automatic-source permission.
 * No transport command or capability is connected here. Its future controller
 * must supply genuine native durable approval and original protection; neither
 * a serialized binding nor an imported Boolean can construct the binding.
 * Phone/email, photo, groups and non-modeled native columns remain unchanged.
 */
internal class KontaktOriginalInhalt(private val freigabe: KontaktOriginalFreigaben.Freigabe) {
    private val bindung get() = freigabe.bindung
    private var verbraucht = false

    @Synchronized fun uebernehmen(ziel: KontaktDaten, freigabePruefen: () -> Unit,
                                 originalSchuetzen: (AndroidKontakt) -> Unit): AndroidKontakt {
        check(!verbraucht) { "contact_original_attempt_consumed" }
        verbraucht = true // A failed/uncertain attempt cannot be replayed by this writer.
        fun guard() { freigabe.pruefen(); freigabePruefen(); freigabe.pruefen() }
        guard()
        val before = bindung.aktuell()
        val alt = before.daten
        require(alt.copy(vorname = ziel.vorname, nachname = ziel.nachname, anzeigename = ziel.anzeigename,
            vcardName = ziel.vcardName, firma = ziel.firma, notiz = ziel.notiz, geburtstag = ziel.geburtstag,
            jubilaeum = ziel.jubilaeum, anschriften = ziel.anschriften) == ziel) { "contact_original_field_scope_changed" }
        val parsed = KontaktSync.lies(KontaktSync.inhalt(KontaktNachricht("original-return", 1, "native", 0, ziel, 2)))
        require(parsed?.kontakt?.copy(gruppen = ziel.gruppen) == ziel) { "contact_original_content_invalid" }
        if (ziel == alt) { guard(); return bindung.aktuell() }
        val ops = arrayListOf<ContentProviderOperation>()
        fun scalar(mime: String, values: Map<String, Any>, event: Int? = null) {
            val args = listOf(bindung.rawContactId.toString(), mime) + listOfNotNull(event?.toString())
            val ids = requireNotNull(bindung.resolver().query(Data.CONTENT_URI, arrayOf(Data._ID),
                "${Data.RAW_CONTACT_ID}=? AND ${Data.MIMETYPE}=?" + if (event == null) "" else " AND ${Event.TYPE}=?",
                args.toTypedArray(), null)).use { cursor ->
                require(cursor.count <= 1) { "contact_original_scalar_ambiguous" }
                if (cursor.moveToFirst()) cursor.getLong(0) else null
            }
            val op = if (ids == null) ContentProviderOperation.newInsert(Data.CONTENT_URI)
                .withValue(Data.RAW_CONTACT_ID, bindung.rawContactId).withValue(Data.MIMETYPE, mime)
            else ContentProviderOperation.newUpdate(ContentUris.withAppendedId(Data.CONTENT_URI, ids)).withExpectedCount(1)
            values.forEach { (key, value) -> op.withValue(key, value) }
            ops += op.build()
        }
        if (alt.vorname != ziel.vorname || alt.nachname != ziel.nachname || alt.anzeigename != ziel.anzeigename || alt.vcardName != ziel.vcardName) {
            scalar(StructuredName.CONTENT_ITEM_TYPE, AndroidKontakte.nameWerte(ziel))
            scalar(AndroidKontakte.NAME_MIME, mapOf(Data.DATA1 to AndroidKontakte.namenJson(ziel)))
        }
        if (alt.firma != ziel.firma) scalar(Organization.CONTENT_ITEM_TYPE, mapOf(Organization.COMPANY to ziel.firma))
        if (alt.notiz != ziel.notiz) scalar(Note.CONTENT_ITEM_TYPE, mapOf(Note.NOTE to ziel.notiz))
        if (alt.geburtstag != ziel.geburtstag) scalar(Event.CONTENT_ITEM_TYPE,
            mapOf(Event.START_DATE to ziel.geburtstag, Event.TYPE to Event.TYPE_BIRTHDAY), Event.TYPE_BIRTHDAY)
        if (alt.jubilaeum != ziel.jubilaeum) scalar(Event.CONTENT_ITEM_TYPE,
            mapOf(Event.START_DATE to ziel.jubilaeum, Event.TYPE to Event.TYPE_ANNIVERSARY), Event.TYPE_ANNIVERSARY)
        if (alt.anschriften != ziel.anschriften) postal(ops, alt.anschriften, ziel.anschriften)
        require(ops.isNotEmpty() && ops.size <= 400)
        val guarded = ArrayList(bindung.pruefungen() + ops)
        require(guarded.size <= 900)
        val parcel = android.os.Parcel.obtain()
        try {
            guarded.forEach {
                it.writeToParcel(parcel, 0)
                require(parcel.dataSize() <= AndroidKontakte.MAX_RESTORE_NUTZLAST) { "contact_original_binder_budget_required" }
            }
        } finally { parcel.recycle() }
        // Planning can reject ambiguity before creating any protection record.
        guard(); bindung.aktuell()
        originalSchuetzen(before)
        guard()
        bindung.aktuell()
        guard()
        bindung.resolver().applyBatch(ContactsContract.AUTHORITY, guarded)
        // Native approval is checked after writing without reusing the old
        // provider revision; readback below independently verifies new identity.
        freigabe.pruefenNachSchreiben(); freigabePruefen(); freigabe.pruefenNachSchreiben()
        return bindung.ruecklesenNachSchreiben().also {
            require(it.daten == ziel) { "contact_original_full_readback_failed" }
            freigabe.pruefenNachSchreiben()
        }
    }

    private data class Postal(val id: Long, val value: KontaktAnschrift, val unmodelliert: Boolean)
    private fun postal(ops: MutableList<ContentProviderOperation>, before: List<KontaktAnschrift>, wanted: List<KontaktAnschrift>) {
        val rows = requireNotNull(bindung.resolver().query(Data.CONTENT_URI, arrayOf(Data._ID, StructuredPostal.TYPE,
            StructuredPostal.STREET, StructuredPostal.POSTCODE, StructuredPostal.CITY, StructuredPostal.REGION, StructuredPostal.COUNTRY,
            StructuredPostal.POBOX, StructuredPostal.NEIGHBORHOOD, Data.DATA11, Data.DATA12, Data.DATA13, Data.DATA14, Data.DATA15),
            "${Data.RAW_CONTACT_ID}=? AND ${Data.MIMETYPE}=?", arrayOf(bindung.rawContactId.toString(), StructuredPostal.CONTENT_ITEM_TYPE), null)).use { cursor ->
            val result = mutableListOf<Postal>()
            while (cursor.moveToNext()) {
                require(result.size < 100)
                val kind = when (cursor.getInt(1)) { StructuredPostal.TYPE_HOME -> "privat"; StructuredPostal.TYPE_WORK -> "arbeit"; else -> "sonstige" }
                fun text(i: Int) = cursor.getString(i).orEmpty()
                val hidden = (7..13).any { !cursor.isNull(it) &&
                    (cursor.getType(it) != android.database.Cursor.FIELD_TYPE_STRING || cursor.getString(it).isNotEmpty()) }
                result += Postal(cursor.getLong(0), KontaktAnschrift(kind, text(2), text(3), text(4), text(5), text(6)), hidden)
            }
            result
        }
        require(rows.map { it.value } == before && wanted.distinct().size == wanted.size) { "contact_original_postal_projection_ambiguous" }
        val remaining = rows.toMutableList()
        val pending = wanted.toMutableList()
        // Exact unchanged rows retain every native byte/column, not just modeled values.
        wanted.forEach { value ->
            val matches = remaining.filter { it.value == value }
            require(matches.size <= 1)
            if (matches.size == 1) { remaining.remove(matches.single()); pending.remove(value) }
        }
        fun assign(row: Postal, value: KontaktAnschrift) {
            val op = ContentProviderOperation.newUpdate(ContentUris.withAppendedId(Data.CONTENT_URI, row.id)).withExpectedCount(1)
                .withValue(StructuredPostal.STREET, value.strasse).withValue(StructuredPostal.POSTCODE, value.plz)
                .withValue(StructuredPostal.CITY, value.ort).withValue(StructuredPostal.REGION, value.region)
                .withValue(StructuredPostal.COUNTRY, value.land).withValue(StructuredPostal.FORMATTED_ADDRESS, null)
            if (row.value.art != value.art) op.withValue(StructuredPostal.TYPE, type(value.art)).withValue(StructuredPostal.LABEL, null)
            ops += op.build(); remaining.remove(row); pending.remove(value)
        }
        pending.toList().forEach { value ->
            val old = remaining.filter { it.value.art == value.art }
            if (old.size == 1 && pending.count { it.art == value.art } == 1) assign(old.single(), value)
        }
        if (remaining.size == 1 && pending.size == 1) assign(remaining.single(), pending.single())
        require(remaining.isEmpty() || pending.isEmpty()) { "contact_original_postal_pairing_ambiguous" }
        require(remaining.none { it.unmodelliert }) { "contact_original_unmodeled_postal_removal" }
        remaining.forEach { ops += ContentProviderOperation.newDelete(ContentUris.withAppendedId(Data.CONTENT_URI, it.id)).withExpectedCount(1).build() }
        pending.forEach { value -> ops += ContentProviderOperation.newInsert(Data.CONTENT_URI)
            .withValue(Data.RAW_CONTACT_ID, bindung.rawContactId).withValue(Data.MIMETYPE, StructuredPostal.CONTENT_ITEM_TYPE)
            .withValue(StructuredPostal.TYPE, type(value.art)).withValue(StructuredPostal.STREET, value.strasse)
            .withValue(StructuredPostal.POSTCODE, value.plz).withValue(StructuredPostal.CITY, value.ort)
            .withValue(StructuredPostal.REGION, value.region).withValue(StructuredPostal.COUNTRY, value.land).build() }
    }

    private fun type(kind: String) = when (kind) {
        "privat" -> StructuredPostal.TYPE_HOME; "arbeit" -> StructuredPostal.TYPE_WORK; else -> StructuredPostal.TYPE_OTHER
    }
}
