package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.Rule
import org.junit.rules.Timeout

class OrdinarySaveEpochPolicyTest {
    @get:Rule val deadline: Timeout = Timeout.seconds(30)
    private val epoch="12345678-1234-4234-8234-123456789abc"
    private val other="aaaaaaaa-1234-4234-8234-123456789abc"
    private fun base()=JSONObject().put("termine",JSONArray()).put("aufgaben",JSONArray()).put("kontakte",JSONArray()).put("notizen",JSONArray()).put("futureRoot",JSONObject().put("keep",7))
    private fun established()=base().put("syncEpoch",epoch).put("syncMetadaten",JSONObject().put("syncEpoch",epoch))
    private fun slots(book: JSONObject): List<String?> = listOf(listOf("syncEpoch"),listOf("syncMetadaten","syncEpoch"),listOf("einstellungen","sync","syncEpoch")).map {path ->
        var current: Any=book
        for(key in path) {val parent=current as? JSONObject; if(parent==null || !parent.has(key)) return@map null; current=parent.get(key)}
        BookRestore.canonical(current)
    }
    private fun reject(block: () -> Unit) {try {block(); fail("Expected rejection")} catch(_: BookRestoreException) {}}
    @Test fun sharedSwiftSlotMatrixPreservesAbsentNullMalformedUnknownValuesAndNeverPromotes() {
        val vectors=mutableListOf(base())
        for(value in listOf("",JSONObject.NULL,"invalid",7,true,JSONObject().put("invalid",true),epoch)) {
            vectors+=base().put("syncEpoch",value)
            vectors+=base().put("syncMetadaten",JSONObject().put("syncEpoch",value))
            vectors+=base().put("einstellungen",JSONObject().put("sync",JSONObject().put("syncEpoch",value)))
        }
        for(settings in listOf(JSONObject(),JSONObject().put("sync",JSONObject().put("syncEpoch",epoch)),JSONObject().put("sync",JSONObject().put("syncEpoch",other)),JSONObject().put("sync",JSONObject().put("syncEpoch",JSONObject.NULL)),JSONObject().put("sync","invalid"),"invalid",JSONObject.NULL,JSONObject().put("sync",JSONObject.NULL))) vectors+=established().put("einstellungen",settings)
        for(value in listOf(JSONObject.NULL,"invalid",7)) vectors+=base().put("syncMetadaten",value)
        vectors+=base().put("syncEpoch",epoch).put("syncMetadaten",JSONObject().put("syncEpoch",other))
        for(original in vectors) {
            val policy=OrdinarySaveEpochPolicy(original.toString())
            val edited=BookRestore.copy(original).put("syncEpoch",other).put("syncMetadaten",JSONObject().put("syncEpoch",other).put("futureMeta",3))
                .put("einstellungen",JSONObject().put("sync",JSONObject().put("syncEpoch",other).put("futureSync",4)))
            if(policy.classification==OrdinarySaveEpochPolicy.Classification.PROTECTED) reject {policy.prepare(edited.toString())}
            else {
                val result=JSONObject(policy.prepare(edited.toString()))
                assertEquals(slots(original),slots(result)); reject {BookRestore.persistedEpoch(result)}
                assertEquals(3,result.getJSONObject("syncMetadaten").getInt("futureMeta"))
                assertEquals(4,result.getJSONObject("einstellungen").getJSONObject("sync").getInt("futureSync"))
                assertEquals(BookRestore.canonical(result),BookRestore.canonical(JSONObject(policy.prepare(result.toString()))))
            }
        }
    }
    @Test fun malformedOptionalContainersCanRepairWithoutGrantingAuthority() {
        for(settings in listOf("invalid",JSONObject.NULL,JSONObject().put("sync","invalid"),JSONObject().put("sync",JSONObject.NULL))) {
            val original=established().put("einstellungen",settings)
            reject {BookRestore.persistedEpoch(original)}
            val policy=OrdinarySaveEpochPolicy(original.toString())
            assertEquals(OrdinarySaveEpochPolicy.Classification.PROTECTED,policy.classification)
            val repaired=BookRestore.copy(original).put("einstellungen",JSONObject().put("sync",JSONObject().put("future",4)))
            val result=JSONObject(policy.prepare(repaired.toString()))
            assertEquals(slots(original),slots(result)); assertEquals(policy.protectedEpoch,BookRestore.persistedEpoch(result))
        }
    }
    @Test fun establishedCannotDropChangeOrMoveEpochAndCaseIsPinned() {
        val original=established().put("einstellungen",JSONObject().put("sync",JSONObject().put("syncEpoch",epoch.uppercase())))
        val policy=OrdinarySaveEpochPolicy(original.toString())
        val dropped=BookRestore.copy(original); dropped.remove("syncEpoch"); reject {policy.prepare(dropped.toString())}
        val changed=BookRestore.copy(original); changed.getJSONObject("syncMetadaten").put("syncEpoch",other); reject {policy.prepare(changed.toString())}
        val normalized=BookRestore.copy(original).put("syncEpoch",epoch.uppercase()); normalized.getJSONObject("einstellungen").getJSONObject("sync").put("syncEpoch",epoch)
        assertEquals(slots(original),slots(JSONObject(policy.prepare(normalized.toString()))))
    }
    @Test fun explicitNullIsNotMissingAndMalformedCandidateCannotDiscardPinnedSlot() {
        val original=base().put("syncEpoch",JSONObject.NULL).put("syncMetadaten",JSONObject().put("syncEpoch",JSONObject().put("unknown",true)))
        val policy=OrdinarySaveEpochPolicy(original.toString())
        val candidate=base().put("syncMetadaten",JSONObject().put("unrelated","keep"))
        val result=JSONObject(policy.prepare(candidate.toString()))
        assertTrue(result.has("syncEpoch")); assertSame(JSONObject.NULL,result.get("syncEpoch")); assertEquals(slots(original),slots(result))
        reject {policy.prepare(base().put("syncMetadaten","bad").toString())}
    }
    @Test fun absentCannotMintEpochAndOversizeCandidateFailsBeforeSerialization() {
        val policy=OrdinarySaveEpochPolicy(null)
        assertEquals(OrdinarySaveEpochPolicy.Classification.ABSENT,policy.classification)
        val result=JSONObject(policy.prepare(established().put("einstellungen",JSONObject().put("sync",JSONObject().put("syncEpoch",epoch))).toString()))
        assertEquals(listOf(null,null,null),slots(result)); reject {BookRestore.persistedEpoch(result)}
        reject {policy.prepare(base().put("large","x".repeat(BookRestore.MAXIMUM_BYTES)).toString())}
    }
    @Test fun policyOutputAndPinnedSlotObjectsDoNotNarrowLargeNumbersOrCollapseKinds() {
        // Supply actual JSON literals; JSONObject.toString on AOSP is the separately scoped
        // existing Vault defect and must not be used to construct this regression's input.
        val loaded="""{"termine":[],"aufgaben":[],"kontakte":[],"notizen":[],"syncEpoch":{"large":9.223372036854776E18,"kinds":[1,1.0]},"unknown":9.223372036854776E18}"""
        val policy=OrdinarySaveEpochPolicy(loaded)
        val before=JSONObject(loaded)
        val output=policy.prepare(loaded)
        val actual=JSONObject(output)
        assertEquals(BookRestore.canonical(before),BookRestore.canonical(actual))
        assertEquals(before.get("unknown"),actual.get("unknown"))
        val number=actual.getJSONObject("syncEpoch").get("large")
        assertEquals(before.getJSONObject("syncEpoch").get("large"),number)
        assertEquals("[1,1.0]",BookRestore.canonical(actual.getJSONObject("syncEpoch").getJSONArray("kinds")))
        assertEquals(output,policy.prepare(output))
    }

}
