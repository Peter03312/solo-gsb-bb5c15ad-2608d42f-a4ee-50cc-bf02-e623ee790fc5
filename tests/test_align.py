"""Tests for the practice alignment endpoint and its DP core."""

from fastapi.testclient import TestClient

from app.align import align_practice
from app.main import app

client = TestClient(app)


def align(payload):
    return client.post("/api/v1/practice/align", json=payload)


# --------------------------------------------------------------------------
# Endpoint behaviour
# --------------------------------------------------------------------------

def test_perfect_match():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 200},
        ],
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_on", "time_ms": 200, "pitch": 64},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pair_count"] == 2
    assert body["missed_count"] == 0 and body["extra_count"] == 0
    assert body["missed_reference_indices"] == []
    assert body["extra_event_indices"] == []
    assert body["pairs"] == [
        {"reference_index": 0, "event_index": 0, "time_delta_ms": 0},
        {"reference_index": 1, "event_index": 1, "time_delta_ms": 0},
    ]


def test_missed_and_extra_notes():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 200},
            {"pitch": 67, "time_ms": 300},
        ],
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},   # pairs with ref 0
            {"type": "note_on", "time_ms": 210, "pitch": 72},   # wrong pitch -> extra
            {"type": "note_off", "time_ms": 400, "pitch": 60},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert [(p["reference_index"], p["event_index"]) for p in body["pairs"]] == [(0, 0)]
    assert body["missed_reference_indices"] == [1, 2]
    assert body["extra_event_indices"] == [1]  # original event index


def test_signed_time_delta_late_and_early():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 300},
        ],
        "events": [
            {"type": "note_on", "time_ms": 130, "pitch": 60},   # 30 ms late
            {"type": "note_on", "time_ms": 280, "pitch": 64},   # 20 ms early
        ],
    })
    assert resp.status_code == 200
    pairs = resp.json()["pairs"]
    assert pairs[0]["time_delta_ms"] == 30
    assert pairs[1]["time_delta_ms"] == -20


def test_tolerance_boundary_is_inclusive():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 50,
        "reference_notes": [{"pitch": 60, "time_ms": 100}],
        "events": [{"type": "note_on", "time_ms": 150, "pitch": 60}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pair_count"] == 1
    assert body["pairs"][0]["time_delta_ms"] == 50
    assert body["extra_event_indices"] == [] and body["missed_reference_indices"] == []


def test_gap_beyond_tolerance_counts_as_miss_and_extra():
    # |delta| = 51 > tolerance 50; pairing is forbidden, so miss + extra
    # (total 2 * 51) is the only possible outcome.
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 50,
        "reference_notes": [{"pitch": 60, "time_ms": 100}],
        "events": [{"type": "note_on", "time_ms": 151, "pitch": 60}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pair_count"] == 0
    assert body["missed_reference_indices"] == [0]
    assert body["extra_event_indices"] == [0]


def test_global_alignment_picks_cheapest_non_greedy_match():
    # Both played notes can pair with both refs, but greedy nearest matching
    # would cross-assign; the global optimum pairs 100->100 and 200->195.
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 60, "time_ms": 200},
        ],
        "events": [
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_on", "time_ms": 195, "pitch": 60},
        ],
    })
    pairs = resp.json()["pairs"]
    assert [(p["reference_index"], p["event_index"]) for p in pairs] == [(0, 0), (1, 1)]
    assert [p["time_delta_ms"] for p in pairs] == [0, -5]


def test_global_alignment_can_skip_with_gaps():
    # ref2 could pair with play0 or play1. Pairing ref2-play1 and letting
    # play0 be extra keeps ref0 in sequence order at lower total cost.
    refs = [
        {"pitch": 60, "time_ms": 100},
        {"pitch": 60, "time_ms": 1000},
    ]
    events = [
        {"type": "note_on", "time_ms": 900, "pitch": 60},
        {"type": "note_on", "time_ms": 1005, "pitch": 60},
    ]
    result = align_practice(events, refs, tolerance_ms=100)
    assert [(p.reference_index, p.event_index) for p in result.pairs] == [(1, 1)]
    assert result.missed_reference_indices == [0]
    assert result.extra_event_indices == [0]


def test_only_note_on_events_are_aligned():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [{"pitch": 60, "time_ms": 100}],
        "events": [
            {"type": "pedal_down", "time_ms": 0},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
            {"type": "note_off", "time_ms": 400, "pitch": 60},
            {"type": "pedal_up", "time_ms": 500},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pair_count"] == 1
    assert body["pairs"][0]["event_index"] == 1
    assert body["extra_event_indices"] == []


def test_events_sorted_by_time_then_original_index():
    # note_on submitted out of order; pairing uses time order but the
    # response reports original event indices.
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [
            {"pitch": 60, "time_ms": 100},
            {"pitch": 64, "time_ms": 200},
        ],
        "events": [
            {"type": "note_on", "time_ms": 200, "pitch": 64},   # index 0, played second
            {"type": "note_on", "time_ms": 100, "pitch": 60},   # index 1, played first
        ],
    })
    assert resp.status_code == 200
    pairs = resp.json()["pairs"]
    assert [(p["reference_index"], p["event_index"]) for p in pairs] == [(0, 1), (1, 0)]


def test_tie_break_prefers_pair_then_miss_then_extra():
    # tolerance 0, same pitch: played at t=0 (extra) and t=100 (pair with
    # ref). Pairing (cost 0) beats miss+extra (cost 2). The tie rule
    # "pair first" selects the t=100 note for the pair.
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 0,
        "reference_notes": [{"pitch": 60, "time_ms": 100}],
        "events": [
            {"type": "note_on", "time_ms": 0, "pitch": 60},
            {"type": "note_on", "time_ms": 100, "pitch": 60},
        ],
    })
    body = resp.json()
    assert body["pairs"] == [
        {"reference_index": 0, "event_index": 1, "time_delta_ms": 0}
    ]
    assert body["extra_event_indices"] == [0]


def test_empty_performance_and_empty_reference():
    resp = align({
        "end_ms": 1000,
        "tolerance_ms": 50,
        "reference_notes": [],
        "events": [],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairs"] == []
    assert body["missed_reference_indices"] == []
    assert body["extra_event_indices"] == []
    assert body["pair_count"] == 0


def test_end_ms_zero_is_valid():
    resp = align({
        "end_ms": 0,
        "tolerance_ms": 0,
        "reference_notes": [{"pitch": 60, "time_ms": 0}],
        "events": [{"type": "note_on", "time_ms": 0, "pitch": 60}],
    })
    assert resp.status_code == 200
    assert resp.json()["pairs"][0]["time_delta_ms"] == 0


def test_reuses_parse_validation_note_off_without_note_on_returns_400():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": 100,
        "reference_notes": [],
        "events": [{"type": "note_off", "time_ms": 100, "pitch": 60}],
    })
    assert resp.status_code == 400
    assert "no matching" in resp.json()["detail"]


def test_negative_tolerance_returns_422():
    resp = align({
        "end_ms": 5000,
        "tolerance_ms": -1,
        "reference_notes": [{"pitch": 60, "time_ms": 0}],
        "events": [],
    })
    assert resp.status_code == 422


def test_reference_time_beyond_end_ms_returns_422():
    resp = align({
        "end_ms": 1000,
        "tolerance_ms": 100,
        "reference_notes": [{"pitch": 60, "time_ms": 1001}],
        "events": [],
    })
    assert resp.status_code == 422


def test_reference_pitch_out_of_range_returns_422():
    for pitch in (-1, 128):
        resp = align({
            "end_ms": 1000,
            "tolerance_ms": 100,
            "reference_notes": [{"pitch": pitch, "time_ms": 0}],
            "events": [],
        })
        assert resp.status_code == 422


def test_event_validation_is_inherited():
    resp = align({
        "end_ms": 1000,
        "tolerance_ms": 100,
        "reference_notes": [],
        "events": [{"type": "note_on", "time_ms": 1001, "pitch": 60}],
    })
    assert resp.status_code == 422

    resp = align({
        "end_ms": 1000,
        "tolerance_ms": 100,
        "reference_notes": [],
        "events": [{"type": "note_on", "time_ms": 0, "pitch": 128}],
    })
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# DP core direct tests (dict input)
# --------------------------------------------------------------------------

def test_core_miss_then_pair_then_extra_order():
    events = [
        {"type": "note_on", "time_ms": 50, "pitch": 99},    # extra
        {"type": "note_on", "time_ms": 305, "pitch": 60},   # pair with ref 1 (early)
    ]
    refs = [
        {"pitch": 60, "time_ms": 100},                      # missed
        {"pitch": 60, "time_ms": 300},
    ]
    result = align_practice(events, refs, tolerance_ms=50)
    assert [(p.reference_index, p.event_index) for p in result.pairs] == [(1, 1)]
    assert result.pairs[0].time_delta_ms == 5
    assert result.missed_reference_indices == [0]
    assert result.extra_event_indices == [0]
