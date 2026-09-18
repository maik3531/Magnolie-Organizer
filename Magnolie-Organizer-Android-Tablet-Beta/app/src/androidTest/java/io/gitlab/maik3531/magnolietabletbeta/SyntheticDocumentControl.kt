package io.gitlab.maik3531.magnolietabletbeta

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import java.io.File

/** Test APK only: creates/inspects this synthetic provider's fixtures, never target app data. */
class SyntheticDocumentControl : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val name=intent.getStringExtra("name") ?: return
        require(name.matches(Regex("[A-Za-z0-9._ -]{1,160}")) && name!="." && name!="..")
        val directory=File(context.filesDir,"synthetic-documents").apply {mkdirs()}
        val file=File(directory,name)
        if(intent.getBooleanExtra("delete",false)) {
            if(file.exists()) check(file.delete())
            setResult(Activity.RESULT_OK,"removed synthetic fixture",Bundle().apply {putByteArray("bytes",byteArrayOf())})
            return
        }
        if(intent.hasExtra("text")) {
            val text=requireNotNull(intent.getStringExtra("text")); require(text.length<500000)
            file.outputStream().use {it.write(text.toByteArray())}
        }
        check(file.isFile && file.length()<750000)
        setResult(Activity.RESULT_OK,"synthetic fixture",Bundle().apply {putByteArray("bytes",file.readBytes())})
    }
}
