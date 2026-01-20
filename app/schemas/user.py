from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, constr


class TokenRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    nickname: str
    points: int
    badges: List[str]


class NicknameUpdate(BaseModel):
    nickname: constr(min_length=2, max_length=50)


class UserAnalysis(BaseModel):
    label: str
    description: str
    confidence: float


class UserSummary(BaseModel):
    nickname: str
    points: int
    accuracy_rate: float
    participated_episodes: int
    primary_badge_id: Optional[int] = None
    primary_badge_name: Optional[str] = None
    primary_badge_icon_url: Optional[str] = None


class BadgeItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    is_owned: bool
    earned_at: Optional[datetime] = None


class BadgeCollection(BaseModel):
    badges: List[BadgeItem]


class AccuracyPoint(BaseModel):
    episode_id: int
    accuracy_rate: float
    correct_predictions: int
    total_predictions: int


class AccuracyTrend(BaseModel):
    points: List[AccuracyPoint]


class PredictionItem(BaseModel):
    id: int
    prediction_item_id: Optional[int] = None
    prediction_type: str
    question_text: Optional[str] = None
    category: Optional[str] = None
    target_participant_id: Optional[int] = None
    selected_value: str
    betting_points: int
    is_correct: Optional[bool] = None
    earned_points: int


class EpisodePredictions(BaseModel):
    episode_id: int
    predictions: List[PredictionItem]


class PredictionHistory(BaseModel):
    episodes: List[EpisodePredictions]
