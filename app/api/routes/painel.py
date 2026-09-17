import json
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
            mint_raw = await client.get("promobot:mel_mint_status")
        finally:
            await client.aclose()
        last_processed_at = datetime.fromtimestamp(float(last_raw), tz=timezone.utc) if last_raw else None
        age = (datetime.now(timezone.utc) - last_processed_at).total_seconds() if last_processed_at else None
        try:
            mel_mint = json.loads(mint_raw) if mint_raw else None
        except (TypeError, ValueError):
            mel_mint = None
        return {
            "queue_length": queue_len,
            "dead_letter_length": dead_len,
            "last_processed_at": last_processed_at.isoformat() if last_processed_at else None,
            "last_processed_seconds_ago": round(age) if age is not None else None,
            "status": "healthy" if last_processed_at else "unknown",
            "mel_mint": mel_mint,
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
        if key_b in SECRET_KEYS:
            if value == "":
                continue  # blank secret = keep current
            await repo.upsert(key_b, value)
            write_secret_file(key_b, value)
        elif value == "":
            # Campo não-secreto vazio = limpar a lista (volta ao default/env).
            await repo.delete(key_b)
        else:
            await repo.upsert(key_b, value)
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
            "🔥 Teste do painel — Notebook Gamer por R$ 19,90! "
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
            --bg-gradient: linear-gradient(135deg, #fafbfc 0%, #eef1f6 100%);
            --surface: #ffffff; --surface-2: #f0f2f7;
            --border: #e6e8ee; --border-strong: #d4d8e1;
            --text-primary: #111318; --text-secondary: #3f4656;
            --text-muted: #5b6272; --text-faint: #8b90a0;
            --accent: #e2350d; --accent-strong: #c22e0a; --accent-2: #ff7a1a;
            --green: #14823c; --red: #d92d20; --amber: #b54708;
            --hover: rgba(16,24,40,.05);
            --shadow: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.08);
            --btn-primary-hover: #a82709;
            --btn-danger-bg: #fdecea; --btn-danger-border: #f0b9b3; --btn-danger-text: #b42318;
            --btn-success-bg: #e8f5ee; --btn-success-border: #bfe3d0; --btn-success-text: #14823c;
            --b-green-bg: #e8f5ee;   --b-green-text: #14823c;
            --b-red-bg: #fdecea;     --b-red-text: #d92d20;
            --b-amber-bg: #fff4e5;   --b-amber-text: #b54708;
            --msg-ok-bg: #e8f5ee; --msg-ok-text: #14823c; --msg-ok-border: #bfe3d0;
            --msg-err-bg: #fdecea; --msg-err-text: #b42318; --msg-err-border: #f0b9b3;
        }
        html[data-theme="dark"] {
            --bg-gradient: linear-gradient(135deg, #020617 0%, #0f172a 100%);
            --surface: #0f172a; --surface-2: #1e293b;
            --border: #1e293b; --border-strong: #334155;
            --text-primary: #f1f5f9; --text-secondary: #cbd5e1;
            --text-muted: #94a3b8; --text-faint: #64748b;
            --accent: #60a5fa; --accent-strong: #3b82f6; --accent-2: #93c5fd;
            --green: #4ade80; --red: #f87171; --amber: #fbbf24;
            --hover: rgba(255,255,255,.03);
            --shadow: 0 1px 3px rgba(0,0,0,.3);
            --btn-primary-hover: #2563eb;
            --btn-danger-bg: #450a0a; --btn-danger-border: #991b1b; --btn-danger-text: #fecaca;
            --btn-success-bg: #14532d; --btn-success-border: #166534; --btn-success-text: #bbf7d0;
            --b-green-bg: #052e16;   --b-green-text: var(--green);
            --b-red-bg: #450a0a;     --b-red-text: var(--red);
            --b-amber-bg: #451a03;   --b-amber-text: var(--amber);
            --msg-ok-bg: #052e16; --msg-ok-text: var(--green); --msg-ok-border: #166534;
            --msg-err-bg: #450a0a; --msg-err-text: #fecaca; --msg-err-border: #991b1b;
        }
        html { color-scheme: light; }
        html[data-theme="dark"] { color-scheme: dark; }

        .theme-btn {
            display: inline-flex; align-items: center; justify-content: center;
            width: 38px; height: 38px; border-radius: 12px; cursor: pointer;
            background: var(--surface-2); border: 1.5px solid var(--border-strong);
            color: var(--text-secondary); transition: all 0.15s; flex-shrink: 0;
        }
        .theme-btn:hover { background: var(--border-strong); color: var(--text-primary); }
        .theme-btn svg { width: 18px; height: 18px; }
        .theme-btn .ic-moon { display: none; }
        html[data-theme="dark"] .theme-btn .ic-moon { display: inline-block; }
        html[data-theme="dark"] .theme-btn .ic-sun { display: none; }

        body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg-gradient); min-height: 100vh; color: var(--text-secondary); }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; }
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
        .btn-primary:hover { background: var(--btn-primary-hover); }
        .btn-danger { background: var(--btn-danger-bg); border-color: var(--btn-danger-border); color: var(--btn-danger-text); }
        .btn-success { background: var(--btn-success-bg); border-color: var(--btn-success-border); color: var(--btn-success-text); }
        .badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 9999px; font-size: 0.7rem; font-weight: 700; }
        .badge-green { background: var(--b-green-bg); color: var(--b-green-text); }
        .badge-red { background: var(--b-red-bg); color: var(--b-red-text); }
        .badge-amber { background: var(--b-amber-bg); color: var(--b-amber-text); }
        .dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .msg { display: none; margin-top: 12px; padding: 8px 12px; border-radius: 8px; font-size: 0.8125rem; }
        .msg-ok { display: block; background: var(--msg-ok-bg); color: var(--msg-ok-text); border: 1px solid var(--msg-ok-border); }
        .msg-err { display: block; background: var(--msg-err-bg); color: var(--msg-err-text); border: 1px solid var(--msg-err-border); }
        .hint { font-size: 0.75rem; color: var(--text-faint); margin-top: 4px; }
        .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
        .chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 6px 3px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; background: var(--surface-2); border: 1px solid var(--border-strong); color: var(--text-primary); }
        .chip button { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 50%; border: 0; background: var(--border-strong); color: var(--text-secondary); font-size: 0.7rem; cursor: pointer; line-height: 1; padding: 0; }
        .chip button:hover { background: var(--red); color: #fff; }
        input.chip-input { border-style: dashed; }
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
                <button id="theme-btn" class="theme-btn" onclick="toggleTheme()" title="Alternar tema" aria-label="Alternar tema">
                    <svg class="ic-sun" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2m0 14v2m9-9h-2M5 12H3m15.36-6.36l-1.42 1.42M7.06 16.94l-1.42 1.42M18.36 18.36l-1.42-1.42M7.06 7.06L5.64 5.64M12 8a4 4 0 100 8 4 4 0 000-8z"/></svg>
                    <svg class="ic-moon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
                </button>
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
            <div id="mint-alert" style="display:none; margin-top:10px; padding:10px 14px; border-radius:10px; background:var(--red); color:#fff; font-weight:600; font-size:0.82rem;">
                ⚠️ Sessão da conta Mercado Livre rejeitada — os links saem sem header (e, com MINT_STRICT ligado, sem posts). Atualize o secret <code>mel_session</code>.
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
                        <label>Mercado Livre — matt_word</label>
                        <input type="text" id="mercadolivre_matt_word" placeholder=""" autocomplete="off">
                        <p class="hint">Parâmetro <code>matt_word</code>. Vazio = usa a word do <code>/social</code>.</p>
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
                    <button class="btn btn-primary" onclick="saveSection('afiliados', ['amazon_tag','mercadolivre_tag','mercadolivre_matt_word','shopee_tag','shopee_app_id'], 'msg-afiliados')">Salvar Afiliados</button>
                    <div id="msg-afiliados" class="msg"></div>
                </div>
            </div>

            <!-- Filtros -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Filtros</h2></div>
                <div class="card-body">
                    <div class="mb-4">
                        <label>Keywords bloqueadas (exclusões da busca)</label>
                        <div class="chips" id="chips-blocked_keywords"></div>
                        <input type="text" class="chip-input" id="input-blocked_keywords" placeholder="digite e pressione Enter para adicionar" autocomplete="off">
                        <input type="hidden" id="blocked_keywords">
                        <p class="hint">Ex.: fake, sorteio, esgotado, golpe. Campo vazio = volta às palavras anti-scam padrão.</p>
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
                        <p class="hint">Onde o bot publica as promoções aprovadas no Telegram.</p>
                    </div>
                    <div class="mb-4">
                        <label>Grupo WhatsApp (JID)</label>
                        <input type="text" id="whatsapp_target_chat" placeholder="120363410512355040@g.us">
                        <p class="hint">Grupo/contato alvo (o número pareado precisa estar no grupo).</p>
                    </div>
                    <div class="mb-4">
                        <label>Publicar no WhatsApp</label>
                        <select id="whatsapp_enabled">
                            <option value="1">Ligado</option>
                            <option value="0">Desligado</option>
                        </select>
                        <p class="hint">Se ligado, cada promoção aprovada também sai no grupo WhatsApp.</p>
                    </div>
                    <div class="mb-4">
                        <label>Enviar imagem no WhatsApp</label>
                        <select id="whatsapp_with_image">
                            <option value="1">Ligado</option>
                            <option value="0">Só texto + link</option>
                        </select>
                        <p class="hint">Quando houver imagem disponível na oferta.</p>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('destinos', ['telegram_target_chat','whatsapp_target_chat','whatsapp_enabled','whatsapp_with_image'], 'msg-destino')">Salvar Destino</button>
                    <div id="msg-destino" class="msg"></div>
                </div>
            </div>

            <!-- Caçador de ofertas -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Caçador de ofertas</h2></div>
                <div class="card-body">
                    <p class="text-sm mb-4" style="color:var(--text-muted);">Busca automática na Open API de Afiliados Shopee por keyword e enfileira as ofertas que passam nas regras abaixo.</p>
                    <div class="mb-4">
                        <label>Ligado</label>
                        <select id="shopee_finder_enabled">
                            <option value="1">Ligado</option>
                            <option value="0">Desligado</option>
                        </select>
                    </div>
                    <div class="mb-4">
                        <label>Credenciais — App ID (Open API)</label>
                        <input type="text" id="shopee_api_app_id" placeholder="••••" autocomplete="off">
                        <p class="hint">App ID da aba "Abrir API" em <b>affiliate.shopee.com.br</b>.</p>
                    </div>
                    <div class="mb-4">
                        <label>Credenciais — Secret (Open API)</label>
                        <input type="text" id="shopee_api_secret" placeholder="••••" autocomplete="off">
                        <p class="hint">Secret da aba "Abrir API". Mostrado mascarado; vazio = manter atual.</p>
                    </div>
                    <div class="mb-4">
                        <label>Keywords (vírgula)</label>
                        <input type="text" id="shopee_finder_keywords" placeholder="fone bluetooth, smart tv…">
                    </div>
                    <div class="grid grid-cols-3 gap-3 mb-4">
                        <div><label>Desc. mín. (%)</label><input type="text" id="shopee_finder_min_discount"></div>
                        <div><label>Vendas mín.</label><input type="text" id="shopee_finder_min_sales"></div>
                        <div><label>Rating mín.</label><input type="text" id="shopee_finder_min_rating"></div>
                        <div><label>Preço máx. (R$)</label><input type="text" id="shopee_finder_max_price"></div>
                        <div><label>Intervalo (min)</label><input type="text" id="shopee_finder_interval_min"></div>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('caçador', ['shopee_api_app_id','shopee_api_secret','shopee_finder_enabled','shopee_finder_keywords','shopee_finder_min_discount','shopee_finder_min_sales','shopee_finder_min_rating','shopee_finder_max_price','shopee_finder_interval_min'], 'msg-cacador')">Salvar Caçador Shopee</button>
                    <div id="msg-cacador" class="msg"></div>
                </div>
            </div>

            <!-- Caçador Mercado Livre -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Caçador Mercado Livre</h2></div>
                <div class="card-body">
                    <p class="text-sm mb-4" style="color:var(--text-muted);">Busca automática na API pública do Mercado Livre por keyword e enfileira itens com desconto real (mín. configurado). O link já sai com a sua tag <code>matt_tool</code>.</p>
                    <div class="mb-4">
                        <label>Ligado</label>
                        <select id="mel_finder_enabled">
                            <option value="1">Ligado</option>
                            <option value="0">Desligado</option>
                        </select>
                    </div>
                    <div class="mb-4">
                        <label>Credenciais — Client ID</label>
                        <input type="text" id="mel_api_client_id" placeholder="••••" autocomplete="off">
                        <p class="hint">App criado em <b>developers.mercadolivre.com.br</b>.</p>
                    </div>
                    <div class="mb-4">
                        <label>Credenciais — Client Secret</label>
                        <input type="text" id="mel_api_client_secret" placeholder="••••" autocomplete="off">
                        <p class="hint">Secret do app. Mascarado; vazio = manter atual.</p>
                    </div>
                    <div class="mb-4">
                        <label>Refresh Token (OAuth offline_access)</label>
                        <input type="text" id="mel_refresh_token" placeholder="••••" autocomplete="off">
                        <p class="hint">Obtido em <b>mel/connect</b> ou configurando manualmente o fluxo de autorização. Mascarado; vazio = manter atual.</p>
                    </div>
                    <div class="mb-4">
                        <label>Keywords da busca (Mercado Livre)</label>
                        <div class="chips" id="chips-mel_finder_keywords"></div>
                        <input type="text" class="chip-input" id="input-mel_finder_keywords" placeholder="digite e pressione Enter para adicionar" autocomplete="off">
                        <input type="hidden" id="mel_finder_keywords">
                        <p class="hint">Termos procurados na página de ofertas. Vazio = volta às keywords padrão do ambiente.</p>
                    </div>
                    <div class="grid grid-cols-3 gap-3 mb-4">
                        <div><label>Desc. mín. (%)</label><input type="text" id="mel_finder_min_discount"></div>
                        <div><label>Preço máx. (R$)</label><input type="text" id="mel_finder_max_price"></div>
                        <div><label>Intervalo (min)</label><input type="text" id="mel_finder_interval_min"></div>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('caçador', ['mel_api_client_id','mel_api_client_secret','mel_refresh_token','mel_finder_enabled','mel_finder_keywords','mel_finder_min_discount','mel_finder_max_price','mel_finder_interval_min'], 'msg-cacador-mel')">Salvar Caçador MEL</button>
                    <div id="msg-cacador-mel" class="msg"></div>
                </div>
            </div>

            <!-- Caçador Amazon -->
            <div class="card">
                <div class="card-header"><h2 class="font-bold" style="color:var(--text-primary);">Caçador Amazon</h2></div>
                <div class="card-body">
                    <p class="text-sm mb-4" style="color:var(--text-muted);">Busca automática na página pública de Ofertas da Amazon (amazon.com.br/deals). Sem credenciais: o caçador raspa o storefront, filtra pelas regras abaixo e enfileira as ofertas — a tag <code>AMAZON_TAG</code> é injetada no pipeline.</p>
                    <div class="mb-4">
                        <label>Ligado</label>
                        <select id="amazon_finder_enabled">
                            <option value="1">Ligado</option>
                            <option value="0">Desligado</option>
                        </select>
                    </div>
                    <div class="mb-4">
                        <label>Keywords do filtro (Amazon)</label>
                        <div class="chips" id="chips-amazon_finder_keywords"></div>
                        <input type="text" class="chip-input" id="input-amazon_finder_keywords" placeholder="digite e pressione Enter para adicionar" autocomplete="off">
                        <input type="hidden" id="amazon_finder_keywords">
                        <p class="hint">Termos que serão procurados no título da oferta. Vazio = volta às keywords padrão do ambiente.</p>
                    </div>
                    <div class="grid grid-cols-3 gap-3 mb-4">
                        <div><label>Desc. mín. (%)</label><input type="text" id="amazon_finder_min_discount"></div>
                        <div><label>Preço máx. (R$)</label><input type="text" id="amazon_finder_max_price"></div>
                        <div><label>Intervalo (min)</label><input type="text" id="amazon_finder_interval_min"></div>
                    </div>
                    <button class="btn btn-primary" onclick="saveSection('caçador', ['amazon_finder_enabled','amazon_finder_keywords','amazon_finder_min_discount','amazon_finder_max_price','amazon_finder_interval_min'], 'msg-cacador-amazon')">Salvar Caçador Amazon</button>
                    <div id="msg-cacador-amazon" class="msg"></div>
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
        function applyTheme(t) {
            t = t || 'light';
            document.documentElement.setAttribute('data-theme', t);
            try { localStorage.setItem('promobot-theme', t); } catch (e) {}
        }
        function toggleTheme() {
            var cur = document.documentElement.getAttribute('data-theme') || 'light';
            applyTheme(cur === 'dark' ? 'light' : 'dark');
        }
        (function initTheme() {
            var t;
            try { t = localStorage.getItem('promobot-theme'); } catch (e) {}
            if (!t) { t = (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light'; }
            applyTheme(t);
        })();

        const SECRET_KEYS = ["amazon_tag","mercadolivre_tag","shopee_tag","shopee_app_id","shopee_api_app_id","shopee_api_secret","mel_api_client_id","mel_api_client_secret","mel_refresh_token"];
        const TAG_KEYS = ["blocked_keywords","mel_finder_keywords","amazon_finder_keywords"];
        const TAG_DATA = {};
        function splitTags(value) {
            return String(value || "").split(",").map(s => s.trim()).filter(Boolean);
        }
        function syncHidden(key) {
            document.getElementById(key).value = (TAG_DATA[key] || []).join(",");
        }
        function renderChips(key) {
            const box = document.getElementById("chips-" + key);
            if (!box) return;
            TAG_DATA[key] = splitTags(document.getElementById(key).value);
            box.innerHTML = "";
            TAG_DATA[key].forEach((t, i) => {
                const chip = document.createElement("span");
                chip.className = "chip";
                chip.textContent = t;
                const x = document.createElement("button");
                x.type = "button";
                x.textContent = "✕";
                x.title = "Remover " + t;
                x.onclick = () => { TAG_DATA[key].splice(i, 1); syncHidden(key); renderChips(key); };
                chip.appendChild(x);
                box.appendChild(chip);
            });
        }
        function addChip(key) {
            const input = document.getElementById("input-" + key);
            const tags = splitTags(input.value);
            input.value = "";
            if (!tags.length) return;
            const cur = TAG_DATA[key] || [];
            tags.forEach(t => {
                t = t.toLowerCase();
                if (!cur.includes(t)) cur.push(t);
            });
            TAG_DATA[key] = cur;
            syncHidden(key);
            renderChips(key);
        }
        function bindChipInput(key) {
            const input = document.getElementById("input-" + key);
            if (!input) return;
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addChip(key); }
            });
            input.addEventListener("blur", () => { if (input.value.trim()) addChip(key); });
        }
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
                    } else if (el.tagName === 'SELECT') {
                        const truthy = ["True", "true", "1", "on", "yes"];
                        el.value = truthy.includes(meta.value) ? "1" : "0";
                    } else {
                        el.value = meta.value || "";
                    }
                }
                TAG_KEYS.forEach(key => { bindChipInput(key); renderChips(key); });
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
                const mint = data.worker.mel_mint;
                document.getElementById('mint-alert').style.display =
                    (mint && mint.mint_enabled && mint.ok === false) ? 'block' : 'none';
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