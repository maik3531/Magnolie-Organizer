"""Synthetic v7 consent and wire contract cases; no network or user profile."""
import copy
from pathlib import Path
from uuid import uuid4
import pytest
from modul_laden import quellmodul_laden

m = quellmodul_laden('time_sync_test', Path(__file__).resolve().parents[1] / 'bin/magnolie_time_sync.py')


def settings(enabled=True, revision=1):
    return dict(format=7, scope='time_tracking', enabled=enabled, revision=revision, epoch=str(uuid4()))


def request(local, remote):
    return dict(format=7, trigger='manual', sender_epoch=remote['epoch'], receiver_epoch=local['epoch'],
                sender_revision=remote['revision'], receiver_revision=local['revision'])


def record():
    return dict(id=str(uuid4()), startMinute=1000, endMinute=1060, pauseMinute=None, pauseMinutes=15,
                zone='Europe/Berlin', type='Synthetic', note='', modifiedMs=1000, deleted=False,
                clock={str(uuid4()): 1})


def test_fresh_own_peer_controls_and_both_current_optins():
    local, remote = settings(), settings()
    body = request(local, remote)
    m.validate(m.REQUEST, body, True)
    assert m.allowed(body, local, remote, True, True, True, [7], [7])
    for local_own, remote_own, fresh in [(False, True, True), (True, False, True), (True, True, False), ('true', True, True)]:
        assert not m.allowed(body, local, remote, local_own, remote_own, fresh, [7], [7])
    assert not m.allowed(body, local, remote, True, True, True, [7], [6])
    assert not m.allowed(body, local, remote, True, True, True, [7], [7.0])
    assert not m.allowed(body, settings(False, 2), remote, True, True, True, [7], [7])
    assert not m.allowed(body, settings(True, 3), remote, True, True, True, [7], [7])
    assert not m.allowed(dict(body, sender_revision=True), local, remote, True, True, True, [7], [7])


def test_consent_revision_and_epoch_cannot_be_replayed():
    old, new = settings(), settings(revision=2)
    assert m.accept_settings(old, old) == old
    assert m.accept_settings(old, new) == new
    with pytest.raises(ValueError): m.accept_settings(new, old)
    with pytest.raises(ValueError): m.accept_settings(old, dict(new, epoch=old['epoch']))


@pytest.mark.parametrize('field,value', [('startMinute', '1000'), ('startMinute', True), ('deleted', True),
    ('pauseMinutes', 61), ('pauseMinute', 1005), ('endMinute', 999), ('clock', {})])
def test_invalid_records_and_remote_deletions_are_rejected(field, value):
    value_record = record()
    value_record[field] = value
    with pytest.raises((ValueError, TypeError)):
        m.validate(m.BATCH, dict(request(settings(), settings()), entries=[value_record]), False)


def test_only_organizer_can_transmit_content_free_deletion_markers():
    tombstone = dict(record(), startMinute=0, endMinute=0, pauseMinute=None, pauseMinutes=0,
                     zone='UTC', type='', note='', deleted=True, pausePlan=None)
    body = dict(request(settings(), settings()), entries=[tombstone])
    assert m.validate(m.BATCH, body, True) == body
    with pytest.raises(ValueError): m.validate(m.BATCH, body, False)
    with pytest.raises(ValueError): m.validate_record(dict(tombstone, note='Private content'), allow_deletion=True)


def test_valid_batch_calendar_direction_and_duplicate_id():
    value = record()
    body = dict(request(settings(), settings()), entries=[value])
    assert m.validate(m.BATCH, body, True) == body
    calendar = dict(enabled=False, country='DE', regions=[], holidays=[])
    m.validate(m.BATCH, dict(body, calendar=calendar), True)
    with pytest.raises(ValueError): m.validate(m.BATCH, dict(body, calendar=calendar), False)
    with pytest.raises(ValueError): m.validate(m.BATCH, dict(body, entries=[value, copy.deepcopy(value)]), True)


def test_unicode_lengths_are_utf16_compatible_and_messages_are_bounded():
    value = record()
    value['note'] = '😀' * 10000
    m.validate_record(value)
    value['note'] += '😀'
    with pytest.raises(ValueError): m.validate_record(value)
    values = [dict(record(), note='x' * 20000) for _ in range(12)]
    with pytest.raises(ValueError, match='too_large'):
        m.validate(m.BATCH, dict(request(settings(), settings()), entries=values), True)


def test_open_pause_plan_is_strict_and_excludes_local_alarm_configuration():
    value = dict(record(), endMinute=None, pausePlan=dict(
        fixed=[dict(start=720, end=750)], manual=[dict(start=1000, end=1015)],
        replaced=[], fixedEnds={}, baseMinutes=0))
    assert m.validate_record(value) == value
    m.validate_record(dict(record(), pausePlan=None))
    for changed in [dict(value['pausePlan'], endAlarm={}),
                    dict(value['pausePlan'], fixed=[dict(start='720', end=750)]),
                    dict(value['pausePlan'], fixed=[dict(start=720, end=720)]),
                    dict(value['pausePlan'], replaced=[1000, 1000]),
                    dict(value['pausePlan'], replaced=[1001, 1000]),
                    dict(value['pausePlan'], fixedEnds={'01000': 1005}),
                    dict(value['pausePlan'], manual=[dict(start=1000, end=1030), dict(start=1020, end=1040)])]:
        with pytest.raises(ValueError):
            m.validate_record(dict(value, pausePlan=changed))
    with pytest.raises(ValueError, match='open_record'):
        m.validate_record(dict(value, endMinute=1060))
