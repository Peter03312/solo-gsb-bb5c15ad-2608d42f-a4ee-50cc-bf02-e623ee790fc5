"""FastAPI application exposing the MIDI sustain parsing and practice
alignment endpoints."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.align import align_practice
from app.models import (
    AlignRequest,
    AlignResponse,
    AlignmentPairOut,
    NoteOut,
    ParseRequest,
    ParseResponse,
)
from app.sustain import SustainError, parse_sustain

app = FastAPI(
    title="MIDI Sustain Parser",
    version="1.0.0",
    description=(
        "Parses timed note_on / note_off / pedal_down / pedal_up events into "
        "sounding half-open intervals [on_ms, end_ms) with an end reason per "
        "key press, and aligns practice note_on events against a reference "
        "score. Built for piano-teaching software."
    ),
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/v1/parse",
    response_model=ParseResponse,
    responses={400: {"description": "Invalid event sequence (e.g. note_off without a held note_on)"}},
)
def parse(req: ParseRequest) -> ParseResponse:
    try:
        results = parse_sustain(req.events, req.end_ms)
    except SustainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    notes = [NoteOut(**vars(r)) for r in results]
    return ParseResponse(end_ms=req.end_ms, note_count=len(notes), notes=notes)


@app.post(
    "/api/v1/practice/align",
    response_model=AlignResponse,
    responses={
        400: {"description": "Invalid event sequence (e.g. note_off without a held note_on)"},
    },
)
def practice_align(req: AlignRequest) -> AlignResponse:
    # Reuse the same event-sequence validation as /api/v1/parse so an
    # ill-formed performance yields the same 400 error format.
    try:
        parse_sustain(req.events, req.end_ms)
    except SustainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    alignment = align_practice(req.events, req.reference_notes, req.tolerance_ms)
    pairs = [AlignmentPairOut(**vars(p)) for p in alignment.pairs]
    return AlignResponse(
        end_ms=req.end_ms,
        tolerance_ms=req.tolerance_ms,
        pair_count=len(pairs),
        missed_count=len(alignment.missed_reference_indices),
        extra_count=len(alignment.extra_event_indices),
        pairs=pairs,
        missed_reference_indices=alignment.missed_reference_indices,
        extra_event_indices=alignment.extra_event_indices,
    )
