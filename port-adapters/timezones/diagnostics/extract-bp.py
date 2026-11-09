#!/usr/bin/env python3
"""Diagnostic only: extract the pinned BP rules; these fail the complete independent oracle.
No network access, production-source rewriting or system timezone lookup occurs.
"""
import argparse, fcntl, hashlib, json, subprocess, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiler-cache',type=Path,required=True)
p.add_argument('--threeten-jar',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
record=json.loads((HERE.parents[2]/'Magnolie-Organizer-Android-Tablet-Beta/third-party/threetenbp-1.7.5.json').read_text())
assert hashlib.sha256(a.threeten_jar.read_bytes()).hexdigest()==record['artifactSHA256']
versions=[('kotlin-compiler-embeddable','2.0.21'),('kotlin-stdlib','2.0.21'),('kotlin-script-runtime','2.0.21'),('kotlin-reflect','1.6.10'),('kotlin-daemon-embeddable','2.0.21'),('trove4j','1.0.20200330'),('kotlinx-coroutines-core-jvm','1.6.4'),('annotations','13.0'),('json','20240303')]
jars=[a.compiler_cache/f'{name}-{version}.jar' for name,version in versions]+[a.threeten_jar]
inputs=[HERE/'GeneratePayload.kt',*jars]
def hashes():return {str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in inputs}
cp=':'.join(map(str,jars));java=['java','-Xmx512m','-XX:ActiveProcessorCount=2']
with (a.compiler_cache/'compiler.lock').open('a') as lock,tempfile.TemporaryDirectory(prefix='magnolie-tz-payload-') as temporary:
 fcntl.flock(lock,fcntl.LOCK_EX);before=hashes();out=Path(temporary)
 subprocess.run([*java,'-cp',cp,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',cp,'-d',str(out/'generator.jar'),str(HERE/'GeneratePayload.kt')],check=True,timeout=120)
 subprocess.run([*java,'-cp',str(out/'generator.jar')+':'+cp,'GeneratePayloadKt',str(out/'payload.json')],check=True,timeout=60)
 assert before==hashes(),'Generator inputs changed during execution'
 value=json.loads((out/'payload.json').read_text());assert value['tzdbVersion']=='2026egtz'
 expected=json.dumps(value,sort_keys=True,separators=(',',':'))+'\n'
 assert not a.output.resolve().is_relative_to(HERE.parents[2]),'The known-bad BP data is diagnostic only; do not install it as shared normative data'
 a.output.write_text(expected)
 print('payloadSHA256='+hashlib.sha256(expected.encode()).hexdigest())
