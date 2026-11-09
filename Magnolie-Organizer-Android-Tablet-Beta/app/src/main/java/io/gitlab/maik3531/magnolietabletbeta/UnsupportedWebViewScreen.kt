package io.gitlab.maik3531.magnolietabletbeta

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Native, pre-bootstrap view. External actions occur only inside button callbacks. */
internal object UnsupportedWebViewScreen {
    fun show(activity: Activity, appName: String, providerPackage: String?, providerLabel: String?, providerVersion: String?, retry: () -> Unit) {
        val padding = (24 * activity.resources.displayMetrics.density).toInt()
        val content = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; setPadding(padding,padding,padding,padding) }
        fun text(value: String, size: Float) { content.addView(TextView(activity).apply { text=value; textSize=size; setPadding(0,0,0,padding/2) }) }
        text(appName,20f); text(activity.getString(R.string.webview_title),24f)
        text(activity.getString(R.string.webview_body),17f)
        text(if(providerPackage==null) activity.getString(R.string.webview_unknown_provider)
            else listOfNotNull(providerLabel ?: providerPackage,providerVersion,providerPackage.takeIf {it!=(providerLabel ?: providerPackage)}).joinToString("\n"),16f)
        fun launch(intent: Intent): Boolean = try { activity.startActivity(intent); true }
            catch (_: ActivityNotFoundException) { false } catch (_: SecurityException) { false }
        fun unavailable() { Toast.makeText(activity,R.string.webview_no_update,Toast.LENGTH_LONG).show() }
        fun button(label: Int, enabled: Boolean=true, action: () -> Unit) {
            content.addView(Button(activity).apply { setText(label); isEnabled=enabled; setOnClickListener { action() } })
        }
        button(R.string.webview_update,providerPackage!=null) {
            providerPackage?.let { name ->
                val market=Uri.Builder().scheme("market").authority("details").appendQueryParameter("id",name).build()
                val listing=Uri.Builder().scheme("https").authority("play.google.com").path("/store/apps/details").appendQueryParameter("id",name).build()
                if(!launch(Intent(Intent.ACTION_VIEW,market)) && !launch(Intent(Intent.ACTION_VIEW,listing))) unavailable()
            }
        }
        button(R.string.webview_settings) {
            val intent=if(providerPackage!=null) Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.fromParts("package",providerPackage,null))
                else Intent(Settings.ACTION_MANAGE_APPLICATIONS_SETTINGS)
            if(!launch(intent)) unavailable()
        }
        button(R.string.webview_retry,action=retry)
        button(R.string.close) { activity.finish() }
        activity.setContentView(ScrollView(activity).apply {
            setOnApplyWindowInsetsListener { view,insets ->
                if(android.os.Build.VERSION.SDK_INT>=30) {
                    val bars=insets.getInsets(android.view.WindowInsets.Type.systemBars())
                    view.setPadding(bars.left,bars.top,bars.right,bars.bottom)
                } else {
                    @Suppress("DEPRECATION")
                    view.setPadding(insets.systemWindowInsetLeft,insets.systemWindowInsetTop,insets.systemWindowInsetRight,insets.systemWindowInsetBottom)
                }
                insets
            }
            addView(content)
        })
    }
}
