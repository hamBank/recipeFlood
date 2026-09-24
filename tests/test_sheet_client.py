"""RestSheetClient's error reporting and the sheet settings' parsing —
the parts of the real Sheets integration that don't need the network."""

import pytest

from backend.config import Settings
from backend.sheet_client import RestSheetClient


class _Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


def _client():
    return RestSheetClient("sheet-id", "Shopping", "/nonexistent.json")


class TestErrorMessages:
    def test_ok_response_passes(self):
        _client()._check(_Response(200, {}))

    def test_403_carries_googles_reason_and_a_hint(self):
        response = _Response(
            403, {"error": {"message": "The caller does not have permission"}}
        )
        with pytest.raises(RuntimeError) as caught:
            _client()._check(response)
        message = str(caught.value)
        assert "403" in message
        assert "The caller does not have permission" in message
        assert "client_email" in message

    def test_404_points_at_the_sheet_id(self):
        with pytest.raises(RuntimeError, match="GOOGLE_SHEET_ID"):
            _client()._check(_Response(404, {"error": {"message": "Not found"}}))

    def test_non_json_error_body_still_reports_the_status(self):
        with pytest.raises(RuntimeError, match="Google Sheets API 500"):
            _client()._check(_Response(500))


class TestInlineComments:
    def test_inline_comment_is_stripped_from_the_tab(self):
        settings = Settings(google_sheet_tab="Shopping   # optional — the default")
        assert settings.google_sheet_tab == "Shopping"

    def test_inline_comment_is_stripped_from_id_and_key_path(self):
        settings = Settings(
            google_sheet_id="abc123  # from the URL",
            google_service_account_file="/opt/recipeFlood/google-sa.json # key",
        )
        assert settings.google_sheet_id == "abc123"
        assert settings.google_service_account_file == "/opt/recipeFlood/google-sa.json"

    def test_tab_names_with_spaces_are_kept(self):
        assert Settings(google_sheet_tab="Weekly Shop").google_sheet_tab == "Weekly Shop"
