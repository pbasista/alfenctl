"""Tilt-sensor calibration: teach the charger which position is upright.

A pedestal charger has an accelerometer so it can report being knocked over
or leaned on.  What counts as upright is not a constant but three stored
setpoints, and the app's *Calibrate Tilt Sensor* button (``PanelAlerts
.OnCalibrateClicked``) sets them by copying the sensor's live reading:

======  ===============================  ======  =============================
0x2207  sensAccelerometerValueX (live)   0x2210  sensAccelerometerSetpointX
0x2208  sensAccelerometerValueY          0x2211  sensAccelerometerSetpointY
0x2209  sensAccelerometerValueZ          0x2212  sensAccelerometerSetpointZ
======  ===============================  ======  =============================

So calibration means exactly this: whatever position the charger is in right
now becomes its definition of level, and tilt alarms are measured from
there.  It follows that it is only meaningful once the station is installed
and standing as it will stand -- which is why the CLI asks before writing.
"""

from __future__ import annotations

from dataclasses import dataclass

from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError
from alfenctl.values import as_int

P_VALUES = ((0x2207, 0), (0x2208, 0), (0x2209, 0))  # live X, Y, Z
P_SETPOINTS = ((0x2210, 0), (0x2211, 0), (0x2212, 0))  # stored X, Y, Z
AXES = ("X", "Y", "Z")


class TiltError(AlfenError):
    """The charger has no tilt sensor to calibrate."""


@dataclass(frozen=True)
class Tilt:
    """The sensor's live reading and the position stored as upright."""

    values: tuple[int, int, int]
    setpoints: tuple[int | None, int | None, int | None]

    @property
    def calibrated(self) -> bool:
        """Whether the stored position already matches what the sensor reads."""
        return tuple(self.values) == tuple(self.setpoints)


def read(charger: AlfenCharger) -> Tilt:
    """Read the live accelerometer and its setpoints, or raise :class:`TiltError`."""
    live = {
        lp.key: lp.value
        for lp in charger.fetch_properties_by_ids([*P_VALUES, *P_SETPOINTS])
    }
    x, y, z = (as_int(live.get(key)) for key in P_VALUES)
    if x is None or y is None or z is None:
        raise TiltError("this charger does not report a tilt sensor")
    sx, sy, sz = (as_int(live.get(key)) for key in P_SETPOINTS)
    return Tilt(values=(x, y, z), setpoints=(sx, sy, sz))


def calibrate(charger: AlfenCharger, tilt: Tilt) -> None:
    """Store the sensor's current reading as the upright position."""
    charger.write_properties(
        {key: (value, None) for key, value in zip(P_SETPOINTS, tilt.values)}
    )
