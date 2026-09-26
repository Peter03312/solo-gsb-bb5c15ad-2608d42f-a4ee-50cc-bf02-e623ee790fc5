"""Tests for the practice alignment endpoint and core logic."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def align(payload):
    return client.post("/api/v1/practice/align", json=payload)


def test_perfect_match():
    resp = align({
        "end_ms": 2000,
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_on", "time_ms": 500, "pitch": 64},
        ],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 500},
        ],
        "tolerance_ms": 100,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["missed_reference_indices"] == []
    assert body["extra_event_indices"] == []
    assert body["pairs"] == [
        {"reference_index": 0, "event_index": 0, "time_delta_ms": 0},
        {"reference_index": 1, "event_index": 1, "time_delta_ms": 0},
    ]


def test_missed_notes():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 100, "pitch": 60}],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 500},
            {"pitch": 67, "time_ms": 900},
        ],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert [p["reference_index"] for p in body["pairs"]] == [0]
    assert body["missed_reference_indices"] == [1, 2]
    assert body["extra_event_indices"] == []


def test_extra_notes():
    resp = align({
        "end_ms": 2000,
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_on", "time_ms": 200, "pitch": 61},
            {"type": "note_on", "time_ms": 500, "pitch": 64},
        ],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 500},
        ],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["extra_event_indices"] == [1]
    assert body["missed_reference_indices"] == []


def test_signed_time_delta_positive_is_late():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 230, "pitch": 60}],
        "reference": [{"pitch": 60, "time_ms": 200}],
        "tolerance_ms": 100,
    })
    assert resp.status_code == 200
    pair = resp.json()["pairs"][0]
    assert pair["time_delta_ms"] == 30


def test_signed_time_delta_negative_is_early():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 180, "pitch": 60}],
        "reference": [{"pitch": 60, "time_ms": 200}],
        "tolerance_ms": 100,
    })
    assert resp.status_code == 200
    pair = resp.json()["pairs"][0]
    assert pair["time_delta_ms"] == -20


def test_match_at_tolerance_boundary_inclusive():
    payload = {
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 250, "pitch": 60}],
        "reference": [{"pitch": 60, "time_ms": 200}],
        "tolerance_ms": 50,
    }
    assert align(payload).json()["pairs"][0]["time_delta_ms"] == 50
    payload["events"][0]["time_ms"] = 251
    body = align(payload).json()
    assert body["pairs"] == []
    assert body["missed_reference_indices"] == [0]
    assert body["extra_event_indices"] == [0]


def test_pitch_mismatch_cannot_pair():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 100, "pitch": 60}],
        "reference": [{"pitch": 61, "time_ms": 100}],
        "tolerance_ms": 200,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairs"] == []
    assert body["missed_reference_indices"] == [0]
    assert body["extra_event_indices"] == [0]


def test_only_note_on_events_are_aligned():
    # note_off and pedal events must not appear as extras; the note_off at 200
    # also validates the event sequence like the parse endpoint.
    resp = align({
        "end_ms": 2000,
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 200, "pitch": 60},
            {"type": "pedal_up", "time_ms": 300},
        ],
        "reference": [{"pitch": 60, "time_ms": 100}],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pairs"]) == 1
    assert body["pairs"][0]["event_index"] == 1
    assert body["extra_event_indices"] == []


def test_global_sequence_alignment_chooses_minimal_cost():
    # Played note 60 is 80ms late (within tolerance); a greedy nearest match
    # could mis-pair; global alignment pairs 60->60, 64->64.
    resp = align({
        "end_ms": 3000,
        "events": [
            {"type": "note_on", "time_ms": 180, "pitch": 60},
            {"type": "note_on", "time_ms": 520, "pitch": 64},
        ],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 500},
        ],
        "tolerance_ms": 100,
    })
    body = resp.json()
    assert [(p["reference_index"], p["event_index"]) for p in body["pairs"]] == [
        (0, 0),
        (1, 1),
    ]
    assert body["pairs"][0]["time_delta_ms"] == 80
    assert body["pairs"][1]["time_delta_ms"] == 20


def test_pitch_mismatch_blocks_pair_even_within_tolerance():
    # r0 (pitch 60) cannot pair p0 (pitch 64); the cheapest path pairs
    # r1/p1 and pays one missed + one extra.
    resp = align({
        "end_ms": 2000,
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 64},
            {"type": "note_on", "time_ms": 200, "pitch": 64},
        ],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 200},
        ],
        "tolerance_ms": 0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairs"] == [
        {"reference_index": 1, "event_index": 1, "time_delta_ms": 0}
    ]
    assert body["missed_reference_indices"] == [0]
    assert body["extra_event_indices"] == [0]


def test_played_events_ordered_by_time_then_input_index():
    # Events submitted out of order; pair indices must point at the original
    # event array positions.
    resp = align({
        "end_ms": 2000,
        "events": [
            {"type": "note_on", "time_ms": 500, "pitch": 64},   # index 0
            {"type": "note_on", "time_ms": 100, "pitch": 60},   # index 1
        ],
        "reference": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 500},
        ],
        "tolerance_ms": 0,
    })
    assert resp.status_code == 200
    assert resp.json()["pairs"] == [
        {"reference_index": 0, "event_index": 1, "time_delta_ms": 0},
        {"reference_index": 1, "event_index": 0, "time_delta_ms": 0},
    ]


def test_empty_events_and_reference():
    resp = align({
        "end_ms": 1000,
        "events": [],
        "reference": [],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 200
    assert resp.json() == {
        "pairs": [],
        "missed_reference_indices": [],
        "extra_event_indices": [],
    }


def test_pairing_within_tolerance_beats_gaps():
    # gap cost is tolerance_ms + 1: a 99ms deviation costs 99, while leaving
    # the note missed and played-as-extra would cost 2 * 101 = 202.
    resp = align({
        "end_ms": 3000,
        "events": [{"type": "note_on", "time_ms": 299, "pitch": 60}],
        "reference": [{"pitch": 60, "time_ms": 200}],
        "tolerance_ms": 100,
    })
    body = resp.json()
    assert len(body["pairs"]) == 1
    assert body["pairs"][0]["time_delta_ms"] == 99
    assert body["missed_reference_indices"] == []
    assert body["extra_event_indices"] == []


def test_reuses_parse_event_validation_note_off_without_note_on_400():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_off", "time_ms": 100, "pitch": 60}],
        "reference": [],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 400
    assert "no matching" in resp.json()["detail"]


def test_invalid_event_pitch_returns_422():
    resp = align({
        "end_ms": 2000,
        "events": [{"type": "note_on", "time_ms": 100, "pitch": 128}],
        "reference": [],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 422


def test_event_time_beyond_end_ms_returns_422():
    resp = align({
        "end_ms": 1000,
        "events": [{"type": "note_on", "time_ms": 1001, "pitch": 60}],
        "reference": [],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 422


def test_reference_time_beyond_end_ms_returns_422():
    resp = align({
        "end_ms": 1000,
        "events": [],
        "reference": [{"pitch": 60, "time_ms": 1001}],
        "tolerance_ms": 50,
    })
    assert resp.status_code == 422


def test_negative_tolerance_returns_422():
    resp = align({
        "end_ms": 1000,
        "events": [],
        "reference": [],
        "tolerance_ms": -1,
    })
    assert resp.status_code == 422


def test_reference_pitch_out_of_range_returns_422():
    for pitch in (-1, 128):
        resp = align({
            "end_ms": 1000,
            "events": [],
            "reference": [{"pitch": pitch, "time_ms": 0}],
            "tolerance_ms": 50,
        })
        assert resp.status_code == 422


def test_reference_time_zero_and_end_ms_are_allowed():
    resp = align({
        "end_ms": 1000,
        "events": [
            {"type": "note_on", "time_ms": 0, "pitch": 60},
            {"type": "note_on", "time_ms": 1000, "pitch": 64},
        ],
        "reference": [
            {"pitch": 60, "time_ms": 0},
            {"pitch": 64, "time_ms": 1000},
        ],
        "tolerance_ms": 0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pairs"]) == 2
    assert body["pairs"][1]["time_delta_ms"] == 0
