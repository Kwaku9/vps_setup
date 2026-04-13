from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram_gateway import db

logger = logging.getLogger(__name__)


class JobQueue:
    """Postgres advisory lock-based job queue with concurrency control."""

    def __init__(self, max_concurrent: int = 3):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    async def enqueue(self, command_id: int, handler):
        """Schedule a command for processing."""
        task = asyncio.create_task(self._run(command_id, handler))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, command_id: int, handler):
        """Process a command with advisory lock and semaphore."""
        async with self.semaphore:
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Advisory lock prevents duplicate processing
                    locked = await conn.fetchval(
                        "SELECT pg_try_advisory_xact_lock($1)", command_id
                    )
                    if not locked:
                        logger.debug("Command %d already locked, skipping", command_id)
                        return

                    # Check it's still pending
                    status = await conn.fetchval(
                        "SELECT status FROM gateway.commands WHERE id = $1",
                        command_id,
                    )
                    if status != "pending":
                        logger.debug("Command %d status is %s, skipping", command_id, status)
                        return

                    await conn.execute(
                        "UPDATE gateway.commands SET status = 'processing' WHERE id = $1",
                        command_id,
                    )

            # Run handler outside the transaction (it manages its own DB calls)
            try:
                await handler(command_id)
            except Exception:
                logger.exception("Failed to process command %d", command_id)
                # Check if responses were already delivered before sending error
                p = await db.get_pool()
                existing = await p.fetchval(
                    "SELECT count(*) FROM gateway.responses "
                    "WHERE command_id = $1 AND response_type NOT IN ('stderr', 'approval')",
                    command_id,
                )
                if existing and existing > 0:
                    # Response already sent — mark completed, skip error message
                    logger.info(
                        "Command %d failed after %d response(s) already delivered — suppressing error",
                        command_id, existing,
                    )
                    await db.update_command_status(
                        command_id, "completed",
                        completed_at=datetime.now(timezone.utc),
                    )
                else:
                    await db.update_command_status(
                        command_id, "failed",
                        completed_at=datetime.now(timezone.utc),
                    )
                    cmd = await p.fetchrow(
                        "SELECT telegram_chat_id, agent_type FROM gateway.commands WHERE id = $1",
                        command_id,
                    )
                    if cmd:
                        await db.insert_response(
                            command_id=command_id,
                            agent_type=cmd["agent_type"],
                            response_type="text",
                            content="Sorry, an error occurred processing your request. Please try again.",
                            chat_id=cmd["telegram_chat_id"],
                        )

    async def shutdown(self):
        """Wait for all running tasks to complete."""
        if self._tasks:
            logger.info("Waiting for %d tasks to complete...", len(self._tasks))
            await asyncio.gather(*self._tasks, return_exceptions=True)


job_queue = JobQueue()
