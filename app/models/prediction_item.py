from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.sql import text

from app.db.base import Base


class PredictionItem(Base):
    __tablename__ = "prediction_items"

    id = Column(Integer, primary_key=True, index=True)
    episode_id = Column(Integer, index=True)
    category = Column(String(50))
    question_text = Column(Text, nullable=False)
    odds = Column(Float)
    is_multiple_choice = Column(Boolean, nullable=False, server_default=text("false"))
    scope = Column(String(20))
    is_special = Column(Boolean, nullable=False, server_default=text("false"))
