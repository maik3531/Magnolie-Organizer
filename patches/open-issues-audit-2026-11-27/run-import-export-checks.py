#!/usr/bin/env python3
"""Run existing semantic exchange contracts using actual desktop codecs and synthetic data."""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--checkout',type=Path,required=True)
p.add_argument('--tools',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--extra-test',action='append',default=[])
a=p.parse_args(); root=a.checkout.resolve(); tools=a.tools.resolve(); out=a.output.resolve()
out.mkdir(parents=True,exist_ok=True)
env_values={'TZ':'Europe/Berlin','MAGNOLIE_TEST_SOURCE_ROOT':str(root),
 'DOTNET_CLI_HOME':str(tools/'dotnet-state'),'NUGET_PACKAGES':str(tools/'nuget'),
 'DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false'}
env=dict(os.environ,**env_values)
sha=lambda b:hashlib.sha256(b).hexdigest()
def git(*args): return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
tests=['test_native_import_regressions.py','test_csv_unicode_import.py',
 'test_contact_type_category_separation.py','test_contact_person_details.py',
 'test_thunderbird_contacts.py','test_kde_contact_export.py',
 'test_mcp_records_export.py','test_mcp_local_import.py','test_category_colors.py',
 'test_or6_import.py','test_or6_contact_region.py','test_or6_contact_source_text.py',
 'test_waste_import.py','test_contact_time_contract.py',
 'test_calendar_color_remainders.py','test_calendar_birthday_dedup.py',
 'test_calendar_birthday_cleanup.py',
 'test_nextcloud.py::test_nextcloud_partial_report_aborts_without_result']
tests=['magnolie-organizer/pruefungen/'+n for n in tests]
tests += a.extra_test
inputs=list(dict.fromkeys(t.split('::')[0] for t in tests))+['magnolie-organizer/pruefungen/test_import_export_vertrag.py',
 'magnolie-organizer/bin/magnolie-organizer','magnolie-organizer/bin/magnolie_or6.py',
 'magnolie-organizer-windows/ExchangeCodec.cs','magnolie-organizer-windows/RecordExportFile.cs',
 'magnolie-organizer-windows/tests/RecordExportFileTests.cs','magnolie-organizer-windows/tests/CategoryColorTests.cs',
 'magnolie-organizer-windows/tests/UnicodeImportTests.cs','magnolie-organizer-windows/tests/Program.cs']
manifest={'source_head':git('rev-parse','HEAD'),'source_tree':git('rev-parse','HEAD^{tree}'),
 'inputs':{f:sha((root/f).read_bytes()) for f in inputs},'environment':env_values,'runs':[],
 'limits':'Actual Python and .NET codecs with synthetic data on Linux. No installed desktop UI, native provider, Apple/Android OS, private original book or package acceptance.'}
def run(name,cmd,cwd=root,run_env=env):
 start=time.monotonic();r=subprocess.run(list(map(str,cmd)),cwd=cwd,env=run_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
 file=out/(name+'.log');file.write_bytes(r.stdout);text=r.stdout.decode(errors='replace')
 row={'name':name,'command':list(map(str,cmd)),'cwd':str(cwd),'exit_code':r.returncode,
 'seconds':round(time.monotonic()-start,3),'log':file.name,'sha256':sha(r.stdout),
 'source_root':run_env['MAGNOLIE_TEST_SOURCE_ROOT']}
 if name=='python-semantics': row['pytest_counts']={k:int(n) for n,k in re.findall(r'(\d+) (passed|failed|skipped|errors?)',text)}
 if name=='python-file-contract': row['assertion_checks']=len(re.findall(r'^  ok\s+-',text,re.M))
 m=re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden',text)
 if m: row.update(passed_groups=int(m[1]),total_groups=int(m[2]))
 manifest['runs'].append(row); print(json.dumps(row),flush=True)
 return r.returncode
run('python-file-contract',[tools/'python/bin/python','magnolie-organizer/pruefungen/test_import_export_vertrag.py'])
run('python-semantics',[tools/'python/bin/python','-m','pytest','-q',*tests])
win=root/'magnolie-organizer-windows';dll=win/'tests/bin/Debug/net8.0/CoreTests.dll'
assert dll.is_file(), 'Use existing successfully built final source assembly first'
manifest['assembly_sha256']=sha(dll.read_bytes())
for name,term in [('csharp-record-export','Record export / native codecs'),
 ('csharp-category-colors','Category colors'),
 ('csharp-encoding','UTF-16 import'),('csharp-or6','OR6 import / native fixtures'),
 ('csharp-or6-extension','OR6 extension / original recurring'),
 ('csharp-thunderbird','Thunderbird local.sqlite Schema 23')]:
 run(name,[tools/'dotnet/dotnet',dll,term],win,dict(env,MAGNOLIE_TEST_SOURCE_ROOT=str(win)))
manifest['inputs_unchanged']=all(sha((root/f).read_bytes())==v for f,v in manifest['inputs'].items())
manifest['worktree_status']=git('status','--porcelain')
manifest['passed']=all(r['exit_code']==0 and (not r['name'].startswith('csharp-') or
 r.get('passed_groups')==r.get('total_groups')==(3 if r['name']=='csharp-category-colors' else 1)) for r in manifest['runs'])
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if manifest['passed'] else 1)
