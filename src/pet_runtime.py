"""Per-turn state shared by a chat worker and its own UI callbacks."""
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TurnState:
    cancel_event: object = None
    token: object = None
    text: str = ''
    queued: bool = False
    emotion: object = None
    images: list = field(default_factory=list)
    transient_image_parts: list = field(default_factory=list)
    allowed_tools: object = None


TOOL_TURN = ContextVar('nijikori_tool_turn', default=None)
