package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PersonalActorCompletionScopeTest {
    @Test fun exactNativeTargetsAllowOnlyTheirDeclaredMembershipChange() {
        val fixture = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/notes-actor-completion-scope.json")).readText()).jsonObject
        val cases = fixture.getValue("cases").jsonArray
        assertEquals(36, cases.size)
        for (raw in cases) {
            val item = raw.jsonObject; val beforeBytes = TelefonKanonisch.bytes(item)
            val name = item.getValue("name").jsonPrimitive.content
            val run = item.getValue("run_id").jsonPrimitive.content
            val before = item.getValue("before").jsonObject; val targets = item.getValue("native_targets").jsonArray
            val decisions = item.getValue("decisions").jsonArray; val after = item.getValue("actual_after").jsonObject
            val result = runCatching { PersonalSyncActor.requireCompletionScope(run, before, targets, decisions, after) }
            val valid = item.getValue("valid").jsonPrimitive.boolean
            assertEquals(name, valid, result.isSuccess)
            if (valid) {
                assertEquals(name, after.getValue("members"), PersonalSyncActor.completionMembers(run, before, targets, decisions))
                assertEquals(name, PhoneContentScope.reference(after), result.getOrThrow())
            }
            assertArrayEquals(name, beforeBytes, TelefonKanonisch.bytes(item))
        }
    }
}
