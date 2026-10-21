"""Normalized incident history; JSON contains actual source payloads, never fixtures."""
from datetime import datetime, timezone
from sqlalchemy import (JSON, CheckConstraint, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = 'schema_migrations'
    version: Mapped[int] = mapped_column(primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Incident(Base):
    __tablename__ = 'incidents'
    __table_args__ = (
        CheckConstraint("status IN ('FIRING','ACKNOWLEDGED','INVESTIGATING','MITIGATED','RESOLVED')"),
        CheckConstraint("severity IN ('INFO','WARNING','HIGH','CRITICAL')"),
        Index('ix_incident_scope', 'site', 'line', 'status', 'created_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50))
    family: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default='FIRING')
    site: Mapped[str] = mapped_column(String(100))
    line: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    investigating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mitigated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quiet_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey('incidents.id'))
    suggested_root_cause: Mapped[str] = mapped_column(Text, default='')
    root_cause: Mapped[str] = mapped_column(Text, default='')
    impact: Mapped[str] = mapped_column(Text, default='')
    remediation: Mapped[list] = mapped_column(JSON, default=list)
    remediation_actions: Mapped[str] = mapped_column(Text, default='')
    resolution_summary: Mapped[str] = mapped_column(Text, default='')
    mtta_seconds: Mapped[float | None] = mapped_column(Float)
    mttr_seconds: Mapped[float | None] = mapped_column(Float)


class AlertOccurrence(Base):
    __tablename__ = 'alert_occurrences'
    __table_args__ = (UniqueConstraint('fingerprint', 'starts_at'),
                     Index('ix_alert_state', 'incident_id', 'status'))
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    fingerprint: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    labels: Mapped[dict] = mapped_column(JSON)
    annotations: Mapped[dict] = mapped_column(JSON)


class IncidentEvent(Base):
    __tablename__ = 'incident_events'
    __table_args__ = (Index('ix_event_timeline', 'incident_id', 'timestamp', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    alert_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str | None] = mapped_column(String(24))
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), unique=True)


class Signal(Base):
    __tablename__ = 'signals'
    __table_args__ = (UniqueConstraint('site', 'line', 'source'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(100))
    line: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)


class Evidence(Base):
    __tablename__ = 'incident_evidence'
    __table_args__ = (Index('ix_evidence_incident', 'incident_id', 'source', 'received_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'))
    source: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)


class Report(Base):
    __tablename__ = 'incident_reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey('incidents.id'), unique=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)
