package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
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
    @Test fun actualSaveControlUsesPositiveButtonIdentityInsteadOfItsUppercaseCaption() {
        // Actual be348 hierarchy has text SAVE, android:id/button1, not text Save.
        assertTrue(NativeDocumentProviderControls.isSaveButton("com.google.android.documentsui", "android:id/button1", "android.widget.Button", true, true, true))
        assertTrue(NativeDocumentProviderControls.isSaveButton("com.android.documentsui", "android:id/button1", "android.widget.Button", true, true, true))
        assertFalse(NativeDocumentProviderControls.isSaveButton("private.documentsui", "android:id/button1", "android.widget.Button", true, true, true))
        assertFalse(NativeDocumentProviderControls.isSaveButton("com.google.android.documentsui", "android:id/button2", "android.widget.Button", true, true, true))
        assertFalse(NativeDocumentProviderControls.isSaveButton("com.google.android.documentsui", "android:id/button1", "android.widget.TextView", true, true, true))
        for(flags in listOf(listOf(false,true,true),listOf(true,false,true),listOf(true,true,false)))
            assertFalse(NativeDocumentProviderControls.isSaveButton("com.google.android.documentsui", "android:id/button1", "android.widget.Button", flags[0], flags[1], flags[2]))
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
