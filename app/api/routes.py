import logging
import uuid
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse
from openai import OpenAIError
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.orchestrator import run_text_turn
from app.core.ratelimit import (
    CONVERSE_IP_LIMIT,
    CONVERSE_LIMIT,
    SPEECH_LIMIT,
    limiter,
)
from app.db.engine import get_db
from app.db.repositories import BookingRepo, ConversationRepo, MemoryRepo, MetricsRepo
from app.schemas.api import ConverseResponse, Timings, WorkflowInfo
from app.services import reply_cache, stt, tts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _require_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError("invalid_input", f"{field} must be a valid UUID") from exc


def require_user_id(x_user_id: str = Header(...)) -> str:
    return _require_uuid(x_user_id, "X-User-Id")


MAX_IMAGE_BYTES = 5 * 1024 * 1024


@router.post("/converse")
@limiter.limit(CONVERSE_LIMIT)
@limiter.limit(CONVERSE_IP_LIMIT, key_func=get_remote_address)
def converse(
    request: Request,
    session_id: str = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> ConverseResponse:
    t0 = perf_counter()
    session_id = _require_uuid(session_id, "session_id")

    stt_ms = 0
    if audio is not None:
        raw = audio.file.read()
        transcript, stt_ms = stt.transcribe(raw, audio.filename, audio.content_type)
    else:
        transcript = (text or "").strip()
        if not transcript and image is None:
            raise AppError("invalid_input", "Provide an audio file, text, or an image.")
    if len(transcript) > 2000:
        raise AppError("invalid_input", "message too long (max 2000 characters)")

    image_payload = None
    if image is not None:
        img_bytes = image.file.read()
        if not img_bytes:
            raise AppError("invalid_input", "the image upload was empty")
        if len(img_bytes) > MAX_IMAGE_BYTES:
            raise AppError("invalid_input", "image too large (max 5 MB)")
        mime = image.content_type or ""
        if not mime.startswith("image/"):
            raise AppError("invalid_input", "only image uploads are supported")
        image_payload = (img_bytes, mime)

    result = run_text_turn(
        ConversationRepo(db),
        MemoryRepo(db),
        BookingRepo(db),
        user_id,
        session_id,
        transcript,
        image=image_payload,
    )

    # TTS is NOT synthesized here: the client streams it from /api/speech/{id},
    # so the reply text arrives immediately and audio starts on first chunks.
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    reply_cache.put(request_id, result.reply_text)

    total_ms = int((perf_counter() - t0) * 1000)
    MetricsRepo(db).add(
        request_id=request_id,
        kind="voice" if audio is not None else "text",
        stt_ms=stt_ms,
        llm_ms=result.llm_ms,
        tool_ms=result.tool_ms,
        total_ms=total_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        workflow_status=result.workflow.get("status", "IDLE"),
    )
    logger.info(
        "turn kind=%s stt=%dms llm=%dms tools=%dms total=%dms tokens=%d/%d wf=%s",
        "voice" if audio is not None else "text",
        stt_ms,
        result.llm_ms,
        result.tool_ms,
        total_ms,
        result.tokens_in,
        result.tokens_out,
        result.workflow.get("status"),
    )

    return ConverseResponse(
        transcript=transcript,
        reply_text=result.reply_text,
        audio_url=f"/api/speech/{request_id}",
        workflow=WorkflowInfo(**result.workflow),
        memories_updated=result.memories_updated,
        timings=Timings(
            stt_ms=stt_ms,
            llm_ms=result.llm_ms,
            tool_ms=result.tool_ms,
            total_ms=total_ms,
        ),
        request_id=request_id,
    )


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    """Latency percentiles, token usage, and cost over the last 500 turns."""
    return MetricsRepo(db).summary()


@router.get("/speech/{request_id}")
@limiter.limit(SPEECH_LIMIT, key_func=get_remote_address)
def speech(request: Request, request_id: str) -> StreamingResponse:
    """Stream the TTS audio for a recent reply. Opaque id: no text in URLs."""
    text = reply_cache.get(request_id)
    if text is None:
        raise AppError("invalid_input", "unknown or expired speech id", status=404)
    try:
        stream = tts.stream_synthesize(text)
        first_chunk = next(stream, b"")
    except OpenAIError as exc:
        logger.error("speech stream failed to start: %s", exc)
        raise AppError("tts_failed", "speech synthesis unavailable", status=502) from exc

    def body():
        yield first_chunk
        yield from stream

    return StreamingResponse(body(), media_type="audio/mpeg")


@router.get("/bookings")
def list_bookings(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> dict:
    bookings = BookingRepo(db).list_for_user(user_id)
    return {
        "bookings": [
            {
                "id": b.id,
                "status": b.status,
                "slots": b.slots,
                "restaurant": (b.restaurant or {}).get("name"),
                "updated_at": b.updated_at.isoformat(),
            }
            for b in bookings
        ]
    }


@router.get("/memories")
def list_memories(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> dict:
    memories = MemoryRepo(db).list_for_user(user_id)
    return {
        "memories": [
            {
                "category": m.category,
                "key": m.key,
                "value": m.value,
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]
    }


@router.delete("/memories")
def delete_all_memories(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> dict:
    count = MemoryRepo(db).delete_all(user_id)
    return {"deleted": count}


@router.delete("/memories/{key}")
def delete_memory(
    key: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
) -> dict:
    deleted = MemoryRepo(db).delete(user_id, key)
    if not deleted:
        raise AppError("invalid_input", f"no memory named {key}", status=404)
    return {"deleted": key}
