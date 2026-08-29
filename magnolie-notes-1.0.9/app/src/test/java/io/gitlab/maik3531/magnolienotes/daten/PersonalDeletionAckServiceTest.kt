package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.After
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import javax.crypto.KeyGenerator

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class PersonalDeletionAckServiceTest {
    private lateinit var context: Context

    @Before fun setUp() {
        val base: Context = ApplicationProvider.getApplicationContext()
        context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
        }
        context.filesDir.listFiles()?.forEach { if (it.isDirectory) it.deleteRecursively() else it.delete() }
        val field = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
        field.set(null, null)
    }

    @After fun tearDown() {
        val field = Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }
        field.set(null, null)
    }

    @Test fun `terminal ack remains tied to pending immutable decision`() {
        val runId = uuid(1)
        val proposalId = uuid(2)
        val decisionId = uuid(3)
        val clock = listOf(PersonalSyncClock(uuid(4), 1))
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val service = Ablage.fuerTest(context, key = { key })
        service.personalSyncStageProposals(runId, "peer", listOf(PersonalDeletionProposal(
            run_id = runId, proposal_id = proposalId, kind = "note", id = "note-id", clock = clock,
            prior_hash = "hash", deleted_ms = 1, source_device = "peer")))

        assertEquals("applied", service.personalSyncDecide("peer", proposalId, decisionId, "restore"))
        service.personalSyncDecisionStopped(decisionId, "terminal:conflict")

        val pending = service.personalSyncPendingDecisions().single()
        assertEquals(PendingPersonalDecision("peer", runId, decisionId, proposalId, "restore", clock,
            "terminal:conflict"), pending)
    }

    private fun uuid(value: Int) = "%08x-0000-4000-8000-%012x".format(value, value)
}
