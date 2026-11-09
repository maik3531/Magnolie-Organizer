package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SavedBookEpochExpectationTest {
    private fun base()=JSONObject().put("version",6).put("syncEpoch","")
        .put("syncMetadaten",JSONObject().put("syncEpoch","").put("future",7))
        .put("futureRoot",JSONObject().put("keep",JSONArray().put("exact")))
    private fun raw()=base().also {it.remove("syncEpoch");it.getJSONObject("syncMetadaten").remove("syncEpoch")}
    private fun equal(a:JSONObject,b:JSONObject)=BookRestore.canonical(a)==BookRestore.canonical(b)
    @Test fun onlyTwoEmptyPlaceholdersCanBeAbsentWithoutMutatingEitherInput() {
        val ui=base();val disk=raw();val beforeUI=BookRestore.canonical(ui);val beforeDisk=BookRestore.canonical(disk)
        val expected=SavedBookEpochExpectation.nativeBook(ui,disk)
        assertTrue(equal(expected,disk));assertEquals(beforeUI,BookRestore.canonical(ui));assertEquals(beforeDisk,BookRestore.canonical(disk))
        expected.getJSONObject("futureRoot").getJSONArray("keep").put("changed clone")
        assertEquals(beforeUI,BookRestore.canonical(ui));assertEquals(beforeDisk,BookRestore.canonical(disk))
    }
    @Test fun genuineAuthorityAndEveryNonemptyOrNonstringValueRemainStrict() {
        for(value in listOf("12345678-1234-4234-8234-123456789abc","invalid"," ",JSONObject.NULL,0,false,JSONObject(),JSONArray())) {
            val root=base().put("syncEpoch",value)
            assertFalse(equal(SavedBookEpochExpectation.nativeBook(root,raw()),raw()))
            val meta=base().also {it.getJSONObject("syncMetadaten").put("syncEpoch",value)}
            assertFalse(equal(SavedBookEpochExpectation.nativeBook(meta,raw()),raw()))
        }
        val established=base().put("syncEpoch","12345678-1234-4234-8234-123456789abc")
        established.getJSONObject("syncMetadaten").put("syncEpoch",established.get("syncEpoch"))
        assertTrue(equal(SavedBookEpochExpectation.nativeBook(established,established),established))
        val changed=base().put("syncEpoch","aaaaaaaa-1234-4234-8234-123456789abc")
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(changed,established),established))
    }
    @Test fun unknownFieldsContainersSettingsAndExplicitNativeValuesAreNeverExcluded() {
        val ui=base()
        val missing=raw().also {it.getJSONObject("syncMetadaten").remove("future")}
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(ui,missing),missing))
        for(value in listOf(JSONObject.NULL,"invalid",JSONObject().put("syncEpoch",JSONObject.NULL))) {
            val malformed=raw().put("syncMetadaten",value)
            assertFalse(equal(SavedBookEpochExpectation.nativeBook(ui,malformed),malformed))
        }
        val noMeta=raw().also {it.remove("syncMetadaten")}
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(ui,noMeta),noMeta))
        val noUnknown=raw().also {it.remove("futureRoot")}
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(ui,noUnknown),noUnknown))
        val settings=base().put("einstellungen",JSONObject().put("sync",JSONObject().put("syncEpoch","")))
        val noSetting=raw().put("einstellungen",JSONObject().put("sync",JSONObject()))
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(settings,noSetting),noSetting))
        val nullRoot=raw().put("syncEpoch",JSONObject.NULL)
        assertFalse(equal(SavedBookEpochExpectation.nativeBook(ui,nullRoot),nullRoot))
    }
    @Test fun copyingRetainsFloatingPointNumbersBeyondTheLongBoundary() {
        val ui=base().put("futureNumber",Math.scalb(1.0,63)).put("negativeZero",-0.0)
        val expected=SavedBookEpochExpectation.nativeBook(ui,raw())
        assertEquals(java.lang.Double.doubleToRawLongBits(ui.getDouble("futureNumber")),java.lang.Double.doubleToRawLongBits(expected.getDouble("futureNumber")))
        assertEquals(java.lang.Double.doubleToRawLongBits(-0.0),java.lang.Double.doubleToRawLongBits(expected.getDouble("negativeZero")))
    }
}
