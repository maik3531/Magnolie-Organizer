package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient

/** Local document only; the Android print service supplies printer/PDF selection. */
object ZeitDrucken {
    fun attributes(): PrintAttributes = PrintAttributes.Builder()
        .setMediaSize(PrintAttributes.MediaSize.ISO_A4.asPortrait())
        .setMinMargins(PrintAttributes.Margins(787, 197, 787, 197))
        .setColorMode(PrintAttributes.COLOR_MODE_COLOR).build()

    fun starten(context: Context, html: String, title: String, beiFehler: (Throwable) -> Unit) {
        val view = WebView(context)
        var submitted = false
        view.settings.apply {
            javaScriptEnabled = false
            allowFileAccess = false
            allowContentAccess = false
            blockNetworkLoads = true
        }
        view.webViewClient = object : WebViewClient() {
            override fun onPageFinished(web: WebView, url: String?) {
                if (submitted) return
                submitted = true
                try {
                    val delegate = web.createPrintDocumentAdapter(title)
                    val adapter = object : PrintDocumentAdapter() {
                        override fun onStart() { delegate.onStart() }
                        override fun onLayout(oldAttributes: PrintAttributes?, newAttributes: PrintAttributes?,
                                              cancellationSignal: CancellationSignal, callback: LayoutResultCallback, extras: Bundle?) {
                            delegate.onLayout(oldAttributes, newAttributes, cancellationSignal, callback, extras)
                        }
                        override fun onWrite(pages: Array<out PageRange>, destination: ParcelFileDescriptor,
                                             cancellationSignal: CancellationSignal, callback: WriteResultCallback) {
                            delegate.onWrite(pages, destination, cancellationSignal, callback)
                        }
                        override fun onFinish() {
                            try { delegate.onFinish() } finally { web.destroy() }
                        }
                    }
                    checkNotNull(context.getSystemService(PrintManager::class.java).print(title, adapter, attributes()))
                } catch (error: Exception) {
                    android.util.Log.e("MagnolieTimePrint", "Could not open Android print dialog", error)
                    web.destroy()
                    beiFehler(error)
                }
            }

            override fun onReceivedError(web: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame && !submitted) {
                    android.util.Log.e("MagnolieTimePrint", "Local document load failed: ${error.errorCode}: ${error.description}")
                    submitted = true
                    web.destroy()
                    beiFehler(IllegalStateException(error.description.toString()))
                }
            }
        }
        try { view.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null) }
        catch (error: Exception) { view.destroy(); beiFehler(error) }
    }
}
