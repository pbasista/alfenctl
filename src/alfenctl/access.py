"""Who may talk to the charger: password policy and the app's PIN.

The rules here are the charger's, not a front end's: what a valid end-user
PIN looks like, how long a temporary password lasts by default, and what
the charger's refusal of a recovery code means in words.  The CLI and the
web API both need all three, and until this module existed the web layer
reached into :mod:`alfenctl.cli.commands.access` for them -- which is the
wrong direction, and which quietly put a second copy of the PIN pattern in
:mod:`alfenctl.web.api`.
"""

from __future__ import annotations

import json
import re

import httpx
from devicectl.progress import SECONDS_PER_MINUTE

# DlgEndUserPin's own validation, mirrored client-side.
PIN_RE = re.compile(r"^[0-9]{4,6}$")

# Default lifetime of a temporary password; the app's dialog offers 1..72 hours.
DEFAULT_TEMP_PASSWORD_HOURS = 24

# HTTP statuses the recovery endpoint answers with (ICULanDevice.ResetPassword).
HTTP_FORBIDDEN = 403

HTTP_TOO_MANY_REQUESTS = 429

HTTP_SERVICE_UNAVAILABLE = 503


def recovery_error(exc: httpx.HTTPStatusError) -> str:
    """Turn the charger's refusal of a reset code into the app's wording."""
    status = exc.response.status_code
    if status == HTTP_FORBIDDEN:
        return "the password reset code is incorrect."
    if status == HTTP_TOO_MANY_REQUESTS:
        try:
            body = json.loads(exc.response.text.replace('{"version":1,', "{"))
            left = float(body.get("lockout_remaining_seconds", 0))
        except (ValueError, TypeError):
            left = 0
        wait = f" for {left / SECONDS_PER_MINUTE:.1f} minutes" if left > 0 else ""
        return f"locked out{wait} after too many incorrect reset attempts."
    if status == HTTP_SERVICE_UNAVAILABLE:
        return "password recovery is not available on this charging station."
    return f"the charger refused the reset code (HTTP {status})."


__all__ = [
    "DEFAULT_TEMP_PASSWORD_HOURS",
    "PIN_RE",
    "recovery_error",
]
