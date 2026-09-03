# PromoBot - Production Readiness Checklist

This document tracks the production readiness status of PromoBot components.

## ✅ Completed Areas

| # | Area | Description | Commit |
|---|------|-------------|--------|
| 1 | **Secrets Management** | Docker Secrets for all sensitive values (DB password, Telegram tokens, affiliate tags) | `a21f300` |
| 2 | **Database Migrations** | Init container (`migrator`) runs `alembic upgrade head` before API starts | `a21f300` |
| 3 | **Healthchecks** | `/live`, `/ready` endpoints + Worker/Listener HTTP health servers (ports 8081, 8082) | `5f917d5` |
| 4 | **Structured Logging** | JSON formatter, correlation IDs (X-Request-ID), sensitive data sanitization | `290e144` |
| 5 | **Retry & Backoff** | Exponential backoff in worker (2^n, max 60s), httpx retry transport for Telegram API | `95aa146` |
| 6 | **Dead-Letter Queue** | Processor script (`scripts/process_dlq.py`) with `--requeue`, `--dry-run`, `--limit` | `a3c4f50` |
| 7 | **PostgreSQL Pool Tuning** | pool_size=5, max_overflow=10, pool_recycle=1800s, pool_pre_ping=True | `a76ac9c` |
| 8 | **Media Cache Cleanup** | Auto-cleanup of files >7 days on worker startup (`MEDIA_CACHE_TTL_DAYS`) | `f013603` |
| 9 | **Compose Hardening** | Resource limits, no host ports for DB/Redis, json-file logging, fixed depends_on | `b5041b2` |
| 10 | **SLA & Monitoring** | Uptime Kuma config documented in `docs/uptime-kuma-config.md` | *(this commit)* |

## 📋 SLA Targets

| Metric | Target | Monitoring |
|--------|--------|------------|
| API Availability | 99.9% | Uptime Kuma `/ready` check |
| Message Processing p95 | < 5 min | Worker heartbeat + queue lag |
| Queue Lag | < 50 | Worker `/health` endpoint |
| Worker Uptime | 100% | Uptime Kuma HTTP check |
| Telegram Listener | 100% | Uptime Kuma HTTP check |

## 🚀 Deployment Checklist

### Pre-deploy
- [ ] Create secret files in `./secrets/` with 600 permissions
- [ ] Copy `.env.example` to `.env` and fill non-secret values
- [ ] Verify `docker-compose.yml` has correct image tags
- [ ] Run `docker compose build` to verify images build

### Deploy
```bash
# Start infrastructure
docker compose up -d postgres redis

# Run migrations (via migrator service)
docker compose up migrator

# Start application services
docker compose up -d api worker telegram_listener

# Verify health
curl http://localhost:8000/ready
curl http://localhost:8081/health
curl http://localhost:8082/health
```

### Post-deploy Verification
- [ ] API `/ready` returns 200 with `{"status":"healthy",...}`
- [ ] Worker `/health` returns 200 with queue_lag
- [ ] Telegram listener `/health` returns 200
- [ ] Uptime Kuma monitors all show "Up"
- [ ] Send test message to source channel → verify publication

## 🔧 Operational Commands

```bash
# View logs
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f telegram_listener

# Process dead-letter queue
docker compose exec worker python -m scripts.process_dlq --requeue --limit 50

# Manual media cleanup
docker compose exec worker find /app/media_cache -type f -mtime +7 -delete

# Check queue status
docker compose exec redis redis-cli LLEN promobot:raw_messages
docker compose exec redis redis-cli LLEN promobot:raw_messages:dead

# Database backup
docker compose exec postgres pg_dump -U promobot promobot > backup_$(date +%F).sql
```

## 📊 Monitoring Endpoints

| Service | Endpoint | Purpose |
|---------|----------|---------|
| API | `GET /live` | Liveness probe (process alive) |
| API | `GET /ready` | Readiness probe (DB+Redis+Queue OK) |
| API | `GET /health` | Full health with queue_lag |
| Worker | `GET :8081/health` | Worker health + queue_lag |
| Worker | `GET :8081/live` | Liveness probe |
| Listener | `GET :8082/health` | Listener health + last_processed |
| Listener | `GET :8082/live` | Liveness probe |

## 📈 Prometheus Metrics (Future)

Add `prometheus-fastapi-instrumentator` to expose `/metrics`:
- `promobot_messages_processed_total{status="published|failed|duplicate|filtered"}`
- `promobot_queue_lag`
- `promobot_processing_duration_seconds`
- `promobot_dlq_size`
- `promobot_telegram_api_errors_total`