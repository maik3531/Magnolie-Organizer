"""#442: preserve actual import semantics without quadratic prefix copying."""
import random
from pathlib import Path

import pytest

from test_nextcloud import m


def legacy(text):
    lines=text.replace('\r\n','\n').replace('\r','\n').split('\n')
    result=[]
    for line in lines:
        if line[:1] in (' ','\t') and result:result[-1]+=line[1:]
        else:result.append(line)
    return [line for line in result if line.strip()]


class CopyCountedString(str):
    copied=0
    def replace(self,*args):return type(self)(super().replace(*args))
    def split(self,*args):return [type(self)(part) for part in super().split(*args)]
    def __getitem__(self,key):return type(self)(super().__getitem__(key))
    def __add__(self,other):
        type(self).copied+=len(self)+len(other)
        return type(self)(super().__add__(other))


def calendar(count):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-folds\r\n'
            'DTSTART:20261108T090000Z\r\nDTEND:20261108T100000Z\r\nSUMMARY:Folded\r\n'
            'DESCRIPTION:'+'x'*63+'\r\n'+(' '+'x'*74+'\r\n')*count+'END:VEVENT\r\nEND:VCALENDAR\r\n')


def test_actual_unfolder_does_not_recopy_growing_prefix_for_each_fold():
    text=CopyCountedString('DESCRIPTION:'+'x'*63+'\r\n'+(' '+'x'*74+'\r\n')*4096)
    CopyCountedString.copied=0
    assert m._entfalte_zeilen(text)==['DESCRIPTION:'+'x'*(63+74*4096)]
    assert CopyCountedString.copied<=8*len(text), 'Actual unfolder recopies the growing logical line quadratically'


def test_existing_line_endings_blanks_leading_folds_and_unicode_semantics():
    examples=['',' ','\t','\r\n hello','\tfirst\r\n second','a\r\n\t\r\n b\r\n\r\n c','a\rb\n c\r\n\td',' ä\r\n\t中\r\n  🙂']
    rng=random.Random(442)
    for _ in range(1000):
        lines=[''.join(rng.choice('abä中🙂 :;\t') for _ in range(rng.randrange(24))) for _ in range(rng.randrange(20))]
        examples.append(rng.choice(['\r\n','\r','\n']).join(lines))
    for text in examples:assert m._entfalte_zeilen(text)==legacy(text)


@pytest.mark.parametrize('count',[0,1,2,64,512,2048,8192])
def test_complete_actual_import_matches_legacy_unfolding_without_description_loss(monkeypatch,count):
    monkeypatch.setattr(m,'jetzt_ms',lambda:1794139200000)
    monkeypatch.setattr(m,'_neue_uid',lambda:'synthetic-generated-uid')
    monkeypatch.setitem(m._REGIONAL,'timeZone','UTC')
    text=calendar(count)
    assert all(len(line.encode('utf-8'))<=75 for line in text.split('\r\n'))
    actual=m.ics_lesen(text,quellen_id='fold-fixture')
    assert len(actual['termine'])==1 and actual['termine'][0]['notiz']=='x'*(63+74*count)
    with monkeypatch.context() as patch:
        patch.setattr(m,'_entfalte_zeilen',legacy)
        expected=m.ics_lesen(text,quellen_id='fold-fixture')
    assert actual==expected


@pytest.mark.parametrize('fixture',sorted((Path(__file__).parent/'fixtures').glob('*.ics')),ids=lambda p:p.name)
def test_existing_complete_ics_fixtures_match_previous_unfolding(monkeypatch,fixture):
    monkeypatch.setattr(m,'jetzt_ms',lambda:1794139200000)
    monkeypatch.setattr(m,'_neue_uid',lambda:'synthetic-generated-uid')
    monkeypatch.setitem(m._REGIONAL,'timeZone','UTC')
    text=fixture.read_text(encoding='utf-8-sig')
    actual=m.ics_lesen(text,quellen_id='fold-fixture')
    with monkeypatch.context() as patch:
        patch.setattr(m,'_entfalte_zeilen',legacy)
        expected=m.ics_lesen(text,quellen_id='fold-fixture')
    assert actual==expected
