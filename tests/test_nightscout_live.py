from unittest.mock import patch

import pandas as pd
import pytest

from health_aggregator.live import nightscout_live


def test_entries_payload_to_frame_skips_entries_without_sgv_or_date():
    payload = [
        {"sgv": 100, "date": 1786000000000, "type": "sgv"},
        {"sgv": None, "date": 1786000060000, "type": "sgv"},
        {"sgv": 105, "date": None, "type": "sgv"},
    ]
    df = nightscout_live._entries_payload_to_frame(payload)
    assert len(df) == 1
    assert df.iloc[0]["mg_dl"] == 100
    assert df.iloc[0]["source"] == "nightscout_live"


def test_entries_payload_to_frame_handles_empty_payload():
    assert nightscout_live._entries_payload_to_frame([]).empty
    assert nightscout_live._entries_payload_to_frame(None).empty


def test_auth_params_and_headers_token_goes_in_query_string():
    params, headers = nightscout_live._auth_params_and_headers("mytoken", None)
    assert params == {"token": "mytoken"}
    assert headers == {}


def test_auth_params_and_headers_api_secret_is_sha1_hashed():
    params, headers = nightscout_live._auth_params_and_headers(None, "supersecret")
    assert params == {}
    assert headers["API-SECRET"] != "supersecret"
    assert len(headers["API-SECRET"]) == 40  # sha1 hex digest length


def test_auth_params_and_headers_requires_one_credential():
    with pytest.raises(ValueError):
        nightscout_live._auth_params_and_headers(None, None)


def test_fetch_entries_sends_since_as_epoch_ms_and_calls_expected_url():
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [{"sgv": 100, "date": 1786000000000, "type": "sgv"}]

        return FakeResponse()

    with patch("health_aggregator.live.nightscout_live.requests.get", side_effect=fake_get):
        result = nightscout_live.fetch_entries(
            "https://example.com/", token="tok", since=pd.Timestamp("2026-08-10 08:00:00"), count=50
        )

    assert captured["url"] == "https://example.com/api/v1/entries.json"
    assert captured["params"]["count"] == 50
    assert captured["params"]["token"] == "tok"
    assert "find[date][$gte]" in captured["params"]
    assert len(result) == 1
