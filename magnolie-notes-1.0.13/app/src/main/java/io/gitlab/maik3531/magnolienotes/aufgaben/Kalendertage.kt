package io.gitlab.maik3531.magnolienotes.aufgaben

import java.time.LocalDate

internal object Kalendertage {
    fun bis(datum: String, heute: LocalDate = LocalDate.now()): Int? =
        runCatching { (LocalDate.parse(datum).toEpochDay() - heute.toEpochDay()).toInt() }.getOrNull()
}
