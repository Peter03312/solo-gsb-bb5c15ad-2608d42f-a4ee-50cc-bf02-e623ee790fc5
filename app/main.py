"""FastAPI application exposing the MIDI sustain parsing endpoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.models import (
    AlignPairOut,
    AlignRequest,
    AlignResponse,
    NoteOut,
    ParseRequest,
    ParseResponse,
)
from app.practice import align_practice
from app.sustain import SustainError, parse_sustain

app = FastAPI(
    title="MIDI Sustain Parser",
    version="1.0.0",
    description=(
        "Parses timed note_on / note_off / pedal_down / pedal_up events into "
        "sounding half-open intervals [on_ms, end_ms) with an end reason per "
        "key press, and aligns practice performances against reference notes. "
        "Built for piano-teaching software."
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
    responses={400: {"description": "Invalid event sequence (e.g. note_off without a held note_on)"}},
)
def practice_align(req: AlignRequest) -> AlignResponse:
    # Reuse the parse endpoint's event validation (same 400/422 semantics).
    try:
        parse_sustain(req.events, req.end_ms)
        result = align_practice(req.events, req.reference, req.tolerance_ms)
    except SustainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pairs = [
        AlignPairOut(
            reference_index=p.reference_index,
            event_index=p.event_index,
            time_delta_ms=p.time_delta_ms,
        )
        for p in result.pairs
    ]
    return AlignResponse(
        pairs=pairs,
        missed_reference_indices=result.missed_reference_indices,
        extra_event_indices=result.extra_event_indices,
    )
