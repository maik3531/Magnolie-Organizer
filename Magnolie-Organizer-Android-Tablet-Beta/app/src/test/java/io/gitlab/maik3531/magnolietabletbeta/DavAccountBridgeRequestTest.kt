package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DavAccountBridgeRequestTest {
    private val revision = "a".repeat(64)
    private fun request(command: String) = JSONObject().put("cmd", command).put("session", "page-session").put("revision", revision)
    private fun save() = request("baum_briefkasten_speichern").put("expectedRevision", revision)
        .put("kontoArt", "nextcloud").put("davAktiv", true).put("briefkastenAktiv", false)
        .put("url", "https://cloud.example.invalid").put("benutzer", "synthetic")
        .put("anwendungskennwort", "synthetic-app-password").put("kennwortLoeschen", false)
    private fun rejected(value: JSONObject) {
        try { DavAccountBridgeRequest.parse(value); fail("Invalid account envelope accepted") }
        catch (expected: DavAccountException) { assertTrue(expected.code in setOf("invalid_request", "invalid_config")) }
    }
    @Test fun statusAndSourceStatusAcceptOnlyBoundedOptionalCorrelation() {
        for (cmd in listOf("baum_briefkasten_status", "eds_status")) {
            assertEquals(cmd, DavAccountBridgeRequest.parse(request(cmd)).command)
            assertEquals("correlation", DavAccountBridgeRequest.parse(request(cmd).put("requestId", "correlation")).requestId)
            rejected(request(cmd).put("requestId", "")); rejected(request(cmd).put("requestId", JSONObject.NULL))
            rejected(request(cmd).put("requestId", 3)); rejected(request(cmd).put("requestId", "ü".repeat(513)))
        }
    }
    @Test fun savesHaveStrictActualTypesAndPreserveSeparateAccountRevision() {
        val parsed = DavAccountBridgeRequest.parse(save().put("requestId", "save"))
        assertEquals("baumBriefkastenGespeichert", parsed.callback)
        assertEquals(revision, parsed.expectedRevision)
        assertTrue(parsed.configuration!!.davEnabled)
        assertEquals("synthetic-app-password", parsed.applicationPassword)
        for (field in listOf("davAktiv", "briefkastenAktiv", "kennwortLoeschen")) {
            rejected(save().put(field, "true")); rejected(save().put(field, 1)); rejected(save().put(field, JSONObject.NULL))
        }
        for (field in listOf("kontoArt", "url", "benutzer", "anwendungskennwort", "expectedRevision")) {
            rejected(save().put(field, JSONObject.NULL)); rejected(save().put(field, 1)); rejected(save().also { it.remove(field) })
        }
    }
    @Test fun testsRequireAccountRevisionAndMcpTestCorrelation() {
        for (cmd in listOf("baum_briefkasten_pruefen", "baum_dav_pruefen")) {
            val input = request(cmd).put("expectedRevision", revision).put("requestId", "test")
            assertTrue(DavAccountBridgeRequest.parse(input).discovery)
            for (bad in listOf("", "A".repeat(64), "a".repeat(63), "a".repeat(65), "../secret"))
                rejected(request(cmd).put("expectedRevision", bad).put("requestId", "test"))
            rejected(request(cmd).put("requestId", "test"))
        }
        rejected(request("baum_dav_pruefen").put("expectedRevision", revision))
        assertNull(DavAccountBridgeRequest.parse(request("baum_briefkasten_pruefen").put("expectedRevision", revision)).requestId)
    }
    @Test fun unknownFieldsAndCoercedSessionAuthorityAreRejected() {
        rejected(save().put("password", "must-not-be-accepted"))
        rejected(request("eds_status").put("daten", JSONObject()))
        rejected(request("eds_status").put("session", 7))
        rejected(request("eds_status").put("revision", false))
        rejected(save().put("kontoArt", "icloud-private-credentials"))
        rejected(save().put("anwendungskennwort", "x".repeat(16385)))
    }
    @Test fun unavailableServiceNeverInventsProviderSnapshotOrRevision() {
        for (cmd in DavAccountBridgeRequest.commands) {
            val failed = DavAccountBridgeRequest.failure(cmd,"request",null,"secret_service_unavailable")
            assertFalse(failed.getBoolean("ok"))
            assertEquals("request",failed.getString("requestId"))
            for (absent in listOf("kalender","adressbuecher","alleKalender","alleAdressbuecher","nextcloud","revision","server","benutzer"))
                assertFalse("Unavailable service fabricated $absent",failed.has(absent))
            if (cmd == "baum_briefkasten_speichern") assertFalse(failed.getBoolean("persisted"))
        }
    }
    @Test fun discoveryFailuresPreserveActualCachedSourcesWithoutClaimingFullSync() {
        val calendar = DavCollection("nextcloud-calendar:one","Synthetic calendar",
            java.net.URI("https://cloud.example.invalid/calendar/"),DavKind.CALENDAR,true,null)
        val status = DavAccountStatus(null,false,revision,"configured","none",listOf(calendar),emptyList(),true)
        val sources = DavAccountBridgeRequest.sources(status,"source-query")
        assertTrue(sources.getBoolean("verfuegbar"))
        assertFalse(sources.getBoolean("systemAccountSyncImplemented"))
        assertEquals(calendar.uid,sources.getJSONArray("alleKalender").getJSONObject(0).getString("uid"))
        val failed = DavAccountBridgeRequest.failure("eds_status","failed-query",status,"conflict")
        assertFalse(failed.getBoolean("ok"))
        assertEquals(calendar.uid,failed.getJSONArray("kalender").getJSONObject(0).getString("uid"))
        assertEquals(revision,failed.getJSONObject("nextcloud").getString("revision"))
    }

}
