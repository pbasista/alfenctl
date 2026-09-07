"""Alfen's firmware server: what is published there, and which of it fits.

The Windows app keeps a local mirror of Alfen's FTP site (``ICUNetwork.UpdateManager``
against ``ftp://ftp.alfen.com/`` with the credentials baked into
``ICUServiceInstaller.AppProperties``) and its upload dialog then lists that
mirror, filtered only by file extension, newest file first.

This module does the same listing on demand -- no mirror to keep in sync --
and filters it harder: an image is offered when its extension matches the
charger's family *and* its product code covers the charger's model, so an
AHWP01 image is not offered for an AHP02. Each candidate is annotated with
what the upgrade would mean (upgrade/downgrade, the 5.0 unique-password
barrier, the 6.6.2 stepping stone), which the app only ever showed as one
standing warning label.

Alfen also publishes an image inside a ``.zip`` bundle (image + certificate +
signature + OCPP key list); a downloaded bundle is unpacked and the image
inside it is what gets uploaded.
"""

from __future__ import annotations

import ftplib
import os
import re
import time
import zipfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from alfenctl.charger import ChargerInfo
from alfenctl.errors import AlfenError
from alfenctl.firmware import (
    BUNDLE_EXTENSION,
    FW_MAJOR_5_BOUNDARY,
    NG_STEPPING_STONE_RELEASE,
    ReleaseName,
    allowed_extensions,
    needs_stepping_stone,
    parse_release_name,
    product_code,
    product_matches_model,
)
from alfenctl.progress import (
    BYTES_PER_MB,
    bar,
    end_live,
    fmt_duration,
    write_live,
)

# --- The server ---------------------------------------------------------------------------

# Straight from ICUServiceInstaller.AppProperties: the site, the shared
# installer account, and the folder the firmware images live in. The app ships
# these in plain sight in its binary; they are not per-customer credentials.
DEFAULT_SITE = "ftp.alfen.com"
DEFAULT_PORT = 21
DEFAULT_USERNAME = "installer"
DEFAULT_PASSWORD = "jIf978FQmk1W"  # noqa: S105 - published in the app's binary
DEFAULT_DIRECTORY = "Firmware"
# The app allows itself 2 s (AppProperties.FTPCommunicationTimeout); that is
# tight for a listing over the open internet, so we are more patient.
DEFAULT_TIMEOUT_S = 20.0
# Reading a ~2 MB image over FTP takes a while; give the transfer its own,
# longer timeout.
DOWNLOAD_TIMEOUT_S = 120.0
# Read size for RETR; also how often the download progress bar advances.
DOWNLOAD_BLOCK_SIZE = 32768


class RepositoryError(AlfenError):
    """The firmware server could not be reached, or answered unusably."""


@dataclass
class RepoConfig:
    """Where to fetch firmware from; overridable via ``[firmware]`` in alfen.toml."""

    site: str = DEFAULT_SITE
    port: int = DEFAULT_PORT
    username: str = DEFAULT_USERNAME
    password: str = DEFAULT_PASSWORD
    directory: str = DEFAULT_DIRECTORY
    timeout: float = DEFAULT_TIMEOUT_S

    @property
    def location(self) -> str:
        """Return a human-readable "host/directory" for messages."""
        return f"{self.site}/{self.directory}".rstrip("/")


def default_cache_dir() -> Path:
    """Return where downloaded images are kept between runs.

    ``$XDG_CACHE_HOME/alfen/firmware``, falling back to
    ``~/.cache/alfen/firmware`` -- the counterpart of the app's
    ``%APPDATA%/ACE Service Installer/Firmware`` mirror, except that we fill
    it lazily with what was actually asked for.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "alfen" / "firmware"


# --- Listing ------------------------------------------------------------------------------


@dataclass
class RemoteFirmware:
    """One firmware file offered by the server."""

    name: str
    size: int | None
    modified: datetime | None
    release: ReleaseName
    is_bundle: bool  # a .zip carrying the image rather than the image itself

    @property
    def version(self) -> tuple[int, int, int] | None:
        """Return the release's ``(major, minor, patch)``, if the name carries one."""
        return self.release.version

    @property
    def sort_key(self) -> tuple:
        """Return a newest-first ordering key: version, then build, then date."""
        return (
            self.version or (-1, -1, -1),
            self.release.build or -1,
            self.modified or datetime.min,
            self.name,
        )


# Unix listing line, as produced by the server the app parses with the very
# same shape (UpdateManager.CheckAdditionalFTPFiles); loosened slightly for
# ACLs ("+"), sticky bits and group names containing dots or dashes.
_LIST_RE = re.compile(
    r"^(?P<kind>[-dl])(?P<perm>[-rwxsStT]{9})\+?\s+\d+"
    r"\s+\S+\s+\S+\s+(?P<size>\d+)"
    r"\s+(?P<date>\w{3}\s+\d{1,2}\s+(?:\d{1,2}:\d{2}|\d{4}))\s+(?P<name>.+)$"
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}
# A Unix listing date is three fields ("Feb", "4", "09:06" or "2026"); one
# with a time and no year is within the last twelve months, so a date that
# would land in the future belongs to last year.
LIST_DATE_FIELDS = 3


def _parse_list_date(text: str, now: datetime | None = None) -> datetime | None:
    """Parse a Unix listing date ("Feb  4 09:06" or "Feb  4 2026")."""
    now = now or datetime.now()
    parts = text.split()
    if len(parts) < LIST_DATE_FIELDS:
        return None
    month = _MONTHS.get(parts[0].lower())
    if month is None or not parts[1].isdigit():
        return None
    day = int(parts[1])
    if ":" in parts[2]:
        hour, minute = (int(x) for x in parts[2].split(":", 1))
        stamp = datetime(now.year, month, day, hour, minute)
        if stamp > now:  # no year in the listing: it must be last year's
            stamp = stamp.replace(year=now.year - 1)
        return stamp
    if not parts[2].isdigit():
        return None
    return datetime(int(parts[2]), month, day)


def parse_list_line(
    line: str, now: datetime | None = None
) -> tuple[str, int, datetime | None] | None:
    """Parse one ``LIST`` line into ``(name, size, modified)``; None if it is not a file."""
    m = _LIST_RE.match(line.strip())
    if m is None or m["kind"] != "-":
        return None
    return m["name"].strip(), int(m["size"]), _parse_list_date(m["date"], now)


def _parse_mlsd_stamp(text: str) -> datetime | None:
    """Parse an MLSD ``modify`` fact ("20260204090658")."""
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _to_remote(
    name: str, size: int | None, modified: datetime | None
) -> RemoteFirmware:
    """Wrap a listing entry, reading what the file name says about the release."""
    return RemoteFirmware(
        name=name,
        size=size,
        modified=modified,
        release=parse_release_name(name),
        is_bundle=name.lower().endswith(BUNDLE_EXTENSION),
    )


@contextmanager
def _connect(config: RepoConfig, timeout: float | None = None) -> Iterator[ftplib.FTP]:
    """Yield a logged-in FTP session, translating every failure to RepositoryError.

    Plain FTP in passive mode, as the app's ``FtpWebRequest`` uses it.
    """
    ftp = ftplib.FTP(timeout=timeout or config.timeout)
    try:
        ftp.connect(config.site, config.port)
        ftp.login(config.username, config.password)
        ftp.set_pasv(True)
    except (OSError, ftplib.Error) as exc:
        raise RepositoryError(f"cannot reach {config.site}: {exc}") from exc
    try:
        yield ftp
    except (OSError, ftplib.Error) as exc:
        raise RepositoryError(f"{config.site}: {exc}") from exc
    finally:
        try:
            ftp.quit()
        except (OSError, ftplib.Error):
            ftp.close()


def _listing(ftp: ftplib.FTP, directory: str) -> list[RemoteFirmware]:
    """List ``directory``, preferring MLSD (exact sizes and UTC dates) over LIST."""
    try:
        entries = list(ftp.mlsd(directory, facts=["type", "size", "modify"]))
    except (ftplib.error_perm, ftplib.error_proto):
        entries = []  # older servers (and the one the app talks to) speak LIST
    else:
        return [
            _to_remote(
                name,
                int(facts["size"]) if facts.get("size", "").isdigit() else None,
                _parse_mlsd_stamp(facts.get("modify", "")),
            )
            for name, facts in entries
            if facts.get("type") == "file"
        ]
    lines: list[str] = []
    ftp.retrlines(f"LIST {directory}" if directory else "LIST", lines.append)
    out: list[RemoteFirmware] = []
    for line in lines:
        parsed = parse_list_line(line)
        if parsed is not None:
            out.append(_to_remote(*parsed))
    return out


def list_firmware(config: RepoConfig | None = None) -> list[RemoteFirmware]:
    """Return every file published in the server's firmware folder, newest first."""
    config = config or RepoConfig()
    with _connect(config) as ftp:
        images = _listing(ftp, config.directory)
    return sorted(images, key=lambda fw: fw.sort_key, reverse=True)


# --- Compatibility ------------------------------------------------------------------------


@dataclass
class Candidate:
    """A published image judged against one charger."""

    fw: RemoteFirmware
    matches_model: bool  # the product code covers this charger's model
    notes: list[str] = field(default_factory=list)  # what this upgrade means
    warnings: list[str] = field(default_factory=list)  # what to watch out for
    # True when this is not the right *next* step for this charger (it needs a
    # stepping stone first, or is built for another model). Such an image can
    # still be chosen deliberately; it just is never the recommendation.
    blocked: bool = False

    @property
    def summary(self) -> str:
        """Return the notes and warnings as one short line for the picker."""
        return "; ".join([*self.notes, *(f"! {w}" for w in self.warnings)])


def _is_image_for(fw: RemoteFirmware, family: str) -> bool:
    """Return whether ``fw`` is an image (or bundle) for a charger of ``family``."""
    lowered = fw.name.lower()
    if lowered.endswith(allowed_extensions(family)):
        return True
    # A bundle hides the image's extension, so its product code has to carry
    # the family instead -- which is exactly what the model match checks.
    return fw.is_bundle and fw.version is not None


def _annotate(fw: RemoteFirmware, info: ChargerInfo) -> Candidate:
    """Judge one image against the charger: what it would do, and what to know first."""
    cand = Candidate(
        fw=fw,
        matches_model=bool(info.model)
        and product_matches_model(fw.release.product, info.model),
    )
    current, target = info.firmware_version, fw.version
    if target is None:
        cand.warnings.append("no version in the file name")
    elif current is None:
        cand.notes.append("charger version unknown")
    elif target > current:
        cand.notes.append("upgrade")
    elif target == current:
        cand.notes.append("currently installed")
    else:
        cand.notes.append("downgrade")
    if not cand.matches_model:
        code = product_code(fw.release.product)
        cand.warnings.append(f"built for {code or 'an unknown product'}")
        cand.blocked = True
    # Crossing 5.0 is allowed, it just needs --new-password afterwards, so it
    # stays a warning; needing the 6.6.2 stepping stone rules the image out as
    # the *next* step.
    if (
        info.family == "NG"
        and current is not None
        and target is not None
        and current[0] < FW_MAJOR_5_BOUNDARY <= target[0]
    ):
        cand.warnings.append("crosses 5.0: needs a new unique password")
    if needs_stepping_stone(info.family, current, target):
        cand.warnings.append(f"install {NG_STEPPING_STONE_RELEASE} first")
        cand.blocked = True
    return cand


def candidates(
    images: list[RemoteFirmware], info: ChargerInfo, *, include_all: bool = False
) -> list[Candidate]:
    """Return the images that suit ``info``, newest first.

    Anything whose extension belongs to the other charger family is dropped
    outright (this is the app's whole filter). Beyond that, images whose
    product code does not cover the charger's model are dropped too, unless
    ``include_all`` keeps them -- flagged -- for the rare case where Alfen
    names a release in a way we do not recognise.

    If that leaves nothing at all, the family list comes back instead with
    every row flagged and blocked: Alfen sometimes retires a product code
    from the server while the chargers are still in the field, and showing
    the family's images with a warning is what the app would show anyway --
    never less than the app, only better labelled.
    """
    out = [_annotate(fw, info) for fw in images if _is_image_for(fw, info.family)]
    matching = [c for c in out if c.matches_model]
    if matching and not include_all:
        out = matching
    return sorted(out, key=lambda c: c.fw.sort_key, reverse=True)


def recommended(cands: list[Candidate]) -> Candidate | None:
    """Return the release to offer as the default, or None if none is worth it.

    The newest image that is an upgrade and is a valid next step -- so for a
    charger below 6.6 that is the 6.6.2 stepping stone, not the 7.x it cannot
    take yet.
    """
    for cand in cands:
        if "upgrade" in cand.notes and not cand.blocked:
            return cand
    return None


# --- Download -----------------------------------------------------------------------------


def _extract_image(bundle: Path, family: str) -> Path:
    """Unpack the firmware image out of a downloaded ``.zip`` release bundle."""
    wanted = allowed_extensions(family)
    with zipfile.ZipFile(bundle) as zf:
        members = [
            n
            for n in zf.namelist()
            if n.lower().endswith(wanted) and not n.endswith("/")
        ]
        if not members:
            raise RepositoryError(
                f"{bundle.name} contains no {' or '.join(wanted)} image"
            )
        member = members[0]
        target = bundle.parent / Path(member).name
        with zf.open(member) as src, target.open("wb") as dst:
            while chunk := src.read(DOWNLOAD_BLOCK_SIZE):
                dst.write(chunk)
    return target


def _report(name: str, done: int, total: int | None, started: float) -> None:
    """Draw one line of download progress (a bar when the total size is known)."""
    elapsed = time.monotonic() - started
    mb = done / BYTES_PER_MB
    if total:
        write_live(
            f"  {name}  [{bar(done / total)}] {done * 100 // total:3d}%  "
            f"{mb:.1f}/{total / BYTES_PER_MB:.1f} MB  {fmt_duration(elapsed)}"
        )
    else:
        write_live(f"  {name}  {mb:.1f} MB  {fmt_duration(elapsed)}")


def download(
    fw: RemoteFirmware,
    family: str,
    *,
    config: RepoConfig | None = None,
    cache_dir: Path | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    """Fetch ``fw`` into the cache and return the path of the image to upload.

    A file already in the cache with the expected size is reused. A ``.zip``
    bundle is unpacked and the image inside it is what comes back.

    ``on_progress`` takes ``(bytes so far, total or None)``; a caller that
    passes one is not a terminal, so nothing is drawn or printed.
    """
    config = config or RepoConfig()
    cache = cache_dir or default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / Path(fw.name).name
    quiet = on_progress is not None

    def say(message: str) -> None:
        if not quiet:
            print(message)

    if local.is_file() and (fw.size is None or local.stat().st_size == fw.size):
        say(f"Using the cached copy of {local.name} ({local.parent}).")
        if on_progress is not None:
            on_progress(local.stat().st_size, fw.size)
    else:
        size_text = f" ({fw.size / BYTES_PER_MB:.1f} MB)" if fw.size else ""
        say(f"Downloading {local.name}{size_text} from {config.location}...")
        started = time.monotonic()
        done = 0
        remote_path = f"{config.directory}/{fw.name}" if config.directory else fw.name
        try:
            with _connect(config, timeout=DOWNLOAD_TIMEOUT_S) as ftp:
                with local.open("wb") as out:

                    def _chunk(data: bytes) -> None:
                        nonlocal done
                        out.write(data)
                        done += len(data)
                        if on_progress is not None:
                            on_progress(done, fw.size)
                        else:
                            _report(local.name, done, fw.size, started)

                    ftp.retrbinary(
                        f"RETR {remote_path}", _chunk, blocksize=DOWNLOAD_BLOCK_SIZE
                    )
                if fw.modified is not None:
                    stamp = fw.modified.timestamp()
                    os.utime(local, (stamp, stamp))
        except BaseException:
            # Don't leave a half-written image in the cache: with no size to
            # check it against, the next run would happily upload it.
            if not quiet:
                end_live()
            local.unlink(missing_ok=True)
            raise
        if not quiet:
            end_live()

    if fw.is_bundle:
        image = _extract_image(local, family)
        say(f"Unpacked {image.name} from {local.name}.")
        return image
    return local


# --- Presets -------------------------------------------------------------------------------

# Alfen publishes ready-made configuration beside the firmware, in the folders
# the app mirrors on startup (``AppProperties.FTPTCPPresetsFolder`` and
# friends).  Two kinds live there, and the app reads each in its own dialog:
# settings XML (``DlgPresets``, which takes .xml and .iip) and Modbus
# register maps as JSON (``DlgModbusRegisterMap``).
#
# The third folder is not like the other two.  Its 900-odd files are firmware
# blobs (``.fwi``/``.fwu`` for NG, ``.tfw``/``.tcf`` for AHP -- exactly
# ``ICULanDevice.getUpdateFileTypes``), and the app installs one by pushing it
# through ``POST /api/firmware`` and then naming it in 0x2076_0, not by
# writing properties out of it (``PanelConnectivity.OnSaveChanges``).
PRESET_DIRECTORIES = ("TCPPresets", "RTUPresets", "BackofficePresets")
SETTINGS_EXTENSIONS = (".xml", ".iip", ".json")
BACKOFFICE_EXTENSIONS = (".fwi", ".fwu", ".tfw", ".tcf")
PRESET_EXTENSIONS = SETTINGS_EXTENSIONS + BACKOFFICE_EXTENSIONS
METER_MAP_EXTENSION = ".json"

# Each backoffice preset is published once per encryption key, as a trailing
# ``-A``/``-B``/``-C`` on the file name (``RemoveTrailingEncryptionKey``).  The
# app picks -B from firmware 4.12.0 and -A below it, and what it writes into
# 0x2076_0 is the name without the marker.
BACKOFFICE_KEY_MARKERS = ("-a", "-b", "-c")
BACKOFFICE_KEY_FLOOR = (4, 12, 0)


@dataclass(frozen=True)
class RemotePreset:
    """One preset file published on the server."""

    name: str
    directory: str
    size: int | None
    modified: datetime | None

    @property
    def stem(self) -> str:
        """The file name without its extension, encryption marker and all."""
        for extension in PRESET_EXTENSIONS:
            if self.name.lower().endswith(extension):
                return self.name[: -len(extension)]
        return self.name

    @property
    def label(self) -> str:
        """The preset's name as the app shows it, and as 0x2076_0 stores it."""
        stem = self.stem
        if self.is_backoffice and stem[-2:].lower() in BACKOFFICE_KEY_MARKERS:
            return stem[:-2]
        return stem

    @property
    def variant(self) -> str | None:
        """Which encryption key this copy carries, when it carries one."""
        stem = self.stem
        if self.is_backoffice and stem[-2:].lower() in BACKOFFICE_KEY_MARKERS:
            return stem[-1].upper()
        return None

    @property
    def is_meter_map(self) -> bool:
        """Whether this is a Modbus register map rather than a settings file."""
        return self.name.lower().endswith(METER_MAP_EXTENSION)

    @property
    def is_backoffice(self) -> bool:
        """Whether this is a blob for /api/firmware rather than a text file."""
        return self.name.lower().endswith(BACKOFFICE_EXTENSIONS)

    @property
    def kind(self) -> str:
        """What the preset configures: its folder, and which of the two kinds."""
        where = {
            "TCPPresets": "Modbus TCP meter",
            "RTUPresets": "Modbus RTU meter",
            "BackofficePresets": "backoffice",
        }.get(self.directory, self.directory)
        if self.is_backoffice:
            return f"{where} preset"
        return f"{where} map" if self.is_meter_map else f"{where} settings"


def list_presets(config: RepoConfig | None = None) -> list[RemotePreset]:
    """Return every preset published in the server's preset folders."""
    config = config or RepoConfig()
    out: list[RemotePreset] = []
    with _connect(config) as ftp:
        for directory in PRESET_DIRECTORIES:
            try:
                entries = _listing(ftp, directory)
            except (OSError, ftplib.Error):
                continue  # a folder this server does not publish
            out.extend(
                RemotePreset(
                    name=item.name,
                    directory=directory,
                    size=item.size,
                    modified=item.modified,
                )
                for item in entries
                if item.name.lower().endswith(PRESET_EXTENSIONS)
            )
    return sorted(out, key=lambda p: (p.directory, p.name.lower()))


def fetch_preset_bytes(preset: RemotePreset, config: RepoConfig | None = None) -> bytes:
    """Download one preset exactly as published."""
    config = config or RepoConfig()
    chunks: list[bytes] = []
    with _connect(config) as ftp:
        ftp.retrbinary(f"RETR {preset.directory}/{preset.name}", chunks.append)
    return b"".join(chunks)


def fetch_preset(preset: RemotePreset, config: RepoConfig | None = None) -> str:
    """Download one preset and return its text (settings XML, or map JSON)."""
    return fetch_preset_bytes(preset, config).decode("utf-8", "replace")


def pick_backoffice_variant(
    presets: Sequence[RemotePreset], firmware: tuple[int, int, int] | None
) -> RemotePreset | None:
    """Choose which copy of a backoffice preset this firmware can decrypt.

    Mirrors ``PanelConnectivity.OnSaveChanges``: -B from 4.12.0 up, -A below
    it, and the unmarked file when neither is published.
    """
    by_variant = {p.variant: p for p in presets}
    wanted = "B" if firmware is not None and firmware >= BACKOFFICE_KEY_FLOOR else "A"
    return by_variant.get(wanted) or by_variant.get(None) or next(iter(presets), None)
