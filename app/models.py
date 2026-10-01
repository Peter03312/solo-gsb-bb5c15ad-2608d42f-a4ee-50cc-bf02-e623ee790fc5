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


class ReferenceNoteIn(BaseModel):
    """One reference note the student was supposed to play."""

    pitch: int = Field(ge=0, le=127, description="MIDI pitch 0-127")
    time_ms: int = Field(ge=0, description="Reference onset time in milliseconds, within [0, end_ms]")


class ParseRequest(BaseModel):
    end_ms: int = Field(ge=0, description="Performance end time in milliseconds")
    events: List[EventIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _times_within_end(self) -> "ParseRequest":
        for i, ev in enumerate(self.events):
            if ev.time_ms > self.end_ms:
                raise ValueError(
                    f"events[{i}].time_ms ({ev.time_ms}) exceeds end_ms ({self.end_ms})"
                )
        return self


class AlignRequest(ParseRequest):
    """Practice alignment request: the same events/end_ms payload plus the
    reference score and a non-negative alignment tolerance."""

    reference_notes: List[ReferenceNoteIn] = Field(default_factory=list)
    tolerance_ms: int = Field(ge=0, description="Maximum |played - reference| gap, in milliseconds, allowed for a pair")

    @model_validator(mode="after")
    def _reference_times_within_end(self) -> "AlignRequest":
        for i, note in enumerate(self.reference_notes):
            if note.time_ms > self.end_ms:
                raise ValueError(
                    f"reference_notes[{i}].time_ms ({note.time_ms}) exceeds end_ms ({self.end_ms})"
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


class AlignmentPairOut(BaseModel):
    """One matched reference/played note pair."""

    reference_index: int = Field(description="Index of the matched note in reference_notes")
    event_index: int = Field(description="Index of the matched note_on in the submitted events array")
    time_delta_ms: int = Field(
        description="Signed onset deviation: played time minus reference time; positive means late, negative early"
    )


class AlignResponse(BaseModel):
    end_ms: int
    tolerance_ms: int
    pair_count: int
    missed_count: int = Field(description="Number of reference notes never played (漏弹)")
    extra_count: int = Field(description="Number of note_on events with no reference counterpart (多弹)")
    pairs: List[AlignmentPairOut] = Field(description="Matched pairs, ordered by reference_index")
    missed_reference_indices: List[int] = Field(description="Reference notes with no played counterpart (漏弹)")
    extra_event_indices: List[int] = Field(
        description="Original event indices of unmatched note_on events (多弹), in played (time) order"
    )
