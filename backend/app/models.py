from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String, Text
from .database import Base
class Generation(Base):
    __tablename__ = "generations"
    id = Column(String(36), primary_key=True)
    headline = Column(String(500), nullable=False)
    article_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    analysis_json = Column(Text, nullable=False, default="{}")
    image_prompt = Column(Text, nullable=False)
    provider = Column(String(80), nullable=False)
    status = Column(String(40), nullable=False, default="completed")
    image_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
