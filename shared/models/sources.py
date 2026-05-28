from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from shared.database.base import Base
from datetime import datetime


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id = Column(Integer, primary_key=True)
    trace_id = Column(String(36), nullable=False, index=True)
    event_type = Column(String(50))
    source_name = Column(String(255))
    service = Column(String(50))
    step = Column(String(50))
    status = Column(String(20), nullable=False)
    ai_signals = Column(JSONB)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_pipeline_logs_trace_service", "trace_id", "service"),
        Index("ix_pipeline_logs_status_created", "status", "created_at"),
    )


class HttpApiSource(Base):
    __tablename__ = "http_api_sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    url = Column(Text, nullable=False)
    data_path = Column(String(255))
    id_field = Column(String(255))
    text_field = Column(String(255))
    eval_str = Column(Text)
    auth_type = Column(String(20))
    auth_key = Column(String(255))
    auth_value = Column(String(500))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScraperSource(Base):
    __tablename__ = "scraper_sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    rss = Column(Text)
    filter_tag = Column(String(100))
    filter_value = Column(String(500))
    listing_url = Column(Text)
    base_url = Column(Text)
    box_selector = Column(Text)
    post_selector = Column(Text)
    is_ssr = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
