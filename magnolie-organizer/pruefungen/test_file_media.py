from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_file_sources as sources
from magnolie_file_media import parse_media_page,correlate_media_pages
from magnolie_file_transfer import FileManifest,ManifestFile,TransferError

NOW=1_800_000_000_000
RUN='33333333-3333-4333-8333-333333333333'


def manifest(count=1):
    return FileManifest('1'*32,'2'*32,'sender_fixture_01','receiver_fixture_01',
        tuple(ManifestFile(f'{index+1:032x}',f'image{index}.jpg',1,sha256(b'x').hexdigest()) for index in range(count)),count)


def message(count=1,after=0,media='images'):
    full=manifest(count)
    result=sources.create_command('media_page',expected_version='a'*64,run_id=RUN,after=after,now=NOW)
    end=min(after+8,count)
    result['kind']=sources.MEDIA
    result['body']=dict(format=1,request_id=result['message_id'],operation='media_page',version='a'*64,run_id=RUN,
        page=dict(format=1,manifest_sha256=full.fingerprint,source_epoch='b'*64,media_type=media,insertion_witness=True,
            after=after,next_cursor=end if end<count else None,total_files=count,entries=[dict(file_id=full.files[index].id,
            photo_id=sha256(f'photo-{index}'.encode()).hexdigest(),media_kind='image' if media=='images' else 'video') for index in range(after,end)]))
    return result


def parse(value,after=0,**expected):
    options=dict(expected_request_id=value['body']['request_id'],expected_version='a'*64,expected_run_id=RUN,expected_after=after,now=NOW)
    options.update(expected)
    return parse_media_page(value,**options)


def test_exact_page_command_and_complete_media_projection_are_metadata_not_grants():
    command=sources.create_command('media_page',expected_version='a'*64,run_id=RUN,after=0,now=NOW)
    decoded=sources.parse_command(command,now=NOW)
    assert decoded.run_id==RUN and decoded.after==0
    page=parse(message())
    assert not page.grants_write_authority and not page.is_saved_receipt
    assert correlate_media_pages((page,),manifest())==page.entries


@pytest.mark.parametrize('key,value',[('after',True),('after','0'),('after',-1),('after',129),
    ('run_id','foreign'),('expected_version','bad'),('read_granted',True),('path','/personal'),('media_kind','animation')])
def test_media_request_cannot_supply_paths_authority_or_invalid_native_cursor(key,value):
    command=sources.create_command('media_page',expected_version='a'*64,run_id=RUN,after=0,now=NOW)
    command['body'][key]=value
    with pytest.raises(TransferError):sources.parse_command(command,now=NOW)


def test_request_factory_rejects_irrelevant_media_options_and_missing_cursor():
    for options in [dict(enabled=True),dict(kinds=('camera',)),dict(catalog_id=RUN),dict(album_id=RUN),dict(desktop_choice=True)]:
        with pytest.raises(TransferError):sources.create_command('media_page',expected_version='a'*64,run_id=RUN,after=0,now=NOW,**options)
    with pytest.raises(TransferError):sources.create_command('media_page',expected_version='a'*64,run_id=RUN,now=NOW)


@pytest.mark.parametrize('key,value',[('format',True),('after',True),('after',1),('next_cursor',True),
    ('next_cursor',1),('total_files',True),('total_files',0),('total_files',129),('media_type','photos'),
    ('manifest_sha256','wrong'),('source_epoch','A'*64),('insertion_witness',1),('entries',[]),
    ('read_granted',True),('path','/private')])
def test_invalid_media_page_cannot_become_a_completed_inventory(key,value):
    value_message=message();value_message['body']['page'][key]=value
    with pytest.raises(TransferError):parse(value_message)


@pytest.mark.parametrize('key,value',[('file_id','path'),('photo_id','native-row-id'),('media_kind','video'),
    ('media_kind','own_camera'),('native_member','123:456'),('relative_path','Camera/photo.jpg'),('write_allowed',True)])
def test_member_fields_do_not_leak_native_ids_paths_or_derive_video_or_camera_authority(key,value):
    value_message=message();value_message['body']['page']['entries'][0][key]=value
    with pytest.raises(TransferError):parse(value_message)


@pytest.mark.parametrize('key,value',[('request_id','44444444-4444-4444-8444-444444444444'),
    ('version','c'*64),('run_id','44444444-4444-4444-8444-444444444444'),('operation','discover'),('read_granted',True)])
def test_media_result_requires_original_policy_request_operation_and_native_run(key,value):
    value_message=message();expected=value_message['body']['request_id'];value_message['body'][key]=value
    with pytest.raises(TransferError):parse(value_message,expected_request_id=expected)


def test_media_page_limits_deadlines_and_expected_context_are_enforced():
    value=message()
    for expected in [dict(expected_manifest_sha256='c'*64),dict(expected_source_epoch='c'*64),dict(now=NOW+60_000),dict(expected_after=True)]:
        with pytest.raises(TransferError):parse(value,**expected)
    oversized=deepcopy(value);oversized['body']['padding']='x'*8192
    with pytest.raises(TransferError):parse(oversized)


def test_full_paging_checks_every_original_manifest_member_and_never_proves_deletion():
    full=manifest(9)
    first=parse(message(9));last=parse(message(9,8),8,expected_manifest_sha256=full.fingerprint,expected_source_epoch='b'*64)
    assert first.next_cursor==8 and last.next_cursor is None
    assert len(correlate_media_pages((first,last),full))==9
    for pages in [(first,),(last,),(last,first),(first,first,last)]:
        with pytest.raises(TransferError):correlate_media_pages(pages,full)
    for changed in [replace(last,source_epoch='c'*64),replace(last,version='c'*64),replace(last,media_type='video'),
        replace(last,insertion_witness=False),replace(last,total_files=8)]:
        with pytest.raises(TransferError):correlate_media_pages((first,changed),full)
    reused=replace(last,entries=(replace(last.entries[0],photo_id=first.entries[0].photo_id),))
    with pytest.raises(TransferError):correlate_media_pages((first,reused),full)
    changed_manifest=FileManifest(full.transfer_id,full.source_id,full.sender_id,full.receiver_id,
        tuple(replace(file,path='changed/'+file.path) for file in full.files),full.total_bytes)
    with pytest.raises(TransferError):correlate_media_pages((first,last),changed_manifest)


@pytest.mark.parametrize('field',['file_id','photo_id'])
def test_duplicate_members_within_page_are_rejected(field):
    value=message(2);entries=value['body']['page']['entries'];entries[1][field]=entries[0][field]
    with pytest.raises(TransferError):parse(value)


def test_video_and_animation_domain_labels_are_not_interchangeable():
    video=message(media='video')
    assert parse(video).entries[0].media_kind=='video'
    video['body']['page']['entries'][0]['media_kind']='animation'
    with pytest.raises(TransferError):parse(video)
    animation=message();animation['body']['page']['entries'][0]['media_kind']='animation'
    assert parse(animation).entries[0].media_kind=='animation'
    unknown=message();unknown['body']['page']['entries'][0]['media_kind']='unknown_image'
    assert parse(unknown).entries[0].media_kind=='unknown_image'


def test_empty_end_page_cannot_replace_the_actual_complete_manifest_pages():
    end=parse(message(1,1),1)
    assert end.entries==() and end.next_cursor is None
    with pytest.raises(TransferError):correlate_media_pages((end,),manifest())


def test_shared_media_request_golden_keeps_exact_canonical_bytes():
    vector=json.loads((Path(__file__).resolve().parents[2]/'contracts/file-transfer-media-v1-vectors.json').read_text())
    request=sources.create_command('media_page',expected_version='a'*64,run_id=RUN,after=0,now=vector['now_ms'],
        message_id='11111111-1111-4111-8111-111111111111')
    assert request==vector['request']
    data=sources.canonical(request)
    assert len(data)==vector['canonical_bytes'] and sha256(data).hexdigest()==vector['canonical_sha256']
