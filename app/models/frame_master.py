from sqlalchemy import Column, Integer, String, Text

from app.db.base import Base


class FrameMaster(Base):
    __tablename__ = "frame_masters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    icon_url = Column(Text, nullable=False)
    price = Column(Integer, nullable=False, default=800)
    description = Column(Text)
