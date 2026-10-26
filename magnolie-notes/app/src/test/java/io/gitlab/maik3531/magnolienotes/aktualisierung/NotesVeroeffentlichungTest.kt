package io.gitlab.maik3531.magnolienotes.aktualisierung

import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.xml.parsers.DocumentBuilderFactory

class NotesVeroeffentlichungTest {
    private val now = Instant.parse("2026-10-25T12:00:00Z")
    private val repo = "https://github.com/maik3531/Magnolie-Organizer"
    private fun asset(version: String = "1.0.20", tag: String = "v2.0.28") = buildJsonObject {
        put("name", "Magnolie-Notes-$version.apk"); put("state", "uploaded"); put("size", 5_000_000)
        put("browser_download_url", "$repo/releases/download/$tag/Magnolie-Notes-$version.apk")
    }
    private fun release(version: String = "1.0.20", tag: String = "v2.0.28") = buildJsonObject {
        put("tag_name", tag); put("html_url", "$repo/releases/tag/$tag")
        put("published_at", "2026-10-23T12:06:45Z"); put("draft", false); put("prerelease", false)
        put("assets", JsonArray(listOf(asset(version, tag))))
    }
    private fun JsonObject.changed(key: String, value: JsonElement) = JsonObject(toMutableMap().apply { put(key, value) })
    private fun check(vararg releases: JsonObject, own: String = "1.0.19") =
        NotesVeroeffentlichung.ausJson(JsonArray(releases.toList()).toString(), own, now)

    @Test fun notesAssetVersionIsIndependentOfTheDesktopTag() {
        val info = check(release())!!
        assertEquals("1.0.20", info.version); assertTrue(info.neuer)
        assertEquals("$repo/releases/tag/v2.0.28", info.releaseUrl)
        assertFalse(check(release(), own = "1.0.20")!!.neuer)
        assertFalse(check(release(), own = "1.0.21")!!.neuer)
    }

    @Test fun numericVersionOrderingAndMultiplePublicReleasesSelectTheNewestNotesAsset() {
        assertEquals("1.0.20", check(release("1.0.9"), release("1.0.20"), release("1.0.10"))!!.version)
        assertTrue(check(release("1.10.0"), own = "1.9.99")!!.neuer)
        assertTrue(check(release("2.0.0"), own = "1.99.99")!!.neuer)
    }

    @Test fun draftsPrereleasesUnpublishedAndFutureDatesCannotAdvertiseAnUpdate() {
        for ((key, value) in listOf("draft" to JsonPrimitive(true), "prerelease" to JsonPrimitive(true),
            "published_at" to JsonNull, "published_at" to JsonPrimitive("2027-01-01T00:00:00Z"),
            "published_at" to JsonPrimitive("invalid"), "draft" to JsonPrimitive("false"))) {
            assertNull(key, check(release("9.0.0").changed(key, value)))
        }
        val withoutFlag = JsonObject(release().filterKeys { it != "draft" })
        assertNull(check(withoutFlag))
        assertEquals("1.0.20", check(release("9.0.0").changed("prerelease", JsonPrimitive(true)), release())!!.version)
    }

    @Test fun desktopFilesAliasesAndCandidateNamesAreNotNotesVersionSources() {
        for (name in listOf("Magnolie-Organizer-Windows-9.0.0.exe", "Magnolie-Notes.apk",
            "Magnolie-Notes-1.0.21-unsigned.apk", "Magnolie-Notes-1.0.21-rc1.apk", "Magnolie-Notes-01.0.21.apk")) {
            val candidate = asset().changed("name", JsonPrimitive(name))
            assertNull(name, check(release().changed("assets", JsonArray(listOf(candidate)))))
        }
    }

    @Test fun releaseAndAssetMustBelongToTheOfficialPublishedSource() {
        assertNull(check(release().changed("html_url", JsonPrimitive("https://other.invalid/releases/tag/v2.0.28"))))
        for ((key, value) in listOf("state" to JsonPrimitive("new"), "size" to JsonPrimitive(0),
            "size" to JsonPrimitive("5000"), "size" to JsonPrimitive(999_999_999),
            "browser_download_url" to JsonPrimitive("https://other.invalid/Magnolie-Notes-1.0.20.apk"))) {
            assertNull(key, check(release().changed("assets", JsonArray(listOf(asset().changed(key, value))))))
        }
    }

    @Test fun missingMalformedOversizedOrUnknownMetadataNeverMeansUpToDate() {
        for (text in listOf("", "{}", "[]", "not json", "[null]", "[{\"assets\":[]}]", " ".repeat(NotesVeroeffentlichung.MAX_BYTES + 1))) {
            assertNull(NotesVeroeffentlichung.ausJson(text, "1.0.20", now))
        }
        assertNull(check(release(), own = "1.0.20-plaintext-fixture"))
        assertNull(check(release(), own = "unknown"))
        assertNull(NotesVersion.lesen("999999999999999.0.0"))
    }

    private class Connection(val body: ByteArray, val status: Int = 200,
                             val stream: InputStream = ByteArrayInputStream(body), val close: () -> Unit = {}) :
        HttpURLConnection(URL(NotesVeroeffentlichung.QUELLE)) {
        val disconnected = AtomicBoolean(false)
        override fun connect() {}
        override fun disconnect() { disconnected.set(true); close() }
        override fun usingProxy() = false
        override fun getResponseCode() = status
        override fun getContentLengthLong() = -1L
        override fun getInputStream() = stream
    }

    @Test fun boundedHttpReaderUsesThePublicApiAndClosesItsConnection() = runBlocking {
        val connection = Connection(JsonArray(listOf(release())).toString().toByteArray())
        val source = NotesVeroeffentlichung(jetzt = { now }) { url -> assertEquals(NotesVeroeffentlichung.QUELLE, url.toString()); connection }
        assertEquals("1.0.20", source.pruefen("1.0.19")!!.version)
        assertTrue(connection.disconnected.get()); assertFalse(connection.instanceFollowRedirects)
        assertEquals(5_000, connection.connectTimeout); assertEquals(5_000, connection.readTimeout)
    }

    @Test fun offlineRedirectHttpErrorsBadEncodingAndOversizedBodiesRemainFailures() = runBlocking {
        for (connection in listOf(Connection(byteArrayOf(), 302), Connection(byteArrayOf(), 403),
            Connection(byteArrayOf(), 503), Connection(byteArrayOf(0xff.toByte())),
            Connection(ByteArray(NotesVeroeffentlichung.MAX_BYTES + 1) { 32 }))) {
            try { NotesVeroeffentlichung { connection }.pruefen("1.0.20"); fail("Unusable response was accepted") }
            catch (_: IOException) { assertTrue(connection.disconnected.get()) }
        }
        try { NotesVeroeffentlichung { throw IOException("owned offline fixture") }.pruefen("1.0.20"); fail("Offline request succeeded") }
        catch (_: IOException) { }
    }

    @Test fun cancellationDisconnectsAnActiveReadAndCannotPublishALateResult() = runBlocking {
        val started = CountDownLatch(1); val closed = CountDownLatch(1)
        val stream = object : InputStream() {
            override fun read(): Int = throw IOException("owned fixture requires buffered read")
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                started.countDown(); closed.await(3, TimeUnit.SECONDS)
                throw IOException("owned cancelled read")
            }
        }
        val connection = Connection(byteArrayOf(), stream = stream, close = { closed.countDown() })
        val job = async(Dispatchers.IO) { NotesVeroeffentlichung { connection }.pruefen("1.0.20") }
        try {
            assertTrue(started.await(3, TimeUnit.SECONDS))
            job.cancel()
            assertTrue("Cancellation did not close the active request", closed.await(500, TimeUnit.MILLISECONDS))
            withTimeout(3_000) { job.join() }
            assertTrue(job.isCancelled); assertTrue(connection.disconnected.get())
        } finally { closed.countDown(); job.cancelAndJoin() }
    }

    @Test fun updateMessagesArePresentInAllTwentyAboutCatalogs() {
        val files = File("app/src/main/res").listFiles()!!.map { File(it, "about.xml") }.filter { it.isFile }
        assertEquals(20, files.size)
        val keys = setOf("about_update_checking", "about_update_available", "about_update_published",
            "about_update_unavailable", "about_update_release", "about_update_retry")
        for (file in files) {
            val nodes = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file).getElementsByTagName("string")
            val messages = (0 until nodes.length).associate { nodes.item(it).attributes.getNamedItem("name").nodeValue to nodes.item(it).textContent }
            assertTrue(file.toString(), keys.all { !messages[it].isNullOrBlank() })
            for (key in listOf("about_update_available", "about_update_published")) assertTrue(messages[key]!!.contains("%1\$s"))
        }
    }
}
