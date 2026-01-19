from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    id: int
    user_id: int
    nickname: str
    content: str
    created_at: datetime
    primary_badge_icon_url: Optional[str] = None
    primary_badge_name: Optional[str] = None


class ChatHistory(BaseModel):
    messages: List[ChatMessage]


class ChatSend(BaseModel):
    content: str
