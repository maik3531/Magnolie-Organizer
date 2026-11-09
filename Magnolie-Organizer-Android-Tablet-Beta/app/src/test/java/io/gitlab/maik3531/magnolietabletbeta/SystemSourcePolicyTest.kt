package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SystemSourcePolicyTest {
    private val events=SystemSourcePolicy.Kind.EVENTS
    private val contacts=SystemSourcePolicy.Kind.CONTACTS
    private fun request()=JSONObject().put("cmd","android_systemzugriff").put("session","page").put("revision","book")
        .put("requestId","permission-1").put("art","events")
    private fun row(kind:SystemSourcePolicy.Kind)=SystemSourcePolicy.Source(SystemSourcePolicy.uid(kind,"provider","account","1"),"Fixture",kind)
    @Test fun namespacesAreStableLengthFramedAndDoNotDiscloseAccountLabels() {
        val id=SystemSourcePolicy.uid(events,"type","private@example.test","1")
        assertEquals(id,SystemSourcePolicy.uid(events,"type","private@example.test","1"))
        assertFalse(id.contains("private"));assertFalse(id.contains("example"))
        assertNotEquals(id,SystemSourcePolicy.uid(contacts,"type","private@example.test","1"))
        assertNotEquals(SystemSourcePolicy.uid(events,null,""),SystemSourcePolicy.uid(events,"",null))
        assertNotEquals(SystemSourcePolicy.uid(events,"a:b","c"),SystemSourcePolicy.uid(events,"a","b:c"))
    }
    @Test fun onlyTypedExplicitSupportedReadAccessRequestsPass() {
        assertEquals(events,SystemSourceRequest.parse(request()).kind)
        assertNull(SystemSourceRequest.parse(request().put("cmd","eds_status").removeArt()).kind)
        for(value in listOf(request().put("art","reminders"),request().put("art",7),request().put("requestId",false),
            request().put("records",JSONArray()),request().put("password","secret"),request().put("cmd","anything"),
            request().put("session",""),request().also {it.remove("requestId")})) {
            try {SystemSourceRequest.parse(value);fail("Untrusted source request accepted")} catch(_:IllegalArgumentException){} catch(_:IllegalStateException){}
        }
    }
    private fun JSONObject.removeArt():JSONObject {remove("art");return this}
    @Test fun deniedPermissionDoesNotQueryAndRevocationDoesNotFabricateSuccess() {
        val denied=SystemSourcePolicy.discover(false,{}) {fail("Denied provider was queried");emptyList()}
        assertEquals("not_granted",denied.state);assertNull(denied.sources)
        val revoked=SystemSourcePolicy.discover(true,{}) {throw SecurityException()}
        assertEquals("not_granted",revoked.state);assertNull(revoked.sources)
        val unavailable=SystemSourcePolicy.discover(true,{}) {error("provider broke")}
        assertEquals("unavailable",unavailable.state);assertNull(unavailable.sources)
        val empty=SystemSourcePolicy.discover(true,{}) {emptyList()}
        assertEquals("authorized",empty.state);assertEquals(emptyList<Any>(),empty.sources)
    }
    @Test fun boundsDuplicatesAndCancellationAreFailClosed() {
        val excess=SystemSourcePolicy.discover(true,{}) {List(1001){row(events)}}
        assertEquals("source_limit",excess.errorCode);assertNull(excess.sources)
        val duplicate=SystemSourcePolicy.discover(true,{}) {listOf(row(events),row(events))}
        assertEquals("unavailable",duplicate.state)
        var cancelled=false
        try {SystemSourcePolicy.discover(true,{check(!cancelled)}) {cancelled=true;listOf(row(events))};fail("Cancelled result escaped")}
        catch(_:IllegalStateException){}
    }
    @Test fun unavailableNativeAndDavDoNotFabricateEmptyProviderArrays() {
        val result=SystemSourceBridge.merge(JSONObject().put("fehlerCode","account_unavailable"),emptyMap(),"failed")
        for(key in listOf("kalender","alleKalender","adressbuecher","alleAdressbuecher","nextcloud")) assertFalse(result.has(key))
        assertFalse(result.getBoolean("davSourcesAvailable"));assertFalse(result.getBoolean("systemSourcesComplete"))
    }
    @Test fun observedNativeSourcesAndCachedDavRemainDistinctWithoutEnablingWritesOrSync() {
        val dav=JSONObject().put("alleKalender",JSONArray().put(JSONObject().put("uid","dav:fixture").put("name","DAV")))
            .put("alleAdressbuecher",JSONArray()).put("nextcloud",JSONObject().put("revision","config"))
        val before=dav.toString()
        val result=SystemSourceBridge.merge(dav,mapOf(events to SystemSourcePolicy.Snapshot("authorized",listOf(row(events))),
            contacts to SystemSourcePolicy.Snapshot("not_granted",errorCode="permission_required")),"source-1")
        assertEquals(before,dav.toString());assertEquals(2,result.getJSONArray("kalender").length())
        val native=result.getJSONArray("kalender").getJSONObject(1)
        assertEquals("android",native.getString("quelle"));assertTrue(native.getBoolean("readOnly"));assertFalse(native.getBoolean("supportsVtodo"))
        assertFalse(result.getBoolean("systemAccountSyncImplemented"));assertFalse(result.getBoolean("systemSourcesComplete"))
        assertEquals("not_granted",result.getJSONObject("permissions").getString("contacts"))
        assertEquals("config",result.getJSONObject("nextcloud").getString("revision"))
    }
}
