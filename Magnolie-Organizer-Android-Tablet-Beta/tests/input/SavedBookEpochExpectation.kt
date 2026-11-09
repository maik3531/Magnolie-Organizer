package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject

/** Test expectation only. An absent native authority is not an empty UI placeholder. */
internal object SavedBookEpochExpectation {
    private fun copy(value: Any): Any = when(value) {
        is JSONObject -> JSONObject().also { result ->
            for(key in value.keys()) result.put(key,copy(value.get(key)))
        }
        is JSONArray -> JSONArray().also { result ->
            for(index in 0 until value.length()) result.put(copy(value.get(index)))
        }
        else -> value
    }
    fun nativeBook(renderer: JSONObject, persisted: JSONObject): JSONObject {
        val expected=copy(renderer) as JSONObject
        if(!persisted.has("syncEpoch") && expected.opt("syncEpoch")=="") expected.remove("syncEpoch")
        val nativeMeta=persisted.opt("syncMetadaten") as? JSONObject
        val expectedMeta=expected.opt("syncMetadaten") as? JSONObject
        if(nativeMeta!=null && !nativeMeta.has("syncEpoch") && expectedMeta?.opt("syncEpoch")=="")
            expectedMeta.remove("syncEpoch")
        return expected
    }
}
