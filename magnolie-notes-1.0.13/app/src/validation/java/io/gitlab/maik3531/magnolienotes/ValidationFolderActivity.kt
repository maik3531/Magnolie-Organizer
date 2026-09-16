package io.gitlab.maik3531.magnolienotes

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.provider.DocumentsContract
import io.gitlab.maik3531.magnolienotes.sicherung.AndroidAutoSicherung

/** Opt-in validation: routes a real SAF result only to the newly created synthetic folder. */
class ValidationFolderActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        check(packageName.endsWith(".validation"))
        val folder = requireNotNull(intent.getStringExtra("folder"))
        require(folder.matches(Regex("MagnolieNativeValidation-[0-9a-f-]{36}")))
        if (savedInstanceState == null) startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri(
                "com.android.externalstorage.documents", "primary:Documents/$folder"))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION)
        }, 1)
    }
    @Deprecated("Native validation of the existing SAF result boundary")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (requestCode == 1 && resultCode == RESULT_OK && uri != null &&
            uri.authority == "com.android.externalstorage.documents" &&
            DocumentsContract.getTreeDocumentId(uri) == "primary:Documents/${intent.getStringExtra("folder")}") {
            AndroidAutoSicherung.hole(this).ordnerSetzen(uri)
            getSharedPreferences("native_validation", 0).edit().putString("saf_uri", uri.toString()).commit()
        }
        finish()
    }
}
