import base64
import uuid
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.orchestrator import run_text_turn
from app.db.engine import get_db
from app.db.repositories import ConversationRepo, MemoryRepo
from app.schemas.api import ConverseResponse, Timings
from app.services import stt, tts

router = APIRouter(prefix="/api")


def _require_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError("invalid_input", f"{field} must be a valid UUID") from exc


def require_user_id(x_user_id: str = Header(...)) -> str:
    return _require_uuid(x_user_id, "X-User-Id")


@router.post("/converse")
def converse(
    request: Request,
    session_id: str = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
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
        if not transcript:
            raise AppError("invalid_input", "Provide either an audio file or a text field.")
    if len(transcript) > 2000:
        raise AppError("invalid_input", "message too long (max 2000 characters)")

    result = run_text_turn(
        ConversationRepo(db), MemoryRepo(db), user_id, session_id, transcript
    )

    audio_bytes, tts_ms = tts.synthesize(result.reply_text)
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None

    return ConverseResponse(
        transcript=transcript,
        reply_text=result.reply_text,
        audio_b64=audio_b64,
        memories_updated=result.memories_updated,
        timings=Timings(
            stt_ms=stt_ms,
            llm_ms=result.llm_ms,
            tool_ms=result.tool_ms,
            tts_ms=tts_ms,
            total_ms=int((perf_counter() - t0) * 1000),
        ),
        request_id=getattr(request.state, "request_id", "unknown"),
    )


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
