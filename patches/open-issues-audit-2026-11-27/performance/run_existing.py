#!/usr/bin/env python3
"""Run one existing Magnolie probe unchanged; retain logs and process RSS samples."""
import argparse,csv,hashlib,json,os,platform,resource,signal,subprocess,time
from pathlib import Path
P=argparse.ArgumentParser();P.add_argument('--name',required=True);P.add_argument('--size',type=int);P.add_argument('--web');P.add_argument('--script',default='magnolie-organizer/pruefungen/last_test.js');P.add_argument('--seconds',type=int,default=300);a=P.parse_args()
base=Path(__file__).resolve().parent;root=base.parents[1]/'open-audit-performance-tests';logs=base/'logs';logs.mkdir(exist_ok=True)
env=os.environ.copy();env['NODE_PATH']=str(base.parents[1]/'round3-tools/js/node_modules');env['MAGNOLIE_SPUR']='1'
if a.size is not None:env['MAGNOLIE_ANZAHL']=str(a.size)
if a.web:env['MAGNOLIE_WEB']=str(root/a.web)
cmd=['node','--max-old-space-size=2048',a.script]
started=time.monotonic();samples=[];stop_reason=None
with (logs/(a.name+'.log')).open('w') as log:
 child=subprocess.Popen(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 while child.poll() is None:
  try:
   status=dict(line.split(':',1) for line in Path('/proc/'+str(child.pid)+'/status').read_text().splitlines() if ':' in line)
   rss=int(status.get('VmRSS','0 kB').split()[0]); hwm=int(status.get('VmHWM','0 kB').split()[0]);threads=int(status.get('Threads','0'))
   fds=len(list(Path('/proc/'+str(child.pid)+'/fd').iterdir()))
   samples.append({'elapsed_s':round(time.monotonic()-started,3),'rss_kib':rss,'hwm_kib':hwm,'threads':threads,'fds':fds})
   if rss>2621440:stop_reason='owned probe RSS exceeded 2.5 GiB safety bound'
  except (OSError,ValueError):pass
  if time.monotonic()-started>a.seconds:stop_reason='owned probe exceeded execution safety deadline'
  if stop_reason:
   os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
   break
  time.sleep(.25)
 code=child.wait()
usage=resource.getrusage(resource.RUSAGE_CHILDREN)
with (logs/(a.name+'.rss.csv')).open('w') as out:
 writer=csv.DictWriter(out,fieldnames=['elapsed_s','rss_kib','hwm_kib','threads','fds']);writer.writeheader();writer.writerows(samples)
manifest={'name':a.name,'command':cmd,'cwd':str(root),'env':{k:env[k] for k in ['NODE_PATH','MAGNOLIE_SPUR','MAGNOLIE_ANZAHL','MAGNOLIE_WEB'] if k in env},'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'exit_code':code,'elapsed_s':round(time.monotonic()-started,3),'child_maxrss_kib':usage.ru_maxrss,'child_user_s':usage.ru_utime,'child_system_s':usage.ru_stime,'stop_reason':stop_reason,'rss_sample_count':len(samples),'script_sha256':hashlib.sha256((root/a.script).read_bytes()).hexdigest(),'node_version':subprocess.check_output(['node','--version'],text=True).strip(),'platform':platform.platform(),'measurement_boundary':'Unchanged source harness in Node/JSDOM with synthetic bridge ACKs; no native GUI, disk Save, tray or month-long execution. RSS includes harness/fixtures/DOM. No explicit GC.'}
(logs/(a.name+'.manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps(manifest,ensure_ascii=False));raise SystemExit(code if code>=0 else 1)
