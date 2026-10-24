"""The Sheets v4 REST API, behind a small interface so `sheet_sync.py` can
be tested with an in-memory fake instead of real network calls.

Deliberately plain `requests`-style REST calls via
`google.auth.transport.requests.AuthorizedSession`, not gspread or
google-api-python-client — the project already depends on `google-auth`
for the login flow, and the surface this feature needs (read a range,
write a handful of cells with their strikethrough) is a few REST calls,
not a reason to add a second Google client library.

Row numbers everywhere in this module are 1-indexed and match the sheet's
own row numbers exactly — row 1 is the first data row, since the tab has
no header (see SPEC.md "Google Sheet sync").

Nothing here deletes, inserts or moves a row. The household keeps spare
rows set up in advance (the location formula in G, anything else they keep
beside an item), so removing an item only empties the cells the app owns
(A, B and I) and leaves the row where it is.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol
from urllib.parse import quote

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

#: Columns this app is ever allowed to read or write. G (the location
#: lookup formula) is deliberately absent from every method's signature —
#: not just unused by convention, but structurally impossible to write
#: through this client.
_TRACKED_COLUMNS = ("a", "b", "i")

#: Zero-based column index of each column the app writes.
_COLUMN_INDEX = {"a": 0, "b": 1, "i": 8}

#: An update that empties the app's cells on a row and drops its
#: strikethrough, leaving G and every other column alone.
CLEARED = {"A": "", "B": "", "I": "", "strike": False}

#: Status codes worth another try: Google's per-minute quota (ticking
#: items off quickly in a shop easily exceeds it) and its own hiccups.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class SheetRow(dict):
    """{"row": int, "a": str, "b": str, "i": str} — a thin alias so
    callers can use attribute-free dict access without importing TypedDict
    machinery for three fields."""


class SheetClient(Protocol):
    def read_rows(self) -> list[dict]:
        """Every row of the tab that has ever had a value in A, B or I,
        oldest (row 1) first, as {"row", "a", "b", "i"}. Trailing fully
        blank rows are omitted; callers filter out A-and-I-blank rows
        themselves (see SPEC.md: "Blank rows... are skipped entirely")."""
        ...

    def write_rows(self, updates: dict[int, dict]) -> None:
        """Apply every change in one call, so a row's text, status and
        strikethrough land together or not at all.

        `updates` is {row: {"A": text, "B": text, "I": text, "strike": bool}};
        each key is optional and only the given ones are touched. An empty
        string empties that cell. Never accepts "G". Grows the tab if a row
        is past its last one."""
        ...


class RestSheetClient:
    """The real implementation, talking to the Sheets v4 REST API."""

    def __init__(
        self,
        spreadsheet_id: str,
        tab: str,
        service_account_file: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 3,
    ):
        self._spreadsheet_id = spreadsheet_id
        self._tab = tab
        self._service_account_file = service_account_file
        self._session = None
        self._sheet_numeric_id: int | None = None
        self._row_count: int = 0
        self._sleep = sleep
        self._retries = retries

    def _authed_session(self):
        if self._session is None:
            # Imported lazily so a deployment with sync disabled never
            # needs the service-account file (or even google.oauth2) to
            # import cleanly.
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2.service_account import Credentials

            creds = Credentials.from_service_account_file(
                self._service_account_file, scopes=SCOPES
            )
            self._session = AuthorizedSession(creds)
        return self._session

    def _check(self, response) -> None:
        """`raise_for_status`, but carrying Google's own explanation.

        A bare "403 Forbidden" can mean the sheet isn't shared with the
        service account or that the Sheets API isn't enabled for its
        project; Google's error body says which, so surface it.
        """
        if response.ok:
            return
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        message = f"Google Sheets API {response.status_code}"
        if detail:
            message += f": {detail}"
        if response.status_code == 403:
            message += (
                " (check the sheet is shared as Editor with the service"
                " account's client_email, and that the Google Sheets API is"
                " enabled for its project)"
            )
        elif response.status_code == 404:
            message += " (check GOOGLE_SHEET_ID)"
        raise RuntimeError(message)

    def _send(self, method: str, url: str, **kwargs):
        """One API call, retried with backoff on a quota or server error
        (honouring Google's Retry-After when it sends one), then checked."""
        for attempt in range(self._retries + 1):
            response = getattr(self._authed_session(), method)(url, **kwargs)
            if response.status_code not in _RETRY_STATUSES or attempt == self._retries:
                break
            try:
                delay = float(response.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                delay = 2.0**attempt
            logger.info("Google Sheets API %s, retrying in %ss", response.status_code, delay)
            self._sleep(min(delay, 30.0))
        self._check(response)
        return response

    def _base(self) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"

    def _load_properties(self) -> None:
        response = self._send("get", self._base(), params={"fields": "sheets.properties"})
        for sheet in response.json().get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self._tab:
                self._sheet_numeric_id = props["sheetId"]
                self._row_count = props.get("gridProperties", {}).get("rowCount", 0)
                return
        raise ValueError(f"No tab named {self._tab!r} in the spreadsheet")

    def read_rows(self) -> list[dict]:
        range_ = f"{self._tab}!A:I"
        response = self._send(
            "get",
            f"{self._base()}/values/{quote(range_)}",
            params={"valueRenderOption": "FORMATTED_VALUE"},
        )
        values = response.json().get("values", [])
        rows = []
        for index, row in enumerate(values, start=1):
            rows.append(
                {
                    "row": index,
                    "a": row[0] if len(row) > 0 else "",
                    "b": row[1] if len(row) > 1 else "",
                    "i": row[8] if len(row) > 8 else "",
                }
            )
        return rows

    def write_rows(self, updates: dict[int, dict]) -> None:
        # Built before any request, so a bad column refuses the whole call.
        cell_requests = []
        for row, cells in sorted(updates.items()):
            cell_requests.extend(_cell_requests(row, cells))
        if not cell_requests:
            return
        last = max(updates)
        if self._sheet_numeric_id is None or last > self._row_count:
            self._load_properties()  # a human may have added rows since
        requests = []
        if last > self._row_count:
            # Writing past the tab's last row is refused by the API, so
            # grow it first. Only ever adds rows at the bottom.
            requests.append(
                {
                    "appendDimension": {
                        "sheetId": self._sheet_numeric_id,
                        "dimension": "ROWS",
                        "length": last - self._row_count,
                    }
                }
            )
        for request in cell_requests:
            request["updateCells"]["range"]["sheetId"] = self._sheet_numeric_id
            requests.append(request)
        self._send("post", f"{self._base()}:batchUpdate", json={"requests": requests})
        self._row_count = max(self._row_count, last)


def _cell_requests(row: int, cells: dict) -> list[dict]:
    """updateCells requests (sheetId still to fill in) for one row: each
    given column's value — plain text, never parsed as a formula, "" empties
    the cell — and, on A and B, the strikethrough if given."""
    strike = cells.get("strike")
    values = {}
    for col, value in cells.items():
        if col == "strike":
            continue
        key = col.lower()
        if key not in _TRACKED_COLUMNS:
            raise ValueError(f"Refusing to write column {col!r} (not A/B/I)")
        values[key] = value
    requests = []
    for key in _TRACKED_COLUMNS:
        has_value = key in values
        styles = strike is not None and key in ("a", "b")
        if not (has_value or styles):
            continue
        cell: dict = {}
        fields = []
        if has_value:
            # Leaving userEnteredValue out of the cell while naming it in
            # `fields` empties the cell. Text runs go too: they belong to
            # the old text, and a run's own format would override the
            # cell's strikethrough.
            if values[key] != "":
                cell["userEnteredValue"] = {"stringValue": values[key]}
            fields += ["userEnteredValue", "textFormatRuns"]
        if styles:
            cell["userEnteredFormat"] = {"textFormat": {"strikethrough": bool(strike)}}
            fields.append("userEnteredFormat.textFormat.strikethrough")
        column = _COLUMN_INDEX[key]
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": column,
                        "endColumnIndex": column + 1,
                    },
                    "rows": [{"values": [cell]}],
                    "fields": ",".join(fields),
                }
            }
        )
    return requests


class FakeSheetClient:
    """In-memory stand-in for tests — no network. Keeps A/B/G/I and a
    strikethrough flag per row so tests can assert both what the app wrote
    and what it (correctly) never touched."""

    def __init__(self):
        self.rows: dict[int, dict] = {}  # row -> {"a", "b", "g", "i", "strike"}

    def _row(self, row: int) -> dict:
        return self.rows.setdefault(
            row, {"a": "", "b": "", "g": f"=LOOKUP(row {row})", "i": "", "strike": False}
        )

    def seed(self, row: int, *, a: str = "", b: str = "", i: str = "", strike: bool = False):
        """Test helper: set up a row as if a human had typed it."""
        entry = self._row(row)
        entry.update(a=a, b=b, i=i, strike=strike)

    def read_rows(self) -> list[dict]:
        last = max(self.rows) if self.rows else 0
        return [
            {
                "row": row,
                "a": self.rows.get(row, {}).get("a", ""),
                "b": self.rows.get(row, {}).get("b", ""),
                "i": self.rows.get(row, {}).get("i", ""),
            }
            for row in range(1, last + 1)
        ]

    def write_rows(self, updates: dict[int, dict]) -> None:
        # Validate everything first: the real call is all-or-nothing.
        for cells in updates.values():
            for col in cells:
                if col != "strike" and col.lower() not in _TRACKED_COLUMNS:
                    raise ValueError(f"Refusing to write column {col!r} (not A/B/I)")
        for row, cells in updates.items():
            entry = self._row(row)
            for col, value in cells.items():
                if col == "strike":
                    entry["strike"] = bool(value)
                else:
                    entry[col.lower()] = value
