from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ParticipantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    image_url: Optional[str] = None
    gender: Optional[str] = None
    is_newcomer: Optional[bool] = None


class EpisodeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_number: int
    start_time: datetime


class SeasonCouplePair(BaseModel):
    female_id: int
    male_id: int


class PredictionAnswer(BaseModel):
    prediction_item_id: int
    selected_value: str
    target_participant_id: Optional[int] = None


class PredictionItemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: Optional[int] = None
    category: Optional[str] = None
    question_text: str
    odds: Optional[float] = None
    is_multiple_choice: bool = False
    scope: Optional[str] = None
    is_special: bool = False


class PredictionsOverview(BaseModel):
    next_episode: Optional[EpisodeSummary] = None
    is_admin: bool = False
    season_start_open: bool
    season_final_vote_open: bool
    season_couples_locked: bool
    season_couples: List[SeasonCouplePair] = Field(default_factory=list)
    episode_predictions_locked: bool = False
    participants: List[ParticipantSummary] = Field(default_factory=list)
    episode_items: List[PredictionItemSummary] = Field(default_factory=list)
    episode_answers: List[PredictionAnswer] = Field(default_factory=list)
    season_final_zero_vote: Optional[int] = None
    season_popular_one: Optional[int] = None


class SeasonCouplesSubmit(BaseModel):
    pairs: List[SeasonCouplePair]


class EpisodePredictionsSubmit(BaseModel):
    episode_id: int
    answers: List[PredictionAnswer]


class SeasonFinalVoteSubmit(BaseModel):
    final_zero_vote_participant_id: Optional[int] = None
    season_popular_participant_id: Optional[int] = None


class AdminSeasonCouplesSubmit(BaseModel):
    pairs: List[SeasonCouplePair]


class AdminSeasonFinalSubmit(BaseModel):
    final_zero_vote_participant_id: Optional[int] = None
    season_popular_participant_id: Optional[int] = None


class AdminEpisodeResultsSubmit(BaseModel):
    episode_id: int
    answers: List[PredictionAnswer]
