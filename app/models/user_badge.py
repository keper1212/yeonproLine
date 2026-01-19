from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer

from app.db.base import Base


class UserBadge(Base):
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    badge_id = Column(Integer, ForeignKey("badges_master.id"), nullable=False, index=True)
    earned_at = Column(DateTime)
