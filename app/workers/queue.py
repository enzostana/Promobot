import json
import logging
from typing import Optional
import redis.asyncio as redis
from app.core.models import RawMessage
from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class RedisQueue:
    """
    Asynchronous queue client using Redis lists (RPUSH / BLPOP).

    A failed message can be re-enqueued (retry) and, once it exceeds the
    max attempts, moved to a dead-letter queue so it is never silently lost.
    """

    def __init__(self, settings: Optional[Settings] = None, client=None):
        self.settings = settings or get_settings()
        self.queue_name = self.settings.REDIS_QUEUE_NAME
        self.dead_queue_name = f"{self.queue_name}:dead"
        self.max_attempts = self.settings.WORKER_MAX_ATTEMPTS
        self._client = client
        self._injected = client is not None

    async def get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True
            )
        return self._client

    async def enqueue(self, raw_msg: RawMessage) -> None:
        try:
            client = await self.get_client()
            payload = raw_msg.model_dump_json()
            await client.rpush(self.queue_name, payload)
        except Exception as e:
            logger.error(f"[QUEUE] Erro ao enfileirar mensagem {raw_msg.id}: {e}", exc_info=True)
            raise

    async def push_dead(self, raw_msg: RawMessage) -> None:
        """Sends an exhausted message to the dead-letter queue for audit."""
        try:
            client = await self.get_client()
            payload = raw_msg.model_dump_json()
            await client.rpush(self.dead_queue_name, payload)
        except Exception as e:
            logger.error(f"[QUEUE] Erro ao mover mensagem {raw_msg.id} para dead-letter: {e}", exc_info=True)
            raise

    async def dequeue(self, timeout: int = 2) -> Optional[RawMessage]:
        try:
            client = await self.get_client()
            item = await client.blpop([self.queue_name], timeout=timeout)
            if item:
                # blpop returns (queue_name, data)
                _, raw_data = item
                data_dict = json.loads(raw_data)
                return RawMessage.model_validate(data_dict)
            return None
        except Exception as e:
            logger.error(f"[QUEUE] Erro ao desenfileirar mensagem: {e}")
            return None

    async def length(self) -> int:
        try:
            client = await self.get_client()
            return await client.llen(self.queue_name)
        except Exception:
            return 0

    async def close(self) -> None:
        # Only close clients this queue owns (an injected client is managed elsewhere).
        if self._client is not None and self._injected is False:
            await self._client.aclose()
        self._client = None
