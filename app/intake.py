import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import africastalking
import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Area, ProcessedInboundMessage, Report, SmsIntakeSession, Task, TaskStatus, TaskStatusHistory


logger = logging.getLogger(__name__)

# Keep every extracted value inside its report column width. A model answer that
# runs long should shorten the stored field, never fail the insert that saves a
# resident's report.
MAX_AREA_LENGTH = 120
MAX_LANDMARK_LENGTH = 200
MAX_SUMMARY_LENGTH = 500
MAX_LANGUAGE_LENGTH = 12
MAX_IMPACT_ITEMS = 6

AFFIRMATIVE_REPLIES = frozenset({"yes", "y", "ok", "okay", "ndio", "ndiyo", "sawa", "ndio sawa"})
NEGATIVE_REPLIES = frozenset({"no", "n", "hapana", "si sawa"})

# Wording that puts a report in the drainage and flood-risk scope on its own.
STRONG_DRAINAGE_TERMS = (
    "drain", "drainage", "gutter", "manhole", "culvert", "waterway", "storm water", "stormwater",
    "sewer", "sewage", "sewerage", "wastewater", "raw sewage",
    "flood", "flooding", "waterlogged", "standing water", "stagnant water",
    "mfereji", "mifereji", "mtaro", "mitaro", "mafuriko",
    "maji yamesimama", "maji imesimama", "maji imefurika", "maji yamefurika",
)
# Wording that only suggests drainage next to the terms above. "Blocked" alone
# describes a fallen tree or a closed road just as often as a choked drain.
WEAK_DRAINAGE_TERMS = (
    "blocked", "choked", "overflow", "channel", "imeziba", "imezibwa", "imejaa",
    "hazipiti", "hayapiti", "water cannot flow", "water is not flowing",
    "blocking water", "obstructing water",
)
SWAHILI_TERMS = (
    "maji", "mfereji", "mifereji", "mtaro", "mitaro", "imeziba", "imezibwa",
    "imejaa", "barabara", "mvua", "takataka", "hazipiti", "hayapiti",
    "kuna", "huku", "karibu na", "imefurika", "yamefurika", "yamesimama",
)
ENGLISH_TERMS = (
    "the", " and ", " is ", " are ", " along ", " opposite ", "causing", "which",
    "will", "with", "blocked", "drainage", "roadside", "please", "report",
)
LANGUAGE_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "sw": "sw", "swa": "sw", "swh": "sw", "swahili": "sw", "kiswahili": "sw",
}


class ExtractedReport(BaseModel):
    category: Literal["drainage_flooding", "other"] = "drainage_flooding"
    area: str | None = Field(default=None, max_length=MAX_AREA_LENGTH)
    landmark: str | None = Field(default=None, max_length=MAX_LANDMARK_LENGTH)
    impact_reported: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_LENGTH)
    language: str = Field(default="en", max_length=MAX_LANGUAGE_LENGTH)


def _is_swahili(language: str | None) -> bool:
    return (language or "en").casefold().startswith("sw")


def _normalize_language(value: object) -> str | None:
    """Map a model's language answer onto a code the resident replies use."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().casefold().replace("_", "-")
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    return LANGUAGE_ALIASES.get(cleaned.split("-", 1)[0])


def _language_signal(normalized_message: str) -> tuple[str, int]:
    """Detect the message language and how strongly it reads as Kiswahili."""
    swahili_score = sum(term in normalized_message for term in SWAHILI_TERMS)
    english_score = sum(term in normalized_message for term in ENGLISH_TERMS)
    return ("sw" if swahili_score > english_score else "en", swahili_score - english_score)


def _has_drainage_wording(normalized_message: str, strong_only: bool = False) -> bool:
    if any(term in normalized_message for term in STRONG_DRAINAGE_TERMS):
        return True
    return not strong_only and any(term in normalized_message for term in WEAK_DRAINAGE_TERMS)


def _match_area(value: object, area_names: list[str]) -> str | None:
    """Resolve a reported area to the exact reference name, or drop it."""
    if not isinstance(value, str) or not value.strip():
        return None
    return {name.casefold(): name for name in area_names}.get(value.strip().casefold())


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
    language, _ = _language_signal(normalized)
    return ExtractedReport(
        category="drainage_flooding" if _has_drainage_wording(normalized) else "other",
        area=area,
        landmark=None,
        impact_reported=[],
        summary=message.strip()[:MAX_SUMMARY_LENGTH] or "Resident report",
        language=language,
    )


def _extraction_prompt(message: str, area_names: list[str]) -> str:
    return (
        "Extract a resident's Mombasa drainage and flood-preparedness report. Use only facts stated in the message. "
        "Choose area only from this list, otherwise null: " + ", ".join(area_names) + ". "
        "Prefer the specific listed neighborhood over a larger sub-county or constituency; "
        "for example, for 'Tononoka in Mvita', choose Tononoka if it is in the list. "
        "When multiple listed areas are mentioned, prefer the one explicitly introduced as the resident's "
        "reporting area (for example, 'from Nyali') over areas mentioned as wards, landmarks, or nearby places. "
        "Return JSON keys category (drainage_flooding for blocked/choked drains, gutters, manholes, culverts, "
        "or waterways; flooding or standing water; blocked sewers or sewage/wastewater overflow; "
        "or waste, silt, walls, or other objects obstructing water flow. "
        "Use other for issues unrelated to drainage or flood risk, such as garbage-only collection, streetlights, "
        "or general road damage), area, landmark, impact_reported "
        "(array of short stated impacts), summary (concise, preserve the specific issue and reported consequences, "
        "and write it in the same language as the resident's message), language "
        "(ISO 639-1 language code based on the original resident message; do not infer language from location names). "
        "Copy landmark wording from the message exactly where practical. Do not infer danger "
        "or verification. Message: " + message
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 429} or exc.response.status_code >= 500
    return False


def _request_extraction(prompt: str) -> Any | None:
    """Ask Groq for the report fields, retrying once on a transient failure."""
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={
                    "model": settings.groq_model,
                    "temperature": 0,
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You extract structured fields from incident reports. Reply with a single JSON "
                                "object using exactly these keys: category (string), area (string or null), "
                                "landmark (string or null), impact_reported (array of strings), summary (string), "
                                "language (string). Never add commentary or extra keys."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=12,
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt == 1 and _is_retryable(exc):
                logger.info("Retrying Groq report extraction after %s", type(exc).__name__)
                continue
            break
    logger.warning("Groq report extraction failed (%s); using local fallback", last_error)
    return None


def _coerce_extraction(raw: Any, message: str, area_names: list[str]) -> dict[str, Any]:
    """Shape a model response into the fields the report flow stores.

    Models return the right information in slightly wrong containers often
    enough that rejecting the whole answer over one malformed field would send
    the resident back to the keyword fallback for no good reason.
    """
    payload = raw if isinstance(raw, dict) else {}

    impacts_value = payload.get("impact_reported")
    if isinstance(impacts_value, str):
        impacts_value = [impacts_value]
    impacts = [
        str(item).strip()[:MAX_LANDMARK_LENGTH]
        for item in (impacts_value if isinstance(impacts_value, list) else [])
        if str(item).strip()
    ][:MAX_IMPACT_ITEMS]

    landmark = payload.get("landmark")
    landmark = landmark.strip()[:MAX_LANDMARK_LENGTH] if isinstance(landmark, str) else None

    summary = payload.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    summary = (summary or message.strip() or "Resident report")[:MAX_SUMMARY_LENGTH]

    category = payload.get("category")
    category = category.strip().casefold() if isinstance(category, str) else ""

    return {
        "category": "drainage_flooding" if category == "drainage_flooding" else "other",
        "area": _match_area(payload.get("area"), area_names),
        "landmark": landmark or None,
        "impact_reported": impacts,
        "summary": summary,
        "language": _normalize_language(payload.get("language")) or "en",
    }


def _reply_language(model_language: str, normalized_message: str) -> str:
    """Pick the language the resident is answered in.

    The model's own answer is used when it names a language this flow can
    write, because it reads the whole message. It is overruled only when the
    message reads unmistakably as the other language: the model sometimes
    translates a report and then reports the translation's language, which
    would answer the resident in a language they did not write in.
    """
    local_language, swahili_margin = _language_signal(normalized_message)
    normalized = _normalize_language(model_language)
    if normalized is None:
        return local_language
    if normalized == "en" and swahili_margin >= 2:
        return "sw"
    if normalized == "sw" and swahili_margin <= -2:
        return "en"
    return normalized


def extract_report(message: str, area_names: list[str]) -> ExtractedReport:
    local = fallback_extract(message, area_names)
    if not settings.groq_api_key:
        return local

    raw = _request_extraction(_extraction_prompt(message, area_names))
    if raw is None:
        return local
    try:
        parsed = ExtractedReport.model_validate(_coerce_extraction(raw, message, area_names))
    except ValidationError as exc:
        logger.warning("Groq returned unusable report fields (%s); using local fallback", exc)
        return local

    normalized = message.casefold()
    # The keyword detector fills gaps instead of overriding the model. It only
    # matches an area name written out literally, so it cannot read a location
    # the resident describes in a sentence.
    if parsed.area is None:
        parsed.area = local.area
    # Unambiguous drainage wording keeps a report in scope even when the model
    # labels it something else. Generic words like "blocked" are not enough.
    if parsed.category == "other" and _has_drainage_wording(normalized, strong_only=True):
        logger.info("Keeping report in drainage scope over the model's 'other' label")
        parsed.category = "drainage_flooding"
    parsed.language = _reply_language(parsed.language, normalized)
    return parsed


def send_sms(phone: str, message: str, link_id: str | None = None) -> Literal["accepted", "simulated", "failed"]:
    if not settings.at_api_key:
        # Show the exact text the resident would receive so a demo without
        # provider credentials can still verify the wording.
        logger.info(
            "SMS simulated; Africa's Talking credentials are not configured. Message: %s", message
        )
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
    if _is_swahili(candidate.language):
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
    if _is_swahili(candidate.language):
        return f"Asante. Ripoti yako imesajiliwa kwa nambari {reference}. Mratibu ataipitia."
    return f"Thank you. Your report reference is {reference}. A coordinator will review it."


def _out_of_scope_reply(candidate: ExtractedReport) -> str:
    if _is_swahili(candidate.language):
        return (
            "Kwa sasa tunapokea ripoti zinazohusu mifereji au hatari ya mafuriko. "
            "Tafadhali eleza tatizo na eneo lake la Mombasa."
        )
    return (
        "This demo currently accepts drainage and flood-risk reports. "
        "Please describe the issue and its Mombasa area."
    )


def _correction_prompt(candidate: ExtractedReport) -> str:
    if _is_swahili(candidate.language):
        return (
            "Tafadhali tuma eneo sahihi la Mombasa na alama ya karibu "
            "kwa tatizo la mifereji au mafuriko."
        )
    return "Please send the corrected Mombasa area and nearest landmark for the drainage or flooding issue."


def _location_prompt(candidate: ExtractedReport) -> str:
    if _is_swahili(candidate.language):
        return "Tafadhali tuma jina la eneo la Mombasa, kama Kisauni. NDIYO pekee haitaji eneo."
    return "Please send the Mombasa area, for example Kisauni. YES alone does not identify the location."


def _new_report_prompt(swahili: bool) -> str:
    if swahili:
        return "Kutuma ripoti mpya, eleza tatizo la mifereji/mafuriko na eneo au alama ya karibu."
    return "To start a report, describe a drainage or flooding issue and its area or nearby landmark."


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
    if _is_swahili(report.language):
        message = f"Ripoti {report.reference} imetatuliwa. Asante kwa kuituma."
    else:
        message = f"Report {report.reference} has been marked resolved. Thank you for reporting it."
    return _send(report.resident_phone, message, report.sms_link_id)


def send_in_progress_sms(report: Report) -> Literal["accepted", "simulated", "failed"]:
    if not report.resident_phone:
        logger.info("In-progress SMS simulated; report %s has no resident phone number", report.reference)
        return "simulated"
    if _is_swahili(report.language):
        message = f"Jibu limeanza kwa ripoti {report.reference}. Tutakujulisha kazi itakapokamilika."
    else:
        message = f"A response has started for report {report.reference}. We will update you when the work is complete."
    return _send(report.resident_phone, message, report.sms_link_id)


def message_claim_key(fields: dict[str, str]) -> str | None:
    """Build the key that stops the webhook and the inbox poller from both
    handling one inbound message.

    Both transports see the same provider message ID for an SMS, so that ID is
    the key. When the provider omits it, the key is derived from the fields both
    transports do receive, so the second one to arrive still recognizes the
    message as already handled.
    """
    channel = (fields.get("channel") or "").strip().casefold() or "sms"
    raw_id = (fields.get("id") or fields.get("messageId") or "").strip()
    if raw_id:
        # The webhook and the poller can format one provider ID differently,
        # so numeric IDs are compared by value rather than by spelling.
        canonical = str(int(raw_id)) if raw_id.lstrip("+-").isdigit() else raw_id
        return f"{channel}:{canonical}"[:180]

    stamp = (fields.get("date") or fields.get("receivedAt") or "").strip()
    if not stamp:
        return None
    fingerprint = f"{fields.get('from', '').strip()}|{fields.get('text', '').strip()}|{stamp}"
    return f"{channel}:body:{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()}"


def prune_processed_messages(db: Session, retain_days: int = 30) -> int:
    """Drop claim rows old enough that neither transport can redeliver them."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    removed = db.execute(
        delete(ProcessedInboundMessage).where(ProcessedInboundMessage.processed_at < cutoff)
    ).rowcount
    db.commit()
    return removed or 0


def _claim_message(db: Session, message_key: str | None) -> bool:
    """Record this message as ours to handle, or report that it is a duplicate.

    The claim is inserted inside the caller's transaction and under the
    per-sender advisory lock, so a webhook delivery and a poller pass that race
    for one message cannot both get past this point.
    """
    if message_key is None:
        logger.warning(
            "Inbound message carries no provider ID or timestamp; duplicate suppression is unavailable"
        )
        return True
    claimed = db.execute(
        text(
            "INSERT INTO processed_inbound_messages (message_key, processed_at) "
            "VALUES (:message_key, CURRENT_TIMESTAMP) ON CONFLICT (message_key) DO NOTHING"
        ),
        {"message_key": message_key},
    )
    if claimed.rowcount:
        return True
    # Release the advisory lock without discarding work the caller has pending;
    # the conflicting insert changed nothing, so this commit writes nothing.
    db.commit()
    logger.info("Skipping inbound message already handled by the other transport (key=%s)", message_key)
    return False


def _session_language(session: SmsIntakeSession | None) -> str | None:
    if session is None or not session.candidate:
        return None
    try:
        return ExtractedReport.model_validate(session.candidate).language
    except ValidationError:
        return None


def process_inbound_sms(fields: dict[str, str], db: Session) -> None:
    phone = fields.get("from", "").strip()
    message = fields.get("text", "").strip()
    message_id = fields.get("id") or fields.get("messageId")
    link_id = fields.get("linkId") or fields.get("link_id")
    channel = (fields.get("channel") or "sms").strip().casefold() or "sms"
    if not phone or not message:
        logger.warning(
            "Ignoring inbound SMS without sender or message (available fields: %s)",
            sorted(fields),
        )
        return

    # Serialize concurrent webhook/poller deliveries for a sender, including the
    # first message when no SmsIntakeSession row exists yet.
    db.execute(
        text("SELECT pg_advisory_xact_lock(0, hashtext(:sender_phone))"),
        {"sender_phone": phone},
    )
    # Claim the message after obtaining the per-sender transaction lock. The
    # claim stays in the same transaction as the intake update, so a failure
    # that rolls back the report also releases the claim for a retry.
    if not _claim_message(db, message_claim_key(fields)):
        return

    session = db.scalar(
        select(SmsIntakeSession).where(SmsIntakeSession.sender_phone == phone).with_for_update()
    )
    if session and channel == "voice":
        # A completed recording starts a fresh report conversation for this
        # resident instead of being interpreted as an SMS correction.
        session.stage = "completed"

    area_names = list(db.scalars(select(Area.name).order_by(Area.name)))
    yes = message.casefold() in AFFIRMATIVE_REPLIES
    no = message.casefold() in NEGATIVE_REPLIES

    if session is None or session.stage == "completed":
        if yes or no or len(message) < 3:
            # A bare acknowledgment after a finished report is not a new report.
            # Answer in the language that conversation used where it is known.
            previous_language = _session_language(session)
            swahili = (
                _is_swahili(previous_language)
                if previous_language
                else any(term in message.casefold() for term in ("ndio", "ndiyo", "sawa", "hapana"))
            )
            db.commit()
            _send(phone, _new_report_prompt(swahili), link_id)
            return
        candidate = extract_report(message, area_names)
        if channel == "voice" and fields.get("language") in {"en", "sw"}:
            candidate.language = fields["language"]
        if candidate.category == "other":
            db.commit()
            _send(phone, _out_of_scope_reply(candidate), link_id)
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
        session.last_message_id = message_id
        if yes or no:
            # "YES" cannot supply the area the previous reply asked for.
            reply = _location_prompt(ExtractedReport.model_validate(session.candidate))
        else:
            clarified_location = fallback_extract(message, area_names).area
            candidate = ExtractedReport.model_validate(session.candidate)
            if clarified_location:
                candidate.area = clarified_location
                session.candidate = candidate.model_dump()
                session.stage = "awaiting_confirmation"
            else:
                combined = f"{session.original_text}\nLocation clarification: {message}"
                candidate = extract_report(combined, area_names)
                session.original_text = combined
                session.candidate = candidate.model_dump()
                session.stage = "awaiting_confirmation" if candidate.area else "awaiting_location"
            reply = confirmation_text(candidate)
    elif session.stage == "awaiting_confirmation" and yes:
        candidate = ExtractedReport.model_validate(session.candidate)
        area_ref = (
            db.scalar(select(Area).where(Area.name.ilike(candidate.area))) if candidate.area else None
        )
        source = "voice_call" if channel == "voice" else "sms"
        report = Report(
            reference="pending",
            category=candidate.category,
            area=candidate.area,
            area_ref=area_ref,
            landmark=candidate.landmark,
            impact_reported=candidate.impact_reported,
            summary=candidate.summary,
            language=candidate.language,
            source=source,
            resident_phone=phone,
            sms_link_id=link_id,
            is_demo=settings.at_username.casefold() == "sandbox",
            verified=False,
            # An area the resident named but the reference list does not hold
            # cannot place the report on the map, so it goes to the coordinator
            # for triage rather than appearing as a confidently located report.
            location_uncertain=area_ref is None,
        )
        db.add(report)
        db.flush()
        report.reference = f"MW-{report.id:06d}"
        channel_label = "voice" if channel == "voice" else "SMS"
        task = Task(report=report, status=TaskStatus.REPORTED)
        acknowledgment_event = TaskStatusHistory(
            status=TaskStatus.REPORTED,
            note=f"Resident confirmed {channel_label} report",
        )
        task.history.append(acknowledgment_event)
        db.add(task)
        session.stage = "completed"
        session.last_message_id = message_id
        db.commit()
        delivery = _send(phone, _completed_reply(candidate, report.reference), link_id)
        if delivery == "accepted":
            outcome = "Acknowledgment accepted by Africa's Talking; handset delivery is unconfirmed."
        elif delivery == "simulated":
            outcome = "Acknowledgment shown in simulated mode; not delivered."
        else:
            outcome = "Provider send failed; acknowledgment shown in simulated mode."
        acknowledgment_event.note = f"Resident confirmed {channel_label} report. {outcome}"
        db.commit()
        return
    elif session.stage == "awaiting_confirmation" and no:
        session.stage = "awaiting_correction"
        session.last_message_id = message_id
        reply = _correction_prompt(ExtractedReport.model_validate(session.candidate))
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
