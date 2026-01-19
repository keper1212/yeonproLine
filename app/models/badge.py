from sqlalchemy import Column, Integer, String, Text

from app.db.base import Base


class BadgeMaster(Base):
    __tablename__ = "badges_master"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    icon_url = Column(Text)
