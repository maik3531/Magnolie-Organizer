package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject

internal data class SystemSourceRequest(val kind: SystemSourcePolicy.Kind?, val requestId: String?) {
    companion object {
        val commands=setOf("eds_status","android_systemzugriff")
        fun parse(value: JSONObject): SystemSourceRequest {
            val access=value.getString("cmd")=="android_systemzugriff"
            require(value.opt("cmd") in commands)
            val keys=value.keys().asSequence().toSet()
            val allowed=setOf("cmd","session","revision","requestId")+if(access) setOf("art") else emptySet()
            require(keys.all {it in allowed})
            fun string(key:String)= (value.opt(key) as? String)?.also {require(it.isNotEmpty() && it.toByteArray().size<=1024)} ?: error("invalid_request")
            string("session");string("revision")
            val id=if(access || value.has("requestId")) string("requestId") else null
            return SystemSourceRequest(if(access) SystemSourcePolicy.kind(string("art")) else null,id)
        }
    }
}
internal object SystemSourceBridge {
    /** Merge only observed provider rows with actual cached DAV collections. No settings mutation. */
    fun merge(dav: JSONObject, snapshots: Map<SystemSourcePolicy.Kind,SystemSourcePolicy.Snapshot>, requestId: String?): JSONObject {
        val result=JSONObject(dav.toString()).put("android",true).put("systemAccountSyncImplemented",false)
        val permissions=JSONObject().put("reminders","unsupported")
        val errors=JSONObject()
        val calendars=JSONArray();val books=JSONArray()
        fun copy(key:String,into:JSONArray) { result.optJSONArray(key)?.let { a -> for(i in 0 until a.length()) into.put(a.getJSONObject(i)) } }
        copy("alleKalender",calendars);copy("alleAdressbuecher",books)
        for (kind in SystemSourcePolicy.Kind.entries) {
            val snapshot=snapshots[kind] ?: SystemSourcePolicy.Snapshot("unavailable",errorCode="provider_unavailable")
            permissions.put(kind.wire,snapshot.state)
            snapshot.errorCode?.let {errors.put(kind.wire,it)}
            for(source in snapshot.sources.orEmpty()) {
                val row=JSONObject().put("uid",source.uid).put("name",source.name).put("quelle","android")
                    .put("art",kind.wire).put("readOnly",true).put("providerWritable",source.providerWritable)
                    .put("supportsVtodo",false).put("supportsVevent",kind==SystemSourcePolicy.Kind.EVENTS)
                if(kind==SystemSourcePolicy.Kind.EVENTS) calendars.put(row) else books.put(row)
            }
        }
        val calendarsObserved=dav.optJSONArray("alleKalender")!=null || snapshots[SystemSourcePolicy.Kind.EVENTS]?.sources!=null
        val booksObserved=dav.optJSONArray("alleAdressbuecher")!=null || snapshots[SystemSourcePolicy.Kind.CONTACTS]?.sources!=null
        if(calendarsObserved) result.put("kalender",calendars).put("alleKalender",calendars)
        if(booksObserved) result.put("adressbuecher",books).put("alleAdressbuecher",books)
        result.put("davSourcesAvailable",dav.optJSONArray("alleKalender")!=null && dav.optJSONArray("alleAdressbuecher")!=null)
        result.put("permissions",permissions).put("systemSourceErrors",errors)
            .put("systemSourcesComplete",snapshots.size==2 && snapshots.values.all {it.state=="authorized"})
            .put("verfuegbar",calendars.length()>0 || books.length()>0).put("buchOk",books.length()>0)
        if(requestId!=null) result.put("requestId",requestId)
        return result
    }
}
