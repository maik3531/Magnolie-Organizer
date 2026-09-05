package io.gitlab.maik3531.magnolienotes.daten

import java.nio.charset.StandardCharsets

data class HierarchischeAufgabe(val aufgabe: Aufgabe, val tiefe: Int)

/** Deterministic, iterative normalization shared by storage, UI, archives and sync. */
object AufgabenHierarchie {
    private val technischeReihenfolge = Comparator<String> { left, right ->
        val a = left.toByteArray(StandardCharsets.UTF_8)
        val b = right.toByteArray(StandardCharsets.UTF_8)
        val common = minOf(a.size, b.size)
        for (index in 0 until common) {
            val compared = a[index].toUByte().compareTo(b[index].toUByte())
            if (compared != 0) return@Comparator compared
        }
        a.size.compareTo(b.size)
    }

    private val aufgabenReihenfolge = Comparator<Aufgabe> { left, right ->
        left.reihenfolge.compareTo(right.reihenfolge).takeIf { it != 0 }
            ?: technischeReihenfolge.compare(left.uid, right.uid)
    }

    fun normalisieren(input: List<Aufgabe>): List<Aufgabe> {
        if (input.isEmpty()) return input
        val oldIndices = input.indices.mapNotNull { index ->
            input[index].uid.trim().takeIf(String::isNotEmpty)?.let { it to index }
        }.groupBy({ it.first }, { it.second })
        val reserved = oldIndices.filterValues { it.size == 1 }.keys
        val normalized = input.toMutableList()
        val used = mutableSetOf<String>()
        val nextAttempt = mutableMapOf<String, Int>()
        input.indices.sortedWith(Comparator { left, right ->
            technischeReihenfolge.compare(input[left].id, input[right].id).takeIf { it != 0 }
                ?: left.compareTo(right)
        }).forEach { index ->
            val task = normalized[index]
            var uid = task.uid.trim()
            if (uid !in reserved || !used.add(uid)) {
                var attempt = nextAttempt[task.id] ?: 0
                do {
                    val salt = if (attempt == 0) "" else (attempt - 1).toString()
                    attempt++
                    uid = stabileUid(task.id, salt)
                } while (uid in reserved || !used.add(uid))
                nextAttempt[task.id] = attempt
            }
            normalized[index] = task.copy(uid = uid)
        }
        val byUid = normalized.associateBy(Aufgabe::uid)
        normalized.indices.forEach { index ->
            val task = normalized[index]
            val rawParent = input[index].elternUid.trim()
            val parent = byUid[rawParent] ?: oldIndices[rawParent]?.singleOrNull()?.let(normalized::get)
            normalized[index] = task.copy(
                elternUid = parent?.uid?.takeUnless { it == task.uid }.orEmpty(),
                reihenfolge = task.reihenfolge.takeIf { it >= 0 } ?: index
            )
        }
        val currentByUid = normalized.withIndex().associate { it.value.uid to it.index }
        val done = mutableSetOf<String>()
        for (start in normalized.indices) {
            val path = mutableListOf<Int>()
            val positions = mutableMapOf<String, Int>()
            var current: Int? = start
            while (current != null) {
                val task = normalized[current]
                if (task.uid in done || task.uid in positions) break
                positions[task.uid] = path.size
                path += current
                current = currentByUid[task.elternUid]
            }
            if (current != null) {
                val cycleStart = positions[normalized[current].uid]
                if (cycleStart != null) {
                    val root = path.subList(cycleStart, path.size).minWith { left, right ->
                        technischeReihenfolge.compare(normalized[left].uid, normalized[right].uid)
                    }
                    normalized[root] = normalized[root].copy(elternUid = "")
                }
            }
            path.forEach { done += normalized[it].uid }
        }
        normalized.indices.groupBy { normalized[it].elternUid }.values.forEach { siblings ->
            siblings.sortedWith { left, right -> aufgabenReihenfolge.compare(normalized[left], normalized[right]) }
                .forEachIndexed { order, index -> normalized[index] = normalized[index].copy(reihenfolge = order) }
        }
        return normalized
    }

    fun flach(input: List<Aufgabe>): List<HierarchischeAufgabe> {
        val tasks = normalisieren(input)
        val children = tasks.groupBy(Aufgabe::elternUid).mapValues { (_, values) ->
            values.sortedWith(aufgabenReihenfolge)
        }
        val result = ArrayList<HierarchischeAufgabe>(tasks.size)
        val stack = ArrayDeque<Pair<Aufgabe, Int>>()
        children[""].orEmpty().asReversed().forEach { stack.addLast(it to 0) }
        while (stack.isNotEmpty()) {
            val (task, depth) = stack.removeLast()
            result += HierarchischeAufgabe(task, depth)
            children[task.uid].orEmpty().asReversed().forEach { stack.addLast(it to depth + 1) }
        }
        return result
    }

    fun nachkommen(input: List<Aufgabe>, uid: String): Set<String> {
        val children = normalisieren(input).groupBy(Aufgabe::elternUid)
        val result = mutableSetOf<String>()
        val stack = ArrayDeque<String>().apply { add(uid) }
        while (stack.isNotEmpty()) children[stack.removeLast()].orEmpty().forEach {
            if (result.add(it.uid)) stack.add(it.uid)
        }
        return result
    }

    fun elternSetzen(input: List<Aufgabe>, uid: String, parentUid: String): List<Aufgabe>? {
        val tasks = normalisieren(input)
        val task = tasks.firstOrNull { it.uid == uid } ?: return null
        if (parentUid == uid || parentUid.isNotEmpty() && tasks.none { it.uid == parentUid } ||
            parentUid in nachkommen(tasks, uid)) return null
        val order = tasks.count { it.elternUid == parentUid }
        return normalisieren(tasks.map { if (it.uid == uid) task.copy(elternUid = parentUid, reihenfolge = order) else it })
    }

    fun verschieben(input: List<Aufgabe>, uid: String, delta: Int): List<Aufgabe>? {
        require(delta == -1 || delta == 1)
        val tasks = normalisieren(input).toMutableList()
        val current = tasks.firstOrNull { it.uid == uid } ?: return null
        val siblings = tasks.filter { it.elternUid == current.elternUid }
            .sortedWith(aufgabenReihenfolge)
        val at = siblings.indexOfFirst { it.uid == uid }
        val target = siblings.getOrNull(at + delta) ?: return tasks
        tasks.replaceAll { when (it.uid) {
            current.uid -> it.copy(reihenfolge = target.reihenfolge)
            target.uid -> it.copy(reihenfolge = current.reihenfolge)
            else -> it
        } }
        return normalisieren(tasks)
    }

    fun loeschenUndKinderHochheben(input: List<Aufgabe>, uid: String): List<Aufgabe> {
        val tasks = normalisieren(input)
        val removed = tasks.firstOrNull { it.uid == uid } ?: return tasks
        val children = tasks.filter { it.elternUid == uid }
            .sortedWith(aufgabenReihenfolge)
        val childOrders = children.mapIndexed { index, task -> task.uid to index }.toMap()
        val siblingShift = children.size - 1
        return normalisieren(tasks.filterNot { it.uid == uid }.map { task ->
            val childIndex = childOrders[task.uid]
            when {
                childIndex != null -> task.copy(elternUid = removed.elternUid,
                    reihenfolge = removed.reihenfolge + childIndex)
                task.elternUid == removed.elternUid && task.reihenfolge > removed.reihenfolge ->
                    task.copy(reihenfolge = task.reihenfolge + siblingShift)
                else -> task
            }
        })
    }

    fun stabileUid(id: String, salt: String = ""): String {
        val bytes = "magnolie-task-v1\u0000$id\u0000$salt".toByteArray(StandardCharsets.UTF_8)
        var first = 2166136261u
        var second = 2166136261u
        bytes.forEach { first = (first xor it.toUByte().toUInt()) * 16777619u }
        bytes.indices.reversed().forEach { second = (second xor bytes[it].toUByte().toUInt()) * 16777619u }
        return "mag-task-${first.toString(16).padStart(8, '0')}${second.toString(16).padStart(8, '0')}@magnolie-organizer"
    }
}
