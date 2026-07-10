"""CSV ingestion edge cases — the jury uploads real data, so parsing must be
robust to messy headers, bad rows, and missing columns."""
from app.data import parse_incidents_csv, parse_zones_csv, seed_snapshot


def test_seed_snapshot_shape():
    snap = seed_snapshot()
    assert len(snap.zones) == 6
    assert any(i.type.value == "medical" for i in snap.incidents)


def test_parse_clean_zones():
    csv = "id,name,capacity,occupancy\ngate-a,Gate A,5000,4900\ngate-b,Gate B,5000,1000\n"
    r = parse_zones_csv(csv)
    assert r.zones_loaded == 2
    assert r.errors == []


def test_parse_tolerates_messy_headers_and_whitespace():
    csv = " ID , Name , Capacity , Occupancy \n gate-a , Gate A , 5000 , 4900 \n"
    r = parse_zones_csv(csv)
    assert r.zones_loaded == 1
    assert r.snapshot.zones[0].id == "gate-a"


def test_parse_missing_required_column_reports_error():
    csv = "id,name,capacity\ngate-a,Gate A,5000\n"
    r = parse_zones_csv(csv)
    assert r.zones_loaded == 0
    assert any("occupancy" in e for e in r.errors)


def test_parse_bad_row_reported_but_others_survive():
    csv = "id,name,capacity,occupancy\ngate-a,Gate A,5000,4900\ngate-b,Gate B,not_a_number,1000\n"
    r = parse_zones_csv(csv)
    assert r.zones_loaded == 1  # good row survived
    assert len(r.errors) == 1
    assert "row 3" in r.errors[0]


def test_parse_empty_csv():
    r = parse_zones_csv("")
    assert r.zones_loaded == 0
    assert r.errors  # missing-columns error, not a crash


def test_parse_optional_lat_lng():
    csv = "id,name,capacity,occupancy,lat,lng\ng,G,100,50,40.8,-74.0\n"
    r = parse_zones_csv(csv)
    assert r.snapshot.zones[0].lat == 40.8


def test_parse_float_counts_coerced_to_int():
    csv = "id,name,capacity,occupancy\ng,G,5000.0,4900.0\n"
    r = parse_zones_csv(csv)
    assert r.snapshot.zones[0].occupancy == 4900


def test_incidents_parse_and_skip_bad():
    csv = ("id,type,zone_id,severity\n"
           "i1,medical,gate-a,4\n"
           "i2,not_a_type,gate-a,3\n")
    incs = parse_incidents_csv(csv)
    assert len(incs) == 1
    assert incs[0].type.value == "medical"


def test_incidents_missing_columns_returns_empty():
    assert parse_incidents_csv("id,type\ni1,medical\n") == []
