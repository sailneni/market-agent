from sqlalchemy import Column, String, Float, DateTime, Text
from app.database import Base
from datetime import datetime

class Signal(Base):
    __tablename__ = "signals"
    id         = Column(String, primary_key=True)
    ticker     = Column(String, index=True)
    source     = Column(String)          # youtube / bloomberg / sec / price
    claim      = Column(Text)
    verified   = Column(String)          # confirmed / unconfirmed / false
    sentiment  = Column(String)          # bullish / bearish / neutral
    risk_score = Column(Float)           # 0.0 - 1.0
    tactic     = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
