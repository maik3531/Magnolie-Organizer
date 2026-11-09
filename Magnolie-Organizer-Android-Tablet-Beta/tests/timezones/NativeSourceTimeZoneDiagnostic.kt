package io.gitlab.maik3531.magnolietabletbeta

import java.io.File

/** Offline mirror of the exact native check. No installed Android/runtime claim. */
fun main(args: Array<String>) {
    require(args.size == 1)
    val assets = File(args.single())
    val result = NativeCalendarSmoke.sourceTimeZoneCases { path -> File(assets, path).readBytes() }
    check(result.getInt("cases") == 3 && result.getInt("negativeCases") == 6 && result.getInt("retainedRawLines") > 0)
    var rejected = false
    try { NativeCalendarSmoke.sourceTimeZoneCases { path -> File(assets, path).readBytes() + byteArrayOf(0) } }
    catch (_: IllegalStateException) { rejected = true }
    check(rejected) { "Native source timezone checker accepted a changed fixture checksum" }
    println(result)
}
