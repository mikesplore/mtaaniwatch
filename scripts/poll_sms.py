"""Poll Africa's Talking's SMS inbox when inbound callbacks are unavailable."""

import argparse
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import africastalking
from app.config import settings
from app.database import SessionLocal
from app.intake import process_inbound_sms, prune_processed_messages
from app.models import SmsPollCursor, WorkerHeartbeat


logger = logging.getLogger("mtaaniwatch.sms_poll")
CURSOR_NAME = "africastalking_inbox"
WORKER_NAME = "africastalking_sms_poller"
CLAIM_RETENTION_DAYS = 30
PRUNE_INTERVAL = timedelta(hours=6)


def _record_worker_outcome(
    processed: int | None, error: Exception | None = None, message_error: str | None = None
) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, WORKER_NAME)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(name=WORKER_NAME, last_attempt_at=now)
            db.add(heartbeat)
        heartbeat.last_attempt_at = now
        if error is not None:
            heartbeat.last_error = f"{type(error).__name__}: {error}"[:300]
        else:
            # A poll that reached the inbox is a success even when one message
            # inside it could not be turned into a report; the coordinator still
            # needs to see that the message was dropped.
            heartbeat.last_error = message_error[:300] if message_error else None
            heartbeat.last_success_at = now
        heartbeat.last_processed_count = processed
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
    # "channel" and "date" are what the inbound callback also sends, so both
    # transports derive the same idempotency key for one provider message.
    fields = {"from": str(sender), "text": str(text), "id": str(message_id), "channel": "sms"}
    link_id = message.get("linkId") or message.get("link_id")
    if link_id:
        fields["linkId"] = str(link_id)
    received_at = message.get("date") or message.get("receivedAt")
    if received_at:
        fields["date"] = str(received_at)
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


def poll_once() -> tuple[int, list[int]]:
    """Process new inbox messages and return the count plus any that failed."""
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
        failed: list[int] = []

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
            try:
                process_inbound_sms(fields, db)
                processed += 1
            except Exception:
                # One unprocessable message must not hold up every later report.
                # Its transaction has rolled back, so its claim is released and
                # it can be replayed once the cause is fixed.
                db.rollback()
                failed.append(message_id)
                logger.exception("Could not process inbox message ID %s; skipping it", message_id)
            # process_inbound_sms commits its own transaction, so re-attach the
            # cursor before recording that this message is behind us.
            cursor = db.get(SmsPollCursor, CURSOR_NAME)
            cursor.last_received_id = message_id
            db.commit()

        if processed or failed:
            logger.info(
                "Inbox poll processed %s new message(s) and skipped %s; cursor advanced from %s to %s",
                processed,
                len(failed),
                previous_id,
                cursor.last_received_id,
            )
        else:
            logger.info("Inbox poll found no new messages; cursor remains at %s", cursor.last_received_id)
        return processed, failed


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
        _poll_iteration()
        time.sleep(args.interval)


_last_prune_at: datetime | None = None


def _prune_claims() -> None:
    global _last_prune_at
    now = datetime.now(timezone.utc)
    if _last_prune_at is not None and now - _last_prune_at < PRUNE_INTERVAL:
        return
    _last_prune_at = now
    try:
        with SessionLocal() as db:
            removed = prune_processed_messages(db, CLAIM_RETENTION_DAYS)
        if removed:
            logger.info("Removed %s inbound message claim(s) older than %s days", removed, CLAIM_RETENTION_DAYS)
    except Exception:
        logger.exception("Could not prune processed inbound message claims")


def _poll_iteration() -> None:
    try:
        count, failed = poll_once()
        message_error = (
            f"Skipped {len(failed)} unprocessable inbox message(s): {failed}" if failed else None
        )
        _record_worker_outcome(count, message_error=message_error)
        if count:
            logger.info("Processed %s new inbound SMS message(s)", count)
        _prune_claims()
    except Exception as exc:
        try:
            _record_worker_outcome(None, exc)
        except Exception:
            logger.exception("Could not record SMS poller failure heartbeat")
        logger.exception("Inbox poll failed; will retry after the interval")


async def run_poller(interval: float) -> None:
    """Poll continuously while the ASGI app is running."""
    if not settings.at_api_key:
        logger.error("SMS inbox polling is enabled but AT_API_KEY is not configured")
        return

    africastalking.initialize(settings.at_username, settings.at_api_key)
    logger.info("SMS inbox poller started (username=%s, interval=%ss)", settings.at_username, interval)
    try:
        while True:
            # The provider SDK and database work are synchronous; keep them off the event loop.
            await asyncio.to_thread(_poll_iteration)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SMS inbox poller stopped")
        raise


if __name__ == "__main__":
    main()
