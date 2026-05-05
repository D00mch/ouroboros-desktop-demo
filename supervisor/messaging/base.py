from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    chat_id: Any
    user_id: Any
    text: str
    caption: str = ""
    image_data: Any = None
    raw_command: str = ""
