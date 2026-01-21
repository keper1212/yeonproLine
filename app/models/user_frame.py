from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.sql import func

from app.db.base import Base


class UserFrame(Base):
    __tablename__ = "user_frames"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    frame_id = Column(Integer, ForeignKey("frame_masters.id"), nullable=False, index=True)
    earned_at = Column(DateTime, nullable=False, server_default=func.now())
