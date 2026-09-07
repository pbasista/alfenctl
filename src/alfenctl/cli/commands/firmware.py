"""Things the charger downloads and runs: firmware and a splash logo.

Both replace something the charger keeps across a reboot, so both check
what they are about to do, show it, and ask.  The work itself is in
:mod:`alfenctl.upgrade` and :mod:`alfenctl.logo`, which print nothing; this
module is the part that talks to a person.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from alfenctl.charger import AlfenCharger, ChargerInfo
from alfenctl.firmware import FirmwareFile, check_compatibility
from alfenctl.progress import BYTES_PER_KB, BYTES_PER_MB, fmt_duration
from alfenctl.repo import (
    Candidate,
    RepoConfig,
    RepositoryError,
    candidates,
    default_cache_dir,
    download,
    list_firmware,
    recommended,
)
from alfenctl.upgrade import (
    DEFAULT_INSTALL_TIMEOUT_S,
    TYPICAL_INSTALL_S,
    UPLOAD_THROUGHPUT_BYTES_PER_S,
    InstallFailed,
    UploadInProgress,
    install,
    send_image,
)

from alfenctl.cli.command import Command
from alfenctl.cli.exits import (
    EXIT_ERROR,
    EXIT_INCOMPATIBLE,
    EXIT_NO_FIRMWARE,
    EXIT_OK,
    EXIT_UPDATE_FAILED,
    EXIT_UPLOAD_IN_PROGRESS,
)
from alfenctl.cli.output import confirm
from alfenctl.cli.report import TerminalReporter
from alfenctl.cli.target import repo_config

# Column width of the file-name column in the firmware picker.
NAME_COLUMN_WIDTH = 40

# What the upgrade's own failures exit with.  Order matters only in that the
# first match wins; these three do not overlap.  See :mod:`alfenctl.cli.exits`.
EXIT_FOR: tuple[tuple[type[Exception], int], ...] = (
    (UploadInProgress, EXIT_UPLOAD_IN_PROGRESS),
    (InstallFailed, EXIT_UPDATE_FAILED),
    (RepositoryError, EXIT_NO_FIRMWARE),
)


# --- Picking a release from Alfen's server ------------------------------------------------


def print_candidates(cands: list[Candidate], info: ChargerInfo, location: str) -> None:
    """Print the numbered table the user picks from, newest release first.

    The columns are the ones the app's upload dialog shows (file, version,
    date) plus the size and what the change would mean for this charger.
    """
    print(
        f"\nFirmware for {info.model or 'this charger'} on {location} "
        f"(now running {info.firmware}):\n"
    )
    print(
        f"  {'#':>2}  {'File':<{NAME_COLUMN_WIDTH}}  {'Version':<12}  "
        f"{'Released':<10}  {'Size':>7}  Notes"
    )
    for n, cand in enumerate(cands, start=1):
        fw = cand.fw
        name = (
            fw.name
            if len(fw.name) <= NAME_COLUMN_WIDTH
            else fw.name[: NAME_COLUMN_WIDTH - 1] + "\u2026"
        )
        date = fw.modified.strftime("%Y-%m-%d") if fw.modified else "-"
        size = f"{fw.size / BYTES_PER_MB:.1f} MB" if fw.size else "-"
        print(
            f"  {n:>2}  {name:<{NAME_COLUMN_WIDTH}}  {fw.release.label or '?':<12}  "
            f"{date:<10}  {size:>7}  {cand.summary}"
        )


def _ask_for_choice(cands: list[Candidate], default: int | None) -> Candidate | None:
    """Prompt until the user names a listed release or cancels (None)."""
    hint = f" [1-{len(cands)}]" if len(cands) > 1 else " [1]"
    suffix = f", default {default + 1}" if default is not None else ""
    while True:
        try:
            reply = input(f"\nChoose a firmware{hint}{suffix}, or 'q' to cancel: ")
        except EOFError:
            return None
        reply = reply.strip()
        if reply.lower() in ("q", "quit", "n", "no"):
            return None
        if not reply and default is not None:
            return cands[default]
        if reply.isdigit() and 1 <= int(reply) <= len(cands):
            return cands[int(reply) - 1]
        print("Please enter one of the numbers above, or 'q'.")


def choose_firmware(
    info: ChargerInfo,
    *,
    config: RepoConfig | None = None,
    cache_dir: Path | None = None,
    include_all: bool = False,
    yes: bool = False,
) -> Path | None:
    """List what Alfen publishes for this charger, pick one, and download it.

    Returns the path of the image to upload, or ``None`` if the user
    cancelled. Raises :class:`RepositoryError` when the server cannot be
    reached or has nothing for this charger.
    """
    config = config or RepoConfig()
    print(f"\nNo firmware file given; asking {config.site} what is available...")
    cands = candidates(list_firmware(config), info, include_all=include_all)
    if not cands:
        raise RepositoryError(
            f"no firmware for {info.model or info.family} published on {config.location}"
            + ("" if include_all else " (try --all to list every image)")
        )
    print_candidates(cands, info, config.location)

    best = recommended(cands)
    default = cands.index(best) if best is not None else None
    if yes:
        if best is None:
            raise RepositoryError(
                "no clear next release for this charger, so --yes has nothing "
                "to choose; run without --yes and pick a line from the list"
            )
        chosen = best
        print(f"\nChoosing {chosen.fw.name} (--yes).")
    else:
        chosen = _ask_for_choice(cands, default)
        if chosen is None:
            return None
    return download(chosen.fw, info.family, config=config, cache_dir=cache_dir)


# --- alfenctl firmware --------------------------------------------------------------------


def cmd_firmware(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Upgrade the firmware, or (with --list) only show what the server offers."""
    cache_dir = Path(args.cache_dir).expanduser() if args.cache_dir else None
    config = repo_config(args)
    info = charger.basic_info()
    try:
        if args.list:
            return _show_list(info, config, cache_dir, include_all=args.all)
        return _upgrade(charger, args, info, config, cache_dir)
    except (UploadInProgress, InstallFailed, RepositoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return next(
            (code for kind, code in EXIT_FOR if isinstance(exc, kind)), EXIT_ERROR
        )


def _show_list(
    info: ChargerInfo,
    config: RepoConfig,
    cache_dir: Path | None,
    *,
    include_all: bool,
) -> int:
    """Print what the server offers for this charger, and stop."""
    cands = candidates(list_firmware(config), info, include_all=include_all)
    if not cands:
        raise RepositoryError(
            f"no firmware for {info.model or info.family} on {config.location}"
            + ("" if include_all else " (try --all to list every image)")
        )
    print_candidates(cands, info, config.location)
    print(f"\nDownloads are cached in {cache_dir or default_cache_dir()}.")
    return EXIT_OK


def _upgrade(
    charger: AlfenCharger,
    args: argparse.Namespace,
    info: ChargerInfo,
    config: RepoConfig,
    cache_dir: Path | None,
) -> int:
    """Check an image against this charger, show what it means, then install it."""
    print(
        f"Selected station: {info.object_id} ({info.model}), firmware {info.firmware}"
    )
    path: Path | None = args.file
    if path is None:
        path = choose_firmware(
            info,
            config=config,
            cache_dir=cache_dir,
            include_all=args.all,
            yes=args.yes,
        )
        if path is None:
            print("Cancelled.", file=sys.stderr)
            return EXIT_ERROR
    fw = FirmwareFile.load(path)
    version = f"  (version {'.'.join(map(str, fw.version))})" if fw.version else ""
    print(f"Firmware file:    {path.name}{version}")

    result = check_compatibility(info.family, info.firmware_version, fw)
    print("\nCompatibility check:")
    for note in result.notes:
        print(f"  - {note}")
    for warning in result.warnings:
        print(f"  ! {warning}")
    for error in result.errors:
        print(f"  x {error}")
    if not result.ok:
        print(
            "\nAborting: firmware file is not compatible with this charger.",
            file=sys.stderr,
        )
        return EXIT_INCOMPATIBLE
    print("  => compatible" + (" (with warnings)" if result.warnings else ""))

    print(
        f"\nThis sends {len(fw.data) / BYTES_PER_MB:.1f} MB (est. "
        f"~{fmt_duration(len(fw.data) / UPLOAD_THROUGHPUT_BYTES_PER_S)} at "
        f"~{UPLOAD_THROUGHPUT_BYTES_PER_S / BYTES_PER_KB:.0f} KB/s); the charger "
        f"then installs it and reboots itself, usually in "
        f"~{fmt_duration(TYPICAL_INSTALL_S)} "
        f"(giving up after {fmt_duration(args.install_timeout)})."
    )
    if not args.yes and not confirm(
        f"\nUpdate the firmware of '{info.object_id}' to '{path.name}'?"
    ):
        print("Cancelled.", file=sys.stderr)
        return EXIT_ERROR

    with TerminalReporter(debug=args.debug) as report:
        install(
            charger,
            fw.data,
            report=report,
            new_password=args.new_password,
            deadline_s=args.install_timeout,
        )
    print("Firmware updated successfully.")
    _print_state_now(charger, info)
    return EXIT_OK


def _print_state_now(charger: AlfenCharger, before: ChargerInfo) -> None:
    """Report the charger's post-upgrade state, above all its firmware version."""
    try:
        after = charger.basic_info()
    except httpx.HTTPError as exc:
        print(
            f"(could not read the charger's state after the upgrade: {exc})",
            file=sys.stderr,
        )
        return
    print("\nCharger state now:")
    print(f"  station : {after.object_id} ({after.model})")
    print(f"  firmware: {before.firmware} -> {after.firmware}")
    if after.identity:
        print(f"  identity: {after.identity}")


# --- alfenctl logo ------------------------------------------------------------------------


def cmd_logo(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Convert and upload a splash-screen logo."""
    from alfenctl.logo import build_package, package_path

    image = Path(args.file)
    if args.save:
        # Only building a file: the licence gates what the *charger* accepts,
        # and the package may well be meant for a different station.
        package, kind, box = build_package(charger, image)
        destination = package_path(Path(args.save), kind)
        if (
            destination.exists()
            and not args.yes
            and not confirm(f"'{destination}' already exists. Overwrite?")
        ):
            print("Aborted.", file=sys.stderr)
            return EXIT_ERROR
        destination.write_bytes(package)
        print(
            f"Wrote {len(package)} bytes to {destination} -- a {kind.upper()} "
            f"package built for a {box[0]}x{box[1]} display."
        )
        return EXIT_OK

    if not _has_a_display(charger, force=args.force):
        return EXIT_ERROR
    if not _display_is_licensed(charger, force=args.force):
        return EXIT_ERROR
    package, kind, box = build_package(charger, image)
    print(
        f"Uploading logo '{image.name}' as a {kind.upper()} package "
        f"({len(package)} bytes, display {box[0]}x{box[1]})..."
    )
    if not args.yes and not confirm("Upload the logo to the charger?"):
        print("Aborted.", file=sys.stderr)
        return EXIT_ERROR
    with TerminalReporter(debug=args.debug) as report:
        send_image(
            charger,
            package,
            report=report,
            label="Uploading the logo",
            is_ahp=kind == "tvf",
        )
    print("Logo uploaded.")
    print(
        "note: HTTP 200 only means the transfer was accepted. The charger "
        "logs 'Unable to upload logo: Personalized display feature is "
        "locked!' and keeps the default logo when the feature is not "
        "licensed -- check with `alfenctl log -n 10`.",
        file=sys.stderr,
    )
    return EXIT_OK


def _has_a_display(charger: AlfenCharger, *, force: bool) -> bool:
    """Report whether the charger has a screen to put a logo on."""
    from alfenctl.logo import read_display

    display = read_display(charger)
    if display.present:
        return True
    if not force:
        print(
            "error: this charger reports no display (property 12896_1 and a "
            "logo box at 12896_3/4), and its model is not one of the few that "
            "have a screen without describing one.\n"
            "The vendor app greys its own upload button out here: a package "
            "sent to a station with no screen transfers and is shown nowhere.\n"
            "Use --force to upload anyway.",
            file=sys.stderr,
        )
        return False
    print(
        "warning: this charger reports no display; uploading anyway (--force)",
        file=sys.stderr,
    )
    return True


def _display_is_licensed(charger: AlfenCharger, *, force: bool) -> bool:
    """Report whether the charger will apply a logo, and say so if it will not."""
    from alfenctl.license import (
        FEATURE_PERSONALIZED_DISPLAY,
        feature_unlocked,
        read_license,
    )

    info = charger.basic_info()
    if feature_unlocked(
        str(info.firmware or ""),
        read_license(charger).features_raw,
        FEATURE_PERSONALIZED_DISPLAY,
        ahp=info.family == "AHP",
    ):
        return True
    if not force:
        print(
            "error: the 'Personalized display' feature is not licensed "
            "on this charger (property 21A2_0 bit 0x1000 is clear).\n"
            "The vendor app refuses logo uploads in this state; the "
            "observed HTTP 400 is consistent with the charger enforcing "
            "it too, but that is not independently confirmed. A key from "
            "your vendor is installed with `alfenctl license set <key>`.\n"
            "Use --force to upload anyway and test the charger's own "
            "behavior.",
            file=sys.stderr,
        )
        return False
    print(
        "warning: 'Personalized display' is not licensed; uploading anyway (--force)",
        file=sys.stderr,
    )
    return True


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "firmware",
        help="upgrade the charger firmware",
        aliases=["upgrade"],
        parents=[common],
    )
    sp.add_argument(
        "file",
        type=Path,
        nargs="?",
        help="firmware image to check and upload (omit to pick one from Alfen's server)",
    )
    sp.add_argument(
        "--list",
        action="store_true",
        help="only list the firmware the server offers for this charger",
    )
    sp.add_argument(
        "--all",
        action="store_true",
        help="also list images whose product code does not match this model",
    )
    sp.add_argument(
        "--cache-dir",
        help=f"where downloaded images are kept (default {default_cache_dir()})",
    )
    sp.add_argument(
        "--new-password",
        help="unique password to set when upgrading across the 5.0 boundary",
    )
    sp.add_argument(
        "--install-timeout",
        type=float,
        default=DEFAULT_INSTALL_TIMEOUT_S,
        help="seconds to wait before giving up on the install; not an "
        f"estimate -- it usually takes ~{TYPICAL_INSTALL_S / 60:.0f} minutes "
        f"(default {DEFAULT_INSTALL_TIMEOUT_S:.0f})",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")

    sp = sub.add_parser(
        "logo", help="upload a splash-screen logo image", parents=[common]
    )
    sp.add_argument("file", type=Path, help="image file (PNG/JPEG/BMP)")
    sp.add_argument(
        "--save",
        metavar="FILE",
        help="write the packaged logo to a file instead of uploading it "
        "(the app's 'Create Image Update file')",
    )
    sp.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    sp.add_argument(
        "--force",
        action="store_true",
        help="upload even when the charger reports no display, or without "
        "the 'Personalized display' license; the charger accepts the "
        "transfer either way but will not apply the logo",
    )


COMMANDS: dict[str, Command] = {
    "firmware": Command(cmd_firmware),
    "upgrade": Command(cmd_firmware),
    "logo": Command(cmd_logo),
}
