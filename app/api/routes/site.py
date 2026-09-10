import base64
import hashlib
import html as _html
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes.dashboard import verify_dashboard_credentials
from app.config.settings import Settings, get_settings
from app.core.runtime_settings import resolve_values, write_secret_file
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.setting_repo import SettingRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Site"])

AUTH = [Depends(verify_dashboard_credentials)]

PAGE_SIZE = 24
EXCLUDE_SOURCE = "painel"
MEL_API_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
MEL_AUTH_URL = "https://auth.mercadolivre.com.br/authorization"


def _fmt_brl(value) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v.is_integer():
        text = f"{int(v):,}".replace(",", ".")
    else:
        text = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def _fmt_pct(value) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v == int(v):
        return f"{int(v)}%"
    return f"{v:.1f}%"


def _fmt_date(value) -> str:
    if not value:
        return ""
    try:
        return value.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _site_image_url(url: Optional[str]) -> str:
    if not url:
        return ""
    s = url.strip()
    if s.startswith("media_cache/"):
        return "/media/" + s.split("/", 1)[1]
    if s.startswith("/app/media_cache/"):
        return "/media/" + s.split("/", 3)[3]
    if s.startswith(("http://", "https://", "//")):
        return s
    return ""


def _display_name(value: Optional[str]) -> str:
    if not value:
        return "Loja"
    return value.replace("_", " ").replace("-", " ").title()


def esc(value) -> str:
    return _html.escape(str(value or ""), quote=True)


def _meta_defaults(settings: Settings, request: Request) -> dict:
    return {
        "title": settings.SITE_TITLE or "Rufino Promo",
        "refresh": max(5, int(getattr(settings, "SITE_REFRESH_SECONDS", 20))),
    }


def _card_html(item: dict, page_link: bool = True) -> str:
    img = _site_image_url(item.get("image"))
    if img:
        img_html = (
            f'<div class="card-media"><img loading="lazy" src="{esc(img)}" '
            f'alt="{esc(item.get("product_name", ""))}" '
            'onerror="this.closest(\'.card-media\').classList.add(\'broken\')"></div>'
        )
    else:
        img_html = f'<div class="card-media no-img"><span class="img-fallback">{esc(_display_name(item.get("store"))[:1])}</span></div>'

    off = f'<span class="badge off">{esc(_fmt_pct(item.get("discount_percentage")))}OFF</span>' if item.get("discount_percentage") else ""
    price = ""
    if item.get("sale_price"):
        price = f'<div class="price"><span class="de">{esc(_fmt_brl(item.get("original_price")))}</span><strong>Por {esc(_fmt_brl(item.get("sale_price")))}</strong></div>'
    elif item.get("original_price"):
        price = f'<div class="price"><strong>Por {esc(_fmt_brl(item.get("original_price")))}</strong></div>'

    name = esc(item.get("product_name", "Oferta"))
    if len(str(item.get("product_name", ""))) > 120:
        name = esc(str(item["product_name"])[:117]) + "…"

    cat_pill = f'<span class="pill cat">{esc(_display_name(item.get("category")))}</span>' if item.get("category") else ""
    meta = (
        f'<div class="meta"><span class="pill store">{esc(_display_name(item.get("store")))}</span>'
        f'{cat_pill}'
        f'<span class="when">{esc(_fmt_date(item.get("published_at") or item.get("created_at")))}</span></div>'
    )

    href = f'/p/{esc(item.get("id"))}' if page_link else "#"
    return (
        f'<div class="promo-card"><div class="card-top">{off}<div class="card-media-wrap">{img_html}</div></div>'
        f'<div class="card-body"><h3 class="card-title"><a href="{href}">{name}</a></h3>{price}'
        f'{meta}<a class="btn-ver" href="{href}" rel="noopener">Ver oferta</a></div></div>'
    )


def _grid_html(items: List[dict]) -> str:
    if not items:
        return '<div class="empty">Nenhuma oferta publicada ainda — as promoções do canal aparecem aqui automaticamente.</div>'
    return '<div class="grid">' + "".join(_card_html(i) for i in _grid_items(items)) + "</div>"


def _grid_items(models) -> List[dict]:
    out = []
    for m in models:
        out.append({
            "id": m.id,
            "product_name": m.product_name,
            "original_price": float(m.original_price) if m.original_price is not None else None,
            "sale_price": float(m.sale_price) if m.sale_price is not None else None,
            "discount_percentage": float(m.discount_percentage) if m.discount_percentage is not None else None,
            "store": m.store,
            "category": m.category,
            "image": _site_image_url(m.image_url),
            "created_at": m.created_at,
            "published_at": m.published_at,
            "affiliate_url": m.affiliate_url,
        })
    return out


def _pagination_html(page: int, total_pages: int, url_builder) -> str:
    if total_pages <= 1:
        return ""
    pages = set()
    for p in range(max(1, page - 3), min(total_pages, page + 3) + 1):
        pages.add(p)
    pages = sorted(pages)
    links = []
    for p in pages:
        if p == page:
            links.append(f'<span class="page current">{p}</span>')
        else:
            links.append(f'<a class="page" href="{esc(url_builder(p))}">{p}</a>')
    prev = f'<a class="page" href="{esc(url_builder(page - 1))}">&laquo; anterior</a>' if page > 1 else ""
    nxt = f'<a class="page" href="{esc(url_builder(page + 1))}">próxima &raquo;</a>' if page < total_pages else ""
    return f'<div class="pagination">{prev}{"".join(links)}{nxt}</div>'


def _feed_url(params: dict, page: int) -> str:
    q = {k: v for k, v in params.items() if v}
    q["page"] = page
    return "/promocoes?" + urllib.parse.urlencode(q)


CATEGORY_ORDER = ["tecnologia", "eletrodomesticos", "casa", "academia", "moda"]


def _sorted_categories(categories: List[str]) -> List[str]:
    return sorted(categories, key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))


def _page_shell(title: str, settings: Settings, request: Request, content: str, meta: dict, active: str = "") -> str:
    refresh = meta["refresh"]
    store_options = meta.get("stores", [])
    cat_options = sorted(meta.get("categories", []), key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))

    store_chips = "".join(
        f'<a class="chip" href="/loja/{esc(s)}">{esc(_display_name(s))}</a>' for s in store_options[:10]
    )
    cat_chips = "".join(f'<a class="chip" href="/categoria/{esc(c)}">{esc(_display_name(c))}</a>' for c in cat_options)
    active_cls = lambda k: "active" if active == k else ""  # noqa: E731

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} — {esc(settings.SITE_TITLE)}</title>
<meta name="description" content="Ofertas do dia com desconto de verdade: produtos em promoção dos seus marketplaces favoritos.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#f7f8fa; --surface:#ffffff; --border:#e6e8ee; --text:#111318; --text-2:#4b5162;
  --muted:#8b90a0; --accent:#e2350d; --accent-2:#ff7a1a; --green:#14823c; --chip:#f0f2f7;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.08);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ color-scheme:light; }}
body {{ font-family:'Inter',system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.container {{ max-width:1180px; margin:0 auto; padding:0 16px; }}
header.top {{
  background:linear-gradient(180deg,#fff,#fff);
  border-bottom:1px solid var(--border); position:sticky; top:0; z-index:20;
}}
.top-inner {{ display:flex; align-items:center; gap:16px; height:64px; }}
.logo {{ font-size:1.35rem; font-weight:800; color:var(--text); letter-spacing:-.3px; }}
.logo span {{ color:var(--accent); }}
nav.main {{ display:flex; gap:4px; margin-left:8px; flex:1; }}
nav.main a {{ padding:8px 12px; border-radius:10px; font-weight:600; color:var(--text-2); font-size:.95rem; }}
nav.main a:hover {{ background:var(--chip); text-decoration:none; }}
nav.main a.active {{ color:var(--accent); background:var(--chip); }}
.search {{ display:inline-flex; align-items:center; gap:8px; background:var(--chip); border:1px solid var(--border); border-radius:12px; padding:6px 10px; }}
.search input {{ border:0; outline:0; background:transparent; font:inherit; width:220px; }}
.search button {{ border:0; background:transparent; cursor:pointer; font-weight:700; color:var(--accent); }}
.controle {{ background:var(--accent); color:#fff !important; padding:8px 14px; border-radius:10px; font-weight:700; font-size:.9rem; white-space:nowrap; }}
.controle:hover {{ opacity:.9; text-decoration:none; }}
.hero {{ padding:24px 0 14px; }}
.hero h1 {{ font-size:1.6rem; font-weight:800; letter-spacing:-.5px; }}
.hero p {{ color:var(--text-2); margin-top:6px; max-width:640px; font-size:.95rem; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 4px; }}
.chips .chip {{ background:var(--surface); border:1px solid var(--border); color:var(--text-2); padding:5px 11px; border-radius:999px; font-size:.8rem; font-weight:600; }}
.chips .chip:hover {{ border-color:var(--accent); color:var(--accent); text-decoration:none; }}
.section-head {{ display:flex; align-items:baseline; justify-content:space-between; margin:18px 0 10px; }}
.section-head h2 {{ font-size:1.1rem; font-weight:800; }}
.section-head .more {{ color:var(--muted); font-weight:600; font-size:.85rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }}
.promo-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; overflow:hidden; box-shadow:var(--shadow); display:flex; flex-direction:column; transition:transform .15s ease,box-shadow .15s ease; }}
.promo-card:hover {{ transform:translateY(-2px); box-shadow:0 4px 12px rgba(16,24,40,.1); }}
.card-top {{ position:relative; }}
.card-media-wrap {{ aspect-ratio:1/1; background:var(--chip); display:flex; align-items:center; justify-content:center; }}
.card-media {{ width:100%; height:100%; }}
.card-media img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.card-media.broken {{ display:none; }}
.card-media.no-img {{ background:linear-gradient(135deg,var(--accent),var(--accent-2)); display:flex; align-items:center; justify-content:center; }}
.img-fallback {{ font-size:1.8rem; font-weight:800; color:#fff; }}
.badge.off {{ position:absolute; top:8px; right:8px; background:var(--accent); color:#fff; font-weight:800; font-size:.72rem; padding:3px 8px; border-radius:999px; }}
.card-body {{ padding:10px 12px 12px; display:flex; flex-direction:column; gap:6px; flex:1; }}
.card-title {{ font-size:.85rem; font-weight:600; line-height:1.35; min-height:2.3em; }}
.card-title a {{ color:var(--text); }}
.card-title a:hover {{ color:var(--accent); text-decoration:none; }}
.price {{ margin-top:auto; }}
.price .de {{ color:var(--muted); text-decoration:line-through; font-size:.78rem; display:block; }}
.price strong {{ font-size:1rem; font-weight:800; color:var(--text); }}
.meta {{ display:flex; flex-wrap:wrap; gap:5px; align-items:center; }}
.pill {{ font-size:.68rem; font-weight:700; padding:2px 7px; border-radius:999px; background:var(--chip); color:var(--text-2); }}
.pill.store {{ color:var(--green); background:#e8f5ee; }}
.pill.cat {{ color:var(--accent); background:#fff0ea; }}
.when {{ margin-left:auto; color:var(--muted); font-size:.7rem; }}
.btn-ver {{ text-align:center; background:var(--accent); color:#fff; font-weight:700; padding:7px; border-radius:9px; font-size:.85rem; }}
.btn-ver:hover {{ background:#c22e0a; text-decoration:none; }}
.empty {{ padding:40px; text-align:center; color:var(--muted); background:var(--surface); border:1px dashed var(--border); border-radius:16px; }}
.pagination {{ display:flex; flex-wrap:wrap; gap:6px; justify-content:center; margin:26px 0; }}
.page {{ padding:8px 12px; border-radius:10px; border:1px solid var(--border); background:var(--surface); font-weight:600; font-size:.9rem; color:var(--text-2); }}
.page.current {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:14px 0; }}
.toolbar .spacer {{ flex:1; }}
.toolbar .text {{ color:var(--muted); font-size:.85rem; }}
.detail {{ display:grid; grid-template-columns:1.05fr 1fr; gap:28px; margin:26px 0 40px; background:var(--surface); border:1px solid var(--border); border-radius:18px; padding:22px; box-shadow:var(--shadow); }}
.detail-media {{ aspect-ratio:4/3; background:var(--chip); border-radius:14px; overflow:hidden; }}
.detail-media img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.detail-media.broken {{ display:none; }}
.detail-media.no-img {{ display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,var(--accent),var(--accent-2)); }}
.detail-info h1 {{ font-size:1.5rem; font-weight:800; letter-spacing:-.4px; line-height:1.3; }}
.detail-prices {{ margin:16px 0; padding:14px; background:var(--bg); border-radius:12px; }}
.detail-prices .de {{ color:var(--muted); text-decoration:line-through; font-size:1rem; }}
.detail-prices .por {{ font-size:2rem; font-weight:800; }}
.detail-prices .off-tag {{ display:inline-block; background:var(--accent); color:#fff; font-weight:800; padding:3px 10px; border-radius:999px; font-size:.85rem; margin-left:8px; }}
.detail-cta {{ display:block; text-align:center; background:var(--accent); color:#fff; font-size:1.15rem; font-weight:800; padding:14px; border-radius:12px; }}
.detail-cta:hover {{ background:#c22e0a; color:#fff; text-decoration:none; }}
.detail-rows {{ margin-top:14px; font-size:.92rem; color:var(--text-2); }}
.detail-rows div {{ padding:7px 0; border-bottom:1px solid var(--border); display:flex; gap:8px; }}
.detail-rows b {{ color:var(--text); width:110px; flex-shrink:0; }}
.desc {{ margin-top:14px; white-space:pre-wrap; color:var(--text-2); font-size:.92rem; }}
footer {{ margin-top:44px; border-top:1px solid var(--border); padding:22px 0 34px; color:var(--muted); font-size:.85rem; }}
footer .foot-inner {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; }}
footer a {{ color:var(--text-2); }}
@media (max-width:760px) {{
  .top-inner {{ flex-wrap:wrap; height:auto; padding:10px 0; }}
  .search input {{ width:120px; }}
  .detail {{ grid-template-columns:1fr; }}
  .hero h1 {{ font-size:1.5rem; }}
}}
</style>
</head>
<body>
<header class="top"><div class="container top-inner">
  <a class="logo" href="/">{esc(settings.SITE_TITLE)}</a>
  <nav class="main">
    <a class="{active_cls("home")}" href="/">Início</a>
    <a class="{active_cls("promocoes")}" href="/promocoes">Promoções</a>
  </nav>
  <form class="search" action="/promocoes" method="get">
    <input type="search" name="q" placeholder="Buscar oferta…" value="{esc(request.query_params.get("q", ""))}" aria-label="Buscar">
    <button type="submit">Buscar</button>
  </form>
  <a class="controle" href="/hub">Controle</a>
</div></header>

<main class="container">
{content}
</main>

<footer><div class="container foot-inner">
  <span>&copy; {esc(datetime.now().year)} {esc(settings.SITE_TITLE)} — preços e disponibilidade sujeitos a alteração.</span>
  <span><a href="/hub">Controle (dashboard e painel)</a></span>
</div></footer>

<script>
  window.addEventListener('DOMContentLoaded', function() {{
    const sp = new URLSearchParams(window.location.search);
    if (sp.get('code') && sp.get('state') === 'promobot') {{
      window.location.href = '/mel/connect?' + sp.toString();
    }}
  }});
  const REFRESH_SECONDS = {refresh};
</script>
</body>
</html>"""


async def _read_meta(settings: Settings, db: AsyncSession) -> dict:
    repo = PromotionRepository(db)
    stores, categories = await repo.distinct_stores(), await repo.distinct_categories()
    return {"stores": stores, "categories": _sorted_categories(categories)}


@router.get("/", response_class=HTMLResponse)
async def site_home(request: Request, db: AsyncSession = Depends(get_db)):
    # MEL OAuth callback: the authorize URL returns here with ?code=...; exchange
    # the code server-side (PKCE-friendly) and show the result on /mel/connect.
    if request.query_params.get("code"):
        ok, error = await _exchange_oauth_code(request, request.query_params["code"], db)
        response = RedirectResponse(
            f"/mel/connect?{'connected=ok' if ok else 'exchange_error=' + urllib.parse.quote(error)}",
            status_code=302,
        )
        response.delete_cookie(_MEL_COOKIE_VERIFIER, path="/")
        return response

    settings = get_settings()
    repo = PromotionRepository(db)
    models = await repo.list_promotions(
        limit=PAGE_SIZE, status="published", exclude_source=EXCLUDE_SOURCE
    )
    meta = await _read_meta(settings, db) | _meta_defaults(settings, request)
    chips = "".join(
        f'<a class="chip" href="/promocoes?category={esc(c)}">{esc(_display_name(c))}</a>' for c in meta["categories"]
    )
    content = f"""
    <section class="hero">
      <h1>{esc(settings.SITE_TITLE)}: ofertas com desconto de verdade</h1>
      <p>Promoções recentes dos marketplaces, com o preço original e o real na mão. Clique, confira e economize.</p>
      <div class="chips">{chips}</div>
    </section>
    <div class="section-head"><h2>Últimas ofertas</h2><a class="more" href="/promocoes">Ver todas →</a></div>
    <div id="grid">{_grid_html([m for m in models])}</div>
    <p class="section-head"><span class="more" id="updated-at" style="color:var(--muted)"></span></p>
    """
    html = _page_shell(settings.SITE_TITLE, settings, request, content, meta, active="home")
    return HTMLResponse(_inject_grid_js(html, "/api/site/promotions?limit=24&order=recent"))


@router.get("/promocoes", response_class=HTMLResponse)
async def site_promocoes(
    request: Request,
    page: int = Query(1, ge=1),
    q: str = Query("", description="Busca por nome"),
    store: str = Query("", description="Loja"),
    category: str = Query("", description="Categoria"),
    order: str = Query("recent", pattern="^(recent|discount)$"),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    repo = PromotionRepository(db)
    params: dict = {}
    if q:
        params["q"] = q
    if store:
        params["store"] = store
    if category:
        params["category"] = category
    params["order"] = order

    models = await repo.list_promotions(
        limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, status="published",
        exclude_source=EXCLUDE_SOURCE, store=store or None, category=category or None,
        search=q or None, order_by=order,
    )
    total = await repo.count_promotions(
        status="published", exclude_source=EXCLUDE_SOURCE, store=store or None,
        category=category or None, search=q or None,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    meta = await _read_meta(settings, db) | _meta_defaults(settings, request)

    title = "Promoções"
    subtitle = ""
    if category:
        title = f"Categoria {_display_name(category)}"
    elif store:
        title = f"Loja {_display_name(store)}"
    if q:
        title = "Resultados: " + _display_name(q)

    toolbar = f"""
    <div class="toolbar">
      <span class="text">{total} oferta(s)</span>
      <span class="spacer"></span>
      <a class="chip" href="/promocoes?{urllib.parse.urlencode({**{k: v for k, v in params.items() if k != "order"}, "order": "discount"})}">Maior desconto</a>
      <a class="chip" href="/promocoes?{urllib.parse.urlencode({**{k: v for k, v in params.items() if k != "order"}, "order": "recent"})}">Mais recentes</a>
    </div>"""
    models2 = [m for m in models]
    content = f"""
    <div class="section-head"><h2>{esc(title)}</h2>{subtitle}</div>
    {toolbar}
    <div id="grid">{_grid_html(models2)}</div>
    {_pagination_html(page, total_pages, lambda p: _feed_url(params, p))}
    """
    html = _page_shell(title, settings, request, content, meta, active="promocoes")
    feed = "/api/site/promotions?page=" + str(page)
    for k in ("q", "store", "category"):
        v = locals().get(k)
        if v:
            feed += f"&{k}=" + urllib.parse.quote(str(v))
    feed += "&order=" + order
    return HTMLResponse(_inject_grid_js(html, feed))


@router.get("/p/{promotion_id}", response_class=HTMLResponse)
async def site_promotion_detail(
    promotion_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    settings = get_settings()
    repo = PromotionRepository(db)
    promo = await repo.get_by_id(promotion_id)
    if not promo or promo.status != "published" or promo.source == EXCLUDE_SOURCE:
        raise HTTPException(status_code=404, detail="Oferta não encontrada")

    item = _grid_items([promo])[0]
    image = item["image"]
    media_html = (
        f'<div class="detail-media"><img src="{esc(image)}" alt="{esc(promo.product_name)}" '
        f'onerror="this.parentElement.classList.add(\'no-img\'); this.style.display=\'none\'"></div>'
        if image else
        '<div class="detail-media no-img"><span class="img-fallback" style="font-size:3rem;">&nbsp;</span></div>'
    )
    prices = ""
    if item["sale_price"]:
        prices = (
            f'<div class="detail-prices"><span class="de">De {esc(_fmt_brl(item["original_price"]))}</span>'
            f'<div class="por">Por {esc(_fmt_brl(item["sale_price"]))}'
            f'<span class="off-tag">{esc(_fmt_pct(item["discount_percentage"]))} OFF</span></div></div>'
        )
    elif item["original_price"]:
        prices = f'<div class="detail-prices"><div class="por">Por {esc(_fmt_brl(item["original_price"]))}</div></div>'

    rows = f"""
      <div><b><i>Loja</i></b> {esc(_display_name(promo.store))}</div>
      <div><b><i>Categoria</i></b> {esc(_display_name(promo.category)) or "—"}</div>
      <div><b><i>Publicado</i></b> {esc(_fmt_date(promo.created_at))}</div>
    """
    desc = await _get_desc(promo)

    href = promo.affiliate_url or promo.original_url
    content = f"""
    <div class="detail">
      {media_html}
      <div class="detail-info">
        <h1>{esc(promo.product_name)}</h1>
        {prices}
        <a class="detail-cta" href="{esc(href)}" target="_blank" rel="noopener nofollow sponsored">VER OFERTA NA LOJA</a>
        <div class="detail-rows">{rows}</div>
        {desc}
      </div>
    </div>
    """
    meta = await _read_meta(settings, db) | _meta_defaults(settings, request)
    return HTMLResponse(_page_shell(promo.product_name, settings, request, content, meta, active="promocoes"))


async def _get_desc(promo) -> str:
    desc = (promo.description or "").strip()
    if not desc or len(desc) < 20:
        return ""
    return html_escape(desc)


def html_escape(text) -> str:
    return _html.escape(str(text or ""), quote=True)


@router.get("/loja/{store}", response_class=HTMLResponse)
async def site_loja(store: str, request: Request, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    return await _site_wrap("loja", store, request, page, db)


@router.get("/categoria/{category}", response_class=HTMLResponse)
async def site_categoria(category: str, request: Request, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    return await _site_wrap("categoria", category, request, page, db)


async def _site_wrap(kind: str, value: str, request: Request, page: int, db: AsyncSession):
    settings = get_settings()
    repo = PromotionRepository(db)
    params = {kind: value}
    models = await repo.list_promotions(
        limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, status="published",
        exclude_source=EXCLUDE_SOURCE, store=value if kind == "loja" else None,
        category=value if kind == "categoria" else None,
    )
    total = await repo.count_promotions(
        status="published", exclude_source=EXCLUDE_SOURCE,
        store=value if kind == "loja" else None, category=value if kind == "categoria" else None,
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    meta = await _read_meta(settings, db) | _meta_defaults(settings, request)
    title = _display_name(value)
    content = f"""
    <div class="section-head"><h2>{esc("Loja" if kind == "loja" else "Categoria")}: {esc(title)}</h2><span class="more">{total} oferta(s)</span></div>
    <div id="grid">{_grid_html(models)}</div>
    {_pagination_html(page, total_pages, lambda p: f"/{kind}/{urllib.parse.quote(value)}?page={p}")}
    """
    html = _page_shell(title, settings, request, content, meta, active="promocoes")
    feed = f"/api/site/promotions?{kind}={urllib.parse.quote(value)}&page={page}&order=recent"
    return HTMLResponse(_inject_grid_js(html, feed))


@router.get("/api/site/meta")
async def api_site_meta(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    meta = await _read_meta(settings, db)
    return {"categories": meta["categories"], "stores": meta["stores"], "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/api/site/promotions")
async def api_site_promotions(
    page: int = Query(1, ge=1),
    limit: int = Query(PAGE_SIZE, ge=1, le=48),
    q: str = Query(""),
    store: str = Query(""),
    category: str = Query(""),
    order: str = Query("recent", pattern="^(recent|discount)$"),
    db: AsyncSession = Depends(get_db),
):
    repo = PromotionRepository(db)
    models = await repo.list_promotions(
        limit=limit, offset=(page - 1) * limit, status="published", exclude_source=EXCLUDE_SOURCE,
        store=store or None, category=category or None, search=q or None, order_by=order,
    )
    total = await repo.count_promotions(
        status="published", exclude_source=EXCLUDE_SOURCE, store=store or None,
        category=category or None, search=q or None,
    )
    total_pages = max(1, (total + limit - 1) // limit)
    items = []
    for m in models:
        items.append({
            "id": m.id,
            "product_name": m.product_name,
            "original_price": float(m.original_price) if m.original_price is not None else None,
            "sale_price": float(m.sale_price) if m.sale_price is not None else None,
            "discount_percentage": float(m.discount_percentage) if m.discount_percentage is not None else None,
            "store": m.store,
            "category": m.category,
            "image": _site_image_url(m.image_url),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "published_at": m.published_at.isoformat() if m.published_at else None,
            "url": f"/p/{m.id}",
        })
    return {
        "items": items,
        "total": total,
        "page": min(page, total_pages),
        "total_pages": total_pages,
        "page_size": limit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


_GRID_JS_SCRIPT = r"""
function cardHTML(i) {
  const img = (i.image || '');
  let mw = '<div class="card-media no-img"><span class="img-fallback">' + (i.store || 'L')[0].toUpperCase() + '</span></div>';
  if (img) mw = '<div class="card-media"><img loading="lazy" src="' + img + '" alt="' + (i.product_name||'').replace(/"/g, '&quot;') + '" onerror="this.closest(\'.card-media\').classList.add(\'broken\'); this.style.display=\'none\'"></div>';
  let off = '';
  if (i.discount_percentage) off = '<span class="badge off">' + (Math.round(i.discount_percentage*10)/10) + '%OFF</span>';
  let price = '';
  if (i.sale_price) {
    price = '<div class="price"><span class="de">' + brl(i.original_price) + '</span><strong>Por ' + brl(i.sale_price) + '</strong></div>';
  } else if (i.original_price) {
    price = '<div class="price"><strong>Por ' + brl(i.original_price) + '</strong></div>';
  }
  const name = ((i.product_name||'').length > 120 ? (i.product_name).slice(0,117)+'…' : (i.product_name||''));
  return '<div class="promo-card"><div class="card-top">' + off + '<div class="card-media-wrap">' + mw + '</div></div>' +
    '<div class="card-body"><h3 class="card-title"><a href="' + i.url + '">' + name + '</a></h3>' + price +
    '<div class="meta"><span class="pill store">' + tt(i.store) + '</span>' + (i.category ? '<span class="pill cat">' + tt(i.category) + '</span>' : '') +
    '<span class="when">' + (i.published_at || i.created_at || '').slice(0,10) + '</span></div>' +
    '<a class="btn-ver" href="' + i.url + '" rel="noopener">Ver oferta</a></div></div>';
}
function tt(s){ s = s||''; return s.replace(/_/g,' ').replace(/-/g,' ').replace(/\b\w/g, c=>c.toUpperCase()); }
function brl(v){ if(v==null) return ''; v=Number(v);
  const t = Math.abs(v - Math.round(v)) < 1e-9 ? v.toLocaleString('pt-BR') : v.toLocaleString('pt-BR',{minimumFractionDigits:2, maximumFractionDigits:2});
  return 'R$ ' + t; }
function bindRefresh(url) {
  const grid = document.getElementById('grid');
  if (!grid) return;
  async function tick() {
    if (document.hidden) return;
    try {
      const r = await fetch(url + '&_=' + Date.now());
      const d = await r.json();
      if (!d.items) return;
      const first = grid.querySelector('.promo-card .card-title a');
      const curId = first ? Number(first.getAttribute('href').split('/').pop()) : null;
      const hasNew = d.items.some(it => it.id > (curId||0));
      const fresh = d.items.map(cardHTML).join('');
      if (fresh !== grid.innerHTML) {
        grid.innerHTML = fresh;
        const el = document.getElementById('updated-at');
        if (el) { el.textContent = 'atualizado ' + new Date().toLocaleTimeString('pt-BR') + (hasNew ? ' · novas ofertas!' : ''); el.style.color = hasNew ? 'var(--accent)' : 'var(--muted)'; }
      }
    } catch (e) { /* ignorado */ }
  }
  setInterval(tick, REFRESH_SECONDS * 1000);
  window.addEventListener('DOMContentLoaded', tick);
}
"""


def _inject_grid_js(page_html: str, feed_url: str) -> str:
    script = _GRID_JS_SCRIPT + "\nbindRefresh(" + json.dumps(feed_url) + ");"
    return page_html.replace("</body>", "<script>" + script + "</script></body>")


class MelAuthIn(BaseModel):
    code: str
    redirect_uri: str


_MEL_COOKIE_VERIFIER = "mel_pkce_verifier"


def _pkce_pair() -> "tuple[str, str]":
    """Returns (code_verifier, code_challenge) for MEL's PKCE OAuth."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _mel_pkce_verifier(state: str, request: Request) -> str:
    """Recovers the code_verifier from the OAuth state or the browser cookie."""
    if state.startswith("promobot."):
        candidate = state[len("promobot."):]
        if candidate:
            return candidate
    return request.cookies.get(_MEL_COOKIE_VERIFIER, "")


async def _exchange_oauth_code(request: Request, code: str, db: AsyncSession) -> "tuple[bool, str]":
    """Server-side exchange of the MEL authorization code (works with PKCE)."""
    settings = get_settings()
    repo = SettingRepository(db)
    overrides = await repo.get_all()
    resolved = resolve_values(settings, overrides)
    client_id = (resolved.get("mel_api_client_id") or {}).get("value")
    client_secret = (resolved.get("mel_api_client_secret") or {}).get("value")
    if not client_id or not client_secret:
        return False, "Client ID/Secret do app MEL não configurados."

    verifier = _mel_pkce_verifier(request.query_params.get("state", ""), request)
    data = {
        "grant_type": "authorization_code",
        "client_id": str(client_id),
        "client_secret": str(client_secret),
        "code": code,
        "redirect_uri": settings.MEL_OAUTH_REDIRECT_URI,
    }
    if verifier:
        data["code_verifier"] = verifier

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(MEL_API_TOKEN_URL, data=data)
    except Exception as e:
        logger.warning(f"[MEL-AUTH] falha de rede na troca de código: {e}")
        return False, f"Falha de rede ao trocar o código: {e}"

    if resp.status_code >= 400:
        logger.warning(f"[MEL-AUTH] troca de código falhou: {resp.text[:200]}")
        try:
            detail = resp.json().get("error_description") or resp.json().get("error")
        except Exception:
            detail = resp.text[:200]
        return False, str(detail)

    data_resp = resp.json()
    refresh_token = data_resp.get("refresh_token")
    if not refresh_token:
        return False, "O MEL não retornou refresh_token (escopo offline_access ausente)."

    try:
        await repo.upsert("mel_refresh_token", refresh_token)
        await db.commit()
    except Exception as e:
        logger.warning(f"[MEL-AUTH] falha ao persistir refresh token: {e}")
        return False, "Falha ao persistir o token."

    try:
        write_secret_file("mel_refresh_token", refresh_token)
    except Exception:
        pass
    logger.info("[MEL-AUTH] refresh_token MEL armazenado com sucesso.")
    return True, ""


@router.get("/mel/connect", response_class=HTMLResponse, dependencies=AUTH)
async def mel_connect_page(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    repo = SettingRepository(db)
    overrides = await repo.get_all()
    resolved = resolve_values(settings, overrides)
    entry = resolved.get("mel_api_client_id") or {}
    client_id = entry.get("value") or get_settings().MEL_API_CLIENT_ID

    authorize_url = ""
    set_pkce_cookie = False
    if client_id:
        verifier, challenge = _pkce_pair()
        set_pkce_cookie = True
        state = f"promobot.{verifier}"
        authorize_url = (
            f"{MEL_AUTH_URL}?response_type=code&client_id={urllib.parse.quote(str(client_id), safe='')}"
            f"&redirect_uri={urllib.parse.quote(settings.MEL_OAUTH_REDIRECT_URI, safe='')}"
            f"&state={urllib.parse.quote(state, safe='')}"
            "&scope=offline_access"
            f"&code_challenge={challenge}&code_challenge_method=S256"
        )

    has_code = bool(request.query_params.get("code"))
    has_error = request.query_params.get("error")
    error_msg = request.query_params.get("error_description")
    connected = request.query_params.get("connected")

    status = ""
    if connected == "ok":
        status = '<div class="msg msg-ok">Conta conectada! O caçador do Mercado Livre começa a varrer nos próximos ciclos.</div>'
    elif request.query_params.get("exchange_error"):
        status = f'<div class="msg msg-err">Falha ao conectar: {esc(request.query_params.get("exchange_error", ""))}</div>'
    elif has_code:
        status = """
        <div id="pulse" class="card">
          <p>Autorizando com o Mercado Livre… <span id="pulse-status">aguarde</span></p>
          <div id="result" style="display:none"></div>
        </div>
        <script>
          (async () => {
            const sp = new URLSearchParams(window.location.search);
            try {
              const r = await fetch('/api/site/mel/auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: sp.get('code'), redirect_uri: sp.get('redirect_uri') || '%RED%' })
              });
              const d = await r.json();
              const box = document.getElementById('result');
              box.style.display = 'block';
              document.getElementById('pulse-status').textContent = r.ok ? 'conectado!' : 'falhou';
              box.className = 'msg ' + (r.ok ? 'msg-ok' : 'msg-err');
              box.textContent = r.ok ? 'Conta conectada! O caçador do Mercado Livre começa a varrer nos próximos ciclos.' : 'Erro: ' + (d.detail || r.status);
            } catch (e) {
              const box = document.getElementById('result');
              box.style.display = 'block'; box.className = 'msg msg-err'; box.textContent = 'Falha de rede: ' + e;
            }
          })();
        </script>
        """
        status = status.replace("%RED%", settings.MEL_OAUTH_REDIRECT_URI)
    elif has_error:
        status = f'<div class="msg msg-err">Erro no Mercado Livre: {esc(error_msg or has_error)}</div>'
    else:
        status = ""

    button = ""
    if authorize_url:
        button = f'<a class="detail-cta" href="{esc(authorize_url)}" rel="noopener">Conectar conta Mercado Livre</a>'
    elif not has_code:
        status += '<div class="msg msg-err">Client ID do app MEL não configurado. Preencha em <a href="/painel">Painel → Caçador</a> primeiro.</div>'

    content = f"""
    <div class="section-head"><h2>Conectar com o Mercado Livre</h2></div>
    <div style="max-width:640px">
      <p style="color:var(--text-2);margin-bottom:14px">Para varrer ofertas da API do Mercado Livre, o app precisa de um token de acesso com "offline_access". Clique no botão abaixo, entre com sua conta do Mercado Livre e autorize a aplicação. Você será redirecionado de volta para cá automaticamente.</p>
      {button}
      {status}
    </div>
    """
    meta = await _read_meta(get_settings(), db) | _meta_defaults(settings, request)
    response = HTMLResponse(_page_shell("Conectar Mercado Livre", settings, request, content, meta))
    if set_pkce_cookie:
        response.set_cookie(
            _MEL_COOKIE_VERIFIER, verifier,
            max_age=600, httponly=True, samesite="lax", path="/",
        )
    return response


@router.post("/api/site/mel/auth", dependencies=AUTH)
async def api_site_mel_auth(payload: MelAuthIn, request: Request, db: AsyncSession = Depends(get_db)):
    ok, error = await _exchange_oauth_code(request, payload.code, db)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Falha ao conectar.")
    return {"ok": True}