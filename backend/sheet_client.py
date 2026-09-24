"""The Sheets v4 REST API, behind a small interface so `sheet_sync.py` can
be tested with an in-memory fake instead of real network calls.

Deliberately plain `requests`-style REST calls via
`google.auth.transport.requests.AuthorizedSession`, not gspread or
google-api-python-client — the project already depends on `google-auth`
for the login flow, and the surface this feature needs (read a range,
write a handful of cells, delete some rows, toggle strikethrough) is a
few REST calls, not a reason to add a second Google client library.

Row numbers everywhere in this module are 1-indexed and match the sheet's
own row numbers exactly — row 1 is the first data row, since the tab has
no header (see SPEC.md "Google Sheet sync").
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

#: Columns this app is ever allowed to read or write. G (the location
#: lookup formula) is deliberately absent from every method's signature —
#: not just unused by convention, but structurally impossible to write
#: through this client.
_TRACKED_COLUMNS = ("a", "b", "i")


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

    def write_cells(self, updates: dict[int, dict[str, str]]) -> None:
        """`updates` is {row: {"A": text, "B": text, "I": text}} — only the
        given columns of each row are touched. Never accepts "G"."""
        ...

    def delete_rows(self, rows: list[int]) -> None:
        """Delete these 1-indexed rows outright. Callers are responsible
        for having matched every row's column I to the id being removed
        first (see sheet_sync.py's HARD SAFETY RULE) — this method deletes
        whatever row numbers it's given, no further checking."""
        ...

    def set_strikethrough(self, rows: list[int], strike: bool) -> None:
        """Toggle strikethrough on columns A:B of these rows."""
        ...


class RestSheetClient:
    """The real implementation, talking to the Sheets v4 REST API."""

    def __init__(self, spreadsheet_id: str, tab: str, service_account_file: str):
        self._spreadsheet_id = spreadsheet_id
        self._tab = tab
        self._service_account_file = service_account_file
        self._session = None
        self._sheet_numeric_id: int | None = None

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

    def _base(self) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"

    def _numeric_sheet_id(self) -> int:
        if self._sheet_numeric_id is None:
            response = self._authed_session().get(
                f"{self._base()}", params={"fields": "sheets.properties"}
            )
            self._check(response)
            for sheet in response.json().get("sheets", []):
                props = sheet.get("properties", {})
                if props.get("title") == self._tab:
                    self._sheet_numeric_id = props["sheetId"]
                    break
            else:
                raise ValueError(f"No tab named {self._tab!r} in the spreadsheet")
        return self._sheet_numeric_id

    def read_rows(self) -> list[dict]:
        range_ = f"{self._tab}!A:I"
        response = self._authed_session().get(
            f"{self._base()}/values/{quote(range_)}",
            params={"valueRenderOption": "FORMATTED_VALUE"},
        )
        self._check(response)
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

    def write_cells(self, updates: dict[int, dict[str, str]]) -> None:
        data = []
        for row, cells in updates.items():
            for col, value in cells.items():
                if col.lower() not in _TRACKED_COLUMNS:
                    raise ValueError(f"Refusing to write column {col!r} (not A/B/I)")
                data.append(
                    {"range": f"{self._tab}!{col}{row}", "values": [[value]]}
                )
        if not data:
            return
        response = self._authed_session().post(
            f"{self._base()}/values:batchUpdate",
            json={"valueInputOption": "RAW", "data": data},
        )
        self._check(response)

    def delete_rows(self, rows: list[int]) -> None:
        if not rows:
            return
        sheet_id = self._numeric_sheet_id()
        # Bottom-up: each deleteDimension shifts every row below it up by
        # one, so applying them top-down would delete the wrong rows for
        # every request after the first.
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row - 1,
                        "endIndex": row,
                    }
                }
            }
            for row in sorted(set(rows), reverse=True)
        ]
        response = self._authed_session().post(
            f"{self._base()}:batchUpdate", json={"requests": requests}
        )
        self._check(response)

    def set_strikethrough(self, rows: list[int], strike: bool) -> None:
        if not rows:
            return
        sheet_id = self._numeric_sheet_id()
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 0,
                        "endColumnIndex": 2,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"strikethrough": strike}
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.strikethrough",
                }
            }
            for row in rows
        ]
        response = self._authed_session().post(
            f"{self._base()}:batchUpdate", json={"requests": requests}
        )
        self._check(response)


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

    def write_cells(self, updates: dict[int, dict[str, str]]) -> None:
        for row, cells in updates.items():
            entry = self._row(row)
            for col, value in cells.items():
                key = col.lower()
                if key not in _TRACKED_COLUMNS:
                    raise ValueError(f"Refusing to write column {col!r} (not A/B/I)")
                entry[key] = value

    def delete_rows(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            last = max(self.rows) if self.rows else 0
            for r in range(row, last):
                if (r + 1) in self.rows:
                    self.rows[r] = self.rows.pop(r + 1)
                else:
                    self.rows.pop(r, None)
            self.rows.pop(last, None)

    def set_strikethrough(self, rows: list[int], strike: bool) -> None:
        for row in rows:
            self._row(row)["strike"] = strike
