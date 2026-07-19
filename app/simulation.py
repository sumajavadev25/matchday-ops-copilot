"""A lightweight crowd-flow simulation so the control room feels *live*.

Each zone gets a net flow rate (persons/second). Advancing the clock moves
occupancy along that rate and bounces it at the capacity / near-empty bounds,
producing realistic ebb-and-flow instead of a frozen snapshot. `advance` takes
an explicit `now` so it is deterministic and unit-testable — no randomness in
the stepping itself; variety comes from the initial per-zone rates.

The projection (`eta_seconds`) is what makes the copilot *predictive* rather
than reactive: "Gate C fills in ~40s at current inflow", not just "Gate C is
busy now".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import StadiumSnapshot, Zone

# Cap a single step so a long gap between polls can't teleport the crowd.
_MAX_STEP_SECONDS = 20.0
# When a zone fills, model an ops redirect: the crowd is diverted and the count
# drops to this fraction, then climbs again. Keeps every zone rising (so it
# always has a live projection) instead of draining to empty and going quiet.
_RELIEF_LEVEL = 0.55

# Density bands used to pick each zone's opening fill rate (see _initial_rate).
_BUSY_DENSITY = 0.75
_MID_DENSITY = 0.5
# Target time-to-fill per band, in seconds — calibrated so the risk spread
# reads sensibly: near-full zones alarm in seconds, quiet zones stay calm.
_BUSY_FILL_SECONDS = 200.0   # ~3 min
_MID_FILL_SECONDS = 300.0    # ~5 min — predictive risk can escalate to HIGH
_QUIET_FILL_SECONDS = 900.0  # ~15 min — stays NORMAL by projection
# A zone always has *some* remaining headroom to fill, even near capacity.
_MIN_REMAINING_FRACTION = 0.05


def _initial_rate(zone: Zone) -> float:
    """Net inflow (persons/sec) calibrated so the *projection* spreads sensibly:
    near-full zones are ~seconds from capacity, busy zones a couple of minutes,
    quiet zones many minutes (so they don't false-alarm as critical).

    Rate is chosen from a target time-to-fill, so it self-scales to any capacity.
    Deterministic — the same snapshot always yields the same opening dynamics.
    """
    d = zone.density
    remaining = max(zone.capacity - zone.occupancy,
                    zone.capacity * _MIN_REMAINING_FRACTION)
    if d >= _BUSY_DENSITY:
        target = _BUSY_FILL_SECONDS
    elif d >= _MID_DENSITY:
        target = _MID_FILL_SECONDS
    else:
        target = _QUIET_FILL_SECONDS
    return remaining / target


@dataclass
class SimState:
    snapshot: StadiumSnapshot
    rates: dict[str, float] = field(default_factory=dict)
    last_tick: float = 0.0


def new_sim(snapshot: StadiumSnapshot, now: float) -> SimState:
    rates = {z.id: _initial_rate(z) for z in snapshot.zones}
    return SimState(snapshot=snapshot, rates=rates, last_tick=now)


def advance(sim: SimState, now: float) -> None:
    """Step every zone forward to `now`, bouncing at the bounds to make waves."""
    dt = now - sim.last_tick
    if dt <= 0:
        return
    dt = min(dt, _MAX_STEP_SECONDS)
    for zone in sim.snapshot.zones:
        rate = abs(sim.rates.get(zone.id, 0.0))
        occ = zone.occupancy + rate * dt
        if occ >= zone.capacity:
            # Gate filled → ops redirect diverts arrivals; count drops, then climbs.
            occ = zone.capacity * _RELIEF_LEVEL
        sim.rates[zone.id] = rate  # always rising, so a projection always exists
        zone.occupancy = max(0, int(occ))
    sim.last_tick = now


def eta_seconds(occupancy: int, capacity: int, rate: float) -> float | None:
    """Seconds until this zone hits capacity at the current rate, or None."""
    if rate <= 0 or occupancy >= capacity:
        return None
    return (capacity - occupancy) / rate


def etas_for(sim: SimState) -> dict[str, float | None]:
    return {z.id: eta_seconds(z.occupancy, z.capacity, sim.rates.get(z.id, 0.0))
            for z in sim.snapshot.zones}
