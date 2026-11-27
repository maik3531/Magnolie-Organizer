# Controlled host harness: source methods, real SQLite and test AES-GCM; not a full phone service.
import ast, contextlib, hashlib, json, os, sqlite3, sys, tempfile, uuid, unittest
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
DAY_MS=86400000
CHUNK_RAW=180000
now_ms=lambda:1700000000000
canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')).encode()
strict_json=json.loads
valid_timestamp=lambda v:type(v) is int and v>0
is_reserved_ephemeral_phone_control=lambda _:False
personal_sync_contract=SimpleNamespace(NOTE_MODE_KIND='note-mode',DESKTOP_FEATURES_KIND='features')
shared_sync_contract=SimpleNamespace(KIND='shared',START_KIND='start')
personal_actor_contract=SimpleNamespace(is_reserved_kind=lambda _:False)
# These gates are not tested here; the inputs are already constructed ordinary requests.
validate_personal_sync_body=lambda *args:None
mime_from_magic=lambda raw:'application/pdf' if raw.startswith(b'%PDF-') else ''
path=Path(sys.argv.pop(1)); candidate='--candidate' in sys.argv
if candidate: sys.argv.remove('--candidate')
source=path.read_text(); lines=source.splitlines(True)
methods={n.name:n for c in ast.parse(source).body if isinstance(c,ast.ClassDef) and c.name=='PhoneStore' for n in c.body if isinstance(n,ast.FunctionDef)}
names=('queue','queue_format2_run','_personal_run_record','remember_personal_run','active_auto_run')
expected=(('91027663b8cd5ef5','20cf8132504f0a21','95cfef2b030d25ed','d9158175a63efc31','dc0309c8b718bd58') if candidate else ('ec1c48166bb1b5d','40cec0c6f9e9ee9f','5201f6e3cc0ab0da','f20b5f24e0c05d2f','dc0309c8b718bd58'))
extracted=[]
for name,want in zip(names,expected):
    n=methods[name]; body=''.join(lines[n.lineno-1:n.end_lineno]); h=14695981039346656037
    for c in body: h=((h^ord(c))*1099511628211)&((1<<64)-1)
    assert format(h,'x')==want,(name,format(h,'x'),want)
    extracted.append(body)
exec(compile('class PhoneStore:\n'+'\n'.join(extracted),str(path),'exec'))
class Store(PhoneStore):
    def __init__(self,path):
        self.database_path=path
        self.cipher=AESGCM(bytes(32))
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value BLOB);
            CREATE TABLE IF NOT EXISTS outbox(message_id TEXT PRIMARY KEY,peer_id TEXT,kind TEXT,created_ms INT,expires_ms INT,payload BLOB,attempts INT,next_attempt_ms INT,last_error TEXT,transport_policy TEXT);
            CREATE TABLE IF NOT EXISTS personal_attachment_chunk(peer_id TEXT,run_id TEXT,reply INT,records_hash TEXT,sha256 TEXT,direction TEXT,chunk_index INT,payload BLOB);
            CREATE TABLE IF NOT EXISTS personal_attachment_transfer(peer_id TEXT,run_id TEXT,reply INT,records_hash TEXT,sha256 TEXT,direction TEXT,size INT,mime TEXT,transport_policy TEXT,expires_ms INT,complete INT,metadata BLOB);''')
    def _encrypt(self,data,kind,key):
        nonce=os.urandom(12);return nonce+self.cipher.encrypt(nonce,data,(kind+':'+key).encode())
    def _decrypt(self,data,kind,key):
        return self.cipher.decrypt(data[:12],data[12:],(kind+':'+key).encode())
    def _attachment_primary(self,*args):return ':'.join(map(str,args))
    def _attachment_metadata(self,*args):return args
    def _encrypt_attachment_metadata(self,v):return self._encrypt(canonical(v),'metadata','test')
class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=self.temp.name+'/q.sqlite';self.s=Store(self.path)
        self.peer='peer';self.run=str(uuid.uuid4());self.req={'format':2,'run_id':self.run,'trigger':'auto_wifi','modules':['notes']}
        self.batch={'run_id':self.run,'records_hash':'a'*64,'reply':False}
        self.msgs=[('personal_sync.request',self.req,3600000),('personal_sync.batch',self.batch,DAY_MS)]
    def register_and_queue(self,group=False,attachments=()):
        # Exact old/new call order from the service; remaining service gates are not run.
        if not candidate:self.s.remember_personal_run(self.peer,self.req)
        options={'remember_request':True} if candidate else {}
        if group:return self.s.queue_format2_run(self.peer,self.msgs,attachments,'wifi_only',**options)
        return self.s.queue(self.peer,'personal_sync.request',self.req,3600000,'wifi_only',**options)
    def count(self,table):
        with sqlite3.connect(self.path) as db:return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def full(self):
        with sqlite3.connect(self.path) as db:db.execute("INSERT INTO outbox(message_id,peer_id,payload) VALUES('unrelated','another',zeroblob(52428800))")
    def clear_full(self):
        with sqlite3.connect(self.path) as db:db.execute("DELETE FROM outbox WHERE message_id='unrelated'")
    def assert_no_phantom(self):
        reopened=Store(self.path)
        self.assertEqual('',reopened.active_auto_run(self.peer))
        self.assertIsNone(reopened._personal_run_record(self.peer,self.run))
    def test_simple_capacity_retry(self):
        self.full()
        with self.assertRaisesRegex(RuntimeError,'queue_full'):self.register_and_queue()
        self.assertEqual(1,self.count('outbox'));self.assert_no_phantom()
        self.clear_full();self.register_and_queue();self.assertEqual(self.run,Store(self.path).active_auto_run(self.peer))
    def test_group_capacity_retry(self):
        self.full()
        with self.assertRaisesRegex(RuntimeError,'attachment staging capacity'):self.register_and_queue(True)
        self.assertEqual(1,self.count('outbox'));self.assert_no_phantom()
        self.clear_full();self.register_and_queue(True);self.assertEqual(2,self.count('outbox'))
    def test_invalid_attachment_no_phantom(self):
        raw=b'%PDF-test'; desc={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'mime':'application/pdf','attachment_id':'a'}
        with self.assertRaisesRegex(ValueError,'attachment source changed'):self.register_and_queue(True,[(desc,raw+b'x')])
        self.assertEqual(0,self.count('outbox'));self.assert_no_phantom()
    def test_sql_abort_simple(self):
        with sqlite3.connect(self.path) as db:db.execute("CREATE TRIGGER fail BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.register_and_queue()
        self.assertEqual(0,self.count('outbox'));self.assert_no_phantom()
    def test_sql_abort_group_rolls_back_staged_attachment(self):
        raw=b'%PDF-test';desc={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'mime':'application/pdf','attachment_id':'a'}
        with sqlite3.connect(self.path) as db:db.execute("CREATE TRIGGER fail BEFORE INSERT ON outbox WHEN NEW.kind='personal_sync.batch' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.register_and_queue(True,[(desc,raw)])
        for table in ('outbox','personal_attachment_chunk','personal_attachment_transfer'):self.assertEqual(0,self.count(table))
        self.assert_no_phantom()
    def test_success_survives_reopen_without_marker(self):
        self.register_and_queue(True);reopened=Store(self.path)
        self.assertEqual(self.req,reopened._personal_run_record(self.peer,self.run)['body'])
        self.assertEqual(self.run,reopened.active_auto_run(self.peer));self.assertEqual(2,self.count('outbox'))
    def test_existing_conflicting_run_remains(self):
        old=dict(self.req,modules=['tasks']);self.s.remember_personal_run(self.peer,old)
        with self.assertRaisesRegex(ValueError,'conflicting personal sync run'):self.register_and_queue(True)
        self.assertEqual(old,self.s._personal_run_record(self.peer,self.run)['body']);self.assertEqual(0,self.count('outbox'))
    def test_received_run_expiry_unchanged(self):
        self.s.remember_personal_run(self.peer,self.req,now_ms()+60000)
        self.assertEqual(now_ms()+60000,self.s._personal_run_record(self.peer,self.run)['expires_ms'])
        with self.assertRaisesRegex(ValueError,'lifetime extension'):self.s.remember_personal_run(self.peer,self.req,now_ms()+60001)
    def test_existing_run_not_deleted_on_queue_failure(self):
        self.s.remember_personal_run(self.peer,self.req); self.full()
        with self.assertRaises(RuntimeError):self.register_and_queue(True)
        self.assertEqual(self.req,self.s._personal_run_record(self.peer,self.run)['body'])
if __name__=='__main__':unittest.main(verbosity=2)
