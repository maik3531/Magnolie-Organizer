"""Mandatory fixed oracle replay, with no dateutil or sibling-tree dependency."""

import hashlib
import itertools
import json
from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "bin"))
from magnolie_recurrence import Rule

MATRIX = json.loads((Path(__file__).parent / "fixtures/recurrence-rfc-oracle.json").read_text(encoding="utf-8"))
CASES = list(itertools.product(MATRIX["anchors"], MATRIX["rules"], MATRIX["endings"]))


@pytest.mark.parametrize("index,text", enumerate(MATRIX["rules"]), ids=MATRIX["rules"])
def test_frozen_448_case_oracle(index, text):
    assert MATRIX["golden"]["cases"] == len(CASES) == 448
    assert len(MATRIX["golden"]["ruleSha256"]) == len(MATRIX["rules"])
    lower, upper = map(datetime.fromisoformat, (MATRIX["lower"], MATRIX["upper"]))
    group = []
    for anchor, ending in itertools.product(MATRIX["anchors"], MATRIX["endings"]):
        values = Rule(text + ending, datetime.fromisoformat(anchor)).between(lower, upper)
        group.append([anchor, text + ending, MATRIX["lower"], MATRIX["upper"], [value.isoformat() for value in values]])
    actual = hashlib.sha256(json.dumps(group, separators=(",", ":")).encode("ascii")).hexdigest()
    assert actual == MATRIX["golden"]["ruleSha256"][index], text
