"""Crowd-flow simulation: deterministic stepping, projections, bounces."""
from app.models import StadiumSnapshot, Zone
from app.simulation import advance, eta_seconds, etas_for, new_sim


def snap(occ, cap=1000, id="a"):
    return StadiumSnapshot(zones=[Zone(id=id, name=id.upper(), capacity=cap, occupancy=occ)])


def test_eta_basic():
    assert eta_seconds(500, 1000, 10) == 50.0


def test_eta_none_when_not_rising_or_full():
    assert eta_seconds(500, 1000, 0) is None
    assert eta_seconds(500, 1000, -5) is None
    assert eta_seconds(1000, 1000, 10) is None


def test_new_sim_assigns_positive_rates():
    sim = new_sim(snap(300), now=0)
    assert sim.rates["a"] > 0  # a quiet zone should be filling


def test_advance_moves_occupancy_along_rate():
    sim = new_sim(snap(500), now=0)
    sim.rates["a"] = 10  # +10/sec
    advance(sim, now=10)
    assert sim.snapshot.zones[0].occupancy == 600


def test_advance_caps_a_long_step():
    sim = new_sim(snap(500), now=0)
    sim.rates["a"] = 10
    advance(sim, now=10_000)  # huge gap must not teleport the crowd
    # capped at _MAX_STEP_SECONDS (20) → +200
    assert sim.snapshot.zones[0].occupancy == 700


def test_advance_redirect_relief_at_capacity():
    sim = new_sim(snap(950, cap=1000), now=0)
    sim.rates["a"] = 100  # will overshoot capacity in 1s
    advance(sim, now=1)
    assert sim.snapshot.zones[0].occupancy == 550  # redirected down to 55%
    assert sim.rates["a"] > 0                       # still rising (has a projection)


def test_advance_no_op_when_time_does_not_move():
    sim = new_sim(snap(500), now=5)
    advance(sim, now=5)
    assert sim.snapshot.zones[0].occupancy == 500


def test_etas_for_returns_entry_per_zone():
    sim = new_sim(StadiumSnapshot(zones=[
        Zone(id="a", name="A", capacity=1000, occupancy=500),
        Zone(id="b", name="B", capacity=1000, occupancy=990),
    ]), now=0)
    etas = etas_for(sim)
    assert set(etas) == {"a", "b"}


def test_advance_is_additive_across_steps():
    sim = new_sim(snap(500), now=0)
    sim.rates["a"] = 5
    advance(sim, now=4)   # +20 -> 520
    advance(sim, now=8)   # +20 -> 540
    assert sim.snapshot.zones[0].occupancy == 540


def test_eta_shrinks_as_a_zone_fills():
    sim = new_sim(snap(200, cap=1000), now=0)
    sim.rates["a"] = 10
    before = etas_for(sim)["a"]
    advance(sim, now=10)  # +100
    after = etas_for(sim)["a"]
    assert after < before


def test_rate_is_constant_until_a_bounce():
    sim = new_sim(snap(300), now=0)
    sim.rates["a"] = 7
    advance(sim, now=5)
    assert sim.rates["a"] == 7  # unchanged while still below capacity


def test_quiet_zone_fills_slower_than_busy_zone():
    quiet = new_sim(snap(100, cap=1000), now=0).rates["a"]   # 10% full
    busy = new_sim(snap(900, cap=1000), now=0).rates["a"]    # 90% full
    # A near-full zone is deliberately given a lower absolute inflow so its
    # projection reads in seconds, not so fast everything alarms at once.
    assert busy < quiet


def test_new_sim_records_start_time():
    sim = new_sim(snap(500), now=42.0)
    assert sim.last_tick == 42.0
