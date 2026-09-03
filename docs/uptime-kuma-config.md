# Uptime Kuma Monitoring Configuration for PromoBot

## SLA Definitions

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| **API Availability** | 99.9% | < 99.5% | < 99% |
| **Message Processing Latency (p95)** | < 5 min | > 5 min | > 15 min |
| **Queue Lag** | < 50 | > 100 | > 500 |
| **Worker Health** | 100% | N/A | Down |
| **Telegram Listener Health** | 100% | N/A | Down |

## Uptime Kuma Monitor Configuration

### 1. API Readiness Check (Primary)
- **Type**: HTTP(s)
- **URL**: `http://promobot-api:8000/ready`
- **Method**: GET
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Retry**: 2
- **Accepted Status Codes**: 200
- **Tags**: `api`, `readiness`, `sla-primary`

**Alert Conditions**:
- Down → Critical (Telegram/Email)
- Degraded (status 503) → Warning

### 2. API Liveness Check (Secondary)
- **Type**: HTTP(s)
- **URL**: `http://promobot-api:8000/live`
- **Method**: GET
- **Interval**: 60 seconds
- **Timeout**: 5 seconds
- **Accepted Status Codes**: 200
- **Tags**: `api`, `liveness`

### 3. Worker Health Check
- **Type**: HTTP(s)
- **URL**: `http://promobot-worker:8081/health`
- **Method**: GET
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Accepted Status Codes**: 200
- **Tags**: `worker`, `health`

**Alert Conditions**:
- Down → Critical
- `queue_lag > 100` → Warning (via heartbeat/push or log parsing)

### 4. Telegram Listener Health Check
- **Type**: HTTP(s)
- **URL**: `http://promobot-telegram-listener:8082/health`
- **Method**: GET
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Accepted Status Codes**: 200
- **Tags**: `telegram`, `listener`, `health`

**Alert Conditions**:
- Down → Critical
- `last_processed_at > 10 min ago` → Warning

### 5. Database Health (via API)
- **Type**: HTTP(s)
- **URL**: `http://promobot-api:8000/health`
- **Method**: GET
- **Interval**: 60 seconds
- **Check Response Body**: `database == "ok"`
- **Tags**: `database`, `postgres`

### 6. Redis Health (via API)
- **Type**: HTTP(s)
- **URL**: `http://promobot-api:8000/health`
- **Method**: GET
- **Interval**: 60 seconds
- **Check Response Body**: `redis == "ok"`
- **Tags**: `redis`, `cache`

## Push Metrics (Heartbeat) for Advanced Alerting

For queue lag and processing latency alerts, configure push endpoints in Uptime Kuma:

### Worker Heartbeat (push every 30s)
```
POST https://uptime-kuma.example.com/api/push/{push-token}
Content-Type: application/json

{
  "status": "up",
  "msg": "queue_lag=5,last_processed=1704067200",
  "ping": 45
}
```

Configure in Worker code (add to `_handle_failure` and success path):
```python
async def _push_heartbeat(service_name: str, queue_lag: int, last_processed: int):
    """Push metrics to Uptime Kuma push endpoint."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                settings.UPTIME_KUMA_PUSH_URL,
                json={
                    "status": "up",
                    "msg": f"queue_lag={queue_lag},last_processed={last_processed}",
                },
                timeout=5.0
            )
    except Exception:
        pass  # Don't fail processing if push fails
```

## Alert Notification Channels

Configure in Uptime Kuma:
1. **Telegram Bot** - for critical alerts (bot token + chat ID)
2. **Email** - for warnings and daily summaries
3. **Webhook** - for integration with Slack/Discord/PagerDuty

## Maintenance Windows

Configure in Uptime Kuma to suppress alerts during:
- Daily backup: 03:00-04:00 UTC
- Weekly maintenance: Sunday 02:00-04:00 UTC

## Status Page

Enable Uptime Kuma public status page at `https://status.promobot.example.com` with:
- API Status (from `/ready`)
- Worker Status
- Telegram Listener Status
- Database Status
- Redis Status
- 90-day uptime history

## Runbook Links

Add to each monitor's "Note" field:
- **API Down**: https://github.com/enzostana/Promobot/wiki/Runbook-API-Down
- **Worker Down**: https://github.com/enzostana/Promobot/wiki/Runbook-Worker-Down
- **High Queue Lag**: https://github.com/enzostana/Promobot/wiki/Runbook-High-Queue-Lag
- **Telegram Listener Down**: https://github.com/enzostana/Promobot/wiki/Runbook-Telegram-Down