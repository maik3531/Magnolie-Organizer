"""Strict typed wire metadata; labels/receipts never grant native READ authority."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import json
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import magnolie_file_sources as sources
from magnolie_file_media import parse_media_page
from magnolie_file_transfer import TransferError

NOW=1_800_000_000_000
REQUEST='11111111-1111-4111-8111-111111111111'
CATALOG='22222222-2222-4222-8222-222222222222'
ALBUM='33333333-3333-4333-8333-333333333333'
RUN='44444444-4444-4444-8444-444444444444'
ATTEMPT='55555555-5555-4555-8555-555555555555'
VERSION='a'*64


def options(operation):
    result=dict(expected_version=VERSION)
    if operation in ('run','batch_run','resume_run'):
        result.update(catalog_id=CATALOG,album_id=ALBUM,desktop_choice=True)
        if operation=='resume_run':result.update(original_job_id='b'*32,original_job_version='c'*64)
    elif operation=='catalog_page':result.update(catalog_id=CATALOG,after=0)
    elif operation in ('media_page','resume_media_page'):result.update(run_id=RUN,after=0)
    elif operation=='select_run':result.update(run_id=RUN,manifest_sha256='b'*64,file_ids=['c'*32])
    elif operation=='resume_lookup':result.update(source_id='c'*32,transfer_id='d'*32,manifest_sha256='e'*64)
    elif operation=='abandon_resume':result.update(run_id=RUN,original_job_id='b'*32,original_job_version='c'*64,attempt_id=ATTEMPT,attempt_sha256='f'*64)
    elif operation not in ('discover','request_read'):result['run_id']=RUN
    return result


def response(kind,operation,**fields):
    return dict(type='message',v=1,message_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind=kind,
        created_ms=NOW,expires_ms=NOW+60_000,
        body=dict(format=1,request_id=REQUEST,operation=operation,version=VERSION,media_type='video',**fields))


@pytest.mark.parametrize('operation',sorted(sources.SCOPED_OPERATIONS))
def test_all_scoped_commands_keep_video_explicit_and_default_images_byte_shapes_unchanged(operation):
    image=sources.create_command(operation,now=NOW,message_id=REQUEST,**options(operation))
    video=sources.create_command(operation,now=NOW,message_id=REQUEST,media_type='video',**options(operation))
    original=deepcopy(video)
    parsed=sources.parse_command(video,now=NOW)
    assert parsed.media_type=='video' and parsed.operation==operation
    assert replace(parsed,media_type='images')==sources.parse_command(image,now=NOW)
    assert {key:value for key,value in video['body'].items() if key!='media_type'}==image['body']
    assert video==original and 'media_type' not in image['body']
    explicit=sources.create_command(operation,now=NOW,message_id=REQUEST,media_type='images',**options(operation))
    assert sources.parse_command(explicit,now=NOW)==sources.parse_command(image,now=NOW)


@pytest.mark.parametrize('scope',[True,False,0,'VIDEO','videos',None,[],{}])
def test_invalid_media_scope_cannot_be_coerced_or_defaulted_to_images(scope):
    message=sources.create_command('discover',now=NOW,expected_version=VERSION)
    message['body']['media_type']=scope
    with pytest.raises(TransferError):sources.parse_command(message,now=NOW)


@pytest.mark.parametrize('operation',['status','configure','configure_videos'])
def test_global_metadata_operations_reject_even_explicit_image_scope_extensions(operation):
    fields={} if operation=='status' else dict(expected_version=VERSION,enabled=True)
    if operation=='configure':fields['kinds']=('camera',)
    for scope in ('images','video'):
        with pytest.raises(TransferError):sources.create_command(operation,now=NOW,media_type=scope,**fields)


def test_video_configuration_is_separate_metadata_and_has_no_image_kind_or_read_grant_alias():
    message=sources.create_command('configure_videos',now=NOW,message_id=REQUEST,expected_version=VERSION,enabled=True)
    assert set(message['body'])=={'format','operation','expected_version','enabled'}
    assert sources.parse_command(message,now=NOW)==sources.SourceCommand(REQUEST,'configure_videos',VERSION,True)
    for key in ('kinds','read_granted','destination','owner'):
        altered=deepcopy(message);altered['body'][key]=True
        with pytest.raises(TransferError):sources.parse_command(altered,now=NOW)


def status_message(operation='status',videos=None):
    result=response(sources.RESULT,operation,revision=3,enabled=True,associated=True,repair_pending=False,kinds=['camera'])
    result['body'].pop('media_type')
    if videos is not None:result['body']['videos']=videos
    return result


def test_video_status_extensions_require_explicit_negotiated_parser_and_legacy_absence_stays_absence():
    message=status_message(videos=dict(enabled=True,revision=1))
    with pytest.raises(TransferError):sources.parse_result(message,expected_request_id=REQUEST,expected_operation='status',now=NOW)
    parsed=sources.parse_result(message,expected_request_id=REQUEST,expected_operation='status',expect_videos=True,now=NOW)
    assert parsed.videos==sources.SourceVideoStatus(True,1)
    legacy=status_message()
    assert sources.parse_result(legacy,expected_request_id=REQUEST,expected_operation='status',expect_videos=True,now=NOW).videos is None
    configured=status_message('configure_videos',dict(enabled=False,revision=2))
    assert sources.parse_result(configured,expected_request_id=REQUEST,expected_operation='configure_videos',expect_videos=True,now=NOW).videos.enabled is False
    with pytest.raises(TransferError):sources.parse_result(configured,expected_request_id=REQUEST,expected_operation='configure_videos',now=NOW)


@pytest.mark.parametrize('value',[True,[],{},dict(enabled=1,revision=1),dict(enabled=True,revision=True),
    dict(enabled=True,revision='1'),dict(enabled=True,revision=0),dict(enabled=False,revision=-1),
    dict(enabled=True,revision=sources.MAX_REVISION+1),dict(enabled=True,revision=1,read_granted=True)])
def test_video_status_rejects_counter_and_boolean_aliases_unknown_fields_and_fake_read_claims(value):
    message=status_message();message['body']['videos']=value
    with pytest.raises(TransferError):
        sources.parse_result(message,expected_request_id=REQUEST,expected_operation='status',expect_videos=True,now=NOW)


def test_catalog_video_scope_and_full_visibility_cannot_be_reassigned_to_image_catalog():
    message=response(sources.CATALOG,'discover',page=dict(format=1,catalog_id=CATALOG,after=0,next_cursor=None,
        coverage='full_videos',proves_deletion=False,
        albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)]))
    arguments=dict(expected_request_id=REQUEST,expected_operation='discover',expected_version=VERSION,now=NOW)
    page=sources.parse_catalog(message,expected_media_type='video',**arguments)
    assert page.media_type=='video' and page.coverage=='full_videos' and page.albums[0].album_id==ALBUM
    with pytest.raises(TransferError):sources.parse_catalog(message,**arguments)
    missing=deepcopy(message);missing['body'].pop('media_type')
    with pytest.raises(TransferError):sources.parse_catalog(missing,expected_media_type='video',**arguments)
    wrong=deepcopy(message);wrong['body']['page']['coverage']='full_images'
    with pytest.raises(TransferError):sources.parse_catalog(wrong,expected_media_type='video',**arguments)


def test_permission_requested_is_typed_attempt_metadata_not_an_os_grant():
    message=response(sources.PERMISSION_RESULT,'request_read',state='requested')
    arguments=dict(expected_request_id=REQUEST,expected_version=VERSION,now=NOW)
    assert sources.parse_permission_result(message,expected_media_type='video',**arguments).media_type=='video'
    with pytest.raises(TransferError):sources.parse_permission_result(message,**arguments)
    message['body']['read_granted']=True
    with pytest.raises(TransferError):sources.parse_permission_result(message,expected_media_type='video',**arguments)


RUN_OPERATIONS=('run','batch_run','next_batch','select_run','run_status','cancel_run','offer_run','end_run','end_album',
    'resume_run','resume_status','cancel_resume','offer_resume','end_resume')


@pytest.mark.parametrize('operation',RUN_OPERATIONS)
def test_run_offer_cancel_and_end_replies_require_exact_requested_video_scope(operation):
    ending=operation in ('end_run','end_album','end_resume')
    canceled=ending or operation in ('cancel_run','cancel_resume')
    fields=dict(run_id=RUN,state='canceled_held' if canceled else 'snapshot_ready',source_io_ended=True)
    if ending:fields['run_ended']=True
    if operation in ('offer_run','offer_resume'):fields.update(offer_id=CATALOG,manifest_sha256='b'*64)
    if operation in ('batch_run','next_batch'):fields['batch_end']=True
    message=response(sources.RUN_RESULT,operation,**fields)
    arguments=dict(expected_request_id=REQUEST,expected_operation=operation,expected_version=VERSION,now=NOW,
        expected_run_id=None if operation in ('run','batch_run','next_batch','select_run','resume_run') else RUN)
    parsed=sources.parse_run_result(message,expected_media_type='video',**arguments)
    assert parsed.media_type=='video' and parsed.run_id==RUN and parsed.run_ended==ending
    with pytest.raises(TransferError):sources.parse_run_result(message,**arguments)
    stripped=deepcopy(message);stripped['body'].pop('media_type')
    with pytest.raises(TransferError):sources.parse_run_result(stripped,expected_media_type='video',**arguments)


def test_resume_history_stays_historical_and_must_echo_the_actual_video_lookup_scope():
    message=response(sources.RESUME,'resume_lookup',history=dict(job_id='b'*32,job_version='c'*64,phase='sealed',
        source_id='c'*32,transfer_id='d'*32,manifest_sha256='e'*64,remote_saved_history=False,attempt_phase='accepted',
        attempt_id=ATTEMPT,attempt_sha256='f'*64))
    arguments=dict(expected_request_id=REQUEST,expected_version=VERSION,expected_source_id='c'*32,
        expected_transfer_id='d'*32,expected_manifest_sha256='e'*64,now=NOW)
    parsed=sources.parse_resume_history(message,expected_media_type='video',**arguments)
    assert parsed.media_type=='video' and parsed.remote_saved_history is False
    with pytest.raises(TransferError):sources.parse_resume_history(message,**arguments)


def test_resume_abandonment_echo_is_tied_to_exact_video_command_original_and_attempt():
    command=sources.parse_command(sources.create_command('abandon_resume',now=NOW,message_id=REQUEST,media_type='video',**options('abandon_resume')),now=NOW)
    message=response(sources.ABANDONED,'abandon_resume',run_id=RUN,job_id='b'*32,job_version='c'*64,
        attempt_id=ATTEMPT,attempt_sha256='f'*64,receipt_sha256='e'*64)
    parsed=sources.parse_resume_abandonment(message,command,now=NOW)
    assert parsed.media_type=='video' and parsed.job_id==command.original_job_id
    with pytest.raises(TransferError):sources.parse_resume_abandonment(message,replace(command,media_type='images'),now=NOW)
    message['body']['attempt_sha256']='0'*64
    with pytest.raises(TransferError):sources.parse_resume_abandonment(message,command,now=NOW)


def test_typed_media_page_requires_both_outer_and_frozen_inner_video_scope():
    message=response(sources.MEDIA,'media_page',run_id=RUN,page=dict(format=1,manifest_sha256='b'*64,source_epoch='c'*64,
        media_type='video',insertion_witness=True,after=0,next_cursor=None,total_files=1,
        entries=[dict(file_id='d'*32,photo_id='e'*64,media_kind='video')]))
    arguments=dict(expected_request_id=REQUEST,expected_version=VERSION,expected_run_id=RUN,now=NOW)
    page=parse_media_page(message,expected_media_type='video',**arguments)
    assert page.media_type=='video' and page.grants_write_authority is False and page.is_saved_receipt is False
    for scope in ('images',None):
        with pytest.raises(TransferError):parse_media_page(message,expected_media_type=scope,**arguments)
    wrong=deepcopy(message);wrong['body']['page']['media_type']='images';wrong['body']['page']['entries'][0]['media_kind']='image'
    with pytest.raises(TransferError):parse_media_page(wrong,expected_media_type='video',**arguments)
    legacy=deepcopy(message);legacy['body'].pop('media_type')
    assert parse_media_page(legacy,**arguments).grants_write_authority is False # Legacy inspection is not a typed receiver.
    with pytest.raises(TransferError):parse_media_page(legacy,expected_media_type='images',**arguments)
    with pytest.raises(TransferError):parse_media_page(legacy,expected_media_type='video',**arguments)


@pytest.mark.parametrize('operation',[[],{},True,1,None])
def test_non_string_operation_cannot_escape_strict_codec_via_media_scope(operation):
    message=sources.create_command('discover',now=NOW,media_type='video',expected_version=VERSION)
    message['body']['operation']=operation
    with pytest.raises(TransferError):sources.parse_command(message,now=NOW)


def test_shared_native_video_command_goldens_keep_exact_canonical_bytes_and_scope():
    from magnolie_telefon import canonical
    vector=json.loads((Path(__file__).parents[2]/'contracts/file-transfer-video-sources-v1-vectors.json').read_text())
    assert len(vector['commands'])==len(vector['canonical_sha256'])==5
    for message,digest in zip(vector['commands'],vector['canonical_sha256']):
        body=message['body'];fields={key:value for key,value in body.items() if key not in ('format','operation')}
        generated=sources.create_command(body['operation'],now=vector['now_ms'],message_id=message['message_id'],**fields)
        assert generated==message and sha256(canonical(generated)).hexdigest()==digest
        parsed=sources.parse_command(message,now=vector['now_ms'])
        assert parsed.media_type==('images' if parsed.operation=='configure_videos' else 'video')
