from pathlib import Path
import hashlib
import json
import subprocess
import sys

repo=Path(sys.argv[1]).resolve()
evidence=Path(sys.argv[3]).resolve() if len(sys.argv)>3 else Path(__file__).resolve().parent
evidence.mkdir(parents=True,exist_ok=True)
deps=Path(sys.argv[2]).resolve()
out=evidence/'native-after'
out.mkdir(exist_ok=True)
cp=':'.join(str(p) for p in sorted(deps.glob('*.jar')))
main=repo/'Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta'
tests=repo/'Magnolie-Organizer-Android-Tablet-Beta/app/src/test/java/io/gitlab/maik3531/magnolietabletbeta'
sources=[main/(f+'.kt') for f in ['EligibleAlarms','Vault','VaultJson','StorageFileOps','NioStorageFileOps','OrdinarySaveEpochPolicy','BookRestore','StandardBase64','Pbkdf2Sha256']]
sources += [repo/'magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten/DatenDateiKrypto.kt',tests/'JsonValueComparison.kt',tests/'VaultTest.kt']
commands=[['java','-cp',cp,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-jvm-target','17','-no-stdlib','-no-reflect','-classpath',cp,'-d',str(out),*map(str,sources)],
['java','-Dtablet.root='+str(repo/'Magnolie-Organizer-Android-Tablet-Beta'),'-cp',str(out)+':'+cp,'org.junit.runner.JUnitCore','io.gitlab.maik3531.magnolietabletbeta.VaultTest']]
records=[]
for name,cmd in zip(['compile','junit'],commands):
 result=subprocess.run(cmd,text=True,capture_output=True)
 text=result.stdout+result.stderr
 (evidence/f'native-{name}-after.log').write_text(text)
 records.append({'name':name,'exit_code':result.returncode,'log':f'native-{name}-after.log'})
 print(name,result.returncode,text,flush=True)
 if result.returncode:break
(evidence/'native-test-manifest.json').write_text(json.dumps({'scope':'Actual JVM product classes and existing VaultTest. No Android OS/NotificationManager execution.','source_files':{str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},'runs':records},indent=2)+'\n')
sys.exit(records[-1]['exit_code'])
