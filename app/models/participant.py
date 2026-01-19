from sqlalchemy import Boolean, Column, Integer, String, Text

from app.db.base import Base


class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    age = Column(Integer)
    job = Column(String(100))
    image_url = Column(Text)
    gender = Column(String(10))
    is_newcomer = Column(Boolean)
