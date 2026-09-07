"""Board revisions, sub-device versions and modem details for ``info``.

The app's Information panel shows more than the identity properties: which
revision each board is, what the RFID readers and the modem report about
themselves.  None of it is in the EDS catalog or the category walk, so --
like the license, master-tag and SCN blocks -- it is read by an explicit
``ids=`` query, and a charger that does not answer for a property simply
does not have that part.

Board revision and assembly are small enumerations the app renders as one
string, ``"<revision>-<assembly>"`` (``PanelInformation.ParseRevision``
over ``EBoardRevision``/``EBoardAssy``): revision 3 assembly 4 reads
``C-03``.  The readers report ``"HW:x.y,SW:a.b"``-shaped strings, split the
way ``ICULanDevice.GetNFCVersion`` splits them.

Firmware older than 4.3.0 published the first reader's versions inside
``sysFirmwareVersion`` after a ``#N:`` marker instead; that path is not
reimplemented here, so a very old charger shows no reader line rather than
a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alfenctl.charger import AlfenCharger
from alfenctl.values import as_int

# 0x204D (8269): board revision/assembly, one sub-index per board.
P_CONTROLLER_REVISION = (0x204D, 1)
P_CONTROLLER_ASSEMBLY = (0x204D, 2)
P_POWER_REVISION = (0x204D, 3)
P_POWER_ASSEMBLY = (0x204D, 4)
P_BOOTLOADER = (0x3182, 0)  # 12674, controller board bootloader
P_NFC_READER_1 = (0x3180, 0)  # 12672
P_NFC_READER_2 = (0x3181, 0)  # 12673
P_MODEM_MANUFACTURER = (0x2118, 0)  # 8472
P_MODEM_MODEL = (0x2119, 0)  # 8473
P_MODEM_REVISION = (0x2120, 0)  # 8480
P_MODEM_IMEI = (0x2121, 0)  # 8481

ALL_KEYS = (
    P_CONTROLLER_REVISION,
    P_CONTROLLER_ASSEMBLY,
    P_POWER_REVISION,
    P_POWER_ASSEMBLY,
    P_BOOTLOADER,
    P_NFC_READER_1,
    P_NFC_READER_2,
    P_MODEM_MANUFACTURER,
    P_MODEM_MODEL,
    P_MODEM_REVISION,
    P_MODEM_IMEI,
)

# EBoardRevision / EBoardAssy, by the value the property carries.  Both start
# at "default" (0) and count up; -1 means the board did not say.
BOARD_REVISIONS = "0ABCDEFGHJKLMNPQR"
BOARD_ASSEMBLIES = tuple(["0"] + [f"{n:02d}" for n in range(16)])


@dataclass(frozen=True)
class Hardware:
    """What the charger reports about its own hardware."""

    controller_board: str | None = None
    power_board: str | None = None
    bootloader: str | None = None
    readers: list[str] = field(default_factory=list)  # one line per RFID reader
    modem: str | None = None
    modem_imei: str | None = None

    def rows(self) -> list[tuple[str, str]]:
        """Return the label/value pairs worth printing, skipping what is absent."""
        out: list[tuple[str, str]] = []
        for label, value in (
            ("Controller board", self.controller_board),
            ("Power board", self.power_board),
            ("Bootloader", self.bootloader),
        ):
            if value:
                out.append((label, value))
        for index, reader in enumerate(self.readers, start=1):
            label = "RFID reader" if len(self.readers) == 1 else f"RFID reader {index}"
            out.append((label, reader))
        if self.modem:
            out.append(("Modem", self.modem))
        if self.modem_imei:
            out.append(("Modem IMEI", self.modem_imei))
        return out


def _board(revision: object, assembly: object) -> str | None:
    """Render one board's revision and assembly as the app does ("C-03")."""
    rev, assy = as_int(revision), as_int(assembly)
    if rev is None or assy is None:
        return None
    if not (0 <= rev < len(BOARD_REVISIONS) and 0 <= assy < len(BOARD_ASSEMBLIES)):
        return None  # -1 is "unknown", and anything else is not ours to guess
    return f"{BOARD_REVISIONS[rev]}-{BOARD_ASSEMBLIES[assy]}"


def _reader(raw: object) -> str | None:
    """Render one RFID reader's ``"HW:x,SW:y"`` string as ``"hardware x, software y"``."""
    text = str(raw or "").strip()
    if not text:
        return None
    parts = []
    for field_text, label in zip(text.split(","), ("hardware", "software")):
        _, _, value = field_text.partition(":")
        value = (value or field_text).strip()
        if value:
            parts.append(f"{label} {value}")
    return ", ".join(parts) or text


def read(charger: AlfenCharger) -> Hardware:
    """Read the hardware details, tolerating a charger that reports none."""
    live = {lp.key: lp.value for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    readers = [
        line
        for line in (_reader(live.get(key)) for key in (P_NFC_READER_1, P_NFC_READER_2))
        if line
    ]
    modem = " ".join(
        str(live[key]).strip()
        for key in (P_MODEM_MANUFACTURER, P_MODEM_MODEL, P_MODEM_REVISION)
        if str(live.get(key) or "").strip()
    )
    return Hardware(
        controller_board=_board(
            live.get(P_CONTROLLER_REVISION), live.get(P_CONTROLLER_ASSEMBLY)
        ),
        power_board=_board(live.get(P_POWER_REVISION), live.get(P_POWER_ASSEMBLY)),
        bootloader=str(live.get(P_BOOTLOADER) or "").strip() or None,
        readers=readers,
        modem=modem or None,
        modem_imei=str(live.get(P_MODEM_IMEI) or "").strip() or None,
    )
