"""Run the repository's existing projections/UI tests and focused JVM suite.

Usage: python3 run_port_checks.py REPOSITORY EXISTING_TOOL_ROOT OUTPUT_DIRECTORY
Tool root layout: gettext/usr/{bin,lib/x86_64-linux-gnu}, js/node_modules,
kotlin/*.jar. Dependency identities are in kotlin-dependencies.json.
This creates no APK, app bundle, source merge or native delivery claim.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

repo, tools, out = (Path(value).resolve() for value in sys.argv[1:4])
out.mkdir(parents=True,exist_ok=True)
env=dict(os.environ)
env['PATH']=str(tools/'gettext/usr/bin')+os.pathsep+env['PATH']
env['LD_LIBRARY_PATH']=str(tools/'gettext/usr/lib/x86_64-linux-gnu')
env['NODE_PATH']=str(tools/'js/node_modules')
env['MACOS_BETA_JSDOM']=str(tools/'js/node_modules/jsdom/lib/api.js')
# No additional PYTHONPATH is required: the repository entrypoint scripts load
# their own sibling tooling, just as in the existing ports CI workflow.
runs=[]
def run(name,args):
 result=subprocess.run(args,cwd=repo,env=env,text=True,capture_output=True)
 (out/(name+'.log')).write_text(result.stdout+result.stderr)
 runs.append({'name':name,'command':args,'exit_code':result.returncode})
 print(name,'exit',result.returncode,flush=True)
 if result.returncode:
  print(result.stdout,result.stderr)
  (out/'port-runs.json').write_text(json.dumps(runs,indent=2)+'\n')
  raise SystemExit(result.returncode)

for locale in (repo/'magnolie-organizer/po/LINGUAS').read_text().split():
 (repo/'magnolie-organizer/web/i18n').mkdir(exist_ok=True)
 run('catalog-'+locale,[sys.executable,'magnolie-organizer/werkzeuge/po_zu_js.py',locale,
   'magnolie-organizer/po/'+locale+'.po','magnolie-organizer/web/i18n/'+locale+'.js'])
run('import-helper-dependency',[sys.executable,'Magnolie-Organizer-macOS-Beta/tools/project_import_helper.py','--prepare-dependencies'])
run('mac-freeze',[sys.executable,'Magnolie-Organizer-macOS-Beta/tools/project_ui.py','freeze','--confirm-desktop-frozen'])
run('mac-project',[sys.executable,'Magnolie-Organizer-macOS-Beta/tools/project_ui.py','generate'])
run('tablet-project',['node','Magnolie-Organizer-Android-Tablet-Beta/tools/project-web.cjs'])
run('mac-reminder-ui',['node','Magnolie-Organizer-macOS-Beta/tests/system_reminder_import.mjs','Magnolie-Organizer-macOS-Beta/Generated'])
run('tablet-reminder-ui',['node','Magnolie-Organizer-Android-Tablet-Beta/tests/reminders.test.cjs'])
run('tablet-vault-jvm',[sys.executable,str(Path(__file__).resolve().parent/'run_native_tests.py'),str(repo),str(tools/'kotlin'),str(out/'native')])
(out/'port-runs.json').write_text(json.dumps(runs,indent=2)+'\n')
