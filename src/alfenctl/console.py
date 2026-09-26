"""The console commands the charger accepts through ``POST /api/cmd``.

A catalog, not a transport: sending one is
:meth:`alfenctl.charger.AlfenCharger.send_command`.  It lives here rather
than beside either front end because both list it -- ``alfenctl console``
and the web UI's Actions tab -- and a command string documented in one and
not the other is a command string that is wrong in one of them.
"""

from __future__ import annotations

# MyEve 2.3.1 CSCommands (#29352, offset 0x67594a) defines command literals
# sent through POST /api/cmd. Support and authorization vary by firmware.
# Windows also sends `date`; the captured NG910 update log shows `cansync off`.
# The CLI and web console share this catalog; raw `cmd` accepts other text.
CONSOLE_COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("Erase Config", "eepromx erase config", "erase settings"),
    ("Erase Transactions", "txerase", "erase transactions"),
    ("Erase Charging Profiles", "cperase", ""),
    ("Erase Log Lines", "log-erase", ""),
    ("Erase Local List", "llerase", ""),
    ("Dump Local List", "lldump", ""),
    ("Erase White List", "wlerase", ""),
    ("Dump White List", "wldump", ""),
    ("Force Firmware Permanent", "forcefirmwarepermanent", ""),
    ("Restart the station", "reboot", "reboot"),
    ("Run All Tests", "test all", ""),
    ("Tamper detection On", "tamper ON", ""),
    ("Tamper detection Off", "tamper OFF", ""),
    ("Show Connected Meter Types", "metertype", ""),
    ("Erase Display Memory", "disp erase", ""),
    ("Show Debug On Display", "disp debug", ""),
    ("Show SCN Info", "scninfo", ""),
    ("Restart Modem (if applicable)", "modemrestart", ""),
    ("Show Flash Memory Info", "flash-info", ""),
    ("Dump Flash Memory (Caution!)", "flash-dump", ""),
    ("Set the clock", "date <yyyy-mm-dd hh:mm:ss>", "time sync"),
    ("Stop the CAN clock sync", "cansync off", ""),
)


CONSOLE_UNKNOWN_NOTE = (
    "This catalog contains command strings documented in vendor clients or "
    "an NG910 log. Support and authorization depend on the firmware. MyEve "
    "restricts advanced choices to the station's Secure Service Access (SSA) "
    "login role, separate from owner/admin access. In reported NG910-60027 "
    "operation, flash-info and flash-dump produced no observable action or "
    "log output. HTTP success acknowledges submission rather than execution; "
    "inspect the charger log for command output. Dumps may contain sensitive "
    "data, and erase, test, reset, and tamper commands can disrupt charging "
    "or configuration."
)


__all__ = ["CONSOLE_COMMANDS", "CONSOLE_UNKNOWN_NOTE"]
