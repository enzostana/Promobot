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
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        brand: { 500: '#2563eb', 600: '#1d4ed8', 700: '#1e40af' },
                        status: {
                            published: '#16a34a',
                            filtered_out: '#f59e0b',
                            duplicate: '#6b7280',
                            error: '#dc2626',
                            pending: '#3b82f6'
                        }
                    },
                    fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] }
                }
            }
        }
    </script>
    <style>
        .chip { @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-all duration-150 cursor-pointer select-none; }
        .chip-default { @apply bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700; }
        .chip-active { @apply bg-brand-500 text-white shadow-sm; }
        .chip-active-published { @apply bg-status-published text-white shadow-sm; }
        .chip-active-filtered_out { @apply bg-status-filtered_out text-white shadow-sm; }
        .chip-active-duplicate { @apply bg-status-duplicate text-white shadow-sm; }
        .chip-active-error { @apply bg-status-error text-white shadow-sm; }
        .chip-active-pending { @apply bg-status-pending text-white shadow-sm; }
        .table-container { @apply overflow-x-auto; }
        table { @apply w-full min-w-max; }
        th { @apply px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700; }
        td { @apply px-4 py-3 text-sm text-gray-900 dark:text-gray-100 border-b border-gray-100 dark:border-gray-800; }
        tbody tr { @apply hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors; }
        .badge { @apply inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium; }
        .skeleton { @apply animate-pulse bg-gray-200 dark:bg-gray-700 rounded; }
        .empty-state { @apply flex flex-col items-center justify-center py-16 text-center; }
        .empty-state svg { @apply w-16 h-16 text-gray-300 dark:text-gray-600 mb-4; }
        .empty-state p { @apply text-gray-500 dark:text-gray-400 text-sm; }
        .tab { @apply px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors; }
        .tab-active { @apply bg-white dark:bg-gray-900 text-brand-600 dark:text-brand-400 border-b-2 border-brand-500; }
        .tab-inactive { @apply text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200; }
        .htmx-indicator { @apply opacity-0 transition-opacity; }
        .htmx-request .htmx-indicator { @apply opacity-100; }
        .htmx-request.htmx-indicator { @apply opacity-100; }
    </style>
</head>
<body class="bg-gray-50 dark:bg-gray-950 min-h-screen font-sans">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <header class="mb-8">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">PromoBot Dashboard</h1>
                    <p class="text-gray-500 dark:text-gray-400 mt-1">Monitoramento e gestão de promoções</p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
                        <span class="w-2 h-2 rounded-full bg-green-500"></span>
                        Sistema Online
                    </span>
                </div>
            </div>
        </header>

        <section class="mb-6" hx-get="/dashboard/filters/all" hx-trigger="load" hx-target="#filter-chips" hx-swap="innerHTML">
            <div id="filter-chips" class="flex flex-wrap gap-3" role="group" aria-label="Filtros rápidos">
                <div class="chip chip-default" style="pointer-events:none;opacity:0.5">Carregando filtros...</div>
            </div>
        </section>

        <div class="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-800 overflow-hidden">
            <div class="border-b border-gray-200 dark:border-gray-800">
                <nav class="flex gap-1 px-2" role="tablist" aria-label="Seções do dashboard">
                    <button id="tab-promocoes" class="tab tab-active" role="tab" aria-selected="true" aria-controls="panel-promocoes"
                        hx-get="/dashboard/partial/promocoes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML"
                        hx-indicator="#loading-promocoes">Promoções</button>
                    <button id="tab-fontes" class="tab tab-inactive" role="tab" aria-selected="false" aria-controls="panel-fontes"
                        hx-get="/dashboard/partial/fontes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML"
                        hx-indicator="#loading-fontes">Fontes</button>
                    <button id="tab-publicacoes" class="tab tab-inactive" role="tab" aria-selected="false" aria-controls="panel-publicacoes"
                        hx-get="/dashboard/partial/publicacoes" hx-trigger="click" hx-target="#table-container" hx-swap="innerHTML"
                        hx-indicator="#loading-publicacoes">Publicações</button>
                </nav>
            </div>

            <div id="table-container" class="p-4">
                <div class="htmx-indicator flex justify-center py-12" id="loading-promocoes">
                    <div class="flex flex-col items-center gap-3">
                        <svg class="animate-spin h-8 w-8 text-brand-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                        <span class="text-gray-500 dark:text-gray-400 text-sm">Carregando promoções...</span>
                    </div>
                </div>
            </div>
        </div>

        <footer class="mt-6 text-center text-xs text-gray-400 dark:text-gray-500">
            PromoBot v1.0.0 &middot; <a href="/docs" class="underline hover:text-brand-500" target="_blank">Documentação da API</a>
        </footer>
    </div>

    <script>
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            if (evt.detail.target.id === 'table-container') {
                updateActiveTab(evt.detail.target.dataset.tab);
            }
        });

        function updateActiveTab(activeTab) {
            document.querySelectorAll('[role="tab"]').forEach(btn => {
                const isActive = btn.id === 'tab-' + activeTab;
                btn.classList.toggle('tab-active', isActive);
                btn.classList.toggle('tab-inactive', !isActive);
                btn.setAttribute('aria-selected', isActive);
            });
        }

        document.body.addEventListener('htmx:beforeRequest', function(evt) {
            if (evt.detail.target.closest('.chip')) {
                evt.detail.target.closest('.chip').classList.add('htmx-request');
            }
        });

        document.body.addEventListener('htmx:afterRequest', function(evt) {
            if (evt.detail.target.closest('.chip')) {
                evt.detail.target.closest('.chip').classList.remove('htmx-request');
            }
        });
    </script>
</body>
</html>'''

DASHBOARD_FILTERS_HTML = '''<div class="flex flex-wrap gap-3" role="group" aria-label="Filtros rápidos" id="filter-chips">
    <div class="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
        <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Status</span>
        <span class="w-px h-4 bg-gray-300 dark:bg-gray-600"></span>
    </div>
    {% for s in statuses %}
    <button class="chip chip-default" data-filter="status" data-value="{{ s }}"
        hx-get="/dashboard/partial/promocoes?status={{ s }}" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>
        {{ s.replace('_', ' ').title() }}
    </button>
    {% endfor %}

    <div class="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
        <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Loja</span>
        <span class="w-px h-4 bg-gray-300 dark:bg-gray-600"></span>
    </div>
    {% for store in stores %}
    <button class="chip chip-default" data-filter="store" data-value="{{ store }}"
        hx-get="/dashboard/partial/promocoes?store={{ store }}" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>
        {{ store.title() }}
    </button>
    {% endfor %}

    <div class="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
        <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Categoria</span>
        <span class="w-px h-4 bg-gray-300 dark:bg-gray-600"></span>
    </div>
    {% for cat in categories %}
    <button class="chip chip-default" data-filter="category" data-value="{{ cat }}"
        hx-get="/dashboard/partial/promocoes?category={{ cat }}" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>
        {{ cat.replace('_', ' ').title() }}
    </button>
    {% endfor %}

    <div class="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
        <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Período</span>
        <span class="w-px h-4 bg-gray-300 dark:bg-gray-600"></span>
    </div>
    <button class="chip chip-default" data-filter="period" data-value="24h"
        hx-get="/dashboard/partial/promocoes?period=24h" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>24h</button>
    <button class="chip chip-default" data-filter="period" data-value="7d"
        hx-get="/dashboard/partial/promocoes?period=7d" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>7 dias</button>
    <button class="chip chip-default" data-filter="period" data-value="30d"
        hx-get="/dashboard/partial/promocoes?period=30d" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>30 dias</button>
    <button class="chip chip-default" data-filter="period" data-value="90d"
        hx-get="/dashboard/partial/promocoes?period=90d" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>90 dias</button>

    <button class="chip chip-default ml-auto" 
        hx-get="/dashboard/partial/promocoes" hx-target="#table-container" hx-swap="innerHTML"
        hx-indicator="#loading-promocoes" hx-vals='js:{page: 1}'>
        Limpar tudo
    </button>
</div>'''

PROMOCOES_PARTIAL = '''<div data-tab="promocoes">
    <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Promoções</h2>
        <div class="htmx-indicator flex items-center gap-2 text-sm text-gray-500" id="loading-promocoes">
            <svg class="animate-spin h-4 w-4 text-brand-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span>Carregando...</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Produto</th>
                    <th>Loja</th>
                    <th>Preço Original</th>
                    <th>Preço Promo</th>
                    <th>Desconto</th>
                    <th>Categoria</th>
                    <th>Status</th>
                    <th>Criado em</th>
                </tr>
            </thead>
            <tbody id="promo-tbody">
                {% if promotions.items %}
                    {% for p in promotions.items %}
                    <tr>
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ p.id }}</td>
                        <td class="max-w-xs truncate" title="{{ p.product_name }}">{{ p.product_name }}</td>
                        <td>{{ p.store or '<span class="text-gray-400">—</span>' | safe }}</td>
                        <td>{{ 'R$ ' + ("%.2f"|format(p.original_price)) if p.original_price is not none else '—' }}</td>
                        <td class="font-semibold text-brand-600 dark:text-brand-400">{{ 'R$ ' + ("%.2f"|format(p.sale_price)) if p.sale_price is not none else '—' }}</td>
                        <td>{{ ("%.1f%%"|format(p.discount_percentage)) if p.discount_percentage is not none else '—' }}</td>
                        <td>{{ p.category or '<span class="text-gray-400">—</span>' | safe }}</td>
                        <td>
                            <span class="badge" style="background-color: {{ status_color(p.status) }}20; color: {{ status_color(p.status) }};">{{ p.status.replace('_', ' ').title() }}</span>
                        </td>
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ format_date(p.created_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="9" class="py-12">
                            <div class="empty-state">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                                <p>Nenhuma promoção encontrada</p>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    {% if promotions.total_pages > 1 %}
    <div class="flex items-center justify-between mt-4 pt-4 border-t border-gray-200 dark:border-gray-800">
        <p class="text-sm text-gray-500 dark:text-gray-400">
            Página {{ promotions.page }} de {{ promotions.total_pages }} — {{ promotions.total }} promoções
        </p>
        <nav class="flex gap-1" aria-label="Paginação">
            {% if promotions.page > 1 %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/promocoes?page={{ promotions.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Anterior
            </button>
            {% endif %}
            {% if promotions.page < promotions.total_pages %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/promocoes?page={{ promotions.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Próxima
            </button>
            {% endif %}
        </nav>
    </div>
    {% endif %}
</div>'''

FONTES_PARTIAL = '''<div data-tab="fontes">
    <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Fontes</h2>
        <div class="htmx-indicator flex items-center gap-2 text-sm text-gray-500" id="loading-fontes">
            <svg class="animate-spin h-4 w-4 text-brand-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span>Carregando...</span>
        </div>
    </div>

    <div class="table-container">
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
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ s.id }}</td>
                        <td><span class="badge bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400">{{ s.platform }}</span></td>
                        <td class="font-mono text-sm">{{ s.chat_id }}</td>
                        <td>{{ s.name or '<span class="text-gray-400">—</span>' | safe }}</td>
                        <td>
                            {% if s.is_active %}
                            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
                                <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>Ativa
                            </span>
                            {% else %}
                            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                                <span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>Inativa
                            </span>
                            {% endif %}
                        </td>
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ format_date(s.created_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="6" class="py-12">
                            <div class="empty-state">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg>
                                <p>Nenhuma fonte configurada</p>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    {% if sources.total_pages > 1 %}
    <div class="flex items-center justify-between mt-4 pt-4 border-t border-gray-200 dark:border-gray-800">
        <p class="text-sm text-gray-500 dark:text-gray-400">
            Página {{ sources.page }} de {{ sources.total_pages }} — {{ sources.total }} fontes
        </p>
        <nav class="flex gap-1" aria-label="Paginação">
            {% if sources.page > 1 %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/fontes?page={{ sources.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Anterior
            </button>
            {% endif %}
            {% if sources.page < sources.total_pages %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/fontes?page={{ sources.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Próxima
            </button>
            {% endif %}
        </nav>
    </div>
    {% endif %}
</div>'''

PUBLICACOES_PARTIAL = '''<div data-tab="publicacoes">
    <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Publicações</h2>
        <div class="htmx-indicator flex items-center gap-2 text-sm text-gray-500" id="loading-publicacoes">
            <svg class="animate-spin h-4 w-4 text-brand-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span>Carregando...</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Promo ID</th>
                    <th>Plataforma</th>
                    <th>Chat Alvo</th>
                    <th>Status</th>
                    <th>Erro</th>
                    <th>Publicado em</th>
                </tr>
            </thead>
            <tbody>
                {% if publications.items %}
                    {% for p in publications.items %}
                    <tr>
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ p.id }}</td>
                        <td class="font-mono">{{ p.promotion_id }}</td>
                        <td><span class="badge bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400">{{ p.platform }}</span></td>
                        <td class="font-mono text-sm">{{ p.target_chat_id }}</td>
                        <td>
                            <span class="badge" style="background-color: {{ pub_status_color(p.status) }}20; color: {{ pub_status_color(p.status) }};">{{ p.status.replace('_', ' ').title() }}</span>
                        </td>
                        <td class="max-w-xs truncate text-red-600 dark:text-red-400">{{ p.error_message or '<span class="text-gray-400">—</span>' | safe }}</td>
                        <td class="font-mono text-gray-500 dark:text-gray-400">{{ format_date(p.published_at) }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="7" class="py-12">
                            <div class="empty-state">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
                                <p>Nenhuma publicação realizada</p>
                            </div>
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    {% if publications.total_pages > 1 %}
    <div class="flex items-center justify-between mt-4 pt-4 border-t border-gray-200 dark:border-gray-800">
        <p class="text-sm text-gray-500 dark:text-gray-400">
            Página {{ publications.page }} de {{ publications.total_pages }} — {{ publications.total }} publicações
        </p>
        <nav class="flex gap-1" aria-label="Paginação">
            {% if publications.page > 1 %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/publicacoes?page={{ publications.page - 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Anterior
            </button>
            {% endif %}
            {% if publications.page < publications.total_pages %}
            <button class="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                hx-get="/dashboard/partial/publicacoes?page={{ publications.page + 1 }}" hx-target="#table-container" hx-swap="innerHTML">
                Próxima
            </button>
            {% endif %}
        </nav>
    </div>
    {% endif %}
</div>'''

STATUS_COLORS = {
    'published': '#16a34a',
    'filtered_out': '#f59e0b',
    'duplicate': '#6b7280',
    'error': '#dc2626',
    'pending': '#3b82f6'
}

PUB_STATUS_COLORS = {
    'published': '#16a34a',
    'failed': '#dc2626',
    'error': '#dc2626',
    'pending': '#3b82f6'
}


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, '#6b7280')


def pub_status_color(status: str) -> str:
    return PUB_STATUS_COLORS.get(status, '#6b7280')


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
        "SELECT DISTINCT store FROM promotions WHERE store IS NOT NULL ORDER BY store"
    )
    stores = [row[0] for row in stores_result.fetchall() if row[0]]

    statuses_result = await db.execute(
        "SELECT DISTINCT status FROM promotions ORDER BY status"
    )
    statuses = [row[0] for row in statuses_result.fetchall()]

    categories_result = await db.execute(
        "SELECT DISTINCT category FROM promotions WHERE category IS NOT NULL ORDER BY category"
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


def parse_datetime(val: str | None):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace('Z', '+00:00'))
    except:
        return None


@router.get("/partial/promocoes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_promocoes(
    page: int = 1,
    page_size: int = 20,
    status: str = None,
    store: str = None,
    category: str = None,
    period: str = None,
    created_at__gte: str = None,
    created_at__lte: str = None,
    db=Depends(get_db)
):
    if period:
        now = datetime.now(timezone.utc)
        if period == '24h':
            created_at__gte = (now - timedelta(hours=24)).isoformat()
        elif period == '7d':
            created_at__gte = (now - timedelta(days=7)).isoformat()
        elif period == '30d':
            created_at__gte = (now - timedelta(days=30)).isoformat()
        elif period == '90d':
            created_at__gte = (now - timedelta(days=90)).isoformat()

    repo = PromotionRepository(db)
    offset = (page - 1) * page_size

    models = await repo.list_promotions(
        limit=page_size,
        offset=offset,
        status=status,
        store=store,
        category=category,
        created_at__gte=parse_datetime(created_at__gte),
        created_at__lte=parse_datetime(created_at__lte)
    )

    total = await repo.count_promotions(
        status=status,
        store=store,
        category=category,
        created_at__gte=parse_datetime(created_at__gte),
        created_at__lte=parse_datetime(created_at__lte)
    )

    total_pages = (total + page_size - 1) // page_size

    result = PaginatedResult(models, total, page, page_size, total_pages)

    template = Template(PROMOCOES_PARTIAL)
    return HTMLResponse(content=template.render(
        promotions=result,
        status_color=status_color,
        format_date=format_date
    ))


@router.get("/partial/fontes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_fontes(
    page: int = 1,
    page_size: int = 20,
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
    return HTMLResponse(content=template.render(
        sources=result,
        format_date=format_date
    ))


@router.get("/partial/publicacoes", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def partial_publicacoes(
    page: int = 1,
    page_size: int = 20,
    platform: str = None,
    status: str = None,
    db=Depends(get_db)
):
    repo = PublicationRepository(db)
    offset = (page - 1) * page_size

    models = await repo.list_publications(limit=page_size, offset=offset, platform=platform, status=status)
    total = await repo.count_publications(platform=platform, status=status)

    total_pages = (total + page_size - 1) // page_size

    result = PaginatedResult(models, total, page, page_size, total_pages)

    template = Template(PUBLICACOES_PARTIAL)
    return HTMLResponse(content=template.render(
        publications=result,
        pub_status_color=pub_status_color,
        format_date=format_date
    ))