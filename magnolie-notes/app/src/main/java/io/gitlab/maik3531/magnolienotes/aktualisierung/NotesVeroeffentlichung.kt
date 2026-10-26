package io.gitlab.maik3531.magnolienotes.aktualisierung

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.*
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.time.Instant
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

internal data class NotesVersionsInfo(val version: String, val releaseUrl: String, val neuer: Boolean)

internal class NotesVersion private constructor(val major: Int, val minor: Int, val patch: Int) : Comparable<NotesVersion> {
    override fun compareTo(other: NotesVersion): Int = compareValuesBy(this, other, NotesVersion::major, NotesVersion::minor, NotesVersion::patch)
    override fun toString(): String = "$major.$minor.$patch"
    companion object {
        fun lesen(value: String): NotesVersion? {
            val match = Regex("(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})").matchEntire(value) ?: return null
            return NotesVersion(match.groupValues[1].toInt(), match.groupValues[2].toInt(), match.groupValues[3].toInt())
        }
    }
}

/** Only published Notes APK assets identify a Notes version; desktop tags never do. */
internal class NotesVeroeffentlichung(
    private val jetzt: () -> Instant = Instant::now,
    private val verbinde: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection }
) {
    suspend fun pruefen(installiert: String): NotesVersionsInfo? = withContext(Dispatchers.IO) {
        val text = try {
            withTimeout(12_000) { laden() }
        } catch (error: TimeoutCancellationException) {
            currentCoroutineContext().ensureActive()
            throw IOException("notes_version_unavailable", error)
        }
        currentCoroutineContext().ensureActive()
        ausJson(text, installiert, jetzt())
    }

    private suspend fun laden(): String = suspendCancellableCoroutine { continuation ->
        val connection = verbinde(URL(QUELLE))
        continuation.invokeOnCancellation { connection.disconnect() }
        if (!continuation.isActive) return@suspendCancellableCoroutine
        try {
            connection.connectTimeout = 5_000
            connection.readTimeout = 5_000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            connection.setRequestProperty("User-Agent", "Magnolie-Notes-Version-Check")
            if (!continuation.isActive) throw CancellationException()
            if (connection.responseCode != HttpURLConnection.HTTP_OK || connection.contentLengthLong > MAX_BYTES) throw IOException("notes_version_unavailable")
            val bytes = connection.inputStream.use { input ->
                val result = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    if (!continuation.isActive) throw CancellationException()
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (result.size() + count > MAX_BYTES) throw IOException("notes_version_too_large")
                    result.write(buffer, 0, count)
                }
                result.toByteArray()
            }
            val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
            if (continuation.isActive) continuation.resume(text)
        } catch (error: Exception) {
            if (continuation.isActive) continuation.resumeWithException(error)
        } finally { connection.disconnect() }
    }

    companion object {
        const val QUELLE = "https://api.github.com/repos/maik3531/Magnolie-Organizer/releases?per_page=10"
        const val MAX_BYTES = 1_048_576
        private const val REPO = "https://github.com/maik3531/Magnolie-Organizer"
        private val json = Json { ignoreUnknownKeys = true }

        fun ausJson(text: String, installiert: String, jetzt: Instant = Instant.now()): NotesVersionsInfo? {
            val own = NotesVersion.lesen(installiert) ?: return null
            if (text.toByteArray(Charsets.UTF_8).size > MAX_BYTES) return null
            val releases = try { json.parseToJsonElement(text) as? JsonArray }
                catch (_: SerializationException) { null } catch (_: IllegalArgumentException) { null } ?: return null
            if (releases.size > 10) return null
            val candidates = releases.flatMap { element ->
                val release = element as? JsonObject ?: return@flatMap emptyList()
                if (release.boolean("draft") != false || release.boolean("prerelease") != false) return@flatMap emptyList()
                val tag = release.string("tag_name") ?: return@flatMap emptyList()
                if (!Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,127}").matches(tag)) return@flatMap emptyList()
                val page = "$REPO/releases/tag/$tag"
                if (release.string("html_url") != page) return@flatMap emptyList()
                val published = runCatching { Instant.parse(release.string("published_at")) }.getOrNull()
                    ?: return@flatMap emptyList()
                if (published < Instant.EPOCH || published > jetzt) return@flatMap emptyList()
                val assets = release["assets"] as? JsonArray ?: return@flatMap emptyList()
                if (assets.size > 100) return@flatMap emptyList()
                assets.mapNotNull { assetElement ->
                    val asset = assetElement as? JsonObject ?: return@mapNotNull null
                    val name = asset.string("name") ?: return@mapNotNull null
                    if (!name.startsWith("Magnolie-Notes-") || !name.endsWith(".apk")) return@mapNotNull null
                    val version = NotesVersion.lesen(name.removePrefix("Magnolie-Notes-").removeSuffix(".apk")) ?: return@mapNotNull null
                    val size = (asset["size"] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull ?: return@mapNotNull null
                    if (size !in 1L..134_217_728L || asset.string("state") != "uploaded" ||
                        asset.string("browser_download_url") != "$REPO/releases/download/$tag/$name") return@mapNotNull null
                    version to page
                }
            }
            val newest = candidates.maxByOrNull { it.first } ?: return null
            return NotesVersionsInfo(newest.first.toString(), newest.second, newest.first > own)
        }

        private fun JsonObject.string(name: String): String? = (this[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
        private fun JsonObject.boolean(name: String): Boolean? = (this[name] as? JsonPrimitive)?.takeUnless { it.isString }?.booleanOrNull
    }
}
