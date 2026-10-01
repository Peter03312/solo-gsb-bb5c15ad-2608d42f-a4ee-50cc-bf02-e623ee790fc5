"""Core practice-alignment logic.

Played ``note_on`` events (ordered by ``(time_ms, input index)``) are
globally sequence-aligned with the time-ordered reference notes using a
dynamic program akin to Needleman-Wunsch. Allowed moves:

- pair  : same pitch and ``|played - reference| <= tolerance_ms``;
          cost is the absolute time difference
- miss  : a reference note has no played counterpart (漏弹);
          cost ``tolerance_ms + 1``
- extra : a played note has no reference counterpart (多弹);
          cost ``tolerance_ms + 1``

The minimum total-cost path is chosen. On ties the preference order is
pair > miss > extra, checked in that order at every DP cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

_PAIR = 0
_MISS = 1
_EXTRA = 2


@dataclass
class AlignmentPair:
    reference_index: int       # index of the matched note in the reference array
    event_index: int           # index of the matched note_on in the submitted events array
    time_delta_ms: int         # signed: played time minus reference time (positive = late)


@dataclass
class PracticeAlignment:
    pairs: List[AlignmentPair]
    missed_reference_indices: List[int]
    extra_event_indices: List[int]


def _field(item, name: str):
    """Read an attribute from a model/dataclass or a key from a dict."""
    if isinstance(item, dict):
        return item[name]
    return getattr(item, name)


def align_practice(
    events: Sequence,
    reference_notes: Sequence,
    tolerance_ms: int,
) -> PracticeAlignment:
    """Align played note_on events against the reference notes.

    ``events`` items carry ``type`` / ``time_ms`` / ``pitch`` (already
    range-validated by the API layer). ``reference_notes`` items carry
    ``pitch`` / ``time_ms`` and are expected to be ordered by time.
    Indices returned for played notes always refer to positions in the
    original ``events`` array.
    """
    # Only note_on events participate; order them by (time, input index).
    played = sorted(
        (i for i, ev in enumerate(events) if _field(ev, "type") == "note_on"),
        key=lambda i: (_field(events[i], "time_ms"), i),
    )

    n_ref = len(reference_notes)
    n_play = len(played)
    gap_cost = tolerance_ms + 1

    # dp[i][j]: min cost aligning the first i refs with the first j played.
    dp = [[0] * (n_play + 1) for _ in range(n_ref + 1)]
    # ops[i][j]: the chosen move (_PAIR/_MISS/_EXTRA) leading into dp[i][j].
    ops = [[_PAIR] * (n_play + 1) for _ in range(n_ref + 1)]

    for i in range(1, n_ref + 1):
        dp[i][0] = i * gap_cost
        ops[i][0] = _MISS
    for j in range(1, n_play + 1):
        dp[0][j] = j * gap_cost
        ops[0][j] = _EXTRA

    for i in range(1, n_ref + 1):
        ref = reference_notes[i - 1]
        ref_pitch = _field(ref, "pitch")
        ref_time = _field(ref, "time_ms")
        for j in range(1, n_play + 1):
            event_index = played[j - 1]
            ev = events[event_index]
            played_pitch = _field(ev, "pitch")
            played_time = _field(ev, "time_ms")

            # Candidate order encodes the tie-break: pair > miss > extra.
            candidates: List[tuple] = []
            if (
                played_pitch == ref_pitch
                and abs(played_time - ref_time) <= tolerance_ms
            ):
                candidates.append(
                    (dp[i - 1][j - 1] + abs(played_time - ref_time), _PAIR)
                )
            candidates.append((dp[i - 1][j] + gap_cost, _MISS))
            candidates.append((dp[i][j - 1] + gap_cost, _EXTRA))

            best_cost = min(cost for cost, _ in candidates)
            for cost, op in candidates:  # first cheapest wins -> fixed tie order
                if cost == best_cost:
                    dp[i][j] = cost
                    ops[i][j] = op
                    break

    pairs: List[AlignmentPair] = []
    missed: List[int] = []
    extras: List[int] = []

    i, j = n_ref, n_play
    while i > 0 or j > 0:
        op = ops[i][j]
        if op == _PAIR:
            ref = reference_notes[i - 1]
            event_index = played[j - 1]
            pairs.append(
                AlignmentPair(
                    reference_index=i - 1,
                    event_index=event_index,
                    time_delta_ms=(
                        _field(events[event_index], "time_ms")
                        - _field(ref, "time_ms")
                    ),
                )
            )
            i -= 1
            j -= 1
        elif op == _MISS:
            missed.append(i - 1)
            i -= 1
        else:  # _EXTRA
            extras.append(played[j - 1])
            j -= 1

    # Backtracking walks the path backwards; report everything in score order.
    pairs.reverse()
    missed.reverse()
    extras.reverse()
    return PracticeAlignment(
        pairs=pairs,
        missed_reference_indices=missed,
        extra_event_indices=extras,
    )
