package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AttachmentLaunchPolicyTest {
    private val uri = "https://example.test/files/Test%20document.pdf?download=1&part=a%2Fb#page=2"
    private fun message(target: String = uri) = JSONObject().put("cmd", "sozial").put("dienst", "custom")
        .put("aktionArt", "url").put("wert", target).put("aktionZiel", target).put("land", "Deutschland")
        .put("requestId", "open-1").put("session", "page-1").put("revision", "book-1")
    private fun item(target: String = uri, local: Boolean = false) = JSONObject().put("id", "attachment-1")
        .put("uri", target).put("anbieter", "Web").put("localOnly", local)
    private fun book(vararg attachments: JSONObject) = JSONObject().put("termine", JSONArray()
        .put(JSONObject().put("id", "event-1").put("kalenderAnhaenge", JSONArray(attachments.toList()))))
    private fun rejected(block: () -> Unit) {
        try { block(); fail("Unsafe attachment launch accepted") }
        catch (_: IllegalArgumentException) {} catch (_: IllegalStateException) {}
    }

    @Test fun exactSavedHttpsAttachmentPreservesAllEscapesQueryAndFragment() {
        val request = AttachmentLaunchRequest.parse(message())
        assertEquals(uri, request.uri)
        assertEquals(uri, AttachmentLaunchPolicy.savedTarget(request, book(item())))
        assertEquals("page-1", request.session); assertEquals("book-1", request.revision)
    }

    @Test fun sharedCommandCannotEnableUnrelatedSocialPhoneMailOrProcessHandlers() {
        for (value in listOf(message().put("dienst", "telegram"), message().put("aktionArt", "command"),
            message().put("cmd", "mail"), message().put("aktionZiel", "https://other.test"),
            message().put("process", "/bin/sh"), message().put("localOnly", false),
            message().put("requestId", false), message().also { it.remove("revision") }))
            rejected { AttachmentLaunchRequest.parse(value) }
    }

    @Test fun schemesCredentialsInvalidPortsAndControlsCannotReachAndroid() {
        for (target in listOf("http://example.test", "file:///tmp/document", "content://contacts/1", "javascript:alert(1)",
            "intent://example.test", "https://user:secret@example.test/file", "https://example.test:0/file", "https://example.test:65536/file",
            "https://example.test/path\nheader", "https://example.test/back\\slash", "https://example.test/%0d%0a", "https://example.test/%2500",
            "https://example.test/%255c", "https://example.test/%xx", "https:///no-host", "https://example.test/a b"))
            rejected { AttachmentLaunchPolicy.https(target) }
    }

    @Test fun ExplicitLocalHttpsAndPunycodeHostsNeedNoNetworkProbe() {
        for (target in listOf("https://localhost:8443/document", "https://192.168.1.5/document", "https://[::1]:8443/document", "https://xn--bcher-kva.example/document"))
            assertEquals(target, AttachmentLaunchPolicy.https(target))
    }

    @Test fun localOnlyUnknownAndDavAttachmentsRemainBlockedEvenWithHttps() {
        val request = AttachmentLaunchRequest.parse(message())
        rejected { AttachmentLaunchPolicy.savedTarget(request, book(item(local = true))) }
        rejected { AttachmentLaunchPolicy.savedTarget(request, book(item().put("anbieter", "unbekannt"))) }
        rejected { AttachmentLaunchPolicy.savedTarget(request, book(item().also { it.remove("localOnly") })) }
        for (target in listOf("https://example.test/remote.php/dav/files/file", "https://example.test/webdav/doc"))
            rejected { AttachmentLaunchPolicy.https(target) }
    }

    @Test fun unsavedUriAndMixedLocalOnlyBindingsDoNotBorrowOtherAttachmentsAuthority() {
        val request = AttachmentLaunchRequest.parse(message())
        rejected { AttachmentLaunchPolicy.savedTarget(request, book(item("https://other.test"))) }
        rejected { AttachmentLaunchPolicy.savedTarget(request, book()) }
        rejected { AttachmentLaunchPolicy.savedTarget(request, book(item(), item(local = true))) }
        assertEquals(uri, AttachmentLaunchPolicy.savedTarget(request, book(item(), item())))
    }

    @Test fun failedHandoffIsNotReportedAsOpenedOrDownloaded() {
        val request = AttachmentLaunchRequest.parse(message())
        val failure = request.reply(false, "handler_unavailable")
        assertFalse(failure.getBoolean("ok")); assertEquals("handler_unavailable", failure.getString("reason"))
        assertEquals("open-1", failure.getString("requestId")); assertEquals("book-1", failure.getString("revision"))
        assertFalse(request.reply(true).has("downloaded")); assertFalse(request.reply(true).has("saved"))
    }

    @Test fun overlongUrlsAndUnboundedRequestIdentifiersAreRejected() {
        rejected { AttachmentLaunchPolicy.https("https://example.test/" + "x".repeat(8192)) }
        rejected { AttachmentLaunchRequest.parse(message().put("requestId", "x".repeat(1025))) }
    }
}
