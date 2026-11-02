package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.database.sqlite.SQLiteDatabase
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import java.nio.file.Files
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class PhotoSourceJobIndexTest {
    private class Fixture : AutoCloseable {
        val native = AndroidPhotoFolderInventoryTest.Fixture()
        val directory = Files.createTempDirectory(File("/tmp/opencode").toPath(), "photo-index329-").toFile()
        val original = File.createTempFile("photo-original329-", ".fixture", File("/tmp/opencode")).apply { writeText("hello") }
        var key: SecretKey? = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val protection = DeviceTransferProtection.fromExistingKeyReader { key }
        val reader = AndroidPhotoSourceReader(native.context, native.scope)
        init {
            native.provider.rows["selected"] = listOf(AndroidPhotoFolderInventoryTest.Row("selected/photo"))
            native.provider.contents["selected/photo"] = original
        }
        fun open(hook: (String) -> Unit = {}) = PhotoSourceJobIndex(directory, protection, hook)
        fun inventory() = native.scan()
        fun freeze(index: PhotoSourceJobIndex, job: PhotoSourceJob, inventory: PhotoFolderInventory) = ProtectedPhotoSourceSnapshot.freeze(
            index.rootFile(job), inventory, "sender_fixture_01", native.scope, reader, protection)
        override fun close() { directory.deleteRecursively(); original.delete() }
    }

    @Test fun revokedSourceCacheCanBeRetiredAfterRestartWithoutRestoringOrOpeningLivePhotos() {
        Fixture().use { f ->
            val job: PhotoSourceJob
            f.open().use { index ->
                val inventory = f.inventory(); val reserved = index.reserve(inventory, f.native.scope)
                job = index.publishSnapshot(reserved, f.freeze(index, reserved, inventory), f.native.scope, inventory.lease)
            }
            val opens = f.native.provider.opened
            f.native.receiver = f.native.receiver.copy(receiveGranted = false)
            f.key = null
            assertThrows(DeviceTransferKeyUnavailable::class.java) { f.open().close() }
            f.key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
            f.open().use { index ->
                index.retireCachedSnapshot(job)
                assertTrue(index.jobs().isEmpty()); assertFalse(index.rootFile(job).exists())
            }
            assertEquals(opens, f.native.provider.opened); assertEquals("hello", f.original.readText())
        }
    }

    @Test fun partialCachedCleanupSurvivesProcessRestartRetainsQuotaAndFencesOldReaders() {
        Fixture().use { f ->
            var failCleanup = false
            val job: PhotoSourceJob
            f.open { if (failCleanup && it == "cached-entry-discarded") throw IOException("synthetic interrupted unlink acknowledgement") }.use { index ->
                val inventory = f.inventory(); val reserved = index.reserve(inventory, f.native.scope)
                job = index.publishSnapshot(reserved, f.freeze(index, reserved, inventory), f.native.scope, inventory.lease)
                val reader = index.restore(job, "sender_fixture_01", f.native.scope, inventory.lease)
                val member = reader.manifest.files.single()
                val before = index.rootFile(job).listFiles()!!.size
                failCleanup = true
                assertThrows(IOException::class.java) { index.retireCachedSnapshot(job) }
                assertEquals(before - 1, index.rootFile(job).listFiles()!!.size)
                val retained = index.jobs().single()
                assertEquals("retired", retained.phase); assertEquals(job.cipherBudget, retained.cipherBudget)
                assertEquals(job.snapshot, retained.snapshot)
                assertEquals("photo_jobs_sealed_head_changed", assertThrows(PhotoFolderScopeError::class.java) { reader.readChunk(member.id, 0) }.code)
                assertThrows(PhotoFolderScopeError::class.java) { index.retireCachedSnapshot(job) }
            }
            f.open().use { index ->
                index.retireCachedSnapshot(index.jobs().single())
                assertTrue(index.jobs().isEmpty()); assertFalse(index.rootFile(job).exists())
            }
            assertEquals("hello", f.original.readText())
        }
    }

    @Test fun cachedCleanupPreflightsAllUnknownChangedAndLinkedOriginalsBeforeAnyUnlink() {
        for (change in listOf("unknown", "cipher", "hardlink", "root")) Fixture().use { f ->
            val job: PhotoSourceJob
            f.open().use { index ->
                val inventory = f.inventory(); val reserved = index.reserve(inventory, f.native.scope)
                job = index.publishSnapshot(reserved, f.freeze(index, reserved, inventory), f.native.scope, inventory.lease)
            }
            val root = File(f.directory, "photo-source-" + job.id)
            when (change) {
                "unknown" -> File(root, "unfamiliar-user-work").writeText("keep")
                "cipher" -> File(root, "manifest.enc").let { file -> file.writeBytes(file.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }) }
                "hardlink" -> Files.createLink(File(f.directory, "held-manifest-link").toPath(), File(root, "manifest.enc").toPath())
                else -> {
                    assertTrue(root.renameTo(File(f.directory, "held-original-root")))
                    Files.createDirectory(root.toPath(), java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
                        java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")))
                    File(root, "foreign-work").writeText("keep")
                }
            }
            val before = root.listFiles()!!.associate { it.name to it.readBytes().toList() }
            f.open().use { index ->
                assertThrows(PhotoFolderScopeError::class.java) { index.retireCachedSnapshot(job) }
                assertEquals("retired", index.jobs().single().phase)
                assertEquals(job.cipherBudget, index.jobs().single().cipherBudget)
                assertEquals(before, root.listFiles()!!.associate { it.name to it.readBytes().toList() })
            }
            assertEquals("hello", f.original.readText())
        }
    }

    @Test fun cachedCleanupAcknowledgementLossKeepsRetiredHeadUntilActualAbsenceIsRechecked() {
        Fixture().use { f ->
            var failAck = false
            f.open { if (failAck && it == "cleanup-proven") throw IOException("synthetic cleanup acknowledgement loss") }.use { index ->
                val inventory = f.inventory(); val reserved = index.reserve(inventory, f.native.scope)
                val job = index.publishSnapshot(reserved, f.freeze(index, reserved, inventory), f.native.scope, inventory.lease)
                failAck = true
                assertThrows(IOException::class.java) { index.retireCachedSnapshot(job) }
                assertFalse(index.rootFile(job).exists())
                val retained = index.jobs().single(); assertEquals("retired", retained.phase); assertEquals(job.cipherBudget, retained.cipherBudget)
                failAck = false
                index.retireCachedSnapshot(retained)
                assertTrue(index.jobs().isEmpty())
            }
        }
    }

    @Test fun partialReservationsWithoutAuthenticatedSnapshotWitnessesAreNotGuessedOrDiscarded() {
        Fixture().use { f -> f.open().use { index ->
            val job = index.reserve(f.inventory(), f.native.scope)
            File(index.rootFile(job), "unknown-partial-original").writeText("preserve")
            assertEquals("photo_cache_snapshot_missing", assertThrows(PhotoFolderScopeError::class.java) { index.retireCachedSnapshot(job) }.code)
            assertEquals(job, index.jobs().single())
            assertEquals("preserve", File(index.rootFile(job), "unknown-partial-original").readText())
        } }
    }

    @Test fun actualProtectedSqliteReservationPrecedesRootCreationAndSealedReadbackSurvivesReopen() {
        Fixture().use { f ->
            val inventory = f.inventory()
            val job: PhotoSourceJob
            f.open().use { index ->
                val reserved = index.reserve(inventory, f.native.scope)
                assertEquals("reserved", reserved.phase); assertEquals(5L, reserved.plainBytes)
                assertTrue(index.rootFile(reserved).isDirectory)
                val snapshot = f.freeze(index, reserved, inventory)
                job = index.publishSnapshot(reserved, snapshot, f.native.scope, inventory.lease)
                assertEquals("sealed", job.phase); assertNotNull(job.snapshot)
                assertEquals(job, index.jobs().single())
            }
            f.open().use { reopened ->
                assertEquals(job, reopened.jobs().single())
                val root = reopened.rootFile(job)
                assertThrows(PhotoFolderScopeError::class.java) { reopened.retireAndClean(job) { } }
                val retained = reopened.jobs().single()
                assertEquals("retired", retained.phase); assertEquals(5L, retained.plainBytes)
                assertTrue(root.exists()) // Failed cleanup never frees quota or removes files.
            }
            assertEquals("hello", f.original.readText())
            assertFalse(File(f.directory, "photo-source-jobs.db").readBytes().toString(Charsets.ISO_8859_1).contains("photo.jpg"))
        }
    }

    @Test fun allReservedAndRetiredJobsCountTowardsBoundedQuotaWithoutCreatingLargeFiles() {
        Fixture().use { f ->
            f.open().use { index ->
                val inventory = f.inventory()
                val jobs = (1..PhotoSourceJobIndex.MAX_JOBS).map { index.reserve(inventory, f.native.scope) }
                assertThrows(PhotoFolderScopeError::class.java) { index.reserve(inventory, f.native.scope) }
                assertThrows(IOException::class.java) { index.retireAndClean(jobs.first()) { throw IOException("synthetic cleanup failure") } }
                assertEquals(PhotoSourceJobIndex.MAX_JOBS, index.jobs().size)
                assertThrows(PhotoFolderScopeError::class.java) { index.reserve(inventory, f.native.scope) }
                val retired = index.jobs().single { it.id == jobs.first().id }
                index.retireAndClean(retired) { assertTrue(index.rootFile(retired).delete()) }
                assertEquals(PhotoSourceJobIndex.MAX_JOBS - 1, index.jobs().size)
                assertNotNull(index.reserve(inventory, f.native.scope))
            }
        }
        Fixture().use { f ->
            f.open().use { index ->
                val small = f.inventory()
                val metadataOnly = PhotoFolderInventory(small.lease, (0..7).map { number ->
                    small.entries.single().copy(documentId = "selected/$number", relativePath = "photo$number.jpg", advertisedBytes = DeviceFileManifest.MAX_FILE_BYTES)
                })
                index.reserve(metadataOnly, f.native.scope) // Reserves 400MiB, never writes 400MiB in this test.
                assertThrows(PhotoFolderScopeError::class.java) { index.reserve(small, f.native.scope) }
            }
        }
    }

    @Test fun postCommitAcknowledgementFailureKeepsARealReservationAndCanReleaseOnlyProvenAbsentRoot() {
        Fixture().use { f ->
            f.open { if (it == "reservation-committed") throw IOException("synthetic acknowledgement loss") }.use { index ->
                assertThrows(IOException::class.java) { index.reserve(f.inventory(), f.native.scope) }
                val actual = index.jobs().single()
                assertNull(actual.rootKey); assertFalse(index.rootFile(actual).exists())
                index.retireAndClean(actual) { throw AssertionError("No absent-root cleanup callback should run") }
                assertTrue(index.jobs().isEmpty())
            }
        }
    }

    @Test fun staleHeadsRevokedScopesAndUnfamiliarRootsAreNeverRebasedOrCleaned() {
        Fixture().use { f ->
            f.open().use { index ->
                val inventory = f.inventory(); val job = index.reserve(inventory, f.native.scope)
                val snapshot = f.freeze(index, job, inventory)
                val sealed = index.publishSnapshot(job, snapshot, f.native.scope, inventory.lease)
                assertThrows(PhotoFolderScopeError::class.java) { index.publishSnapshot(job, snapshot, f.native.scope, inventory.lease) }
                assertEquals(sealed, index.jobs().single())
                f.native.receiver = f.native.receiver.copy(permissionEpoch = "a".repeat(64))
                assertThrows(PhotoFolderScopeError::class.java) { index.reserve(inventory, f.native.scope) }
                assertEquals(1, index.jobs().size)
                index.retireAndClean(sealed) { snapshot.discard() }
                assertTrue(index.jobs().isEmpty()); assertEquals("hello", f.original.readText())
            }
        }
        Fixture().use { f ->
            f.open().use { index ->
                val job = index.reserve(f.inventory(), f.native.scope)
                val held = File(f.directory, "held-known-root")
                assertTrue(index.rootFile(job).renameTo(held)); assertTrue(index.rootFile(job).mkdir())
                File(index.rootFile(job), "unknown-user-work").writeText("keep")
                assertThrows(PhotoFolderScopeError::class.java) { index.retireAndClean(job) { throw AssertionError("Foreign root cleanup") } }
                assertEquals("keep", File(index.rootFile(job), "unknown-user-work").readText())
                assertEquals("retired", index.jobs().single().phase)
            }
        }
    }

    @Test fun missingKeyOrMissingIndexWithExistingSourceFilesNeverCreatesReplacementState() {
        Fixture().use { f ->
            f.key = null
            assertThrows(DeviceTransferKeyUnavailable::class.java) { f.open().close() }
            assertFalse(File(f.directory, "photo-source-jobs.db").exists()); assertNull(f.key)
        }
        Fixture().use { f ->
            val unknown = File(f.directory, "unfamiliar-existing-snapshot").apply { mkdir(); File(this, "original").writeText("keep") }
            assertThrows(PhotoFolderScopeError::class.java) { f.open().close() }
            assertEquals("keep", File(unknown, "original").readText())
            assertFalse(File(f.directory, "photo-source-jobs.db").exists())
        }
        Fixture().use { f ->
            f.open().use { it.reserve(f.inventory(), f.native.scope) }
            val key = f.key; f.key = null
            assertThrows(DeviceTransferKeyUnavailable::class.java) { f.open().close() }
            f.key = key
            f.open().use { assertEquals(1, it.jobs().size) }
        }
    }

    @Test fun corruptEncryptedRowsStayBlockedAndUnrelatedRowsArePreserved() {
        Fixture().use { f ->
            f.open().use { it.reserve(f.inventory(), f.native.scope) }
            val file = File(f.directory, "photo-source-jobs.db")
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.execSQL("INSERT INTO source_meta(name,sealed) VALUES(?,?)", arrayOf("unrelated-fixture", byteArrayOf(4, 2)))
                db.execSQL("UPDATE source_jobs SET sealed=?", arrayOf(byteArrayOf(1, 2, 3)))
            }
            f.open().use { index -> assertThrows(IllegalArgumentException::class.java) { index.jobs() } }
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT sealed FROM source_meta WHERE name='unrelated-fixture'", null).use { cursor ->
                    assertTrue(cursor.moveToFirst()); assertArrayEquals(byteArrayOf(4, 2), cursor.getBlob(0))
                }
                db.rawQuery("SELECT sealed FROM source_jobs", null).use { cursor ->
                    assertTrue(cursor.moveToFirst()); assertArrayEquals(byteArrayOf(1, 2, 3), cursor.getBlob(0))
                }
            }
        }
    }

    @Test fun unindexedLeftoversAndLinkedSidecarsBlockNewWorkWithoutBeingDeletedOrIgnoringTheirQuota() {
        Fixture().use { f ->
            f.open().use { index ->
                val unknown = File(f.directory, "unindexed-existing-copy").apply { mkdir(); File(this, "keep").writeText("preserve") }
                assertEquals("photo_jobs_unindexed_entries_preserved", assertThrows(PhotoFolderScopeError::class.java) {
                    index.reserve(f.inventory(), f.native.scope) }.code)
                assertTrue(index.jobs().isEmpty()); assertEquals("preserve", File(unknown, "keep").readText())
            }
        }
        Fixture().use { f ->
            f.open().close()
            val sidecar = File(f.directory, "photo-source-jobs.db-wal")
            assertFalse(sidecar.exists())
            Files.createSymbolicLink(sidecar.toPath(), f.original.toPath())
            assertThrows(PhotoFolderScopeError::class.java) { f.open().close() }
            assertEquals("hello", f.original.readText()); assertTrue(Files.isSymbolicLink(sidecar.toPath()))
        }
    }

    @Test fun postCommitHeadOrCleanupAcknowledgementFailureRetainsTheActualHeadForNativeRetry() {
        Fixture().use { f ->
            var point = ""
            f.open { if (it == point) throw IOException("synthetic native-index acknowledgement failure") }.use { index ->
                val inventory = f.inventory(); val job = index.reserve(inventory, f.native.scope)
                val snapshot = f.freeze(index, job, inventory)
                point = "job-head-committed"
                assertThrows(IOException::class.java) { index.publishSnapshot(job, snapshot, f.native.scope, inventory.lease) }
                val committed = index.jobs().single()
                assertEquals("sealed", committed.phase); assertNotNull(committed.snapshot)
                point = "cleanup-proven"
                assertThrows(IOException::class.java) { index.retireAndClean(committed) { snapshot.discard() } }
                val retired = index.jobs().single()
                assertEquals("retired", retired.phase); assertFalse(index.rootFile(retired).exists())
                point = ""
                index.retireAndClean(retired) { throw AssertionError("Completed root cleanup repeated") }
                assertTrue(index.jobs().isEmpty()); assertEquals("hello", f.original.readText())
            }
        }
    }

    @Test fun recreatedNativeOwnerRestoresActualFrozenBytesFromProtectedIndexWithoutOpeningLivePhotosAgain() {
        Fixture().use { f ->
            val inventory = f.inventory()
            val job: PhotoSourceJob
            val originalSnapshot: ProtectedPhotoSourceSnapshot
            f.open().use { index ->
                val reserved = index.reserve(inventory, f.native.scope)
                originalSnapshot = f.freeze(index, reserved, inventory)
                job = index.publishSnapshot(reserved, originalSnapshot, f.native.scope, inventory.lease)
            }
            val opens = f.native.provider.opened
            f.original.writeText("new live photo contents")
            f.native.receiver = f.native.receiver.copy(owner = Any())
            assertThrows(PhotoFolderScopeError::class.java) { originalSnapshot.manifest }
            val lease = requireNotNull(f.native.scope.lease())
            f.open().use { index ->
                val restored = index.restore(job, "sender_fixture_01", f.native.scope, lease)
                val member = restored.manifest.files.single()
                assertArrayEquals("hello".toByteArray(), restored.readChunk(member.id, 0))
                assertEquals(opens, f.native.provider.opened)
                assertEquals("new live photo contents", f.original.readText())
                restored.retireAndDiscard()
                assertTrue(index.jobs().isEmpty()); assertFalse(index.rootFile(job).exists())
            }
        }
    }

    @Test fun corruptedOrUnfamiliarRestartStateNeverBecomesANewValidBaselineOrLosesTheStoredHead() {
        for (change in listOf("cipher", "unknown", "epoch")) Fixture().use { f ->
            val inventory = f.inventory(); val job: PhotoSourceJob
            f.open().use { index ->
                val reserved = index.reserve(inventory, f.native.scope)
                val snapshot = f.freeze(index, reserved, inventory)
                job = index.publishSnapshot(reserved, snapshot, f.native.scope, inventory.lease)
            }
            val root = File(f.directory, "photo-source-" + job.id)
            when (change) {
                "cipher" -> root.listFiles()!!.single { it.name.matches(Regex("[0-9a-f]{32}-0\\.enc")) }.let {
                    val changed = it.readBytes().also { bytes -> bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte() }
                    it.writeBytes(changed)
                }
                "unknown" -> File(root, "unfamiliar-work").writeText("keep")
                "epoch" -> f.native.receiver = f.native.receiver.copy(permissionEpoch = "a".repeat(64))
            }
            val before = root.listFiles()!!.associate { it.name to it.readBytes().toList() }
            f.open().use { index ->
                assertThrows(PhotoFolderScopeError::class.java) { index.restore(job, "sender_fixture_01", f.native.scope, requireNotNull(f.native.scope.lease())) }
                assertEquals(job, index.jobs().single())
                assertEquals(before, root.listFiles()!!.associate { it.name to it.readBytes().toList() })
            }
            assertEquals("hello", f.original.readText())
        }
    }

    @Test fun actualRetirementInvalidatesAlreadyRestoredReadersEvenWhenCleanupFailsOrDoesNothing() {
        Fixture().use { f ->
            f.open().use { index ->
                val inventory = f.inventory(); val reserved = index.reserve(inventory, f.native.scope)
                val snapshot = f.freeze(index, reserved, inventory)
                val job = index.publishSnapshot(reserved, snapshot, f.native.scope, inventory.lease)
                val reader = index.restore(job, "sender_fixture_01", f.native.scope, inventory.lease)
                val member = reader.manifest.files.single()
                assertArrayEquals("hello".toByteArray(), reader.readChunk(member.id, 0))
                assertThrows(PhotoFolderScopeError::class.java) { index.retireAndClean(job) { } }
                assertEquals("photo_jobs_sealed_head_changed", assertThrows(PhotoFolderScopeError::class.java) { reader.readChunk(member.id, 0) }.code)
                val retired = index.jobs().single(); assertEquals(5L, retired.plainBytes)
                index.retireAndClean(retired) { snapshot.discard() }
                assertTrue(index.jobs().isEmpty())
            }
        }
    }

    @Test fun knownJobRootsCannotHideUnfamiliarOrOverBudgetContentsDuringNewReservations() {
        for (large in listOf(false, true)) Fixture().use { f ->
            f.open().use { index ->
                val job = index.reserve(f.inventory(), f.native.scope)
                val file = File(index.rootFile(job), if (large) "c".repeat(32) + "-0.enc" else "unfamiliar-fixture")
                java.io.RandomAccessFile(file, "rw").use { it.setLength(if (large) job.cipherBudget + 1 else 1) }
                Files.setPosixFilePermissions(file.toPath(), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"))
                assertEquals(if (large) "photo_jobs_root_budget_exceeded" else "photo_jobs_unfamiliar_root_entry",
                    assertThrows(PhotoFolderScopeError::class.java) { index.reserve(f.inventory(), f.native.scope) }.code)
                assertEquals(1, index.jobs().size); assertTrue(file.exists())
            }
        }
    }
}
