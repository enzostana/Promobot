from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from app.config.settings import get_settings

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


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>PromoBot Dashboard</title>
    <style>
        body {font-family: Arial, sans-serif; margin: 20px;}
        h1 {color:#333;}
        .filters {margin-bottom: 20px;}
        .filters label {margin-right: 10px;}
        table {width:100%; border-collapse: collapse; margin-bottom: 30px;}
        th, td {border:1px solid #ddd; padding:8px; text-align:left; font-size:14px;}
        th {background:#f4f4f4;}
        .status-published {color:green;}
        .status-filtered_out {color:orange;}
        .status-duplicate {color:gray;}
        .status-error {color:red;}
        .error-msg {color:red; font-size:12px;}
    </style>
</head>
<body>
    <h1>PromoBot Dashboard</h1>

    <div class="filters">
        <label>Status:
            <select id="filterStatus">
                <option value="">Todos</option>
                <option value="published">Publicado</option>
                <option value="filtered_out">Filtrado</option>
                <option value="duplicate">Duplicado</option>
                <option value="error">Erro</option>
            </select>
        </label>
        <label>Loja:
            <input type="text" id="filterStore" placeholder="ex: amazon">
        </label>
        <button onclick="loadData()">Aplicar Filtros</button>
    </div>

    <h2>Promoções</h2>
    <table id="promoTable">
        <thead>
            <tr>
                <th>ID</th><th>Produto</th><th>Loja</th><th>Preço Original</th><th>Preço Promo</th><th>Desconto %</th><th>Status</th><th>Criado em</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>

    <h2>Fontes</h2>
    <table id="sourceTable">
        <thead>
            <tr><th>ID</th><th>Plataforma</th><th>Chat ID</th><th>Nome</th><th>Ativo</th><th>Criado em</th></tr>
        </thead>
        <tbody></tbody>
    </table>

    <h2>Publicações</h2>
    <table id="pubTable">
        <thead>
            <tr><th>ID</th><th>Promo ID</th><th>Plataforma</th><th>Chat Alvo</th><th>Status</th><th>Erro</th><th>Publicado em</th></tr>
        </thead>
        <tbody></tbody>
    </table>

<script>
async function fetchJSON(url) {
    const resp = await fetch(url, {credentials: 'include'});
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

function renderPromotions(data) {
    const tbody = document.querySelector('#promoTable tbody');
    tbody.innerHTML = '';
    data.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${p.id}</td>
            <td>${p.product_name}</td>
            <td>${p.store || ''}</td>
            <td>${p.original_price ?? ''}</td>
            <td>${p.sale_price ?? ''}</td>
            <td>${p.discount_percentage ?? ''}</td>
            <td class="status-${p.status}">${p.status}</td>
            <td>${p.created_at}</td>`;
        tbody.appendChild(tr);
    });
}

function renderSources(data) {
    const tbody = document.querySelector('#sourceTable tbody');
    tbody.innerHTML = '';
    data.forEach(s => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${s.id}</td><td>${s.platform}</td><td>${s.chat_id}</td><td>${s.name || ''}</td><td>${s.is_active ? 'Sim' : 'Não'}</td><td>${s.created_at}</td>`;
        tbody.appendChild(tr);
    });
}

function renderPublications(data) {
    const tbody = document.querySelector('#pubTable tbody');
    tbody.innerHTML = '';
    data.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${p.id}</td><td>${p.promotion_id}</td><td>${p.platform}</td><td>${p.target_chat_id}</td>
            <td class="status-${p.status}">${p.status}</td>
            <td class="error-msg">${p.error_message || ''}</td>
            <td>${p.published_at}</td>`;
        tbody.appendChild(tr);
    });
}

async function loadData() {
    const status = document.getElementById('filterStatus').value;
    const store = document.getElementById('filterStore').value;
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (store) params.append('store', store);
    const q = params.toString();
    try {
        const [promos, sources, pubs] = await Promise.all([
            fetchJSON(`/promotions${q ? '?' + q : ''}`),
            fetchJSON('/sources'),
            fetchJSON('/publications')
        ]);
        renderPromotions(promos);
        renderSources(sources);
        renderPublications(pubs);
    } catch (e) {
        alert('Erro ao carregar dados: ' + e);
    }
}

// initial load
loadData();
</script>
</body>
</html>
"""

@router.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_dashboard_credentials)])
async def dashboard_home():
    return HTMLResponse(content=DASHBOARD_HTML)