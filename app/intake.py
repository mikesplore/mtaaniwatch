import json
import logging
import re
from typing import Literal

import africastalking
import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Area, ProcessedInboundMessage, Report, SmsIntakeSession, Task, TaskStatus, TaskStatusHistory


logger = logging.getLogger(__name__)


class ExtractedReport(BaseModel):
    category: Literal["drainage_flooding", "other"] = "drainage_flooding"
    area: str | None = None
    landmark: str | None = None
    impact_reported: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=500)
    language: str = "en"


def fallback_extract(message: str, area_names: list[str]) -> ExtractedReport:
    normalized = message.casefold()
    # Prefer the explicitly reported neighborhood ("from Nyali", "in Nyali")
    # over a ward or landmark mentioned later ("Kongowea ward", "near market").
    area = None
    for name in area_names:
        variants = [name, *(part.strip() for part in name.split("/"))]
        for variant in variants:
            escaped = re.escape(variant.casefold())
            explicit_area = re.search(
                rf"(?:from|in|at|area(?:\s+is)?|eneo(?:\s+la)?|kutoka|huko)\s+"
                rf"(?:the\s+)?{escaped}(?![\w])",
                normalized,
            )
            if explicit_area:
                area = name
                break
        if area:
            break
    if not area:
        area = next(
            (
                name
                for name in area_names
                if name.casefold() in normalized
                or any(part.strip().casefold() in normalized for part in name.split("/"))
            ),
            None,
        )
    drainage_terms = (
        "drain", "gutter", "manhole", "culvert", "waterway", "channel", "storm water",
        "mfereji", "mifereji", "mtaro", "mitaro", "imeziba", "imezibwa", "imejaa",
        "blocked", "choked", "overflow", "flood", "flooding", "waterlogged", "standing water",
        "mafuriko", "maji yamesimama", "maji imesimama", "maji imefurika", "hazipiti", "hayapiti",
        "water cannot flow", "water is not flowing", "blocking water", "obstructing water",
    )
    swahili_terms = (
        "maji", "mfereji", "mifereji", "mtaro", "mitaro", "imeziba", "imezibwa",
        "imejaa", "barabara", "mvua", "takataka", "hazipiti", "hayapiti",
        "kuna", "huku", "karibu na", "imefurika", "yamefurika", "yamesimama",
    )
    english_terms = (
        "the", " and ", " is ", " are ", " along ", " opposite ", "causing", "which",
        "will", "with", "blocked", "drainage", "roadside", "please", "report",
    )
    swahili_score = sum(term in normalized for term in swahili_terms)
    english_score = sum(term in normalized for term in english_terms)
    language = "sw" if swahili_score > english_score else "en"
    return ExtractedReport(
        category="drainage_flooding" if any(term in normalized for term in drainage_terms) else "other",
        area=area,
        landmark=None,
        impact_reported=[],
        summary=message.strip()[:500],
        language=language,
    )


def extract_report(message: str, area_names: list[str]) -> ExtractedReport:
    if not settings.groq_api_key:
        return fallback_extract(message, area_names)

    prompt = (
        "Extract a resident's Mombasa drainage and flood-preparedness report. Use only facts stated in the message. "
        "Choose area only from this list, otherwise null: " + ", ".join(area_names) + ". "
        "Prefer the specific listed neighborhood over a larger sub-county or constituency; "
        "for example, for 'Tononoka in Mvita', choose Tononoka if it is in the list. "
        "When multiple listed areas are mentioned, prefer the one explicitly introduced as the resident's "
        "reporting area (for example, 'from Nyali') over areas mentioned as wards, landmarks, or nearby places. "
        "Return JSON keys category (drainage_flooding for blocked/choked drains, gutters, manholes, culverts, "
        "or waterways; flooding or standing water; or waste, silt, walls, or other objects obstructing water flow. "
        "Use other for issues unrelated to drainage or flood risk, such as garbage-only collection, streetlights, "
        "or general road damage), area, landmark, impact_reported "
        "(array of short stated impacts), summary (concise, preserve the specific issue and reported consequences, "
        "and write it in the same language as the resident's message), language "
        "(ISO 639-1 language code based on the original resident message; do not infer language from location names). "
        "Copy landmark wording from the message exactly where practical. Do not infer danger "
        "or verification. Message: " + message
    )
    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You extract structured fields from incident reports."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=12,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = ExtractedReport.model_validate(json.loads(content))
        if parsed.area and parsed.area.casefold() not in {name.casefold() for name in area_names}:
            parsed.area = None
        local = fallback_extract(message, area_names)
        if local.area:
            parsed.area = local.area
        if local.category == "drainage_flooding" and parsed.category == "other":
            parsed.category = "drainage_flooding"
        # Use the local detector as a guard against the LLM translating a
        # non-English message and then sending the resident an English reply.
        parsed.language = local.language
        return parsed
    except (httpx.HTTPError, KeyError, ValueError, TypeError, ValidationError) as exc:
        logger.warning("Groq report extraction failed (%s); using local fallback", exc)
        return fallback_extract(message, area_names)


def send_sms(phone: str, message: str, link_id: str | None = None) -> Literal["accepted", "simulated", "failed"]:
    if not settings.at_api_key:
        logger.info("SMS simulated; Africa's Talking credentials are not configured")
        return "simulated"

    if link_id and not settings.at_shortcode:
        logger.error("Cannot reply to an on-demand SMS without AT_SHORTCODE")
        return "failed"

    try:
        africastalking.initialize(settings.at_username, settings.at_api_key)
        sms = africastalking.SMS
        if link_id:
            payload = sms.send_premium(
                message,
                short_code=settings.at_shortcode,
                recipients=[phone],
                link_id=link_id,
                timeout=10,
            )
        else:
            payload = sms.send(
                message,
                [phone],
                sender_id=settings.at_sender_id,
                timeout=10,
            )
        recipients = payload.get("SMSMessageData", {}).get("Recipients", [])
        status_code = recipients[0].get("statusCode") if recipients else None
        if status_code in (100, 101, 102, 201):
            logger.info("Africa's Talking accepted outbound SMS (status %s)", status_code)
            return "accepted"
        logger.warning("Africa's Talking did not accept outbound SMS (status %s)", status_code)
        return "failed"
    except Exception as exc:
        logger.error("Africa's Talking SMS send failed: %s", exc)
        return "failed"


def confirmation_text(candidate: ExtractedReport) -> str:
    issue = candidate.summary.strip().rstrip(".") or "drainage or flooding issue"
    # Summaries often already include the landmark as part of the incident
    # description. Only append the location field when it adds new information.
    location_parts = [
        part
        for part in (candidate.area, candidate.landmark)
        if part and part.casefold() not in issue.casefold()
    ]
    location = ", ".join(location_parts)
    if candidate.language.casefold().startswith("sw"):
        if location:
            return f"Tumeelewa: {issue}. Eneo/alama: {location}. Jibu NDIYO kuthibitisha au tuma marekebisho."
        if candidate.area:
            return f"Tumeelewa: {issue}. Jibu NDIYO kuthibitisha au tuma marekebisho."
        return f"Tumeelewa: {issue}. Tafadhali tuma eneo la Mombasa."
    if location:
        return f"We understood: {issue}. Area/landmark: {location}. Reply YES to confirm, or send a correction."
    if candidate.area:
        return f"We understood: {issue}. Reply YES to confirm, or send a correction."
    return f"We understood: {issue}. Please send the Mombasa area."


def _completed_reply(candidate: ExtractedReport, reference: str) -> str:
    if candidate.language.casefold().startswith("sw"):
        return f"Asante. Ripoti yako imesajiliwa kwa nambari {reference}. Mratibu ataipitia."
    return f"Thank you. Your report reference is {reference}. A coordinator will review it."


def parse_callback(body: bytes) -> dict[str, str]:
    from urllib.parse import parse_qs

    values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: entries[-1] for key, entries in values.items() if entries}


def _send(phone: str, message: str, link_id: str | None = None) -> Literal["accepted", "simulated", "failed"]:
    delivery = send_sms(phone, message, link_id)
    if delivery == "accepted":
        logger.info("Resident SMS accepted by Africa's Talking (handset delivery not confirmed)")
    elif delivery == "simulated":
        logger.info("Simulated resident SMS response prepared")
    return delivery


def send_resolution_sms(report: Report) -> Literal["accepted", "simulated", "failed"]:
    if not report.resident_phone:
        logger.info("Resolution SMS simulated; report %s has no resident phone number", report.reference)
        return "simulated"
    if (report.language or "en").casefold().startswith("sw"):
        message = f"Ripoti {report.reference} imetatuliwa. Asante kwa kuituma."
    else:
        message = f"Report {report.reference} has been marked resolved. Thank you for reporting it."
    return _send(report.resident_phone, message, report.sms_link_id)


def process_inbound_sms(fields: dict[str, str], db: Session) -> None:
    phone = fields.get("from", "").strip()
    message = fields.get("text", "").strip()
    message_id = fields.get("id") or fields.get("messageId")
    link_id = fields.get("linkId") or fields.get("link_id")
    if not phone or not message:
        logger.warning("Ignoring inbound SMS without sender or message")
        return

    message_key = f"{fields.get('channel', 'sms')}:{message_id}" if message_id else None

    # Serialize concurrent webhook/poller deliveries for a sender, including the
    # first message when no SmsIntakeSession row exists yet.
    db.execute(
        text("SELECT pg_advisory_xact_lock(0, hashtext(:sender_phone))"),
        {"sender_phone": phone},
    )
    # Claim the provider ID after obtaining the per-sender transaction lock.
    # The claim remains in the same transaction as the intake update.
    if message_key:
        claimed = db.execute(
            text(
                "INSERT INTO processed_inbound_messages (message_key, processed_at) "
                "VALUES (:message_key, CURRENT_TIMESTAMP) ON CONFLICT (message_key) DO NOTHING"
            ),
            {"message_key": message_key},
        )
        if claimed.rowcount == 0:
            db.rollback()
            return
    session = db.scalar(
        select(SmsIntakeSession).where(SmsIntakeSession.sender_phone == phone).with_for_update()
    )
    if session and fields.get("channel") == "voice":
        # A completed recording starts a fresh report conversation for this
        # resident instead of being interpreted as an SMS correction.
        session.stage = "completed"

    area_names = list(db.scalars(select(Area.name).order_by(Area.name)))
    yes = message.casefold() in {"yes", "y", "ok", "okay", "ndio", "ndiyo", "sawa", "ndio sawa"}
    no = message.casefold() in {"no", "n", "hapana", "si sawa"}

    if session is None or session.stage == "completed":
        short_acknowledgment = message.casefold() in {
            "yes", "y", "ok", "okay", "ndio", "ndiyo", "sawa", "ndio sawa",
            "no", "n", "hapana", "si sawa",
        }
        if short_acknowledgment or len(message) < 3:
            if any(term in message.casefold() for term in ("ndio", "ndiyo", "sawa", "hapana")):
                reply = "Kutuma ripoti mpya, eleza tatizo la mifereji/mafuriko na eneo au alama ya karibu."
            else:
                reply = "To start a report, describe a drainage or flooding issue and its area or nearby landmark."
            db.commit()
            _send(phone, reply, link_id)
            return
        candidate = extract_report(message, area_names)
        if fields.get("channel") == "voice" and fields.get("language") in {"en", "sw"}:
            candidate.language = fields["language"]
        if candidate.category == "other":
            reply = (
                "Kwa sasa tunapokea ripoti zinazohusu mifereji au hatari ya mafuriko. Tafadhali eleza tatizo na eneo lake la Mombasa."
                if candidate.language.casefold().startswith("sw")
                else "This demo currently accepts drainage and flood-risk reports. Please describe the issue and its Mombasa area."
            )
            db.commit()
            _send(
                phone,
                reply,
                link_id,
            )
            return
        if session is None:
            session = SmsIntakeSession(sender_phone=phone)
            db.add(session)
        session.stage = "awaiting_confirmation" if candidate.area else "awaiting_location"
        session.original_text = message
        session.candidate = candidate.model_dump()
        session.last_message_id = message_id
        reply = confirmation_text(candidate)
    elif session.stage == "awaiting_location":
        combined = f"{session.original_text}\nLocation clarification: {message}"
        candidate = extract_report(combined, area_names)
        session.original_text = combined
        session.candidate = candidate.model_dump()
        session.stage = "awaiting_confirmation" if candidate.area else "awaiting_location"
        session.last_message_id = message_id
        reply = confirmation_text(candidate)
    elif session.stage == "awaiting_confirmation" and yes:
        candidate = ExtractedReport.model_validate(session.candidate)
        report = Report(
            reference="pending",
            category="drainage_flooding",
            area=candidate.area,
            landmark=candidate.landmark,
            impact_reported=candidate.impact_reported,
            summary=candidate.summary,
            language=candidate.language,
            source="voice_call" if fields.get("channel") == "voice" else "sms",
            resident_phone=phone,
            sms_link_id=link_id,
            is_demo=settings.at_username.casefold() == "sandbox",
            verified=False,
            location_uncertain=False,
        )
        if candidate.area:
            report.area_ref = db.scalar(select(Area).where(Area.name.ilike(candidate.area)))
        db.add(report)
        db.flush()
        report.reference = f"MW-{report.id:06d}"
        task = Task(report=report, status=TaskStatus.REPORTED)
        acknowledgment_event = TaskStatusHistory(
            status=TaskStatus.REPORTED,
            note=f"Resident confirmed {('voice' if fields.get('channel') == 'voice' else 'SMS')} report",
        )
        task.history.append(acknowledgment_event)
        db.add(task)
        session.stage = "completed"
        session.last_message_id = message_id
        db.commit()
        reply = _completed_reply(candidate, report.reference)
        delivery = _send(phone, reply, link_id)
        if delivery == "accepted":
            acknowledgment_event.note = "Resident confirmed SMS report. Acknowledgment accepted by Africa's Talking; handset delivery is unconfirmed."
        elif delivery == "simulated":
            acknowledgment_event.note = "Resident confirmed SMS report. Acknowledgment shown in simulated mode; not delivered."
        else:
            acknowledgment_event.note = "Resident confirmed SMS report. Provider send failed; acknowledgment shown in simulated mode."
        db.commit()
        return
    elif session.stage == "awaiting_confirmation" and no:
        session.stage = "awaiting_correction"
        session.last_message_id = message_id
        reply = "Please send the corrected Mombasa area and nearest landmark for the drainage or flooding issue."
    else:
        combined = f"{session.original_text}\nResident correction: {message}"
        candidate = extract_report(combined, area_names)
        session.original_text = combined
        session.candidate = candidate.model_dump()
        session.stage = "awaiting_confirmation" if candidate.area else "awaiting_location"
        session.last_message_id = message_id
        reply = confirmation_text(candidate)

    db.commit()
    _send(phone, reply, link_id)
