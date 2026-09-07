"""``alfenctl tags`` -- the RFID whitelist the charger authorizes against.

This is the local list, used when no back office answers.  The master tag
is a separate property and gets its own action.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from alfenctl import master_tag, whitelist
from alfenctl.charger import AlfenCharger
from alfenctl.progress import end_live, write_live
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK
from alfenctl.cli.output import confirm


def _read_whitelist(
    charger: AlfenCharger, args: argparse.Namespace
) -> list[whitelist.Tag]:
    """Read the charger's whitelist, showing progress (it pages slowly)."""
    info = charger.basic_info()
    stride = whitelist.probe_stride(info.firmware_version)

    def tick(found: int) -> None:
        if not args.debug:
            write_live(f"  Reading tags  {found} found")

    tags = whitelist.download(charger, stride=stride, on_progress=tick)
    if not args.debug:
        end_live()
    return tags


def _print_tags(tags: list[whitelist.Tag]) -> None:
    """Print the whitelist as a table."""
    if not tags:
        print("The whitelist is empty.")
        return
    width = max(len(t.tag) for t in tags)
    parents = max((len(t.parent) for t in tags), default=0)
    print(f"{'TAG'.ljust(width)}  {'STATUS'.ljust(7)}  EXPIRES", end="")
    print(f"      {'PARENT'}" if parents else "")
    for tag in sorted(tags, key=lambda t: t.tag):
        line = f"{tag.tag.ljust(width)}  {tag.status_name.ljust(7)}  {tag.expiry_text}"
        print(f"{line}  {tag.parent}" if parents else line)
    print(f"\n{len(tags)} tag(s).")


def cmd_tags(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Read and edit the charger's local RFID whitelist."""
    import csv
    import io

    action = args.action
    if action == "list":
        tags = _read_whitelist(charger, args)
        if args.json:
            print(json.dumps([whitelist.tag_dict(t) for t in tags], indent=2))
        elif args.csv:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(whitelist.TAG_COLUMNS)
            writer.writerows(whitelist.tag_row(t) for t in tags)
            sys.stdout.write(buf.getvalue())
        else:
            _print_tags(tags)
        return EXIT_OK

    if action == "add":
        expires = _tag_expiry(args)
        if expires is EXPIRY_INVALID:
            return EXIT_ERROR
        status = whitelist.STATUS_CODES.get(args.status, whitelist.STATUS_ACTIVE)
        for tag in args.tags:
            whitelist.upsert(
                charger, tag, parent=args.parent, status=status, expires=expires
            )
        print(f"Wrote {len(args.tags)} tag(s).")
        return EXIT_OK

    if action == "remove":
        for tag in args.tags:
            whitelist.remove(charger, tag)
        print(f"Removed {len(args.tags)} tag(s).")
        return EXIT_OK

    if action == "clear":
        info = charger.basic_info()
        if not args.yes:
            if not confirm(f"Remove every tag from the whitelist on {info.object_id}?"):
                print("Aborted.", file=sys.stderr)
                return EXIT_ERROR
        whitelist.clear(charger)
        print("Whitelist cleared.")
        return EXIT_OK

    if action == "learn":
        whitelist.start_add_mode(charger)
        print(
            "The charger will add the next tag presented at its reader.\n"
            "Hold the card to the reader now, then re-read with "
            "'alfenctl tags list'."
        )
        return EXIT_OK

    if action == "master":
        return _cmd_tags_master(charger, args)

    return _import_tags(charger, args)


def _cmd_tags_master(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show or change the master tag (``tags master``)."""
    if args.tag:
        master_tag.set_tag(charger, args.tag)
        print(f"Master tag set to {args.tag} (enabled).")
    elif args.clear:
        master_tag.clear(charger)
        print("Master tag cleared.")
    elif args.enable or args.disable:
        charger.write_properties(
            {master_tag.PROP_ENABLED: (1 if args.enable else 0, None)}
        )
        print(f"Master tag mode {'enabled' if args.enable else 'disabled'}.")
    state = master_tag.read(charger)
    if not state.supported:
        print("This charger does not support a master tag.", file=sys.stderr)
        return EXIT_ERROR
    print(
        f"Master tag: {state.tag or '<none set>'} "
        f"({'enabled' if state.enabled else 'disabled'})"
    )
    return EXIT_OK


# Sentinel: --expires was given but could not be parsed.
EXPIRY_INVALID = object()


def _tag_expiry(args: argparse.Namespace) -> Any:
    """Parse ``--expires``, or return None (no expiry) / the invalid sentinel."""
    raw = getattr(args, "expires", None)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, whitelist.EXPIRY_FORMAT)
    except ValueError:
        print(
            f"error: --expires must be YYYY-MM-DD, not {raw!r}",
            file=sys.stderr,
        )
        return EXPIRY_INVALID


def _import_tags(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Apply a tag file to the charger, with a preview (``tags import``)."""
    try:
        wanted = whitelist.parse_tag_file(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not wanted:
        print(f"error: no tags in {args.file}", file=sys.stderr)
        return EXIT_ERROR
    current = _read_whitelist(charger, args)
    writes, removals = whitelist.diff(current, wanted)
    if not args.replace:
        removals = []
    if not writes and not removals:
        print("Nothing to change; the charger already matches the file.")
        return EXIT_OK
    for tag in writes:
        verb = "add" if all(t.tag != tag.tag for t in current) else "update"
        print(f"  {verb:6s} {tag.tag}  {tag.status_name}  {tag.expiry_text}")
    for tag in removals:
        print(f"  remove {tag.tag}")
    if args.dry_run:
        print("\nDry run; nothing written.")
        return EXIT_OK
    if not args.yes:
        if not confirm(f"\nApply {len(writes) + len(removals)} change(s)?"):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
    for tag in writes:
        whitelist.upsert(
            charger,
            tag.tag,
            parent=tag.parent,
            status=tag.status,
            expires=tag.expires,
        )
    for tag in removals:
        whitelist.remove(charger, tag.tag)
    print(f"Applied {len(writes) + len(removals)} change(s).")
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "tags",
        help="read and edit the local RFID whitelist",
        aliases=["whitelist"],
        description="Read and edit the charger's local RFID whitelist. "
        "With no ACTION, lists the tags.",
    )
    # The connection options go on each action, not on `tags` itself: argparse
    # hands everything after the action name to the action's own parser.  An
    # omitted action is filled in from DEFAULT_ACTIONS before parsing, so the
    # options still land on the action that ends up running.
    tags = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    tp = tags.add_parser("list", help="show every tag on the charger", parents=[common])
    tp.add_argument("--json", action="store_true", help="JSON instead of a table")
    tp.add_argument("--csv", action="store_true", help="CSV instead of a table")
    tp = tags.add_parser("add", help="add or update tags", parents=[common])
    tp.add_argument("tags", nargs="+", metavar="TAG", help="tag ids to write")
    tp.add_argument("--parent", default="", help="parent tag id (group membership)")
    tp.add_argument(
        "--status",
        default="active",
        choices=sorted(whitelist.STATUS_CODES),
        help="tag status (default active)",
    )
    tp.add_argument("--expires", metavar="YYYY-MM-DD", help="expiry date")
    tp = tags.add_parser("remove", help="remove tags", parents=[common])
    tp.add_argument("tags", nargs="+", metavar="TAG", help="tag ids to remove")
    tp = tags.add_parser("clear", help="remove every tag", parents=[common])
    tp.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    tp = tags.add_parser(
        "learn",
        help="enrol the next tag presented at the charger's reader",
        parents=[common],
    )
    tp = tags.add_parser(
        "import",
        help="apply a tag file (JSON, CSV, or one id a line)",
        parents=[common],
    )
    tp.add_argument("file", help="file to apply")
    tp.add_argument(
        "--replace",
        action="store_true",
        help="also remove tags the charger has that the file does not",
    )
    tp.add_argument(
        "--dry-run", action="store_true", help="preview the changes, write nothing"
    )
    tp.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    tp = tags.add_parser(
        "master",
        help="show or change the master tag (always authorises, no whitelist needed)",
        parents=[common],
    )
    tp.add_argument(
        "tag", nargs="?", help="tag id to set as the master tag (also enables it)"
    )
    mode = tp.add_mutually_exclusive_group()
    mode.add_argument("--clear", action="store_true", help="clear the master tag id")
    mode.add_argument(
        "--enable", action="store_true", help="turn the master tag mode on"
    )
    mode.add_argument(
        "--disable", action="store_true", help="turn the master tag mode off"
    )


COMMANDS: dict[str, Command] = {
    "tags": Command(cmd_tags),
    "whitelist": Command(cmd_tags),
}
