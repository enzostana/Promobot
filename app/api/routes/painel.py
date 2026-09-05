import logging
from typing import Dict, List, Optional
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.api.routes.dashboard import verify_dashboard_credentials
from app.config.settings import Settings
from app.core.models import RawMessage
from app.core.runtime_settings import (
    EDITABLE_KEYS,
    SECTIONS,
    SECRET_KEYS,
    RuntimeOverrides,
    mask_secret,
    resolve_values,
    validate_section,
    write_secret_file,
)
from app.database.repositories.setting_repo import SettingRepository
from app.workers.queue import RedisQueue
import redis.asyncio as redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/painel", tags=["Control Panel"])

AUTH = [Depends(verify_dashboard_credentials)]

settings = Settings()
runtime_overrides = RuntimeOverrides()


def _paused_value(values: Dict[str, str]) -> bool:
    return values.get("bot_paused") == "1"


async def _get_worker_status() -> dict:
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            last_raw = await client.get("promobot:last_processed:worker")
            queue_len = await client.llen(settings.REDIS_QUEUE_NAME)
            dead_len = await client.llen(f"{settings.REDIS_QUEUE_NAME}:dead")
        finally:
            await client.aclose()
        last_processed_at = datetime.fromtimestamp(float(last_raw), tz=timezone.utc) if last_raw else None
        age = (datetime.now(timezone.utc) - last_processed_at).total_seconds() if last_processed_at else None
        return {
            "queue_length": queue_len,
            "dead_letter_length": dead_len,
            "last_processed_at": last_processed_at.isoformat() if last_processed_at else None,
            "last_processed_seconds_ago": round(age) if age is not None else None,
            "status": "healthy" if last_processed_at else "unknown",
        }
    except Exception as e:
        logger.warning(f"[PAINEL] erro ao ler status do worker: {e}")
        return {"queue_length": None, "dead_letter_length": None, "last_processed_at": None,
                "last_processed_seconds_ago": None, "status": "unknown", "error": str(e)}


@router.get("", response_class=HTMLResponse, dependencies=AUTH)
async def painel_page():
    return PAINEL_HTML


class SectionUpdate(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)


@router.get("/values", dependencies=AUTH)
async def get_values(db=Depends(get_db)):
    from sqlalchemy.ext.asyncio import AsyncSession
    session: AsyncSession = db
    repo = SettingRepository(session)
    overrides = await repo.get_all()
    resolved = resolve_values(settings, overrides)
    worker = await _get_worker_status()
    return {
        "sections": {name: {"keys": keys} for name, keys in SECTIONS.items()},
        "settings": resolved,
        "paused": _paused_value(overrides),
        "worker": worker,
    }


@router.put("/section/{section}", dependencies=AUTH)
async def update_section(section: str, payload: SectionUpdate, db=Depends(get_db)):
    from sqlalchemy.ext.asyncio import AsyncSession
    session: AsyncSession = db
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail=f"Seção desconhecida: '{section}'")

    submitted = {k: v for k, v in payload.values.items() if k in SECTIONS[section]}
    errors = validate_section(section, submitted)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    repo = SettingRepository(session)
    for key_b, raw_value in submitted.items():
        value = str(raw_value).strip()
        if value == "":
            continue  # blank = keep current value
        await repo.upsert(key_b, value)
        if key_b in SECRET_KEYS:
            write_secret_file(key_b, value)
    await session.commit()

    runtime_overrides._cache = None  # invalidate worker-side cache is separate process; invalidate API view
    overrides = await repo.get_all()
    resolved = resolve_values(settings, overrides)
    return {
        "ok": True,
        "section": section,
        "settings": resolved,
        "paused": _paused_value(overrides),
    }


@router.post("/test", dependencies=AUTH)
async def send_test_promotion(db=Depends(get_db)):
    from sqlalchemy.ext.asyncio import AsyncSession
    session: AsyncSession = db
    repo = SettingRepository(session)
    overrides = await repo.get_all()
    paused = _paused_value(overrides)
    if paused:
        raise HTTPException(status_code=409, detail="Bot está pausado. Retome antes de enviar o teste.")

    raw = RawMessage(
        id=f"painel-test-{uuid4().hex[:8]}",
        source="painel",
        source_message_id=str(uuid4().hex[:8]),
        source_chat_id="@painel",
        source_chat_title="Teste do Painel",
        text=(
            "🔥 Promoção de teste do painel por R$ 19,90! "
            "https://www.mercadolivre.com.br/p/MLB999000123"
        ),
        received_at=datetime.now(timezone.utc),
    )
    queue = RedisQueue(settings)
    await queue.enqueue(raw)
    return {"ok": True, "enqueued": True, "message_id": raw.id}


class PauseRequest(BaseModel):
    paused: bool


@router.post("/pause", dependencies=AUTH)
async def set_paused(payload: PauseRequest, db=Depends(get_db)):
    from sqlalchemy.ext.asyncio import AsyncSession
    session: AsyncSession = db
    repo = SettingRepository(session)
    await repo.upsert("bot_paused", "1" if payload.paused else "0")
    await session.commit()
    return {"ok": True, "paused": payload.paused}


PAINEL_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PromoBot — Painel de Controle</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-gradient: linear-gradient(135deg, #020617 0%, #0f172a 100%);
            --surface: #0f172a; --surface-2: #1e293b;
            --border: #1e293b; --border-strong: #334155;
            --text-primary: #f1f5f9; --text-secondary: #cbd5e1;
            --text-muted: #94a3b8; --text-faint: #64748b;
            --accent: #60a5fa; --accent-strong: #3b82f6;
            --green: #4ade80; --red: #f87171; --amber: #fbbf24;
        }
        html { color-scheme: dark; }
        body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg-gradient); min-height: 100vh; color: var(--text-secondary); }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); overflow: hidden; }
        .card-header { padding: 16px 20px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
        .card-body { padding: 20px; }
        label { display: block; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
        input[type=text], input[type=number] {
            width: 100%; padding: 9px 12px; border-radius: 8px; font-size: 0.875rem;
            background: var(--surface-2); border: 1.5px solid var(--border-strong);
            color: var(--text-primary); outline: none;
        }
        input:focus { border-color: var(--accent-strong); }
        .btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border-radius: 8px; font-size: 0.8125rem; font-weight: 600; border: 1.5px solid var(--border-strong); background: var(--surface-2); color: var(--text-secondary); transition: all 0.15s; cursor: pointer; }
        .btn:hover { background: var(--border-strong); }
        .btn-primary { background: var(--accent-strong); border-color: var(--accent-strong); color: #fff; }
        .btn-primary:hover { background: #2563eb; }
        .btn-danger { background: #7f1d1d; border-color: #991b1b; color: #fecaca; }
        .btn-success { background: #14532d; border-color: #166534; color: #bbf7d0; }
        .badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 9999px; font-size: 0.7rem; font-weight: 700; }
        .badge-green { background: #052e16; color: var(--green); }
        .badge-red { background: #450a0a; color: var(--red); }
        .badge-amber { background: #451a03; color: var(--amber); }
        .dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .msg { display: none; margin-top: 12px; padding: 8px 12px; border-radius: 8px; font-size: 0.8125rem; }
        .msg-ok { display: block; background: #052e16; color: var(--green); border: 1px solid #166534; }
        .msg-err { display: block; background: #450a0a; color: #fecaca; border: 1px solid #991b1b; }
        .hint { font-size: 0.75rem; color: var(--text-faint); margin-top: 4px; }
        .pill-status { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; background: var(--surface-2); border: 1.5px solid var(--border-strong); color: var(--text-secondary); }
        .grid2 { display: grid; grid-template-columns: 1fr; gap: 16px; }
        @media (min-width: 900px) { .grid2 { grid-template-columns: 1fr 1fr; } }
    </style>
</head>
<body class="p-6">
    <div class="max-w-5xl mx-auto">
        <header class="flex flex-wrap items-center justify-between gap-4 mb-6">
            <div>
                <h1 class="text-2xl font-extrabold" style="color:var(--text-primary);">Painel de Controle</h1>
                <p class="text-sm font-medium" style="color:var(--text-muted);">Gestão do PromoBot — tags, filtros e destino</p>
            </div>
            <div class="flex items-center gap-3">
                <span id="bot-pill" class="pill-status"><span class="dot" style="background:var(--text-faint);"></span>carregando…</span>
                <a href="/dashboard" class="btn">← Dashboard</a>
            </div>
        </header>

        <div id="worker-strip" class="card mb-6">
            <div class="card-body flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
                <span>Status: <strong id="ws-status" style="color:var(--text-primary);">—</strong></span>
                <span>Fila: <strong id="ws-queue" style="color:var(--text-primary);">—</strong></span>
                <span>Dead-letter: <strong id="ws-dead" style="color:var(--text-primary);">—</strong></span>
                <span>Última mensagem: <strong id="ws-last" style="color:var(--text-primary);">—</strong></span>
            </div>
        </div>

        <div class="grid2">
            <!-- Afiliados -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Afiliados</h2></div>
                <div class="card-body">
                    <div class="mb-4">
                        <label>Amazon — tag</label>
                        <input type="text" id="amazon_tag" placeholder="••••" autocomplete="off">
                        <p class="hint">Parâmetro <code>tag</code> da URL. Ex.: <b>minhatag-20</b>.</p>
                    </div>
                    <div class="mb-4">
                        <label>Mercado Livre — tag (matt_tool)</label>
                        <input type="text" id="mercadolivre_tag" placeholder="••••" autocomplete="off">
                        <p class="hint">Parâmetro <code>matt_tool</code> do link de afiliado.</p>
                    </div>
                    <div class="mb-4">
                        <label>Shopee — tag (aff_trace_key)</label>
                        <input type="text" id="shopee_tag" placeholder="••••" autocomplete="off">
                    </div>
                    <div class="mb-4">
                        <label>Shopee — App ID</label>
                        <input type="text" id="shopee_app_id" placeholder="••••" autocomplete="off">
                        <p class="hint">Usado junto com o <code>aff_trace_key</code>.</p>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('afiliados', ['amazon_tag','mercadolivre_tag','shopee_tag','shopee_app_id'], 'msg-afiliados')">Salvar Afiliados</button>
                    <div id="msg-afiliados" class="msg"></div>
                </div>
            </div>

            <!-- Filtros -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Filtros</h2></div>
                <div class="card-body">
                    <div class="mb-4">
                        <label>Keywords bloqueadas (vírgula)</label>
                        <input type="text" id="blocked_keywords" placeholder="esgotado, sorteio…">
                    </div>
                    <div class="mb-4">
                        <label>Keywords obrigatórias (vírgula)</label>
                        <input type="text" id="required_keywords" placeholder="(vazio = todas)">
                    </div>
                    <div class="mb-4">
                        <label>Lojas permitidas (whitelist)</label>
                        <input type="text" id="allowed_stores" placeholder="(vazio = todas)">
                    </div>
                    <div class="mb-4">
                        <label>Lojas bloqueadas (blacklist)</label>
                        <input type="text" id="blocked_stores" placeholder="amazon, …">
                    </div>
                    <div class="mb-4">
                        <label>Categorias permitidas</label>
                        <input type="text" id="allowed_categories" placeholder="(vazio = todas)">
                    </div>
                    <div class="mb-4">
                        <label>Categorias bloqueadas</label>
                        <input type="text" id="blocked_categories" placeholder="moda, …">
                    </div>
                    <div class="grid grid-cols-3 gap-3 mb-4">
                        <div><label>Desc. mín. (%)</label><input type="text" id="min_discount_percent"></div>
                        <div><label>Preço mín. (R$)</label><input type="text" id="min_price"></div>
                        <div><label>Preço máx. (R$)</label><input type="text" id="max_price"></div>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('filtros', ['blocked_keywords','required_keywords','allowed_stores','blocked_stores','allowed_categories','blocked_categories','min_discount_percent','min_price','max_price'], 'msg-filtros')">Salvar Filtros</button>
                    <div id="msg-filtros" class="msg"></div>
                </div>
            </div>

            <!-- Destino -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Destino</h2></div>
                <div class="card-body">
                    <div class="mb-4">
                        <label>Canal de destino (chat_id)</label>
                        <input type="text" id="telegram_target_chat" placeholder="-100xxxxxxxxxx">
                        <p class="hint">Onde o bot publica as promoções aprovadas.</p>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('destinos', ['telegram_target_chat'], 'msg-destino')">Salvar Destino</button>
                    <div id="msg-destino" class="msg"></div>
                </div>
            </div>

            <!-- Ações -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Ações</h2></div>
                <div class="card-body">
                    <p class="text-sm mb-4" style="color:var(--text-muted);">Teste o pipeline de ponta a ponta enfileirando uma promoção sintética, ou pause/resuma o processamento.</p>
                    <div class="flex flex-wrap gap-3">
                        <button class="btn btn-success" onclick="sendTest()">▶ Enviar promoção de teste</button>
                        <button class="btn btn-danger" id="pause-btn" onclick="setPause(true)" style="display:none;">Pausar bot</button>
                        <button class="btn btn-success" id="resume-btn" onclick="setPause(false)" style="display:none;">Retomar bot</button>
                    </div>
                    <div id="msg-acoes" class="msg"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const SECRET_KEYS = ["amazon_tag","mercadolivre_tag","shopee_tag","shopee_app_id"];
        function showMsg(id, ok, text) {
            const el = document.getElementById(id);
            el.className = "msg " + (ok ? "msg-ok" : "msg-err");
            el.textContent = text;
            setTimeout(() => { el.className = "msg"; }, 6000);
        }
        async function load() {
            try {
                const r = await fetch('/painel/values');
                if (r.status === 401) { window.location.reload(); return; }
                const data = await r.json();
                for (const [key, meta] of Object.entries(data.settings)) {
                    const el = document.getElementById(key);
                    if (!el) continue;
                    if (SECRET_KEYS.includes(key)) {
                        el.placeholder = meta.masked || "•••• (vazio = manter atual)";
                        el.value = "";
                    } else {
                        el.value = meta.value || "";
                    }
                }
                const pill = document.getElementById('bot-pill');
                if (data.paused) { pill.innerHTML = '<span class="dot" style="background:var(--red);"></span>pausado'; }
                else { pill.innerHTML = '<span class="dot" style="background:var(--green);"></span>ativo — ' + (data.worker.status || '?'); }
                document.getElementById('pause-btn').style.display = data.paused ? 'none' : 'inline-flex';
                document.getElementById('resume-btn').style.display = data.paused ? 'inline-flex' : 'none';
                document.getElementById('ws-status').textContent = data.worker.status || '—';
                document.getElementById('ws-queue').textContent = data.worker.queue_length ?? '—';
                document.getElementById('ws-dead').textContent = data.worker.dead_letter_length ?? '—';
                const last = data.worker.last_processed_seconds_ago;
                document.getElementById('ws-last').textContent = last == null ? '—' : last + 's atrás';
            } catch (e) { console.error(e); }
        }
        async function saveSection(section, keys, msgId) {
            const values = {};
            keys.forEach(k => { const el = document.getElementById(k); values[k] = el.value; });
            try {
                const r = await fetch('/painel/section/' + section, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ values })
                });
                const data = await r.json();
                if (r.ok) {
                    showMsg(msgId, true, 'Salvo com sucesso!');
                    if (SECRET_KEYS.some(k => k in values)) { location.reload(); }
                } else {
                    showMsg(msgId, false, 'Erro: ' + (data.detail || r.status));
                }
            } catch (e) { showMsg(msgId, false, 'Falha de rede: ' + e); }
        }
        async function sendTest() {
            try {
                const r = await fetch('/painel/test', { method: 'POST' });
                const data = await r.json();
                showMsg('msg-acoes', r.ok, r.ok ? 'Mensagem de teste enfileirada!' : 'Erro: ' + (data.detail || r.status));
            } catch (e) { showMsg('msg-acoes', false, 'Falha de rede: ' + e); }
        }
        async function setPause(paused) {
            try {
                const r = await fetch('/painel/pause', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ paused })
                });
                const data = await r.json();
                if (r.ok) { showMsg('msg-acoes', true, paused ? 'Bot pausado.' : 'Bot retomado.'); load(); }
                else { showMsg('msg-acoes', false, 'Erro: ' + (data.detail || r.status)); }
            } catch (e) { showMsg('msg-acoes', false, 'Falha de rede: ' + e); }
        }
        load();
    </script>
</body>
</html>
'''