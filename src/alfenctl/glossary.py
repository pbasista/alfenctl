"""What alfenctl knows about properties the vendor's EDS does not describe.

The bundled ``EDS.xml`` is the vendor's own catalog and it is the authority
on what a property means -- but it is not complete.  A charger answers for
about three times as many properties as the file describes: a 7.4.5 NG910
returns 311 and the EDS names 93 of them.  The rest arrived in the property
browser as an id, an id again where the name should be, and a number.

The gaps are filled here from three vendor sources, each reverse-engineered
in this repo's ``research/`` directory (a step-by-step guide and the
findings per source, next to ``alfenctl`` itself):

* the Windows installer's own code -- its panels read every property by
  decimal id (``8273`` is ``0x2051``), and the tooltip file it ships is the
  vendor's own id->label catalog
  (``research/windows/windows-findings.md``);
* the My Eve Android app, whose React Native bundle embeds a complete
  745-entry id->display-name dictionary (plus, for each entry, the value
  ranges the app validates and the enumerations it decodes) -- 198 of its
  entries are named by nothing else and make up the last block below
  (``research/android/android-findings.md``);
* the alfen_wallbox Home Assistant integration, whose wiki reproduces the
  charger's OD_* parameter names and whose sensors name the ones it reads
  (``research/home-assistant/ha-findings.md``).

Wherever two of them disagree the Windows app wins: it is the program this
tool is a re-implementation of.  Titles below are the vendor's own words
(matches are spelled as the Windows app spells them), with two exceptions
noted inline: the Modbus TCP port subs (``2522_5``/``2523_5``), which no
source names but whose sibling layout and live value (502, the one and
only Modbus TCP port) leave nothing else they can be.  Three properties --
``3251_0``, ``3253_0`` and ``3295_0`` -- are named by no source at all, so
they stay out of this table and every front end marks them *purpose
unknown*: the property browser badges the row, the CLI table prints ``?``
in the TITLE column, and both JSON shapes carry ``known: false``.  A
made-up name for a register that reconfigures a charger is worse than no
name at all.

The first block below predates the mining and keeps its stricter rule:
entries this program's own modules read deliberately, titled as those
modules call them.  They are kept because their titles are the ones the
app's own panels use as well.  The last block is the opposite end: names
only My Eve has.

Several objects are whole families whose sub-indices share a shape -- the
four meter blocks, the four network profiles, the LED colour table -- so
they are generated from one table each rather than written out, which is
also why adding a sub-index there names it on every member at once.
"""

from __future__ import annotations

# A whole object whose sub-indices share a shape: the title takes the
# sub-index, the same way the app's per-socket panels do.
_SOCKET_STATE_SUBS = {
    1: "main state",
    2: "LED state",
    3: "power/relay state",
    4: "Mode 3 pilot state",
}

# The OCPP "meter values sampled data" / "aligned data" selectors, subs 1-9
# (the app builds the same nine rows in its Connectivity panel).
_METER_VALUE_SUBS = range(1, 10)

# One entry per LED state the charger can light: 0x23xx holds the color and
# blink timing for state xx (ELEDStates; PanelInterface's LED page lists
# exactly these, and My Eve's dictionary names the same slots).
_LED_STATES = {
    0x00: "Unknown",
    0x01: "Off",
    0x02: "Booting",
    0x03: "Check Mains",
    0x04: "Available",
    0x05: "Authorizing",
    0x06: "Authorized",
    0x07: "Cable Connected",
    0x08: "EV Connected",
    0x09: "Preparing Charging",
    0x10: "Wait Vehicle Charging",
    0x11: "Charging Normal",
    0x12: "Charging Simplified",
    0x13: "Suspended Over-Current",
    0x14: "Suspended HF Switching",
    0x15: "Suspended EV Disconnected",
    0x16: "Finish Wait Vehicle",
    0x17: "Finish Wait Disconnect",
    0x18: "Error Protective Earth",
    0x19: "Power-line Fault",
    0x20: "Contactor Fault",
    0x21: "Error Charging",
    0x22: "Power Failure",
    0x23: "Error Temperature",
    0x24: "Illegal CP Value",
    0x25: "Illegal PP Value",
    0x26: "Too Many Restarts",
    0x27: "Error",
    0x28: "Error Message",
    0x29: "Not Authorised",
    0x30: "Cable Not Supported",
    0x31: "S2 Not Opened",
    0x32: "Time-out",
    0x33: "Reserved",
    0x34: "In Operative",
    0x35: "Load Balancing Limited",
    0x36: "Load Balancing Forced Off",
    # The last two are outside the range the app's LED page enumerates
    # (0x2300-0x2336); only My Eve's dictionary names them.
    0x38: "Inactive",
    0x50: "Heartbeat",
}

# One measurand per sub-index, in the order of the vendor's EnergyMeterMeasurand
# enum offset by three (the app's Monitoring/Meter values panels and My Eve's
# dictionary agree on the layout; the EDS's own subs for this block are stale).
_METER_SUBS = {
    0x03: "Voltage L1-N (V)",
    0x04: "Voltage L2-N (V)",
    0x05: "Voltage L3-N (V)",
    0x06: "Voltage L1-L2 (V)",
    0x07: "Voltage L2-L3 (V)",
    0x08: "Voltage L3-L1 (V)",
    0x09: "Current N (A)",
    0x0A: "Current L1 (A)",
    0x0B: "Current L2 (A)",
    0x0C: "Current L3 (A)",
    0x0D: "Current Sum (A)",
    0x0E: "Cos phi L1",
    0x0F: "Cos phi L2",
    0x10: "Cos phi L3",
    0x11: "Cos phi Sum",
    0x12: "Frequency (Hz)",
    0x13: "Active Power L1 (kW)",
    0x14: "Active Power L2 (kW)",
    0x15: "Active Power L3 (kW)",
    0x16: "Active Power Total (kW)",
    0x17: "Apparent Power L1 (kVA)",
    0x18: "Apparent Power L2 (kVA)",
    0x19: "Apparent Power L3 (kVA)",
    0x1A: "Apparent Power Total (kVA)",
    0x1B: "Reactive Power L1 (kvar)",
    0x1C: "Reactive Power L2 (kvar)",
    0x1D: "Reactive Power L3 (kvar)",
    0x1E: "Reactive Power Total (kvar)",
    0x1F: "Energy Delivered L1 (kWh)",
    0x20: "Energy Delivered L2 (kWh)",
    0x21: "Energy Delivered L3 (kWh)",
    0x22: "Energy Delivered Total (kWh)",
    0x23: "Energy Consumed L1 (kWh)",
    0x24: "Energy Consumed L2 (kWh)",
    0x25: "Energy Consumed L3 (kWh)",
    0x26: "Energy Consumed Total (kWh)",
    0x27: "Energy Apparent L1 (kVAh)",
    0x28: "Energy Apparent L2 (kVAh)",
    0x29: "Energy Apparent L3 (kVAh)",
    0x2A: "Energy Apparent Total (kVAh)",
    0x2B: "Energy Reactive L1 (kvarh)",
    0x2C: "Energy Reactive L2 (kvarh)",
    0x2D: "Energy Reactive L3 (kvarh)",
    0x2E: "Energy Reactive Total (kvarh)",
}

# Which meter a block belongs to: the id the app's own helpers pass around
# (AddVoltages/AddCurrents/AddNetQuality, and My Eve's names).
_METER_NAMES = {
    0x2221: "Socket 1",
    0x3221: "Socket 2",
    0x4221: "Central meter",
    0x5221: "Smart meter",
}

# The CP/PP diagnostic block per socket: sub 0 = CP voltage high, 1 = CP
# voltage low, 2 = PP resistance, 3 = PWM duty cycle (PanelMonitoring's
# AddMode3Signals, tooltips socket1_CP_PP_*).
_CP_PP_SUBS = (
    "CP voltage high (V)",
    "CP voltage low (V)",
    "PP resistance (Ω)",
    "PWM duty cycle (%)",
)

# The network-profile block, 0x20F0-0x20F3, one profile per object: the
# app's ENPSubIds enum, spelled as its Connectivity panel spells them.
_NETWORK_PROFILE_SUBS = {
    1: "OCPP protocol",
    3: "CSMS URL",
    4: "websocket timeout (s)",
    5: "security profile",
    6: "connect method",
    7: "APN name",
    8: "APN user (deprecated)",
    9: "APN password",
    0xA: "SIM pin (deprecated)",
    0xB: "preferred network",
    0xC: "use preferred network only",
    0xD: "APN authentication",
    0xE: "priority",
    0xF: "APN name",
    0x10: "SIM pin",
}

# The Modbus TCP/IP meter config pair, 0x2522 (central) and 0x2523 (smart):
# MbusTCP1/MbusTCP2 in the app and My Eve, subs as both spell them.
_MODBUS_TCP_SUBS = {
    1: "enabled",
    2: "meter type",
    3: "connection type",
    4: "IP address",
    5: "port",  # no source names it; 502 is Modbus TCP's only port
    6: "slave address",
}

# The Modbus RTU/serial meter config, 0x2564-0x2565 for the central meter
# (word order, update/read timing, function code, then baudrate/parity/
# address -- the app's Modbus RTU category, and My Eve's names).
# The central-meter register-map arrays, 0x2560-0x2563, mirror the smart
# meter's 0x2570-0x2573 (ICUModbusRegmap reads both blocks with the same
# four-property shape).

# (property id, sub index) -> the vendor's own title for it.
TITLES: dict[tuple[int, int], str] = {
    # --- properties this program reads deliberately, named as its modules
    # --- call them (and as the app's panels call them too).
    (0x205E, 0): "Number of Sockets",
    (0x204D, 1): "Controller Board Revision",
    (0x204D, 2): "Controller Board Assembly",
    (0x204D, 3): "Power Board Revision",
    (0x204D, 4): "Power Board Assembly",
    # The license trio the dashboard's License card shows: the app's
    # DlgUnlockFeature dialog reads all three (Windows tooltip 21A1_00 =
    # "Feature license key"), and this program's license module calls
    # them unique id, key and features.
    (0x21A0, 0): "License Unique ID",
    (0x21A1, 0): "License Key",
    (0x21A2, 0): "Unlocked Features",
    (0x2118, 0): "Modem Manufacturer",
    (0x2119, 0): "Modem Model",
    (0x2120, 0): "Modem Revision",
    (0x2121, 0): "Modem IMEI",
    (0x3180, 0): "NFC Reader 1 Version",
    (0x3181, 0): "NFC Reader 2 Version",
    (0x3182, 0): "Controller Board Bootloader",
    **{(0x2501, sub): f"Socket 1 {name}" for sub, name in _SOCKET_STATE_SUBS.items()},
    **{(0x2502, sub): f"Socket 2 {name}" for sub, name in _SOCKET_STATE_SUBS.items()},
    (0x2180, 1): "SCN Network Name",
    (0x2180, 2): "SCN Socket ID",
    (0x2180, 3): "SCN Socket Count",
    (0x2180, 4): "SCN Alternating Period",
    (0x2180, 5): "SCN Total Maximum Current",
    (0x2180, 6): "SCN Socket Safe Current",
    (0x2180, 10): "SCN Total Safe Current",
    (0x2400, 1): "Master Tag Enabled",
    (0x2400, 2): "Master Tag",
    (0x2570, 0): "Smart Meter Measurands",
    (0x2571, 0): "Smart Meter Registers",
    (0x2572, 0): "Smart Meter Register Data Types",
    (0x2573, 0): "Smart Meter Register Scale Factors",
    (0x2523, 2): "Modbus TCP/IP Slave Balancing Mode",
    (0x3260, 0): "Display Descriptor",
    (0x3260, 3): "Display Logo Width",
    (0x3260, 4): "Display Logo Height",
    # --- the rest: named by the vendor's own apps (see the module docstring).
    # Windows tooltip "General"/"Power settings" and ICUConfig "Charge Box
    # Configuration"; a bitmask: bits 0-1 phases (0=1F, 2=3F), 0x30 cable.
    (0x204F, 0): "Charge Point Configuration",
    (0x205D, 0): "Display Language",
    (0x205F, 0): "Socket Status Flags",
    (0x2060, 0): "System uptime",
    (0x2063, 0): "Plug & charge ID",
    # Nuvve vehicle-to-grid support (tooltip OD_sysNuvveSupport.*).
    (0x206B, 1): "Nuvve Enabled",
    (0x206B, 2): "Nuvve Interval (s)",
    (0x206B, 3): "Nuvve Threshold (W)",
    # OCPP message timing (tooltip OD_commRpcConnectTimeout/ReplyTimeout).
    (0x208D, 1): "Wired OCPP send timeout (s)",
    (0x208D, 2): "Mobile OCPP send timeout (s)",
    (0x208E, 1): "Wired OCPP reply timeout (s)",
    (0x208E, 2): "Mobile OCPP reply timeout (s)",
    # Transaction-message retrying (tooltip OD_commTransactionMessage*).
    (0x2096, 0): "Transaction message attempts",
    (0x2097, 0): "Transaction message retry interval (s)",
    (0x209B, 0): "Remote transaction requests",
    (0x209C, 0): "Status notification method",
    (0x209D, 0): "Send always heartbeat",
    # 0x209E: a bitmask of the radio access technologies the modem supports
    # (ICULanDevice.SupportsRats); 0x209F: the one in use.
    (0x209E, 0): "Supported mobile technologies (bitmask)",
    (0x209F, 0): "Mobile technology (RAT)",
    # The OCPP meter-value selectors, subs 1-9 (tooltip SampledData_1..9,
    # AlignedData_1..9; each holds an OCPP measurand+phase code).
    **{(0x2098, sub): f"Sampled data {sub}" for sub in _METER_VALUE_SUBS},
    **{(0x2099, sub): f"Aligned data {sub}" for sub in _METER_VALUE_SUBS},
    (0x209A, 0): "Clock aligned data interval (s)",
    # Smart Charging Mode (My Eve; a sibling of sysLoadBalancingMode).
    (0x2065, 1): "Smart Charging Mode Enabled",
    # Display pricing block (tooltip OD_dispDisplayPricing.*; the app's
    # Interface panel edits the same subs).
    (0x3262, 1): "Pricing currency",
    (0x3262, 2): "Start price",
    (0x3262, 3): "Price per kWh",
    (0x3262, 4): "Price per minute",
    (0x3262, 5): "Show price components",
    (0x3262, 6): "Other price",
    (0x3262, 7): "Other price name",
    # Network profiles 1-4, one object each (ENPSubIds; sub 8/0xA are the
    # short APN user/SIM pin slots from before the extended lengths).
    **{
        (0x20F0 + n, sub): f"Network Profile {n + 1}: {title}"
        for n in range(4)
        for sub, title in _NETWORK_PROFILE_SUBS.items()
    },
    # Proxy for the wired back-office connection (tooltip OD_proxy*).
    (0x2115, 0): "Proxy domain and port",
    (0x2116, 0): "Proxy user name",
    (0x2117, 0): "Proxy enabled",
    (0x2124, 0): "Send informational notifications",
    # P1 (DSMR) smart-meter interface: status block 0x212E and per-phase
    # currents 0x212F (My Eve; HA exposes the same as P1 Meter sensors).
    (0x212E, 1): "P1 read status",
    (0x212E, 2): "P1 version",
    (0x212E, 3): "P1 timestamp",
    (0x212F, 1): "P1 Meter Phase 1 Current (A)",
    (0x212F, 2): "P1 Meter Phase 2 Current (A)",
    (0x212F, 3): "P1 Meter Phase 3 Current (A)",
    # LED/heartbeat (tooltip OD_mainLEDHeartBeat*).
    (0x2171, 0): "Heart beat mode enabled",
    (0x2172, 0): "Heart beat intensity",
    (0x2174, 0): "Maximum imbalance current (A)",
    # External-Meter wiring (My Eve; the boot log confirms the hardware).
    (0x2175, 0): "External Modbus Support",
    (0x2176, 0): "External Modbus Device ID",
    (0x2182, 0): "Random mv clock aligned msg (s)",
    (0x2185, 0): "Allow phase switching",
    (0x2187, 0): "Last time Configuration Changed",
    (0x218E, 0): "Max energy on invalid id",
    # What is limiting the charge current, per socket: a bitmask whose bits
    # My Eve decodes (cable, temperature, phase imbalance, EMS, ...).
    (0x218F, 1): "Limiting Factors 1",
    (0x218F, 2): "Limiting Factors 2",
    (0x2191, 1): "P1 interface source",
    (0x2191, 2): "P1 interface IP address",
    (0x2191, 3): "P1 interface port",
    (0x2192, 0): "Payment options",
    # Socket-1 meter: pulses per kWh when the meter type is "Pulse"
    # (EDS 0x2218 option 0; My Eve).
    (0x2219, 0): "Socket 1 Pulses per kWh",
    (0x2249, 0): "Maximum measured temperature (°C)",
    (0x2249, 1): "Minimum measured temperature (°C)",
    # The LED color presets, one per state (see _LED_STATES).
    **{(0x2300 + sub, 0): f"LED color: {title}" for sub, title in _LED_STATES.items()},
    # CP/PP diagnostics per socket (tooltip socket1_CP_PP_*/socket2_CP_PP_*).
    **{
        (0x2511 + n, sub): f"Socket {n + 1} {label}"
        for n in range(2)
        for sub, label in enumerate(_CP_PP_SUBS)
    },
    # Central (0x2522) and smart/external (0x2523) Modbus TCP/IP meter.
    **{
        (0x2522, sub): f"Central Modbus TCP/IP: {title}"
        for sub, title in _MODBUS_TCP_SUBS.items()
    },
    **{
        (0x2523, sub): f"Smart Modbus TCP/IP: {title}"
        for sub, title in _MODBUS_TCP_SUBS.items()
    },
    # EMS Modbus balancing (tooltip OD_modbusTCPIPSlave.*; sub 2 is the
    # socket-vs-SCN mode My Eve calls "EMS Socket Balancing").
    (0x2530, 2): "Modbus balancing: EMS socket balancing",
    (0x2530, 3): "Modbus balancing: EMS mode",
    (0x2530, 4): "Modbus command validity time (s)",
    (0x2540, 0): "Modbus TCP/IP connection state",
    # Central-meter register map and RTU wiring (ICUModbusRegmap reads
    # 0x2560-0x2565 with the same shape as the smart-meter block).
    (0x2560, 0): "Central Meter Measurands",
    (0x2561, 0): "Central Meter Registers",
    (0x2562, 0): "Central Meter Register Data Types",
    (0x2563, 0): "Central Meter Register Scale Factors",
    (0x2564, 0): "Central Meter Word Order",
    (0x2564, 1): "Central Meter RTU Update Time",
    (0x2564, 2): "Central Meter RTU Read Timeout",
    (0x2564, 3): "Central Meter RTU Function Code",
    (0x2565, 0): "Central Meter RTU Baudrate",
    (0x2565, 1): "Central Meter RTU Parity",
    (0x2565, 2): "Central Meter RTU Address",
    (0x312E, 0): "Socket 1 max phases",
    (0x312F, 0): "Socket 2 max phases",
    (0x3260, 1): "Display Width (px)",
    (0x3260, 2): "Display Height (px)",
    (0x3260, 5): "Max upload size (bytes)",
    (0x3290, 0): "Wi-Fi access point timeout",
    (0x3600, 1): "OCPP boot notification state",
    (0x3600, 2): "OCPP boot last time sent",
    (0x3600, 3): "OCPP boot accept time",
    (0x3600, 4): "OCPP boot delay",
    (0x3600, 5): "OCPP RPC connected",
    (0x3600, 6): "OCPP heartbeat last received",
    (0x3600, 7): "OCPP heartbeat last failed",
    (0x3600, 8): "OCPP heartbeat last sent",
    (0x5217, 0): "Smart meter protocol selection",
    # --- named only by My Eve's embedded dictionary -----------------------
    # The Android app ships a 745-entry id->name map (recovered from its
    # Hermes bundle; research/android/android-findings.md lists it).  Most of
    # it agrees with the EDS or the block above, which keep precedence; these
    # are the ones no other source names at all.  The wording is the
    # dictionary's own, with two corrections: the four device-state subs,
    # which it gives one name for both the state and its error number, and
    # one "IS015118" written with a zero.
    (0x2068, 0x1): "Socket 1 - Safe Current (A)",
    (0x2068, 0x2): "Socket 2 - Safe Current (A)",
    (0x206A, 0x0): "Minimum Chameleon current (A)",
    (0x208B, 0x1): "Ethernet - websocket timeout (s)",
    (0x208B, 0x2): "Wired - Websocket timeout (s)",
    (0x208F, 0x0): "Meter value sample interval (s)",
    (0x2095, 0x0): "Stop transaction on invalid tag",
    (0x2098, 0x0): "Meter values sampled data - Data 0",
    (0x2099, 0x0): "Meter values aligned data - Data 0",
    (0x20F4, 0x0): "Network Profile Connection Attempts",
    (0x2113, 0x0): "Mobile - Network Mode",
    (0x2114, 0x0): "Mobile - Network Technology",
    (0x213C, 0x0): "Online NFC action",
    (0x213D, 0x0): "Local list enabled",
    (0x213E, 0x0): "Offline action - Local list",
    (0x215D, 0x0): "Disable 105 percent overcurrent",
    (0x215E, 0x0): "Restart after Power Outage",
    (0x215F, 0x0): "External Max. Current (A)",
    (0x2160, 0x0): "External Min. Current (A)",
    (0x2161, 0x0): "Active Max. Current (A)",
    (0x2165, 0x1): "DSC 0 - Status",
    (0x2165, 0x2): "DSC 0 - Safe current (A)",
    (0x2165, 0x3): "DSC 0 - Max. current (A)",
    (0x2165, 0x4): "DSC 0 - Valid to",
    (0x2166, 0x1): "DSC 1 - Status",
    (0x2166, 0x2): "DSC 1 - Safe current (A)",
    (0x2166, 0x3): "DSC 1 - Max. current (A)",
    (0x2166, 0x4): "DSC 1 - Valid to",
    (0x2167, 0x1): "DSC 2 - Status",
    (0x2167, 0x2): "DSC 2 - Safe current (A)",
    (0x2167, 0x3): "DSC 2 - Max. current (A)",
    (0x2167, 0x4): "DSC 2 - Valid to",
    (0x2168, 0x0): "Time to unlock not charging (s)",
    (0x2169, 0x0): "Max. Allowed Outage Duration (s)",
    (0x216B, 0x0): "Signed meter values at Interval",
    (0x216D, 0x0): "QR code display time (s)",
    (0x216F, 0x0): "Signed meter values at Start & Stop",
    (0x2173, 0x0): "Socket 1.2 Max current (A)",
    (0x2177, 0x0): "QR URL Socket #1",
    (0x2178, 0x0): "QR URL Socket #2",
    (0x2179, 0x0): "Dynamic QR code enabled",
    (0x2180, 0x8): "SCN - Is unlocked",
    (0x2183, 0x0): "Cover lock enabled",
    (0x2184, 0x0): "Time to report not charging (s)",
    (0x2188, 0x0): "Giro-e ready",
    (0x218A, 0x0): "Tx Start Point",
    (0x218B, 0x0): "Tx Stop Point",
    (0x21A3, 0x0): "ERP Password",
    (0x21B5, 0x0): "Modem Enabled",
    (0x21B6, 0x0): "CS Operational Time",
    (0x21B7, 0x0): "Secure EEProm",
    (0x21B8, 0x0): "Auxiliary Board Information",
    (0x21B9, 0x0): "Charging Profile Max. Random Delay",
    (0x21BA, 0x0): "Auxiliary Board Revision",
    (0x2401, 0x0): "Emergency Services ID",
    (0x2541, 0x0): "Socket 1 public key",
    (0x2542, 0x0): "Socket 2 public key",
    (0x2574, 0x1): "Smart Meter - Update time",
    (0x2574, 0x2): "Smart Meter - Read Timeout",
    (0x2575, 0x2): "Smart Meter - Address",
    (0x2600, 0x0): "Auto Charge - Enabled",
    (0x2720, 0x0): "Certificates Max Chain Length",
    (0x2721, 0x0): "Certificates Max Store Length",
    (0x2722, 0x0): "CPO name",
    (0x2723, 0x0): "Security Profile",
    (0x2724, 0x0): "Max. number of certificates",
    (0x3129, 0x0): "Socket 2 - Max current (A)",
    (0x312A, 0x0): "Socket 2 - External Max. Current (A)",
    (0x312B, 0x0): "Socket 2 - Standard LB Max Current (A)",
    (0x312C, 0x0): "Socket 2 - Active Max Current (A)",
    (0x312D, 0x0): "Socket 2 - Active LB Min Current (A)",
    (0x3160, 0x0): "Socket 2 - External Min. Current (A)",
    (0x3173, 0x0): "Socket 2.2 Max current (A)",
    (0x3190, 0x1): "Socket 1 - Device state",
    (0x3190, 0x2): "Socket 1 - Device state error number",
    (0x3191, 0x1): "Socket 2 - Device state",
    (0x3191, 0x2): "Socket 2 - Device state error number",
    (0x3258, 0x0): "OCPP - Min status duration (s)",
    (0x3263, 0x1): "OCPP - Tariff enabled",
    (0x3263, 0x2): "OCPP - Tariff fallback message",
    (0x3263, 0x3): "OCPP - Cost enabled",
    (0x3263, 0x4): "OCPP - Cost fallback message",
    (0x3263, 0x5): "OCPP - Custom field",
    (0x3264, 0x0): "OCPP - Aligned Transaction Interval",
    (0x3265, 0x0): "OCPP - Offline Threshold",
    (0x3266, 0x0): "OCPP - Message Timeout",
    (0x3267, 0x0): "Local List Entries",
    (0x3269, 0x0): "Local List Bytes per msg",
    (0x3270, 0x0): "Sampled Transaction Interval",
    (0x3271, 0x0): "Sampled Transaction Started Measurands",
    (0x3272, 0x0): "Certificate Entries",
    (0x3273, 0x0): "Rate Units",
    (0x3274, 0x0): "Charging Profile Entries",
    (0x3275, 0x0): "Charging Profile Limit Change",
    (0x3276, 0x1): "OCPP - DataTime",
    (0x3276, 0x2): "OCPP - NTP Server URL",
    (0x3276, 0x3): "OCPP - NTP Source",
    (0x3276, 0x4): "OCPP - Time Offset",
    (0x3276, 0x5): "OCPP - Next Transition DateTime",
    (0x3276, 0x6): "OCPP - Next Transition Offset",
    (0x3276, 0x7): "OCPP - Time Source",
    (0x3276, 0x8): "OCPP - Time Zone",
    (0x3277, 0x1): "OCPP - Items per GetReport Msg",
    (0x3277, 0x2): "OCPP - Items per GetVariables Msg",
    (0x3277, 0x3): "OCPP - Items per SetVariables Msg",
    (0x3277, 0x4): "OCPP - Bytes per GetReport Msg",
    (0x3277, 0x5): "OCPP - Bytes per GetVariables Msg",
    (0x3277, 0x6): "OCPP - Bytes per SetVariables Msg",
    (0x3277, 0x7): "OCPP - Configuration Size",
    (0x3277, 0x8): "OCPP - Reporting size",
    (0x3278, 0x1): "Override Charging Profile Socket 1",
    (0x3278, 0x2): "Override Charging Profile Socket 2",
    (0x3280, 0x1): "Solar - Operation Mode",
    (0x3280, 0x2): "Solar - Green Share",
    (0x3280, 0x3): "Solar - Comfort Level",
    (0x3280, 0x4): "Solar - Override Socket 1",
    (0x3280, 0x5): "Solar - Override Socket 2",
    (0x3286, 0x2): "Wifi - Fixed Netmask",
    (0x3287, 0x2): "Wifi - Fixed Gateway",
    (0x3288, 0x2): "Wifi - Fixed DNS 1",
    (0x3289, 0x2): "Wifi - Fixed DNS 2",
    (0x5230, 0x0): "Register Meter values incl. Phases",
    (0x8006, 0x0): "Display ID - 0 for device without",
    (0x8101, 0x1): "Device ID - Socket Board 1",
    (0x8101, 0x2): "Device ID - Socket Board 2",
    (0x8102, 0x1): "Hardware Version - Socket Board 1",
    (0x8102, 0x2): "Hardware Version - Socket Board 2",
    (0x8103, 0x1): "Software Version - Socket Board 1",
    (0x8103, 0x2): "Software Version - Socket Board 2",
    (0x8107, 0x1): "ISO15118 SW - Socket Board 1",
    (0x8107, 0x2): "ISO15118 SW - Socket Board 2",
    (0x8108, 0x1): "Energy Meter - Socket Board 1",
    (0x8108, 0x2): "Energy Meter - Socket Board 2",
    (0x8109, 0x1): "ISO15118 HW - Socket Board 1",
    (0x8109, 0x2): "ISO15118 HW - Socket Board 2",
    (0x810A, 0x1): "Socket Type - Socket Board 1",
    (0x810A, 0x2): "Socket Type - Socket Board 2",
    (0x8201, 0x0): "Device ID - NFC",
    (0x8202, 0x0): "Hardware version - NFC",
    (0x8203, 0x0): "Software version - NFC",
    (0x8301, 0x0): "DC charger - CS max. current (A)",
    (0x8302, 0x0): "DC charger - Socket 1 max. current (A)",
    (0x8303, 0x0): "DC charger - Socket 2 max. current (A)",
}

# The four live meter blocks (0x2221 socket 1, 0x3221 socket 2, 0x4221
# central, 0x5221 smart meter): one measurand per sub-index.
TITLES.update(
    {
        (meter, sub): f"{_METER_NAMES[meter]}: {title}"
        for meter in _METER_NAMES
        for sub, title in _METER_SUBS.items()
    }
)


def title(key: tuple[int, int]) -> str:
    """Return this program's title for a property key, or ``""``."""
    return TITLES.get(key, "")


__all__ = ["TITLES", "title"]
