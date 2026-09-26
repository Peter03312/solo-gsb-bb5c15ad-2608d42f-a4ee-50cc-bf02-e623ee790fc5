"""Tests for the sustain parsing endpoint, covering the required semantics."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def parse(payload):
    return client.post("/api/v1/parse", json=payload)


def test_simple_note_on_off():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 900, "pitch": 60},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["note_count"] == 1
    note = body["notes"][0]
    assert note["pitch"] == 60
    assert note["on_ms"] == 100
    assert note["release_ms"] == 900
    assert note["end_ms"] == 900
    assert note["end_reason"] == "note_off"


def test_pedal_extends_released_note_until_pedal_up():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 900, "pitch": 60},
            {"type": "pedal_up", "time_ms": 2000},
        ],
    })
    assert resp.status_code == 200
    note = resp.json()["notes"][0]
    assert note["on_ms"] == 100
    assert note["release_ms"] == 900
    assert note["end_ms"] == 2000
    assert note["end_reason"] == "pedal_up"


def test_pedal_up_only_ends_sustained_notes_not_held_keys():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 900, "pitch": 60},   # sustained
            {"type": "note_on", "time_ms": 1000, "pitch": 64},   # still held
            {"type": "pedal_up", "time_ms": 2000},
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert notes[0]["end_ms"] == 2000 and notes[0]["end_reason"] == "pedal_up"
    assert notes[1]["release_ms"] is None
    assert notes[1]["end_ms"] == 5000 and notes[1]["end_reason"] == "end_ms"


def test_same_pitch_repeated_presses_are_independent_and_release_earliest_first():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "note_on", "time_ms": 0, "pitch": 60},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 500, "pitch": 60},   # releases press 0
            {"type": "note_off", "time_ms": 800, "pitch": 60},   # releases press 1
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert [n["press_index"] for n in notes] == [0, 1]
    assert notes[0]["on_ms"] == 0 and notes[0]["end_ms"] == 500
    assert notes[1]["on_ms"] == 100 and notes[1]["end_ms"] == 800
    assert all(n["end_reason"] == "note_off" for n in notes)


def test_note_off_releases_held_press_not_sustained_one():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 0, "pitch": 60},
            {"type": "note_off", "time_ms": 100, "pitch": 60},   # press 0 -> sustained
            {"type": "note_on", "time_ms": 200, "pitch": 60},    # press 1, held
            {"type": "note_off", "time_ms": 300, "pitch": 60},   # releases press 1
            {"type": "pedal_up", "time_ms": 1000},
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert notes[0]["release_ms"] == 100
    assert notes[0]["end_ms"] == 1000 and notes[0]["end_reason"] == "pedal_up"
    assert notes[1]["release_ms"] == 300
    assert notes[1]["end_ms"] == 1000 and notes[1]["end_reason"] == "pedal_up"


def test_repeated_pedal_events_are_noops():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "pedal_up", "time_ms": 0},                  # no-op, pedal already up
            {"type": "pedal_down", "time_ms": 100},
            {"type": "pedal_down", "time_ms": 200},              # no-op
            {"type": "note_on", "time_ms": 300, "pitch": 60},
            {"type": "note_off", "time_ms": 400, "pitch": 60},   # sustained
            {"type": "pedal_up", "time_ms": 1000},
            {"type": "pedal_up", "time_ms": 1500},               # no-op
        ],
    })
    assert resp.status_code == 200
    note = resp.json()["notes"][0]
    assert note["end_ms"] == 1000
    assert note["end_reason"] == "pedal_up"


def test_end_ms_closes_held_and_sustained_notes():
    resp = parse({
        "end_ms": 3000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 500, "pitch": 60},   # sustained to end
            {"type": "note_on", "time_ms": 600, "pitch": 64},    # held to end
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert notes[0]["end_ms"] == 3000 and notes[0]["end_reason"] == "end_ms"
    assert notes[1]["end_ms"] == 3000 and notes[1]["end_reason"] == "end_ms"


def test_events_processed_by_time_then_input_order():
    # Submitted out of order; same-time events keep input order.
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "note_off", "time_ms": 500, "pitch": 60},   # index 0
            {"type": "note_on", "time_ms": 500, "pitch": 60},    # index 1, same time -> off first
            {"type": "note_on", "time_ms": 100, "pitch": 60},    # index 2, earliest time
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    # press 0 is the note_on at t=100 (input index 2); press 1 is at t=500 (input index 1).
    # The note_off at t=500 processed before the simultaneous note_on releases press 0.
    assert notes[0]["event_index"] == 2
    assert notes[0]["on_ms"] == 100 and notes[0]["end_ms"] == 500
    assert notes[1]["event_index"] == 1
    assert notes[1]["on_ms"] == 500 and notes[1]["end_ms"] == 5000
    assert notes[1]["end_reason"] == "end_ms"


def test_note_off_without_held_note_returns_400():
    resp = parse({
        "end_ms": 5000,
        "events": [{"type": "note_off", "time_ms": 100, "pitch": 60}],
    })
    assert resp.status_code == 400
    assert "no matching" in resp.json()["detail"]


def test_note_off_for_sustained_but_not_held_pitch_returns_400():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 0, "pitch": 60},
            {"type": "note_off", "time_ms": 100, "pitch": 60},   # sustained, no longer held
            {"type": "note_off", "time_ms": 200, "pitch": 60},   # nothing held -> error
        ],
    })
    assert resp.status_code == 400


def test_pitch_out_of_range_returns_422():
    for pitch in (-1, 128):
        resp = parse({
            "end_ms": 5000,
            "events": [{"type": "note_on", "time_ms": 0, "pitch": pitch}],
        })
        assert resp.status_code == 422


def test_missing_pitch_for_note_event_returns_422():
    resp = parse({
        "end_ms": 5000,
        "events": [{"type": "note_on", "time_ms": 0}],
    })
    assert resp.status_code == 422


def test_time_outside_zero_to_end_ms_returns_422():
    resp = parse({
        "end_ms": 1000,
        "events": [{"type": "note_on", "time_ms": 1001, "pitch": 60}],
    })
    assert resp.status_code == 422
    resp = parse({
        "end_ms": 1000,
        "events": [{"type": "note_on", "time_ms": -1, "pitch": 60}],
    })
    assert resp.status_code == 422


def test_results_ordered_by_press_index():
    resp = parse({
        "end_ms": 5000,
        "events": [
            {"type": "note_on", "time_ms": 300, "pitch": 67},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_on", "time_ms": 200, "pitch": 64},
        ],
    })
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert [n["press_index"] for n in notes] == [0, 1, 2]
    assert [n["pitch"] for n in notes] == [60, 64, 67]  # press order follows time order


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
