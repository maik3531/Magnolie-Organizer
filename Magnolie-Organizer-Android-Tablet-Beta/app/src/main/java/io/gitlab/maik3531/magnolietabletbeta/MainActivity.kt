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
import androidx.webkit.WebSettingsCompat
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
    private var calendarExportCount = 0
    private var importToken: String? = null
    private var documentBusy = false
    private var documentRequests = DocumentRequests()
    @Volatile private var ready = false
    @Volatile private var startupReadyAtElapsed = 0L
    private val startupOriginMs = android.os.SystemClock.elapsedRealtime()
    private enum class StartupPhase { CREATE_BEGIN, WEBVIEW_CREATE_BEGIN, WEBVIEW_CREATE_END,
        LOAD_URL, PAGE_STARTED, PAGE_VISIBLE, PAGE_FINISHED, BOOTSTRAP_REQUEST,
        VAULT_OPEN_BEGIN, VAULT_OPEN_END, INIT_REPLY, PAGE_ACKNOWLEDGED,
        ACTIVATION_BEGIN, ACTIVATION_END, NATIVE_READY, READY_REPLY }
    private fun startupMark(event: StartupPhase, epoch: Int = generation) {
        val now = android.os.SystemClock.elapsedRealtime()
        android.util.Log.d("MagnolieStartup", "event=${event.name} pid=${android.os.Process.myPid()} generation=$epoch elapsedRealtimeMs=$now sinceCreateMs=${now-startupOriginMs}")
    }
    private var printing = false
    private val network = java.util.concurrent.Executors.newSingleThreadExecutor()
    private val calendarImportWorker = java.util.concurrent.Executors.newSingleThreadExecutor()
    private val accountNetwork = java.util.concurrent.Executors.newSingleThreadExecutor()
    @Volatile private var accountCancellation: DavCancellation? = null
    private fun cancelAccountDiscovery() { accountCancellation?.cancel(); accountCancellation = null }
    private val systemSourceWorker = java.util.concurrent.Executors.newSingleThreadExecutor()
    @Volatile private var systemSourceControl: AndroidSystemSources.Control? = null
    private data class PendingSystemAccess(val request: SystemSourceRequest, val epoch: Int, val session: DocumentSession, val code: Int)
    private var systemPermissionGate = SystemPermissionGate.restore(currentProcess=SYSTEM_PERMISSION_PROCESS)
    private var pendingSystemAccess: PendingSystemAccess? = null
    private fun cancelSystemSources() {
        systemSourceControl?.cancel(); systemSourceControl = null
    }
    private fun dispatchSystemSources(message: JSONObject, epoch: Int, session: DocumentSession) {
        val request = SystemSourceRequest.parse(message)
        if (pendingSystemAccess == null) systemPermissionGate.clearIfAlreadyGranted {
            checkSelfPermission(AndroidSystemSources.permission(it)) == android.content.pm.PackageManager.PERMISSION_GRANTED
        }
        if (request.kind != null && systemPermissionGate.pending != null) {
            respond("edsStatus",JSONObject().put("requestId",request.requestId).put("android",true)
                .put("systemAccountSyncImplemented",false).put("fehlerCode","permission_request_pending")
                .put("fehler",getString(R.string.unavailable)),epoch)
            return // Keep the original OS request until its correlated callback arrives.
        }
        val kind = request.kind
        if (kind != null) { systemSourceControl?.cancel(); systemSourceControl = null }
        if (kind != null && checkSelfPermission(AndroidSystemSources.permission(kind)) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            val code = systemPermissionGate.begin(kind)
            pendingSystemAccess = PendingSystemAccess(request,epoch,session,code)
            try { requestPermissions(arrayOf(AndroidSystemSources.permission(kind)),code) }
            catch (_: Exception) { systemPermissionGate.finish(code); pendingSystemAccess = null; readSystemSources(request,epoch,session) }
        } else readSystemSources(request,epoch,session)
    }
    private fun readSystemSources(request: SystemSourceRequest, epoch: Int, session: DocumentSession) {
        systemSourceControl?.cancel()
        val control = AndroidSystemSources.Control().also { systemSourceControl = it }
        systemSourceWorker.execute {
            try {
                if (!accountCurrent(epoch,session) || systemSourceControl !== control) return@execute
                var failed = false
                val snapshots = try { AndroidSystemSources(applicationContext).status(control) }
                    catch (_: Exception) { failed = true; emptyMap() }
                if (!accountCurrent(epoch,session) || systemSourceControl !== control) return@execute
                AndroidStore.io.execute sourceStatus@{
                    if (!accountCurrent(epoch,session) || systemSourceControl !== control) return@sourceStatus
                    val dav = try { DavAccountBridgeRequest.sources(AndroidDavAccounts.service(this).status(),request.requestId) }
                        catch (_: Exception) { JSONObject().put("android",true).put("systemAccountSyncImplemented",false)
                            .put("fehlerCode","account_unavailable").put("fehler",getString(R.string.unavailable)) }
                    val payload = SystemSourceBridge.merge(dav,snapshots,request.requestId)
                    if (failed) payload.put("fehlerCode","provider_unavailable").put("fehler",getString(R.string.unavailable))
                    runOnUiThread {
                        if (accountCurrent(epoch,session) && systemSourceControl === control) respond("edsStatus",payload,epoch)
                    }
                }
            } finally { control.close() }
        }
    }

    @Volatile private var holidayCancellation: DavCancellation? = null
    private fun cancelHolidayFetch() { holidayCancellation?.cancel(); holidayCancellation = null }
    private val printViews = mutableListOf<WebView>()
    private val appName get() = applicationInfo.loadLabel(packageManager).toString()

    companion object {
        private val SYSTEM_PERMISSION_PROCESS = java.util.UUID.randomUUID().toString()
        const val ORIGIN = "https://appassets.androidplatform.net"
        const val START = "$ORIGIN/assets/web/index.html"
        fun allowedOrigin(uri: Uri): Boolean = trustedOrigin(uri.toString())
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startupMark(StartupPhase.CREATE_BEGIN)
        documentRequests = DocumentRequests(savedInstanceState?.getInt("nextDocumentCode",100) ?: 100)
        systemPermissionGate = SystemPermissionGate.restore(savedInstanceState?.getInt("nextSystemAccessCode",1000) ?: 1000,
            savedInstanceState?.getInt("systemAccessPendingCode",-1)?.takeIf {it>=1000},
            savedInstanceState?.getString("systemAccessPendingKind"),savedInstanceState?.getString("systemAccessProcess"),SYSTEM_PERMISSION_PROCESS)
        window.setFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE,
            android.view.WindowManager.LayoutParams.FLAG_SECURE)
        startupMark(StartupPhase.WEBVIEW_CREATE_BEGIN)
        web = WebView(this)
        startupMark(StartupPhase.WEBVIEW_CREATE_END)
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
                cancelHolidayFetch(); cancelAccountDiscovery(); cancelSystemSources()
                generation++; proxy = null; ready = false; startupReadyAtElapsed = 0L
                documentSession = null; bootstrapStarted = false; restoreFenced = false
                exporting = null; importToken = null; documentBusy = false
                documentRequests.cancel()
                startupMark(StartupPhase.PAGE_STARTED)
            }
            override fun onPageCommitVisible(view: WebView, url: String) { startupMark(StartupPhase.PAGE_VISIBLE) }
            override fun onPageFinished(view: WebView, url: String) { startupMark(StartupPhase.PAGE_FINISHED) }
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                cancelHolidayFetch(); cancelAccountDiscovery(); cancelSystemSources()
                generation++; ready = false; startupReadyAtElapsed = 0L; proxy = null; documentSession = null
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
        startupMark(StartupPhase.LOAD_URL)
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
            mediaPlaybackRequiresUserGesture = true
            if (WebViewFeature.isFeatureSupported(WebViewFeature.SAFE_BROWSING_ENABLE))
                WebSettingsCompat.setSafeBrowsingEnabled(this,true)
            cacheMode = WebSettings.LOAD_NO_CACHE
        }
    }
    private fun blocked() = WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden", emptyMap(), ByteArrayInputStream(byteArrayOf()))
    private fun respond(callback: String, payload: Any, epoch: Int = generation) {
        runOnUiThread {
            if (!isDestroyed && epoch == generation) {
                val target = proxy
                target?.postMessage(JSONObject().put("callback", callback).put("payload", payload).toString())
                if (target != null && callback == "init") startupMark(StartupPhase.INIT_REPLY, epoch)
                if (target != null && callback == "ready") startupMark(StartupPhase.READY_REPLY, epoch)
            }
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

    private fun openDocument(intent: Intent, export: Boolean, epoch: Int, session: DocumentSession,
                             format: ImportFormat = ImportFormat.JSON, requestId: String? = null) {
        if (!currentPage(epoch,session)) return
        try {
            val request = documentRequests.begin(export,epoch,session,format,requestId)
            startActivityForResult(intent,request.code)
        } catch (_: Exception) { cancelDocument(); respond("error",getString(R.string.unavailable),epoch) }
    }
    private fun work(onError: (Exception) -> Unit = { error ->
        if (error is CommitFailure && error.outcome != "before-commit") {
            cancelAccountDiscovery(); cancelSystemSources(); ready = false; startupReadyAtElapsed = 0L; restoreFenced = true
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
    // Account revisions are independent from saves to this page's Organizer book.
    // Same-session authority survives a pending book-save ACK, but never a reload/restore.
    private fun accountCurrent(epoch: Int, session: DocumentSession): Boolean =
        !isDestroyed && epoch == generation && documentSession?.id == session.id && ready && !restoreFenced

    private fun accountReply(callback: String, payload: JSONObject, epoch: Int, session: DocumentSession,
                             cancellation: DavCancellation? = null) {
        runOnUiThread {
            if (accountCurrent(epoch,session) && (cancellation == null || accountCancellation === cancellation))
                respond(callback,payload,epoch)
        }
    }

    private fun accountFailure(command: String, requestId: String?, error: Exception, epoch: Int,
                               session: DocumentSession, cancellation: DavCancellation? = null) {
        if (error is java.util.concurrent.CancellationException) return
        // Never manufacture an empty provider snapshot to stand in for a failed read.
        AndroidStore.io.execute {
            if (!accountCurrent(epoch,session) || cancellation != null && accountCancellation !== cancellation) return@execute
            val code = DavAccountService.errorCode(error)
            val actual = try { AndroidDavAccounts.service(this).status() } catch (_: Exception) { null }
            val payload = DavAccountBridgeRequest.failure(command,requestId,actual,code)
            accountReply(DavAccountBridgeRequest.callback(command),payload,epoch,session,cancellation)
        }
    }

    private fun dispatchAccount(message: JSONObject, epoch: Int, session: DocumentSession) {
        val command = message.getString("cmd")
        val requestId = (message.opt("requestId") as? String)?.takeIf { it.isNotEmpty() && it.toByteArray().size <= 1024 }
        val request = try { DavAccountBridgeRequest.parse(message) } catch (error: Exception) {
            accountFailure(command,requestId,error,epoch,session); return
        }
        if (request.discovery || command == "baum_briefkasten_speichern") cancelAccountDiscovery()
        val cancellation = if (request.discovery) DavCancellation().also { accountCancellation = it } else null
        AndroidStore.io.execute {
            if (!accountCurrent(epoch,session) || cancellation != null && accountCancellation !== cancellation) return@execute
            try {
                cancellation?.check()
                // Keystore/configuration initialization and mutations never run on the UI thread.
                val service = AndroidDavAccounts.service(this)
                if (request.discovery) {
                    accountNetwork.execute accountDiscovery@{
                        if (!accountCurrent(epoch,session) || accountCancellation !== cancellation) return@accountDiscovery
                        try {
                            cancellation!!.check()
                            val result = service.discover(requireNotNull(request.expectedRevision),cancellation)
                            val payload = if (command == "baum_dav_pruefen")
                                JSONObject(result.connectionTestPayload(requireNotNull(request.requestId)))
                            else JSONObject(result.status.payload(request.requestId))
                            accountReply(request.callback,payload,epoch,session,cancellation)
                        } catch (error: Exception) { accountFailure(command,request.requestId,error,epoch,session,cancellation) }
                    }
                } else {
                    if (!accountCurrent(epoch,session)) return@execute
                    val payload = when (command) {
                        "baum_briefkasten_speichern" -> JSONObject(service.save(requireNotNull(request.expectedRevision),
                            requireNotNull(request.configuration),request.applicationPassword,request.clearPassword)
                            .payload(request.requestId,true))
                        "eds_status" -> DavAccountBridgeRequest.sources(service.status(),request.requestId)
                        else -> JSONObject(service.status().payload(request.requestId))
                    }
                    accountReply(request.callback,payload,epoch,session)
                }
            } catch (error: Exception) { accountFailure(command,request.requestId,error,epoch,session,cancellation) }
        }
    }

    private fun dispatch(message: JSONObject) {
        val epoch = generation
        val cmd = message.getString("cmd")
        val session = if (cmd == "bereit") null else DocumentSession(message.getString("session"),message.getString("revision"))
        if (cmd != "bereit") {
            // This timer only reschedules the current persisted state, never its supplied snapshot.
            // A save ACK may still be in transit when the same page's timer fires.
            if (cmd == "erinnerung_einrichten" || cmd == "tablet_calendar_import_done" || cmd in DavAccountBridgeRequest.commands || cmd in SystemSourceRequest.commands) check(session?.id == documentSession?.id)
            else check(session == documentSession)
            check(!restoreFenced && (ready || cmd == "tablet_loaded"))
        }
        if (cmd in SystemSourceRequest.commands) {
            dispatchSystemSources(message,epoch,requireNotNull(session)); return
        }
        if (cmd in DavAccountBridgeRequest.commands) {
            dispatchAccount(message, epoch, requireNotNull(session)); return
        }
        when (cmd) {
            "bereit" -> {
                check(!bootstrapStarted); bootstrapStarted = true
                startupMark(StartupPhase.BOOTSTRAP_REQUEST, epoch)
                work({ fatal() }) {
                    startupMark(StartupPhase.VAULT_OPEN_BEGIN, epoch)
                    val loaded = AndroidStore.vault(this).openSession()
                    startupMark(StartupPhase.VAULT_OPEN_END, epoch)
                    runOnUiThread { if (epoch == generation) documentSession = loaded.session }
                    respond("init",JSONObject().put("daten",loaded.value?.getJSONObject("data") ?: JSONObject.NULL)
                        .put("session",loaded.session.id).put("revision",loaded.session.revision),epoch)
                }
            }
            "tablet_loaded" -> {
                startupMark(StartupPhase.PAGE_ACKNOWLEDGED, epoch)
                work({ fatal() }) {
                    startupMark(StartupPhase.ACTIVATION_BEGIN, epoch)
                    AndroidStore.vault(this).activate(requireNotNull(session))
                    startupMark(StartupPhase.ACTIVATION_END, epoch)
                    runOnUiThread { if (epoch == generation) {
                        startupReadyAtElapsed = android.os.SystemClock.elapsedRealtime()
                        ready = true
                        startupMark(StartupPhase.NATIVE_READY, epoch)
                    } }
                    respond("ready",JSONObject().put("session",session.id).put("revision",session.revision),epoch)
                }
            }
            "speichern" -> {
                val id = message.getLong("id")
                work({ error ->
                    val reload = !AndroidStore.vault(this).isWritable(requireNotNull(session))
                    if (reload) { cancelAccountDiscovery(); cancelSystemSources(); ready = false; startupReadyAtElapsed = 0L; restoreFenced = true }
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
            "feiertage" -> {
                val authority = requireNotNull(session)
                val requestId = message.opt("requestId") as? String
                require(requestId == null || (requestId.isNotEmpty() && requestId.toByteArray().size <= 1024))
                cancelHolidayFetch()
                val cancellation = DavCancellation().also { holidayCancellation = it }
                val failure: (Exception) -> Unit = {
                    val payload = JSONObject().put("fehler",getString(R.string.failed))
                    if (requestId != null) payload.put("requestId",requestId)
                    if (holidayCancellation === cancellation && documentSession?.id == authority.id && !restoreFenced)
                        respond("feiertageErgebnis",payload,epoch)
                }
                // Obtain persisted preferences on the storage queue; HTTP never blocks saves.
                work(failure) {
                    val vault = AndroidStore.vault(this)
                    vault.requireSession(authority)
                    val selected = vault.read()?.getJSONObject("data")?.optJSONObject("einstellungen")
                        ?.optJSONObject("regional")?.optString("language","system") ?: "system"
                    val language = if (selected == "system") java.util.Locale.getDefault().language else selected
                    val query = HolidayService.Query.fromMessage(message,language)
                    network.execute {
                        try {
                            val payload = HolidayService().fetch(query,cancellation).callbackValue()
                            runOnUiThread {
                                if (holidayCancellation === cancellation && documentSession?.id == authority.id && !restoreFenced)
                                    respond("feiertageErgebnis",payload,epoch)
                            }
                        } catch (error: Exception) { runOnUiThread { failure(error) } }
                    }
                }
            }
            "tablet_import" -> {
                check(!documentBusy)
                val format = when (message.opt("format")) { "json" -> ImportFormat.JSON; "ics" -> ImportFormat.ICS; else -> error("Explicit import format required") }
                val requestId = message.opt("requestId") as? String
                check(format != ImportFormat.ICS || requestId != null && requestId.isNotEmpty() && requestId.toByteArray().size <= 1024)
                documentBusy = true
                openDocument(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = if (format == ImportFormat.ICS) "*/*" else "application/json"
                    if (format == ImportFormat.ICS) putExtra(Intent.EXTRA_MIME_TYPES,arrayOf("text/calendar","application/ics","text/plain","application/octet-stream"))
                },false,epoch,requireNotNull(session),format,requestId)
            }
            "tablet_calendar_import_done" -> {
                val active = documentRequests.active()
                check(active != null && active.format == ImportFormat.ICS && active.session.id == session?.id &&
                    active.requestId == message.opt("requestId") && active.code == message.getInt("pickerToken"))
                check(documentRequests.finish(active.code)); documentBusy = false
            }
            "tablet_export_ics" -> {
                check(!documentBusy)
                val selected = try { CalendarExportRequest.parse(message) } catch (_: Exception) {
                    val id = (message.opt("requestId") as? String)?.takeIf { it.isNotEmpty() && it.toByteArray().size <= 1024 }
                    respond("exportErgebnis",JSONObject().put("requestId",id).put("session",session?.id).put("ok",false),epoch)
                    return
                }
                documentBusy = true
                val request = documentRequests.begin(true,epoch,requireNotNull(session),requestId=selected.requestId,exportFormat=ExportFormat.ICS)
                prepareCalendarExport(selected,request)
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
                            cancelHolidayFetch(); cancelAccountDiscovery(); cancelSystemSources()
                            restoreFenced = true; ready = false; startupReadyAtElapsed = 0L
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
            hint = getString(R.string.password)
            if (Build.VERSION.SDK_INT >= 26) importantForAutofill = android.view.View.IMPORTANT_FOR_AUTOFILL_NO
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
    private fun cancelDocument(requestIdOverride: String? = null) {
        runOnUiThread {
            if (restoreFenced) return@runOnUiThread
            val token = importToken; val session = documentSession
            val requestId = requestIdOverride ?: documentRequests.active()?.requestId
             exporting=null; importToken=null; documentBusy=false
             documentRequests.cancel()
            if (token != null && session != null) work {
                AndroidStore.vault(this).cancelImport(session,token)
                respond("cancelled",JSONObject().put("token",token))
            } else respond("cancelled",JSONObject().also { if (requestId != null) it.put("requestId",requestId) })
        }
    }
    @Deprecated("Platform Activity result API is sufficient for this isolated host")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        val matched = documentRequests.matches(requestCode)
        val pendingRequest = if (matched) documentRequests.active() else null
        val selectedRequestId = pendingRequest?.requestId
        val request = documentRequests.take(requestCode,generation,documentSession) ?: run {
            if (matched) {
                cancelDocument(selectedRequestId)
                if (pendingRequest?.exportFormat == ExportFormat.ICS) calendarExportReply(pendingRequest,false,true)
            }
            return
        }
        if (!documentBusy || !currentPage(request.generation,request.session)) return
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) {
            cancelDocument()
            if (request.exportFormat == ExportFormat.ICS) calendarExportReply(request,false,true)
            return
        }
        if (request.export) {
            val text = exporting ?: run { cancelDocument(); return }
            val count = calendarExportCount
            val write: () -> Unit = {
                check(currentPage(request.generation,request.session) && documentRequests.isActive(request))
                // Success is emitted only after write, flush and close all return.
                CalendarExportRequest.write(contentResolver.openOutputStream(uri,"wt"),text)
                runOnUiThread {
                    if (currentPage(request.generation,request.session) && documentRequests.isActive(request)) {
                        exporting=null; documentBusy=false; documentRequests.finish(request.code)
                        if (request.exportFormat == ExportFormat.ICS) calendarExportReply(request,true,count=count)
                        else respond("notice",getString(R.string.saved),request.generation)
                    } else if (request.exportFormat == ExportFormat.ICS) calendarExportFailed(request)
                }
            }
            if (request.exportFormat == ExportFormat.ICS) {
                try { calendarImportWorker.execute {
                    try { write() } catch (_: Exception) { calendarExportFailed(request) }
                } } catch (_: java.util.concurrent.RejectedExecutionException) { calendarExportFailed(request) }
            } else work({cancelDocument();respond("error",getString(R.string.failed))},write)
        } else if (request.format == ImportFormat.ICS) {
            readCalendar(uri,request)
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
    private fun calendarExportReply(request: DocumentRequests.Request, ok: Boolean, cancelled: Boolean = false, count: Int = 0) {
        runOnUiThread {
            if (!accountCurrent(request.generation,request.session)) return@runOnUiThread
            respond("exportErgebnis",JSONObject().put("requestId",request.requestId).put("session",request.session.id)
                .put("ok",ok).put("abgebrochen",cancelled).put("anzahl",count),request.generation)
        }
    }
    private fun calendarExportFailed(request: DocumentRequests.Request) {
        runOnUiThread {
            if (!accountCurrent(request.generation,request.session) || !documentRequests.isActive(request)) return@runOnUiThread
            documentRequests.cancel(); exporting=null; documentBusy=false
            calendarExportReply(request,false)
        }
    }
    private fun prepareCalendarExport(selected: CalendarExportRequest, request: DocumentRequests.Request) {
        AndroidStore.io.execute {
            if (!calendarCurrent(request)) return@execute
            try {
                AndroidStore.vault(this).requireSession(request.session)
                val book = AndroidStore.vault(this).read()?.getJSONObject("data") ?: error("No saved book")
                val records = selected.records(book)
                val zone = book.optJSONObject("einstellungen")?.optJSONObject("regional")?.optString("timeZone","system") ?: "system"
                calendarImportWorker.execute {
                    try {
                        val text = ICalendarExport.encode(records,selected.kind,zone) {
                            check(calendarCurrent(request) && documentSession == request.session) { "Calendar export authority changed" }
                        }
                        runOnUiThread {
                            if (!calendarCurrent(request)) return@runOnUiThread
                            if (documentSession != request.session) { calendarExportFailed(request); return@runOnUiThread }
                            exporting=text; calendarExportCount=records.size
                            try { startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                                addCategory(Intent.CATEGORY_OPENABLE); type="text/calendar"; putExtra(Intent.EXTRA_TITLE,selected.fileName)
                            },request.code) } catch (_: Exception) { calendarExportFailed(request) }
                        }
                    } catch (_: Exception) { calendarExportFailed(request) }
                }
            } catch (_: Exception) { calendarExportFailed(request) }
        }
    }

    private fun calendarCurrent(request: DocumentRequests.Request): Boolean =
        accountCurrent(request.generation,request.session) && documentRequests.isActive(request)

    private fun readCalendar(uri: Uri, request: DocumentRequests.Request) {
        // Obtain the saved display zone on book IO, then stream/decode independently of saves.
        AndroidStore.io.execute {
            if (!calendarCurrent(request)) return@execute
            val zone = try {
                AndroidStore.vault(this).requireSession(request.session)
                AndroidStore.vault(this).read()?.getJSONObject("data")?.optJSONObject("einstellungen")
                    ?.optJSONObject("regional")?.optString("timeZone","system") ?: "system"
            } catch (_: Exception) { calendarImportFailure(request); return@execute }
            try { calendarImportWorker.execute calendarRead@{
                try {
                    fun checkCurrent() {
                        if (!calendarCurrent(request) || Thread.currentThread().isInterrupted)
                            throw java.util.concurrent.CancellationException()
                        check(documentSession == request.session) { "Book changed during calendar import; retry the selected file" }
                    }
                    checkCurrent()
                    val bytes = contentResolver.openInputStream(uri)?.use { input ->
                        val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                        while (true) {
                            checkCurrent(); val count = input.read(buffer); if (count < 0) break
                            require(output.size().toLong() + count <= ICalendarImport.maximumBytes)
                            output.write(buffer,0,count)
                        }
                        output.toByteArray()
                    } ?: error("No calendar input stream")
                    checkCurrent()
                    val name = contentResolver.query(uri,arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),null,null,null)?.use { cursor ->
                        if (cursor.moveToFirst()) cursor.getString(0)?.takeIf { it.toByteArray().size <= 4096 } else null
                    } ?: "calendar.ics"
                    val result = ICalendarImport.decode(bytes,displayTimeZone=zone,sourceName=name,checkCancelled=::checkCurrent).document
                    require(result.toString().toByteArray(Charsets.UTF_8).size <= 8 * 1024 * 1024)
                    require(listOf("termine","aufgaben","jahrestage").sumOf { result.getJSONArray(it).length() } <= 5000)
                    val payload = JSONObject().put("requestId",request.requestId).put("pickerToken",request.code)
                        .put("session",request.session.id).put("revision",request.session.revision).put("data",result)
                    // Serialize large DTOs off UI; the UI only hands the completed message to WebView.
                    val envelope = JSONObject().put("callback","calendarImport").put("payload",payload).toString()
                    require(envelope.toByteArray(Charsets.UTF_8).size <= 8 * 1024 * 1024 + 4096)
                    runOnUiThread {
                        if (calendarCurrent(request)) {
                            if (documentSession == request.session) proxy?.postMessage(envelope)
                            else calendarImportFailure(request)
                        }
                    }
                } catch (_: java.util.concurrent.CancellationException) { /* Stale bytes never become an import candidate. */ }
                catch (_: Exception) { calendarImportFailure(request) }
            } } catch (_: java.util.concurrent.RejectedExecutionException) { calendarImportFailure(request) }
        }
    }
    private fun calendarImportFailure(request: DocumentRequests.Request) {
        runOnUiThread {
            if (!calendarCurrent(request)) return@runOnUiThread
            documentRequests.finish(request.code); documentBusy = false
            respond("calendarImport",JSONObject().put("requestId",request.requestId)
                .put("session",request.session.id).put("revision",request.session.revision)
                .put("fehler",getString(R.string.import_failed)),request.generation)
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
        val pending = pendingSystemAccess
        // A restored slot may be cleared, but has no request object and cannot reply.
        val matched = systemPermissionGate.finish(requestCode)
        if (matched && pending != null && requestCode == pending.code) {
            pendingSystemAccess = null
            if (accountCurrent(pending.epoch,pending.session)) readSystemSources(pending.request,pending.epoch,pending.session)
        }
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
        outState.putInt("nextSystemAccessCode",systemPermissionGate.nextCode)
        systemPermissionGate.pending?.let {
            outState.putInt("systemAccessPendingCode",it.code);outState.putString("systemAccessPendingKind",it.kind.wire)
        }
        outState.putString("systemAccessProcess",SYSTEM_PERMISSION_PROCESS)
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        cancelHolidayFetch(); cancelAccountDiscovery(); cancelSystemSources(); network.shutdownNow(); accountNetwork.shutdownNow(); systemSourceWorker.shutdownNow(); calendarImportWorker.shutdownNow()
        generation++; ready=false; startupReadyAtElapsed=0L; proxy=null; documentSession=null; documentRequests.cancel()
        printViews.forEach { it.destroy() }; web.destroy(); super.onDestroy()
    }
}
