from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClusterReviewStatus, TaskStatus


class ReportCreate(BaseModel):
    category: str = "drainage_flooding"
    area: str | None = Field(default=None, max_length=120)
    landmark: str | None = Field(default=None, max_length=200)
    impact_reported: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=3, max_length=4000)
    language: str | None = Field(default=None, max_length=12)
    source: str = "manual"
    resident_phone: str | None = Field(default=None, max_length=32)
    is_demo: bool = False


class ReportRead(ReportCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
    verified: bool
    created_at: datetime


class ReportVerificationUpdate(BaseModel):
    verified: bool


class AreaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_demo: bool


class CrewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    home_area_id: int | None
    is_demo: bool


class TaskAssign(BaseModel):
    crew_name: str = Field(min_length=1, max_length=120)


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    note: str | None = Field(default=None, max_length=500)


class TaskStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: TaskStatus
    note: str | None
    created_at: datetime


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    crew_name: str | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    history: list[TaskStatusHistoryRead]


class ClusterReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
    area: str | None
    landmark: str | None
    summary: str
    verified: bool
    is_demo: bool
    created_at: datetime


class IncidentClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    area_name: str
    status: ClusterReviewStatus
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reports: list[ClusterReportRead]


class ClusterSuggestionResult(BaseModel):
    created: int


class ClusterReviewUpdate(BaseModel):
    status: ClusterReviewStatus
    note: str | None = Field(default=None, max_length=500)
