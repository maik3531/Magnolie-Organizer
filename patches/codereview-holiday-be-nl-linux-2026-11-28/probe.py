#!/usr/bin/env python3
"""Refs #854. Execute the exact Linux holiday functions with a controlled HTTP host.
Usage: python3 probe.py <checkout or source-file>. No live provider calls.
"""
import ast
import datetime
import json
import re
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

path = Path(sys.argv[1])
if path.is_dir():
    path = path / 'magnolie-organizer/bin/magnolie-organizer'
source = path.read_text()
funcs = {'_feiertag_sprache', '_name_waehlen', '_openholidays_region_code',
         '_openholidays_schulgruppen', '_openholidays_auswerten', 'feiertage_abrufen'}
module = ast.parse(source)
selected = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in funcs]
class GroessenFehler(RuntimeError):
    pass

def iso(value):
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False

setup = types.ModuleType('magnolie_setup_ui')
setup.REGIONS_BY_COUNTRY = {'DE': [('DE-BY','Bayern')], 'AT': [('AT-9','Wien')]}
setup.school_holiday_region = lambda land, code: (code if any(c == code for c, _ in setup.REGIONS_BY_COUNTRY.get(land, [])) else '', '')
sys.modules['magnolie_setup_ui'] = setup
ctx = {'json': json, 're': re, '_REGIONAL': {'language': 'de'}, '_': lambda s:s,
       '_ist_iso': iso, 'FEIERTAG_DIENST':'https://openholidaysapi.org',
       'FEIERTAG_ABRUF_MAX': 1000000, 'GroessenFehler':GroessenFehler,
       'kanonischer_text': lambda s:s.casefold(), 'ngettext':lambda a,b,n:a if n==1 else b}
exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),ctx)
fetch=ctx['feiertage_abrufen']

def row(name='Fixture', groups=(), subdivisions=(), nationwide=False, start='2026-07-04', end='2026-08-16'):
    return dict(startDate=start,endDate=end,name=[dict(language='DE',text=name)],nationwide=nationwide,
                groups=[dict(code=g,shortName=g.split('-')[-1]) for g in groups],
                subdivisions=[dict(code=s) for s in subdivisions])

public = row('Public',nationwide=True,start='2026-01-01',end='2026-01-01')
# Dates and group codes follow the pinned provider data (NL summer 2026 and BE-DE
# carnival 2026); JSON shape is a constructed fixture, not a captured response.
north = row('Summer North', ['NL-NO'])
centre = row('Summer Centre', ['NL-MI'],start='2026-07-18',end='2026-08-30')
south = row('Summer South', ['NL-ZU'],start='2026-07-11',end='2026-08-23')
shared = row('Shared winter',['NL-NO','NL-MI','NL-ZU'],start='2026-12-19',end='2027-01-03')
be = row('Carnival',['BE-DE'],start='2026-02-16',end='2026-02-21')

def run(land,region='',school=(),pub=(public,),regions=None,ferien=True):
    calls=[]
    def http(url):
        u=urlsplit(url); q={k:v[0] for k,v in parse_qs(u.query).items()}; calls.append((u.path,q))
        data=pub if u.path.endswith('PublicHolidays') else school
        if callable(data): data=data(q)
        if isinstance(data,Exception): raise data
        return json.dumps(data)
    ans=fetch(land,region,[2026],ferien=ferien,holer=http,regionen=regions)
    return ans,calls

def schools(ans): return [r for r in ans['feiertage'] if r['art']=='school-holiday']
def scope(ans,art='school-holiday'): return [r['region'] for r in ans['abrufbereiche'] if r['art']==art]
def params(calls,endpoint): return [q for p,q in calls if p=='/'+endpoint]

checks=[]
def check(name,fn):
    try: ok=bool(fn()); detail='' if ok else 'assertion false'
    except Exception as e: ok=False;detail=f'{type(e).__name__}: {e}'
    checks.append(dict(name=name,passed=ok,detail=detail))

for land,group,fixture in [('NL','NL-NO',north),('BE','BE-DE',be),('NL','NL-MI',centre),('NL','NL-ZU',south),('BE','BE-FR',row(groups=['BE-FR'])),('BE','BE-NL',row(groups=['BE-NL']))]:
    a,c=run(land,group,[fixture]);
    check(group+' uses groupCode',lambda:params(c,'SchoolHolidays')[0].get('groupCode')==group and 'subdivisionCode' not in params(c,'SchoolHolidays')[0])
    check(group+' public unfiltered',lambda:'subdivisionCode' not in params(c,'PublicHolidays')[0] and 'groupCode' not in params(c,'PublicHolidays')[0] and scope(a,'public-holiday')==[''] and [r['region'] for r in a['feiertage'] if r['art']=='public-holiday']==[''])
    check(group+' canonical positive scope',lambda: schools(a)[0]['regions']==[group] and scope(a)==[group])

a,c=run('NL','', [north,centre,south,shared]);
check('country query keeps all four group identities',lambda:len(schools(a))==4 and {tuple(r['regions']) for r in schools(a)}=={('NL-NO',),('NL-MI',),('NL-ZU',),('NL-MI','NL-NO','NL-ZU')} and scope(a)==[''])
check('country query preserves cross-year interval',lambda:next(r for r in schools(a) if r['name']=='Shared winter')['bis']=='2027-01-03')
a,c=run('NL','NL-NO',[shared]);check('multi-group source identity retained',lambda:schools(a)[0]['regions']==['NL-MI','NL-NO','NL-ZU'] and scope(a)==['NL-NO'])
for name,bad in [('wrong group',centre),('unknown code',row(groups=['NL-XX'])),('foreign code',row(groups=['BE-DE'])),('prefixless code',row(groups=['NO'])),('missing identity',row()),('wrong type',{**north,'groups':'NL-NO'}),('mixed valid/invalid',row(groups=['NL-NO','NL-XX'])),('municipal restriction',row(groups=['NL-NO'],subdivisions=['NL-GM001'])),('contradictory nationwide',row(groups=['NL-NO'],nationwide=True))]:
    a,c=run('NL','NL-NO',[north,bad]);check(name+' not broadened and no coverage',lambda:len(schools(a))==1 and schools(a)[0]['regions']==['NL-NO'] and not scope(a))
a,c=run('NL','NL-NO',[]);check('empty group no delete authority',lambda:not scope(a) and not schools(a))
a,c=run('NL','',[]);check('empty country school no delete authority',lambda:not scope(a) and not schools(a))
a,c=run('NL','', [row(groups=['NL-NO'],subdivisions=['NL-GM001'],nationwide=True)]);check('contradictory nationwide municipal data rejected',lambda:not schools(a) and not scope(a))
a,c=run('NL','NL-NO',RuntimeError('offline'));check('offline school preserves public scope',lambda:not scope(a) and scope(a,'public-holiday')==[''])
a,c=run('NL','NL-NO',[row('National',nationwide=True)]);check('nationwide accepted without proving group coverage',lambda:schools(a)[0]['nationwide'] and not scope(a))
a,c=run('NL','NL-NO',[north,row('National',nationwide=True)]);check('nationwide plus explicit group proves structural scope',lambda:len(schools(a))==2 and scope(a)==['NL-NO'])
a,c=run('NL','',[north]);check('country response missing other groups no delete authority',lambda:len(schools(a))==1 and schools(a)[0]['regions']==['NL-NO'] and not scope(a))
a,c=run('NL','', [row(groups=['NL-NO'],subdivisions=['NL-GM001'])]);check('country municipality not widened',lambda:schools(a)[0]['regions']==['NL-GM001'] and not scope(a))
a,c=run('NL','NL-NO',[],ferien=False);check('school opt-out only public',lambda:len(c)==1 and scope(a,'public-holiday')==[''] and not scope(a))
a,c=run('NL',school=lambda q:[{'NL-NO':north,'NL-MI':centre,'NL-ZU':south}[q.get('groupCode',q.get('subdivisionCode'))]],regions=[('NL-NO','Noord'),('NL-MI','Midden'),('NL-ZU','Zuid')]);check('three group fanout and one public',lambda:len(params(c,'PublicHolidays'))==1 and {q.get('groupCode') for q in params(c,'SchoolHolidays')}=={'NL-NO','NL-MI','NL-ZU'} and set(scope(a))=={'NL-NO','NL-MI','NL-ZU'})
def mixed_rejected():
    try: run('NL',regions=[('NL-NO','Noord'),('NL-GM001','Gemeente')])
    except RuntimeError: return True
    return False
check('group plus subdivision selection rejected',mixed_rejected)
a,c=run('AT','AT-9',[row(subdivisions=['AT-WI'])]);check('AT ISO mapping unchanged',lambda:params(c,'SchoolHolidays')[0].get('subdivisionCode')=='AT-WI' and schools(a)[0]['regions']==['AT-9'] and scope(a)==['AT-9'])
a,c=run('DE','DE-BY',[row(subdivisions=['DE-BY'])]);check('DE subdivision unchanged',lambda:params(c,'SchoolHolidays')[0].get('subdivisionCode')=='DE-BY' and scope(a)==['DE-BY'])
a,c=run('NL','NL-GM001',[row(subdivisions=['NL-GM001'])]);check('legacy municipality selection unchanged',lambda:params(c,'SchoolHolidays')[0].get('subdivisionCode')=='NL-GM001' and schools(a)[0]['regions']==['NL-GM001'])
result={'passed':sum(x['passed'] for x in checks),'total':len(checks),'checks':checks}
print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(result['passed']!=result['total'])
