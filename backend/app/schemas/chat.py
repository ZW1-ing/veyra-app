"""对话出入参。"""

from typing import Literal

from pydantic import BaseModel, Field

from .kb import SourceOut


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1)
    use_knowledge: bool = True
    max_steps: int | None = Field(default=None, ge=1, le=16)
    # 不传就沿用会话本身的模式；传了会覆盖并写回会话
    mode: Literal["single", "swarm"] | None = None


class ChatResponse(BaseModel):
    session_id: str
    text: str
    steps: int
    usage: dict[str, int]
    mode: str = "single"
    sources: list[SourceOut] = []
    tool_calls: list[str] = []
    members: list[dict] = []
