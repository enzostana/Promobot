from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.routes.dashboard import verify_dashboard_credentials

router = APIRouter(tags=["Hub"])

AUTH = [Depends(verify_dashboard_credentials)]


@router.get("/hub", response_class=HTMLResponse, dependencies=AUTH)
async def hub_page():
    return HUB_HTML


HUB_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PromoBot — Controle</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #f7f8fa; --surface: #ffffff; --border: #e6e8ee; --text: #111318;
            --text-2: #4b5162; --muted: #8b90a0; --accent: #e2350d; --accent-2: #ff7a1a;
            --green: #14823c; --red: #d92d20; --amber: #b54708;
            --shadow: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.08);
        }
        html { color-scheme: light; }
        body {
            font-family: 'Inter', system-ui, sans-serif;
            background: var(--bg); min-height: 100vh; color: var(--text-2);
            margin: 0; display: flex; flex-direction: column; align-items: center;
            justify-content: center; padding: 24px; box-sizing: border-box;
        }
        .wrap { width: 100%; max-width: 720px; }
        header { text-align: center; margin-bottom: 28px; }
        .logo-badge {
            width: 56px; height: 56px; border-radius: 16px; margin: 0 auto 12px;
            background: linear-gradient(135deg, var(--accent), var(--accent-2));
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 8px 20px rgba(226,53,13,.25);
        }
        .logo-badge svg { width: 28px; height: 28px; color: #fff; }
        h1 { margin: 0; font-size: 1.75rem; font-weight: 800; color: var(--text); letter-spacing: -.4px; }
        header p { margin: 4px 0 0; font-size: .9rem; color: var(--muted); }
        .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 14px; margin-bottom: 20px; }
        .card {
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 16px; padding: 20px; box-shadow: var(--shadow);
            color: inherit; text-decoration: none; transition: transform .15s ease, border-color .15s ease;
        }
        .card:hover { transform: translateY(-3px); border-color: var(--accent); }
        .card h2 { margin: 0 0 4px; font-size: 1.05rem; font-weight: 700; color: var(--text); }
        .card p { margin: 0; font-size: .83rem; color: var(--muted); line-height: 1.45; }
        .status {
            background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
            padding: 14px 16px; display: flex; flex-wrap: wrap; align-items: center;
            justify-content: space-between; gap: 10px; box-shadow: var(--shadow);
        }
        .status-label { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
        .status-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
        .pill-status {
            display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px;
            border-radius: 999px; font-size: .78rem; font-weight: 700;
            background: #f0f2f7; border: 1.5px solid var(--border); color: var(--text-2);
        }
        .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
        .status-meta small { color: var(--muted); font-size: .78rem; }
        .back { display: block; text-align: center; margin-top: 18px; font-size: .85rem; font-weight: 600; color: var(--muted); text-decoration: none; }
        .back:hover { color: var(--accent); }
        hr.sep { border: 0; border-top: 1px solid var(--border); margin: 22px 0 18px; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <div class="logo-badge">
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                </svg>
            </div>
            <h1>PromoBot</h1>
            <p>Centro de controle</p>
        </header>

        <div class="cards">
            <a href="/dashboard" class="card">
                <h2>Dashboard</h2>
                <p>Promoções, fontes e publicações em tempo real.</p>
            </a>
            <a href="/painel" class="card">
                <h2>Painel</h2>
                <p>Controle do bot: tags, filtros, destino e ações.</p>
            </a>
            <a href="/" class="card">
                <h2>Ver site</h2>
                <p>Página pública de ofertas — Rufino Promo.</p>
            </a>
        </div>

        <div class="status">
            <span class="status-label">Status do worker</span>
            <div class="status-meta">
                <span id="hub-pill" class="pill-status"><span class="dot" style="background:var(--muted);"></span>carregando…</span>
                <small id="hub-meta">—</small>
            </div>
        </div>

        <hr class="sep">
        <a class="back" href="/">← Voltar para o site</a>
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