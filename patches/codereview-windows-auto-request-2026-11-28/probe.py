"""#128 Windows request persistence: real SQLite, not a C# or product test.
SQL strings are from TelefonStore.Enqueue and PersonalSyncStore.ReadMeta/WriteMeta.
The latter substitutes the actual false/IGNORE branch for the interpolated SQL.
Payload bytes and metadata validation are synthetic; no wire, crypto or device claims.
"""
import sqlite3, tempfile, pathlib, sys
LIMIT=50*1024*1024
SELECT_META='SELECT value FROM meta WHERE key=$key'
INSERT_META='INSERT OR IGNORE INTO meta(key,value) VALUES($key,$value)'
SIZE='SELECT COALESCE(SUM(length(payload)),0) FROM outbox'
INSERT='INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES($id,$peer,$kind,$created,$expires,$payload,0,$now,\'\',$policy)'
SCHEMA='''CREATE TABLE meta(key TEXT PRIMARY KEY,value BLOB NOT NULL);
CREATE TABLE outbox(message_id TEXT PRIMARY KEY,peer_id TEXT,kind TEXT,created_ms INTEGER,expires_ms INTEGER,payload BLOB,attempts INTEGER,next_attempt_ms INTEGER,last_error TEXT,transport_policy TEXT);'''
KEY='personal_run:peer:new'; BODY=b'opaque-test-run'; OLD='personal_run:peer:old'
def add(db,id,payload=b'test-message',kind='personal_sync.request',policy='wifi_only'):
    if db.execute(SIZE).fetchone()[0]+len(payload)>LIMIT: raise ValueError('queue_full')
    db.execute(INSERT,dict(id=id,peer='peer',kind=kind,created=100,expires=3600100,payload=payload,now=100,policy=policy))
def remember(db,body):
    prior=db.execute(SELECT_META,dict(key=KEY)).fetchone()
    if prior is not None:
        if prior[0]!=body: raise ValueError('conflicting run')
        return
    db.execute(INSERT_META,dict(key=KEY,value=body))
def run(path,atomic,body=BODY):
    with sqlite3.connect(path) as db:
        if not atomic: remember(db,body)
    with sqlite3.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if atomic: remember(db,body)
        add(db,'new-message')
def scenario(name,atomic):
    with tempfile.TemporaryDirectory() as tmp:
        path=pathlib.Path(tmp)/'phone.db'
        with sqlite3.connect(path) as db:
            db.executescript(SCHEMA); db.execute(INSERT_META,dict(key=OLD,value=b'old-run')); add(db,'status',b'old-status','device_status.request','any')
            if name=='capacity': db.execute("UPDATE outbox SET payload=zeroblob(?) WHERE message_id='status'",(LIMIT,))
            if name in ('insert_failure','retry','existing'): db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON outbox WHEN NEW.message_id='new-message' BEGIN SELECT RAISE(ABORT,'injected'); END")
            if name in ('existing','conflict'): remember(db,BODY)
        error=False
        try: run(path,atomic,b'different' if name=='conflict' else BODY)
        except (ValueError,sqlite3.DatabaseError): error=True
        with sqlite3.connect(path) as db:
            actual=db.execute(SELECT_META,dict(key=KEY)).fetchone(); old=db.execute(SELECT_META,dict(key=OLD)).fetchone()
            rows=db.execute('SELECT message_id,transport_policy FROM outbox ORDER BY message_id').fetchall()
            assert old==(b'old-run',) and ('status','any') in rows
            if name in ('capacity','insert_failure','retry'): assert error and actual is None and rows==[('status','any')]
            if name in ('existing','conflict'): assert error and actual==(BODY,) and rows==[('status','any')]
            if name=='success': assert not error and actual==(BODY,) and rows==[('new-message','wifi_only'),('status','any')]
            if name=='retry': db.execute('DROP TRIGGER fail_insert')
        if name=='retry':
            run(path,atomic)
            with sqlite3.connect(path) as db: assert db.execute(SELECT_META,dict(key=KEY)).fetchone()==(BODY,) and db.execute('SELECT transport_policy FROM outbox WHERE message_id=?',('new-message',)).fetchone()==('wifi_only',)

def main():
    atomic=sys.argv[1]=='after'; failures=0
    for name in ('capacity','insert_failure','retry','existing','conflict','success'):
        try: scenario(name,atomic); print('PASS',name)
        except AssertionError: failures+=1; print('FAIL',name)
    print(f'{6-failures}/6 passed; SQLite {sqlite3.sqlite_version}; mode={sys.argv[1]}')
    return bool(failures)
if __name__=='__main__': sys.exit(main())
