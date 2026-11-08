package io.gitlab.maik3531.magnolietabletbeta

/** Native test driver policy; a breadcrumb is not a clickable provider root row. */
data class NativeDocumentProviderState(val selectedBreadcrumb: Boolean, val rootsListVisible: Boolean, val matchingRootVisible: Boolean) {
    enum class Action { ALREADY_SELECTED, SELECT_ROOT, OPEN_ROOTS, WAIT_FOR_ROOT }
    fun action(): Action = when {
        rootsListVisible && matchingRootVisible -> Action.SELECT_ROOT
        rootsListVisible -> Action.WAIT_FOR_ROOT
        selectedBreadcrumb -> Action.ALREADY_SELECTED
        else -> Action.OPEN_ROOTS
    }
}

/** DocumentsUI's public positive button ID is stable even when its caption is SAVE or localized. */
object NativeDocumentProviderControls {
    fun isSaveButton(packageName: String?, resourceId: String?, className: String?, visible: Boolean, enabled: Boolean, clickable: Boolean): Boolean =
        packageName in setOf("com.android.documentsui", "com.google.android.documentsui") &&
            resourceId == "android:id/button1" && className == "android.widget.Button" && visible && enabled && clickable
}
