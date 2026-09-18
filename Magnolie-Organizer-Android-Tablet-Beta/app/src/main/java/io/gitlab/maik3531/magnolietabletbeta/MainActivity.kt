package io.gitlab.maik3531.magnolietabletbeta

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.print.PrintManager
import android.text.InputType
import android.webkit.*
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.webkit.JavaScriptReplyProxy
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream

class MainActivity : Activity() {
    private lateinit var web: WebView
    private var proxy: JavaScriptReplyProxy? = null
    @Volatile private var generation = 0
    @Volatile private var documentSession: DocumentSession? = null
    private var bootstrapStarted = false
    @Volatile private var restoreFenced = false
    private var exporting: String? = null
    private var importToken: String? = null
    private var documentBusy = false
    private var documentRequests = DocumentRequests()
    private var ready = false
    private var printing = false
    private val printViews = mutableListOf<WebView>()
    private val appName get() = applicationInfo.loadLabel(packageManager).toString()

    companion object {
        const val ORIGIN = "https://appassets.androidplatform.net"
        const val START = "$ORIGIN/assets/web/index.html"
        fun allowedOrigin(uri: Uri): Boolean = trustedOrigin(uri.toString())
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        documentRequests = DocumentRequests(savedInstanceState?.getInt("nextDocumentCode",100) ?: 100)
        window.setFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE,
            android.view.WindowManager.LayoutParams.FLAG_SECURE)
        web = WebView(this)
        // Target 35 edge-to-edge: keep binder controls outside system bars and the IME.
        web.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.ime())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        web.setBackgroundColor(Color.rgb(38,55,46))
        secureSettings(web)
        web.settings.javaScriptEnabled = true
        web.settings.builtInZoomControls = true
        web.settings.displayZoomControls = false
        web.settings.setSupportZoom(true)
        WebView.setWebContentsDebuggingEnabled(false)
        CookieManager.getInstance().setAcceptCookie(false)
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build()
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse =
                if (allowedOrigin(request.url)) loader.shouldInterceptRequest(request.url) ?: blocked() else blocked()
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                !request.isForMainFrame || request.url.toString() != START
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) = handler.cancel()
            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                generation++; proxy = null; ready = false
                documentSession = null; bootstrapStarted = false; restoreFenced = false
                exporting = null; importToken = null; documentBusy = false
                documentRequests.cancel()
            }
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                generation++; ready = false; proxy = null; documentSession = null
                documentRequests.cancel(); view.destroy(); fatal(); return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                callback.onReceiveValue(null)
                respond("error",getString(R.string.unavailable))
                return true
            }
        }
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) { fatal(); return }
        WebViewCompat.addWebMessageListener(web, "TabletNative", setOf(ORIGIN)) { _, message, origin, mainFrame, reply ->
            if (!mainFrame || !allowedOrigin(origin) || web.url != START) return@addWebMessageListener
            proxy = reply
            try {
                val raw = message.data ?: error("String JSON required")
                require(raw.length <= MAX_BYTES)
                dispatch(parseObject(raw))
            } catch (_: Exception) { respond("error", getString(R.string.failed)) }
        }
        setContentView(web)
        web.loadUrl(START)
    }

    @Suppress("DEPRECATION")
    private fun secureSettings(view: WebView) {
        view.settings.apply {
            allowFileAccess = false; allowContentAccess = false
            allowFileAccessFromFileURLs = false; allowUniversalAccessFromFileURLs = false
            domStorageEnabled = false; databaseEnabled = false; saveFormData = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            javaScriptCanOpenWindowsAutomatically = false; setSupportMultipleWindows(false)
            mediaPlaybackRequiresUserGesture = true; safeBrowsingEnabled = true
            cacheMode = WebSettings.LOAD_NO_CACHE
        }
    }
    private fun blocked() = WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden", emptyMap(), ByteArrayInputStream(byteArrayOf()))
    private fun respond(callback: String, payload: Any, epoch: Int = generation) {
        runOnUiThread {
            if (!isDestroyed && epoch == generation) proxy?.postMessage(JSONObject()
                .put("callback", callback).put("payload", payload).toString())
        }
    }
    private fun fatal() {
        setContentView(TextView(this).apply {
            text = "$appName\n\n${getString(R.string.save_failed)}\n${getString(R.string.unavailable)}"
            setPadding(32,32,32,32); textSize = 20f
        })
    }
    private fun currentPage(epoch: Int, session: DocumentSession): Boolean =
        !isDestroyed && epoch == generation && session == documentSession && !restoreFenced

    private fun openDocument(intent: Intent, export: Boolean, epoch: Int, session: DocumentSession) {
        if (!currentPage(epoch,session)) return
        try {
            val request = documentRequests.begin(export,epoch,session)
            startActivityForResult(intent,request.code)
        } catch (_: Exception) { cancelDocument(); respond("error",getString(R.string.unavailable),epoch) }
    }
    private fun work(onError: (Exception) -> Unit = { error ->
        if (error is CommitFailure && error.outcome != "before-commit") {
            ready = false; restoreFenced = true
            respond("storageBlocked",JSONObject().put("outcome",error.outcome).put("text",getString(R.string.save_failed)))
        } else respond("error",getString(R.string.failed))
    }, action: () -> Unit) {
        val epoch = generation
        AndroidStore.io.execute {
            if (epoch != generation || isDestroyed) return@execute
            try { action() } catch (error: Exception) {
                runOnUiThread { if (epoch == generation && !isDestroyed) onError(error) }
            }
        }
    }
    private fun dispatch(message: JSONObject) {
        val epoch = generation
        val cmd = message.getString("cmd")
        val session = if (cmd == "bereit") null else DocumentSession(message.getString("session"),message.getString("revision"))
        if (cmd != "bereit") {
            // This timer only reschedules the current persisted state, never its supplied snapshot.
            // A save ACK may still be in transit when the same page's timer fires.
            if (cmd == "erinnerung_einrichten") check(session?.id == documentSession?.id)
            else check(session == documentSession)
            check(!restoreFenced && (ready || cmd == "tablet_loaded"))
        }
        when (cmd) {
            "bereit" -> {
                check(!bootstrapStarted); bootstrapStarted = true
                work({ fatal() }) {
                    val loaded = AndroidStore.vault(this).openSession()
                    runOnUiThread { if (epoch == generation) documentSession = loaded.session }
                    respond("init",JSONObject().put("daten",loaded.value?.getJSONObject("data") ?: JSONObject.NULL)
                        .put("session",loaded.session.id).put("revision",loaded.session.revision),epoch)
                }
            }
            "tablet_loaded" -> work({ fatal() }) {
                AndroidStore.vault(this).activate(requireNotNull(session))
                runOnUiThread { if (epoch == generation) ready = true }
                respond("ready",JSONObject().put("session",session.id).put("revision",session.revision),epoch)
            }
            "speichern" -> {
                val id = message.getLong("id")
                work({ error ->
                    val reload = !AndroidStore.vault(this).isWritable(requireNotNull(session))
                    if (reload) { ready = false; restoreFenced = true }
                    respond("gespeichert",JSONObject().put("id",id).put("ok",false)
                        .put("session",session!!.id).put("expectedRevision",session.revision)
                        .put("reloadRequired",reload).put("outcome",(error as? CommitFailure)?.outcome ?: "rejected")
                        .put("fehler",getString(R.string.save_failed)),epoch)
                }) {
                    val state = AndroidStore.vault(this).save(requireNotNull(session),message.getString("text"),message.getJSONArray("alarms"))
                    runOnUiThread { if (epoch == generation) documentSession = DocumentSession(session.id,state.getString("revision")) }
                    respond("gespeichert",JSONObject().put("id",id).put("ok",true).put("session",session.id)
                        .put("expectedRevision",session.revision).put("revision",state.getString("revision")),epoch)
                    try { scheduleReminders(this,state) } catch (_: Exception) { respond("notice",getString(R.string.limits),epoch) }
                }
            }
            "tablet_import" -> {
                check(!documentBusy); documentBusy = true
                openDocument(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type="application/json"
                },false,epoch,requireNotNull(session))
            }
            "tablet_export" -> {
                check(!documentBusy); documentBusy=true
                password { chars -> work({ cancelDocument(); respond("error",getString(R.string.failed)) }) {
                    try {
                        AndroidStore.vault(this).requireSession(requireNotNull(session))
                        val data = AndroidStore.vault(this).read()?.getJSONObject("data") ?: error("No data")
                         val sealed = Portable.seal(data.toString(),chars)
                         runOnUiThread {
                             if (!currentPage(epoch,session)) return@runOnUiThread
                             exporting=sealed
                             openDocument(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                                 addCategory(Intent.CATEGORY_OPENABLE); type="application/json"
                                 putExtra(Intent.EXTRA_TITLE,"Magnolie-Organizer-Android-Tablet-Beta-encrypted.json")
                             },true,epoch,session)
                        }
                    } finally { chars.fill('\u0000') }
                } }
            }
            "tablet_replace" -> {
                check(documentBusy && importToken != null && message.getString("token") == importToken)
                val token = requireNotNull(importToken)
                AlertDialog.Builder(this).setTitle(R.string.restore)
                    .setMessage(getString(R.string.replacement).replace("%(path)s","JSON")+"\n\n"+getString(R.string.limits))
                    .setNegativeButton(R.string.cancel) { _,_ -> cancelDocument() }
                    .setOnCancelListener { cancelDocument() }
                    .setPositiveButton(R.string.restore) { _,_ ->
                        if (epoch == generation && session == documentSession && !restoreFenced) {
                            restoreFenced = true; ready = false
                            work({ error -> respond("restoreFailed",JSONObject().put("token",token)
                                .put("outcome",(error as? CommitFailure)?.outcome ?: "before-commit")
                                .put("text",getString(R.string.import_failed)),epoch) }) {
                                val restored = AndroidStore.vault(this).replace(requireNotNull(session),token)
                                // Storage success is final. Scheduling is a separate, non-transactional follow-up.
                                respond("replaced",JSONObject().put("token",token),epoch)
                                try { scheduleReminders(this,restored) }
                                catch (_: Exception) { respond("notice",getString(R.string.limits),epoch) }
                            }
                        }
                    }.show()
            }
            "tablet_import_cancel" -> {
                check(importToken == message.getString("token")); cancelDocument()
            }
            "tablet_notifications" -> notifications(requireNotNull(session))
            "erinnerung_einrichten" -> work {
                val state = AndroidStore.vault(this).read() ?: error("No saved reminder state")
                scheduleReminders(this,state)
                respond("notice",getString(R.string.limits),epoch)
            }
            "tablet_about" -> AlertDialog.Builder(this).setTitle(appName).setMessage(R.string.limits)
                .setPositiveButton(R.string.close,null).show()
            "drucken" -> printDocument(message.getString("html"))
            "ablage_kopieren" -> {
                val clip = ClipData.newPlainText(appName,message.getString("text"))
                if (Build.VERSION.SDK_INT >= 33) clip.description.extras = android.os.PersistableBundle().apply {
                    putBoolean(android.content.ClipDescription.EXTRA_IS_SENSITIVE,true)
                }
                getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
            }
            "ablage_holen" -> {
                val clip = getSystemService(ClipboardManager::class.java).primaryClip
                respond("clipboard",clip?.getItemAt(0)?.text?.toString() ?: "")
            }
            "beenden_bereit" -> finish()
            "beenden_abgebrochen" -> Unit // Explicit cancellation, not an operation ACK.
            else -> respond("error",getString(R.string.unavailable)+" "+cmd)
        }
    }

    private fun password(next: (CharArray) -> Unit) {
        val epoch = generation
        val field = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            hint = getString(R.string.password); importantForAutofill = android.view.View.IMPORTANT_FOR_AUTOFILL_NO
        }
        val dialog = AlertDialog.Builder(this).setTitle(R.string.password).setView(field)
            .setNegativeButton(R.string.cancel) { _,_ -> field.text.clear(); if (epoch == generation) cancelDocument() }
            .setOnCancelListener { field.text.clear(); if (epoch == generation) cancelDocument() }
            .setPositiveButton(android.R.string.ok,null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (epoch != generation || isDestroyed) { field.text.clear(); dialog.dismiss(); return@setOnClickListener }
                if (field.length() !in 8..1024) { field.error = "8 - 1024"; return@setOnClickListener }
                val chars = field.text.toString().toCharArray(); field.text.clear(); dialog.dismiss(); next(chars)
            }
        }
        dialog.show()
    }
    private fun cancelDocument() {
        runOnUiThread {
            if (restoreFenced) return@runOnUiThread
            val token = importToken; val session = documentSession
             exporting=null; importToken=null; documentBusy=false
             documentRequests.cancel()
            if (token != null && session != null) work {
                AndroidStore.vault(this).cancelImport(session,token)
                respond("cancelled",JSONObject().put("token",token))
            } else respond("cancelled",JSONObject())
        }
    }
    @Deprecated("Platform Activity result API is sufficient for this isolated host")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        val matched = documentRequests.matches(requestCode)
        val request = documentRequests.take(requestCode,generation,documentSession) ?: run {
            if (matched) cancelDocument()
            return
        }
        if (!documentBusy || !currentPage(request.generation,request.session)) return
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) { cancelDocument(); return }
        if (request.export) {
            val text = exporting ?: run { cancelDocument(); return }
            work({cancelDocument();respond("error",getString(R.string.failed))}) {
                // SAF providers own commit durability. Propagate all write/flush/close errors, never claim atomic SAF writes.
                contentResolver.openOutputStream(uri,"wt")?.use { it.write(text.toByteArray(Charsets.UTF_8)); it.flush() }
                    ?: error("No output stream")
                runOnUiThread {
                    if (currentPage(request.generation,request.session)) {
                        exporting=null; documentBusy=false; respond("notice",getString(R.string.saved),request.generation)
                    }
                }
            }
        } else work({cancelDocument();respond("error",getString(R.string.import_failed))}) {
            val bytes = contentResolver.openInputStream(uri)?.use { input ->
                val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                while (true) { val n = input.read(buffer); if (n < 0) break
                    require(output.size()+n <= MAX_BYTES); output.write(buffer,0,n) }
                output.toByteArray()
            } ?: error("No input stream")
            val text = decodeUtf8(bytes)
            val obj = parseObject(text)
            if (obj.has("ciphertext")) runOnUiThread {
                if (currentPage(request.generation,request.session)) password { chars ->
                    work({cancelDocument();respond("error",getString(R.string.import_failed))}) {
                        try { offerImport(Portable.open(text,chars),request) } finally { chars.fill('\u0000') }
                    }
                }
            } else { validateData(obj); offerImport(text,request) }
        }
    }
    private fun offerImport(text: String, request: DocumentRequests.Request) {
        val epoch = request.generation
        val session = request.session
        if (!currentPage(epoch,session)) return
        val token = AndroidStore.vault(this).prepareImport(session,text)
        runOnUiThread {
            if (currentPage(epoch,session)) {
                importToken=token
                respond("importCandidate",JSONObject().put("token",token).put("text",text),epoch)
            }
        }
    }
    private fun notifications(session: DocumentSession) = work {
        val epoch = generation
        AndroidStore.vault(this).requireSession(session)
        val state = AndroidStore.vault(this).read() ?: error("No state")
        runOnUiThread {
            if (epoch != generation || session != documentSession || restoreFenced || isDestroyed) return@runOnUiThread
            val enabled = CheckBox(this).apply { text=getString(R.string.notifications); isChecked=state.optBoolean("enabled") }
            val custom = CheckBox(this).apply { text=getString(R.string.custom); isChecked=state.optBoolean("customEnabled") }
            val layout = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(24,12,24,12)
                addView(TextView(context).apply { text=getString(R.string.limits) }); addView(enabled); addView(custom) }
            AlertDialog.Builder(this).setTitle(R.string.notifications).setView(layout)
                .setNegativeButton(R.string.cancel,null).setPositiveButton(android.R.string.ok) { _,_ ->
                    val allow = enabled.isChecked
                    val allowCustom = custom.isChecked
                    work {
                        val vault = AndroidStore.vault(this)
                        vault.requireSession(session)
                        val current = vault.read() ?: error("No state")
                        current.put("enabled",allow).put("customEnabled",allowCustom)
                        vault.write(current)
                        scheduleReminders(this,current)
                        respond("notificationConsent",JSONObject().put("enabled",allow)
                            .put("session",session.id).put("revision",session.revision),epoch)
                        runOnUiThread {
                            if (allow && Build.VERSION.SDK_INT >= 33 && !notificationPermission(this))
                                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),12)
                            else respond("notice",if (allow && !notificationPermission(this))
                                getString(R.string.unavailable) else getString(R.string.saved))
                        }
                    }
                }.show()
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if (requestCode == 12) work {
            AndroidStore.vault(this).read()?.let { scheduleReminders(this,it) }
            respond("notice",if(notificationPermission(this)) getString(R.string.saved) else getString(R.string.unavailable))
        }
    }
    private fun printDocument(html: String) {
        require(html.toByteArray().size <= MAX_BYTES)
        check(!printing)
        printing = true
        val view = WebView(this); secureSettings(view); view.settings.javaScriptEnabled=false
        printViews.add(view)
        view.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(v: WebView, r: WebResourceRequest) = blocked()
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest) = true
            override fun onPageFinished(v: WebView, url: String) {
                val delegate = v.createPrintDocumentAdapter(appName)
                val adapter = object : android.print.PrintDocumentAdapter() {
                    override fun onStart() = delegate.onStart()
                    override fun onLayout(old: android.print.PrintAttributes?, new: android.print.PrintAttributes?,
                        signal: android.os.CancellationSignal?, callback: LayoutResultCallback?, extras: Bundle?) =
                        delegate.onLayout(old,new,signal,callback,extras)
                    override fun onWrite(pages: Array<out android.print.PageRange>?, destination: android.os.ParcelFileDescriptor?,
                        signal: android.os.CancellationSignal?, callback: WriteResultCallback?) =
                        delegate.onWrite(pages,destination,signal,callback)
                    override fun onFinish() {
                        delegate.onFinish(); printViews.remove(v); v.destroy(); printing=false
                    }
                }
                try { getSystemService(PrintManager::class.java).print(appName,adapter,null) }
                catch (_: Exception) { adapter.onFinish(); respond("error",getString(R.string.failed)) }
            }
        }
        // No bridge, JavaScript, external resources or automatic success message in print documents.
        view.loadDataWithBaseURL(ORIGIN,html,"text/html","UTF-8",null)
    }
    override fun onPause() { if (ready) web.evaluateJavascript("window.Tablet.flush()",null); super.onPause() }
    override fun onResume() { super.onResume(); if (ready) work { AndroidStore.vault(this).read()?.let {scheduleReminders(this,it)} } }
    @Deprecated("Delegate back to the canonical unsaved-editor guard")
    override fun onBackPressed() { if(ready) web.evaluateJavascript("window.App.vorBeenden()",null) else super.onBackPressed() }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("nextDocumentCode",documentRequests.nextCode)
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        generation++; ready=false; proxy=null; documentSession=null; documentRequests.cancel()
        printViews.forEach { it.destroy() }; web.destroy(); super.onDestroy()
    }
}
