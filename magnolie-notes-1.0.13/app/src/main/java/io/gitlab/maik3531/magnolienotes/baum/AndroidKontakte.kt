package io.gitlab.maik3531.magnolienotes.baum

import android.content.ContentProviderOperation
import android.content.ContentUris
import android.content.Context
import android.provider.ContactsContract.CommonDataKinds.Email
import android.provider.ContactsContract.CommonDataKinds.Event
import android.provider.ContactsContract.CommonDataKinds.Note
import android.provider.ContactsContract.CommonDataKinds.Organization
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.CommonDataKinds.Photo
import android.provider.ContactsContract.CommonDataKinds.StructuredName
import android.provider.ContactsContract.CommonDataKinds.StructuredPostal
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract
import android.content.ContentValues
import io.gitlab.maik3531.magnolienotes.journal.KontaktRohstand
import io.gitlab.maik3531.magnolienotes.journal.KontaktZeile

data class AndroidKontakt(
    val lookupKey: String,
    val rawContactId: Long,
    val daten: KontaktDaten,
    val contactId: Long = rawContactId,
    val rawContactIds: Set<Long> = setOf(rawContactId),
    val herkuenfte: List<KontaktHerkunft> = emptyList()
)
data class KontaktHerkunft(
    val accountType: String = "", val accountName: String = "", val dataSet: String = "",
    val sourceId: String = "", val lookupKey: String = ""
)
data class KontaktSnapshot(val kontakte: List<AndroidKontakt>, val vollstaendig: Boolean)
interface KontaktSchreiber {
    fun anlegen(k: KontaktDaten): AndroidKontakt
    fun mischen(rawId: Long, fern: KontaktDaten): AndroidKontakt?
    fun fotoErgaenzen(rawId: Long, foto: String): AndroidKontakt?
}

/** Schmale Android-Grenze; Vertrag, Revision und Merge bleiben in [KontaktSync]. */
class AndroidKontakte(private val context: Context) : KontaktSchreiber {
    private val resolver get() = context.contentResolver

    fun snapshot(): KontaktSnapshot {
      return try {
        val rawZuKontakt = linkedMapOf<Long, Long>()
        val herkunft = mutableMapOf<Long, KontaktHerkunft>()
        resolver.query(RawContacts.CONTENT_URI, arrayOf(RawContacts._ID, RawContacts.CONTACT_ID,
            RawContacts.ACCOUNT_TYPE, RawContacts.ACCOUNT_NAME, RawContacts.DATA_SET, RawContacts.SOURCE_ID),
            "${RawContacts.DELETED}=0", null, null)?.use { c ->
            while (c.moveToNext()) {
                rawZuKontakt[c.getLong(0)] = c.getLong(1)
                herkunft[c.getLong(0)] = KontaktHerkunft(c.getString(2).orEmpty(), c.getString(3).orEmpty(),
                    c.getString(4).orEmpty(), c.getString(5).orEmpty())
            }
        } ?: return KontaktSnapshot(emptyList(), false)
        val lookup = mutableMapOf<Long, String>()
        resolver.query(Contacts.CONTENT_URI, arrayOf(Contacts._ID, Contacts.LOOKUP_KEY), null, null, null)?.use { c ->
            while (c.moveToNext()) lookup[c.getLong(0)] = c.getString(1).orEmpty()
        } ?: return KontaktSnapshot(emptyList(), false)
        val daten = rawZuKontakt.keys.associateWith { BauKontakt() }.toMutableMap()
        val spalten = arrayOf(Data.RAW_CONTACT_ID, Data.MIMETYPE, Data.DATA1, Data.DATA2,
            Data.DATA3, Data.DATA4, Data.DATA5, Data.DATA6, Data.DATA7, Data.DATA8, Data.DATA9, Data.DATA10,
            Data.DATA15)
        resolver.query(Data.CONTENT_URI, spalten, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val b = daten[c.getLong(0)] ?: continue
                val mime = c.getString(1)
                fun s(i: Int) = c.getString(i).orEmpty()
                when (mime) {
                    StructuredName.CONTENT_ITEM_TYPE -> { b.vorname = s(3); b.nachname = s(4) }
                    Organization.CONTENT_ITEM_TYPE -> b.firma = s(2)
                    Note.CONTENT_ITEM_TYPE -> b.notiz = s(2)
                    Event.CONTENT_ITEM_TYPE -> if (s(3).toIntOrNull() == Event.TYPE_BIRTHDAY) b.geburtstag = s(2)
                    Phone.CONTENT_ITEM_TYPE -> b.telefone += KontaktWert(art(s(3)), s(2))
                    Email.CONTENT_ITEM_TYPE -> b.emails += KontaktWert(art(s(3)), s(2))
                    StructuredPostal.CONTENT_ITEM_TYPE -> b.anschriften += KontaktAnschrift(
                        art(s(3)), strasse = s(5), plz = s(10), ort = s(8), region = s(9), land = s(11)
                    )
                    Photo.CONTENT_ITEM_TYPE -> b.foto = KontaktSync.fotoDataUrl(c.getBlob(12) ?: byteArrayOf())
                }
            }
        } ?: return KontaktSnapshot(emptyList(), false)
        val roh = rawZuKontakt.mapNotNull { (raw, kontakt) ->
            val b = daten[raw] ?: return@mapNotNull null
            val lookupKey = lookup[kontakt].orEmpty()
            AndroidKontakt(lookupKey, raw, KontaktSync.normalisiere(b.fertig()), kontakt,
                herkuenfte = listOf((herkunft[raw] ?: KontaktHerkunft()).copy(lookupKey = lookupKey)))
        }.filter { k -> with(k.daten) {
            vorname.isNotBlank() || nachname.isNotBlank() || firma.isNotBlank() ||
                telefone.isNotEmpty() || emailEintraege.isNotEmpty() || anschriften.isNotEmpty()
        } }
        KontaktSnapshot(aggregiere(roh), true)
      } catch (_: SecurityException) { KontaktSnapshot(emptyList(), false) }
        catch (_: Exception) { KontaktSnapshot(emptyList(), false) }
    }

    fun alle(): List<AndroidKontakt> = snapshot().let {
        if (!it.vollstaendig) throw IllegalStateException("Kontakte konnten nicht vollständig gelesen werden.")
        it.kontakte
    }

    fun liesRaw(rawId: Long): AndroidKontakt? {
        val gruppe = alle().firstOrNull { rawId in it.rawContactIds } ?: return null
        return gruppe.copy(rawContactId = rawId)
    }

    /** Verlustarmer, auf ausgewählte RawContacts begrenzter Journalstand. */
    fun journalStaende(rawIds: Collection<Long>, action: String): List<KontaktRohstand> = rawIds.distinct()
        .mapNotNull { rawId ->
            val meta = resolver.query(ContentUris.withAppendedId(RawContacts.CONTENT_URI, rawId), arrayOf(
                RawContacts.ACCOUNT_NAME, RawContacts.ACCOUNT_TYPE, RawContacts.DATA_SET,
                RawContacts.SOURCE_ID, RawContacts.AGGREGATION_MODE, RawContacts.CONTACT_ID
            ), null, null, null)?.use { c ->
                if (!c.moveToFirst()) null else arrayOf(c.getString(0), c.getString(1), c.getString(2),
                    c.getString(3), c.getInt(4), c.getLong(5))
            } ?: return@mapNotNull null
            val columns = arrayOf(Data.MIMETYPE) + (1..15).map { "data$it" } +
                (1..4).map { "sync$it" } + arrayOf(Data.IS_PRIMARY, Data.IS_SUPER_PRIMARY)
            val rows = mutableListOf<KontaktZeile>()
            resolver.query(Data.CONTENT_URI, columns, "${Data.RAW_CONTACT_ID}=?",
                arrayOf(rawId.toString()), null)?.use { c -> while (c.moveToNext()) rows += KontaktZeile(
                mime = c.getString(0).orEmpty(),
                data = (1..15).map { i -> if (c.getType(i) == android.database.Cursor.FIELD_TYPE_BLOB)
                    android.util.Base64.encodeToString(c.getBlob(i), android.util.Base64.NO_WRAP) else c.getString(i) },
                sync = (16..19).map(c::getString), primary = c.getInt(20) != 0,
                superPrimary = c.getInt(21) != 0
            ) }
            val portable = runCatching { liesRaw(rawId)?.daten }.getOrNull() ?: KontaktDaten()
            @Suppress("UNCHECKED_CAST")
            KontaktRohstand(rawId, runCatching { liesRaw(rawId)?.lookupKey }.getOrNull().orEmpty(),
                meta[0] as String?, meta[1] as String?, meta[2] as String?, meta[3] as String?,
                meta[4] as Int, rows, portable, KontaktSync.hash(portable), action)
        }

    fun geplanterStand(k: KontaktDaten, action: String) = KontaktRohstand(
        portable = k, beforeHash = KontaktSync.hash(k), action = action, generatedByMagnolie = true)

    enum class RestoreErgebnis { WIEDERHERGESTELLT, KONFLIKT, NICHT_SCHREIBBAR }

    /** Stellt nur den im Snapshot gebundenen RawContact wieder her; niemals einen Namensfund. */
    fun wiederherstellen(stand: KontaktRohstand, konfliktBestaetigt: Boolean): RestoreErgebnis =
        wiederherstellenMitGrenzen(stand, konfliktBestaetigt,
            aktuellLesen = { stand.rawContactId.takeIf { it > 0 }?.let(::liesRaw) },
            batchAnwenden = { resolver.applyBatch(ContactsContract.AUTHORITY, it) })

    fun loeschen(rawId: Long, lookupKey: String): Boolean {
        val lokal = runCatching { liesRaw(rawId) }.getOrNull() ?: return false
        if (lokal.lookupKey != lookupKey) return false
        val op = ContentProviderOperation.newDelete(ContentUris.withAppendedId(RawContacts.CONTENT_URI, rawId)).build()
        resolver.applyBatch(ContactsContract.AUTHORITY, arrayListOf(op))
        return true
    }

    fun systemkontaktOeffnen(lookupKey: String): Boolean {
        if (lookupKey.isBlank()) return false
        val uri = android.net.Uri.withAppendedPath(Contacts.CONTENT_LOOKUP_URI, lookupKey)
        return runCatching {
            context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, uri)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)); true
        }.getOrDefault(false)
    }

    fun verknuepfen(rawId: Long, andererRawId: Long): Boolean {
        if (rawId <= 0 || andererRawId <= 0 || rawId == andererRawId) return false
        val op = ContentProviderOperation.newInsert(ContactsContract.AggregationExceptions.CONTENT_URI)
            .withValue(ContactsContract.AggregationExceptions.TYPE,
                ContactsContract.AggregationExceptions.TYPE_KEEP_TOGETHER)
            .withValue(ContactsContract.AggregationExceptions.RAW_CONTACT_ID1, rawId)
            .withValue(ContactsContract.AggregationExceptions.RAW_CONTACT_ID2, andererRawId)
            .build()
        resolver.applyBatch(ContactsContract.AUTHORITY, arrayListOf(op))
        return true
    }

    override fun anlegen(k: KontaktDaten): AndroidKontakt {
        val ops = arrayListOf(ContentProviderOperation.newInsert(RawContacts.CONTENT_URI)
            .withValue(RawContacts.ACCOUNT_TYPE, null).withValue(RawContacts.ACCOUNT_NAME, null).build())
        fuegeDatenEin(ops, k, null)
        val ergebnis = resolver.applyBatch(ContactsContract.AUTHORITY, ops)
        val rawId = ContentUris.parseId(ergebnis.first().uri!!)
        return liesRaw(rawId) ?: AndroidKontakt("", rawId, k)
    }

    override fun mischen(rawId: Long, fern: KontaktDaten): AndroidKontakt? {
        val lokal = liesRaw(rawId) ?: return null
        val ziel = KontaktSync.mische(lokal.daten, fern)
        val ops = arrayListOf<ContentProviderOperation>()
        aktualisiereSkalare(ops, rawId, lokal.daten, ziel)
        fuegeListenEin(ops, rawId, lokal.daten, ziel)
        if (ops.isNotEmpty()) resolver.applyBatch(ContactsContract.AUTHORITY, ops)
        return liesRaw(rawId) ?: lokal.copy(daten = ziel)
    }

    /** Ergänzt nur auf der über eine Spur bestimmten RawContact-ID und nie über ein Namensmatching. */
    override fun fotoErgaenzen(rawId: Long, foto: String): AndroidKontakt? {
        val lokal = liesRaw(rawId) ?: return null
        if (lokal.daten.foto.isNotEmpty() || foto.isEmpty()) return lokal
        val bytes = KontaktSync.fotoBytes(foto) ?: return lokal
        if (bytes.isEmpty()) return lokal
        val op = einfuegen(rawId, Photo.CONTENT_ITEM_TYPE, mapOf(Photo.PHOTO to bytes))
        resolver.applyBatch(ContactsContract.AUTHORITY, arrayListOf(op))
        return liesRaw(rawId) ?: lokal.copy(daten = lokal.daten.copy(foto = foto))
    }

    private fun aktualisiereSkalare(ops: MutableList<ContentProviderOperation>, raw: Long,
                                    alt: KontaktDaten, neu: KontaktDaten) {
        if (neu.vorname != alt.vorname || neu.nachname != alt.nachname) {
            setzeOderFuege(ops, raw, StructuredName.CONTENT_ITEM_TYPE,
                mapOf(StructuredName.GIVEN_NAME to neu.vorname, StructuredName.FAMILY_NAME to neu.nachname))
        }
        if (neu.firma != alt.firma) setzeOderFuege(ops, raw, Organization.CONTENT_ITEM_TYPE,
            mapOf(Organization.COMPANY to neu.firma))
        if (neu.notiz != alt.notiz) setzeOderFuege(ops, raw, Note.CONTENT_ITEM_TYPE, mapOf(Note.NOTE to neu.notiz))
        if (neu.geburtstag != alt.geburtstag) setzeOderFuege(ops, raw, Event.CONTENT_ITEM_TYPE,
            mapOf(Event.START_DATE to neu.geburtstag, Event.TYPE to Event.TYPE_BIRTHDAY))
    }

    private fun setzeOderFuege(ops: MutableList<ContentProviderOperation>, raw: Long, mime: String,
                               werte: Map<String, Any>) {
        val vorhanden = resolver.query(Data.CONTENT_URI, arrayOf(Data._ID),
            "${Data.RAW_CONTACT_ID}=? AND ${Data.MIMETYPE}=?", arrayOf(raw.toString(), mime), null)
            ?.use { if (it.moveToFirst()) it.getLong(0) else null }
        val bau = if (vorhanden != null) ContentProviderOperation.newUpdate(
            ContentUris.withAppendedId(Data.CONTENT_URI, vorhanden)) else ContentProviderOperation.newInsert(Data.CONTENT_URI)
            .withValue(Data.RAW_CONTACT_ID, raw).withValue(Data.MIMETYPE, mime)
        werte.forEach { (name, wert) -> bau.withValue(name, wert) }
        ops += bau.build()
    }

    private fun fuegeListenEin(ops: MutableList<ContentProviderOperation>, raw: Long,
                               alt: KontaktDaten, neu: KontaktDaten) {
        neu.telefone.drop(alt.telefone.size).forEach { w -> ops += einfuegen(raw, Phone.CONTENT_ITEM_TYPE,
            mapOf(Phone.NUMBER to w.wert, Phone.TYPE to typ(w.art))) }
        neu.emailEintraege.drop(alt.emailEintraege.size).forEach { w -> ops += einfuegen(raw, Email.CONTENT_ITEM_TYPE,
            mapOf(Email.ADDRESS to w.wert, Email.TYPE to typ(w.art))) }
        neu.anschriften.drop(alt.anschriften.size).forEach { a -> ops += einfuegen(raw, StructuredPostal.CONTENT_ITEM_TYPE,
            mapOf(StructuredPostal.TYPE to typ(a.art), StructuredPostal.STREET to a.strasse,
                StructuredPostal.POSTCODE to a.plz, StructuredPostal.CITY to a.ort,
                StructuredPostal.REGION to a.region, StructuredPostal.COUNTRY to a.land)) }
    }

    private fun fuegeDatenEin(ops: MutableList<ContentProviderOperation>, k: KontaktDaten, raw: Long?) {
        fun add(mime: String, werte: Map<String, Any>) {
            var b = ContentProviderOperation.newInsert(Data.CONTENT_URI)
            b = if (raw == null) b.withValueBackReference(Data.RAW_CONTACT_ID, 0) else b.withValue(Data.RAW_CONTACT_ID, raw)
            b.withValue(Data.MIMETYPE, mime); werte.forEach { (n, v) -> b.withValue(n, v) }; ops += b.build()
        }
        if (k.vorname.isNotBlank() || k.nachname.isNotBlank()) add(StructuredName.CONTENT_ITEM_TYPE,
            mapOf(StructuredName.GIVEN_NAME to k.vorname, StructuredName.FAMILY_NAME to k.nachname))
        if (k.firma.isNotBlank()) add(Organization.CONTENT_ITEM_TYPE, mapOf(Organization.COMPANY to k.firma))
        if (k.notiz.isNotBlank()) add(Note.CONTENT_ITEM_TYPE, mapOf(Note.NOTE to k.notiz))
        if (k.geburtstag.isNotBlank()) add(Event.CONTENT_ITEM_TYPE,
            mapOf(Event.START_DATE to k.geburtstag, Event.TYPE to Event.TYPE_BIRTHDAY))
        k.telefone.forEach { add(Phone.CONTENT_ITEM_TYPE, mapOf(Phone.NUMBER to it.wert, Phone.TYPE to typ(it.art))) }
        k.emailEintraege.forEach { add(Email.CONTENT_ITEM_TYPE, mapOf(Email.ADDRESS to it.wert, Email.TYPE to typ(it.art))) }
        k.anschriften.forEach { add(StructuredPostal.CONTENT_ITEM_TYPE,
            mapOf(StructuredPostal.TYPE to typ(it.art), StructuredPostal.STREET to it.strasse,
                StructuredPostal.POSTCODE to it.plz, StructuredPostal.CITY to it.ort,
                StructuredPostal.REGION to it.region, StructuredPostal.COUNTRY to it.land)) }
    }

    private fun einfuegen(raw: Long, mime: String, werte: Map<String, Any>): ContentProviderOperation {
        val b = ContentProviderOperation.newInsert(Data.CONTENT_URI).withValue(Data.RAW_CONTACT_ID, raw)
            .withValue(Data.MIMETYPE, mime)
        werte.forEach { (n, v) -> b.withValue(n, v) }
        return b.build()
    }

    private fun art(typ: String) = when (typ.toIntOrNull()) { 1 -> "privat"; 2 -> "mobil"; 3 -> "arbeit"; else -> "sonstige" }
    private fun typ(art: String) = when (art.trim().lowercase()) {
        "privat", "home" -> 1; "mobil", "mobile" -> 2; "arbeit", "work" -> 3; else -> 7
    }

    private class BauKontakt {
        var vorname = ""; var nachname = ""; var firma = ""; var notiz = ""; var geburtstag = ""
        var foto = ""
        val telefone = mutableListOf<KontaktWert>(); val emails = mutableListOf<KontaktWert>()
        val anschriften = mutableListOf<KontaktAnschrift>()
        fun fertig() = KontaktDaten(vorname, nachname, firma, notiz, geburtstag, foto, telefone, emails, anschriften)
    }

    companion object {
        // Deutlich unter dem Binder-Limit bleiben. Ein Aufteilen waere hier nicht atomar.
        internal const val MAX_RESTORE_OPERATIONEN = 400
        internal const val MAX_RESTORE_NUTZLAST = 700 * 1024

        internal fun wiederherstellenMitGrenzen(
            stand: KontaktRohstand,
            konfliktBestaetigt: Boolean,
            aktuellLesen: () -> AndroidKontakt?,
            batchAnwenden: (ArrayList<ContentProviderOperation>) -> Unit
        ): RestoreErgebnis {
            val aktuell = runCatching(aktuellLesen).getOrElse { return RestoreErgebnis.NICHT_SCHREIBBAR }
            if (aktuell != null && KontaktSync.hash(aktuell.daten) != stand.beforeHash && !konfliktBestaetigt) {
                return RestoreErgebnis.KONFLIKT
            }
            val ops = runCatching { restoreOperationen(stand, aktuell != null) }
                .getOrElse { return RestoreErgebnis.NICHT_SCHREIBBAR }
            return runCatching {
                batchAnwenden(ops)
                RestoreErgebnis.WIEDERHERGESTELLT
            }.getOrElse {
                // applyBatch ist die einzige Mutationsgrenze; der ContactsProvider rollt den Batch zurueck.
                RestoreErgebnis.NICHT_SCHREIBBAR
            }
        }

        private fun restoreOperationen(stand: KontaktRohstand, vorhanden: Boolean): ArrayList<ContentProviderOperation> {
            require(stand.rows.size + 1 <= MAX_RESTORE_OPERATIONEN)
            require(stand.rows.all { it.mime.isNotBlank() && it.data.size <= 15 && it.sync.size <= 4 })
            var groesse = 512L + listOf(stand.accountName, stand.accountType, stand.dataSet, stand.sourceId)
                .sumOf { it?.toByteArray(Charsets.UTF_8)?.size?.toLong() ?: 0L }
            val dekodierteFotos = mutableMapOf<Int, ByteArray>()
            stand.rows.forEachIndexed { index, row ->
                groesse += 512L + row.mime.toByteArray(Charsets.UTF_8).size
                row.data.forEachIndexed { dataIndex, value -> if (value != null) {
                    if (row.mime == Photo.CONTENT_ITEM_TYPE && dataIndex == 14) {
                        val bytes = java.util.Base64.getDecoder().decode(value)
                        dekodierteFotos[index] = bytes
                        groesse += bytes.size
                    } else groesse += value.toByteArray(Charsets.UTF_8).size
                } }
                row.sync.filterNotNull().forEach { groesse += it.toByteArray(Charsets.UTF_8).size }
                require(groesse <= MAX_RESTORE_NUTZLAST)
            }

            val ops = arrayListOf<ContentProviderOperation>()
            if (vorhanden) {
                ops += ContentProviderOperation.newDelete(Data.CONTENT_URI)
                    .withSelection("${Data.RAW_CONTACT_ID}=?", arrayOf(stand.rawContactId.toString())).build()
            } else {
                ops += ContentProviderOperation.newInsert(RawContacts.CONTENT_URI)
                    .withValue(RawContacts.ACCOUNT_NAME, stand.accountName)
                    .withValue(RawContacts.ACCOUNT_TYPE, stand.accountType)
                    .withValue(RawContacts.DATA_SET, stand.dataSet)
                    .withValue(RawContacts.SOURCE_ID, stand.sourceId)
                    .withValue(RawContacts.AGGREGATION_MODE, stand.aggregationMode).build()
            }
            stand.rows.forEachIndexed { index, row ->
                var bau = ContentProviderOperation.newInsert(Data.CONTENT_URI)
                bau = if (vorhanden) bau.withValue(Data.RAW_CONTACT_ID, stand.rawContactId)
                    else bau.withValueBackReference(Data.RAW_CONTACT_ID, 0)
                bau.withValue(Data.MIMETYPE, row.mime)
                row.data.forEachIndexed { i, value -> if (value != null) {
                    bau.withValue("data${i + 1}", if (row.mime == Photo.CONTENT_ITEM_TYPE && i == 14)
                        dekodierteFotos.getValue(index) else value)
                } }
                row.sync.forEachIndexed { i, value -> bau.withValue("sync${i + 1}", value) }
                bau.withValue(Data.IS_PRIMARY, if (row.primary) 1 else 0)
                bau.withValue(Data.IS_SUPER_PRIMARY, if (row.superPrimary) 1 else 0)
                ops += bau.build()
            }
            return ops
        }

        /** Ein sichtbarer Android-Kontakt wird unabhängig von seinen Konten genau einmal gesendet. */
        fun aggregiere(roh: List<AndroidKontakt>): List<AndroidKontakt> = roh.groupBy { it.contactId }
            .values.map { teile ->
                val erste = teile.first()
                val daten = teile.drop(1).fold(erste.daten) { gesamt, teil ->
                    // Der erste nichtleere Skalar bleibt erhalten, Listen werden additiv vereinigt.
                    KontaktSync.mische(teil.daten, gesamt)
                }
                AndroidKontakt(
                    lookupKey = teile.firstOrNull { it.lookupKey.isNotBlank() }?.lookupKey.orEmpty(),
                    rawContactId = teile.minOf { it.rawContactId },
                    daten = daten,
                    contactId = erste.contactId,
                    rawContactIds = teile.map { it.rawContactId }.toSet(),
                    herkuenfte = teile.flatMap { it.herkuenfte }.distinct()
                )
            }
    }
}
