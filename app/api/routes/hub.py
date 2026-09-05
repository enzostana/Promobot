from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.routes.dashboard import verify_dashboard_credentials

router = APIRouter(tags=["Hub"])

AUTH = [Depends(verify_dashboard_credentials)]


@router.get("/", response_class=HTMLResponse, dependencies=AUTH)
async def hub_page():
    return HUB_HTML


HUB_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PromoBot</title>
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
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); overflow: hidden; transition: all 0.2s ease; }
        .card:hover { transform: translateY(-4px); border-color: var(--accent-strong); }
        .pill-status { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; background: var(--surface-2); border: 1.5px solid var(--border-strong); color: var(--text-secondary); }
        .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    </style>
</head>
<body class="p-6 flex flex-col items-center justify-center min-h-screen">
    <div class="w-full max-w-2xl">
        <header class="text-center mb-8">
            <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 shadow-lg shadow-blue-500/20 mb-4">
                <svg class="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                </svg>
            </div>
            <h1 class="text-3xl font-extrabold" style="color:var(--text-primary);">PromoBot</h1>
            <p class="text-sm font-medium mt-1" style="color:var(--text-muted);">Centro de controle</p>
        </header>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-8">
            <a href="/dashboard" class="card p-6 block">
                <h2 class="text-lg font-bold mb-1" style="color:var(--text-primary);">Dashboard</h2>
                <p class="text-sm" style="color:var(--text-muted);">Promoções, fontes e publicações em tempo real.</p>
            </a>
            <a href="/painel" class="card p-6 block">
                <h2 class="text-lg font-bold mb-1" style="color:var(--text-primary);">Painel</h2>
                <p class="text-sm" style="color:var(--text-muted);">Controle do bot: tags, filtros, destino e ações.</p>
            </a>
        </div>

        <div class="card">
            <div class="p-4 flex flex-wrap items-center justify-between gap-3">
                <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--text-muted);">Status do worker</span>
                <div class="flex flex-wrap items-center gap-3">
                    <span id="hub-pill" class="pill-status"><span class="dot" style="background:var(--text-faint);"></span>carregando…</span>
                    <span class="text-xs" style="color:var(--text-faint);" id="hub-meta">—</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function loadStatus() {
            try {
                const r = await fetch('/painel/values');
                if (r.status === 401) { return; }
                const data = await r.json();
                const pill = document.getElementById('hub-pill');
                const meta = document.getElementById('hub-meta');
                if (data.paused) {
                    pill.innerHTML = '<span class="dot" style="background:var(--red);"></span>pausado';
                } else if (data.worker.status === 'healthy') {
                    pill.innerHTML = '<span class="dot" style="background:var(--green);"></span>ativo';
                } else {
                    pill.innerHTML = '<span class="dot" style="background:var(--amber);"></span>' + (data.worker.status || 'desconhecido');
                }
                const q = data.worker.queue_length ?? '—';
                const last = data.worker.last_processed_seconds_ago;
                meta.textContent = 'fila: ' + q + ' · última msg: ' + (last == null ? '—' : last + 's atrás');
            } catch (e) { console.error(e); }
        }
        loadStatus();
        setInterval(loadStatus, 15000);
    </script>
</body>
</html>
'''