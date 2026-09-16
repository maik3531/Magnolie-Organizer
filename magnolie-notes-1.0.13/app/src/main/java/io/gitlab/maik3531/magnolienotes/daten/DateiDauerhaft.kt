package io.gitlab.maik3531.magnolienotes.daten

import java.io.File
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

/** Fail closed: a rename is not durably acknowledged unless its directory is synced. */
internal fun synchronisiereOrdner(ordner: File) {
    FileChannel.open(ordner.toPath(), StandardOpenOption.READ).use { it.force(true) }
}
