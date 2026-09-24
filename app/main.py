import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import check_database_connection, get_db
from app.intake import parse_callback, process_inbound_sms, send_resolution_sms
from app.models import (
    Area,
    ClusterReviewStatus,
    Crew,
    IncidentCluster,
    Report,
    Task,
    TaskStatus,
    TaskStatusHistory,
)
from app.schemas import (
    AreaRead,
    ClusterReviewUpdate,
    ClusterSuggestionResult,
    CrewRead,
    IncidentClusterRead,
    ReportCreate,
    ReportRead,
    TaskAssign,
    TaskRead,
    TaskStatusUpdate,
)


app = FastAPI(title=settings.app_name, version="0.1.0")
logger = logging.getLogger(__name__)
DASHBOARD_FILE = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=FileResponse, tags=["coordinator dashboard"])
def coordinator_dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_FILE, media_type="text/html")


@app.post("/webhooks/africastalking/sms", response_class=PlainTextResponse, tags=["resident intake"])
async def africastalking_sms_webhook(
    request: Request, db: Session = Depends(get_db)
) -> PlainTextResponse:
    if settings.at_webhook_token and request.query_params.get("token") != settings.at_webhook_token:
        raise HTTPException(status_code=403, detail="Invalid webhook token")
    fields = parse_callback(await request.body())
    sender = fields.get("from", "").strip()
    masked_sender = f"***{sender[-4:]}" if sender else "missing"
    logger.info(
        "Africa's Talking SMS callback received: fields=%s sender=%s text_length=%d message_id=%s",
        sorted(fields),
        masked_sender,
        len(fields.get("text", "").strip()),
        fields.get("id") or fields.get("messageId") or "missing",
    )
    process_inbound_sms(fields, db)
    return PlainTextResponse("Received")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        check_database_connection()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ready", "database": "connected"}


@app.get("/areas", response_model=list[AreaRead], tags=["reference data"])
def list_areas(db: Session = Depends(get_db)) -> list[Area]:
    return list(db.query(Area).order_by(Area.name).all())


@app.get("/crews", response_model=list[CrewRead], tags=["reference data"])
def list_crews(db: Session = Depends(get_db)) -> list[Crew]:
    return list(db.query(Crew).order_by(Crew.name).all())


@app.post("/reports", response_model=ReportRead, status_code=201, tags=["reports"])
def create_report(payload: ReportCreate, db: Session = Depends(get_db)) -> Report:
    report = Report(**payload.model_dump(), reference="pending")
    if payload.area:
        report.area_ref = db.query(Area).filter(Area.name.ilike(payload.area)).first()
    db.add(report)
    db.flush()
    report.reference = f"MW-{report.id:06d}"
    task = Task(report=report, status=TaskStatus.REPORTED)
    task.history.append(TaskStatusHistory(status=TaskStatus.REPORTED, note="Report received"))
    db.add(task)
    db.commit()
    db.refresh(report)
    return report


@app.get("/reports", response_model=list[ReportRead], tags=["reports"])
def list_reports(db: Session = Depends(get_db)) -> list[Report]:
    return list(db.query(Report).order_by(Report.created_at.desc()).all())


@app.get("/reports/{reference}", response_model=ReportRead, tags=["reports"])
def get_report(reference: str, db: Session = Depends(get_db)) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.get("/tasks", response_model=list[TaskRead], tags=["tasks"])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.query(Task).order_by(Task.created_at.desc()).all())


@app.post(
    "/clusters/suggest",
    response_model=ClusterSuggestionResult,
    tags=["possible incident clusters"],
)
def suggest_incident_clusters(db: Session = Depends(get_db)) -> ClusterSuggestionResult:
    active_reports = (
        db.query(Report)
        .join(Task, Task.report_id == Report.id)
        .filter(
            Report.area_id.is_not(None),
            Task.status.in_([TaskStatus.REPORTED, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS]),
        )
        .all()
    )
    groups: dict[tuple[str, int], list[Report]] = defaultdict(list)
    for report in active_reports:
        groups[(report.category, report.area_id)].append(report)

    created = 0
    for (category, area_id), reports in groups.items():
        if len(reports) < 2:
            continue
        reports.sort(key=lambda item: item.id)
        fingerprint = f"{category}:{area_id}:{','.join(str(item.id) for item in reports)}"
        existing = db.query(IncidentCluster.id).filter(IncidentCluster.fingerprint == fingerprint).first()
        if existing:
            continue
        db.add(
            IncidentCluster(
                category=category,
                area_id=area_id,
                fingerprint=fingerprint,
                status=ClusterReviewStatus.SUGGESTED,
                reports=reports,
            )
        )
        created += 1

    db.commit()
    return ClusterSuggestionResult(created=created)


@app.get("/clusters", response_model=list[IncidentClusterRead], tags=["possible incident clusters"])
def list_incident_clusters(db: Session = Depends(get_db)) -> list[IncidentCluster]:
    return list(db.query(IncidentCluster).order_by(IncidentCluster.created_at.desc()).all())


@app.patch(
    "/clusters/{cluster_id}",
    response_model=IncidentClusterRead,
    tags=["possible incident clusters"],
)
def review_incident_cluster(
    cluster_id: int, payload: ClusterReviewUpdate, db: Session = Depends(get_db)
) -> IncidentCluster:
    cluster = db.query(IncidentCluster).filter(IncidentCluster.id == cluster_id).first()
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster suggestion not found")
    if payload.status not in {ClusterReviewStatus.ACCEPTED, ClusterReviewStatus.DISMISSED}:
        raise HTTPException(status_code=422, detail="A suggestion can only be accepted or dismissed")
    if cluster.status != ClusterReviewStatus.SUGGESTED:
        raise HTTPException(status_code=409, detail="This cluster suggestion has already been reviewed")

    cluster.status = payload.status
    cluster.review_note = payload.note
    cluster.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cluster)
    return cluster


@app.post("/tasks/{task_id}/assign", response_model=TaskRead, tags=["tasks"])
def assign_task(task_id: int, payload: TaskAssign, db: Session = Depends(get_db)) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.REPORTED:
        raise HTTPException(status_code=409, detail="Only reported tasks can be assigned")
    crew = db.query(Crew).filter(Crew.name == payload.crew_name).first()
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    task.crew_name = payload.crew_name
    task.crew_ref = crew
    task.status = TaskStatus.ASSIGNED
    task.history.append(TaskStatusHistory(status=TaskStatus.ASSIGNED, note=f"Assigned to {payload.crew_name}"))
    db.commit()
    db.refresh(task)
    return task


@app.patch("/tasks/{task_id}/status", response_model=TaskRead, tags=["tasks"])
def update_task_status(
    task_id: int, payload: TaskStatusUpdate, db: Session = Depends(get_db)
) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    allowed_transitions = {
        TaskStatus.REPORTED: {TaskStatus.CANCELLED},
        TaskStatus.ASSIGNED: {TaskStatus.IN_PROGRESS},
        TaskStatus.IN_PROGRESS: {TaskStatus.RESOLVED},
    }
    if payload.status not in allowed_transitions.get(task.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move task from {task.status} to {payload.status}")

    task.status = payload.status
    status_event = TaskStatusHistory(status=payload.status, note=payload.note)
    task.history.append(status_event)
    db.commit()
    if payload.status == TaskStatus.RESOLVED:
        delivery = send_resolution_sms(task.report)
        if delivery == "accepted":
            outcome = "resolution SMS accepted by Africa's Talking; handset delivery is unconfirmed"
        elif delivery == "simulated":
            outcome = "resolution SMS shown in simulated mode; not delivered"
        else:
            outcome = "provider send failed; resolution update shown in simulated mode"
        status_event.note = f"{payload.note}. {outcome}" if payload.note else outcome.capitalize()
        db.commit()
    db.refresh(task)
    return task
