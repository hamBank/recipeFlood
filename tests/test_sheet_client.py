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
        self.headers = {}

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


class _Session:
    """Records every call and answers from a queue of responses."""

    def __init__(self, *responses, row_count=100):
        self.calls = []
        self._responses = list(responses)
        self._props = _Response(
            200,
            {
                "sheets": [
                    {
                        "properties": {
                            "title": "Shopping",
                            "sheetId": 7,
                            "gridProperties": {"rowCount": row_count},
                        }
                    }
                ]
            },
        )

    def _answer(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if method == "get" and kwargs.get("params", {}).get("fields") == "sheets.properties":
            return self._props
        return self._responses.pop(0) if self._responses else _Response(200, {})

    def get(self, url, **kwargs):
        return self._answer("get", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("post", url, kwargs)


def _with(session, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    client = RestSheetClient("sheet-id", "Shopping", "/nonexistent.json", sleep=sleeps.append)
    client._session = session
    return client


def _batch(session):
    posts = [kwargs["json"]["requests"] for method, _url, kwargs in session.calls if method == "post"]
    assert len(posts) == 1, "every change goes in one batchUpdate"
    return posts[0]


class TestWriteRows:
    def test_text_status_and_strikethrough_go_in_one_call(self):
        session = _Session()
        _with(session).write_rows({3: {"A": "milk", "B": "2 L", "I": "rf:9 ticked", "strike": True}})
        requests = _batch(session)
        cells = {r["updateCells"]["range"]["startColumnIndex"]: r["updateCells"] for r in requests}
        assert sorted(cells) == [0, 1, 8]  # A, B and I; never G (6)
        assert cells[0]["rows"][0]["values"][0] == {
            "userEnteredValue": {"stringValue": "milk"},
            "userEnteredFormat": {"textFormat": {"strikethrough": True}},
        }
        assert "userEnteredFormat.textFormat.strikethrough" in cells[1]["fields"]
        assert "strikethrough" not in cells[8]["fields"]
        assert all(c["range"]["sheetId"] == 7 and c["range"]["startRowIndex"] == 2 for c in cells.values())

    def test_clearing_empties_the_cells_and_never_deletes_the_row(self):
        session = _Session()
        _with(session).write_rows({4: {"A": "", "B": "", "I": "", "strike": False}})
        requests = _batch(session)
        assert all(set(r) == {"updateCells"} for r in requests)  # no deleteDimension
        for request in requests:
            cell = request["updateCells"]["rows"][0]["values"][0]
            assert "userEnteredValue" not in cell  # absent + named in fields = emptied
            assert "userEnteredValue" in request["updateCells"]["fields"]

    def test_only_given_columns_are_touched(self):
        session = _Session()
        _with(session).write_rows({2: {"I": "rf:5 synced"}})
        requests = _batch(session)
        assert len(requests) == 1
        assert requests[0]["updateCells"]["range"]["startColumnIndex"] == 8

    def test_g_is_refused_before_anything_is_sent(self):
        session = _Session()
        with pytest.raises(ValueError, match="'G'"):
            _with(session).write_rows({1: {"A": "milk", "G": "=x"}})
        assert session.calls == []

    def test_the_tab_grows_when_a_row_is_past_its_end(self):
        session = _Session(row_count=10)
        _with(session).write_rows({12: {"A": "milk"}})
        requests = _batch(session)
        assert requests[0] == {"appendDimension": {"sheetId": 7, "dimension": "ROWS", "length": 2}}

    def test_a_quota_error_is_retried_after_googles_delay(self):
        busy = _Response(429, {"error": {"message": "Quota exceeded"}})
        busy.headers = {"Retry-After": "3"}
        sleeps = []
        session = _Session(busy)
        _with(session, sleeps).write_rows({1: {"A": "milk"}})
        assert sleeps == [3.0]
        assert len([c for c in session.calls if c[0] == "post"]) == 2

    def test_retries_give_up_with_googles_message(self):
        failures = []
        for _ in range(4):
            failures.append(_Response(503, {"error": {"message": "Backend error"}}))
            failures[-1].headers = {}
        sleeps = []
        with pytest.raises(RuntimeError, match="503: Backend error"):
            _with(_Session(*failures), sleeps).write_rows({1: {"A": "milk"}})
        assert sleeps == [1.0, 2.0, 4.0]
