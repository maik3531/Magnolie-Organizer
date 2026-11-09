package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Pins loaded slots; never migrates a book or grants restore/sync admission. */
internal class OrdinarySaveEpochPolicy(loadedPlain: String?) {
    enum class Classification { ABSENT, LEGACY, PROTECTED }
    val classification: Classification
    val protectedEpoch: UUID?
    private val slots: List<Any?>
    private val paths = listOf(listOf("syncEpoch"),listOf("syncMetadaten","syncEpoch"),listOf("einstellungen","sync","syncEpoch"))
    init {
        val book = loadedPlain?.let(::parseBook) ?: JSONObject()
        protectedEpoch = protected(book)
        classification = if (loadedPlain == null) Classification.ABSENT else if (protectedEpoch != null) Classification.PROTECTED else Classification.LEGACY
        slots = paths.map { path ->
            var current: Any = book
            for (key in path) {
                val parent = current as? JSONObject
                if (parent == null || !parent.has(key)) return@map null
                current = parent.get(key)
            }
            current
        }
    }
    private fun parseBook(text: String): JSONObject {
        BookRestore.boundedText(text)
        val book = parseObject(text)
        BookRestore.preflight(book)
        for (key in listOf("termine","aufgaben","kontakte","notizen")) {
            val array = book.opt(key) as? JSONArray ?: throw BookRestoreException("invalid_input")
            if (array.length() > 100_000) throw BookRestoreException("limit")
            for (i in 0 until array.length()) if (array.opt(i) !is JSONObject) throw BookRestoreException("invalid_input")
        }
        if (listOf("magnolie","verfahren","salz","dekDaten","datenNonce","nonce").any(book::has)) throw BookRestoreException("invalid_input")
        return book
    }
    private fun protected(book: JSONObject): UUID? {
        val epoch = BookRestore.uuid(book.opt("syncEpoch")) ?: return null
        val meta = book.opt("syncMetadaten") as? JSONObject ?: return null
        if (BookRestore.uuid(meta.opt("syncEpoch")) != epoch) return null
        val settings = book.opt("einstellungen") as? JSONObject
        val sync = settings?.opt("sync") as? JSONObject
        if (sync?.has("syncEpoch") == true && BookRestore.uuid(sync.opt("syncEpoch")) != epoch) return null
        return epoch
    }
    fun prepare(candidate: String): String {
        val book = parseBook(candidate)
        if (classification == Classification.PROTECTED && protected(book) != protectedEpoch) throw BookRestoreException("epoch_changed")
        fun restore(parent: JSONObject, path: List<String>, offset: Int, value: Any?) {
            val key = path[offset]
            if (offset == path.lastIndex) { if (value == null) parent.remove(key) else parent.put(key,value); return }
            if (!parent.has(key) && value == null) return
            val child = parent.opt(key) as? JSONObject
            if (child == null) {
                if (value == null) return
                throw BookRestoreException("malformed_epoch_container")
            }
            restore(child,path,offset+1,value)
        }
        for ((index,path) in paths.withIndex()) {
            // Clone pinned objects before inserting so repeated calls cannot mutate policy state.
            val value = slots[index]
            val copied = value?.let(BookRestore::copyValue)
            restore(book,path,0,copied)
        }
        if (classification == Classification.PROTECTED) {
            if (protected(book) != protectedEpoch) throw BookRestoreException("epoch_changed")
        } else {
            val valid = try { BookRestore.persistedEpoch(book); true } catch (_: BookRestoreException) { false }
            if (valid) throw BookRestoreException("epoch_promotion")
        }
        BookRestore.preflight(book)
        return BookRestore.encode(book).also(::parseBook)
    }
}
