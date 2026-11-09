package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.Rule
import org.junit.rules.Timeout
import java.util.UUID
import org.threeten.bp.Instant

class BookRestoreTest {
    @get:Rule val deadline: Timeout = Timeout.seconds(30)
    private fun fixture() = JSONObject(javaClass.getResourceAsStream("/dav-book-restore.json")!!.bufferedReader().use { it.readText() })
    private fun transform(incoming: JSONObject? = null, live: JSONObject? = null): JSONObject {
        val f = fixture()
        return BookRestore.transform(incoming ?: f.getJSONObject("incoming"), live ?: f.getJSONObject("live"), UUID.fromString(f.getString("newEpoch")), Instant.parse(f.getString("restoredAt")).toEpochMilli())
    }
    private fun reject(code: String? = null, block: () -> Unit) {
        try { block(); fail("Expected rejection") } catch(e: BookRestoreException) { if(code != null) assertEquals(code,e.code) }
    }
    @Test fun matchesExactSharedMacGoldenFixtureAndDoesNotMutateOrAliasInputs() {
        val f = fixture(); val incoming = f.getJSONObject("incoming"); val live = f.getJSONObject("live")
        val beforeIncoming = BookRestore.canonical(incoming); val beforeLive = BookRestore.canonical(live)
        val result = transform(incoming,live)
        assertEquals(BookRestore.canonical(f.getJSONObject("expected")), BookRestore.canonical(result))
        result.getJSONObject("personalSync").getJSONObject("custom_entities").put("later","mutation")
        assertEquals(beforeIncoming,BookRestore.canonical(incoming)); assertEquals(beforeLive,BookRestore.canonical(live))
    }
    @Test fun actualCanonicalNormalizedBindingFixtureRetainsEpochAndQuarantine() {
        val f = JSONObject(javaClass.getResourceAsStream("/dav-book-normalized-epoch.json")!!.bufferedReader().use { it.readText() })
        val saved = f.getJSONObject("savedBinding"); val expected = transform()
        assertEquals(BookRestore.persistedEpoch(expected),BookRestore.persistedEpoch(saved))
        assertEquals(BookRestore.canonical(expected.getJSONObject("syncMetadaten").get("quarantinedDeletes")),BookRestore.canonical(saved.getJSONObject("syncMetadaten").get("quarantinedDeletes")))
    }
    @Test fun rootMetaSettingsMissingNullMalformedConflictMatrix() {
        val valid = transform(); val epoch = BookRestore.persistedEpoch(valid)
        val missingOptional = BookRestore.copy(valid); missingOptional.getJSONObject("einstellungen").getJSONObject("sync").remove("syncEpoch")
        assertEquals(epoch,BookRestore.persistedEpoch(missingOptional))
        for (path in listOf(listOf("syncEpoch"),listOf("syncMetadaten","syncEpoch"),listOf("einstellungen","sync","syncEpoch"))) {
            for (value in listOf(null,JSONObject.NULL,"", "invalid", "1-1-1-1-1",7,true,JSONObject(),JSONArray(),UUID.randomUUID().toString())) {
                val changed = BookRestore.copy(valid); var parent = changed
                for (key in path.dropLast(1)) parent = parent.getJSONObject(key)
                if(value == null) parent.remove(path.last()) else parent.put(path.last(),value)
                if (value == null && path.size == 3) assertEquals(epoch,BookRestore.persistedEpoch(changed)) else reject { BookRestore.persistedEpoch(changed) }
            }
        }
        for (key in listOf("syncMetadaten","einstellungen")) for (bad in listOf(JSONObject.NULL,"bad",true,7,JSONArray())) {
            val changed = BookRestore.copy(valid).put(key,bad); reject { BookRestore.persistedEpoch(changed) }
        }
        for (bad in listOf(JSONObject.NULL,"bad",7,JSONArray())) {
            val changed = BookRestore.copy(valid); changed.getJSONObject("einstellungen").put("sync",bad); reject { BookRestore.persistedEpoch(changed) }
        }
    }
    @Test fun newEpochCannotReuseAnyLiveOrArchiveSlotAndTimeCannotBeNegative() {
        val f = fixture()
        for (book in listOf(f.getJSONObject("incoming"),f.getJSONObject("live"))) {
            val epoch = UUID.fromString(book.getString("syncEpoch"))
            reject("invalid_epoch") { BookRestore.transform(f.getJSONObject("incoming"),f.getJSONObject("live"),epoch,0) }
        }
        reject { BookRestore.transform(f.getJSONObject("incoming"),f.getJSONObject("live"),UUID.randomUUID(),-1) }
    }
    @Test fun malformedOrUnknownQuarantineNeverSilentlyReplaced() {
        for (value in listOf(JSONObject.NULL,"bad",JSONArray(),JSONObject().put("future",JSONArray()),JSONObject().put("geloescht",JSONObject().put("unknown",JSONArray())),JSONObject().put("tombstones",JSONObject()),JSONObject().put("tombstones",JSONArray().put("invalid")))) {
            for (side in listOf("live","incoming")) {
                val f = fixture(); f.getJSONObject(side).getJSONObject("syncMetadaten").put("quarantinedDeletes",value)
                reject("unsupported_quarantine") { transform(f.getJSONObject("incoming"),f.getJSONObject("live")) }
            }
        }
    }
    @Test fun quarantineExactContentDedupIsContainerLocalAndOpaqueIdentityPreserved() {
        val f = fixture(); val incoming = f.getJSONObject("incoming")
        val entries = JSONArray().put(JSONObject().put("uid","café").put("flag",true)).put(JSONObject().put("flag",true).put("uid","café"))
            .put(JSONObject().put("uid","cafe\u0301").put("flag",true)).put(JSONObject().put("uid","café").put("flag",1))
        incoming.put("tombstones",entries).put("baumKontaktGeloescht",JSONArray().put(JSONObject().put("uid","café").put("flag",true)))
        incoming.getJSONObject("syncMetadaten").remove("quarantinedDeletes"); f.getJSONObject("live").getJSONObject("syncMetadaten").remove("quarantinedDeletes")
        val q = transform(incoming,f.getJSONObject("live")).getJSONObject("syncMetadaten").getJSONObject("quarantinedDeletes")
        assertEquals(3,q.getJSONArray("tombstones").length()); assertEquals(1,q.getJSONArray("baumKontaktGeloescht").length())
    }
    @Test fun additiveMarkersLocalEvidenceAndUnknownsArePreservedExactly() {
        val f=fixture(); val result=transform(); val meta=result.getJSONObject("syncMetadaten")
        assertEquals(true,meta.get("ersteSyncLoeschungsfrei")); assertFalse(result.has("syncAbgleichBasis")); assertFalse(result.has("syncAbgleichNachweis"))
        assertEquals(BookRestore.canonical(f.getJSONObject("live").getJSONObject("personalSync").get("custom_entities")),BookRestore.canonical(result.getJSONObject("personalSync").get("custom_entities")))
        assertEquals(BookRestore.canonical(f.getJSONObject("incoming").get("futureRoot")),BookRestore.canonical(result.get("futureRoot")))
        val cloud=meta.getJSONObject("nextcloud"); assertFalse(cloud.has("pendingCommitId")); assertFalse(cloud.has("ausstehendeTransaktion")); assertEquals(0,cloud.getJSONObject("transaktionen").length())
        assertEquals(0,result.getJSONArray("tombstones").length()); assertEquals(0,result.getJSONArray("baumKontaktGeloescht").length())
        val smsInput=fixture().getJSONObject("incoming").put("smsPlanung",JSONArray().put(JSONObject().put("status","planned").put("opaque","keep")).put(JSONObject().put("status","submitting")).put(JSONObject().put("status","sent")))
        val sms=transform(smsInput).getJSONArray("smsPlanung")
        assertEquals("paused",sms.getJSONObject(0).getString("status")); assertEquals("uncertain",sms.getJSONObject(1).getString("status")); assertEquals("sent",sms.getJSONObject(2).getString("status")); assertEquals("keep",sms.getJSONObject(0).getString("opaque"))
    }
    @Test fun publicInputPreflightRejectsCyclesNonFiniteMalformedUtf16DepthAndAggregateBytes() {
        reject { BookRestore.preflight(JSONObject().also { it.put("cycle",it) }) }
        reject { BookRestore.preflight(JSONObject().put("text","\ud800")) }
        for (number in listOf(Double.NaN,Double.POSITIVE_INFINITY)) {
            // Android's put(Object) permits construction; Gradle's JSON library may reject first.
            val nonfinite = try { JSONArray().put(number as Any) } catch (_: org.json.JSONException) { null }
            if (nonfinite != null) reject { BookRestore.preflight(nonfinite) }
        }
        reject { BookRestore.preflight(JSONObject().put("text","x".repeat(BookRestore.MAXIMUM_BYTES))) }
        val a=JSONArray(); var parent=a; repeat(65) {val child=JSONArray(); parent.put(child); parent=child}; reject {BookRestore.preflight(a)}
        assertTrue(BookRestore.preflight(JSONObject().put("unicode","é".repeat(1000)),2100)<2100)
        reject("limit") {BookRestore.preflight(JSONObject().put("a","x".repeat(600)).put("b","y".repeat(600)),1000)}
    }
    @Test fun aggregateMergedOutputBoundBeforePublicationAndDomainLimits() {
        val f=fixture(); f.getJSONObject("incoming").put("attachment","x".repeat(9*1024*1024))
        f.getJSONObject("live").getJSONObject("personalSync").put("custom_entities",JSONObject().put("large","y".repeat(9*1024*1024)))
        reject("limit") { transform(f.getJSONObject("incoming"),f.getJSONObject("live")) }
        val incoming=fixture().getJSONObject("incoming"); val notes=JSONArray(); repeat(100001) {notes.put(JSONObject())}; incoming.put("notizen",notes)
        reject("limit") {transform(incoming)}
    }
    @Test fun quarantineCountBoundAndUtf8KeyOrderingRemainDeterministic() {
        val f=fixture(); val values=JSONArray()
        repeat(100001) {values.put(JSONObject().put("uid",it.toString()))}
        f.getJSONObject("incoming").put("tombstones",values)
        reject("limit") {transform(f.getJSONObject("incoming"),f.getJSONObject("live"))}
        val keys=JSONObject().put("\ud800\udc00",1).put("\ue000",2)
        assertEquals("{\"\ue000\":2,\"\ud800\udc00\":1}",BookRestore.canonical(keys))
        val incoming=fixture().getJSONObject("incoming")
        val rows=incoming.getJSONArray("termine"); rows.getJSONObject(0).put("sync","true").put("geaendert",123)
        val transformed=transform(incoming)
        assertEquals(123,transformed.getJSONArray("termine").getJSONObject(0).getInt("geaendert"))
    }

    @Test fun typedCopiesPreserveLargeDoublesAndNumericDistinctQuarantineEntries() {
        val large=9.223372036854776E18
        for (archived in listOf(false,true)) {
            val f=fixture(); val incoming=f.getJSONObject("incoming"); val live=f.getJSONObject("live")
            val entries=JSONArray().put(JSONObject().put("uid","same").put("n",1)).put(JSONObject().put("uid","same").put("n",1.0))
            live.getJSONObject("syncMetadaten").remove("quarantinedDeletes")
            incoming.getJSONObject("syncMetadaten").remove("quarantinedDeletes")
            if(archived) {
                incoming.getJSONObject("syncMetadaten").put("quarantinedDeletes",JSONObject().put("tombstones",entries))
                incoming.put("tombstones",JSONArray())
            } else incoming.put("tombstones",entries)
            incoming.put("opaqueNumber",large)
            val result=transform(incoming,live)
            assertEquals(large,result.get("opaqueNumber")); assertEquals(java.lang.Double::class.java,result.get("opaqueNumber").javaClass)
            val output=result.getJSONObject("syncMetadaten").getJSONObject("quarantinedDeletes").getJSONArray("tombstones")
            assertEquals(2,output.length())
            assertEquals(java.lang.Integer::class.java,output.getJSONObject(0).get("n").javaClass)
            assertEquals(java.lang.Double::class.java,output.getJSONObject(1).get("n").javaClass)
            assertEquals(1,output.getJSONObject(0).get("n")); assertEquals(1.0,output.getJSONObject(1).get("n"))
        }
    }
    @Test fun rawJavaNullAndTypedNestedCopiesPreserveJsonNullWithoutAliasing() {
        val array=JSONArray().put(null as Any?).put(JSONObject.NULL).put(JSONArray().put(1).put(1.0))
        val source=JSONObject().put("unknown",array)
        BookRestore.preflight(source)
        val copied=BookRestore.copy(source); val result=copied.getJSONArray("unknown")
        assertEquals("null",BookRestore.canonical(result.opt(0))); assertEquals("null",BookRestore.canonical(result.opt(1)))
        assertEquals("[1,1.0]",BookRestore.canonical(result.getJSONArray(2)))
        result.getJSONArray(2).put(7)
        assertEquals(2,array.getJSONArray(2).length())
        assertEquals("{\"unknown\":[null,null,[1,1.0]]}",BookRestore.encode(source))
    }

}
