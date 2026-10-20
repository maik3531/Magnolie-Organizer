import copy
import json
from pathlib import Path
import pytest
from modul_laden import quellmodul_laden

BIN = Path(__file__).resolve().parents[1] / "bin"
quellmodul_laden("magnolie_time_sync", BIN / "magnolie_time_sync.py")
control = quellmodul_laden("time_control_test", BIN / "magnolie_time_control.py")

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "contracts/time-control-v13.json").read_text())


@pytest.mark.parametrize("body", VECTORS["requests"])
def test_shared_request_vectors(body):
    assert control.validate_request(copy.deepcopy(body)) == body


@pytest.mark.parametrize("body", VECTORS["reports"])
def test_shared_report_vectors(body):
    assert control.validate_report(copy.deepcopy(body)) == body


@pytest.mark.parametrize("key,value", [("format", True), ("action", "shell"), ("expected_revision", "client-revision"), ("entry_id", "old-entry")])
def test_invalid_timer_commands_are_not_synchronization_records(key, value):
    body = copy.deepcopy(VECTORS["requests"][1]); body[key] = value
    with pytest.raises(ValueError): control.validate_request(body)


@pytest.mark.parametrize("key,value", [("persisted", True), ("operation_applied", True), ("runtime_request", "requested"), ("paused", True)])
def test_read_cannot_claim_mutation_or_a_nonexistent_running_timer(key, value):
    body = copy.deepcopy(VECTORS["reports"][0]); body[key] = value
    with pytest.raises(ValueError): control.validate_report(body)


@pytest.mark.parametrize("key,value", [("revision", "a" * 64), ("enabled", True), ("persisted", True), ("error", "none")])
def test_denied_report_does_not_publish_data_or_success(key, value):
    body = copy.deepcopy(VECTORS["reports"][2]); body[key] = value
    with pytest.raises(ValueError): control.validate_report(body)
