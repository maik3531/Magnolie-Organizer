package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.assertEquals
import org.junit.Test

class NativeDocumentProviderStateTest {
    @Test fun actualA804AlreadySelectedRootDoesNotClickItsNonclickableBreadcrumb() {
        // Actual DocumentsUI hierarchy: root breadcrumb + files, closed drawer.
        assertEquals(NativeDocumentProviderState.Action.ALREADY_SELECTED,
            NativeDocumentProviderState(true, false, false).action())
        // The same current-root title must not bypass an open drawer.
        assertEquals(NativeDocumentProviderState.Action.SELECT_ROOT,
            NativeDocumentProviderState(true, true, true).action())
    }
    @Test fun initialPickerAndPendingDrawerAreDistinctBoundedStates() {
        assertEquals(NativeDocumentProviderState.Action.OPEN_ROOTS,
            NativeDocumentProviderState(false, false, false).action())
        assertEquals(NativeDocumentProviderState.Action.SELECT_ROOT,
            NativeDocumentProviderState(false, true, true).action())
        assertEquals(NativeDocumentProviderState.Action.WAIT_FOR_ROOT,
            NativeDocumentProviderState(true, true, false).action())
    }
}
