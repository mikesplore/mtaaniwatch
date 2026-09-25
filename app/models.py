from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, JSON, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(StrEnum):
    REPORTED = "reported"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ClusterReviewStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


incident_cluster_reports = Table(
    "incident_cluster_reports",
    Base.metadata,
    Column("cluster_id", ForeignKey("incident_clusters.id"), primary_key=True),
    Column("report_id", ForeignKey("reports.id"), primary_key=True),
)


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    crews: Mapped[list["Crew"]] = relationship(back_populates="home_area")


class Crew(Base):
    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    home_area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    home_area: Mapped[Area | None] = relationship(back_populates="crews")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(64), default="drainage_flooding")
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    landmark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    impact_reported: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    resident_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sms_link_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    area_ref: Mapped[Area | None] = relationship()
    task: Mapped["Task | None"] = relationship(back_populates="report", uselist=False)
    incident_clusters: Mapped[list["IncidentCluster"]] = relationship(
        secondary=incident_cluster_reports, back_populates="reports"
    )


class IncidentCluster(Base):
    __tablename__ = "incident_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(64))
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    fingerprint: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    status: Mapped[ClusterReviewStatus] = mapped_column(
        Enum(ClusterReviewStatus, name="cluster_review_status"),
        default=ClusterReviewStatus.SUGGESTED,
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    area_ref: Mapped[Area] = relationship()
    reports: Mapped[list[Report]] = relationship(
        secondary=incident_cluster_reports, back_populates="incident_clusters"
    )

    @property
    def area_name(self) -> str:
        return self.area_ref.name


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), unique=True)
    crew_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    crew_id: Mapped[int | None] = mapped_column(ForeignKey("crews.id"), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.REPORTED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    crew_ref: Mapped[Crew | None] = relationship()
    report: Mapped[Report] = relationship(back_populates="task")
    history: Mapped[list["TaskStatusHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStatusHistory.created_at"
    )


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="history")


class SmsIntakeSession(Base):
    __tablename__ = "sms_intake_sessions"

    sender_phone: Mapped[str] = mapped_column(String(32), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32))
    original_text: Mapped[str] = mapped_column(Text)
    candidate: Mapped[dict] = mapped_column(JSON)
    last_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProcessedInboundMessage(Base):
    __tablename__ = "processed_inbound_messages"

    message_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SmsPollCursor(Base):
    __tablename__ = "sms_poll_cursors"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_received_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
