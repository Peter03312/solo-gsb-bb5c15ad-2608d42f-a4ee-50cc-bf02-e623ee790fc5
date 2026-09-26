"""Core sustain-pedal parsing logic.

Events are processed in (time_ms, input order). Each note_on opens a new
sounding note; its sounding interval is the half-open range [on_ms, end_ms).
A note ends for exactly one reason:

- note_off : key released while the pedal is up
- pedal_up : key was released while the pedal was down; the note kept
             sounding and stops when the pedal comes up
- end_ms   : still held (or still sustained) when the performance ends
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

END_REASON_NOTE_OFF = "note_off"
END_REASON_PEDAL_UP = "pedal_up"
END_REASON_END_MS = "end_ms"


class SustainError(ValueError):
    """Raised for semantically invalid event sequences (HTTP 400)."""


@dataclass
class _Note:
    press_index: int          # 0-based ordinal among note_on events, in processing order
    event_index: int          # index of the note_on event in the submitted events array
    pitch: int
    on_ms: int
    release_ms: Optional[int] = None   # when the key was physically released
    end_ms: Optional[int] = None       # when the note stops sounding
    end_reason: Optional[str] = None


@dataclass
class NoteResult:
    press_index: int
    event_index: int
    pitch: int
    on_ms: int
    release_ms: Optional[int]
    end_ms: int
    end_reason: str


def parse_sustain(events: List[dict], end_ms: int) -> List[NoteResult]:
    """Parse MIDI events into sounding note intervals.

    ``events`` items are dicts/objects with ``type``, ``time_ms`` and
    optional ``pitch`` attributes (already range-validated by the API layer).
    Returns one NoteResult per note_on, ordered by press_index.
    """
    order = sorted(range(len(events)), key=lambda i: (events[i].time_ms, i))

    pedal_down = False
    held: Dict[int, Deque[_Note]] = {}   # pitch -> keys currently held down
    sustained: List[_Note] = []          # released but kept sounding by the pedal
    notes: List[_Note] = []

    for i in order:
        ev = events[i]
        ev_type = ev.type if hasattr(ev, "type") else ev["type"]
        t = ev.time_ms if hasattr(ev, "time_ms") else ev["time_ms"]
        pitch = ev.pitch if hasattr(ev, "pitch") else ev.get("pitch")

        if ev_type == "note_on":
            note = _Note(press_index=len(notes), event_index=i, pitch=pitch, on_ms=t)
            held.setdefault(pitch, deque()).append(note)
            notes.append(note)

        elif ev_type == "note_off":
            queue = held.get(pitch)
            if not queue:
                raise SustainError(
                    f"note_off at {t} ms for pitch {pitch} has no matching "
                    f"held note_on (event index {i})"
                )
            note = queue.popleft()  # release the earliest still-held press
            note.release_ms = t
            if pedal_down:
                sustained.append(note)  # keeps sounding until pedal_up / end_ms
            else:
                note.end_ms = t
                note.end_reason = END_REASON_NOTE_OFF

        elif ev_type == "pedal_down":
            pedal_down = True  # repeated pedal_down is a no-op

        elif ev_type == "pedal_up":
            if pedal_down:
                pedal_down = False
                for note in sustained:
                    note.end_ms = t
                    note.end_reason = END_REASON_PEDAL_UP
                sustained.clear()
            # pedal_up while already up is a no-op

        else:
            raise SustainError(f"unknown event type {ev_type!r} (event index {i})")

    for note in notes:
        if note.end_ms is None:
            note.end_ms = end_ms
            note.end_reason = END_REASON_END_MS

    return [
        NoteResult(
            press_index=n.press_index,
            event_index=n.event_index,
            pitch=n.pitch,
            on_ms=n.on_ms,
            release_ms=n.release_ms,
            end_ms=n.end_ms,
            end_reason=n.end_reason,
        )
        for n in notes  # notes were appended in press order already
    ]
