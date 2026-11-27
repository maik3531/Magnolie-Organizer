#!/usr/bin/env python3
"""Rebuild changed C# test assembly on the final frozen base and run affected groups."""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--checkout',type=Path,required=True)
p.add_argument('--tools',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
root,tools,out=a.checkout.resolve(),a.tools.resolve(),a.output.resolve()
out.mkdir(parents=True,exist_ok=True)
win=root/'magnolie-organizer-windows'
dotnet=tools/'dotnet/dotnet'
env_add={'TZ':'Europe/Berlin','MAGNOLIE_TEST_SOURCE_ROOT':str(root),
 'DOTNET_CLI_HOME':str(tools/'dotnet-state'),'NUGET_PACKAGES':str(tools/'nuget'),
 'DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false'}
env=dict(os.environ,**env_add)
sha=lambda b:hashlib.sha256(b).hexdigest()
def git(*args):
 return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
paths=[p for p in git('ls-files','magnolie-organizer-windows','contracts').splitlines()
       if p.endswith(('.cs','.csproj','.props','.targets','packages.lock.json')) or p.startswith('contracts/') and p.endswith('.json')]
inputs={p:sha(subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{p}'])) for p in paths}
data={'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),
 'base':'24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b','tracked_source_and_contract_hashes':inputs,
 'reason':'Upstream changed Program.cs and added UnicodeImportTests.cs after the previous tested assembly; preserve that registration and rebuild.',
 'environment':env_add,'runs':[],'native_windows':False}
def run(name,command,expected=None):
 started=time.monotonic()
 r=subprocess.run(list(map(str,command)),cwd=win,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
 file=out/(name+'.log');file.write_bytes(r.stdout)
 row={'name':name,'command':list(map(str,command)),'cwd':str(win),'exit_code':r.returncode,
      'seconds':round(time.monotonic()-started,3),'log':file.name,'sha256':sha(r.stdout)}
 if expected:
  m=re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden',r.stdout.decode())
  row.update(passed_groups=int(m[1]) if m else None,total_groups=int(m[2]) if m else None,expected_groups=expected)
 data['runs'].append(row); print(json.dumps(row),flush=True)
 assert r.returncode==0, r.stdout.decode()[-5000:]
 if expected: assert row['passed_groups']==row['total_groups']==expected
run('core-build',[dotnet,'build','tests/CoreTests.csproj','--nologo','--verbosity','quiet','-p:RestoreLockedMode=true'])
dll=win/'tests/bin/Debug/net8.0/CoreTests.dll';data['assembly_sha256']=sha(dll.read_bytes())
for name,term,count in [('csv','CSV',2),('restore-identity','Additive restore',1),
 ('recovery-journal','Wiederherstellungsjournal',1),('exchange','ICS / VCF / LDIF / Claws / Lotus / Thunderbird',1),
 ('import-file','Import file / native readers',1)]:
 run(name,[dotnet,dll,term],count)
data['worktree_status']=git('status','--porcelain')
data['passed']=True
(out/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
