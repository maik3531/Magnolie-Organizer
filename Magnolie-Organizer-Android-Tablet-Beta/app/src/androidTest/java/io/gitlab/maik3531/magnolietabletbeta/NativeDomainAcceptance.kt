package io.gitlab.maik3531.magnolietabletbeta

import android.accessibilityservice.AccessibilityServiceInfo
import android.app.Activity
import android.app.Instrumentation
import android.app.UiAutomation
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Test-only physical input and full native/renderer data-integrity comparison. */
internal object NativeDomainAcceptance {
    private fun ownershipState(test: Instrumentation, activity: Activity, web: WebView): JSONObject {
        val origin=IntArray(2); var density=0f
        val state=JSONObject().put("elapsedRealtimeMs",SystemClock.elapsedRealtime())
        var activePackage="";var activeWindow=-1
        var automation:UiAutomation?=null
        var activeRootPresent=false;var activeReadFailed=false;var targetReadFailed=false
        try {
            automation=test.uiAutomation
            val root=automation?.rootInActiveWindow
            if(root!=null)try {
                activeRootPresent=true
                activePackage=root.packageName?.toString().orEmpty().take(160);activeWindow=root.windowId
            }
                finally {root.recycle()}
        } catch(failure:Exception) {
            activeReadFailed=true;state.put("activeWindowReadError",failure.javaClass.simpleName.take(80))
        }
        // Bounded, read-only service metadata. Do not change flags or request more windows.
        state.put("serviceInfoPresent",false)
        try {
            val info=automation?.serviceInfo
            if(info!=null) state.put("serviceInfoPresent",true).put("serviceFlags",info.flags)
                .put("serviceCapabilities",info.capabilities)
                .put("canRetrieveWindowContent",info.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_RETRIEVE_WINDOW_CONTENT != 0)
                .put("retrievesInteractiveWindows",info.flags and AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS != 0)
        } catch(failure:Exception) {state.put("serviceInfoReadError",failure.javaClass.simpleName.take(80))}
        var nativeReady=false;var targetWindow=-1
        test.runOnMainSync {
            web.getLocationOnScreen(origin);density=web.resources.displayMetrics.density
            state.put("targetNodePresent",false)
            try {
                val node=web.createAccessibilityNodeInfo()
                if(node!=null)try {state.put("targetNodePresent",true);targetWindow=node.windowId} finally {node.recycle()}
            } catch(failure:Exception) {
                targetReadFailed=true;state.put("targetWindowReadError",failure.javaClass.simpleName.take(80))
            }
            nativeReady=!activity.isFinishing && !activity.isDestroyed && activity.hasWindowFocus() &&
                web.isAttachedToWindow && web.isShown && web.hasWindowFocus()
            state.put("activityFinishing",activity.isFinishing).put("activityDestroyed",activity.isDestroyed)
                .put("activityWindowFocused",activity.hasWindowFocus()).put("webAttached",web.isAttachedToWindow)
                .put("webShown",web.isShown).put("webWindowFocused",web.hasWindowFocus())
                .put("targetWindowId",targetWindow).put("origin",JSONArray(origin.toList()))
                .put("viewSize",JSONArray(listOf(web.width,web.height))).put("density",density)
        }
        val result=NativeWindowOwnershipPolicy.assess(NativeWindowOwnershipPolicy.Evidence(
            nativeReady,targetWindow,activeWindow,activePackage,activity.packageName,activeRootPresent,activeReadFailed,targetReadFailed))
        if(!result.owned) state.put("classification",result.classification).put("failureCode",result.failureCode)
            .put("diagnosis",result.name)
        return state.put("activePackage",activePackage).put("activeWindowId",activeWindow).put("owned",result.owned)
            .put("nativeReady",nativeReady).put("activeRootPresent",activeRootPresent)
            .put("activeReadFailed",activeReadFailed).put("targetReadFailed",targetReadFailed)
    }
    fun requireOwnership(test: Instrumentation, activity: Activity, web: WebView, phase: String,
                         report: (JSONObject) -> Unit): JSONObject {
        val receipt=JSONObject().put("schema",1).put("source","native-window-ownership").put("phase",phase)
        val state=ownershipState(test,activity,web); receipt.put("state",state)
        if(!state.getBoolean("owned")) receipt.put("classification",state.getString("classification"))
        report(receipt)
        check(state.getBoolean("owned")) {"${state.getString("failureCode")}: app-owned drawing window lacks native input ownership ($phase)"}
        return receipt
    }
    // Only this app-owned drawing gesture requires the app's native window.
    // SAF/permission/system-dialog interactions deliberately do not use this guard.
    fun stroke(test: Instrumentation, activity: Activity, web: WebView, target: JSONObject,
               report: (JSONObject) -> Unit): JSONObject {
        val origin=IntArray(2)
        val receipt=JSONObject().put("schema",1).put("source","native-touchscreen")
            .put("requestedDurationMs",420).put("cssTarget",JSONObject()
                .put("x1",target.getDouble("x1")).put("x2",target.getDouble("x2")).put("y",target.getDouble("y")))
        var density=0f
        fun ownership(phase: String) {
            val state=ownershipState(test,activity,web)
            val publishedOrigin=state.getJSONArray("origin"); origin[0]=publishedOrigin.getInt(0);origin[1]=publishedOrigin.getInt(1)
            density=state.getDouble("density").toFloat()
            if(phase=="beforeInjection" && density.isFinite() && density>0) receipt.put("nativeTarget",JSONObject()
                .put("x1",origin[0]+target.getDouble("x1")*density).put("x2",origin[0]+target.getDouble("x2")*density)
                .put("y",origin[1]+target.getDouble("y")*density))
            val owned=state.getBoolean("owned")
            receipt.put(phase,state)
            if(!owned) receipt.put("classification",state.getString("classification"))
            report(receipt)
            check(owned) {"${state.getString("failureCode")}: app-owned drawing window lacks native input ownership ($phase)"}
        }
        ownership("beforeInjection")
        val x1=origin[0]+target.getDouble("x1")*density
        val x2=origin[0]+target.getDouble("x2")*density
        val y=origin[1]+target.getDouble("y")*density
        check(density.isFinite() && density>0 && listOf(x1,x2,y).all { it.isFinite() && it>=0 } && x2>x1)
        receipt.put("nativeTarget",JSONObject().put("x1",x1).put("x2",x2).put("y",y))
        report(receipt)
        val started=SystemClock.elapsedRealtime()
        val output=test.uiAutomation.executeShellCommand("input touchscreen swipe $x1 $y $x2 $y 420").use {
            ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().readText()
        }
        receipt.put("durationMs",SystemClock.elapsedRealtime()-started).put("shellOutputBlank",output.isBlank())
        report(receipt)
        check(output.isBlank()) { "Native touchscreen injection failed" }
        ownership("afterInjection")
        return receipt
    }
    private fun semantic(value: Any?): Any? = when(value) {
        null,JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().toList().sorted().associateWith { semantic(value.get(it)) }
        is JSONArray -> (0 until value.length()).map { semantic(value.get(it)) }
        is Number -> value.toDouble()
        else -> value
    }
    fun requireEqual(expected: JSONObject, actual: JSONObject, message: String) {
        check(semantic(expected)==semantic(actual)) { message }
    }
    fun requireSavedEqual(renderer: JSONObject, persisted: JSONObject, message: String) {
        requireEqual(SavedBookEpochExpectation.nativeBook(renderer,persisted),persisted,message)
    }
    fun hash(value: JSONObject): String = MessageDigest.getInstance("SHA-256")
        .digest(semantic(value).toString().toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
}
