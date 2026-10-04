package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.time.LocalDate

/** Read-only projection of the paired Organizer's existing calendar settings. */
@Serializable
data class ZeitKalender(
    val enabled: Boolean = false,
    val country: String = "",
    val regions: Set<String> = emptySet(),
    val holidays: List<ZeitFeiertag> = emptyList()
) {
    fun validate(): ZeitKalender {
        require(country.isEmpty() && !enabled || Regex("[A-Z]{2}").matches(country))
        require(regions.size <= 64 && regions.all { it.length in 1..64 })
        require(holidays.size <= 2048)
        holidays.forEach {
            require(Regex("[A-Z]{2}").matches(it.country) && it.name.length in 1..160)
            require(it.regions.size <= 64 && it.regions.all { value -> value.length in 1..64 })
            require(LocalDate.parse(it.date).toString() == it.date)
        }
        return this
    }

    fun names(date: LocalDate): List<String> {
        if (!enabled) return emptyList()
        fun normalized(value: String): String = value.trim().uppercase(java.util.Locale.ROOT).let {
            if ('-' in it) it else "$country-$it"
        }
        val selected = regions.map(::normalized).toSet()
        return holidays.filter { it.country == country && it.date == date.toString() &&
            (selected.isEmpty() || it.nationwide || it.regions.any { value -> normalized(value) in selected }) }
            .map { it.name }.distinct()
    }
}

@Serializable
data class ZeitFeiertag(val date: String, val name: String, val country: String,
                       val nationwide: Boolean = false, val regions: Set<String> = emptySet())
