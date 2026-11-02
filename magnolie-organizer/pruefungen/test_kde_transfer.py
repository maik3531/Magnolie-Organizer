import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin"))
from magnolie_kde_transfer import BatchError, IncomingFileBatch


def staged(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_batch_only_offers_complete_list_and_never_accepts_unseen_followups(tmp_path):
    connection = object()
    batch = IncomingFileBatch("peer", connection, 2, 5, 100)
    batch.announce(connection, 1, "one.txt", 2, 2, 5)
    with pytest.raises(BatchError):
        batch.proposal()
    assert not batch.stage(connection, 1, staged(tmp_path, "a", b"ab"))
    batch.announce(connection, 2, "two.txt", 3, 2, 5)
    assert batch.stage(connection, 2, staged(tmp_path, "b", b"cde"))
    reviewed = batch.proposal()
    assert reviewed == ({"name": "one.txt", "size": 2}, {"name": "two.txt", "size": 3})
    reviewed[0]["name"] = "tampered"
    assert batch.proposal()[0]["name"] == "one.txt"
    with pytest.raises(BatchError):
        batch.announce(connection, 3, "unseen.txt", 1, 3, 6)
    taken = batch.take()
    assert [entry["name"] for entry in taken] == ["one.txt", "two.txt"]
    with pytest.raises(BatchError):
        batch.take()
    batch.discard()
    assert all(os.path.isfile(entry["staged"]) for entry in taken)


def test_batch_is_bound_to_exact_connection_not_just_same_peer_and_totals(tmp_path):
    connection, other = object(), object()
    batch = IncomingFileBatch("peer", connection, 2, 2, 100)
    for action in (lambda: batch.update(other, 2, 2),
                   lambda: batch.announce(other, 1, "a", 1, 2, 2),
                   lambda: batch.stage(other, 1, staged(tmp_path, "x", b"x"))):
        with pytest.raises(BatchError):
            action()
    assert batch.reserved_bytes == 2


def test_batch_updates_can_grow_only_before_sealing_and_duplicates_do_not_join(tmp_path):
    connection = object()
    batch = IncomingFileBatch("peer", connection, 1, 1, 100)
    batch.announce(connection, 10, "a", 1, 1, 1)
    batch.update(connection, 2, 2)
    for action in (lambda: batch.update(connection, 1, 1),
                   lambda: batch.announce(connection, 10, "a", 1, 2, 2)):
        with pytest.raises(BatchError):
            action()
    assert not batch.stage(connection, 10, staged(tmp_path, "a", b"a"))
    batch.announce(connection, 11, "b", 1, 2, 2)
    assert batch.stage(connection, 11, staged(tmp_path, "b", b"b"))
    with pytest.raises(BatchError):
        batch.update(connection, 3, 3)


@pytest.mark.parametrize("count,total", [(True, 1), (0, 1), (129, 1), (1, True),
                                          (1, -1), (1, IncomingFileBatch.MAX_BYTES + 1)])
def test_batch_bounds(count, total):
    with pytest.raises(BatchError):
        IncomingFileBatch("peer", object(), count, total, 100)


def test_batch_size_mismatch_and_missing_files_never_form_proposal(tmp_path):
    connection = object()
    batch = IncomingFileBatch("peer", connection, 1, 3, 100)
    batch.announce(connection, 1, "a", 2, 1, 3)
    with pytest.raises(BatchError):
        batch.stage(connection, 1, staged(tmp_path, "short", b"a"))
    with pytest.raises(BatchError):
        batch.stage(connection, 1, staged(tmp_path, "actual", b"ab"))
    with pytest.raises(BatchError):
        batch.proposal()
    batch.discard()
    assert not (tmp_path / "actual").exists()


def test_discard_removes_only_owned_staging_and_preserves_unrelated_files(tmp_path):
    connection = object()
    own = staged(tmp_path, "own", b"a")
    unrelated = staged(tmp_path, "unrelated", b"keep")
    batch = IncomingFileBatch("peer", connection, 2, 2, 100)
    batch.announce(connection, 1, "a", 1, 2, 2)
    batch.stage(connection, 1, own)
    batch.discard()
    batch.discard()
    assert not os.path.exists(own)
    assert open(unrelated, "rb").read() == b"keep"
