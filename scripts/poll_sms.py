"""Poll Africa's Talking's SMS inbox when inbound callbacks are unavailable."""

import argparse
import logging
import time
from datetime import datetime, timezone

import africastalking
from app.config import settings
from app.database import SessionLocal
from app.intake import process_inbound_sms
from app.models import SmsPollCursor, WorkerHeartbeat


logger = logging.getLogger("mtaaniwatch.sms_poll")
CURSOR_NAME = "africastalking_inbox"
WORKER_NAME = "africastalking_sms_poller"


def _record_worker_outcome(processed: int | None, error: Exception | None = None) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, WORKER_NAME)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(name=WORKER_NAME, last_attempt_at=now)
            db.add(heartbeat)
        heartbeat.last_attempt_at = now
        heartbeat.last_error = f"{type(error).__name__}: {error}"[:300] if error else None
        heartbeat.last_processed_count = processed
        if error is None:
            heartbeat.last_success_at = now
        db.commit()


def _messages_after(last_received_id: int) -> list[dict]:
    response = africastalking.SMS.fetch_messages(last_received_id=last_received_id, timeout=15)
    if not isinstance(response, dict):
        raise RuntimeError("Africa's Talking returned an unexpected inbox response")
    return response.get("SMSMessageData", {}).get("Messages", [])


def _message_id(message: dict) -> int | None:
    try:
        return int(message.get("id"))
    except (TypeError, ValueError):
        return None


def _as_inbound_fields(message: dict, message_id: int) -> dict[str, str]:
    sender = (
        message.get("from")
        or message.get("phoneNumber")
        or message.get("msisdn")
        or message.get("sender")
        or ""
    )
    text = message.get("text") or message.get("message") or ""
    fields = {"from": str(sender), "text": str(text), "id": str(message_id)}
    link_id = message.get("linkId") or message.get("link_id")
    if link_id:
        fields["linkId"] = str(link_id)
    return fields


def _get_or_initialize_cursor(db) -> SmsPollCursor:
    cursor = db.get(SmsPollCursor, CURSOR_NAME)
    if cursor is not None:
        return cursor

    existing = _messages_after(0)
    latest_id = max((_message_id(message) or 0 for message in existing), default=0)
    cursor = SmsPollCursor(name=CURSOR_NAME, last_received_id=latest_id)
    db.add(cursor)
    db.commit()
    logger.info(
        "Initialized inbox cursor at message ID %s from %s existing inbox message(s); "
        "existing messages will not be replayed",
        latest_id,
        len(existing),
    )
    return cursor


def poll_once() -> int:
    with SessionLocal() as db:
        cursor = _get_or_initialize_cursor(db)
        previous_id = cursor.last_received_id
        messages = _messages_after(previous_id)
        ordered = sorted(
            ((message_id, message) for message in messages if (message_id := _message_id(message)) is not None),
            key=lambda pair: pair[0],
        )
        newest_id = ordered[-1][0] if ordered else None
        logger.info(
            "Inbox poll succeeded: returned %s message(s), %s with valid IDs; "
            "cursor=%s, newest_returned_id=%s",
            len(messages),
            len(ordered),
            previous_id,
            newest_id if newest_id is not None else "none",
        )
        processed = 0

        for message_id, message in ordered:
            if message_id <= cursor.last_received_id:
                continue
            fields = _as_inbound_fields(message, message_id)
            if not fields["from"].strip() or not fields["text"].strip():
                logger.warning(
                    "Skipping malformed inbox message ID %s (available fields: %s)",
                    message_id,
                    sorted(message),
                )
                cursor.last_received_id = message_id
                db.commit()
                continue

            sender = fields["from"]
            logger.info(
                "Processing polled SMS ID %s from ***%s (%d chars)",
                message_id,
                sender[-4:],
                len(fields["text"]),
            )
            process_inbound_sms(fields, db)
            cursor.last_received_id = message_id
            db.commit()
            processed += 1

        if processed:
            logger.info(
                "Inbox poll processed %s new message(s); cursor advanced from %s to %s",
                processed,
                previous_id,
                cursor.last_received_id,
            )
        else:
            logger.info("Inbox poll found no new messages; cursor remains at %s", cursor.last_received_id)
        return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=20, help="Polling interval in seconds (default: 20)")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if not settings.at_api_key:
        parser.error("AT_API_KEY is not configured in the project .env")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    africastalking.initialize(settings.at_username, settings.at_api_key)
    logger.info(
        "SMS inbox worker started (username=%s, interval=%ss); credentials are configured",
        settings.at_username,
        args.interval,
    )

    while True:
        try:
            count = poll_once()
            _record_worker_outcome(count)
            if count:
                logger.info("Processed %s new inbound SMS message(s)", count)
        except Exception as exc:
            try:
                _record_worker_outcome(None, exc)
            except Exception:
                logger.exception("Could not record SMS poller failure heartbeat")
            logger.exception("Inbox poll failed; will retry after the interval")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
