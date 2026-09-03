#!/usr/bin/env python3
"""
Dead-letter queue processor for PromoBot.

This script processes messages that have exhausted all retry attempts
and were moved to the dead-letter queue (promobot:raw_messages:dead).

Usage:
    python -m scripts.process_dlq [--requeue] [--limit N] [--dry-run]

Options:
    --requeue    Re-enqueue messages back to the main queue after inspection
    --limit N    Maximum number of messages to process (default: 100)
    --dry-run    Only log what would be done, don't modify queues
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

import redis.asyncio as redis

from app.config.settings import get_settings
from app.core.models import RawMessage

logger = logging.getLogger("promobot.dlq")


async def process_dlq(
    requeue: bool = False,
    limit: int = 100,
    dry_run: bool = False,
) -> dict:
    """Process dead-letter queue messages."""
    settings = get_settings()
    dlq_name = f"{settings.REDIS_QUEUE_NAME}:dead"
    main_queue = settings.REDIS_QUEUE_NAME

    r = redis.from_url(settings.REDIS_URL, decode_responses=True)

    processed = 0
    requeued = 0
    errors = 0

    try:
        while processed < limit:
            # Pop from dead-letter queue (LPOP to process in order)
            item = await r.lpop(dlq_name)
            if not item:
                break

            processed += 1
            try:
                msg = RawMessage.model_validate_json(item)
            except Exception as e:
                logger.error(f"[DLQ] Failed to parse message: {e}")
                errors += 1
                if not dry_run:
                    # Put back to DLQ if parsing failed
                    await r.rpush(dlq_name, item)
                continue

            logger.warning(
                f"[DLQ] Processing message: id={msg.id} "
                f"attempts={msg.attempts} chat={msg.source_chat_id} "
                f"correlation_id={msg.correlation_id} "
                f"text_preview={msg.text[:100]!r}"
            )

            if requeue and not dry_run:
                # Reset attempts and re-enqueue to main queue
                msg.attempts = 0
                await r.rpush(main_queue, msg.model_dump_json())
                requeued += 1
                logger.info(f"[DLQ] Re-enqueued message {msg.id} to main queue")
            elif dry_run:
                logger.info(f"[DLQ] DRY-RUN: would {'requeue' if requeue else 'inspect'} message {msg.id}")

        return {
            "processed": processed,
            "requeued": requeued,
            "errors": errors,
            "remaining_in_dlq": await r.llen(dlq_name),
        }

    finally:
        await r.aclose()


def main():
    parser = argparse.ArgumentParser(description="Process PromoBot dead-letter queue")
    parser.add_argument("--requeue", action="store_true", help="Re-enqueue messages to main queue")
    parser.add_argument("--limit", type=int, default=100, help="Max messages to process")
    parser.add_argument("--dry-run", action="store_true", help="Only log, don't modify queues")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info(f"[DLQ] Starting dead-letter processor (requeue={args.requeue}, limit={args.limit}, dry_run={args.dry_run})")

    result = asyncio.run(process_dlq(
        requeue=args.requeue,
        limit=args.limit,
        dry_run=args.dry_run,
    ))

    logger.info(
        f"[DLQ] Done: processed={result['processed']} "
        f"requeued={result['requeued']} errors={result['errors']} "
        f"remaining_in_dlq={result['remaining_in_dlq']}"
    )

    if result["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()