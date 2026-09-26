"""FastAPI application exposing the MIDI sustain parsing endpoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.models import NoteOut, ParseRequest, ParseResponse
from app.sustain import SustainError, parse_sustain

app = FastAPI(
    title="MIDI Sustain Parser",
    version="1.0.0",
    description=(
        "Parses timed note_on / note_off / pedal_down / pedal_up events into "
        "sounding half-open intervals [on_ms, end_ms) with an end reason per "
        "key press. Built for piano-teaching software."
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
