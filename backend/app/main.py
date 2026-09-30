"""API платформы «Промышленная кооперация» (FastAPI).

Запуск: uvicorn app.main:app --reload   (из каталога backend/)
Данные хранятся в PostgreSQL, у каждого раздела своя база (docs/DATABASE.md):
  sm01_catalog    — каталог предприятий (пишет сбор, API читает и держит в памяти для подбора поставщиков);
  sm01_ingest     — состояние сбора, журналы, запросы ручного запуска;
  sm01_accounts   — пользователи, сессии, личный кабинет, уведомления (персональные данные);
  sm01_market     — предложения, заявки, отклики;
  sm01_chains     — производственные цепочки;
  sm01_moderation — регистрации представителей, решения модератора, правки продукции, аудит.
"""
from __future__ import annotations
import hmac, json, os, re, subprocess, sys, time, uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import psycopg
from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator

from pkdb import tx
from pkdb import ingest
from pkdb import catalog as cat

from . import bundle as bd
from . import overview as ov
from . import notify as nt
from . import profile as pf
from . import userstore as us
from .auth import TOKENS, create_session, is_moderator, optional_user, role, user  # noqa: F401 (TOKENS — для тестов)
from .matching import parse_query, search, match_company, query_dict, StructuredQuery
from .repo import get_repo, DataRepo
from .validators import inn_ok, ogrn_ok, kpp_ok, okpo_ok

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("PK_CORS", "http://localhost:3000,http://localhost:8000").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]


def sanitize_text(value, *, multiline: bool = False):
    """Убирает управляющие символы и лишние пробелы. Длину не обрезает: её проверяют ограничения полей (ответ 422).

    multiline — сохранить переводы строк (описания, характеристики). Не строки возвращаются как есть,
    чтобы Pydantic сам отклонил неверный тип.
    """
    if not isinstance(value, str):
        return value
    if multiline:
        text = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]+", " ", value.replace("\r\n", "\n").replace("\r", "\n"))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"[\x00-\x1F\x7F]+", " ", value)
    return re.sub(r"\s+", " ", text).strip()


# Строковые поля без собственного ограничения длины
Short = Annotated[str, Field(max_length=250)]
Medium = Annotated[str, Field(max_length=500)]


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    origin = origin.strip()
    return origin in ALLOWED_ORIGINS or any(urlsplit(origin).scheme == urlsplit(o).scheme and urlsplit(origin).netloc == urlsplit(o).netloc for o in ALLOWED_ORIGINS)


app = FastAPI(title="Промышленная кооперация API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "If-None-Match"],
    allow_credentials=False,
)

# ---------- безопасность: rate limit, RBAC, защита HTTP headers ----------
_hits: dict[str, deque] = defaultdict(deque)
RATE = int(os.environ.get("PK_RATE_PER_MIN", "120"))


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    origin = request.headers.get("origin")
    # страница с того же адреса, что и API (сайт отдаёт сам сервер), разрешена всегда
    same_origin = origin and urlsplit(origin).netloc == request.headers.get("host")
    if origin and not same_origin and not is_allowed_origin(origin):
        return JSONResponse({"detail": "Origin not permitted"}, status_code=403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        ctype = request.headers.get("content-type", "")
        if ctype and not ctype.startswith("application/json"):
            return JSONResponse({"detail": "Unsupported media type. Use JSON."}, status_code=415)

    api = request.url.path.startswith("/api/")
    if api:   # ограничение частоты — для API; страница сайта отдаётся без него
        key = request.client.host if request.client else "anon"
        now = time.time(); q = _hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE:
            return JSONResponse({"detail": "Слишком много запросов. Повторите через минуту."}, status_code=429)
        q.append(now)

    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if api:   # у страницы сайта своя политика в <meta http-equiv="Content-Security-Policy">
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return resp


@app.exception_handler(psycopg.errors.IntegrityError)
async def integrity_error(request: Request, exc: psycopg.errors.IntegrityError):
    # нарушение ограничений базы (статус не из списка, отрицательная цена, пустое обязательное поле)
    return JSONResponse({"detail": "Данные не прошли проверку базы: " + (exc.diag.message_primary or "ограничение")}, status_code=422)


def audit(u, action, entity, eid, after=None):
    with tx("moderation") as m:
        m.execute("INSERT INTO audit_log (actor_id, action, entity, entity_id, payload) VALUES (%s,%s,%s,%s,%s)",
                  (u["id"], action, entity, None if eid is None else str(eid), Jsonb(after) if after is not None else None))


# ---------- сессия пользователя ----------
@app.post("/api/v1/session", status_code=201)
def new_session(request: Request):
    """Новая сессия браузера. Токен знает только браузер, в базе — его хеш."""
    return create_session(request)


@app.get("/api/v1/session")
def current_session(u=Depends(user)):
    return {"user": {"id": u["id"], "role": u["role"]}, "moderator": is_moderator(u)}


# ---------- справочники и каталог ----------
def public_company(c: dict, full=False) -> dict:
    keys = None if full else ("id", "name", "short", "inn", "ogrn", "region", "city", "address", "okved_main", "industry", "subindustry", "verification_status")
    d = {k: v for k, v in c.items() if keys is None or k in keys}
    if not full:
        d["products_count"] = len(c["products"])
    return d


@app.get("/api/v1/meta")
def meta(repo: DataRepo = Depends(get_repo)):
    t = repo.totals
    return {"data_revision": repo.revision, "companies": t["companies"], "products": t["products"], "sources": t["sources"],
            "companies_in_memory": len(repo.companies)}


@app.get("/api/v1/bundle")
def catalog_bundle(request: Request, repo: DataRepo = Depends(get_repo)):
    """Каталог для сайта: облегчённые карточки всех предприятий, справочники, итоги сбора. Сжат gzip, ETag по ревизии."""
    tag, gz, raw_size = bd.get(repo)
    headers = {"ETag": tag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding", "X-Uncompressed-Size": str(raw_size)}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    if "gzip" in (request.headers.get("accept-encoding") or ""):
        return Response(gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(bd.raw_body(), media_type="application/json", headers=headers)


@app.get("/api/v1/stats")
def stats(u=Depends(optional_user), repo: DataRepo = Depends(get_repo)):
    """Сводка для панели мониторинга xRoyse: каталог — всем, пользовательские разделы — модератору (только числа)."""
    t = repo.totals
    with tx("catalog") as c:
        r = c.execute("""SELECT count(*) FILTER (WHERE verification_status = 'VERIFIED') AS verified,
                                count(*) FILTER (WHERE origin IN ('registry_sync', 'registry_fast')) AS registry,
                                (SELECT count(DISTINCT company_id) FROM company_risk_signal WHERE level = 'high') AS risk FROM company""").fetchone()
    out = {"catalog": {"companies": t["companies"], "revision": repo.revision, "activeCompanies": t["active"], "verifiedCompanies": r["verified"],
                       "fromRegistrySync": r["registry"], "regions": t["regions"], "products": t["products"], "riskCompanies": r["risk"]}}
    with tx("ingest") as g:
        last = ingest.read_run(g, changes_limit=0, with_errors=False)
    out["lastSync"] = {k: last.get(k) for k in ("at", "finished", "found", "stats")} if last else None
    if is_moderator(u):
        with tx("accounts") as a, tx("market") as m, tx("moderation") as mo, tx("chains") as ch:
            out["platform"] = {
                "users": a.execute("SELECT count(*) AS n FROM app_user WHERE kind <> 'staff'").fetchone()["n"],
                "representatives": a.execute("SELECT count(*) AS n FROM user_account").fetchone()["n"],
                "offers": m.execute("SELECT count(*) AS n FROM offer").fetchone()["n"],
                "requests": m.execute("SELECT count(*) AS n FROM purchase_request").fetchone()["n"],
                "responses": m.execute("SELECT count(*) AS n FROM request_response").fetchone()["n"],
                "chains": ch.execute("SELECT count(*) AS n FROM chain").fetchone()["n"],
                "pendingRegistrations": mo.execute("SELECT count(*) AS n FROM registration r WHERE NOT EXISTS "
                                                   "(SELECT 1 FROM registration_decision d WHERE d.user_id = r.user_id AND d.submitted_at = r.submitted_at)").fetchone()["n"]}
    return out


@app.get("/api/v1/overview")
def overview(repo: DataRepo = Depends(get_repo)):
    """Раздел «Статистика» на сайте: предприятия и продукция по регионам и отраслям, источники продукции, ход сбора. Открыт всем."""
    out = dict(ov.catalog(repo))
    try:
        out["collection"] = ov.collection()
    except Exception:   # база сбора недоступна: статистика каталога всё равно показывается
        out["collection"] = None
    return out


@app.get("/api/v1/companies")
def companies(region: str | None = None, okved: str | None = None, status: str | None = None, q: str | None = Query(None, max_length=200),
              industry: str | None = None, city: str | None = None, include_unverified: bool = False,
              sort: Literal["revenue", "status", "name", "region", "products"] = "revenue",
              page: int = Query(1, ge=1, le=10000), size: int = Query(20, ge=1, le=100), repo: DataRepo = Depends(get_repo)):
    """Список предприятий по всему каталогу, в том числе тех, которых нет в каталоге, отданном браузеру (repo.list_companies)."""
    statuses = [status] if status else ["VERIFIED", "PARTIALLY_VERIFIED"] + (["UNVERIFIED", "OUTDATED"] if include_unverified else [])
    total, items = repo.list_companies(region=region, industry=industry, okved=okved, city=city, q=q, statuses=statuses, sort=sort,
                                       offset=(page - 1) * size, limit=size)
    return {"total": total, "page": page, "items": items}


@app.get("/api/v1/companies/{cid}")
def company(cid: str, repo: DataRepo = Depends(get_repo)):
    """Полная карточка из базы: все источники, история изменений, отчётность и налоги, продукция с описанием и характеристиками.
    Сайт загружает её при открытии предприятия — в том числе того, которого нет в каталоге, отданном браузеру."""
    c = repo.full(cid)
    if not c:
        raise HTTPException(404, "Предприятие не найдено")
    return {**public_company(c, full=True), "relations": [r for r in repo.relations if cid in (r["from"], r["to"])]}


@app.get("/api/v1/products")
def products(okpd2: str | None = None, kind: str | None = None, q: str | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), repo: DataRepo = Depends(get_repo)):
    items = [p for p in repo.products.values() if (not okpd2 or (p.get("okpd2") or {}).get("code", "").startswith(okpd2))
             and (not kind or p["kind"] == kind) and (not q or q.lower() in p["name"].lower())]
    return {"total": len(items), "items": [dict(p) for p in items[(page - 1) * size: page * size]]}


@app.get("/api/v1/products/{pid}")
def product(pid: str, repo: DataRepo = Depends(get_repo)):
    p = repo.product(pid)
    if p is None:
        raise HTTPException(404, "Позиция не найдена")
    return p


@app.get("/api/v1/sources/{sid}")
def source(sid: str, repo: DataRepo = Depends(get_repo)):
    s = repo.source(sid)
    if s is None:
        raise HTTPException(404, "Источник не найден")
    return s


@app.get("/api/v1/okved")
def okved(repo: DataRepo = Depends(get_repo)):
    return [{"code": k, "name": v} for k, v in repo.okved.items()]


@app.get("/api/v1/okpd2")
def okpd2(repo: DataRepo = Depends(get_repo)):
    return [{"code": k, "name": v} for k, v in repo.okpd2.items()]


# ---------- поиск ----------
class SearchIn(BaseModel):
    text: str = Field(min_length=2, max_length=500)
    city: str | None = Field(None, max_length=120)
    include_unverified: bool = False
    use_llm: bool = False

    @field_validator("text", "city", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return sanitize_text(value)


def llm_parse(text: str) -> StructuredQuery:
    """Разбор через LLM (если задан ANTHROPIC_API_KEY): только структура, без фактов. Иначе — правила."""
    q = parse_query(text)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return q
    try:
        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=os.environ.get("PK_LLM_MODEL", "claude-haiku-4-5"), max_tokens=400,
            system="Разбери промышленный запрос в JSON {product_keywords[], technology_keywords[], material, volume, unit, period, region}. Не называй предприятий и фактов.",
            messages=[{"role": "user", "content": text}])
        extra = json.loads(msg.content[0].text)
        q2 = parse_query(" ".join([text, *extra.get("product_keywords", []), *extra.get("technology_keywords", []), extra.get("material") or "", extra.get("region") or ""]))
        q2.raw, q2.engine = text, "llm"
        q2.volume = q2.volume if q2.volume is not None else extra.get("volume")
        return q2
    except Exception:
        return q


@app.post("/api/v1/search/parse")
def search_parse(body: SearchIn):
    return query_dict(llm_parse(body.text) if body.use_llm else parse_query(body.text))


@app.post("/api/v1/search")
def do_search(body: SearchIn, repo: DataRepo = Depends(get_repo)):
    q = llm_parse(body.text) if body.use_llm else parse_query(body.text)
    res = search(q, repo, body.include_unverified, body.city)
    return {"query": query_dict(q), "results": res,
            "message": None if res else "Информация не найдена в открытых источниках."}


# ---------- заявки и предложения ----------
Unit = Literal["т", "кг", "шт", "м", "м²", "м³", "л", "комплект", "партия"]


class OfferIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category: Short
    organization_id: Short | None = None
    description: str | None = Field(None, max_length=5000)
    material: Short | None = None
    okpd2: str | None = Field(None, pattern=r"^\d{2}(\.\d{1,2}){0,3}$")
    quantity: float | None = Field(None, ge=0)
    unit: Unit | None = None
    price_value: float | None = Field(None, ge=0)
    price_currency: str = Field("RUB", max_length=10)
    price_unit: Short | None = None
    min_batch: Short | None = None
    lead_time_production: Short | None = None
    lead_time_delivery: Short | None = None
    city: Short | None = None
    country: str | None = Field(None, max_length=60)   # страна производства
    price_negotiable: bool | None = None               # торг возможен; False — цена окончательная

    @field_validator("title", "category", "organization_id", "material", "price_currency", "price_unit", "min_batch", "lead_time_production", "lead_time_delivery", "city", "country", mode="before")
    @classmethod
    def sanitize_str(cls, value):
        return sanitize_text(value)

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, value):
        return sanitize_text(value, multiline=True)

    @model_validator(mode="after")
    def _deal_needs_price(self):
        # торг или окончательная цена имеют смысл только при указанной цене; у «Цены по запросу» пометки нет
        if self.price_value is None:
            self.price_negotiable = None
        elif self.price_negotiable is None:
            self.price_negotiable = False
        return self


class RequestIn(BaseModel):
    what: str = Field(min_length=3, max_length=500)
    quantity: float | None = Field(None, ge=0)
    unit: Unit | None = None
    period: Literal["мес", "год"] | None = None
    material: Short | None = None
    okpd2: str | None = Field(None, pattern=r"^\d{2}(\.\d{1,2}){0,3}$")
    certificates: Medium | None = None
    region: str | None = Field(None, max_length=10)
    city: Short | None = None
    max_distance_km: int | None = Field(None, ge=0)
    budget: float | None = Field(None, ge=0)
    target_organization_id: Short | None = None

    @field_validator("what", "material", "certificates", "region", "city", "target_organization_id", mode="before")
    @classmethod
    def sanitize_request_text(cls, value):
        return sanitize_text(value)


@app.post("/api/v1/offers", status_code=201)
def create_offer(body: OfferIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    if body.organization_id and not repo.exists(body.organization_id):
        raise HTTPException(422, "Предприятие не найдено в базе")
    oid = uuid.uuid4().hex
    row = {"title": body.title, "category": body.category, "company_name": None, "company_id": body.organization_id, "description": body.description,
           "material": body.material, "okpd2": body.okpd2, "specs": None, "qty": body.quantity, "unit": body.unit, "price_value": body.price_value,
           "price_currency": body.price_currency if body.price_value is not None else None, "price_unit": body.price_unit, "price_date": None,
           "price_negotiable": body.price_negotiable, "price_source": "SELLER" if body.price_value is not None else None, "country": body.country,
           "min_batch": body.min_batch, "lead_time_production": body.lead_time_production, "lead_time_delivery": body.lead_time_delivery,
           "city": body.city, "warehouse": None, "terms": None, "docs": None, "status": "NEW", "created_at": None, "extra": {}}
    with tx("market") as m:
        r = us.insert_offer(m, oid, u["id"], row)
    audit(u, "create", "offer", oid)
    return us.offer_api(r)


@app.get("/api/v1/offers")
def list_offers(u=Depends(optional_user)):
    with tx("market") as m:
        return us.read_offers(m, u)


@app.post("/api/v1/requests", status_code=201)
def create_request(body: RequestIn, background: BackgroundTasks, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    rid = uuid.uuid4().hex
    q = parse_query(" ".join(filter(None, [body.what, body.material])))
    if body.quantity is not None:
        q.volume, q.unit, q.period = body.quantity, body.unit, body.period
    if body.region:
        q.region = body.region
    sup = search(q, repo, city=body.city)
    if body.max_distance_km is not None:
        sup = [s for s in sup if s["distance_km"] is None or s["distance_km"] <= body.max_distance_km]
    row = {"company_id": None, "target_company_id": body.target_organization_id, "target_product_id": None, "what": body.what, "qty": body.quantity,
           "unit": body.unit, "period": body.period, "material": body.material, "okpd2": body.okpd2, "specs": None, "certificates": body.certificates,
           "deadline": None, "region_code": body.region, "region_name": (repo.regions.get(body.region or "") or {}).get("name"), "city": body.city,
           "max_distance_km": body.max_distance_km, "budget": body.budget, "requirements": None, "status": "NEW", "created_at": None, "extra": {}}
    with tx("market") as m:
        r = us.insert_request(m, rid, u["id"], row, parsed_query=query_dict(q))
        m.cursor().executemany("INSERT INTO request_supplier (request_id, company_id, pos, match) VALUES (%s,%s,%s,%s)",
                               [(rid, s["company_id"], i, Jsonb(s)) for i, s in enumerate(sup)])
    audit(u, "create", "request", rid)
    # Уведомляем представителей подобранных поставщиков, кроме автора заявки. Только подтверждённых модератором:
    # иначе любой, кто назвался представителем компании, сразу получал бы заявки, адресованные ей
    matched = [s["company_id"] for s in sup]
    with tx("moderation") as mo:
        reps = [x["user_id"] for x in mo.execute("SELECT user_id FROM company_rep WHERE company_id = ANY(%s)", (matched,)) if x["user_id"] != u["id"]]
    if reps:
        nt.notifier.dispatch("new_requests", body.what, nt.settings_for(reps), link=f"#r.{rid}")
    return request_api(r, sup)


def request_api(r: dict, sup: list) -> dict:
    return {"id": r["id"], "what": r["what"], "quantity": us.out_num(r["qty"]), "unit": r["unit"], "period": r["period"], "material": r["material"],
            "okpd2": r["okpd2"], "certificates": r["certificates"], "region": r["region_code"], "city": r["city"], "max_distance_km": r["max_distance_km"],
            "budget": us.out_num(r["budget"]), "target_organization_id": r["target_company_id"], "author": r["author_id"],
            "parsed_query": r["parsed_query"], "suppliers": sup, "created_at": r["created_at"].timestamp()}


@app.get("/api/v1/requests/{rid}")
def get_request(rid: str):
    with tx("market") as m:
        r = m.execute("SELECT * FROM purchase_request WHERE id = %s", (rid,)).fetchone()
        if not r:
            raise HTTPException(404, "Заявка не найдена")
        sup = [x["match"] for x in m.execute("SELECT match FROM request_supplier WHERE request_id = %s ORDER BY pos", (rid,))]
    return request_api(r, sup)


# ---------- производственные цепочки ----------
class NodeIn(BaseModel):
    step: str = Field(min_length=2, max_length=200)
    requirement: Medium | None = None
    organization_id: Short | None = None
    product_id: Short | None = None


class ChainIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    buyer_city: Short | None = None
    nodes: list[NodeIn] = Field(default_factory=list, max_length=50)


def _rel(repo, a, b):
    r = next((x for x in repo.relations if x["from"] == a.get("organization_id") and x["to"] == b.get("organization_id")), None)
    return r["type"] if r else "INFERRED_RELATION"


def _api_chain_doc(ch: dict) -> dict:
    """Цепочка в формате API → документ для сохранения (формат сайта)."""
    return {"id": ch["id"], "title": ch["title"], "buyer_city": ch.get("buyer_city"),
            "nodes": [{"id": n["id"], "step": n["step"], "req_text": n.get("requirement"), "company_id": n.get("organization_id"),
                       "product_id": n.get("product_id"), "status": n["status"],
                       "history": [{"company_id": h["from"], "to": h["to"], "reason": h["reason"], "at": h["at"]} for h in n.get("history") or []]}
                      for n in ch["nodes"]],
            "edges": [{"from": e["from"], "to": e["to"], "type": e["relation"]} for e in ch["edges"]]}


@app.post("/api/v1/chains", status_code=201)
def create_chain(body: ChainIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    for n in body.nodes:
        if n.organization_id and not repo.exists(n.organization_id):
            raise HTTPException(422, f"Предприятие {n.organization_id} не найдено в базе")
    cid = uuid.uuid4().hex
    nodes = [{**n.model_dump(), "id": uuid.uuid4().hex, "status": "SELECTED" if n.organization_id else "EMPTY", "history": []} for n in body.nodes]
    edges = [{"from": a["id"], "to": b["id"], "relation": _rel(repo, a, b)} for a, b in zip(nodes, nodes[1:])]
    pf.save_chain(u["id"], _api_chain_doc({"id": cid, "title": body.title, "buyer_city": body.buyer_city, "nodes": nodes, "edges": edges}))
    return _own_chain(cid, u)


def _own_chain(cid, u):
    ch = pf.load_chains(u["id"], cid, api=True)
    if not ch:
        raise HTTPException(404, "Цепочка не найдена")
    return ch[0]


@app.post("/api/v1/chains/{cid}/nodes/{nid}/alternatives")
def alternatives(cid: str, nid: str, include_unverified: bool = False, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    """Замена поставщика: альтернативы без автоматического выбора победителя."""
    ch = _own_chain(cid, u)
    nd = next((n for n in ch["nodes"] if n["id"] == nid), None)
    if nd is None:
        raise HTTPException(404, "Узел не найден")
    p = repo.products.get(nd.get("product_id") or "")
    q = parse_query(" ".join(filter(None, [nd.get("requirement"), p["name"] if p else None, nd.get("step")])))
    if p and p.get("okpd2"):
        q.okpd2 = p["okpd2"]["code"]
    cur_co = repo.companies.get(nd.get("organization_id") or "")
    # регион текущего поставщика: альтернатива из того же региона получает совпадение по географии
    q.region = cur_co["region"] if cur_co else q.region
    cur = match_company(q, cur_co, repo, ch["buyer_city"]) if cur_co else None
    alts = search(q, repo, include_unverified, ch["buyer_city"], exclude=[nd.get("organization_id")])
    return {"current": cur, "alternatives": alts, "note": "Порядок — по числу подтверждённых критериев. Выбор остаётся за пользователем."}


class PickIn(BaseModel):
    organization_id: Short
    product_id: Short | None = None
    reason: Medium | None = None


@app.post("/api/v1/chains/{cid}/nodes/{nid}/replace")
def replace_supplier(cid: str, nid: str, body: PickIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    ch = _own_chain(cid, u)
    if not repo.exists(body.organization_id):
        raise HTTPException(422, "Предприятие не найдено в базе")
    i, nd = next(((i, n) for i, n in enumerate(ch["nodes"]) if n["id"] == nid), (None, None))
    if nd is None:
        raise HTTPException(404, "Узел не найден")
    nd["history"].append({"from": nd.get("organization_id"), "to": body.organization_id, "reason": body.reason, "at": time.time()})
    nd.update(organization_id=body.organization_id, product_id=body.product_id, status="SELECTED")
    for e in ch["edges"]:
        if e["to"] == nid and i > 0:
            e["relation"] = _rel(repo, ch["nodes"][i - 1], nd)
        if e["from"] == nid and i + 1 < len(ch["nodes"]):
            e["relation"] = _rel(repo, nd, ch["nodes"][i + 1])
    pf.save_chain(u["id"], _api_chain_doc(ch))
    audit(u, "replace_supplier", "chain_node", nid, body.model_dump())
    return _own_chain(cid, u)


# ---------- администрирование ----------
class StatusIn(BaseModel):
    status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"]
    note: Medium | None = None


@app.patch("/api/v1/admin/companies/{cid}/status")
def set_status(cid: str, body: StatusIn, u=Depends(role("moderator")), repo: DataRepo = Depends(get_repo)):
    """Статус проверки выставляет модератор поверх данных сбора (sm01_moderation.status_override): сбор его не затирает."""
    if not repo.exists(cid):
        raise HTTPException(404)
    c = repo.companies.get(cid) or repo.full(cid)
    before = repo.overrides.get(cid) or c["verification_status"]
    with tx("moderation") as m:
        m.execute("INSERT INTO status_override (company_id, status, note, author_id) VALUES (%s,%s,%s,%s) ON CONFLICT (company_id) DO UPDATE SET "
                  "status = EXCLUDED.status, note = EXCLUDED.note, author_id = EXCLUDED.author_id, created_at = now()", (cid, body.status, body.note, u["id"]))
    repo.apply_moderation()
    audit(u, "set_status", "organization", cid, {"before": before, "after": body.status, "note": body.note})
    return {"id": cid, "verification_status": body.status}


class CrawlIn(BaseModel):
    url: str = Field(pattern=r"^https?://", max_length=1000)
    organization_id: Short | None = None

    @field_validator("url", "organization_id", mode="before")
    @classmethod
    def sanitize_crawl_fields(cls, value):
        return sanitize_text(value)


@app.get("/api/v1/admin/crawl-jobs")
def crawl_jobs(u=Depends(role("moderator"))):
    """Очередь повторного обхода (последние задания с итогом) и последний запуск краулера."""
    with tx("ingest") as g:
        last = ingest.crawl_run_last(g)
        return {"jobs": ingest.crawl_jobs_recent(g), "last_run": ingest.crawl_run_doc(last) if last else None}


@app.post("/api/v1/admin/crawl-jobs", status_code=202)
def queue_crawl(body: CrawlIn, u=Depends(role("moderator"))):
    jid = uuid.uuid4().hex
    with tx("ingest") as g:   # очередь в sm01_ingest; краулер (crawler/daemon.py) забирает задания раз в минуту
        r = g.execute("INSERT INTO crawl_job (id, url, organization_id, requested_by) VALUES (%s,%s,%s,%s) RETURNING *",
                      (jid, body.url, body.organization_id, u["id"])).fetchone()
    audit(u, "queue_crawl", "crawl_job", jid, body.model_dump())
    return {"id": jid, **body.model_dump(), "status": r["status"], "at": r["created_at"].timestamp()}


@app.get("/api/v1/admin/crawl-errors")
def crawl_errors(u=Depends(role("moderator")), repo: DataRepo = Depends(get_repo)):
    return [s for s in repo.sources.values() if s.get("fetch_status") != "OK"]


# ---------- официальные сайты, найденные краулером: решение модератора ----------
class SiteDecisionIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253, pattern=r"^[a-z0-9.-]+$")
    decision: Literal["CONFIRMED", "REJECTED"]


@app.get("/api/v1/admin/sites")
def found_sites(status: Literal["CANDIDATE", "CONFIRMED", "REJECTED"] = "CANDIDATE", u=Depends(role("moderator")),
                repo: DataRepo = Depends(get_repo)):
    """Сайты, найденные краулером. CANDIDATE — на сайте совпали название и город, но нет ИНН и адреса: решает модератор."""
    with tx("ingest") as g:
        rows = g.execute("SELECT * FROM site_discovery WHERE status = %s ORDER BY checked_at DESC LIMIT 2000", (status,)).fetchall()
    # предприятия, которых нет в памяти API (быстрое добавление), — реквизиты из базы одним запросом
    rest = list({r["company_id"] for r in rows} - repo.companies.keys())
    with tx("catalog") as c:
        known = {x["id"]: x for x in c.execute("SELECT id, name, city, inn, site FROM company WHERE id = ANY(%s)", (rest,)).fetchall()}
    known.update({cid: repo.companies[cid] for r in rows if (cid := r["company_id"]) in repo.companies})
    return [{"company_id": r["company_id"], "company": c["name"], "city": c.get("city"), "inn": c.get("inn"), "site": c.get("site"),
             "domain": r["domain"], "url": r["url"], "method": r["method"], "status": r["status"], "evidence": r["evidence"] or {},
             "checked_at": r["checked_at"].isoformat()}
            for r in rows if (c := known.get(r["company_id"]))]


@app.post("/api/v1/admin/sites/{cid}")
def decide_site(cid: str, body: SiteDecisionIn, u=Depends(role("moderator")), repo: DataRepo = Depends(get_repo)):
    """CONFIRMED — это сайт предприятия: ежедневный сбор запишет его в карточку, краулер обойдёт; REJECTED — чужой сайт."""
    if not repo.exists(cid):
        raise HTTPException(404, "Предприятие не найдено")
    with tx("ingest") as g:
        r = g.execute("""UPDATE site_discovery SET status = %s, evidence = coalesce(evidence, '{}'::jsonb) || %s, checked_at = now()
                         WHERE company_id = %s AND domain = %s RETURNING company_id, domain, url, status""",
                      (body.decision, Jsonb({"by": "moderator", "moderator": u["id"]}), cid, body.domain)).fetchone()
    if not r:
        raise HTTPException(404, "Такого сайта нет среди найденных краулером")
    audit(u, "site_decision", "organization", cid, body.model_dump())
    return dict(r)


@app.get("/api/v1/admin/audit")
def audit_log(u=Depends(role("admin"))):
    with tx("moderation") as m:
        rows = m.execute("SELECT * FROM audit_log ORDER BY at DESC, id DESC LIMIT 500").fetchall()
    return [{"actor": r["actor_id"], "action": r["action"], "entity": r["entity"], "id": r["entity_id"], "after": r["payload"],
             "at": r["at"].timestamp()} for r in reversed(rows)]


# ---------- сбор данных из реестров: состояние и ручной запуск (кнопка в админ-панели) ----------
# Состояние хранит база sm01_ingest (см. sync/control.py): sync_lock — идёт сбор, sync_state — этап и итоги,
# sync_request — запрос ручного запуска, который планировщик (python -m sync --daemon) забирает в течение 15 секунд.
REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_ALIVE_S = 120
SYNC_LOG = Path(os.environ.get("PK_SYNC_LOG", str(REPO_ROOT / "Trash" / "logs" / "manual-run.log")))


def _age_s(iso: str | None) -> float | None:
    try:
        return time.time() - datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def sync_state() -> dict:
    with tx("ingest") as g:
        st = ingest.read_status(g)
        running = ingest.lock_active(g)
        pending = ingest.request_pending(g)
        latest = None if st.get("last_run") else ingest.read_run(g, changes_limit=0, with_errors=False)
    daemon_age = _age_s(st.get("daemon_at"))
    return {"running": running, "stage": st.get("stage") if running else None, "done": st.get("done") if running else None,
            "total": st.get("total") if running else None, "trigger": st.get("trigger") if running else None,
            "started_at": st.get("started_at") if running else None,
            "daemon_alive": daemon_age is not None and -60 < daemon_age < DAEMON_ALIVE_S, "schedule": st.get("schedule"), "next_run": st.get("next_run"),
            "request_pending": pending,
            "last_run": st.get("last_run") or ({k: latest.get(k) for k in ("at", "finished", "found", "queued_new", "stats")} if latest else None),
            "last_trigger": st.get("last_trigger"), "error": st.get("error")}


def spawn_sync() -> None:
    """Запустить сбор отдельным процессом, если планировщик не работает (локальный сервер без python -m sync --daemon)."""
    SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    out = open(SYNC_LOG, "a", encoding="utf-8")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-m", "sync"], cwd=REPO_ROOT, stdout=out, stderr=subprocess.STDOUT,
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kw)


@app.get("/api/v1/admin/sync")
def sync_status(u=Depends(role("moderator"))):
    return sync_state()


@app.post("/api/v1/admin/sync/run", status_code=202)
def sync_run(u=Depends(role("admin"))):
    st = sync_state()
    if st["running"]:
        raise HTTPException(409, "Сбор уже идёт")
    if st["daemon_alive"]:
        with tx("ingest") as g:
            ingest.request_run(g, u["id"])
        mode, message = "daemon", "Сбор запустится в течение 15 секунд"
    elif (REPO_ROOT / "sync").is_dir():
        spawn_sync()
        mode, message = "spawned", "Планировщик не запущен: сбор запущен отдельным процессом"
    else:
        raise HTTPException(503, "Планировщик сбора не запущен. Запустите сервис sync (docker compose up) или python -m sync --daemon")
    audit(u, "sync_run", "sync", mode)
    return {**sync_state(), "mode": mode, "message": message}


@app.post("/api/v1/admin/reload-data")
def reload_data(u=Depends(role("admin")), repo: DataRepo = Depends(get_repo)):
    repo.reload()
    return meta(repo)


# ---------- регистрация представителя компании ----------
def _norm_name(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'().,]", " ", s)
    s = re.sub(r"\b(ооо|оао|зао|пао|ао|ип|нпо|пк|фнпц|ано)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@app.get("/api/v1/suggest/companies")
def suggest_companies(q: str = Query(min_length=2, max_length=100), repo: DataRepo = Depends(get_repo)):
    """Подсказка при регистрации: поиск по названию или началу ИНН, с известными реквизитами."""
    # по всему каталогу в базе: все слова названия (без организационно-правовой формы) префиксами или начало ИНН
    with tx("catalog") as c:
        ids = cat.find_companies(c, q.strip() if q.strip().isdigit() else _norm_name(q), limit=8)
        comps, _, _ = cat.load_companies(c, ids) if ids else ({}, None, None)
    return [{k: c.get(k) for k in ("id", "name", "legal_name", "inn", "ogrn", "kpp", "okpo", "okved_main", "reg_date",
                                    "address", "site", "city", "verification_status")}
            | {"phone": (c.get("phones") or [None])[0], "email": (c.get("emails") or [None])[0]}
            for cid in ids if (c := comps.get(cid))]


class AccountIn(BaseModel):
    fio: str = Field(min_length=3, max_length=200)
    position: str = Field(min_length=2, max_length=200)
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: str | None = Field(None, max_length=50)
    consent: bool

    @field_validator("fio", "position", "email", "phone", mode="before")
    @classmethod
    def sanitize_contact_fields(cls, value):
        return sanitize_text(value)

    @field_validator("consent")
    @classmethod
    def _consent(cls, v):
        if not v:
            raise ValueError("Нужно согласие на обработку персональных данных (152-ФЗ)")
        return v


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    legal_name: str = Field(min_length=2, max_length=500)
    inn: str
    ogrn: str
    kpp: str | None = None
    okpo: str | None = None
    okved_main: str = Field(pattern=r"^\d{2}(\.\d{1,2}){0,3}$")
    reg_date: str | None = None
    address: str = Field(min_length=5, max_length=500)
    postal_address: Medium | None = None
    site: Short | None = None
    phone: str | None = Field(None, max_length=50)
    email: Short | None = None

    @field_validator("name", "legal_name", "inn", "ogrn", "kpp", "okpo", "reg_date", "address", "postal_address", "site", "phone", "email", mode="before")
    @classmethod
    def sanitize_company_fields(cls, value):
        return sanitize_text(value)

    @field_validator("inn")
    @classmethod
    def _inn(cls, v):
        if not inn_ok(v):
            raise ValueError("ИНН не проходит проверку контрольной суммы")
        return v

    @field_validator("ogrn")
    @classmethod
    def _ogrn(cls, v):
        if not ogrn_ok(v):
            raise ValueError("ОГРН не проходит проверку контрольной суммы")
        return v

    @field_validator("kpp")
    @classmethod
    def _kpp(cls, v):
        if v and not kpp_ok(v.upper()):
            raise ValueError("КПП: 9 знаков, например 344601001")
        return v.upper() if v else v

    @field_validator("okpo")
    @classmethod
    def _okpo(cls, v):
        if v and not okpo_ok(v):
            raise ValueError("ОКПО не проходит проверку контрольной суммы")
        return v


class RegistrationIn(BaseModel):
    account: AccountIn
    company: CompanyIn
    base_company_id: str | None = None   # карточка из базы, из которой подставлены реквизиты
    data_checked: bool                    # представитель вручную проверил все данные

    @field_validator("data_checked")
    @classmethod
    def _checked(cls, v):
        if not v:
            raise ValueError("Подтвердите, что проверили все данные компании")
        return v


def registration_api(uid: str) -> dict | None:
    with tx("moderation") as m:
        r = m.execute("SELECT * FROM registration WHERE user_id = %s", (uid,)).fetchone()
        d = m.execute("SELECT * FROM registration_decision WHERE user_id = %s", (uid,)).fetchone()
    if not r:
        return None
    acc = us._accounts_of([uid]).get(uid) or {}
    company = {k: r[k] for k in us.REG_COMPANY}
    return {"account": {"fio": acc.get("fio"), "position": acc.get("position"), "email": acc.get("email"), "phone": acc.get("phone"),
                        "consent": acc.get("consent_at") is not None},
            "company": company, "base_company_id": r["base_company_id"], "data_checked": r["data_checked"], "user": uid, "status": r["status"],
            "moderator_comment": d["comment"] if d else None, "created_at": r["submitted_at"].timestamp()}


@app.post("/api/v1/registration", status_code=201)
def register(body: RegistrationIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    co = body.company
    if len(co.inn) == 10 and not co.kpp:
        raise HTTPException(422, "Для организации укажите КПП")
    if (len(co.inn) == 12) != (len(co.ogrn) == 15):
        raise HTTPException(422, "ИНН и ОГРН относятся к разным типам лиц")
    if body.base_company_id and not repo.exists(body.base_company_id):
        raise HTTPException(404, "Карточка предприятия не найдена")
    us.save_account(u["id"], body.account.model_dump(), consent=True)
    with tx("moderation") as m:
        us.upsert_registration(m, u["id"], {"company": co.model_dump(), "base_company_id": body.base_company_id, "status": "PENDING_MODERATION",
                                            "data_checked": True})
        m.execute("DELETE FROM registration_decision WHERE user_id = %s", (u["id"],))   # новая отправка — прежнее решение к ней не относится
    audit(u, "register", "organization", co.inn)
    return registration_api(u["id"])


@app.get("/api/v1/registration")
def my_registration(u=Depends(role("user"))):
    reg = registration_api(u["id"])
    if not reg:
        raise HTTPException(404, "Регистрация не найдена")
    return reg


class ModerationIn(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    comment: Medium | None = None


@app.patch("/api/v1/admin/registrations/{uid}")
def moderate_registration(uid: str, body: ModerationIn, u=Depends(role("moderator"))):
    with tx("moderation") as m:
        reg = m.execute("SELECT * FROM registration WHERE user_id = %s FOR UPDATE", (uid,)).fetchone()
        if not reg:
            raise HTTPException(404, "Регистрация не найдена")
        m.execute("UPDATE registration SET status = %s WHERE user_id = %s", (body.status, uid))
        m.execute("INSERT INTO registration_decision (user_id, status, comment, submitted_at, moderator_id, company_name) VALUES (%s,%s,%s,%s,%s,%s) "
                  "ON CONFLICT (user_id) DO UPDATE SET status = EXCLUDED.status, comment = EXCLUDED.comment, decided_at = now(), "
                  "submitted_at = EXCLUDED.submitted_at, moderator_id = EXCLUDED.moderator_id, company_name = EXCLUDED.company_name",
                  (uid, body.status, body.comment, reg["submitted_at"], u["id"], reg["name"]))
        # подтверждённый представитель получает заявки, адресованные его компании
        if body.status == "APPROVED" and reg["base_company_id"]:
            m.execute("INSERT INTO company_rep (user_id, company_id, company_name) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET "
                      "company_id = EXCLUDED.company_id, company_name = EXCLUDED.company_name, approved_at = now()", (uid, reg["base_company_id"], reg["name"]))
        else:
            m.execute("DELETE FROM company_rep WHERE user_id = %s", (uid,))
    audit(u, "moderate", "registration", uid, body.status)
    text = f"{reg['name']}: " + ("данные подтверждены, права представителя подтверждены." if body.status == "APPROVED"
                                 else "регистрация отклонена." + (f" Комментарий: {body.comment}" if body.comment else ""))
    nt.notifier.dispatch("moderation", text, nt.settings_for([uid]), link="#cabinet.company")
    return registration_api(uid)


# ---------- уведомления: Telegram и ВКонтакте ----------
class ChannelIn(BaseModel):
    enabled: bool = False
    contact: str | None = Field("", max_length=200)

    @field_validator("contact", mode="before")
    @classmethod
    def sanitize_channel(cls, value):
        return sanitize_text(value)


class NotifySettingsIn(BaseModel):
    channels: dict[Literal["telegram", "vk"], ChannelIn]
    events: dict[Literal["new_requests", "responses", "messages", "risks", "moderation"], dict[Literal["telegram", "vk"], bool]] = {}


@app.get("/api/v1/me/notifications")
def get_notifications(u=Depends(role("user"))):
    return nt.settings_for([u["id"]])[u["id"]]


@app.put("/api/v1/me/notifications")
def put_notifications(body: NotifySettingsIn, u=Depends(role("user"))):
    s = nt.settings_for([u["id"]])[u["id"]]
    for ch, cfg in body.channels.items():
        try:
            contact = nt.normalize_contact(ch, cfg.contact)
        except ValueError as e:
            raise HTTPException(422, str(e))
        s["channels"][ch] = {"enabled": cfg.enabled, "contact": contact}
    for ev, per in body.events.items():
        s["events"][ev].update(per)
    nt.save_settings(u["id"], s)
    return s


@app.post("/api/v1/me/notifications/test")
def test_notification(u=Depends(role("user"))):
    res = nt.notifier.dispatch("test", "Уведомления платформы «Промышленная кооперация» подключены.", nt.settings_for([u["id"]]))
    return {"sent": res, "message": None if res else "Нет включённых каналов с указанным контактом"}


@app.post("/api/v1/notify/telegram/webhook")
def telegram_webhook(update: dict, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    """Вебхук бота: после /start запоминаем chat_id пользователя, чтобы бот мог ему писать.

    Секрет обязателен: без него кто угодно мог бы привязать чужой @username к своему чату и читать чужие уведомления.
    Секрет задаётся в PK_TG_WEBHOOK_SECRET и передаётся Telegram в setWebhook(secret_token=...).
    """
    secret = os.environ.get("PK_TG_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "Вебхук не настроен: задайте PK_TG_WEBHOOK_SECRET")
    if not hmac.compare_digest(x_telegram_bot_api_secret_token or "", secret):
        raise HTTPException(403, "Неверный секрет вебхука")
    msg = update.get("message") or {}
    tg_user, chat = msg.get("from") or {}, msg.get("chat") or {}
    if (msg.get("text") or "").startswith("/start") and tg_user.get("username") and chat.get("id") is not None:
        nt.link_telegram(tg_user["username"], chat["id"])
        return {"linked": "@" + tg_user["username"]}
    return {"linked": None}


# ---------- уведомления на сайте (лента в личном кабинете) ----------
@app.get("/api/v1/me/inbox")
def my_inbox(unread_only: bool = False, u=Depends(role("user"))):
    with tx("accounts") as a:
        items = [pf.inbox_item(r, site=False) for r in a.execute("SELECT * FROM inbox_notice WHERE user_id = %s ORDER BY at DESC", (u["id"],))]
    return {"unread": sum(not x["read"] for x in items), "items": [x for x in items if not x["read"]] if unread_only else items}


class ReadIn(BaseModel):
    ids: list[str] | None = None   # None — отметить прочитанными все


@app.post("/api/v1/me/inbox/read")
def read_inbox(body: ReadIn, u=Depends(role("user"))):
    with tx("accounts") as a:
        if body.ids is None:
            n = a.execute("UPDATE inbox_notice SET read = true WHERE user_id = %s AND NOT read", (u["id"],)).rowcount
        else:
            n = a.execute("UPDATE inbox_notice SET read = true WHERE user_id = %s AND NOT read AND id = ANY(%s)", (u["id"], body.ids)).rowcount
    return {"marked": n}


# ---------- данные сайта: коллекции, личный кабинет, цепочки ----------
MAX_DOC_BYTES = 64_000


def _check_id(doc_id: str) -> str:
    if not re.fullmatch(r"[\w:.\-]{1,120}", doc_id):
        raise HTTPException(422, "Недопустимый идентификатор записи")
    return doc_id


def _check_size(doc: Any):
    if len(json.dumps(doc, ensure_ascii=False)) > MAX_DOC_BYTES:
        raise HTTPException(413, "Запись слишком большая")


@app.get("/api/v1/store")
def store_all(u=Depends(optional_user)):
    """Все коллекции сайта, которые может видеть пользователь (без входа — только общедоступные)."""
    return us.read_all(u)


@app.get("/api/v1/store/{name}")
def store_list(name: str, u=Depends(optional_user)):
    spec = us.coll(name)
    with tx(spec.db) as c:
        return spec.read(c, u)


@app.put("/api/v1/store/{name}/{doc_id}")
def store_put(name: str, doc_id: str, background: BackgroundTasks, doc: dict = Body(...), u=Depends(user), repo: DataRepo = Depends(get_repo)):
    spec, doc_id = us.coll(name), _check_id(doc_id)
    _check_size(doc)
    with tx(spec.db) as c:
        existed = False
        if spec.notify:
            key = {"offers": ("offer", "id"), "requests": ("purchase_request", "id"), "responses": ("request_response", "id"),
                   "moderation": ("registration_decision", "user_id"), "decisions": ("item_decision", "key")}.get(name)
            if key:
                existed = bool(c.execute(f"SELECT 1 FROM {key[0]} WHERE {key[1]} = %s", (doc_id,)).fetchone())
        out = spec.put(c, u, doc_id, doc)
    if name in us.AFFECTS_CATALOG:
        repo.apply_moderation()
    if spec.notify:
        background.add_task(lambda: us.send_notices(spec.notify(u, doc_id, doc, not existed)))
    return out


@app.delete("/api/v1/store/{name}/{doc_id}", status_code=204)
def store_delete(name: str, doc_id: str, u=Depends(user), repo: DataRepo = Depends(get_repo)):
    spec = us.coll(name)
    with tx(spec.db) as c:
        spec.delete(c, u, _check_id(doc_id))
    if name in us.AFFECTS_CATALOG:
        repo.apply_moderation()
    return Response(status_code=204)


@app.get("/api/v1/me")
def me(u=Depends(user)):
    """Профиль и цепочки пользователя одним запросом (сайт вызывает его при загрузке и периодически)."""
    return {"user": {"id": u["id"], "role": u["role"]}, "moderator": is_moderator(u), "profile": pf.load_profile(u["id"]),
            "chains": pf.load_chains(u["id"])}


@app.put("/api/v1/me/profile")
def put_profile(profile: dict = Body(...), u=Depends(user)):
    _check_size(profile)
    pf.save_profile(u["id"], profile)
    return {"ok": True}


@app.put("/api/v1/me/chains/{cid}")
def put_chain(cid: str, doc: dict = Body(...), u=Depends(user)):
    _check_size(doc)
    pf.save_chain(u["id"], {**doc, "id": _check_id(cid)})
    return pf.load_chains(u["id"], cid)[0]


@app.delete("/api/v1/me/chains/{cid}", status_code=204)
def delete_chain(cid: str, u=Depends(user)):
    pf.delete_chain(u["id"], _check_id(cid))
    return Response(status_code=204)


class ImportIn(BaseModel):
    collections: dict[str, list[dict]] = {}
    profile: dict | None = None
    chains: list[dict] = []
    local_uid: str | None = "local"


IMPORTABLE = ("offers", "requests", "responses", "reports", "registrations", "product_edits")


@app.post("/api/v1/me/import-local")
def import_local(body: ImportIn, u=Depends(user)):
    """Перенос данных, которые до перехода на сервер хранились только в браузере (localStorage).

    Переносится только то, что пользователь создал сам: предложения, заявки, отклики, сообщения об ошибках, регистрация,
    правки продукции, профиль и цепочки. Решения модератора из браузера не переносятся — в браузере их мог «принять» кто угодно.
    Уже перенесённые записи повторно не создаются.
    """
    _check_size(body.model_dump())
    done: dict[str, int] = {}
    local = body.local_uid or "local"
    for name in IMPORTABLE:
        spec = us.COLLECTIONS[name]
        n = 0
        for doc in body.collections.get(name) or []:
            did = str(doc.get("id") or "")
            if name in ("registrations", "product_edits"):
                if did not in (local, u["id"]):
                    continue
                did = u["id"]
            elif doc.get("author") not in (None, local, u["id"]) or not re.fullmatch(r"[\w:.\-]{1,120}", did):
                continue
            with tx(spec.db) as c:
                table = {"offers": "offer", "requests": "purchase_request", "responses": "request_response", "reports": "report",
                         "registrations": "registration", "product_edits": "product_edit"}[name]
                col = "user_id" if name in ("registrations", "product_edits") else "id"
                if c.execute(f"SELECT 1 FROM {table} WHERE {col} = %s LIMIT 1", (did,)).fetchone():
                    continue
                try:
                    with c.transaction():
                        spec.put(c, u, did, {**doc, "id": did})
                    n += 1
                except HTTPException:
                    continue   # запись не проходит проверку (например, отклик на заявку, которой нет) — пропускаем
        done[name] = n
    if body.profile and not pf.load_profile(u["id"]):
        pf.save_profile(u["id"], body.profile)
        done["profile"] = 1
    n = 0
    have = {c["id"] for c in pf.load_chains(u["id"])}
    for ch in body.chains:
        if ch.get("id") and ch["id"] not in have and re.fullmatch(r"[\w:.\-]{1,120}", str(ch["id"])):
            try:
                pf.save_chain(u["id"], ch)
                n += 1
            except HTTPException:
                pass
    done["chains"] = n
    audit(u, "import_local", "user", u["id"], done)
    return {"imported": done}


# ---------- сайт с того же адреса, что и API (локальный запуск: start-local.cmd → http://localhost:8765) ----------
# Страница обращается к /api/... со своего адреса, поэтому кнопки админ-панели работают без Docker и nginx.
# Подключается последним: маршруты /api/... выше имеют приоритет
SITE_DIST = Path(os.environ.get("PK_SITE_DIST", str(REPO_ROOT / "site" / "dist")))
if SITE_DIST.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    @app.get("/", include_in_schema=False)
    def site_index():
        # полная HTML-страница (doctype, viewport); index.html собран для публикации на claude.ai, где каркас добавляется при публикации
        return FileResponse(SITE_DIST / "preview.html", headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=SITE_DIST, html=True), name="site")
