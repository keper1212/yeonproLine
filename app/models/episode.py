from sqlalchemy import Boolean, Column, DateTime, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import text

from app.db.base import Base


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, index=True)
    episode_number = Column(Integer, nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    result_data = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default=text("'{}'"),
    )
