#!/usr/bin/env python3
"""Focused Kotlin lifecycle-method harness. Requires Python 3, kotlinc, java.
Run with path to TelefonWerk.kt or to the source-bound excerpt.
No Android runtime, encrypted DB or actual book writes are emulated as native tests.
"""
import pathlib, subprocess, sys, tempfile, hashlib, sqlite3

source = pathlib.Path(sys.argv[1]).read_text()
start = source.index('    @Synchronized internal fun stopPersonalActor(')
end = source.index('    @Synchronized private fun reapPersonalActors()', start)
methods = source[start:end]
print('method excerpt SHA256:', hashlib.sha256(methods.encode()).hexdigest(), flush=True)

stub = '''
object Ablage { val SCHREIBSPERRE = Any() }
class Handle(val runId:String, val peerId:String="peer")
class Channel
class Completion(val completed:Boolean=false)
class Saved(val handle:Handle, val publicKey:String, val channel:Channel, val generation:Long)
class Intent(val actorRun:Boolean=true, val deviceId:String="peer", val correlatedRunId:String="run")
class Origin { fun clear() {} }
class Journal {
    var live=true; var fail=false; var stops=0
    fun withActive(handle:Handle, action:()->Unit) { check(live); action() }
    fun retire(handle:Handle, action:()->Unit) { if(fail) error("synthetic I/O fault"); action(); stops++ }
}
class Harness {
    val personalActorJournal=Journal()
    val personalActorWork=mutableSetOf<String>()
    val personalActorHandles=mutableMapOf<String,Handle>()
    val personalActorReportReceipts=mutableMapOf<String,String>()
    val personalActorCompletions=mutableMapOf<String,Completion>()
    val personalActorTransports=mutableMapOf<String,Channel>()
    val personalActorBooks=mutableMapOf<String,String>()
    val personalActorTargetOrigins=mutableMapOf<String,Origin>()
    val personalActorHistoricalHandoffs=mutableMapOf<String,Saved>()
    var pendingScopedSync:Intent?=null
    val old=Channel(); var activeChannel:Channel?=old
    var authority:String?="valid"; var stoppedRows=0; var book="saved"; var privatePurges=0
    fun currentActorCompletionAuthority(peer:String,key:String,channel:Channel,generation:Long):String? = if(channel===activeChannel) authority else null
    fun stopActorRunAndPrivateStaging(peer:String,run:String) { stoppedRows=65; privatePurges++ }
    fun completion(completed:Boolean=false,historical:Boolean=false) {
        val h=Handle("run"); personalActorHandles["run"]=h
        personalActorTransports["run"]=old
        personalActorCompletions["run"]=Completion(completed)
        // The normal commit removes work after beginCompletion; only historical commits install a handoff.
        if(historical) personalActorHistoricalHandoffs["run"]=Saved(h,"key",old,0)
    }
    fun active() { personalActorHandles["run"]=Handle("run"); personalActorWork.add("run"); personalActorTransports["run"]=old }
    fun tick()=retireInvalidPersonalActors()
'''
main = '''
}
fun main() {
    var failures=0
    fun test(name:String, checkCase:()->Unit) { try { checkCase(); println("PASS $name") } catch(e:Throwable) { failures++; println("FAIL $name: ${e.message}") } }
    test("ordinary completion lost channel") { val h=Harness(); h.completion(); h.activeChannel=null; h.tick(); check(h.stoppedRows==65); check(h.personalActorCompletions.isEmpty()); check(h.book=="saved") }
    test("ordinary completion replacement channel") { val h=Harness(); h.completion(); h.activeChannel=Channel(); h.tick(); check(h.stoppedRows==65); check(h.personalActorCompletions.isEmpty()) }
    test("same channel waiting for scope") { val h=Harness(); h.completion(); h.authority=null; h.tick(); check(h.stoppedRows==0); check(h.personalActorCompletions.size==1) }
    test("completed ordinary completion retained") { val h=Harness(); h.completion(completed=true); h.activeChannel=null; h.tick(); check(h.stoppedRows==0); check(h.personalActorCompletions.size==1) }
    test("historical loss existing retirement") { val h=Harness(); h.completion(historical=true); h.activeChannel=null; h.tick(); check(h.stoppedRows==65); check(h.privatePurges==1) }
    test("historical same channel authority lost existing rule") { val h=Harness(); h.completion(historical=true); h.authority=null; h.tick(); check(h.stoppedRows==65); check(h.privatePurges==1) }
    test("active actor existing retirement") { val h=Harness(); h.active(); h.personalActorJournal.live=false; h.activeChannel=null; h.tick(); check(h.stoppedRows==65) }
    test("cleanup fault retains owner then retries") { val h=Harness(); h.completion(); h.activeChannel=null; h.personalActorJournal.fail=true; h.tick(); check(h.personalActorCompletions.size==1); check(h.stoppedRows==0); h.personalActorJournal.fail=false; h.tick(); check(h.stoppedRows==65); check(h.personalActorCompletions.isEmpty()) }
    println("FAILURES=$failures")
    if(failures!=0) kotlin.system.exitProcess(1)
}
'''
with tempfile.TemporaryDirectory() as tmp:
    kt=pathlib.Path(tmp)/'Repro.kt'; jar=pathlib.Path(tmp)/'repro.jar'
    kt.write_text(stub+methods.replace('PersonalActorHandle','Handle')+main)
    subprocess.run(['kotlinc',str(kt),'-nowarn','-include-runtime','-d',str(jar)],check=True)
    result=subprocess.run(['java','-jar',str(jar)])

# Product query ordering and 32-row bound, on actual SQLite, independently of the Kotlin doubles.
# The protected envelope classification is supplied by the fixture; no encrypted payload is parsed here.
con=sqlite3.connect(':memory:')
con.execute('CREATE TABLE outbox(message_id TEXT PRIMARY KEY,peer_id TEXT,kind TEXT,created_ms INTEGER,next_attempt_ms INTEGER)')
con.executemany('INSERT INTO outbox VALUES (?,?,?,?,?)',[(f'a{i:03d}','peer','personal_sync.deletion_decision',i,0) for i in range(65)]+[('status','peer','incoming_call_state.event',100,0)])
order="CASE kind WHEN 'capabilities.update' THEN 0 WHEN 'grants.update' THEN 1 WHEN 'personal_sync.settings' THEN 2 WHEN 'personal_sync.note_settings' THEN 3 WHEN 'personal_sync.time_settings' THEN 4 WHEN 'personal_sync.custom_settings' THEN 5 WHEN 'personal_sync.shared_settings' THEN 6 WHEN 'personal_sync.content_scope' THEN 7 WHEN 'personal_sync.request' THEN 8 ELSE 9 END,created_ms,message_id"
query='SELECT message_id FROM outbox WHERE peer_id=? AND next_attempt_ms<=? ORDER BY '+order+' LIMIT 32'
assert con.execute(query,('peer',100)).fetchall()==[(f'a{i:03d}',) for i in range(32)]
con.execute('UPDATE outbox SET next_attempt_ms=? WHERE peer_id=? AND message_id LIKE ?', (2**63-1,'peer','a%'))
assert con.execute(query,('peer',100)).fetchall()==[('status',)]
assert con.execute('SELECT count(*) FROM outbox').fetchone()==(66,)
print('SQLite selection: 32 actor rows before stop; 1 status after stop; all 66 rows retained')
sys.exit(result.returncode)
