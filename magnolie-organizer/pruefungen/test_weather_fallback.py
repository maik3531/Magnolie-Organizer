import ast
from datetime import date
import json
from pathlib import Path
import re

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "bin/magnolie-organizer"


def weather_api():
    names = {"wetter_abrufen", "_wetter_open_meteo", "_wetter_auswerten", "_wetter_text_holen"}
    tree = ast.parse(SOURCE.read_text())
    selected = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    def valid(value):
        try:
            return date.fromisoformat(value).isoformat() == value
        except (TypeError, ValueError):
            return False
    scope = {"json": json, "re": re, "_": lambda value: value, "_ist_iso": valid,
             "_feiertag_sprache": lambda: "DE", "WETTER_DIENST": "https://wttr.in",
             "PROGRAMM_FASSUNG": "2.0.18", "_text_dekodieren": lambda value: value.decode("utf-8")}
    exec(compile(selected, str(SOURCE), "exec"), scope)
    return scope


def forecast():
    return json.dumps({"weather": [{"date": "2026-09-15", "mintempC": "10", "maxtempC": "20",
                                  "hourly": [{"time": "1200", "weatherCode": "113"}]}]})


@pytest.mark.parametrize("failures", [0, 1, 2])
def test_https_then_http_then_alternative(failures):
    calls = []
    def fetch(url):
        calls.append(url)
        if len(calls) <= failures:
            raise OSError("synthetic unavailable provider")
        if "geocoding-api.open-meteo.com" in url:
            return json.dumps({"results": [{"name": "Berlin", "latitude": 52.5, "longitude": 13.4}]})
        if "api.open-meteo.com" in url:
            return json.dumps({"daily": {"time": ["2026-09-15"], "temperature_2m_min": [10],
                                         "temperature_2m_max": [20], "weather_code": [0]}})
        return forecast()
    result = weather_api()["wetter_abrufen"]("10115 Berlin", fetch)
    assert result["ok"] and result["tage"][0]["code"] == 113
    assert calls[0].startswith("https://wttr.in/")
    if failures:
        assert calls[1].startswith("http://wttr.in/")
    assert len(calls) == (4 if failures == 2 else failures + 1)
    if failures == 2:
        assert result["anbieter"] == "Open-Meteo"


def test_no_location_opt_out_makes_no_requests():
    result = weather_api()["wetter_abrufen"]("", lambda url: pytest.fail(url), lambda: {}, False)
    assert result["ohneOrt"] and not result["tage"]


def test_invalid_primary_data_also_falls_back():
    calls = []
    def fetch(url):
        calls.append(url)
        return "not JSON" if len(calls) == 1 else forecast()
    assert weather_api()["wetter_abrufen"]("Berlin", fetch)["ok"]
    assert len(calls) == 2 and calls[-1].startswith("http://wttr.in/")


def test_total_failure_stays_failure():
    with pytest.raises(RuntimeError, match="^The weather service returned unreadable data.$"):
        weather_api()["wetter_abrufen"]("Berlin", lambda url: "not JSON")


def test_ip_estimate_failure_does_not_send_empty_location_to_alternative():
    calls = []
    def fetch(url):
        calls.append(url)
        raise OSError("unavailable")
    with pytest.raises(RuntimeError):
        weather_api()["wetter_abrufen"]("", fetch, lambda: {})
    assert len(calls) == 2 and all("wttr.in/" in url for url in calls)


@pytest.mark.parametrize("bad", [{"weather": {}}, {"weather": [{"date": "2026-09-15", "mintempC": "Infinity", "maxtempC": "20"}]}])
def test_malformed_forecasts_do_not_block_http_fallback(bad):
    replies = iter([json.dumps(bad), forecast()])
    assert weather_api()["wetter_abrufen"]("Berlin", lambda url: next(replies))["ok"]


def test_response_size_limit(monkeypatch):
    import urllib.request
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, count):
            assert count == 1024 * 1024 + 1
            return b"x" * count
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="too much data"):
        weather_api()["_wetter_text_holen"]("https://wttr.in/")
