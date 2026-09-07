"""The base class every error this program raises on purpose derives from.

A command fails for one of two reasons.  Either the charger, the network or
the input was not what it needed -- a property that does not exist, a
firmware image for another model, an unreachable station -- which is
ordinary and gets one clear line on stderr.  Or this program has a bug,
which deserves a traceback.

:class:`AlfenError` is the first kind.  Every module raises its own subclass
so a caller that cares can still tell a bad logo apart from a bad license
key, but :func:`alfenctl.cli.main` catches this one class, prints the
message and exits, and the web API turns it into a 400 -- neither has to
know the list.

Errors that are specifically about a *value* also derive from
:class:`ValueError`, because that is what they are and callers already
catch it that way.
"""

from __future__ import annotations


class AlfenError(Exception):
    """An expected failure, reportable to the user as a single line."""


__all__ = ["AlfenError"]
