import asyncio
import logging
import signal
from typing import Optional
from app.config.settings import get_settings
from app.core.models import RawMessage
from app.core.processor import PromotionProcessor
from app.adapters.telegram import TelegramPublisher
from app.workers.queue import RedisQueue
from app.database.session import async_session_maker, init_db
from app.workers.health_server import run_health_server
import redis.asyncio as redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("worker")


class Worker:
    """
    Background worker process. Consumes raw promotion messages from Redis queue,
    orchestrates processing, publishes approved offers, and commits records to PostgreSQL.
    """

    def __init__(self, queue: Optional[RedisQueue] = None, processor: Optional[PromotionProcessor] = None):
        self.settings = get_settings()
        self.queue = queue or RedisQueue(self.settings)
        publisher = TelegramPublisher(self.settings)
        self.processor = processor or PromotionProcessor(publisher=publisher, settings=self.settings)
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("[WORKER] Worker de promoções inicializado. Consumindo fila...")

        # Start health check server
        health_runner = await run_health_server("worker", 8081)

        # Initialize DB schema if tables don't exist yet
        try:
            await init_db()
        except Exception as e:
            logger.warning(f"[WORKER] Falha ao verificar/inicializar DB: {e}. Certifique-se de que o Postgres está pronto.")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                pass

        redis_client = redis.from_url(self.settings.REDIS_URL)

        while self._running:
            try:
                # Wait for next item in Redis queue
                raw_msg = await self.queue.dequeue(timeout=2)
                if not raw_msg:
                    continue

                logger.info(f"[WORKER] Nova mensagem recebida da fila: id={raw_msg.id} (origem: {raw_msg.source_chat_id}, tentativa {raw_msg.attempts + 1})")

                # Open database session for this message transaction
                async with async_session_maker() as db_session:
                    try:
                        result = await self.processor.process(raw_msg, db_session=db_session)
                        await db_session.commit()
                    except Exception as err:
                        await db_session.rollback()
                        logger.error(f"[WORKER] Erro no processamento da mensagem {raw_msg.id}: {err}", exc_info=True)
                        await self._handle_failure(raw_msg)
                        continue

                    # Failure retry: unexpected error (None) or transient FAILED status
                    if result is None or getattr(result, "status", None) == "failed":
                        logger.warning(f"[WORKER] Processamento falhou para {raw_msg.id} (tentativa {raw_msg.attempts + 1})")
                        await self._handle_failure(raw_msg)
                    else:
                        logger.info(f"[WORKER] Processamento concluído com sucesso: status={result.status.value}")
                        # Update last processed timestamp for health checks
                        try:
                            await redis_client.set(
                                "promobot:last_processed:worker",
                                str(int(asyncio.get_event_loop().time()))
                            )
                        except Exception:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WORKER] Exceção no ciclo do worker: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("[WORKER] Worker finalizado com sucesso.")
        await health_runner.cleanup()
        await redis_client.aclose()

    def stop(self) -> None:
        logger.info("[WORKER] Sinal de encerramento recebido...")
        self._running = False

    async def _handle_failure(self, raw_msg: RawMessage) -> None:
        """
        Handles a transient failure: re-enqueues the message (incrementing the
        attempt counter) or moves it to the dead-letter queue when exhausted.
        """
        raw_msg.attempts += 1
        if raw_msg.attempts < self.queue.max_attempts:
            logger.info(f"[WORKER] Re-enfileirando {raw_msg.id} (tentativa {raw_msg.attempts}/{self.queue.max_attempts})")
            await self.queue.enqueue(raw_msg)
        else:
            logger.error(f"[WORKER] Mensagem {raw_msg.id} esgotou tentativas; movendo para dead-letter.")
            await self.queue.push_dead(raw_msg)


async def run_worker():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
