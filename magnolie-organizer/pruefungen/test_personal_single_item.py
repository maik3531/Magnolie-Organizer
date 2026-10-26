"""One selected entry is the limit in both transfer directions, not the whole scope."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as personal


@pytest.mark.parametrize("kind", ["note", "task"])
def test_selected_send_and_reply_reject_other_members_and_empty_initial_payload(kind):
    request = {"send_item": {"kind": kind, "id": "chosen"}}
    chosen = {"kind": kind, "id": "chosen", "value": {"notebook_id": "chosen-book"}}
    for reply in (False, True):
        personal.validate_selected_records(request, [chosen], complete=True, reply=reply)
        with pytest.raises(ValueError):
            personal.validate_selected_records(request, [chosen, dict(chosen, id="other-member")], complete=True, reply=reply)
    personal.validate_selected_records(request, [], complete=True, reply=True)
    with pytest.raises(ValueError):
        personal.validate_selected_records(request, [], complete=True, reply=False)


def test_only_the_chosen_notes_required_notebook_can_accompany_a_complete_reply():
    request = {"send_item": {"kind": "note", "id": "chosen"}}
    chosen = {"kind": "note", "id": "chosen", "value": {"notebook_id": "chosen-book"}}
    book = {"kind": "notebook", "id": "chosen-book", "value": {"name": "Required"}}
    personal.validate_selected_records(request, [chosen, book], complete=True, reply=True)
    with pytest.raises(ValueError):
        personal.validate_selected_records(request, [chosen, book, dict(book, id="private-book")], complete=True, reply=True)


def test_task_selection_cannot_advertise_any_notebook_even_in_a_partial_batch():
    request = {"send_item": {"kind": "task", "id": "chosen"}}
    with pytest.raises(ValueError):
        personal.validate_selected_records(request, [{"kind": "notebook", "id": "private-book"}])
