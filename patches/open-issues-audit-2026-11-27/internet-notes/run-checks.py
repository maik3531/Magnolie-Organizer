#!/usr/bin/env python3
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--only',choices=['python-tree','tree-protocol','mailbox','snapshot','discovery']);a=p.parse_args()
root,tools,out=a.root.resolve(),a.tools.resolve(),a.output.resolve();out.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,TZ='Europe/Berlin',MAGNOLIE_TEST_SOURCE_ROOT=str(root),DOTNET_CLI_HOME=str(tools/'dotnet-state'),NUGET_PACKAGES=str(tools/'nuget'),DOTNET_CLI_TELEMETRY_OPTOUT='1',NODE_PATH=str(tools/'js/node_modules'))
sha=lambda b:hashlib.sha256(b).hexdigest()
def git(*v):return subprocess.check_output(['git','-C',str(root),*v],text=True).strip()
paths=['magnolie-organizer/bin/magnolie-organizer','magnolie-organizer/bin/magnolie_nextcloud.py','magnolie-organizer-windows/MagnolienbaumCoordinator.cs','magnolie-organizer-windows/NextcloudMailbox.cs','magnolie-organizer-windows/tests/Program.cs']
paths += [str(f.relative_to(root)) for f in (root/'magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/baum').glob('*.kt')]
m={'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'inputs':{v:sha((root/v).read_bytes())for v in paths},'runs':[],'boundary':'Actual Python and C# host code with synthetic peers/local fixtures. Notes Kotlin remote route and Compose setup reviewed as source only; Android/Robolectric and real Internet/device/NAT behavior not executed.'}
def run(name,cmd,cwd=root):
 t=time.monotonic();p=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240);f=out/(name+'.log');f.write_bytes(p.stdout);s=p.stdout.decode(errors='replace');row={'name':name,'command':list(map(str,cmd)),'cwd':str(cwd),'exit_code':p.returncode,'seconds':round(time.monotonic()-t,3),'log':f.name,'sha256':sha(p.stdout)}
 if name=='python-tree':row['counts']={k:int(n)for n,k in re.findall(r'(\d+) (passed|failed|skipped|errors?)',s)}
 z=re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden',s)
 if z:row.update(passed_groups=int(z[1]),total_groups=int(z[2]))
 m['runs'].append(row);print(json.dumps(row),flush=True)
tests=['test_fs1_identity_binding.py','test_tree_pair_request.py','test_baum_receipts.py','test_baum_discovery_firewall.py','test_baum_off_state.py','test_baum_ui_opt_in.py','test_auto_sync_transport.py']
if not a.only or a.only=='python-tree':run('python-tree',[tools/'python/bin/python','-m','pytest','-q',*['magnolie-organizer/pruefungen/'+v for v in tests]])
win=root/'magnolie-organizer-windows';dll=win/'tests/bin/Debug/net8.0/CoreTests.dll';m['assembly_sha256']=sha(dll.read_bytes());env['MAGNOLIE_TEST_SOURCE_ROOT']=str(win)
for name,term in [('tree-protocol','Magnolienbaum Crypto / Pairing / FS1 / Replay / Queues / Netzwerk'),('mailbox','Magnolienbaum Nextcloud / WebDAV / Authentisierung'),('snapshot','Baum synchronization snapshot continuity'),('discovery','Magnolienbaum discovery / allowed UDP port / active listener')]:
 if not a.only or a.only==name:run(name,[tools/'dotnet/dotnet',dll,term],win)
m['inputs_unchanged']=all(sha((root/v).read_bytes())==d for v,d in m['inputs'].items());m['passed']=all(x['exit_code']==0 for x in m['runs']);(out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n');raise SystemExit(0 if m['passed'] else 1)
