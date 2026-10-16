"""Single-use codes for signing the desktop app in.

The desktop app can't use Google Identity Services itself (its webview
origin can't be registered with Google), so it opens the website in the
user's browser. Once they're signed in there, the site calls `issue` and
sends the code to the app over a loopback URL; the app then calls
`redeem` (via `POST /auth/desktop-exchange`) to trade it for a normal JWT.
The JWT itself never travels in a URL — only this short-lived code does.
See SPEC.md "Desktop app sign-in".

Codes live in process memory behind a lock, the same single-uvicorn-
process assumption `sheet_sync.py` makes: a restart just drops pending
codes, and the user retries the sign-in.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time

#: Long enough to switch windows and click Continue, short enough that a
#: leaked code is useless almost immediately.
CODE_LIFETIME_SECONDS = 120

_lock = threading.Lock()
# code -> (user_id, state, expires_at as a time.monotonic() reading)
_codes: dict[str, tuple[int, str, float]] = {}


def issue(user_id: int, state: str) -> str:
    """A fresh code for `user_id`, redeemable only with the same `state`."""
    code = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _lock:
        for stale in [c for c, (_, _, exp) in _codes.items() if exp <= now]:
            del _codes[stale]
        _codes[code] = (user_id, state, now + CODE_LIFETIME_SECONDS)
    return code


def redeem(code: str, state: str) -> int | None:
    """The user id behind `code`, or None if it's unknown, expired, or
    `state` doesn't match.

    The code is popped whatever the outcome: a wrong guess burns it, so a
    code can't be probed with different states.
    """
    with _lock:
        entry = _codes.pop(code, None)
    if entry is None:
        return None
    user_id, expected_state, expires_at = entry
    if time.monotonic() >= expires_at:
        return None
    if not hmac.compare_digest(state.encode(), expected_state.encode()):
        return None
    return user_id


def _reset() -> None:
    """Test hook: forget every outstanding code."""
    with _lock:
        _codes.clear()
