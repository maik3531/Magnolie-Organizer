"""Relative candidates only. No tests here grant or claim a file move."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import grouped_media_path, plan_special_folder_path


@pytest.mark.parametrize('setting',['animation','capture'])
@pytest.mark.parametrize('separate',[False,True])
def test_each_switch_preserves_the_other_folder_and_always_starts_from_the_original_album(setting,separate):
    original='Animationen/Eigene Aufnahmen/clip.gif' # These are actual album names here.
    before_animation=not separate if setting=='animation' else True
    before_capture=not separate if setting=='capture' else True
    before=grouped_media_path(original,animation=before_animation,capture=before_capture)
    candidate=plan_special_folder_path(original,before,was_animation=before_animation,was_capture=before_capture,
        verified_animation=True,verified_capture=True,setting=setting,separate=separate)
    expected=(('Eigene Aufnahmen/' if setting!='capture' or separate else '')+
        ('Animationen/' if setting!='animation' or separate else '')+original)
    assert candidate==expected


@pytest.mark.parametrize('setting',['animation','capture'])
def test_unproven_original_is_kept_in_place_even_when_grouping_is_requested(setting):
    original='Camera/looks-like-an-animation.gif'
    assert plan_special_folder_path(original,original,was_animation=False,was_capture=False,
        verified_animation=False,verified_capture=False,setting=setting,separate=True) is None


@pytest.mark.parametrize('mapped,was_grouped,verified',[
    ('Another album/clip.gif',False,True),
    ('Versionen/copy/clip.gif',False,True),
    ('Animationen/Camera/clip.gif',False,True),
    ('Animationen/Camera/clip.gif',True,False),
])
def test_different_historical_mapping_or_unproven_original_never_becomes_a_target(mapped,was_grouped,verified):
    with pytest.raises(TransferError,match='photo_grouping_original_layout_required'):
        plan_special_folder_path('Camera/clip.gif',mapped,was_animation=was_grouped,was_capture=False,
            verified_animation=verified,verified_capture=False,setting='animation',separate=False)


@pytest.mark.parametrize('original',['../outside.gif','Camera/../outside.gif','Camera\\outside.gif','x/'*15+'clip.gif'])
def test_grouping_cannot_form_a_path_that_native_file_transfer_would_reject(original):
    with pytest.raises(TransferError):grouped_media_path(original,animation=True,capture=False)
