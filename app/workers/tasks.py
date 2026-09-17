import asyncio
import json
import logging
import signal
import time
from typing import Optional
from app.config.settings import Settings
from app.core.models import RawMessage
from app.core.processor import PromotionProcessor
from app.adapters.telegram import TelegramPublisher
from app.adapters.whatsapp import WhatsAppPublisher
from app.workers.queue import RedisQueue
from app.database.session import async_session_maker, init_db
from app.core.runtime_settings import RuntimeOverrides
from app.workers.health_server import run_health_server
import redis.asyncio as redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("worker")


def _last_processed_ts() -> str:
    """Wall-clock Unix epoch (seconds) as string.

    Health checks and the painel read this via ``datetime.fromtimestamp``,
    so the stored value MUST be wall-clock epoch — never a monotonic clock.
    """
    return str(int(time.time()))


class Worker:
    """
    Background worker process. Consumes raw promotion messages from Redis queue,
    orchestrates processing, publishes approved offers, and commits records to PostgreSQL.
    """

    def __init__(self, queue: Optional[RedisQueue] = None, processor: Optional[PromotionProcessor] = None):
        # Fresh Settings instance (not the cached singleton) so runtime overrides
        # applied in-place are scoped to this process.
        self.settings = Settings()
        self.runtime_overrides = RuntimeOverrides()
        self.queue = queue or RedisQueue(self.settings)
        publishers = [TelegramPublisher(self.settings)]
        if self.settings.WHATSAPP_TARGET_CHAT:
            publishers.append(WhatsAppPublisher(self.settings))
            logger.info("[WORKER] WhatsAppPublisher registrado (publicação via Evolution API).")
        self.processor = processor or PromotionProcessor(publishers=publishers, settings=self.settings)
        self._running = False
        self._finder_task = None

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
        self.redis_client = redis_client

        # Clean up old media files on startup
        await self._cleanup_media_cache()

        # Periodic deal-finder (Shopee Open API)
        self._finder_task = asyncio.create_task(self._finder_loop())

        while self._running:
            try:
                # Wait for next item in Redis queue
                raw_msg = await self.queue.dequeue(timeout=2)
                if not raw_msg:
                    continue

                logger.info(f"[WORKER] Nova mensagem recebida da fila: id={raw_msg.id} (origem: {raw_msg.source_chat_id}, tentativa {raw_msg.attempts + 1})")

                # Drop stale messages so queue backlog/reconnect never causes
                # retroactive posting. Painel tests always process immediately.
                if self._is_stale(raw_msg):
                    logger.info(f"[WORKER] Mensagem descartada (antiga demais; {self.settings.STALE_AFTER_MINUTES}min): id={raw_msg.id} recebida_em={raw_msg.received_at}")
                    continue

                # Apply runtime settings edited in the control panel (DB overrides)
                try:
                    async with async_session_maker() as settings_session:
                        await self.runtime_overrides.apply(settings_session, self.settings)
                except Exception as e:
                    logger.warning(f"[WORKER] Falha ao atualizar configurações dinâmicas: {e}")

                # Rebuild runtime-dependent components (affiliate tags, filters)
                self.processor.refresh_runtime(self.settings)

                if self.runtime_overrides.is_paused():
                    # Do not keep cycling stale messages while paused.
                    if self._is_stale(raw_msg):
                        logger.info(f"[WORKER] Mensagem descartada (pausa + antiga demais): id={raw_msg.id}")
                        continue
                    logger.info("[WORKER] Bot pausado pelo painel; mensagem re-enfileirada, aguardando retomar.")
                    await self.queue.enqueue(raw_msg)
                    await asyncio.sleep(5)
                    continue

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
                                _last_processed_ts()
                            )
                        except Exception:
                            pass

                # Mirror the MEL mint health to Redis so the painel can flag a
                # dead affiliate session ("links sem header").
                await self._publish_mel_mint_status()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WORKER] Exceção no ciclo do worker: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("[WORKER] Worker finalizado com sucesso.")
        try:
            self._finder_task.cancel()
        except Exception:
            pass
        await health_runner.cleanup()
        await redis_client.aclose()

    async def _publish_mel_mint_status(self) -> None:
        """Copies the process-wide MEL mint health to Redis for the painel."""
        try:
            from app.affiliates.mercadolivre import MEL_MINT_STATUS

            await self.redis_client.set(
                "promobot:mel_mint_status",
                json.dumps(MEL_MINT_STATUS),
                ex=6 * 3600,
            )
        except Exception as e:
            logger.debug(f"[WORKER] Falha ao publicar status do mint MEL: {e}")

    async def _finder_loop(self) -> None:
        """Periódico: consulta as APIs de afiliados (Shopee, Mercado Livre, Amazon) e enfileira ofertas."""
        from app.finder.amazon import AmazonFinder
        from app.finder.mercadolivre import MercadoLivreFinder
        from app.finder.shopee import ShopeeFinder

        logger.info("[FINDER] Ciclo do caçador de ofertas iniciado.")
        while self._running:
            try:
                # Refresh runtime config (DB overrides) before each cycle
                async with async_session_maker() as settings_session:
                    await self.runtime_overrides.apply(settings_session, self.settings, force=True)

                finders = [
                    ShopeeFinder(self.settings),
                    MercadoLivreFinder(
                        self.settings,
                        refresh_saver=self._save_mel_refresh_token,
                    ),
                    AmazonFinder(self.settings),
                ]
                intervals = []
                for finder in finders:
                    label = finder.label
                    if not finder.enabled():
                        logger.info(f"[FINDER] Caçador {label} desabilitado.")
                        continue
                    intervals.append(finder.interval_min)
                    if not finder.credentials_ok():
                        logger.warning(
                            f"[FINDER] Caçador {label}: credenciais ausentes (configure 'Caçador' no painel)."
                        )
                        continue
                    found = await finder.scan(self.queue)
                    logger.info(f"[FINDER] Varredura {label} concluída: {found} ofertas enfileiradas.")

                interval_min = max(1, min(intervals)) if intervals else 30
                await self._publish_mel_mint_status()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[FINDER] Erro na varredura: {e}")
                interval_min = 30
            await asyncio.sleep(interval_min * 60)

    async def _save_mel_refresh_token(self, token: str) -> None:
        from app.database.repositories.setting_repo import SettingRepository

        try:
            async with async_session_maker() as settings_session:
                repo = SettingRepository(settings_session)
                await repo.upsert("mel_refresh_token", token)
                await settings_session.commit()
                settings = self.settings
                if settings is not None:
                    setattr(settings, "MEL_REFRESH_TOKEN", token)
                logger.info("[FINDER] Refresh token MEL rotacionado e persistido.")
        except Exception as e:
            logger.warning(f"[FINDER] Erro ao persistir refresh token MEL: {e}")

    def stop(self) -> None:
        logger.info("[WORKER] Sinal de encerramento recebido...")
        self._running = False

    def _is_stale(self, raw_msg: RawMessage) -> bool:
        """True when a captured message is older than STALE_AFTER_MINUTES."""
        from datetime import datetime, timezone
        max_age = getattr(self.settings, "STALE_AFTER_MINUTES", 15)
        if max_age <= 0 or raw_msg.source == "painel":
            return False
        received = raw_msg.received_at
        if received is None:
            return False
        age_minutes = (datetime.now(timezone.utc) - received).total_seconds() / 60.0
        return age_minutes > max_age

    async def _handle_failure(self, raw_msg: RawMessage) -> None:
        """
        Handles a transient failure: re-enqueues the message (incrementing the
        attempt counter) or moves it to the dead-letter queue when exhausted.
        Uses exponential backoff before re-enqueueing.
        """
        raw_msg.attempts += 1
        if self._is_stale(raw_msg):
            logger.info(f"[WORKER] Retry abortado, mensagem antiga demais; descartada: {raw_msg.id}")
            return
        if raw_msg.attempts < self.queue.max_attempts:
            # Exponential backoff: 2^attempt seconds, max 60s
            delay = min(2 ** raw_msg.attempts, 60)
            logger.info(f"[WORKER] Aguardando {delay}s antes de re-enfileirar {raw_msg.id} (tentativa {raw_msg.attempts}/{self.queue.max_attempts})")
            await asyncio.sleep(delay)
            await self.queue.enqueue(raw_msg)
        else:
            logger.error(f"[WORKER] Mensagem {raw_msg.id} esgotou tentativas; movendo para dead-letter.")
            await self.queue.push_dead(raw_msg)

    async def _cleanup_media_cache(self) -> None:
        """Remove media files older than MEDIA_CACHE_TTL_DAYS (default 7)."""
        from pathlib import Path
        import time

        ttl_days = getattr(self.settings, "MEDIA_CACHE_TTL_DAYS", 7)
        cutoff = time.time() - (ttl_days * 86400)
        media_dir = Path("media_cache")

        if not media_dir.exists():
            return

        removed = 0
        for file_path in media_dir.iterdir():
            if file_path.is_file():
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        removed += 1
                except Exception as e:
                    logger.warning(f"[WORKER] Erro ao remover {file_path}: {e}")

        if removed:
            logger.info(f"[WORKER] Limpeza de media_cache: {removed} arquivo(s) removido(s) (TTL={ttl_days}d)")


async def run_worker():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
