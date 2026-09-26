"""``alfenctl cloud`` -- what Alfen's own servers hold about a station.

In rising order of consequence: ``login`` signs in once and caches the token
(``logout`` forgets it); ``info`` reads the account, warranty, registered
license key and -- with ``--defaults`` -- the full factory-default property
profile for the connected station; ``license`` fetches that registered key
and, with ``--install``, writes it to the charger -- the one write this group
can make, and the same one ``license set`` and the vendor apps make after an
upgrade.  Everything else is for the owner's information only.

The token comes from ``--token``/``--token-file``/``$ALFEN_CLOUD_TOKEN`` or
the cache ``login`` wrote, in that order; an expired one with a refresh half
is renewed and re-cached without asking.  ``info`` and ``license`` need the
station reachable, because that is where the station's identity (serial and
socket count) is read from before it is asked about.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from devicectl.cli.command import Command, Need

from alfenctl.charger import AlfenCharger
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm, note
from alfenctl.config import default_config_dir
from alfenctl.errors import AlfenError


def _resolve_client(args: argparse.Namespace) -> tuple[Any, Any]:
    """Return an ``(httpx client, MyEveClient)`` for a valid token, or raise.

    Renews an expired token from its refresh half and re-caches it, so a
    day-old ``login`` still works without a second sign-in.
    """
    from alfenctl import cloud

    config_dir = default_config_dir()
    token = cloud.token_from_sources(
        explicit=getattr(args, "token", None),
        token_file=getattr(args, "token_file", None),
        config_dir=config_dir,
    )
    if token is None:
        raise cloud.CloudError(
            "no Alfen credentials: run 'alfenctl cloud login', or pass --token / "
            f"--token-file, or set ${cloud.TOKEN_ENV}"
        )
    client = cloud.make_client()
    if token.expired and token.refresh_token:
        token = cloud.refresh_token(client, token)
        # Only the cache is refreshed; a token passed by flag/env is not ours to store.
        if not getattr(args, "token", None) and not getattr(args, "token_file", None):
            cloud.save_cached_token(config_dir, token)
    return client, cloud.MyEveClient(token.access_token, client=client)


def _identity(
    charger: AlfenCharger, args: argparse.Namespace
) -> tuple[str, int, str | None]:
    """Return ``(identifier, sockets, object_code)`` to ask the server about.

    Read from the connected charger, with ``--identifier`` and ``--sockets``
    overriding for the odd station whose own report is not what Alfen filed
    it under, and ``--object-code`` supplying the article code the query
    takes but the charger does not carry.
    """
    info = charger.basic_info()
    identifier = getattr(args, "identifier", None) or info.object_id
    sockets = getattr(args, "sockets", None) or info.sockets or 1
    return identifier, int(sockets), getattr(args, "object_code", None)


def cmd_cloud(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Sign in, or read what Alfen holds about the connected station."""
    if args.action == "login":
        return _cmd_login(args)
    if args.action == "logout":
        return _cmd_logout(args)
    if args.action == "license":
        return _cmd_license(charger, args)
    return _cmd_info(charger, args)


def _cmd_login(args: argparse.Namespace) -> int:
    """Sign in interactively and cache the token for later commands."""
    from alfenctl import cloud

    client = cloud.make_client()
    try:
        token = cloud.login(client, open_browser=not args.no_browser)
    finally:
        client.close()
    path = cloud.save_cached_token(default_config_dir(), token)
    print(f"Signed in. Token cached at {path}.")
    print("Now: alfenctl cloud info, or alfenctl cloud license --install.")
    return EXIT_OK


def _cmd_logout(args: argparse.Namespace) -> int:
    """Forget the cached token, so the next command signs in afresh."""
    import os

    from alfenctl import cloud

    if cloud.clear_cached_token(default_config_dir()):
        print("Signed out. The cached Alfen token has been removed.")
    else:
        print("No cached Alfen token to remove.")
    if os.environ.get(cloud.TOKEN_ENV):
        note(f"${cloud.TOKEN_ENV} is still set and would be used by the next command")
    return EXIT_OK


def _print_rows(rows: list[tuple[str, object]]) -> None:
    """Print aligned ``label : value`` rows, dashing the empty ones."""
    width = max((len(label) for label, _ in rows), default=0)
    for label, value in rows:
        shown = value if value not in (None, "") else "-"
        print(f"  {label:<{width}} : {shown}")


def _cmd_info(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Show everything Alfen's servers hold about the connected station.

    The account, warranty and registered license key are the manufacturer's
    summary of a station; ``--defaults`` also prints the full factory-default
    property profile Alfen keeps on file, which is every property value the
    manufacturer has for it -- the same set the app reads to reset a station.
    """
    assert charger is not None  # Need.READY
    client, myeve = _resolve_client(args)
    try:
        identifier, sockets, object_code = _identity(charger, args)
        user = _safe(lambda: myeve.authenticated_user())
        warranty = _safe(lambda: myeve.warranty(identifier))
        registered_key = _safe(
            lambda: myeve.license_key(identifier, sockets, object_code)
        )
        recorded = _safe(lambda: myeve.last_created(identifier))
        defaults = _safe(
            lambda: myeve.factory_defaults(identifier, sockets, object_code)
        )
    finally:
        client.close()

    rows: list[tuple[str, object]] = [("Station", identifier), ("Sockets", sockets)]
    if isinstance(user, dict):
        profile = user.get("profileInformation") or {}
        name = " ".join(
            p for p in (profile.get("firstName"), profile.get("lastName")) if p
        )
        rows.append(("Account", name or user.get("uuid")))
        if profile.get("company"):
            rows.append(("Company", profile["company"]))
        if profile.get("phoneNumber"):
            rows.append(("Phone", profile["phoneNumber"]))
    if isinstance(warranty, dict) and warranty:
        rows.append(("Warranty type", warranty.get("warrantyType")))
        rows.append(("Warranty until", warranty.get("warrantyEnddate")))
    if isinstance(recorded, dict) and recorded:
        rows.append(("Records on file", recorded.get("totalCount")))
        rows.append(("Last recorded change", recorded.get("lastUpdate")))
    rows.append(
        ("Registered key", registered_key if isinstance(registered_key, str) else None)
    )
    default_props = defaults if isinstance(defaults, list) else []
    if default_props and not getattr(args, "defaults", False):
        rows.append(("Factory defaults", f"{len(default_props)} properties"))
    _print_rows(rows)

    if getattr(args, "defaults", False) and default_props:
        print("\nFactory defaults Alfen has on file:")
        _print_defaults(default_props)
    elif default_props:
        note("to see every factory-default property: alfenctl cloud info --defaults")
    if isinstance(registered_key, str) and registered_key:
        note("to install this key on the charger: alfenctl cloud license --install")
    return EXIT_OK


def _print_defaults(defaults: list[dict[str, Any]]) -> None:
    """Print the factory-default properties, each with its human title.

    The server hands back bare ``id``/``value`` pairs; the id gets the same
    name the rest of the tool shows it under (the EDS catalog's title, or the
    program's glossary where the EDS is silent), so the profile reads as
    properties rather than a column of register numbers.
    """
    from alfenctl.eds import load_catalog
    from alfenctl.glossary import title as glossary_title
    from alfenctl.transport import parse_prop_id

    catalog = load_catalog()
    decorated: list[tuple[str, str, object]] = []
    for entry in defaults:
        prop_id = str(entry.get("id") or "")
        key = parse_prop_id(prop_id)
        described = catalog.get(key) if key else None
        title = (described.title if described else "") or (
            glossary_title(key) if key else ""
        )
        decorated.append((prop_id, title, entry.get("value")))
    decorated.sort(key=lambda row: row[0])
    id_w = max((len(pid) for pid, _, _ in decorated), default=0)
    title_w = max((len(t) for _, t, _ in decorated), default=0)
    for prop_id, title, value in decorated:
        shown = value if value not in (None, "") else "-"
        print(f"  {prop_id:<{id_w}}  {title:<{title_w}}  {shown}")


def _cmd_license(charger: AlfenCharger | None, args: argparse.Namespace) -> int:
    """Fetch the registered license key; with ``--install``, write it."""
    from alfenctl.license import (
        PROP_LICENSE_KEY,
        normalize_license_key,
        read_license,
    )

    assert charger is not None  # Need.READY
    client, myeve = _resolve_client(args)
    try:
        identifier, sockets, object_code = _identity(charger, args)
        registered = myeve.license_key(identifier, sockets, object_code)
    finally:
        client.close()

    if not registered:
        print(f"Alfen has no license key on file for {identifier}.")
        return EXIT_OK

    key = normalize_license_key(registered)
    print(f"Alfen's registered key for {identifier}: {key}")
    if not args.install:
        note("re-run with --install to write it to the charger")
        return EXIT_OK

    current = read_license(charger).license_key
    if current and normalize_license_key(current) == key:
        print("The charger already has this key; nothing to install.")
        return EXIT_OK
    if not args.yes and not confirm(f"Install {key} on {identifier}?"):
        print("Aborted.", file=sys.stderr)
        return EXIT_ERROR
    charger.write_properties({PROP_LICENSE_KEY: (key, None)})
    print(f"License key set to {key}.")
    print(
        "The charging station will reboot on its own to install any new "
        "feature(s); check with 'alfenctl license show' once it is back."
    )
    return EXIT_OK


def _safe(call: Any) -> Any:
    """Run a server call, returning None instead of failing the whole report.

    ``info`` gathers several independent answers; one the account is not
    entitled to should dim a row, not sink the command.
    """
    try:
        return call()
    except AlfenError:
        return None


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "cloud",
        help="query Alfen's servers for a station's registered info and license",
        description="Read what Alfen's servers hold about a station -- account, "
        "warranty, and the registered license key -- and optionally install "
        "that key. With no ACTION, shows the info.",
    )
    csub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)

    lp = csub.add_parser(
        "login", help="sign in to Alfen and cache a token", parents=[common]
    )
    lp.add_argument(
        "--no-browser",
        action="store_true",
        help="do not try to open a browser; print the URL to open yourself",
    )

    csub.add_parser(
        "logout",
        help="forget the cached token (the next command signs in again)",
        parents=[common],
    )

    def _add_token_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--token", help="bearer token to use instead of a cached login"
        )
        parser.add_argument("--token-file", help="read the bearer token from this file")
        parser.add_argument(
            "--identifier",
            help="station serial to ask about (default: the charger's own)",
        )
        parser.add_argument(
            "--sockets",
            type=int,
            help="socket count for the query (default: the charger's own)",
        )
        parser.add_argument(
            "--object-code", help="article/object code, if the query needs one"
        )

    ip = csub.add_parser(
        "info",
        help="show account, warranty, registered license and factory defaults",
        parents=[common],
    )
    _add_token_args(ip)
    ip.add_argument(
        "--defaults",
        action="store_true",
        help="also list every factory-default property Alfen holds for the station",
    )

    lp = csub.add_parser(
        "license",
        help="fetch the registered license key, and optionally install it",
        parents=[common],
    )
    _add_token_args(lp)
    lp.add_argument(
        "--install",
        action="store_true",
        help="write the fetched key to the charger (it reboots to apply)",
    )
    lp.add_argument(
        "-y", "--yes", action="store_true", help="install without asking to confirm"
    )


COMMANDS: dict[str, Command] = {
    "cloud": Command(
        cmd_cloud,
        default_action="info",
        per_action={"login": Need.NOTHING, "logout": Need.NOTHING},
        fans_out=("info", "license"),
    ),
}
