#!/usr/bin/env python3
"""Execute the unmodified Notes probe method with controlled Kotlin dependencies.

This is a source-extracted JVM control-flow check, not Android/Robolectric, a
Compose UI test, cryptographic authentication or a real Internet test. The
production method and proof-validity predicate are copied byte-for-byte; only
storage, network handshake and monotonic clock are synthetic.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True, type=Path)
parser.add_argument("--compiler-dir", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
code = args.repo / "magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum"
work = (code / "Baumwerk.kt").read_text()
start = work.index("    internal fun fernAbgleichVerbindungen(): List<FernAbgleichVerbindung> {")
end = work.index("\n    /** Single-entry sync", start)
method = work[start:end]
proof_source = (code / "FernAbgleich.kt").read_text()
start = proof_source.index("internal data class FernAbgleichVerbindung(")
end = proof_source.index("\ninternal object FernAbgleich", start)
proof = proof_source[start:end]
helper = code / "FernAbgleichReihenfolge.kt"
fields = ""
extra_sources = []
if helper.exists():
    fields = re.search(r"^    private val fernAbgleichReihenfolge = .*?$", work, re.M).group(0) + "\n"
    extra_sources.append(str(helper))

stubs = r'''
package io.gitlab.maik3531.magnolienotes.baum

internal data class Partner(val kennung: String, val bestaetigt: Boolean = true,
    val vertraut: Boolean = true, val fernAdresse: String = "fixture.invalid", val fernPort: Int = 8737,
    val oeffentlich: String = "pinned-key", val protokoll: String = "baum-fs1")
internal data class Baumzustand(val partner: List<Partner>, val dienstAn: Boolean = true,
    val syncEpoch: String = "epoch", val kennung: String = "own", val oeffentlich: String = "own-key")
internal data class State(var value: Baumzustand)
internal class Ablage(val baum: State)
internal data class EigeneIdentitaet(val kennung: String = "own", val oeffentlich: String = "own-key")
internal object System { var now = 0L; fun nanoTime() = now }
internal object FernAbgleich {
    val attempts = mutableListOf<String>()
    var slow = false
    var expire = false
    var during: (Partner) -> Unit = {}
    fun reset() { attempts.clear(); slow = false; expire = false; during = {}; System.now = 0 }
    fun pruefen(identity: EigeneIdentitaet, peer: Partner, epoch: String): FernAbgleichVerbindung? {
        attempts += peer.kennung
        if (slow && peer.kennung.startsWith("offline")) { System.now += 1_500_000_000L; return null }
        System.now += 1_000_000L
        during(peer)
        return FernAbgleichVerbindung(peer, identity.kennung, identity.oeffentlich, epoch,
            System.now + if (expire) 0 else 30_000_000_000L)
    }
}
'''
wrapper = r'''
internal class Work(val ablage: Ablage) {
    var online = true
    var ownAvailable = true
    fun fernInternet() = online
    fun eigen(): EigeneIdentitaet? = if (ownAvailable) EigeneIdentitaet() else null
'''
tests = r'''
}
private fun fixture(vararg peers: Partner) = Work(Ablage(State(Baumzustand(peers.toList()))))
fun main() {
    var failures = 0; var passed = 0
    fun test(name: String, body: () -> Unit) {
        FernAbgleich.reset()
        try { body(); passed++; println("PASS $name") }
        catch (e: Throwable) { failures++; println("FAIL $name: ${e.message}") }
        finally { Thread.interrupted() }
    }
    test("reachable peer after six timeouts becomes available on a later refresh") {
        val peers = (1..6).map { Partner("offline$it") } + Partner("reachable")
        val work = fixture(*peers.toTypedArray())
        FernAbgleich.slow = true
        val seen = mutableSetOf<String>()
        repeat(3) {
            FernAbgleich.attempts.clear()
            seen += work.fernAbgleichVerbindungen().map { p -> p.partner.kennung }
            check(FernAbgleich.attempts.size <= 7)
            System.now += 15_000_000_000L
        }
        check("reachable" in seen) { "reachable peer never probed after repeated refreshes" }
    }
    test("all seventy peers are considered without exceeding thirty-two per refresh") {
        val peers = (1..70).map { Partner("peer$it") }
        val work = fixture(*peers.toTypedArray())
        val seen = mutableSetOf<String>()
        repeat(3) {
            FernAbgleich.attempts.clear()
            seen += work.fernAbgleichVerbindungen().map { p -> p.partner.kennung }
            check(FernAbgleich.attempts.size <= 32)
            check(FernAbgleich.attempts.distinct().size == FernAbgleich.attempts.size)
            System.now += 15_000_000_000L
        }
        check(seen == peers.map { it.kennung }.toSet()) { "only ${seen.size}/70 peers were considered" }
    }
    test("offline does not probe") {
        val work = fixture(Partner("allowed")); work.online = false
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("disabled service does not probe") {
        val work = fixture(Partner("allowed"))
        work.ablage.baum.value = work.ablage.baum.value.copy(dienstAn = false)
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("missing own identity does not probe") {
        val work = fixture(Partner("allowed")); work.ownAvailable = false
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("unconfirmed untrusted and unconfigured peers are not probed") {
        val work = fixture(Partner("unconfirmed", bestaetigt = false), Partner("untrusted", vertraut = false),
            Partner("unconfigured", fernAdresse = ""), Partner("allowed"))
        check(work.fernAbgleichVerbindungen().map { it.partner.kennung } == listOf("allowed"))
        check(FernAbgleich.attempts == listOf("allowed"))
    }
    test("trust revocation during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { p -> work.ablage.baum.value = work.ablage.baum.value.copy(partner = listOf(p.copy(vertraut = false))) }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("endpoint replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { p -> work.ablage.baum.value = work.ablage.baum.value.copy(partner = listOf(p.copy(fernPort = 9999))) }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("restore epoch replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { work.ablage.baum.value = work.ablage.baum.value.copy(syncEpoch = "restored") }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("own key replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { work.ablage.baum.value = work.ablage.baum.value.copy(oeffentlich = "new-key") }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("expired proof is never reported available") {
        val work = fixture(Partner("allowed")); FernAbgleich.expire = true
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("interruption stops before any network attempt") {
        val work = fixture(Partner("allowed")); Thread.currentThread().interrupt()
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    println("RESULT passed=$passed failures=$failures")
    check(failures == 0) { "$failures regression assertions failed" }
}
'''
generated = args.output / "ProbeFairnessHarness.kt"
generated.write_text(stubs + proof + wrapper + fields + method + tests)
classpath = ":".join(str(p) for p in sorted(args.compiler_dir.glob("*.jar")))
compile_command = ["java", "-cp", classpath, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect", "-jvm-target", "17", "-classpath", classpath, "-d", str(args.output / "classes"), str(generated), *extra_sources]
compiled = subprocess.run(compile_command, capture_output=True, text=True)
(args.output / "compile.log").write_text(compiled.stdout + compiled.stderr)
if compiled.returncode:
    print(compiled.stdout + compiled.stderr)
    raise SystemExit(compiled.returncode)
run_command = ["java", "-cp", str(args.output / "classes") + ":" + classpath, "io.gitlab.maik3531.magnolienotes.baum.ProbeFairnessHarnessKt"]
ran = subprocess.run(run_command, capture_output=True, text=True)
(args.output / "results.log").write_text(ran.stdout + ran.stderr)
bindings = {str(p.relative_to(args.repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [code / "Baumwerk.kt", code / "FernAbgleich.kt", *map(Path, extra_sources)]}
(args.output / "manifest.json").write_text(json.dumps({
    "source_head": subprocess.run(["git", "-C", str(args.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
    "source_files_sha256": bindings,
    "production_method_sha256": hashlib.sha256(method.encode()).hexdigest(),
    "production_proof_predicate_sha256": hashlib.sha256(proof.encode()).hexdigest(),
    "generated_harness_sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
    "compiler_exit": compiled.returncode,
    "runtime_exit": ran.returncode,
    "result_log_sha256": hashlib.sha256((args.output / "results.log").read_bytes()).hexdigest(),
    "boundary": __doc__,
}, indent=2) + "\n")
print(ran.stdout + ran.stderr)
raise SystemExit(ran.returncode)
