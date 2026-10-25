package io.gitlab.maik3531.magnolienotes.daten

/** Creation provenance is independent of the last editor, transport or import source. */
internal object EintragsUrsprung {
    const val FORMAT = 14
    private val apps = setOf("notes", "organizer")
    fun bekannt(value: String?) = value?.takeIf { it in apps }.orEmpty()
    fun erhalten(lokal: String?, fern: String?) = bekannt(lokal).ifEmpty { bekannt(fern) }
}
