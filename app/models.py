"""Request/response schemas for the MIDI sustain parsing API."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

NOTE_TYPES = ("note_on", "note_off")


class EventIn(BaseModel):
    """A single MIDI event. ``pitch`` is required for note events and
    ignored for pedal events."""

    type: Literal["note_on", "note_off", "pedal_down", "pedal_up"]
    time_ms: int = Field(ge=0, description="Event time in milliseconds, within [0, end_ms]")
    pitch: Optional[int] = Field(default=None, ge=0, le=127, description="MIDI pitch 0-127")

    @model_validator(mode="after")
    def _pitch_required_for_notes(self) -> "EventIn":
        if self.type in NOTE_TYPES and self.pitch is None:
            raise ValueError(f"pitch is required for {self.type} events")
        return self


def _validate_times_within_end(times: List[int], end_ms: int, label: str) -> None:
    """Every time must lie within [0, end_ms]; ``times`` are already ge=0."""
    for i, t in enumerate(times):
        if t > end_ms:
            raise ValueError(f"{label}[{i}].time_ms ({t}) exceeds end_ms ({end_ms})")


class ParseRequest(BaseModel):
    end_ms: int = Field(ge=0, description="Performance end time in milliseconds")
    events: List[EventIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _times_within_end(self) -> "ParseRequest":
        _validate_times_within_end(
            [ev.time_ms for ev in self.events], self.end_ms, "events"
        )
        return self


class ReferenceNoteIn(BaseModel):
    """A reference note to practice against, given in chronological order."""

    pitch: int = Field(ge=0, le=127, description="MIDI pitch 0-127")
    time_ms: int = Field(ge=0, description="Reference onset in milliseconds, within [0, end_ms]")


class AlignRequest(BaseModel):
    end_ms: int = Field(ge=0, description="Performance end time in milliseconds")
    events: List[EventIn] = Field(default_factory=list)
    reference: List[ReferenceNoteIn] = Field(
        default_factory=list,
        description="Reference notes ordered by time, each {pitch, time_ms}",
    )
    tolerance_ms: int = Field(
        ge=0, description="Non-negative matching tolerance in milliseconds"
    )

    @model_validator(mode="after")
    def _times_within_end(self) -> "AlignRequest":
        _validate_times_within_end(
            [ev.time_ms for ev in self.events], self.end_ms, "events"
        )
        _validate_times_within_end(
            [n.time_ms for n in self.reference], self.end_ms, "reference"
        )
        return self


class NoteOut(BaseModel):
    """One sounded note. The sounding interval is the half-open range
    [on_ms, end_ms): the note is audible at on_ms and silent from end_ms."""

    press_index: int = Field(description="0-based ordinal of this key press among all note_on events")
    event_index: int = Field(description="Index of the note_on event in the submitted events array")
    pitch: int
    on_ms: int = Field(description="Key press time; start of the sounding interval")
    release_ms: Optional[int] = Field(
        description="Key release time; null if the key was still held at end_ms"
    )
    end_ms: int = Field(description="End of the sounding interval (exclusive)")
    end_reason: Literal["note_off", "pedal_up", "end_ms"]


class ParseResponse(BaseModel):
    end_ms: int
    note_count: int
    notes: List[NoteOut]


class AlignPairOut(BaseModel):
    reference_index: int = Field(description="Index of the matched note in the submitted reference array")
    event_index: int = Field(description="Index of the matched note_on event in the submitted events array")
    time_delta_ms: int = Field(
        description="Signed onset deviation in milliseconds (played time minus reference time; positive = late)"
    )


class AlignResponse(BaseModel):
    pairs: List[AlignPairOut] = Field(description="Matched reference/played pairs, in reference order")
    missed_reference_indices: List[int] = Field(
        default_factory=list, description="Reference notes not played (漏弹)"
    )
    extra_event_indices: List[int] = Field(
        default_factory=list, description="Played note_on events with no reference note (多弹)"
    )
