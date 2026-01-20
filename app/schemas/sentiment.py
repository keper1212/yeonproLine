from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ParticipantSummary(BaseModel):
    id: int
    name: str
    gender: Optional[str] = None
    image_url: Optional[str] = None


class SentimentPoint(BaseModel):
    captured_at: datetime
    support_rate: int
    episode_id: Optional[int] = None


class SentimentEvent(BaseModel):
    event_type: str
    delta: int
    start_at: datetime
    end_at: datetime


class SentimentOverview(BaseModel):
    female_id: Optional[int] = None
    male_id: Optional[int] = None
    target_id: Optional[int] = None
    support_rate: int
    delta_5m: int
    history: List[SentimentPoint]
    summary: Optional[str] = None
    event: Optional[SentimentEvent] = None
