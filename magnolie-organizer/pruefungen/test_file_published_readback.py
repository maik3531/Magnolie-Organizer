"""Shared Kotlin/Python metadata codec, never a native proof producer."""
from dataclasses import replace
from pathlib import Path
import copy
import json
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import NativeTransferBinding,TransferError
from magnolie_file_published_readback import CONTEXT,destination_token,encode_body,parse_readback


def vector():return json.loads((Path(__file__).resolve().parents[2]/'contracts/file-published-readback-v1-vectors.json').read_text())
def binding(v):return NativeTransferBinding(**v['binding'])
def parse(v):return parse_readback(v['message'],v['offer'],binding(v),'images',now=v['now_ms'])


def test_shared_canonical_vector_matches_all_three_digest_domains_without_granting_receipt_or_write():
    v=vector();b=binding(v);body=v['message']['body'];context={name:body[name] for name in CONTEXT}
    assert destination_token(context)==b.destination_token and encode_body(context,b)==body
    result=parse(v);assert result.body==body and not result.grants_write_authority and not result.is_saved_receipt and not result.allows_chunk_output
    returned=result.body;returned['size']=999;assert result.body['size']==123


@pytest.mark.parametrize('field,value',[('size',True),('size','123'),('size',0),('size',-1),('size',None),
    ('format',True),('format','1'),('sha256','A'*64),('readback_nonce','1'*63),('mime_type','video/mp4')])
def test_typed_context_is_not_a_truth_flag_or_implicit_media_grant(field,value):
    v=vector();context={name:v['message']['body'][name] for name in CONTEXT};context[field]=value
    with pytest.raises(TransferError):encode_body(context,binding(v))


@pytest.mark.parametrize('field,value',[('transfer_id','6'*32),('source_id','7'*32),('file_id','8'*32),('size',124),
    ('sha256','9'*64),('manifest_sha256','a'*64),('offer_id','33333333-3333-4333-8333-333333333333')])
def test_self_consistent_codec_body_still_requires_exact_current_offer_and_file(field,value):
    v=vector();context={name:v['message']['body'][name] for name in CONTEXT};context[field]=value
    b=replace(binding(v),destination_token=destination_token(context));v['binding']['destination_token']=b.destination_token
    v['message']['body']=encode_body(context,b)
    with pytest.raises(TransferError):parse(v)


@pytest.mark.parametrize('change',['kind','extra','binding','expiry','offer_expired','offer_future','digest','wrong_kind'])
def test_wire_lifetime_binding_kind_and_digest_are_independently_checked(change):
    v=vector()
    if change=='kind':v['message']['kind']='file_transfer.saved'
    elif change=='extra':v['message']['body']['allows_write']=True
    elif change=='binding':v['binding']['receiver_identity_sha256']='a'*64
    elif change=='expiry':v['message']['expires_ms']=v['offer']['expires_ms']+1
    elif change=='offer_expired':v['offer']['expires_ms']=v['now_ms'];v['offer']['created_ms']=v['now_ms']-60000
    elif change=='offer_future':v['offer']['created_ms']=v['now_ms']+1;v['offer']['expires_ms']=v['now_ms']+60001
    elif change=='digest':v['message']['body']['readback_sha256']='a'*64
    else:
        with pytest.raises(TransferError):parse_readback(v['message'],v['offer'],binding(v),'video',now=v['now_ms'])
        return
    with pytest.raises(TransferError):parse(v)


def test_fresh_nonce_changes_destination_binding_and_readback_digest_without_creating_authority():
    v=vector();old=copy.deepcopy(v['message']['body']);context={name:old[name] for name in CONTEXT};context['readback_nonce']='2'*64
    b=replace(binding(v),destination_token=destination_token(context));body=encode_body(context,b)
    for name in ('destination_token','binding_sha256','readback_sha256'):assert body[name]!=old[name]
    v['binding']['destination_token']=b.destination_token;v['message']['body']=body
    assert not parse(v).is_saved_receipt
