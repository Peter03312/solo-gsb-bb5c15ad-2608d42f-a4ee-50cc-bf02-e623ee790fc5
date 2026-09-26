"""Practice alignment: compare played note_on events with reference notes.

Only ``note_on`` events are considered. They are ordered by
``(time_ms, original event index)`` and globally sequence-aligned against the
reference notes (also ordered by ``(time_ms, original reference index)``).

Alignment moves:

- pair   : a played note_on matches a reference note; allowed only when the
           pitches are equal and the onset difference is within tolerance.
           Cost is the absolute onset difference in milliseconds.
- missed : a reference note was not played (漏弹). Costs ``tolerance_ms + 1``.
- extra  : a played note_on has no reference note (多弹). Costs
           ``tolerance_ms + 1``.

The minimum-total-cost path is chosen. On equal cost, moves are preferred in
the order pair -> missed -> extra.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence

# Backtrack move tags; order doubles as the tie-break preference (smallest wins).
_MOVE_PAIR = 0
_MOVE_MISSED = 1
_MOVE_EXTRA = 2


@dataclass
class PairResult:
    reference_index: int       # index of the reference note in the submitted array
    event_index: int           # index of the note_on event in the submitted events array
    time_delta_ms: int         # played onset minus reference onset; positive = late


@dataclass
class AlignResult:
    pairs: List[PairResult]
    missed_reference_indices: List[int]
    extra_event_indices: List[int]


def _field(obj: Any, name: str) -> Any:
    """Read an attribute from a model instance or a key from a dict."""
    if hasattr(obj, name):
        return getattr(obj, name)
    return obj[name]


def align_practice(
    events: Sequence[Any],
    reference: Sequence[Any],
    tolerance_ms: int,
) -> AlignResult:
    """Align played ``note_on`` events with the reference notes.

    Inputs are assumed already range-validated by the API layer (pitches in
    0..127, times in ``[0, end_ms]``, ``tolerance_ms >= 0``).
    """
    played_order = sorted(
        (i for i, ev in enumerate(events) if _field(ev, "type") == "note_on"),
        key=lambda i: (_field(events[i], "time_ms"), i),
    )
    played = [
        (i, _field(events[i], "pitch"), _field(events[i], "time_ms"))
        for i in played_order
    ]

    ref_order = sorted(
        range(len(reference)),
        key=lambda i: (_field(reference[i], "time_ms"), i),
    )
    refs = [
        (i, _field(reference[i], "pitch"), _field(reference[i], "time_ms"))
        for i in ref_order
    ]

    m, n = len(refs), len(played)
    gap_cost = tolerance_ms + 1

    # cost[i][j]: minimum cost aligning refs[:i] with played[:j].
    # move[i][j]: last move on the preferred path (pair / missed / extra).
    cost = [[0] * (n + 1) for _ in range(m + 1)]
    move = [[-1] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        cost[i][0] = i * gap_cost
        move[i][0] = _MOVE_MISSED
    for j in range(1, n + 1):
        cost[0][j] = j * gap_cost
        move[0][j] = _MOVE_EXTRA

    for i in range(1, m + 1):
        _, ref_pitch, ref_time = refs[i - 1]
        for j in range(1, n + 1):
            _, play_pitch, play_time = played[j - 1]
            diff = abs(play_time - ref_time)

            # Enumerate moves in tie-break preference order (pair first,
            # then missed, then extra); only a strictly cheaper move replaces
            # the current best, so equal costs keep the earlier move.
            if ref_pitch == play_pitch and diff <= tolerance_ms:
                candidates = (
                    (cost[i - 1][j - 1] + diff, _MOVE_PAIR),
                    (cost[i - 1][j] + gap_cost, _MOVE_MISSED),
                    (cost[i][j - 1] + gap_cost, _MOVE_EXTRA),
                )
            else:
                candidates = (
                    (cost[i - 1][j] + gap_cost, _MOVE_MISSED),
                    (cost[i][j - 1] + gap_cost, _MOVE_EXTRA),
                )

            best_cost, best_move = candidates[0]
            for c, tag in candidates[1:]:
                if c < best_cost:
                    best_cost, best_move = c, tag

            cost[i][j] = best_cost
            move[i][j] = best_move

    pairs: List[PairResult] = []
    missed: List[int] = []
    extra: List[int] = []
    i, j = m, n
    while i > 0 or j > 0:
        tag = move[i][j]
        if tag == _MOVE_PAIR:
            ref_idx, _, ref_time = refs[i - 1]
            ev_idx, _, play_time = played[j - 1]
            pairs.append(
                PairResult(
                    reference_index=ref_idx,
                    event_index=ev_idx,
                    time_delta_ms=play_time - ref_time,
                )
            )
            i -= 1
            j -= 1
        elif tag == _MOVE_MISSED:
            missed.append(refs[i - 1][0])
            i -= 1
        else:
            extra.append(played[j - 1][0])
            j -= 1

    pairs.reverse()  # backtracking runs backwards; report in reference order
    missed.sort()
    extra.sort()
    return AlignResult(
        pairs=pairs,
        missed_reference_indices=missed,
        extra_event_indices=extra,
    )
