from pydantic import BaseModel, Field


class WorkflowInfo(BaseModel):
    status: str = "IDLE"
    slots: dict = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    options: list[dict] | None = None


class Timings(BaseModel):
    stt_ms: int = 0
    llm_ms: int = 0
    tool_ms: int = 0
    tts_ms: int = 0
    total_ms: int = 0


class ConverseResponse(BaseModel):
    transcript: str
    reply_text: str
    audio_b64: str | None = None
    workflow: WorkflowInfo = Field(default_factory=WorkflowInfo)
    memories_updated: bool = False
    timings: Timings = Field(default_factory=Timings)
    request_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
