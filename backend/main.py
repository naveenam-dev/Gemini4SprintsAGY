from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.genai import types

load_dotenv()

from .db import get_care_plan, init_db, save_care_plan, update_checklist_item, utc_now_iso
from .gemini_service import (
    CLINICAL_DISCLAIMER,
    LANGUAGE_NAMES,
    LIVE_MODEL,
    _get_client,
    answer_care_question,
    build_care_plan,
    create_live_config,
    extract_discharge_summary,
    synthesize_tts_wav,
)
from .samples import SAMPLES
from .schemas import (
    AskRequest,
    AskResponse,
    CarePlanRequest,
    CarePlanResponse,
    ChecklistUpdateRequest,
    ExtractedDischarge,
    TTSRequest,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discharge_dost")

app = FastAPI(
    title="Discharge Dost API",
    description="Multimodal clinical discharge comprehension agent powered by Gemini 4 & Cloud Run",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    has_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return {
        "status": "ok",
        "service": "discharge-dost",
        "gemini_key_configured": has_key,
        "text_model": os.getenv("GEMINI_MODEL", "gemini-4-hydrogen"),
        "tts_model": os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"),
        "live_model": LIVE_MODEL,
    }


@app.get("/api/samples")
def list_samples() -> dict:
    return {"samples": SAMPLES}


@app.post("/api/extract", response_model=ExtractedDischarge)
async def extract_endpoint(
    file: Optional[UploadFile] = File(default=None),
    raw_text: str = Form(default=""),
) -> ExtractedDischarge:
    image_bytes: Optional[bytes] = None
    mime_type: Optional[str] = None

    if file is not None:
        image_bytes = await file.read()
        mime_type = file.content_type or "image/jpeg"
        if len(image_bytes) > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 15 MB).")

    if not image_bytes and not raw_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Please upload a discharge photo/PDF or paste discharge text.",
        )

    try:
        return extract_discharge_summary(
            image_bytes=image_bytes,
            mime_type=mime_type,
            raw_text=raw_text,
        )
    except Exception as exc:
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=f"Extraction error: {exc}") from exc


@app.post("/api/care-plan", response_model=CarePlanResponse)
def create_care_plan_endpoint(req: CarePlanRequest) -> CarePlanResponse:
    if not req.extracted.medications:
        raise HTTPException(status_code=400, detail="At least one medication is required.")

    try:
        generated, _curated, thought_summary = build_care_plan(
            confirmed=req.extracted,
            language=req.language,
            hospital_city=req.hospital_city,
        )
    except Exception as exc:
        logger.exception("Care plan generation failed")
        raise HTTPException(status_code=500, detail=f"Care plan generation error: {exc}") from exc

    plan = CarePlanResponse(
        plan_id=uuid.uuid4().hex[:10],
        language=req.language,
        language_name=LANGUAGE_NAMES[req.language],
        diagnosis=req.extracted.diagnosis,
        follow_up_date=req.extracted.follow_up_date,
        follow_up_department=req.extracted.follow_up_department,
        pharmacist_review_required=req.extracted.pharmacist_review_required
        or any(m.needs_pharmacist_review for m in req.extracted.medications),
        summary_headline=generated.summary_headline,
        schedule=generated.schedule,
        safety_alerts=generated.safety_alerts_localized,
        red_flag_banner=generated.red_flag_banner,
        follow_up_reminder=generated.follow_up_reminder,
        diet_activity_tips=generated.diet_activity_tips,
        caregiver_script=generated.caregiver_script,
        reasoning_trace=generated.reasoning_trace,
        thought_summary=thought_summary,
        disclaimer=CLINICAL_DISCLAIMER,
        created_at=utc_now_iso(),
    )
    save_care_plan(plan)
    return plan


@app.get("/api/plans/{plan_id}", response_model=CarePlanResponse)
def get_plan_endpoint(plan_id: str) -> CarePlanResponse:
    plan = get_care_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Care plan not found.")
    return plan


@app.patch("/api/plans/{plan_id}/checklist", response_model=CarePlanResponse)
def update_checklist_endpoint(plan_id: str, req: ChecklistUpdateRequest) -> CarePlanResponse:
    plan = update_checklist_item(plan_id, req.item_id, req.checked)
    if not plan:
        raise HTTPException(status_code=404, detail="Care plan not found.")
    return plan


@app.post("/api/tts")
def tts_endpoint(req: TTSRequest) -> Response:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is required for TTS.")
    try:
        wav_bytes = synthesize_tts_wav(req.text, req.language)
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as exc:
        logger.exception("TTS synthesis failed")
        raise HTTPException(status_code=500, detail=f"TTS error: {exc}") from exc


@app.post("/api/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    plan = get_care_plan(req.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Care plan not found.")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        answer, interaction_id, escalate = answer_care_question(
            plan_context=plan.model_dump(),
            question=req.question,
            language=req.language,
            previous_interaction_id=req.previous_interaction_id,
        )
        return AskResponse(
            answer=answer,
            interaction_id=interaction_id,
            escalate_108=escalate,
        )
    except Exception as exc:
        logger.exception("Q&A failed")
        raise HTTPException(status_code=500, detail=f"Q&A error: {exc}") from exc


@app.websocket("/ws/live/{plan_id}")
async def live_voice_endpoint(websocket: WebSocket, plan_id: str) -> None:
    """Bidirectional Gemini 3.8 Live voice/text Q&A grounded on a saved care plan."""
    await websocket.accept()
    plan = get_care_plan(plan_id)
    if not plan:
        await websocket.send_json({"type": "error", "message": "Care plan not found."})
        await websocket.close(code=1008)
        return

    lang_param = websocket.query_params.get("language") or plan.language
    language = lang_param if lang_param in LANGUAGE_NAMES else plan.language

    try:
        client = _get_client(api_version="v1beta")
        config = create_live_config(plan.model_dump(), language)
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        return

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await websocket.send_json(
                {
                    "type": "ready",
                    "model": LIVE_MODEL,
                    "language": LANGUAGE_NAMES[language],
                }
            )

            async def client_to_gemini() -> None:
                while True:
                    raw = await websocket.receive_text()
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "audio" and msg.get("data"):
                        pcm_bytes = base64.b64decode(msg["data"])
                        await session.send_realtime_input(
                            audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
                        )
                    elif msg_type == "audio_stream_end":
                        await session.send_realtime_input(audio_stream_end=True)
                    elif msg_type == "text" and msg.get("text"):
                        await session.send_realtime_input(text=str(msg["text"]))

            async def gemini_to_client() -> None:
                async for response in session.receive():
                    sc = response.server_content
                    if not sc:
                        continue
                    if sc.interrupted:
                        await websocket.send_json({"type": "interrupted"})
                    if sc.input_transcription and sc.input_transcription.text:
                        await websocket.send_json(
                            {"type": "input_transcript", "text": sc.input_transcription.text}
                        )
                    if sc.output_transcription and sc.output_transcription.text:
                        await websocket.send_json(
                            {"type": "output_transcript", "text": sc.output_transcription.text}
                        )
                    if sc.model_turn and sc.model_turn.parts:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                b64_audio = base64.b64encode(part.inline_data.data).decode("ascii")
                                await websocket.send_json(
                                    {"type": "audio", "data": b64_audio, "sample_rate": 24000}
                                )
                    if sc.turn_complete:
                        await websocket.send_json({"type": "turn_complete"})

            tasks = [
                asyncio.create_task(client_to_gemini()),
                asyncio.create_task(gemini_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except WebSocketDisconnect:
        logger.info("Live voice client disconnected for plan %s", plan_id)
    except Exception as exc:
        logger.exception("Live voice session error")
        try:
            await websocket.send_json({"type": "error", "message": f"Live voice error: {exc}"})
        except Exception:
            pass


# Serve built React frontend in production / Cloud Run
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found.")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
