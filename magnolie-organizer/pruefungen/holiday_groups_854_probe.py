#!/usr/bin/env python3
"""Refs #854 #857. Exact Linux holiday functions with a controlled HTTP host.
Usage: python3 probe.py <checkout or source-file> [captured-fixture-directory].
Captured provider bytes are replayed without making live network requests.
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
for name,bad in [('wrong group',centre),('unknown code',row(groups=['NL-XX'])),('foreign code',row(groups=['BE-DE'])),('prefixless code',row(groups=['NO'])),('missing identity',row()),('wrong type',{**north,'groups':'NL-NO'}),('mixed valid/invalid',row(groups=['NL-NO','NL-XX'])),('explicit local restriction',{**row(groups=['NL-NO'],subdivisions=['NL-GM001']), 'regionalScope':'Local'}),('contradictory nationwide',row(groups=['NL-NO'],nationwide=True))]:
    a,c=run('NL','NL-NO',[north,bad]);check(name+' not broadened and no coverage',lambda:len(schools(a))==1 and schools(a)[0]['regions']==['NL-NO'] and not scope(a))
a,c=run('NL','NL-NO',[]);check('empty group no delete authority',lambda:not scope(a) and not schools(a))
a,c=run('NL','',[]);check('empty country school no delete authority',lambda:not scope(a) and not schools(a))
a,c=run('NL','', [row(groups=['NL-NO'],subdivisions=['NL-GM001'],nationwide=True)]);check('contradictory nationwide municipal data rejected',lambda:not schools(a) and not scope(a))
a,c=run('NL','NL-NO',RuntimeError('offline'));check('offline school preserves public scope',lambda:not scope(a) and scope(a,'public-holiday')==[''])
a,c=run('NL','NL-NO',[row('National',nationwide=True)]);check('nationwide accepted without proving group coverage',lambda:schools(a)[0]['nationwide'] and not scope(a))
a,c=run('NL','NL-NO',[north,row('National',nationwide=True)]);check('nationwide plus explicit group proves structural scope',lambda:len(schools(a))==2 and scope(a)==['NL-NO'])
a,c=run('NL','',[north]);check('country response missing other groups no delete authority',lambda:len(schools(a))==1 and schools(a)[0]['regions']==['NL-NO'] and not scope(a))
a,c=run('NL','', [{**row(groups=['NL-NO'],subdivisions=['NL-GM001']), 'regionalScope':'Local'}]);check('country explicit local scope not widened',lambda:schools(a)[0]['regions']==['NL-GM001'] and not scope(a))
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
fixtures = Path(sys.argv[2]) if len(sys.argv) > 2 else path.parents[2] / 'contracts/fixtures/holiday-groups-2026-11-28'
def captured(land, group=''):
    calls=[]
    def http(url):
        u=urlsplit(url);q={k:v[0] for k,v in parse_qs(u.query).items()};calls.append((u.path,q))
        prefix = q.get('groupCode',land) if u.path.endswith('SchoolHolidays') else land
        return (fixtures / (prefix + '-' + u.path.rsplit('/',1)[1] + '.json')).read_text()
    return fetch(land,group,[2026],holer=http),calls
def expected_scopes(rows):
    result={}
    for item in rows:
        key=(item['startDate'],item['endDate'],item['name'][0]['text'])
        result.setdefault(key,set()).update(g['code'] for g in item.get('groups',[]))
    return {key:sorted(value) for key,value in result.items()}
for land,codes in [('BE',['BE-DE','BE-FR','BE-NL']),('NL',['NL-NO','NL-MI','NL-ZU'])]:
    for group in ['',*codes]:
        data=json.loads((fixtures / ((group or land)+'-SchoolHolidays.json')).read_text())
        expected=expected_scopes(data)
        a,c=captured(land,group)
        check((group or land)+' raw captured rows retain exact group identities and dates',lambda: {(r['von'],r['bis'],r['name']):r['regions'] for r in schools(a)}==expected)
        check((group or land)+' captured school scope authorized',lambda:scope(a)==[group])
        check((group or land)+' captured public remains nationwide',lambda:scope(a,'public-holiday')==[''] and all('groupCode' not in q and 'subdivisionCode' not in q for q in params(c,'PublicHolidays')))
    code=codes[0]; expanded=row(groups=[code],subdivisions=[land+'-MUNICIPAL'])
    a,c=run(land,code,[expanded]);check(land+' synthetic expanded group has only group identity',lambda:schools(a)[0]['regions']==[code] and scope(a)==[code])
    a,c=run(land,code,[{**expanded,'tags':['Exception']}]);check(land+' Exception tag alone does not remove explicit group identity',lambda:schools(a)[0]['regions']==[code] and scope(a)==[code])
    a,c=run(land,code,[row(groups=codes,subdivisions=[land+'-MUNICIPAL'],nationwide=True)]);check(land+' all groups nationwide with expansion remains consistent',lambda:schools(a)[0]['regions']==sorted(codes) and scope(a)==[code])
    a,c=run(land,'',[row(subdivisions=[land+'-MUNICIPAL'])]);check(land+' subdivision-only country row retained without group coverage',lambda:schools(a)[0]['regions']==[land+'-MUNICIPAL'] and not scope(a))
    for invalid in ['Unknown',42,None]:
        a,c=run(land,code,[{**row(groups=[code]),'regionalScope':invalid}]);check(land+' invalid regionalScope '+repr(invalid)+' grants no coverage',lambda:len(schools(a))==1 and schools(a)[0]['regions']==[code] and not scope(a))
    for label,bad in [('foreign subdivision',{**expanded,'subdivisions':[{'code':'XX-FOREIGN'}]}),('prefixless subdivision',{**expanded,'subdivisions':[{'code':'MUNICIPAL'}]}),('malformed subdivisions',{**expanded,'subdivisions':'invalid'}),('local without local identity',{**row(groups=[code]),'regionalScope':'Local'})]:
        a,c=run(land,code,[bad]);check(land+' '+label+' not widened',lambda:not schools(a) and not scope(a))
result={'passed':sum(x['passed'] for x in checks),'total':len(checks),'checks':checks}
print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(result['passed']!=result['total'])
