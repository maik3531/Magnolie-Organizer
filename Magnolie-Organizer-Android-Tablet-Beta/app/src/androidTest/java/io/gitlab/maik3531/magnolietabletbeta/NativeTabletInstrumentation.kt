package io.gitlab.maik3531.magnolietabletbeta

import android.app.Activity
import android.app.Instrumentation
import android.app.NotificationManager
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.provider.DocumentsContract
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.File
import java.security.KeyStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.crypto.SecretKey

/** No test entry points are added to the production/debug application's manifest. */
class NativeTabletInstrumentation : Instrumentation() {
    private lateinit var options: Bundle
    private lateinit var activity: MainActivity
    private lateinit var web: WebView
    private val checks=JSONArray()
    private var lastTouchTiming=JSONObject()
    private var lastIssuedTouch=emptyList<AsyncTouchPair.Delivery>()
    private var previousNativeDownTime=-1L
    private var nativeDomOffset:Double?=null
    private val nativeMotion=java.util.ArrayDeque<DoubleArray>()
    private val injector get()=options.getString("injector") ?: "async"
    private val navigationProof=JSONArray()
    private var webEvaluations=0
    private var webEvaluationMs=0L
    private var inputPort:android.webkit.WebMessagePort?=null
    private val inputToken=java.util.UUID.randomUUID().toString()
    @Volatile private var inputDocument=""
    @Volatile private var ackLatch=CountDownLatch(1)
    @Volatile private var incomingAck:JSONObject?=null
    @Volatile private var expectedStep=0
    private var touchNumber=0
    private val provider="io.gitlab.maik3531.magnolieorganizer.tablet.beta.test.documents"
    private val out get()=File(targetContext.getExternalFilesDir(null),"native-evidence/"+(options.getString("case") ?: "legacy")).apply {mkdirs()}
    override fun onCreate(arguments: Bundle?) {super.onCreate(arguments); options=arguments ?: Bundle(); start()}
    override fun onStart() {
        val stage=options.getString("stage") ?: "basics"
        android.util.Log.i("TabletNativeTest","START $stage")
        var error: Throwable?=null
        try {
            check(injector in listOf("shell","async")) {"Unknown injector"}
            check(android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.MODEL.contains("sdk")) {"Disposable emulator required"}
            when(stage) {
                "basics" -> basics()
                "restart" -> {launch(); assertPersisted()}
                "layout" -> {launch(); checkLayout(); navigation()}
                "time" -> customTimeKeyboard()
                "navigation" -> {launch(); navigation()}
                "saf" -> saf()
                "fault" -> fault()
                "print" -> printPdf()
                "notifications" -> notifications(false)
                "seed-reboot" -> notifications(true)
                "verify-reboot" -> verifyReboot()
                else -> error("Unknown stage")
            }
            capture(stage)
        } catch(t: Throwable) {
            error=t
            android.util.Log.e("TabletNativeTest","FAIL $stage",t)
            try {dump("failure-"+stage); if(::activity.isInitialized) capture("failure-"+stage)} catch(_:Throwable) {}
        }
        val proof=JSONObject().put("stage",stage).put("checks",checks).put("passed",error==null)
            .put("injector",injector).put("case",options.getString("case"))
            .put("sdk",android.os.Build.VERSION.SDK_INT).put("model",android.os.Build.MODEL)
            .put("brand",android.os.Build.BRAND).put("applicationId",targetContext.packageName)
            .put("applicationLabel",targetContext.applicationInfo.loadLabel(targetContext.packageManager).toString())
            .put("sourceHash",JSONObject(targetContext.assets.open("projection.json").bufferedReader().readText()).getString("sourceHash"))
            .put("webview",WebView.getCurrentWebViewPackage()?.versionName).put("error",error?.stackTraceToString() ?: JSONObject.NULL)
        File(out,"$stage.json").writeText(proof.toString(2))
        if(inputPort!=null) runOnMainSync {inputPort?.close()}
        val result=Bundle().apply {putString("stream",proof.toString(2)+"\n")}
        finish(if(error==null) Activity.RESULT_OK else Activity.RESULT_CANCELED,result)
    }
    private fun pass(name:String,detail:Any=true) {
        checks.put(JSONObject().put("name",name).put("detail",detail))
        File(out,"progress-${options.getString("stage")}.json").writeText(JSONObject().put("complete",false).put("checks",checks).toString(2))
        android.util.Log.i("TabletNativeTest","PASS $name")
        sendStatus(1,Bundle().apply {putString("stream","PASS $name\n")})
    }
    private fun waitFor(name:String,seconds:Long=25,condition:()->Boolean) {
        val end=SystemClock.elapsedRealtime()+seconds*1000
        while(SystemClock.elapsedRealtime()<end) {if(condition()) return; SystemClock.sleep(100)}
        error("Timeout: $name")
    }
    private fun launch() {
        activity=startActivitySync(Intent(targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        web=MainActivity::class.java.getDeclaredField("web").apply {isAccessible=true}.get(activity) as WebView
        waitFor("native initialization acknowledged") {
            var ready=false; runOnMainSync {ready=MainActivity::class.java.getDeclaredField("ready").apply {isAccessible=true}.getBoolean(activity)}; ready
        }
        js("window.MagnolieI18n.setLocale('en'); OrganizerTest.daten().einstellungen.regional.language='en'; OrganizerTest.daten().einstellungen.regional.timeZone='UTC'; true")
        raw(context.assets.open("scenarios.js").bufferedReader().readText())
        raw(context.assets.open("touch-proof.js").bufferedReader().readText()+"\n"+
            context.assets.open("input-diagnostics.js").bufferedReader().readText())
        runOnMainSync {
            web.setOnTouchListener { _, event ->
                synchronized(nativeMotion) {
                if(nativeMotion.size==256) nativeMotion.removeFirst()
                nativeMotion.addLast(doubleArrayOf(event.actionMasked.toDouble(),event.eventTime.toDouble(),
                    event.downTime.toDouble(),SystemClock.uptimeMillis().toDouble(),event.x.toDouble(),
                    event.y.toDouble(),event.rawX.toDouble(),event.rawY.toDouble(),event.source.toDouble(),event.getToolType(0).toDouble()))
                }
                false
            }
        }
        saved()
    }
    private fun raw(script:String):String {
        val started=SystemClock.elapsedRealtime(); webEvaluations++
        val latch=CountDownLatch(1); var result="null"
        activity.runOnUiThread {web.evaluateJavascript(script){result=it; latch.countDown()}}
        check(latch.await(20,TimeUnit.SECONDS)) {"WebView evaluation timed out"}
        webEvaluationMs+=SystemClock.elapsedRealtime()-started
        return result
    }
    private fun js(expression:String):String {
        val raw=raw("JSON.stringify((()=>{$expression})())")
        return JSONTokener(raw).nextValue().toString()
    }
    private fun value(expression:String)=js("return ($expression)")
    private fun scenario(expression:String):JSONObject {
        raw("window.__nativeDone=false; window.__nativeError=''; Promise.resolve().then(()=>($expression)).then(v=>window.__nativeResult=v).catch(e=>window.__nativeError=String(e.stack||e)).finally(()=>window.__nativeDone=true)")
        waitFor("real editor action") {value("window.__nativeDone")=="true"}
        check(value("window.__nativeError")=="\"\"") {value("window.__nativeError")}
        return JSONObject(value("window.__nativeResult") )
    }
    private fun saved() {
        raw("window.__nativeSaved=false; MagnolieTabletActions.afterSave(()=>window.__nativeSaved=true)")
        waitFor("durable native save ACK") {value("window.__nativeSaved")=="true"}
        check(File(targetContext.noBackupFilesDir,"tablet-vault.enc").isFile)
    }
    private fun reloadVerified() {
        val generation=MainActivity::class.java.getDeclaredField("generation").apply {isAccessible=true}
        val ready=MainActivity::class.java.getDeclaredField("ready").apply {isAccessible=true}
        val before=generation.getInt(activity)
        runOnMainSync {web.reload()}
        waitFor("fresh page generation and native initialization",40) {
            var done=false; runOnMainSync {done=generation.getInt(activity)>before && ready.getBoolean(activity)}; done
        }
        raw(context.assets.open("scenarios.js").bufferedReader().readText())
    }
    private fun data()=JSONObject(value("OrganizerTest.daten()"))
    private fun vault()=AndroidStore.vault(targetContext)
    private fun capture(name:String) {
        File(out,"$name-navigation-proof.json").writeText(navigationProof.toString(2))
        File(out,"$name-rpc-metrics.json").writeText(JSONObject().put("evaluations",webEvaluations).put("evaluationMs",webEvaluationMs).toString(2))
        File(out,"$name-diagnostics.json").writeText(value("window.__nativeDiagnosticSnapshot?.() || {}"))
        lateinit var motion:String
        synchronized(nativeMotion) {motion=JSONArray(nativeMotion.map {JSONArray(it.toList())}).toString()}
        File(out,"$name-native-motion.json").writeText(motion)
        // Test-only screenshot exception; always restore the actual app's FLAG_SECURE.
        runOnMainSync {activity.window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)}
        try {
            SystemClock.sleep(400)
            var screenshot:Bitmap?=null
            waitFor("compositor screenshot after secure flag transition",5) {screenshot=uiAutomation.takeScreenshot(); screenshot!=null}
            val bitmap=requireNotNull(screenshot)
            try {File(out,"$name.png").outputStream().use {check(bitmap.compress(Bitmap.CompressFormat.PNG,100,it))}}
            finally {bitmap.recycle()}
        }
        finally {runOnMainSync {activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)}}
        File(out,"$name-dom.json").writeText(value("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,section:OrganizerTest.zustand().sektion,status:document.querySelector('#tablet-status').textContent,body:document.body.innerText.slice(0,20000)})"))
        File(out,"$name-input-events.json").writeText(value("window.__nativeInputTrace || []"))
        File(out,"$name-fonts.json").writeText(value("({title:document.title,betaLabel:document.querySelector('#tablet-bar strong').textContent,selected:OrganizerTest.daten().einstellungen.schrift,faces:[...document.fonts].map(f=>({family:f.family,status:f.status})),fields:[...document.querySelectorAll('input:not([type=password]),textarea,[contenteditable]')].slice(0,80).map(e=>({id:e.id,tag:e.tagName,readOnly:e.readOnly===true,disabled:e.disabled===true,contentEditable:e.contentEditable,fontFamily:getComputedStyle(e).fontFamily,fontStyle:getComputedStyle(e).fontStyle,fontSize:getComputedStyle(e).fontSize}))})"))
    }
    private fun nodes():List<AccessibilityNodeInfo> {
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun visit(n:AccessibilityNodeInfo?) {if(n==null) return; result.add(n); for(i in 0 until n.childCount) visit(n.getChild(i))}
        visit(uiAutomation.rootInActiveWindow); return result
    }
    private fun dump(name:String) {File(out,"$name-accessibility.txt").writeText(nodes().joinToString("\n") {it.toString()})}
    private fun clickNode(label:String,seconds:Long=15) {
        var match:AccessibilityNodeInfo?=null
        waitFor("native control $label",seconds) {match=nodes().firstOrNull {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label || it.viewIdResourceName==label)}; match!=null}
        var n=match!!
        while(!n.isClickable && n.parent!=null) n=n.parent
        check(n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {"Cannot click $label"}
        SystemClock.sleep(250)
    }
    private fun setNativeText(text:String) {
        val field=nodes().firstOrNull {it.isVisibleToUser && it.className?.toString()=="android.widget.EditText"} ?: error("Native text field absent")
        check(field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,Bundle().apply {putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,text)}))
    }
    private fun tapExpression(expression:String) {
        touchNumber++
        val preparedAt=SystemClock.elapsedRealtime()
        lateinit var rect:JSONObject
        waitFor("stable unobscured touch target",5) {
            rect=JSONObject(value("(()=>{const e=$expression;if(!e)throw Error('Missing touch target');e.scrollIntoView({block:'nearest',behavior:'instant'});const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);let moving=false;for(let p=e;p;p=p.parentElement)moving ||= p.getAnimations().some(a=>a.playState==='running'&&a.effect?.getTiming().iterations!==Infinity);return{x,y,hit:!!hit&&(hit===e||e.contains(hit)),tab:e.classList.contains('registerknopf'),moving,disabled:!!e.disabled}})()"))
            rect.getBoolean("hit") && (rect.optBoolean("tab") || !rect.getBoolean("moving")) && !rect.getBoolean("disabled")
        }
        val location=IntArray(2); var scale=1f; runOnMainSync {web.getLocationOnScreen(location); scale=web.resources.displayMetrics.density}
        val x=location[0]+rect.getDouble("x").toFloat()*scale
        val y=location[1]+rect.getDouble("y").toFloat()*scale
        val probe=JSONObject(value("(()=>{const e=$expression;return {node:__nativeProbeTarget(e),dpr:devicePixelRatio,viewport:{scale:visualViewport.scale,x:visualViewport.offsetLeft,y:visualViewport.offsetTop},rect:e.getBoundingClientRect().toJSON(),touchAction:getComputedStyle(e).touchAction}})()"))
        File(out,"last-touch.json").writeText(JSONObject().put("target",expression)
            .put("probe",probe)
            .put("css",rect).put("originX",location[0]).put("originY",location[1])
            .put("scale",scale).put("screenX",x).put("screenY",y).toString(2))
        val injectionAt=SystemClock.elapsedRealtime()
        injectTouch(x,y)
        lastTouchTiming.put("prepareMs",injectionAt-preparedAt)
    }
    private fun injectTouch(x:Float,y:Float) {
        val injectionAt=SystemClock.elapsedRealtime()
        val injectionUptime=SystemClock.uptimeMillis()
        val deliveries=JSONArray()
        if(injector=="shell") {
            val inputOutput=shell("input touchscreen tap $x $y")
            check(inputOutput.isBlank()) {"Unexpected native input output: $inputOutput"}
        } else {
            val result=AsyncTouchPair.inject({SystemClock.uptimeMillis()},{SystemClock.sleep(it)}) { event,sync ->
                val properties=android.view.MotionEvent.PointerProperties().apply {
                    id=0; toolType=android.view.MotionEvent.TOOL_TYPE_FINGER
                }
                val coords=android.view.MotionEvent.PointerCoords().apply {
                    this.x=x; this.y=y; pressure=if(event.down) 1f else 0f; size=1f
                }
                val motion=android.view.MotionEvent.obtain(event.downTime,event.eventTime,
                    if(event.down) android.view.MotionEvent.ACTION_DOWN else android.view.MotionEvent.ACTION_UP,
                    1,arrayOf(properties),arrayOf(coords),0,0,1f,1f,0,0,
                    android.view.InputDevice.SOURCE_TOUCHSCREEN,0)
                try {uiAutomation.injectInputEvent(motion,sync)} finally {motion.recycle()}
            }
            lastIssuedTouch=result
            for(d in result) deliveries.put(JSONObject().put("action",if(d.event.down) "DOWN" else "UP")
                .put("downTime",d.event.downTime).put("eventTime",d.event.eventTime)
                .put("callAt",d.callAt).put("returnedAt",d.returnedAt).put("sync",false).put("accepted",d.accepted))
        }
        lastTouchTiming=JSONObject().put("injectionMs",SystemClock.elapsedRealtime()-injectionAt)
            .put("injector",injector).put("callUptime",injectionUptime)
            .put("returnedUptime",SystemClock.uptimeMillis()).put("deliveries",deliveries)
    }
    private fun checkLayout() {
        val geometry=JSONObject(value("(()=>{const l=document.querySelector('#seite-links').getBoundingClientRect(),r=document.querySelector('#seite-rechts').getBoundingClientRect();return{width:innerWidth,height:innerHeight,l:{x:l.x,y:l.y,w:l.width,h:l.height},r:{x:r.x,y:r.y,w:r.width,h:r.height}}})()"))
        val l=geometry.getJSONObject("l"); val r=geometry.getJSONObject("r")
        check(l.getDouble("w")>100 && r.getDouble("w")>100)
        if(geometry.getInt("width")>850 && geometry.getInt("width")>geometry.getInt("height")) check(r.getDouble("x")>l.getDouble("x"))
        else check(r.getDouble("y")>l.getDouble("y"))
        val tabs=JSONArray(value("[...document.querySelectorAll('.registerknopf')].map(e=>{const r=e.getBoundingClientRect();return {label:e.textContent,x:r.x,right:r.right,width:document.documentElement.clientWidth}})"))
        for(i in 0 until tabs.length()) {
            val tab=tabs.getJSONObject(i)
            check(tab.getDouble("x")>=-1 && tab.getDouble("right")<=tab.getDouble("width")+1) {"Clipped tab: $tab"}
        }
        lateinit var fontSettings: JSONObject
        runOnMainSync {
            fontSettings = JSONObject().put("fontScale", targetContext.resources.configuration.fontScale)
                .put("webTextZoom", web.settings.textZoom)
        }
        pass("native font/display settings", fontSettings)
        pass("real WebView responsive binder geometry",geometry)
    }
    private fun basics() {
        launch(); pass("real AssetLoader/WebMessage initialization")
        scenario("NativeScenario.calendar()"); saved(); pass("calendar editor to encrypted native store")
        scenario("NativeScenario.task('Synthetic native task','2030-05-10','11:00',1,true)"); saved(); pass("task editor early+due to native store")
        scenario("NativeScenario.contact()"); saved(); pass("contact editor to native store")
        scenario("NativeScenario.note()"); saved(); pass("note editor to native store")
        scenario("NativeScenario.custom()"); saved(); pass("custom designer and time editor to native store")
        checkLayout()
        raw("OrganizerTest.wechsel('notizen')"); SystemClock.sleep(300)
        tapExpression("document.querySelector('#notiz-titel')")
        waitFor("actual touch focuses note title",10) {value("document.activeElement===document.querySelector('#notiz-titel')")=="true"}
        sendKeySync(KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_MOVE_END)); sendKeySync(KeyEvent(KeyEvent.ACTION_UP,KeyEvent.KEYCODE_MOVE_END))
        sendStringSync(" Keyboard"); SystemClock.sleep(300); saved()
        check(data().getJSONArray("notizen").toString().contains("Keyboard")); pass("hardware key input into real WebView note")
        assertPersisted()
        if(options.getString("fixture")=="capture") prepareNavigationFixture()
    }
    private fun prepareNavigationFixture() {
        // Stress fixture retains actual editor structure; replace only this test's own series.
        val fixture=File(targetContext.getExternalFilesDir(null),"input-ab-fixture.json")
        if(options.getString("fixture")=="restore") {
            check(fixture.isFile) {"A/B fixture was not captured by basics"}
            js("const d=OrganizerTest.daten(),seed=JSON.parse(${JSONObject.quote(fixture.readText())});for(const k of Object.keys(d))delete d[k];Object.assign(d,seed);OrganizerTest.speichereJetzt();return true")
        } else {
            js("const d=OrganizerTest.daten();d.termine=d.termine.filter(x=>!String(x.id).startsWith('old-series-'));const base=d.termine[0];if(!base)throw Error('Missing seeded calendar'); for(let i=0;i<17;i++) d.termine.push({...base,id:'old-series-'+i,titel:'Old series '+i,datum:'2000-01-01',zeit:'10:00',endDatum:'2000-01-01',endZeit:'11:00',icsRoundtrip:['DTSTART:20000101T100000Z','DTEND:20000101T110000Z','RRULE:FREQ=DAILY;COUNT=20000'],wiederholung:{art:'daily'}}); OrganizerTest.speichereJetzt(); return true")
            if(options.getString("fixture")=="capture") fixture.writeText(value("OrganizerTest.daten()"))
        }
        val fixtureText=value("OrganizerTest.daten()")
        if(options.getString("fixture")=="restore") check(fixtureText==fixture.readText()) {"A/B data fixture differs"}
        File(out,"fixture.json").writeText(fixtureText)
        raw("OrganizerTest.wechsel('kalender')")
        waitFor("fixture begins on Calendar") {value("OrganizerTest.zustand().sektion")==JSONObject.quote("kalender")}
        saved()
    }
    private fun navigation() {
        prepareNavigationFixture()
        connectInputProbe()
        val durations=JSONArray(); val labels=listOf("Planner","Tasks","Contacts","Notes","Calendar","Anniversaries","Health","Tablet custom")
        for(i in 0 until 40) {
            val label=labels[i%labels.size]; val started=SystemClock.elapsedRealtime()
            val section=mapOf("Planner" to "planer","Tasks" to "aufgaben","Contacts" to "adressen","Notes" to "notizen","Calendar" to "kalender",
                "Anniversaries" to "jahrestage","Health" to "gesundheit","Tablet custom" to "custom").getValue(label)
            ackLatch=CountDownLatch(1); incomingAck=null; expectedStep=i+1
            val prepared=prepareTouch(i+1,label,section)
            val preparedAt=SystemClock.elapsedRealtime()
            injectTouch(prepared.getDouble("screenX").toFloat(),prepared.getDouble("screenY").toFloat())
            val returnedAt=SystemClock.elapsedRealtime()
            check(ackLatch.await(10,TimeUnit.SECONDS)) {"Timeout: trusted touch acknowledgement $section"}
            val ack=requireNotNull(incomingAck)
            check(ack.optString("kind")=="ack" && ack.optBoolean("trusted") &&
                ack.getString("token")==inputToken && ack.getString("documentId")==inputDocument && ack.getInt("step")==i+1 &&
                ack.getString("label")==label && ack.getString("section")==section &&
                ack.getInt("node")==prepared.getInt("node") && ack.getString("before")!=section &&
                ack.getString("sourceHash")==prepared.getString("sourceHash") &&
                ack.getDouble("armedAt")==prepared.getDouble("armedAt") && ack.getInt("clockPrecisionMs")==1) {"Invalid touch acknowledgement: $ack"}
            val epoch=lastIssuedTouch.first().event.downTime
            val receipts=synchronized(nativeMotion) {
                nativeMotion.filter {it[2].toLong()==epoch}.map {
                    NativeGestureBinding.Receipt(it[0].toInt(),it[1].toLong(),it[2].toLong(),it[3].toLong(),
                        it[6],it[7],it[8].toInt(),it[9].toInt())
                }
            }
            val verifiedOffset=NativeGestureBinding.verify(prepared.getLong("nativeEvaluationStart"),prepared.getLong("nativeArmedUptime"),
                previousNativeDownTime,lastIssuedTouch,receipts,prepared.getDouble("screenX"),prepared.getDouble("screenY"),
                NativeGestureBinding.Browser(ack.getDouble("armedAt"),ack.getDouble("downStamp"),ack.getDouble("upStamp")),nativeDomOffset)
            if(nativeDomOffset==null) nativeDomOffset=verifiedOffset
            previousNativeDownTime=epoch
            ack.put("nativeGestureVerified",true).put("nativeDownTime",epoch).put("nativeDomOffset",verifiedOffset)
            if(section=="planer") check(ack.getInt("pendingJobs")==0) {"Planner has pending jobs"}
            val total=SystemClock.elapsedRealtime()-started
            durations.put(total)
            navigationProof.put(JSONObject().put("target",prepared).put("injection",lastTouchTiming)
                .put("ack",ack).put("prepareMs",preparedAt-started).put("ackWaitMs",SystemClock.elapsedRealtime()-returnedAt)
                .put("totalMs",total))
            android.util.Log.i("TabletNativeTest","TOUCH_ACK "+JSONObject(ack.toString()).apply {remove("token")}.toString())
        }
        pass("40 real touchscreen tab switches with 17 old series",durations)
        saved()
    }

    private fun connectInputProbe() {
        val source=JSONObject(targetContext.assets.open("projection.json").bufferedReader().readText()).getString("sourceHash")
        raw("NativeTouchProbe.connect(${JSONObject.quote(inputToken)},${JSONObject.quote(source)})")
        val ready=CountDownLatch(1)
        activity.runOnUiThread {
            val ports=web.createWebMessageChannel(); inputPort=ports[0]
            ports[0].setWebMessageCallback(object:android.webkit.WebMessagePort.WebMessageCallback() {
                override fun onMessage(port:android.webkit.WebMessagePort,message:android.webkit.WebMessage) {
                    val row=try {JSONObject(message.data ?: "{}")} catch(_:Exception) {return}
                    if(row.optString("token")!=inputToken) return
                    if(row.optString("kind")=="ready" && row.optString("sourceHash")==source) {
                        inputDocument=row.getString("documentId"); ready.countDown()
                    } else if(row.optString("documentId")==inputDocument && row.optInt("step")==expectedStep) {
                        incomingAck=row; ackLatch.countDown()
                    }
                }
            })
            web.postWebMessage(android.webkit.WebMessage(inputToken,arrayOf(ports[1])),android.net.Uri.parse(MainActivity.ORIGIN))
        }
        check(ready.await(5,TimeUnit.SECONDS)) {"Test-only WebMessagePort handshake failed"}
    }

    private fun prepareTouch(step:Int,label:String,section:String):JSONObject {
        lateinit var prepared:JSONObject
        val before=webEvaluations
        waitFor("stable unobscured touch target",5) {
            val latch=CountDownLatch(1); var result="null"; val location=IntArray(2); var density=1f
            var uiAt=0L
            var nativeEvaluationStart=0L; var nativeArmedUptime=0L
            val started=SystemClock.elapsedRealtime(); webEvaluations++
            activity.runOnUiThread {
                uiAt=SystemClock.elapsedRealtime()
                web.getLocationOnScreen(location); density=web.resources.displayMetrics.density
                nativeEvaluationStart=SystemClock.uptimeMillis()
                web.evaluateJavascript("NativeTouchProbe.prepare($step,${JSONObject.quote(label)},${JSONObject.quote(section)})") {
                    nativeArmedUptime=SystemClock.uptimeMillis(); result=it; latch.countDown()
                }
            }
            // Preserve raw()'s existing per-evaluation deadline; the five-second
            // target retry guard is not a replacement for the RPC deadline.
            check(latch.await(20,TimeUnit.SECONDS)) {"Touch preparation evaluation timed out"}
            webEvaluationMs+=SystemClock.elapsedRealtime()-started
            prepared=JSONObject(result)
            check(!prepared.has("error")) {prepared.optString("error")}
            if(prepared.optBoolean("ready")) {
                check(prepared.getString("documentId")==inputDocument) {"Wrong renderer document"}
                check(prepared.getDouble("pageScale")==1.0 && prepared.getDouble("viewportX")==0.0 && prepared.getDouble("viewportY")==0.0) {"Unverified zoom conversion"}
                prepared.put("originX",location[0]).put("originY",location[1]).put("density",density)
                    .put("nativeEvaluationStart",nativeEvaluationStart).put("nativeArmedUptime",nativeArmedUptime)
                    .put("evaluations",webEvaluations-before).put("uiQueueMs",uiAt-started)
                    .put("evaluationCallbackMs",SystemClock.elapsedRealtime()-uiAt)
                    .put("screenX",location[0]+prepared.getDouble("x")*density)
                    .put("screenY",location[1]+prepared.getDouble("y")*density)
                true
            } else false
        }
        return prepared
    }
    private fun assertPersisted() {
        val state=vault().read() ?: error("Missing native vault")
        val d=state.getJSONObject("data")
        check(d.getJSONArray("termine").toString().contains("Synthetic native calendar"))
        check(d.getJSONArray("aufgaben").toString().contains("Synthetic native task"))
        check(d.getJSONArray("kontakte").toString().contains("Tablet"))
        check(d.getJSONArray("notizen").toString().contains("Keyboard"))
        check(d.getJSONObject("customOrganizer").toString().contains("12:35"))
        val encrypted=File(targetContext.noBackupFilesDir,"tablet-vault.enc").readBytes()
        check(!String(encrypted).contains("Synthetic native")); check(!String(encrypted).contains("Private synthetic"))
        val key=KeyStore.getInstance("AndroidKeyStore").apply {load(null)}.getKey("magnolie-organizer-tablet-beta-vault-v1",null) as SecretKey
        check(key.encoded==null)
        pass("real non-exportable Android Keystore key and encrypted profile restart",JSONObject().put("ciphertextBytes",encrypted.size).put("calendars",d.getJSONArray("termine").length()))
    }
    private fun documentControl(name:String,text:String?=null,delete:Boolean=false):ByteArray {
        val done=CountDownLatch(1); var bytes:ByteArray?=null
        val intent=Intent().setComponent(android.content.ComponentName(context.packageName,SyntheticDocumentControl::class.java.name))
            .addFlags(Intent.FLAG_INCLUDE_STOPPED_PACKAGES or Intent.FLAG_RECEIVER_FOREGROUND)
            .putExtra("name",name).putExtra("delete",delete)
        if(text!=null) intent.putExtra("text",text)
        targetContext.sendOrderedBroadcast(intent,null,object:android.content.BroadcastReceiver() {
            override fun onReceive(c:android.content.Context,i:Intent) {
                if(resultCode==Activity.RESULT_OK) bytes=getResultExtras(false)?.getByteArray("bytes")
                done.countDown()
            }
        },null,Activity.RESULT_CANCELED,null,null)
        check(done.await(20,TimeUnit.SECONDS)) {"Synthetic provider fixture control timed out"}
        return requireNotNull(bytes) {"Synthetic fixture control failed"}
    }
    private fun seedDocument(name:String,text:String) {documentControl(name,text)}
    private fun selectProvider() {
        if(nodes().none {it.text?.toString()=="Tablet Beta Test Documents"}) {
            val menu=nodes().firstOrNull {it.contentDescription?.toString() in listOf("Show roots","Open navigation drawer","Show navigation drawer")}
            if(menu!=null) menu.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        }
        clickNode("Tablet Beta Test Documents")
    }
    private fun importFile(name:String) {
        raw("Tablet.action('tablet_import')")
        waitFor("Android DocumentsUI") {nodes().any {it.packageName?.toString()?.contains("documentsui")==true}}
        selectProvider(); clickNode(name)
        waitFor("native restore confirmation") {nodes().any {it.text?.toString()?.contains("current data will be backed up")==true}}
    }
    private fun saf() {
        launch(); saved(); val original=data()
        seedDocument("cancel-import.json",original.toString())
        importFile("cancel-import.json"); clickNode("android:id/button2"); saved()
        check(data().getJSONArray("notizen").length()==original.getJSONArray("notizen").length()); pass("SAF selection and native restore cancellation")
        documentControl("tablet-export.json",delete=true)
        raw("Tablet.action('tablet_export')"); waitFor("export password") {nodes().any {it.className?.toString()=="android.widget.EditText"}}
        setNativeText("synthetic-password-123"); clickNode("android:id/button1")
        waitFor("SAF create document") {nodes().any {it.packageName?.toString()?.contains("documentsui")==true}}
        selectProvider(); setNativeText("tablet-export.json"); clickNode("Save")
        waitFor("native export finished") {value("document.querySelector('#tablet-status').textContent.includes('Saved.')")=="true"}
        val exported=String(documentControl("tablet-export.json"))
        check(!exported.contains("Private synthetic")); check(JSONObject(Portable.open(exported,"synthetic-password-123".toCharArray())).getInt("version")==6)
        pass("real SAF encrypted export and password decryption")
        val replacement=JSONObject(original.toString()); replacement.getJSONArray("notizen").getJSONObject(0).put("titel","Synthetic restored B")
        seedDocument("confirmed-import.json",replacement.toString()); importFile("confirmed-import.json"); clickNode("android:id/button1")
        waitFor("confirmed import B reloaded") {value("OrganizerTest.daten().notizen.some(n=>n.titel==='Synthetic restored B')")=="true"}
        saved(); check(!vault().read()!!.getBoolean("enabled")); check(!vault().read()!!.getBoolean("customEnabled"))
        check(File(targetContext.noBackupFilesDir,"before-import.enc").isFile); pass("real SAF confirmed replacement, backup and consent reset")
        capture("saf-restored")
    }
    private fun fault() {
        launch(); saved()
        val key=KeyStore.getInstance("AndroidKeyStore").apply {load(null)}.getKey("magnolie-organizer-tablet-beta-vault-v1",null) as SecretKey
        val armed=java.util.concurrent.atomic.AtomicBoolean(false)
        val faultVault=Vault(targetContext.noBackupFilesDir,{key},{if(it=="rename" && armed.compareAndSet(true,false)) throw java.io.IOException("INSTRUMENTATION_ONLY_POST_RENAME")})
        AndroidStore.io.submit {AndroidStore::class.java.getDeclaredField("instance").apply {isAccessible=true}.set(AndroidStore,faultVault)}.get(10,TimeUnit.SECONDS)
        reloadVerified(); saved()
        val b=data(); b.getJSONArray("notizen").getJSONObject(0).put("titel","Synthetic fault B")
        seedDocument("fault-import.json",b.toString()); importFile("fault-import.json"); armed.set(true); clickNode("android:id/button1")
        waitFor("post-rename native fence") {value("document.querySelector('#schreibtisch').inert")=="true"}
        check(faultVault.read()!!.getJSONObject("data").getJSONArray("notizen").getJSONObject(0).getString("titel")=="Synthetic fault B")
        js("Tablet.receive({callback:'cancelled',payload:{}}); Tablet.receive({callback:'error',payload:'late cancellation'}); OrganizerTest.daten().notizen[0].titel='STALE A'; Tablet.flush(); OrganizerTest.speichereJetzt(); return true")
        SystemClock.sleep(700)
        check(faultVault.read()!!.getJSONObject("data").getJSONArray("notizen").getJSONObject(0).getString("titel")=="Synthetic fault B")
        capture("a2-post-rename-fenced"); pass("actual Android post-rename checkpoint, native host fence and stale UI rejection")
        reloadVerified(); check(value("OrganizerTest.daten().notizen[0].titel")==JSONObject.quote("Synthetic fault B"))
        saved(); pass("fresh generation/readback restores B, not A")
    }
    private fun printPdf() {
        launch(); raw("OrganizerTest.wechsel('notizen')"); SystemClock.sleep(250)
        documentControl("tablet-print.pdf",delete=true)
        raw("OrganizerTest.oeffneDruckvorschau()")
        SystemClock.sleep(300); dump("print-selection")
        js("NativeScenario.click('#druck-schleier button','All'); return true")
        tapExpression("document.querySelector('#druck-schleier .druck-fuss button')")
        waitFor("Android print spooler") {nodes().any {it.packageName?.toString()?.contains("printspooler")==true}}
        dump("print-spooler"); capture("print-spooler")
        val printer=nodes().firstOrNull {it.text?.toString()?.contains("Save as PDF")==true}
        if(printer==null) {clickNode("Select a printer"); clickNode("Save as PDF")}
        val save=nodes().firstOrNull {it.contentDescription?.toString() in listOf("Save to PDF","Save as PDF","Save") || it.viewIdResourceName?.endsWith("/print_button")==true}
            ?: error("Print PDF action missing")
        check(save.performAction(AccessibilityNodeInfo.ACTION_CLICK)); SystemClock.sleep(500)
        selectProvider(); setNativeText("tablet-print.pdf"); clickNode("Save")
        SystemClock.sleep(1500)
        val bytes=documentControl("tablet-print.pdf")
        check(String(bytes.copyOfRange(0,5))=="%PDF-"); File(out,"tablet-print.pdf").writeBytes(bytes)
        pass("actual PrintManager/Print UI/SAF PDF file",bytes.size)
    }
    private fun customTimeKeyboard() {
        launch(); shell("settings put system time_12_24 24")
        raw("OrganizerTest.wechsel('custom')"); SystemClock.sleep(250)
        raw("document.querySelector('.custom-modul-appointments .custom-modul-kopf-aktionen button').click()")
        SystemClock.sleep(250)
        js("NativeScenario.set('.custom-titel-zeile input','Synthetic keyboard custom time');return true")
        tapExpression("document.querySelector('.custom-eintrag-formular input[type=time]')")
        waitFor("native Android time picker") {nodes().any {it.className?.toString()?.contains("TimePicker")==true}}
        val toggle=nodes().firstOrNull {it.viewIdResourceName=="android:id/toggle_mode" || it.contentDescription?.toString()?.contains("text input")==true}
        if(toggle!=null) {check(toggle.performAction(AccessibilityNodeInfo.ACTION_CLICK)); SystemClock.sleep(250)}
        val fields=nodes().filter {it.className?.toString()=="android.widget.EditText" && it.isVisibleToUser}
        check(fields.size>=2) {"Native keyboard time fields absent"}
        for((field,text) in fields.take(2).zip(listOf("13","45"))) {
            check(field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,Bundle().apply {putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,"")}))
            field.performAction(AccessibilityNodeInfo.ACTION_FOCUS); sendStringSync(text)
        }
        clickNode("android:id/button1")
        waitFor("time picker writes WebView input") {value("document.querySelector('.custom-eintrag-formular input[type=time]').value")==JSONObject.quote("13:45")}
        js("NativeScenario.click('.custom-eintrag-aktionen button','Add');return true"); saved()
        check(data().getJSONObject("customOrganizer").toString().contains("13:45"))
        pass("touchscreen native time picker plus real hardware key events; no wheel emulation")
    }
    private fun notifications(reboot:Boolean) {
        launch(); shell("pm grant ${targetContext.packageName} android.permission.POST_NOTIFICATIONS")
        raw("Tablet.action('tablet_notifications')"); waitFor("native notification consent") {nodes().any {it.className?.toString()=="android.widget.CheckBox"}}
        val boxes=nodes().filter {it.className?.toString()=="android.widget.CheckBox"}
        if(!boxes[0].isChecked) boxes[0].performAction(AccessibilityNodeInfo.ACTION_CLICK)
        if(boxes[1].isChecked) boxes[1].performAction(AccessibilityNodeInfo.ACTION_CLICK)
        clickNode("android:id/button1"); SystemClock.sleep(300)
        val at=((System.currentTimeMillis()/60000)+2)*60000
        val due=java.time.Instant.ofEpochMilli(at).atZone(java.time.ZoneOffset.UTC)
        val date=due.toLocalDate().toString(); val time=due.toLocalTime().toString().take(5)
        val prefix=(if(reboot) "Reboot-" else "Live-")+SystemClock.elapsedRealtime()
        val created=scenario("NativeScenario.task('$prefix due','$date','$time',0,true)")
        if(!reboot) {
            scenario("NativeScenario.task('$prefix early','${due.toLocalDate().plusDays(1)}','$time',1,false)")
            js("OrganizerTest.daten().einstellungen.erinnerung.vorlauf=0;return true")
            scenario("NativeScenario.custom('$prefix custom','$date','$time')")
        }
        saved(); val state=vault().read()!!
        check(state.getBoolean("enabled") && !state.getBoolean("customEnabled"))
        pass("native AlarmManager scheduled against real clock",JSONObject().put("now",System.currentTimeMillis()).put("at",at).put("alarms",state.getJSONArray("alarms")))
        File(out,"reboot-target.json").writeText(JSONObject().put("at",at).put("prefix",prefix).put("taskId",created.getString("id")).toString())
        sendKeyDownUpSync(KeyEvent.KEYCODE_HOME)
        if(reboot) return
        waitFor("actual background early and due notifications",125) {
            val names=targetContext.getSystemService(NotificationManager::class.java).activeNotifications.map {it.notification.extras.getCharSequence("android.text")?.toString()}
            names.contains("$prefix due") && names.contains("$prefix early")
        }
        check(targetContext.getSystemService(NotificationManager::class.java).activeNotifications.none {
            it.notification.extras.getCharSequence("android.text")?.toString()?.contains("$prefix custom")==true
        })
        pass("actual AlarmManager receiver posted early-only and due notifications while backgrounded")
        pass("future custom appointment not delivered with native custom consent off")
        check(vault().read()!!.getJSONObject("delivered").length()>=2); pass("native encrypted delivery receipts persisted")
    }
    private fun verifyReboot() {
        val target=JSONObject(File(out,"reboot-target.json").readText())
        waitFor("actual post-reboot reminder notification",125) {
            targetContext.getSystemService(NotificationManager::class.java).activeNotifications.any {it.notification.extras.getCharSequence("android.text")?.toString()==target.getString("prefix")+" due"}
        }
        check(!vault().read()!!.getBoolean("customEnabled")); pass("actual reboot receiver, Keystore reload, notification and custom consent off")
    }
    private fun shell(text:String):String = uiAutomation.executeShellCommand(text).use {android.os.ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().readText()}
}
