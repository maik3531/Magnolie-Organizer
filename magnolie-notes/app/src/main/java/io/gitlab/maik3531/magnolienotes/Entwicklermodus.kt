package io.gitlab.maik3531.magnolienotes

import android.content.Context
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.io.File

/** Installation-local options; exported content never enables diagnosis remotely. */
class Entwicklermodus(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = context.applicationContext.getSharedPreferences("magnolie_developer", Context.MODE_PRIVATE)
    private val file = File(context.applicationContext.filesDir, "diagnostics/wlan-debug.jsonl")
    private var versionClicks = 0
    val an: Boolean get() = prefs.getBoolean("enabled", false)
    val wlan: Boolean get() = an && prefs.getBoolean("wifi", false)
    fun aktivieren() { prefs.edit().putBoolean("enabled", true).commit() }
    fun versionAngeklickt(): Boolean {
        if (!an && ++versionClicks >= 10) { aktivieren(); versionClicks = 0 }
        return an
    }
    fun deaktivieren() { prefs.edit().putBoolean("enabled", false).putBoolean("wifi", false).commit(); versionClicks = 0 }
    fun wlanSetzen(value: Boolean) { check(an); prefs.edit().putBoolean("wifi", value).commit() }

    fun ereignis(stage: String, transport: String, failure: Boolean = false) = synchronized(SPERRE) {
        if (!wlan || stage !in STUFEN || transport !in setOf("wifi", "bluetooth")) return@synchronized
        val event = buildJsonObject {
            put("time_ms", JsonPrimitive(System.currentTimeMillis())); put("stage", JsonPrimitive(stage))
            put("transport", JsonPrimitive(transport)); put("failure", JsonPrimitive(failure))
        }
        runCatching {
            file.parentFile?.mkdirs()
            val old = if (file.isFile && file.length() <= 65536) file.readLines().takeLast(127) else emptyList()
            file.writeText((old + event.toString()).joinToString("\n", postfix = "\n"))
        }
    }

    fun bericht(mitAbsturz: Boolean = false): JsonObject = synchronized(SPERRE) {
        check(wlan) { "developer_wifi_disabled" }
        val entries = runCatching {
            if (file.isFile && file.length() <= 65536) file.readLines().takeLast(128)
                .map { kotlinx.serialization.json.Json.parseToJsonElement(it) } else emptyList()
        }.getOrDefault(emptyList())
        buildJsonObject {
            put("format", JsonPrimitive(1)); put("app_version", JsonPrimitive(BuildConfig.VERSION_NAME))
            put("events", JsonArray(entries))
            if (mitAbsturz) {
                val crash = runCatching {
                    val source = Absturzberichte.bericht(appContext) ?: return@runCatching null
                    source.inputStream().use { input ->
                        val buffer = ByteArray(16_385)
                        var length = 0
                        while (length < buffer.size) {
                            val read = input.read(buffer, length, buffer.size - length)
                            if (read <= 0) break
                            length += read
                        }
                        val masked = DiagnoseMaskierung.maskiere(String(buffer, 0, minOf(length, 16_384), Charsets.UTF_8)).toByteArray(Charsets.UTF_8)
                        Pair(String(masked, 0, minOf(masked.size, 16_384), Charsets.UTF_8), length > 16_384 || masked.size > 16_384)
                    }
                }.getOrNull()
                put("crash_report", buildJsonObject {
                    put("available", JsonPrimitive(crash != null))
                    put("text", JsonPrimitive(crash?.first.orEmpty()))
                    put("truncated", JsonPrimitive(crash?.second ?: false))
                })
            }
        }
    }

    companion object {
        const val ABSTURZ_DIAGNOSE_VERSION = 13
        private val SPERRE = Any()
        private val STUFEN = setOf("pair_begin", "pair_confirmed", "authenticating", "secure_ready", "online", "closed", "failed")
    }
}
