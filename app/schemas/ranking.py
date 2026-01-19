from typing import List, Optional

from pydantic import BaseModel


class RankingEntry(BaseModel):
    user_id: int
    nickname: str
    points: int
    rank: int
    primary_badge_icon_url: Optional[str] = None
    primary_badge_name: Optional[str] = None


class RankingOverview(BaseModel):
    me: Optional[RankingEntry] = None
    leaders: List[RankingEntry]
