package io.gitlab.maik3531.magnolienotes.telefon

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class TelefonUpdateEmpfaenger : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        // Android permits the foreground request from this system broadcast.
        // Start it here; the service itself waits for application readiness.
        try {
            TelefonDienst.resumeIfEnabled(context)
        } catch (error: IllegalStateException) {
            Log.w("MagnolieStartup", "Phone service update start: ${error.javaClass.simpleName}")
        } catch (error: SecurityException) {
            Log.w("MagnolieStartup", "Phone service update start: ${error.javaClass.simpleName}")
        }
    }
}
