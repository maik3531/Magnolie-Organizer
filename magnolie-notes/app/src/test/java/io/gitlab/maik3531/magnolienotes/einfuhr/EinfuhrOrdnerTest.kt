package io.gitlab.maik3531.magnolienotes.einfuhr

import androidx.documentfile.provider.DocumentFile
import androidx.documentfile.provider.SyntheticImportDocumentFile as FileNode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.IOException

/** Actual folder traversal with synthetic provider nodes; no storage or Android device is touched. */
class EinfuhrOrdnerTest {
    private fun file(name: String = "a.txt", text: String = "x") = FileNode(name, text.toByteArray())
    private fun folder(vararg children: FileNode) = FileNode("folder", children = arrayOf(*children))
    private fun collect(root: FileNode, budget: OrdnerImportBudget = OrdnerImportBudget(),
                        reader: (DocumentFile, Long) -> ByteArray? = { node, limit ->
                            (node as FileNode).bytes.takeIf { it.size <= limit }
                        }, parser: (ByteArray, DocumentFile) -> List<Rohnotiz> = { bytes, _ ->
                            listOf(Rohnotiz("", bytes.toString(Charsets.UTF_8)))
                        }): List<Rohnotiz> {
        val notes = mutableListOf<Rohnotiz>()
        Einfuhr.sammle(root, notes, 0, budget, reader, parser)
        return notes
    }

    @Test fun `flacher Ordner ist auf 5000 Eintraege begrenzt`() {
        assertEquals(5000, collect(folder(*Array(5000) { file("$it.txt") })).size)
        assertThrows(IOException::class.java) { collect(folder(*Array(5001) { file("$it.txt") })) }
    }

    @Test fun `Unterordner teilen Eingabegrenze und verbleibendes Lesebudget`() {
        val reads = mutableListOf<Long>()
        val root = folder(folder(file("a.txt", "abc")), folder(file("b.txt", "de")))
        assertEquals(2, collect(root, OrdnerImportBudget(maxRohbytes = 5), reader = { node, limit ->
            reads += limit; (node as FileNode).bytes
        }).size)
        assertEquals(listOf(5L, 2L), reads)
        assertThrows(IOException::class.java) {
            collect(folder(file("a.txt", "abc"), file("b.txt", "def")), OrdnerImportBudget(maxRohbytes = 5))
        }
    }

    @Test fun `entpackte Notizen teilen Anzahl und UTF8 Textgrenze`() {
        val root = folder(file("one.zip"), file("two.zip"))
        assertThrows(IOException::class.java) {
            collect(root, OrdnerImportBudget(maxNotizen = 3), parser = { _, _ -> List(2) { Rohnotiz("", "x") } })
        }
        assertThrows(IOException::class.java) {
            collect(root, OrdnerImportBudget(maxTextbytes = 7), parser = { _, _ -> listOf(Rohnotiz("", "äö")) })
        }
        assertEquals(2, collect(root, OrdnerImportBudget(maxTextbytes = 8),
            parser = { _, _ -> listOf(Rohnotiz("", "äö")) }).size)
    }

    @Test fun `unlesbare oder zu tiefe Quellen liefern kein scheinbar vollstaendiges Ergebnis`() {
        assertThrows(IOException::class.java) { collect(folder(file()), reader = { _, _ -> null }) }
        var deep = folder(file())
        repeat(7) { deep = folder(deep) }
        assertThrows(IOException::class.java) { collect(deep) }
    }

    @Test fun `unbekannte Dateien werden nicht gelesen zaehlen aber zum Laufbudget`() {
        val root = folder(file("ignore.bin"), file("yes.txt"))
        var reads = 0
        assertEquals(1, collect(root, reader = { node, _ -> reads++; (node as FileNode).bytes }).size)
        assertEquals(1, reads)
        assertThrows(IOException::class.java) { collect(root, OrdnerImportBudget(maxEintraege = 1)) }
    }
}
