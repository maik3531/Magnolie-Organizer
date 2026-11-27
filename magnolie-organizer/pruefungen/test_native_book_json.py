"""Finite local book numbers never relax the telephone wire format (Refs #761)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_native_book_json import book_hash,canonical_book,parse_book,same_book
from magnolie_telefon import canonical,strict_json


@pytest.mark.parametrize('as_bytes',[False,True])
def test_local_book_roundtrip_preserves_nested_finite_numbers_and_types(as_bytes):
    raw='{"zeichnung":{"punkte":[12.5,-0.125,1e-6,1.7976931348623157e308]},"werte":[true,1,1.0],"titel":"Größe"}'
    parsed=parse_book(raw.encode('utf-8') if as_bytes else raw)
    assert parsed['zeichnung']['punkte']==[12.5,-0.125,1e-6,1.7976931348623157e308]
    assert [type(value) for value in parsed['werte']]==[bool,int,float]
    assert parse_book(canonical_book(parsed))==parsed
    assert same_book(parsed,parse_book(canonical_book(parsed)))
    assert len({book_hash({'wert':value}) for value in (True,1,1.0)})==3


@pytest.mark.parametrize('raw',[
    b'{"zeichnung":{"x":NaN}}',
    b'{"zeichnung":{"x":Infinity}}',
    b'{"zeichnung":{"x":-Infinity}}',
    b'{"zeichnung":{"x":1e400}}',
    b'{"zeichnung":{"x":-1e400}}',
    b'{"zeichnung":{"x":1,"x":2}}',
    b'{"zeichnung":{},"zeichnung":{}}',
    b'[]',b'null',b'1.25',b'{"zeichnung":',b'{"titel":"\xff"}',
])
def test_local_book_parser_rejects_ambiguous_invalid_or_nonfinite_content(raw):
    with pytest.raises(ValueError):parse_book(raw)


@pytest.mark.parametrize('number',[float('nan'),float('inf'),float('-inf')])
def test_local_book_hash_cannot_authorize_nonfinite_content(number):
    with pytest.raises(ValueError):book_hash({'zeichnung':{'x':number}})


def test_integer_book_hash_remains_wire_compatible_but_fractions_remain_forbidden_on_wire():
    integer_book={'einstellungen':{'papierkorb':{'an':True,'tage':7}},'werte':[None,-1,0,2**63-1],'titel':'Größe'}
    assert canonical_book(integer_book)==canonical(integer_book)
    assert strict_json(canonical_book(integer_book))==integer_book
    decimal_book={'zeichnung':{'punkte':[{'x':12.5,'y':-0.125}]}}
    assert same_book(decimal_book,parse_book(canonical_book(decimal_book)))
    with pytest.raises(ValueError,match='unsupported canonical JSON value'):canonical(decimal_book)
    with pytest.raises(ValueError,match='fractions are forbidden'):strict_json(canonical_book(decimal_book))
