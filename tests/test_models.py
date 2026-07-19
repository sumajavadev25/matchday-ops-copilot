"""Model-level edge cases — especially the density divide-by-zero guard."""
import pytest
from pydantic import ValidationError

from app.models import Incident, IncidentType, Zone


def test_density_normal():
    assert Zone(id="z", name="Z", capacity=1000, occupancy=800).density == 0.8


def test_density_zero_capacity_with_people_is_maxed():
    # A zone with no declared capacity but holding people must not divide by zero,
    # and should read as maximally risky rather than crash or return 0.
    assert Zone(id="z", name="Z", capacity=0, occupancy=50).density == 1.0


def test_density_zero_capacity_empty_is_zero():
    assert Zone(id="z", name="Z", capacity=0, occupancy=0).density == 0.0


def test_density_over_capacity_allowed():
    # Over-crowding is real; density can exceed 1.0.
    assert Zone(id="z", name="Z", capacity=100, occupancy=150).density == 1.5


def test_negative_occupancy_rejected():
    with pytest.raises(ValidationError):
        Zone(id="z", name="Z", capacity=100, occupancy=-1)


def test_empty_id_rejected():
    with pytest.raises(ValidationError):
        Zone(id="", name="Z", capacity=100, occupancy=1)


def test_incident_severity_bounds():
    with pytest.raises(ValidationError):
        Incident(id="i", type=IncidentType.MEDICAL, zone_id="z", severity=6)
    with pytest.raises(ValidationError):
        Incident(id="i", type=IncidentType.MEDICAL, zone_id="z", severity=0)


def test_density_exactly_at_capacity_is_one():
    assert Zone(id="z", name="Z", capacity=1000, occupancy=1000).density == 1.0


def test_occupancy_implausibly_large_rejected():
    with pytest.raises(ValidationError):
        Zone(id="z", name="Z", capacity=1000, occupancy=2_000_000)


def test_negative_capacity_rejected():
    with pytest.raises(ValidationError):
        Zone(id="z", name="Z", capacity=-1, occupancy=0)


def test_incident_defaults_resolved_false_and_blank_description():
    inc = Incident(id="i", type=IncidentType.CROWD, zone_id="z", severity=2)
    assert inc.resolved is False
    assert inc.description == ""


def test_incident_type_accepts_all_enum_values():
    for t in IncidentType:
        inc = Incident(id="i", type=t, zone_id="z", severity=1)
        assert inc.type == t


def test_incident_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Incident(id="i", type="earthquake", zone_id="z", severity=1)


def test_snapshot_defaults_to_empty_lists():
    from app.models import StadiumSnapshot
    snap = StadiumSnapshot()
    assert snap.zones == [] and snap.incidents == []


def test_zone_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        Zone(id="z", name="Z", capacity=1000)  # occupancy missing
