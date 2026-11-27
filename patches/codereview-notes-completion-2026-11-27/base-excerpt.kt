    @Synchronized internal fun stopPersonalActor(handle: PersonalActorHandle) = synchronized(Ablage.SCHREIBSPERRE) {
        personalActorJournal.retire(handle) { stopActorRunAndPrivateStaging(handle.peerId, handle.runId) }
        personalActorWork.remove(handle.runId)
        personalActorReportReceipts.remove(handle.runId)
        personalActorCompletions.remove(handle.runId)
        personalActorTransports.remove(handle.runId)
        personalActorBooks.remove(handle.runId)
        personalActorTargetOrigins.remove(handle.runId)?.clear()
        personalActorHistoricalHandoffs.remove(handle.runId)
        if (pendingScopedSync?.let { it.actorRun && it.deviceId == handle.peerId && it.correlatedRunId == handle.runId } == true)
            pendingScopedSync = null
    }

    @Synchronized private fun retireInvalidPersonalActors() {
        personalActorWork.toList().forEach { run ->
            val handle = personalActorHandles[run] ?: return@forEach
            if (runCatching { personalActorJournal.withActive(handle) {} }.isFailure) {
                // A lost source already prevents work. Retain the owner for maintenance retry on I/O failure.
                runCatching { stopPersonalActor(handle) }
            }
        }
        personalActorHistoricalHandoffs.values.toList().forEach { saved ->
            if (personalActorCompletions[saved.handle.runId]?.completed != true &&
                currentActorCompletionAuthority(saved.handle.peerId, saved.publicKey, saved.channel, saved.generation) == null)
                runCatching { stopPersonalActor(saved.handle) }
        }
    }

    @Synchronized private fun reapPersonalActors() {
