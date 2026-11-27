"""Replay the saved pre-fix UI plan through the original and current Kotlin gate."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

repo,deps,out=(Path(x).resolve() for x in sys.argv[1:4])
here=Path(__file__).resolve().parent
out.mkdir(parents=True,exist_ok=True)
cp=':'.join(str(p) for p in sorted(deps.glob('*.jar')))
current=repo/'Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/EligibleAlarms.kt'
results=[]
for name,source in [('before',here/'baseline-EligibleAlarms.kt'),('after',current)]:
 destination=out/name;destination.mkdir(exist_ok=True)
 compile=subprocess.run(['java','-cp',cp,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-jvm-target','17',
   '-no-stdlib','-no-reflect','-classpath',cp,'-d',str(destination),str(source),str(here/'NativeAlarmCollisionProbe.kt')],text=True,capture_output=True)
 (out/(name+'-compile.log')).write_text(compile.stdout+compile.stderr)
 if compile.returncode:raise SystemExit(compile.returncode)
 result=subprocess.run(['java','-cp',str(destination)+':'+cp,
   'io.gitlab.maik3531.magnolietabletbeta.NativeAlarmCollisionProbeKt',str(here/'collision-before.json'),str(here/'imported-event.json')],text=True,capture_output=True)
 (out/(name+'.log')).write_text(result.stdout+result.stderr)
 results.append({'phase':name,'exit_code':result.returncode,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'result':json.loads(result.stdout)})
 print(name,result.returncode,result.stdout,flush=True)
(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
assert results[0]['exit_code']==1 and results[1]['exit_code']==0
