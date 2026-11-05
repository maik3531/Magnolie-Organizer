package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.Ablage

/** Local saved/unlocked book evidence, never a packet, cached preference or
 * substitute for Android media consent. New recovery operations capture again;
 * an observed lock/failed save cannot revive this old permit. */
internal class NativeGalleryTrashBookPermit private constructor(private val documents: Ablage,
    private val unlocked: () -> Boolean) {
    private val book = documents.bestand.value
    private val saved = documents.personalActorSavedBookState() ?: fail()
    val trashEnabled = book.papierkorbEinstellungen.an
    val retentionDays = book.papierkorbEinstellungen.tage
    private var revoked = false

    init {
        if (retentionDays !in setOf(0, 7, 30, 90, 365)) fail()
        requireCurrent()
    }

    @Synchronized fun requireCurrent() {
        try {
            if (revoked || !unlocked() || documents.bestand.value !== book || documents.personalActorSavedBookState() != saved) fail()
        } catch (error: Exception) { revoked = true; throw error }
    }

    companion object {
        fun capture(documents: Ablage, unlocked: () -> Boolean) = NativeGalleryTrashBookPermit(documents, unlocked)
        private fun fail(): Nothing = throw PhotoFolderScopeError("gallery_trash_current_saved_unlocked_book_required")
    }
}
