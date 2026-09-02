import asyncio
import logging
import signal
from typing import Optional
from app.config.settings import get_settings
from app.core.processor import PromotionProcessor
from app.adapters.telegram import TelegramPublisher
from app.workers.queue import RedisQueue
from app.database.session import async_session_maker, init_db

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

        while self._running:
            try:
                # Wait for next item in Redis queue
                raw_msg = await self.queue.dequeue(timeout=2)
                if not raw_msg:
                    continue

                logger.info(f"[WORKER] Nova mensagem recebida da fila: id={raw_msg.id} (origem: {raw_msg.source_chat_id})")

                # Open database session for this message transaction
                async with async_session_maker() as db_session:
                    try:
                        result = await self.processor.process(raw_msg, db_session=db_session)
                        await db_session.commit()
                        if result:
                            logger.info(f"[WORKER] Processamento concluído com sucesso: status={result.status.value}")
                    except Exception as err:
                        await db_session.rollback()
                        logger.error(f"[WORKER] Erro no processamento da mensagem {raw_msg.id}: {err}", exc_info=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WORKER] Exceção no ciclo do worker: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("[WORKER] Worker finalizado com sucesso.")

    def stop(self) -> None:
        logger.info("[WORKER] Sinal de encerramento recebido...")
        self._running = False


async def run_worker():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
