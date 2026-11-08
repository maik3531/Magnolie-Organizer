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
