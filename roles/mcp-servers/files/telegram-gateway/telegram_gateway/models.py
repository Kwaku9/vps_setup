from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommandStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResponseType(str, Enum):
    TEXT = "text"
    CODE = "code"
    LOG = "log"
    STRUCTURED = "structured"
    AUDIO = "audio"
    VIDEO = "video"
    VOICE = "voice"
    DOCUMENT = "document"
    STDERR = "stderr"
    APPROVAL = "approval"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    # Requester stopped waiting (its poll window is shorter than our TTL) and
    # closed the row itself. Distinct from EXPIRED, which is the TTL elapsing.
    ABANDONED = "abandoned"


class Command(BaseModel):
    id: int
    telegram_user_id: int
    telegram_chat_id: int
    agent_type: str
    message: str
    status: CommandStatus
    created_at: datetime
    completed_at: datetime | None = None


class Response(BaseModel):
    id: int
    command_id: int
    agent_type: str
    response_type: ResponseType
    content: str
    payload: dict[str, Any] | None = None
    telegram_chat_id: int
    sent: bool
    created_at: datetime


class AgentConfig(BaseModel):
    agent_type: str
    backend: str = "claude-cli"  # "claude-cli" or "litellm"
    system_prompt: str
    model: str
    max_tokens: int
    enabled: bool
    updated_at: datetime


# --- MCP Tool Request/Response Models ---

class SendMessageRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send the message to")
    text: str = Field(..., description="Message text to send")
    parse_mode: str | None = Field(None, description="Parse mode: MarkdownV2, HTML, or null")


class SendCodeRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send the code to")
    code: str = Field(..., description="Code content to send")
    language: str = Field("", description="Programming language for syntax highlighting")


class SendNotificationRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send the notification to")
    title: str = Field(..., description="Notification title (shown in bold)")
    body: str = Field(..., description="Notification body text")


class UpdateCommandStatusRequest(BaseModel):
    command_id: int = Field(..., description="Command ID to update")
    status: CommandStatus = Field(..., description="New status: completed or failed")
    response_text: str | None = Field(None, description="Optional response text to insert")


class SendAudioRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send audio to")
    audio: str = Field(..., description="URL or file_id of the audio file")
    caption: str | None = Field(None, description="Optional caption for the audio")
    title: str | None = Field(None, description="Track title")
    performer: str | None = Field(None, description="Performer/artist name")


class SendVideoRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send video to")
    video: str = Field(..., description="URL or file_id of the video file")
    caption: str | None = Field(None, description="Optional caption for the video")


class SendVoiceRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send voice message to")
    voice: str = Field(..., description="URL or file_id of the voice message (.ogg)")
    caption: str | None = Field(None, description="Optional caption for the voice message")


class SendDocumentRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send document to")
    document: str = Field(..., description="URL or file_id of the document")
    caption: str | None = Field(None, description="Optional caption for the document")


class SendStderrRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send stderr output to")
    stderr_text: str = Field(..., description="Stderr output text")
    command_id: int | None = Field(None, description="Optional originating command ID")


class SendApprovalRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send approval request to")
    prompt_text: str = Field(..., description="Description of what needs approval")
    command_id: int | None = Field(None, description="Optional originating command ID")
    requested_by: str | None = Field(None, description="Username of the person requesting approval")
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata for the approval")


class AbandonApprovalRequest(BaseModel):
    approval_id: int = Field(..., ge=1, description="Approval to close out")
    reason: str | None = Field(None, description="Why the requester stopped waiting")


class ApprovalResponse(BaseModel):
    ok: bool
    approval_id: int | None = None
    status: str | None = None
    error: str | None = None


class SendResponse(BaseModel):
    ok: bool
    message_id: int | None = None
    error: str | None = None


class GrafanaScreenshotRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat ID to send the screenshot to")
    dashboard_uid: str = Field(..., description="Grafana dashboard UID")
    panel_id: int | None = Field(None, description="Panel ID for a single panel (omit for full dashboard)")
    from_time: str = Field("now-1h", description="Start time (e.g. now-1h, now-6h, now-24h)")
    to_time: str = Field("now", description="End time (e.g. now)")
    width: int = Field(1000, description="Image width in pixels")
    height: int = Field(500, description="Image height in pixels")
    render_timeout: int = Field(15, description="Seconds for Grafana renderer to wait for panel data to load")
    caption: str | None = Field(None, description="Optional caption for the screenshot")
