from sqlalchemy import BigInteger, Column, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import text

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    nickname = Column(String(50), unique=True, nullable=False)
    email = Column(String(255), unique=True)
    google_id = Column(String(255), unique=True)
    points = Column(Integer, nullable=False, server_default=text("0"))
    personality_analysis = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default=text("'{}'"),
    )
