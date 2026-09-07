"""How the backend's dataclasses reach the browser.

One place for the JSON the UI consumes, kept apart from the CLI's own
``--json`` output: that one is a user-facing format we should not break,
this one is an internal contract between two halves of the same program.
Keys are camelCase because they are read as JavaScript.

Absent readings stay in the document as ``null`` rather than being dropped,
so the UI can render a steady row of fields with an em dash where the
charger said nothing, instead of the layout changing shape between polls.
"""

from datetime import datetime
from typing import Any

from alfenctl import (
    authorization as auth_mod,
    charging_profiles,
    doctor,
    loadbalancing as lb_mod,
    meter_map,
    ocpp as ocpp_mod,
    whitelist,
)
from alfenctl.authorization import Authorization
from alfenctl.charger import ChargerInfo
from alfenctl.charging_profiles import ChargingProfile, DirectStart
from alfenctl.clock import Clock, format_drift, format_offset, format_zone
from alfenctl.controls import (
    MAX_ALARM_TEMPERATURE_C,
    MAX_CURRENT_A,
    MIN_ALARM_TEMPERATURE_C,
    MIN_CHARGE_CURRENT_A,
    MIN_CURRENT_A,
    Controls,
)
from alfenctl.doctor import Finding, Report
from alfenctl.hardware import Hardware
from alfenctl.license import LicenseInfo
from alfenctl.loadbalancing import LoadBalancing
from alfenctl.logo import DisplayInfo
from alfenctl.logs import LogLine
from alfenctl.master_tag import MasterTag
from alfenctl.meter_map import RegisterMap
from alfenctl.network import Network
from alfenctl.ocpp import Ocpp
from alfenctl.repo import Candidate, RemotePreset
from alfenctl.scn import Membership
from alfenctl.secret import Secret
from alfenctl.setup import Setup
from alfenctl.status import Status
from alfenctl.transactions import Session, Totals
from alfenctl.values import Property, format_value
from alfenctl.wifi import Network as WifiNetwork
from alfenctl.whitelist import Tag


def _stamp(when: datetime | None, *, timespec: str = "auto") -> str | None:
    """Render a datetime as ISO-8601, or None.

    The clock's own readings ask for ``seconds``: the charger is set in whole
    seconds anyway, and six digits of microseconds only made the field too
    long for its row.
    """
    return when.isoformat(timespec=timespec) if when is not None else None


def info_json(info: ChargerInfo | None) -> dict[str, Any] | None:
    """Render the charger's identity."""
    if info is None:
        return None
    return {
        "objectId": info.object_id,
        "identity": info.identity,
        "model": info.model,
        "family": info.family,
        "firmware": info.firmware,
        "sockets": info.sockets,
    }


def status_json(status: Status) -> dict[str, Any]:
    """Render a live status snapshot."""
    return {
        "sockets": [
            {
                "number": socket.number,
                "state": socket.main_state,
                "mode3": socket.mode3_state,
                "led": socket.led_state,
                "power": socket.power_state,
            }
            for socket in status.sockets
        ],
        "temperatureC": status.temperature_c,
        "temperatureAlarm": list(status.temperature_alarm),
        "maxStationCurrentA": status.max_station_current_a,
        "maxInstallationCurrentA": status.max_installation_current_a,
        "activeSafeCurrentA": status.active_safe_current_a,
        "voltagesV": status.voltages_v,
        "currentsA": status.currents_a,
        "powersW": status.powers_w,
        "activePowerW": status.active_power_w,
        "energyDeliveredKWh": status.energy_delivered_kwh,
        "energyConsumedKWh": status.energy_consumed_kwh,
    }


def clock_json(clock: Clock | None) -> dict[str, Any] | None:
    """Render the clock, with the drift already put into words."""
    if clock is None:
        return None
    drift = clock.drift()
    return {
        "utc": _stamp(clock.utc, timespec="seconds"),
        "local": _stamp(clock.local, timespec="seconds"),
        "offset": format_offset(clock.offset),
        "zone": format_zone(clock),
        "daylightSavings": clock.daylight_savings,
        "driftSeconds": drift.total_seconds() if drift is not None else None,
        "drift": format_drift(drift),
    }


def setup_json(setup: Setup | None) -> dict[str, Any] | None:
    """Render the installation settings, with uptime and balancing in words."""
    if setup is None:
        return None
    return {
        "latitude": setup.latitude,
        "longitude": setup.longitude,
        "language": setup.language,
        "uptime": setup.format_uptime() or None,
        "loadBalancing": setup.load_balancing_label() or None,
        "smartCharging": setup.smart_charging,
        "priceCurrency": setup.price_currency,
        "priceStart": setup.price_start,
        "pricePerKwh": setup.price_per_kwh,
        "pricePerMinute": setup.price_per_minute,
    }


def controls_json(state: Controls | None) -> dict[str, Any] | None:
    """Render the settings the dashboard can change, with their warnings."""
    if state is None:
        return None
    return {
        "stationMaxCurrentA": state.station_max_a,
        "installationMaxCurrentA": state.installation_max_a,
        "sockets": [
            {"number": number, "maxCurrentA": amps}
            for number, amps in sorted(state.sockets.items())
        ],
        "socketCount": state.socket_count,
        "intensity": state.intensity,
        "autoDim": state.auto_dim,
        "temperatureAlarmLowC": state.temp_alarm_low_c,
        "temperatureAlarmHighC": state.temp_alarm_high_c,
        "minAlarmTemperatureC": MIN_ALARM_TEMPERATURE_C,
        "maxAlarmTemperatureC": MAX_ALARM_TEMPERATURE_C,
        "minCurrentA": MIN_CURRENT_A,
        "maxCurrentA": MAX_CURRENT_A,
        # What the sliders offer, as opposed to what a write will accept:
        # under this a socket does not charge slowly, it does not charge.
        "minChargeCurrentA": MIN_CHARGE_CURRENT_A,
        "warnings": [
            {"short": caveat.short, "detail": caveat.detail}
            for caveat in state.warnings()
        ],
    }


def firmware_json(cand: Candidate) -> dict[str, Any]:
    """One published firmware image, judged against this charger."""
    version = cand.fw.version
    return {
        "name": cand.fw.name,
        "version": ".".join(str(part) for part in version) if version else None,
        "size": cand.fw.size,
        "modified": _stamp(cand.fw.modified),
        "isBundle": cand.fw.is_bundle,
        "matchesModel": cand.matches_model,
        "blocked": cand.blocked,
        "notes": list(cand.notes),
        "warnings": list(cand.warnings),
        "summary": cand.summary,
    }


def client_json(client: dict[str, Any]) -> dict[str, Any]:
    """One watching browser, with its user agent read into something short."""
    return {
        "id": client.get("id"),
        "address": client.get("address") or "",
        "port": client.get("port"),
        "agent": client.get("agent") or "",
        "label": describe_agent(str(client.get("agent") or "")),
        "since": client.get("since"),
    }


# Enough of a user-agent reading to tell two browsers on the same machine
# apart, in the order that matters: Edge and Opera both claim Chrome, Chrome
# claims Safari, and every Android is also a Linux.
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
    ("curl/", "curl"),
)
_SYSTEMS = (
    ("Android", "Android"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Windows", "Windows"),
    ("Macintosh", "macOS"),
    ("CrOS", "ChromeOS"),
    ("X11", "Linux"),
    ("Linux", "Linux"),
)


# Addresses not worth naming: a tab on this machine is the ordinary case.
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def describe_agent(agent: str) -> str:
    """Return a short name for a browser ("Firefox on Linux")."""
    if not agent.strip():
        return "unknown client"
    browser = next((name for token, name in _BROWSERS if token in agent), "")
    system = next((name for token, name in _SYSTEMS if token in agent), "")
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or agent.split()[0][:40]


def name_watchers(clients: list[dict[str, Any]]) -> list[str]:
    """Name the browsers on the stream: one line each, oldest first.

    Two tabs of one browser share a user agent and an address, so they are
    counted together rather than listed twice.  A watcher somewhere else on
    the network is named with the address it came from, which is the part
    that tells it from a tab of my own.  The user agent is a stranger's
    header and these lines are printed to a terminal, so anything
    unprintable in it is dropped.
    """
    counted: dict[str, int] = {}
    for client in clients:
        label = describe_agent(str(client.get("agent") or ""))
        address = str(client.get("address") or "")
        if address and address not in LOOPBACK:
            label = f"{label} at {address}"
        label = "".join(ch for ch in label if ch.isprintable())
        counted[label] = counted.get(label, 0) + 1
    return [
        f"{label} ({count} tabs)" if count > 1 else label
        for label, count in counted.items()
    ]


def hardware_json(hardware: Hardware | None) -> list[dict[str, str]]:
    """Render the hardware rows this charger actually reports."""
    if hardware is None:
        return []
    return [{"label": label, "value": value} for label, value in hardware.rows()]


def display_json(display: DisplayInfo | None) -> dict[str, Any] | None:
    """Render what the charger has for a screen, if it has one.

    Not every station does, and one that does not takes a logo upload and
    quietly does nothing with it -- so the page has to be able to say so
    rather than offering a control that cannot work.
    """
    if display is None:
        return None
    return {
        "present": display.present,
        "width": display.width,
        "height": display.height,
        "source": display.source,
    }


def license_json(
    license_info: LicenseInfo | None, info: ChargerInfo | None
) -> dict[str, Any] | None:
    """Render the licensed features, named -- the locked ones included.

    ``features`` carries every feature this model can have, each with whether
    it is installed, rather than only the installed ones: a block that lists
    what a station has says nothing about what is left of its licence, which
    is most of why anyone opens it.
    """
    if license_info is None:
        return None
    family = (info.family if info else "") or ""
    return {
        "uniqueId": license_info.unique_id,
        "key": license_info.license_key,
        "raw": license_info.features_raw,
        "features": [
            {"name": name, "on": installed}
            for name, installed in license_info.feature_states(
                ahp=family == "AHP", dc=family.startswith("DC")
            )
        ],
        "supported": not (
            license_info.license_key is None
            and license_info.features_raw is None
            and family != "AHP"
        ),
    }


def option_title(prop: Property) -> str:
    """Name what the live value *means*, for an enumerated property.

    ``sysLoadBalancingMode`` reads as ``0``; the catalog knows that 0 is
    "Disabled".  The number is what the charger stores and what a write has
    to send, so it stays the value -- this is the word that goes beside it.
    Comparison is on the text of the value because the EDS writes its option
    values as strings and the charger answers with numbers.
    """
    if not prop.options or prop.value is None:
        return ""
    wanted = str(prop.value).strip()
    for option in prop.options:
        if option.value.strip() == wanted:
            return option.title or ""
    return ""


def property_json(prop: Property) -> dict[str, Any]:
    """One property, with everything the editor needs to render an input.

    ``title`` is what the property is -- the catalog's own words, or this
    program's glossary where the catalog says nothing -- and ``meaning``
    the catalog's words for the value it is holding.  ``known`` says
    whether either had an answer, and ``purpose`` spells out what a row
    whose ``known`` is false wants said out loud: the register's purpose
    is unknown to the EDS, to the vendor's own apps and to this program,
    and the browser badges it rather than printing the id twice and
    calling one of them a name.
    """
    described = prop.title
    return {
        "id": prop.id_str,
        "name": prop.name,
        "title": described,
        "known": prop.known,
        "purpose": "" if prop.known else "purpose unknown",
        "meaning": option_title(prop),
        "value": prop.value,
        "display": format_value(prop, None),
        "type": prop.type_name,
        "typeCode": prop.data_type,
        "unit": prop.unit,
        "writable": prop.writable,
        "category": prop.category,
        "length": prop.length,
        "default": None if prop.definition is None else prop.definition.default,
        "options": [
            {"value": option.value, "title": option.title} for option in prop.options
        ],
    }


def log_json(line: LogLine) -> dict[str, Any]:
    """One log line."""
    return {
        "id": line.id,
        "time": _stamp(line.time),
        "kind": line.kind,
        "text": line.text,
    }


def loadbalancing_json(state: LoadBalancing | None) -> dict[str, Any] | None:
    """Render the load-balancing and solar settings, with the option tables.

    The option tables ride along so a card can offer the vendor app's own
    dropdowns without the browser having to know a second copy of them.
    """
    if state is None:
        return None
    return {
        "modeRaw": state.mode_raw,
        "modeLabel": state.mode_label,
        "static": state.static,
        "active": state.active,
        "maxMeterCurrentA": state.max_meter_current_a,
        "safeCurrentA": state.safe_current_a,
        "phaseRotation": state.phase_rotation,
        "measurementIncludesEv": state.measurement_includes_ev,
        "maxImbalanceA": state.max_imbalance_a,
        "phaseSwitching": state.phase_switching,
        "maxAllowedPhases": state.max_allowed_phases,
        "dataSource": state.data_source,
        "protocol": state.protocol,
        "p1Interface": state.p1_interface,
        "p1Address": state.p1_address,
        "p1Port": state.p1_port,
        "solarMode": state.solar_mode,
        "solarGreenShare": state.solar_green_share,
        "solarComfortW": state.solar_comfort_w,
        "solarBoost": {str(k): v for k, v in state.solar_boost.items()},
        "licensedStatic": state.licensed_static,
        "licensedActive": state.licensed_active,
        "licensedScn": state.licensed_scn,
        "warnings": state.warnings(),
        "options": {
            "protocols": {str(k): v for k, v in lb_mod.PROTOCOLS.items()},
            "dataSources": {str(k): v for k, v in lb_mod.DATA_SOURCES.items()},
            "p1Interfaces": {str(k): v for k, v in lb_mod.P1_INTERFACES.items()},
            "solarModes": {str(k): v for k, v in lb_mod.SOLAR_MODES.items()},
            "phaseRotations": list(lb_mod.PHASE_ROTATIONS),
            "measurementSources": {
                str(k): v for k, v in lb_mod.MEASUREMENT_SOURCES.items()
            },
        },
        "bounds": {
            "minSafeCurrentA": lb_mod.MIN_SAFE_CURRENT_A,
            "maxSafeCurrentA": lb_mod.MAX_SAFE_CURRENT_A,
            "minMeterCurrentA": lb_mod.MIN_METER_CURRENT_A,
            "maxMeterCurrentA": lb_mod.MAX_METER_CURRENT_A,
            "minGreenShare": lb_mod.MIN_GREEN_SHARE,
            "maxGreenShare": lb_mod.MAX_GREEN_SHARE,
            "minComfortW": lb_mod.MIN_COMFORT_W,
            "maxComfortW": lb_mod.MAX_COMFORT_W,
            "allowedPhases": list(lb_mod.ALLOWED_PHASES),
        },
    }


def authorization_json(state: Authorization | None) -> dict[str, Any] | None:
    """Render the authorization settings, with the option tables."""
    if state is None:
        return None
    return {
        "mode": state.mode,
        "plugAndChargeId": state.plug_and_charge_id,
        "whitelistEnabled": state.whitelist_enabled,
        "localListEnabled": state.local_list_enabled,
        "restartAfterOutage": state.restart_after_outage,
        "maxOutageS": state.max_outage_s,
        "remoteTxRequests": state.remote_tx_requests,
        "stopOnInvalidTag": state.stop_on_invalid_tag,
        "abortConcurrent": state.abort_concurrent,
        "connectionTimeoutS": state.connection_timeout_s,
        "authorizationTimeoutS": state.authorization_timeout_s,
        "onlineAction": state.online_action,
        "offlineAction": state.offline_action,
        "warnings": state.warnings(),
        "options": {
            "modes": {str(k): v for k, v in auth_mod.MODES.items()},
            "offlineActions": {str(k): v for k, v in auth_mod.OFFLINE_ACTIONS.items()},
            "onlineActions": {str(k): v for k, v in auth_mod.ONLINE_ACTIONS.items()},
        },
    }


def ocpp_json(state: Ocpp | None) -> dict[str, Any] | None:
    """Render the backoffice connection settings, with the option tables."""
    if state is None:
        return None
    return {
        "backofficeName": state.backoffice_name,
        "connectMethod": state.connect_method,
        "protocol": state.protocol,
        "wiredUrl": state.wired_url,
        "wiredPath": state.wired_path,
        "mobileUrl": state.mobile_url,
        "mobilePath": state.mobile_path,
        "heartbeatS": state.heartbeat_s,
        "heartbeatActualS": state.heartbeat_actual_s,
        "pingPongS": state.ping_pong_s,
        "sendTimeoutS": list(state.send_timeout_s),
        "replyTimeoutS": list(state.reply_timeout_s),
        "sendStationStatus": state.send_station_status,
        "statusMode": state.status_mode,
        "infoNotifications": state.info_notifications,
        "meterIntervalS": state.meter_interval_s,
        "alignedIntervalS": state.aligned_interval_s,
        "txAttempts": state.tx_attempts,
        "txRetryS": state.tx_retry_s,
        "cpoName": state.cpo_name,
        "securityProfile": state.security_profile,
        "proxyEnabled": state.proxy_enabled,
        "proxyAddress": state.proxy_address,
        "proxyUser": state.proxy_user,
        "warnings": state.warnings(),
        "options": {
            "connectMethods": {str(k): v for k, v in ocpp_mod.CONNECT_METHODS.items()},
            "protocols": list(ocpp_mod.PROTOCOLS),
            "securityProfiles": {
                str(k): v for k, v in ocpp_mod.SECURITY_PROFILES.items()
            },
            "statusModes": {str(k): v for k, v in ocpp_mod.STATUS_MODES.items()},
        },
    }


def tag_json(tag: Tag) -> dict[str, Any]:
    """One whitelist entry."""
    return {
        "tag": tag.tag,
        "parent": tag.parent,
        "status": tag.status,
        "statusLabel": whitelist.TAG_STATUSES.get(tag.status, str(tag.status)),
        "expires": tag.expires,
    }


def master_tag_json(state: MasterTag | None) -> dict[str, Any] | None:
    """Render the master-tag state."""
    if state is None:
        return None
    return {"supported": state.supported, "enabled": state.enabled, "tag": state.tag}


def network_json(state: Network | None) -> dict[str, Any] | None:
    """Render the network state, per interface, with the option tables."""
    if state is None:
        return None
    return {
        "hasWifi": state.has_wifi,
        "wifiEnabled": state.wifi_enabled,
        "wifiSsid": state.wifi_ssid,
        "wifiSecurity": state.wifi_security,
        "wifiRssi": state.wifi_rssi,
        "wifiStatus": state.wifi_status,
        "wifiStationStatus": state.wifi_station_status,
        "wifiApEnabled": state.wifi_ap_enabled,
        "wifiApStatus": state.wifi_ap_status,
        "wifiAddress": state.wifi_address,
        "scanObstacle": state.scan_obstacle(),
        "mac": state.mac,
        "wiredAddress": state.wired_address,
        "wiredFixed": state.wired_fixed,
        "wired": state.wired,
        "mobileAddress": state.mobile_address,
        "signalStrength": state.signal_strength,
        "imsi": state.imsi,
        "iccid": state.iccid,
        "apn": state.apn,
        "networkMode": state.network_mode,
        "networkTechnology": state.network_technology,
        "rows": [{"label": k, "value": v} for k, v in state.rows()],
    }


def wifi_network_json(net: WifiNetwork) -> dict[str, Any]:
    """One network the charger's radio can see."""
    return {
        "ssid": net.ssid,
        "signalDbm": net.signal_dbm,
        "signal": net.signal_label,
        "security": net.security,
        "securityLabel": net.security_label,
        "band": net.band,
        "supported": net.supported,
    }


def meter_map_json(regmap: RegisterMap | None) -> dict[str, Any] | None:
    """Render the custom Modbus register map."""
    if regmap is None:
        return None
    return {
        "name": regmap.name,
        "capacity": regmap.capacity,
        "entries": [
            {
                "measurand": entry.measurand,
                "register": entry.register,
                "dataType": entry.data_type,
                "scale": entry.scale,
                "factor": entry.factor,
            }
            for entry in regmap.entries
        ],
        "measurands": list(meter_map.MEASURANDS),
        "dataTypes": list(meter_map.DATA_TYPES),
    }


def session_json(session: Session) -> dict[str, Any]:
    """One charging session, folded from the transaction records."""
    return {
        "socket": session.socket,
        "id": session.transaction_id,
        "start": _stamp(session.start_time, timespec="seconds"),
        "stop": _stamp(session.stop_time, timespec="seconds"),
        "durationS": (
            None if session.duration is None else session.duration.total_seconds()
        ),
        "meterStart": session.start_meter_kwh,
        "meterStop": session.stop_meter_kwh,
        "energyKwh": session.energy_kwh,
        "tag": session.start_tag or session.stop_tag,
        "reason": session.stop_reason,
        "complete": session.complete,
    }


def totals_json(row: Totals) -> dict[str, Any]:
    """One row of a session summary."""
    return {
        "key": row.key,
        "sessions": row.sessions,
        "energyKwh": round(row.energy_kwh, 3),
        "durationS": (None if row.duration is None else row.duration.total_seconds()),
        "averageKwh": row.average_kwh,
        "incomplete": row.incomplete,
        "first": _stamp(row.first, timespec="seconds"),
        "last": _stamp(row.last, timespec="seconds"),
    }


def finding_json(finding: Finding) -> dict[str, Any]:
    """One doctor finding."""
    return {
        "severity": finding.severity,
        "area": finding.area,
        "detail": finding.detail,
        "fix": finding.fix,
    }


def doctor_json(report: Report | None) -> dict[str, Any] | None:
    """Render a whole doctor pass."""
    if report is None:
        return None
    return {
        "findings": [finding_json(f) for f in report.findings],
        "unavailable": report.unavailable,
        "counts": {
            severity: sum(1 for f in report.findings if f.severity == severity)
            for severity in (doctor.ERROR, doctor.WARNING, doctor.NOTE)
        },
    }


def charging_profile_json(profile: ChargingProfile) -> dict[str, Any]:
    """One installed OCPP charging profile, with its schedule in words."""
    return {
        "id": profile.profile_id,
        "connectorId": profile.connector_id,
        "kind": profile.kind,
        "purpose": profile.purpose,
        "stackLevel": profile.stack_level,
        "rateUnit": profile.charging_rate_unit,
        "startSchedule": profile.start_schedule,
        "periods": [
            {"startS": period.start_period_s, "limitA": period.limit_a}
            for period in profile.periods
        ],
        "isUkDefault": profile.is_uk_default,
    }


def direct_start_json(state: DirectStart | None) -> dict[str, Any] | None:
    """Render the charging-profile override state."""
    if state is None:
        return None
    return {
        "overrides": {str(k): v for k, v in state.overrides.items()},
        "randomDelayS": state.random_delay_s,
        "compliantDelayS": charging_profiles.COMPLIANT_RANDOM_DELAY_S,
        "maxDelayS": charging_profiles.MAX_RANDOM_DELAY_S,
    }


def scn_json(membership: Membership | None, peers: Any = None) -> dict[str, Any] | None:
    """Render SCN membership, and (when probed) the network's other members."""
    if membership is None:
        return None
    doc: dict[str, Any] = {
        "inNetwork": membership.in_network,
        "name": membership.name,
        "socketId": membership.socket_id,
        "socketCount": membership.socket_count,
        "alternatingPeriodS": membership.settings.alternating_period_s,
        "totalCurrentA": membership.settings.total_current_a,
        "socketSafeCurrentA": membership.settings.socket_safe_current_a,
        "totalSafeCurrentA": membership.settings.total_safe_current_a,
    }
    if peers is not None:
        doc["peers"] = [
            {
                "objectId": peer.object_id,
                "identity": peer.identity,
                "name": peer.membership.name,
                "socketId": peer.membership.socket_id,
                "ownSockets": peer.own_sockets,
            }
            for peer in peers
        ]
    return doc


def preset_json(preset: RemotePreset) -> dict[str, Any]:
    """One preset published on Alfen's server."""
    return {
        "name": preset.name,
        "label": preset.label,
        "kind": preset.kind,
        "modified": (preset.modified.strftime("%Y-%m-%d") if preset.modified else None),
        "isBackoffice": preset.is_backoffice,
        "isMeterMap": preset.is_meter_map,
    }


def secret_json(item: Secret) -> dict[str, Any]:
    """One installable write-only secret."""
    return {
        "name": item.name,
        "summary": item.summary,
        "takesFile": item.takes_file,
        "verified": item.verified,
    }


def console_command_json(what: str, wire: str, own: str) -> dict[str, Any]:
    """One known console command, from the maintenance table."""
    return {"what": what, "command": wire, "alfenctl": own}
