#!/usr/bin/env python3
import argparse,hashlib,json,os,platform,resource,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--phase',required=True);p.add_argument('--root',type=Path,default=Path('/workspace/scratch/7203da5bd564/open-audit-395-worker-url'));p.add_argument('--expect-clean',action='store_true');a=p.parse_args()
b=Path(__file__).resolve().parent;logs=b/'logs';logs.mkdir(exist_ok=True);env=os.environ.copy();env['NODE_PATH']='/workspace/scratch/7203da5bd564/round3-tools/js/node_modules'
commands=[['node',str(b/'actual-url-probe.cjs'),str(a.root),str(b/(a.phase+'-actual-urls.json'))]+(['--expect-clean']if a.expect_clean else []),['node','magnolie-organizer-windows/tests/recurrence-worker.js'],['python',str(b/'check_projection.py'),str(a.root)]]
results=[]
for i,cmd in enumerate(commands):
 name=['actual-urls','recurrence-worker','projection-adapters'][i];log=logs/(a.phase+'-'+name+'.log');start=time.monotonic()
 with log.open('w') as out:
  try:r=subprocess.run(cmd,cwd=a.root,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=180);code=r.returncode
  except subprocess.TimeoutExpired:code=124
 results.append({'name':name,'command':cmd,'exit_code':code,'elapsed_s':round(time.monotonic()-start,3),'log':str(log)});print(json.dumps(results[-1]),flush=True)
inputs=['magnolie-organizer/web/anwendung.js','magnolie-organizer-windows/app/web/anwendung.js','magnolie-organizer-windows/tests/recurrence-worker.js','magnolie-organizer-windows/tests/desktop-state-regressions.js','magnolie-organizer-windows/tests/worker-file-fixture.js','magnolie-organizer/web/normative-timezones.js','magnolie-organizer-windows/app/web/normative-timezones.js']
m={'issue':843,'phase':a.phase,'root':str(a.root),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=a.root,text=True).strip(),'git_status':subprocess.check_output(['git','status','--short'],cwd=a.root,text=True),'env':{'NODE_PATH':env['NODE_PATH']},'platform':platform.platform(),'node':subprocess.check_output(['node','--version'],text=True).strip(),'inputs':{f:hashlib.sha256((a.root/f).read_bytes()).hexdigest()for f in inputs},'probe_sha256':hashlib.sha256((b/'actual-url-probe.cjs').read_bytes()).hexdigest(),'results':results,'child_maxrss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
(b/(a.phase+'-manifest.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n');raise SystemExit(1 if any(x['exit_code'] for x in results)else 0)
