"""Africa's Talking Voice recording transcription and SMS handoff."""

import logging
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.database import SessionLocal
from app.intake import process_inbound_sms, send_sms

logger = logging.getLogger(__name__)
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
ALLOWED_RECORDING_DOMAIN = "africastalking.com"


def _could_not_process(phone: str, language: str) -> None:
    if not phone:
        return
    message = (
        "Hatukuweza kuchakata ripoti yako ya sauti. Tafadhali jaribu kupiga tena au tuma ripoti kwa SMS."
        if language == "sw"
        else "We could not process your voice report. Please try calling again or send the report by SMS."
    )
    send_sms(
        phone,
        message,
    )


def transcribe_voice_report(
    phone: str, session_id: str, recording_url: str, language: str
) -> None:
    """Transcribe an AT call recording and hand it into the existing SMS intake."""
    if not settings.groq_api_key:
        logger.error("Cannot transcribe voice report: GROQ_API_KEY is not configured")
        _could_not_process(phone, language)
        return

    parsed_url = urlparse(recording_url)
    hostname = (parsed_url.hostname or "").casefold()
    if (
        parsed_url.scheme != "https"
        or not hostname
        or not (hostname == ALLOWED_RECORDING_DOMAIN or hostname.endswith(f".{ALLOWED_RECORDING_DOMAIN}"))
        or parsed_url.username
        or parsed_url.password
    ):
        logger.warning("Rejected voice recording URL from provider callback")
        _could_not_process(phone, language)
        return

    prompts = {
        "en": "MtaaniWatch, Mombasa, drainage, blocked drain, flooding, neighborhood and landmark names.",
        "sw": "MtaaniWatch, Mombasa, mifereji, mtaro, mafuriko, majina ya maeneo na alama za karibu.",
    }
    try:
        response = httpx.post(
            GROQ_TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data={
                "model": settings.groq_stt_model,
                "language": language,
                "response_format": "json",
                "temperature": "0",
                "prompt": prompts[language],
            },
            files={"url": (None, recording_url)},
            timeout=35,
        )
        response.raise_for_status()
        transcript = response.json().get("text", "").strip()
        if len(transcript) < 3:
            logger.warning("Voice recording transcription was empty or too short")
            _could_not_process(phone, language)
            return

        logger.info(
            "Voice report transcribed; handing to SMS confirmation flow (session=%s, chars=%d)",
            session_id,
            len(transcript),
        )
        with SessionLocal() as db:
            process_inbound_sms(
                {
                    "from": phone,
                    "text": transcript,
                    "id": f"voice:{session_id}",
                    "channel": "voice",
                    "language": language,
                },
                db,
            )
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        logger.exception("Voice report transcription or intake processing failed")
        _could_not_process(phone, language)
