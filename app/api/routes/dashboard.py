from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.api.deps import get_db
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.source_repo import SourceRepository
from app.database.repositories.publication_repo import PublicationRepository
from sqlalchemy import text
from jinja2 import Template

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

security = HTTPBasic()


def verify_dashboard_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    settings = get_settings()
    correct_username = settings.DASHBOARD_USERNAME or "admin"
    correct_password = settings.DASHBOARD_PASSWORD or "admin"
    if not (secrets.compare_digest(credentials.username, correct_username) and
            secrets.compare_digest(credentials.password, correct_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PromoBot Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'media',
            theme: {
                extend: {
                    colors: {
                        brand: { 50:'#eff6ff', 100:'#dbeafe', 200:'#bfdbfe', 300:'#93c5fd', 400:'#60a5fa', 500:'#3b82f6', 600:'#2563eb', 700:'#1d4ed8', 800:'#1e40af', 900:'#1e3a8a' },
                        surface: { 50:'#f8fafc', 100:'#f1f5f9', 200:'#e2e8f0', 300:'#cbd5e1', 400:'#94a3b8', 500:'#64748b', 600:'#475569', 700:'#334155', 800:'#1e293b', 900:'#0f172a', 950:'#020617' }
                    },
                    fontFamily: { sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'] }
                }
            }
        }
    </script>
    <style>
        :root {
            --bg-gradient: linear-gradient(135deg, #020617 0%, #0f172a 100%);
            --surface: #0f172a;
            --surface-2: #1e293b;
            --border: #1e293b;
            --border-strong: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #cbd5e1;
            --text-muted: #94a3b8;
            --text-faint: #64748b;
            --accent: #60a5fa;
            --accent-strong: #3b82f6;
            --green: #4ade80;
            --red: #f87171;
        }
        html { color-scheme: dark; }
        body { font-family: 'Inter', system-ui, -apple-system, sans-serif; }

        .chip {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 6px 14px; border-radius: 9999px;
            font-size: 0.8125rem; font-weight: 600;
            transition: all 0.15s ease; cursor: pointer; user-select: none;
            border: 1.5px solid transparent;
        }
        .chip-default { background: var(--surface-2); color: var(--text-muted); border-color: var(--border-strong); }
        .chip-default:hover { background: var(--border-strong); color: var(--text-secondary); }
        .chip-active { background: #2563eb !important; color: #fff !important; border-color: #1d4ed8 !important; box-shadow: 0 1px 3px rgba(37,99,235,0.3); }

        .card {
            background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3); overflow: hidden;
        }

        .tab-btn {
            padding: 10px 18px; font-size: 0.875rem; font-weight: 600;
            border-radius: 10px 10px 0 0; transition: all 0.15s ease;
            border-bottom: 2.5px solid transparent;
            color: var(--text-faint); background: transparent;
        }
        .tab-btn:hover { color: var(--text-muted); background: rgba(255,255,255,0.02); }
        .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent-strong); background: var(--surface); }

        .tbl-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        table { width: 100%; border-collapse: separate; border-spacing: 0; min-width: 700px; }
        th {
            padding: 12px 16px; text-align: left;
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em;
            text-transform: uppercase; color: var(--text-muted);
            background: var(--surface-2); border-bottom: 1.5px solid var(--border-strong);
        }
        td {
            padding: 12px 16px; font-size: 0.8125rem; color: var(--text-secondary);
            border-bottom: 1px solid var(--border);
        }
        tbody tr { transition: background 0.1s; }
        tbody tr:hover { background: rgba(255,255,255,0.02); }

        .badge {
            display: inline-flex; align-items: center; gap: 4px;
            padding: 3px 10px; border-radius: 9999px;
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.02em;
        }
        .badge-green { background: #052e16; color: var(--green); }
        .badge-amber { background: #451a03; color: #fbbf24; }
        .badge-gray  { background: var(--surface-2); color: var(--text-muted); }
        .badge-red   { background: #450a0a; color: var(--red); }
        .badge-blue  { background: #172554; color: var(--accent); }
        .badge-dot {
            width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
        }
        .badge-green .badge-dot { background: #22c55e; }
        .badge-amber .badge-dot { background: #f59e0b; }
        .badge-gray  .badge-dot { background: #94a3b8; }
        .badge-red   .badge-dot { background: #ef4444; }
        .badge-blue  .badge-dot { background: #3b82f6; }

        .empty-box {
            display: flex; flex-direction: column; align-items: center;
            justify-content: center; padding: 48px 16px; text-align: center;
        }
        .empty-box svg { width: 56px; height: 56px; color: var(--border-strong); margin-bottom: 16px; }
        .empty-box p { color: var(--text-muted); font-size: 0.875rem; }
        .empty-box span { color: var(--text-faint); font-size: 0.75rem; margin-top: 4px; }

        .pg-btn {
            padding: 6px 14px; font-size: 0.8125rem; font-weight: 600;
            border-radius: 8px; border: 1.5px solid var(--border-strong);
            color: var(--text-muted); background: var(--surface-2); transition: all 0.15s;
        }
        .pg-btn:hover { background: var(--border-strong); }
        .pg-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        .htmx-indicator { opacity: 0; transition: opacity 0.2s; }
        .htmx-request .htmx-indicator, .htmx-request.htmx-indicator { opacity: 1; }

        .fade-in { animation: fadeIn 0.2s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body class="min-h-screen" style="background: var(--bg-gradient);">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">

        <header class="mb-8">
            <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-11 h-11 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
                        <svg class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                        </svg>
                    </div>
                    <div>
                        <h1 class="text-xl sm:text-2xl font-extrabold" style="color:var(--text-primary);">PromoBot</h1>
                        <p class="text-sm font-medium" style="color:var(--text-muted);">Dashboard de Promoções</p>
                    </div>
                </div>
                <div class="flex items-center gap-3">
                    <span class="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-bold badge-green">
                        <span class="badge-dot"></span>
                        Online
                    </span>
                </div>
            </div>
        </header>

        <section class="mb-6" hx-get="/dashboard/filters/all" hx-trigger="load" hx-target="#filter-chips" hx-swap="innerHTML">
            <div id="filter-chips" class="flex flex-wrap gap-2 sm:gap-2.5">
                <div class="chip chip-default" style="pointer-events:none;opacity:0.5">Carregando filtros...</div>
            </div>
        </section>

        <div class="card">
            <div class="border-b" style="border-color:var(--border-strong);">
                <nav class="flex gap-0.5 px-2 pt-1" role="tablist">
                    <button id="tab-promocoes" class="tab-btn active" role="tab" aria-selected="true"
                        hx-get="/dashboard/partial/promocoes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML">
                        <span class="hidden sm:inline">Promoções</span>
                        <span class="sm:hidden">Promos</span>
                    </button>
                    <button id="tab-fontes" class="tab-btn" role="tab" aria-selected="false"
                        hx-get="/dashboard/partial/fontes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML">
                        Fontes
                    </button>
                    <button id="tab-publicacoes" class="tab-btn" role="tab" aria-selected="false"
                        hx-get="/dashboard/partial/publicacoes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML">
                        Pubs
                    </button>
                </nav>
            </div>
            <div id="table-container" class="p-3 sm:p-5">
                <div class="flex justify-center py-16">
                    <div class="flex flex-col items-center gap-3">
                        <svg class="animate-spin h-7 w-7 text-brand-600" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                        <span class="text-sm font-medium" style="color:var(--text-muted);">Carregando...</span>
                    </div>
                </div>
            </div>
        </div>

        <footer class="mt-8 text-center">
            <a href="/docs" class="text-xs font-medium" style="color:var(--text-muted);" target="_blank">API Docs &rarr;</a>
        </footer>
    </div>

    <script>
        document.body.addEventListener('htmx:afterSwap', function(e) {
            if (e.detail.target.id === 'table-container') {
                e.detail.target.classList.add('fade-in');
                document.querySelectorAll('[role="tab"]').forEach(b => {
                    var active = b.id === 'tab-' + e.detail.target.dataset.tab;
                    b.classList.toggle('active', active);
                    b.setAttribute('aria-selected', active);
                });
            }
        });
    </script>
</body>
</html>'''

DASHBOARD_FILTERS_HTML = '''<div class="flex flex-col gap-3" id="filter-chips">
    <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--text-muted);">Período</span>
        <div class="h-4 w-px" style="background:var(--border-strong);"></div>
        <button class="chip chip-default" data-filter="period" data-value="24h"
            hx-get="/dashboard/partial/promocoes?period=24h" hx-target="#table-container" hx-swap="innerHTML">24h</button>
        <button class="chip chip-default" data-filter="period" data-value="7d"
            hx-get="/dashboard/partial/promocoes?period=7d" hx-target="#table-container" hx-swap="innerHTML">7 dias</button>
        <button class="chip chip-default" data-filter="period" data-value="30d"
            hx-get="/dashboard/partial/promocoes?period=30d" hx-target="#table-container" hx-swap="innerHTML">30 dias</button>
        <button class="chip chip-default" data-filter="period" data-value="90d"
            hx-get="/dashboard/partial/promocoes?period=90d" hx-target="#table-container" hx-swap="innerHTML">90 dias</button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--text-muted);">Status</span>
        <div class="h-4 w-px" style="background:var(--border-strong);"></div>
        {% for s in statuses %}
        <button class="chip chip-default" data-filter="status" data-value="{{ s }}"
            hx-get="/dashboard/partial/promocoes?status={{ s }}" hx-target="#table-container" hx-swap="innerHTML">
            {{ s.replace('_', ' ').title() }}
        </button>
        {% endfor %}
        {% if not statuses %}
        <span class="text-xs" style="color:var(--text-muted);">Nenhum</span>
        {% endif %}
    </div>
    <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--text-muted);">Loja</span>
        <div class="h-4 w-px" style="background:var(--border-strong);"></div>
        {% for store in stores %}
        <button class="chip chip-default" data-filter="store" data-value="{{ store }}"
            hx-get="/dashboard/partial/promocoes?store={{ store }}" hx-target="#table-container" hx-swap="innerHTML">
            {{ store.title() }}
        </button>
        {% endfor %}
        {% if not stores %}
        <span class="text-xs" style="color:var(--text-muted);">Nenhuma</span>
        {% endif %}
    </div>
    <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--text-muted);">Categoria</span>
        <div class="h-4 w-px" style="background:var(--border-strong);"></div>
        {% for cat in categories %}
        <button class="chip chip-default" data-filter="category" data-value="{{ cat }}"
            hx-get="/dashboard/partial/promocoes?category={{ cat }}" hx-target="#table-container" hx-swap="innerHTML">
            {{ cat.replace('_', ' ').title() }}
        </button>
        {% endfor %}
        {% if not categories %}
        <span class="text-xs" style="color:var(--text-muted);">Nenhuma</span>
        {% endif %}
    </div>
    <div class="flex justify-end mt-1">
        <button class="chip chip-default" style="font-size:0.75rem;"
            hx-get="/dashboard/partial/promocoes" hx-target="#table-container" hx-swap="innerHTML">
            Limpar filtros
        </button>
    </div>
</div>'''

PROMOCOES_PARTIAL = '''<div data-tab="promocoes">
    <div class="tbl-wrap">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Produto</th>
                    <th>Loja</th>
                    <th>Preço</th>
                    <th>Promo</th>
                    <th>Desc.</th>
                    <th>Categoria</th>
                    <th>Status</th>
                    <th>Data</th>
                </tr>
            </thead>
            <tbody>
                {% if promotions.items %}
                    {% for p in promotions.items %}
                    <tr>
                        <td class="font-semibold" style="color:var(--text-muted);">#{{ p.id }}</td>
                        <td style="color:var(--text-primary); font-weight:500;">
                            <span class="truncate block max-w-[200px] sm:max-w-[300px]" title="{{ p.product_name }}">{{ p.product_name }}</span>
                        </td>
                        <td>
                            {% if p.store %}
                            <span class="badge badge-blue"><span class="badge-dot"></span>{{ p.store.title() }}</span>
                            {% else %}
                            <span style="color:var(--text-faint);">—</span>
                            {% endif %}
                        </td>
                        <td style="color:var(--text-muted);">{{ 'R$ ' + ("%.2f"|format(p.original_price)) if p.original_price is not none else '—' }}</td>
                        <td>
                            {% if p.sale_price is not none %}
                            <span class="font-bold" style="color:var(--green);">R$ {{ "%.2f"|format(p.sale_price) }}</span>
                            {% else %}
                            <span style="color:var(--text-faint);">—</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if p.discount_percentage is not none %}
                            <span class="badge badge-green"><span class="badge-dot"></span>{{ "%.0f"|format(p.discount_percentage) }}%</span>
                            {% else %}
                            <span style="color:var(--text-faint);">—</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if p.category %}
                            <span style="color:var(--text-secondary); font-weight:500;">{{ p.category.replace('_', ' ').title() }}</span>
                            {% else %}
                            <span style="color:var(--text-faint);">—</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if p.status == 'published' %}
                            <span class="badge badge-green"><span class="badge-dot"></span>Publicado</span>
                            {% elif p.status == 'filtered_out' %}
                            <span class="badge badge-amber"><span class="badge-dot"></span>Filtrado</span>
                            {% elif p.status == 'duplicate' %}
                            <span class="badge badge-gray"><span class="badge-dot"></span>Duplicado</span>
                            {% elif p.status == 'error' %}
                            <span class="badge badge-red"><span class="badge-dot"></span>Erro</span>
                            {% elif p.status == 'pending' %}
                            <span class="badge badge-blue"><span class="badge-dot"></span>Pendente</span>
                            {% else %}
                            <span class="badge badge-gray">{{ p.status }}</span>
                            {% endif %}
                        </td>
                        <td style="color:var(--text-muted); font-size:0.75rem; white-space:nowrap;">{{ format_date(p.created_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="9">
                            <div class="empty-box">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                                <p>Nenhuma promoção encontrada</p>
                                <span>Tente ampliar o período ou limpar os filtros</span>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    {% if promotions.total_pages > 1 %}
    <div class="flex flex-col sm:flex-row items-center justify-between mt-4 pt-4 gap-3" style="border-top:1px solid var(--border-strong);">
        <p class="text-xs font-medium" style="color:var(--text-muted);">
            Página {{ promotions.page }} de {{ promotions.total_pages }} &middot; {{ promotions.total }} promoções
        </p>
        <div class="flex gap-2">
            {% if promotions.page > 1 %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/promocoes?page={{ promotions.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">&larr; Anterior</button>
            {% endif %}
            {% if promotions.page < promotions.total_pages %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/promocoes?page={{ promotions.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">Próxima &rarr;</button>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>'''

FONTES_PARTIAL = '''<div data-tab="fontes">
    <div class="tbl-wrap">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Plataforma</th>
                    <th>Chat ID</th>
                    <th>Nome</th>
                    <th>Status</th>
                    <th>Criado em</th>
                </tr>
            </thead>
            <tbody>
                {% if sources.items %}
                    {% for s in sources.items %}
                    <tr>
                        <td class="font-semibold" style="color:var(--text-muted);">#{{ s.id }}</td>
                        <td><span class="badge badge-blue"><span class="badge-dot"></span>{{ s.platform }}</span></td>
                        <td style="font-family:monospace; font-size:0.8rem; color:var(--text-secondary);">{{ s.chat_id }}</td>
                        <td style="font-weight:500; color:var(--text-primary);">{{ s.name or '—' }}</td>
                        <td>
                            {% if s.is_active %}
                            <span class="badge badge-green"><span class="badge-dot"></span>Ativa</span>
                            {% else %}
                            <span class="badge badge-gray"><span class="badge-dot"></span>Inativa</span>
                            {% endif %}
                        </td>
                        <td style="color:var(--text-muted); font-size:0.75rem; white-space:nowrap;">{{ format_date(s.created_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="6">
                            <div class="empty-box">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                                <p>Nenhuma fonte configurada</p>
                                <span>Adicione canais de origem no banco de dados</span>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    {% if sources.total_pages > 1 %}
    <div class="flex flex-col sm:flex-row items-center justify-between mt-4 pt-4 gap-3" style="border-top:1px solid var(--border-strong);">
        <p class="text-xs font-medium" style="color:var(--text-muted);">
            Página {{ sources.page }} de {{ sources.total_pages }} &middot; {{ sources.total }} fontes
        </p>
        <div class="flex gap-2">
            {% if sources.page > 1 %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/fontes?page={{ sources.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">&larr; Anterior</button>
            {% endif %}
            {% if sources.page < sources.total_pages %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/fontes?page={{ sources.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">Próxima &rarr;</button>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>'''

PUBLICACOES_PARTIAL = '''<div data-tab="publicacoes">
    <div class="tbl-wrap">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Promo</th>
                    <th>Plataforma</th>
                    <th>Chat Alvo</th>
                    <th>Status</th>
                    <th>Erro</th>
                    <th>Publicado</th>
                </tr>
            </thead>
            <tbody>
                {% if publications.items %}
                    {% for p in publications.items %}
                    <tr>
                        <td class="font-semibold" style="color:var(--text-muted);">#{{ p.id }}</td>
                        <td class="font-semibold" style="color:var(--accent);">#{{ p.promotion_id }}</td>
                        <td><span class="badge badge-blue"><span class="badge-dot"></span>{{ p.platform }}</span></td>
                        <td style="font-family:monospace; font-size:0.8rem; color:var(--text-secondary);">{{ p.target_chat_id }}</td>
                        <td>
                            {% if p.status == 'published' %}
                            <span class="badge badge-green"><span class="badge-dot"></span>Publicado</span>
                            {% elif p.status == 'error' or p.status == 'failed' %}
                            <span class="badge badge-red"><span class="badge-dot"></span>Falhou</span>
                            {% elif p.status == 'pending' %}
                            <span class="badge badge-blue"><span class="badge-dot"></span>Pendente</span>
                            {% else %}
                            <span class="badge badge-gray">{{ p.status }}</span>
                            {% endif %}
                        </td>
                        <td style="max-width:180px;">
                            {% if p.error_message %}
                            <span class="truncate block font-medium" style="color:var(--red); font-size:0.75rem;" title="{{ p.error_message }}">{{ p.error_message }}</span>
                            {% else %}
                            <span style="color:var(--text-faint);">—</span>
                            {% endif %}
                        </td>
                        <td style="color:var(--text-muted); font-size:0.75rem; white-space:nowrap;">{{ format_date(p.published_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="7">
                            <div class="empty-box">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
                                <p>Nenhuma publicação realizada</p>
                                <span>As publicações aparecerão aqui quando forem enviadas</span>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    {% if publications.total_pages > 1 %}
    <div class="flex flex-col sm:flex-row items-center justify-between mt-4 pt-4 gap-3" style="border-top:1px solid var(--border-strong);">
        <p class="text-xs font-medium" style="color:var(--text-muted);">
            Página {{ publications.page }} de {{ publications.total_pages }} &middot; {{ publications.total }} publicações
        </p>
        <div class="flex gap-2">
            {% if publications.page > 1 %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/publicacoes?page={{ publications.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">&larr; Anterior</button>
            {% endif %}
            {% if publications.page < publications.total_pages %}
            <button class="pg-btn"
                hx-get="/dashboard/partial/publicacoes?page={{ publications.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">Próxima &rarr;</button>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>'''


def format_date(dt) -> str:
    if not dt:
        return '—'
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return str(dt)


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def dashboard_home():
    return HTMLResponse(content=DASHBOARD_HTML)


@router.get("/filters/all", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def dashboard_filters(db=Depends(get_db)):
    stores_result = await db.execute(
        text("SELECT DISTINCT store FROM promotions WHERE store IS NOT NULL ORDER BY store")
    )
    stores = [row[0] for row in stores_result.fetchall() if row[0]]

    statuses_result = await db.execute(
        text("SELECT DISTINCT status FROM promotions ORDER BY status")
    )
    statuses = [row[0] for row in statuses_result.fetchall()]

    categories_result = await db.execute(
        text("SELECT DISTINCT category FROM promotions WHERE category IS NOT NULL ORDER BY category")
    )
    categories = [row[0] for row in categories_result.fetchall() if row[0]]

    template = Template(DASHBOARD_FILTERS_HTML)
    return HTMLResponse(content=template.render(stores=stores, statuses=statuses, categories=categories))


class PaginatedResult:
    def __init__(self, items, total, page, page_size, total_pages):
        self.items = items
        self.total = total
        self.page = page
        self.page_size = page_size
        self.total_pages = total_pages


def parse_datetime(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace('Z', '+00:00'))
    except:
        return None


@router.get("/partial/promocoes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_promocoes(
    page: int = 1, page_size: int = 20,
    status: str = None, store: str = None, category: str = None,
    period: str = None,
    created_at__gte: str = None, created_at__lte: str = None,
    db=Depends(get_db)
):
    if period:
        now = datetime.now(timezone.utc)
        deltas = {'24h': timedelta(hours=24), '7d': timedelta(days=7), '30d': timedelta(days=30), '90d': timedelta(days=90)}
        if period in deltas:
            created_at__gte = (now - deltas[period]).isoformat()

    repo = PromotionRepository(db)
    offset = (page - 1) * page_size
    gte = parse_datetime(created_at__gte)
    lte = parse_datetime(created_at__lte)

    models = await repo.list_promotions(limit=page_size, offset=offset, status=status, store=store, category=category, created_at__gte=gte, created_at__lte=lte)
    total = await repo.count_promotions(status=status, store=store, category=category, created_at__gte=gte, created_at__lte=lte)
    total_pages = (total + page_size - 1) // page_size

    result = PaginatedResult(models, total, page, page_size, total_pages)
    template = Template(PROMOCOES_PARTIAL)
    return HTMLResponse(content=template.render(promotions=result, format_date=format_date))


@router.get("/partial/fontes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_fontes(
    page: int = 1, page_size: int = 20,
    active_only: bool = False,
    db=Depends(get_db)
):
    repo = SourceRepository(db)
    offset = (page - 1) * page_size
    models = await repo.list_sources(active_only=active_only, limit=page_size, offset=offset)
    total = await repo.count_sources(active_only=active_only)
    total_pages = (total + page_size - 1) // page_size

    result = PaginatedResult(models, total, page, page_size, total_pages)
    template = Template(FONTES_PARTIAL)
    return HTMLResponse(content=template.render(sources=result, format_date=format_date))


@router.get("/partial/publicacoes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_publicacoes(
    page: int = 1, page_size: int = 20,
    platform: str = None, status: str = None,
    db=Depends(get_db)
):
    repo = PublicationRepository(db)
    offset = (page - 1) * page_size
    models = await repo.list_publications(limit=page_size, offset=offset, platform=platform, status=status)
    total = await repo.count_publications(platform=platform, status=status)
    total_pages = (total + page_size - 1) // page_size

    result = PaginatedResult(models, total, page, page_size, total_pages)
    template = Template(PUBLICACOES_PARTIAL)
    return HTMLResponse(content=template.render(publications=result, format_date=format_date))