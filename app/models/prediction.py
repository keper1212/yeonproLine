from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import text

from app.db.base import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=False, index=True)
    prediction_item_id = Column(Integer, ForeignKey("prediction_items.id"), index=True)
    prediction_type = Column(String(50), nullable=False)
    target_participant_id = Column(Integer, ForeignKey("participants.id"))
    selected_value = Column(Text, nullable=False)
    betting_points = Column(Integer, nullable=False, server_default=text("0"))
    earned_points = Column(Integer, nullable=False, server_default=text("0"))
    is_correct = Column(Boolean)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
