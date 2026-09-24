"""API платформы «Промышленная кооперация» (FastAPI).

Запуск: uvicorn app.main:app --reload   (из каталога backend/)
Справочные данные читаются из Git-репозитория data/. Пользовательские сущности (заявки, предложения, цепочки)
в этом MVP хранятся в памяти процесса; в продуктиве — таблицы offer, purchase_request, production_chain* (sql/schema.sql).
"""
from __future__ import annotations
import hmac, json, os, re, subprocess, sys, time, uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from .repo import DATA_DIR, get_repo, DataRepo
from .matching import parse_query, search, match_company, query_dict, StructuredQuery
from . import notify as nt
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


app = FastAPI(title="Промышленная кооперация API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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
    if api:   # ограничение частоты — для API; сайт (страница и data.json) отдаётся без него
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
    elif request.url.path.endswith("/data.json"):
        resp.headers["Cache-Control"] = "no-cache"   # база обновляется сбором каждый день
    return resp

ROLES = {"user": 1, "company_admin": 2, "moderator": 3, "admin": 4}
# Токены → роли. Без PK_TOKENS работают только локальные dev-токены; в docker-compose по умолчанию токенов нет
# (PK_TOKENS='{}'), чтобы развёрнутый сервер не пускал по общеизвестному dev-admin. В продуктиве — JWT/SSO.
TOKENS = json.loads(os.environ.get("PK_TOKENS", '{"dev-user":"user","dev-admin":"admin"}'))
if not isinstance(TOKENS, dict) or any(r not in ROLES for r in TOKENS.values()):
    raise RuntimeError("PK_TOKENS: ожидается JSON-объект {токен: роль}, роли: " + ", ".join(ROLES))


def user(authorization: str | None = Header(default=None)) -> dict:
    tok = (authorization or "").removeprefix("Bearer ").strip()
    if tok not in TOKENS:
        raise HTTPException(401, "Требуется авторизация")
    return {"id": tok, "role": TOKENS[tok]}


def role(min_role: str):
    def dep(u: dict = Depends(user)):
        if ROLES[u["role"]] < ROLES[min_role]:
            raise HTTPException(403, "Недостаточно прав")
        return u
    return dep


AUDIT: list[dict] = []
def audit(u, action, entity, eid, after=None):
    AUDIT.append({"actor": u["id"], "action": action, "entity": entity, "id": eid, "after": after, "at": time.time()})


# ---------- справочники и каталог ----------
def public_company(c: dict, full=False) -> dict:
    keys = None if full else ("id", "name", "short", "inn", "ogrn", "region", "city", "address", "okved_main", "industry", "subindustry", "verification_status")
    d = {k: v for k, v in c.items() if keys is None or k in keys}
    if not full:
        d["products_count"] = len(c["products"])
    return d


@app.get("/api/v1/meta")
def meta(repo: DataRepo = Depends(get_repo)):
    return {"data_revision": repo.revision, "companies": len(repo.companies), "products": len(repo.products), "sources": len(repo.sources)}


@app.get("/api/v1/companies")
def companies(region: str | None = None, okved: str | None = None, status: str | None = None, q: str | None = None,
              include_unverified: bool = False, sort: Literal["status", "name", "completeness"] = "status",
              page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), repo: DataRepo = Depends(get_repo)):
    ok = {"VERIFIED", "PARTIALLY_VERIFIED"} | ({"UNVERIFIED", "OUTDATED"} if include_unverified else set())
    items = [c for c in repo.companies.values() if c["verification_status"] in ok
             and (not region or c["region"] == region) and (not okved or c.get("okved_main") == okved)
             and (not status or c["verification_status"] == status)
             and (not q or q.lower() in " ".join([c["name"], c.get("inn") or "", c.get("city") or "", *[p["name"] for p in c["products"]]]).lower())]
    order = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 1, "UNVERIFIED": 2, "OUTDATED": 3}
    items.sort(key={"status": lambda c: (order[c["verification_status"]], c["name"]), "name": lambda c: c.get("short") or c["name"],
                    "completeness": lambda c: -sum(bool(c.get(k)) for k in ("inn", "ogrn", "site", "okved_main", "technologies", "capacities", "certificates"))}[sort])
    return {"total": len(items), "page": page, "items": [public_company(c) for c in items[(page - 1) * size: page * size]]}


@app.get("/api/v1/companies/{cid}")
def company(cid: str, repo: DataRepo = Depends(get_repo)):
    c = repo.companies.get(cid)
    if not c:
        raise HTTPException(404, "Предприятие не найдено")
    return {**public_company(c, full=True), "relations": [r for r in repo.relations if cid in (r["from"], r["to"])]}


@app.get("/api/v1/products")
def products(okpd2: str | None = None, kind: str | None = None, q: str | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), repo: DataRepo = Depends(get_repo)):
    items = [p for p in repo.products.values() if (not okpd2 or (p.get("okpd2") or {}).get("code", "").startswith(okpd2))
             and (not kind or p["kind"] == kind) and (not q or q.lower() in p["name"].lower())]
    return {"total": len(items), "items": items[(page - 1) * size: page * size]}


@app.get("/api/v1/products/{pid}")
def product(pid: str, repo: DataRepo = Depends(get_repo)):
    if pid not in repo.products:
        raise HTTPException(404, "Позиция не найдена")
    return repo.products[pid]


@app.get("/api/v1/sources/{sid}")
def source(sid: str, repo: DataRepo = Depends(get_repo)):
    if sid not in repo.sources:
        raise HTTPException(404, "Источник не найден")
    return repo.sources[sid]


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
OFFERS: dict[str, dict] = {}
REQUESTS: dict[str, dict] = {}
CHAINS: dict[str, dict] = {}
REGISTRATIONS: dict[str, dict] = {}   # user_id → регистрация представителя компании
NOTIFY: dict[str, dict] = {}          # user_id → настройки уведомлений
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
def create_offer(body: OfferIn, u=Depends(role("user"))):
    oid = uuid.uuid4().hex
    OFFERS[oid] = {**body.model_dump(), "id": oid, "author": u["id"], "moderation_status": "NEW",
                   "price_source": "SELLER" if body.price_value is not None else None, "created_at": time.time()}
    audit(u, "create", "offer", oid)
    return OFFERS[oid]


@app.get("/api/v1/offers")
def list_offers():
    return list(OFFERS.values())


@app.post("/api/v1/requests", status_code=201)
def create_request(body: RequestIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    rid = uuid.uuid4().hex
    q = parse_query(" ".join(filter(None, [body.what, body.material])))
    if body.quantity is not None:
        q.volume, q.unit, q.period = body.quantity, body.unit, body.period
    if body.region:
        q.region = body.region
    sup = search(q, repo, city=body.city)
    if body.max_distance_km is not None:
        sup = [s for s in sup if s["distance_km"] is None or s["distance_km"] <= body.max_distance_km]
    REQUESTS[rid] = {**body.model_dump(), "id": rid, "author": u["id"], "parsed_query": query_dict(q), "suppliers": sup, "created_at": time.time()}
    audit(u, "create", "request", rid)
    # Уведомляем представителей подобранных поставщиков, кроме автора заявки. Только подтверждённых модератором:
    # иначе любой, кто назвался представителем компании, сразу получал бы заявки, адресованные ей
    matched = {s["company_id"] for s in sup}
    recipients = {uid: NOTIFY.get(uid, nt.default_settings()) for uid, reg in REGISTRATIONS.items()
                  if uid != u["id"] and reg.get("status") == "APPROVED" and reg.get("base_company_id") in matched}
    if recipients:
        nt.notifier.dispatch("new_requests", body.what, recipients, link=f"#r.{rid}")
    return REQUESTS[rid]


@app.get("/api/v1/requests/{rid}")
def get_request(rid: str):
    if rid not in REQUESTS:
        raise HTTPException(404, "Заявка не найдена")
    return REQUESTS[rid]


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


@app.post("/api/v1/chains", status_code=201)
def create_chain(body: ChainIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    for n in body.nodes:
        if n.organization_id and n.organization_id not in repo.companies:
            raise HTTPException(422, f"Предприятие {n.organization_id} не найдено в базе")
    cid = uuid.uuid4().hex
    nodes = [{**n.model_dump(), "id": uuid.uuid4().hex, "status": "SELECTED" if n.organization_id else "EMPTY", "history": []} for n in body.nodes]
    edges = [{"from": a["id"], "to": b["id"], "relation": _rel(repo, a, b)} for a, b in zip(nodes, nodes[1:])]
    CHAINS[cid] = {"id": cid, "owner": u["id"], "title": body.title, "buyer_city": body.buyer_city, "nodes": nodes, "edges": edges}
    return CHAINS[cid]


def _own_chain(cid, u):
    ch = CHAINS.get(cid)
    if not ch or ch["owner"] != u["id"]:
        raise HTTPException(404, "Цепочка не найдена")
    return ch


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
    if body.organization_id not in repo.companies:
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
    audit(u, "replace_supplier", "chain_node", nid, body.model_dump())
    return ch


# ---------- администрирование ----------
class StatusIn(BaseModel):
    status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"]
    note: Medium | None = None


@app.patch("/api/v1/admin/companies/{cid}/status")
def set_status(cid: str, body: StatusIn, u=Depends(role("moderator")), repo: DataRepo = Depends(get_repo)):
    c = repo.companies.get(cid)
    if not c:
        raise HTTPException(404)
    before = c["verification_status"]; c["verification_status"] = body.status
    audit(u, "set_status", "organization", cid, {"before": before, "after": body.status, "note": body.note})
    return {"id": cid, "verification_status": body.status}


CRAWL_QUEUE: list[dict] = []


class CrawlIn(BaseModel):
    url: str = Field(pattern=r"^https?://", max_length=1000)
    organization_id: Short | None = None

    @field_validator("url", "organization_id", mode="before")
    @classmethod
    def sanitize_crawl_fields(cls, value):
        return sanitize_text(value)


@app.post("/api/v1/admin/crawl-jobs", status_code=202)
def queue_crawl(body: CrawlIn, u=Depends(role("admin"))):
    job = {"id": uuid.uuid4().hex, **body.model_dump(), "status": "QUEUED", "at": time.time()}
    CRAWL_QUEUE.append(job)  # продуктив: Redis-очередь → воркер crawler/
    audit(u, "queue_crawl", "crawl_job", job["id"], body.model_dump())
    return job


@app.get("/api/v1/admin/crawl-errors")
def crawl_errors(u=Depends(role("moderator")), repo: DataRepo = Depends(get_repo)):
    return [s for s in repo.sources.values() if s.get("fetch_status") != "OK"]


@app.get("/api/v1/admin/audit")
def audit_log(u=Depends(role("admin"))):
    return AUDIT[-500:]


# ---------- сбор данных из реестров: состояние и ручной запуск (кнопка в админ-панели) ----------
# Файлы управления пишет парсер sync/ (см. sync/control.py): run.lock — идёт сбор, status.json — этап и итоги,
# run-request.json — запрос ручного запуска, который планировщик (python -m sync --daemon) забирает в течение 15 секунд.
SYNC_DIR = Path(os.environ.get("PK_SYNC_DIR", str(DATA_DIR / "sync")))
REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_LOCK_STALE_S, DAEMON_ALIVE_S = 600, 120


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _age_s(iso: str | None) -> float | None:
    try:
        return time.time() - datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def sync_state() -> dict:
    st = _read_json(SYNC_DIR / "status.json") or {}
    lock = SYNC_DIR / "run.lock"
    running = lock.exists() and time.time() - lock.stat().st_mtime < SYNC_LOCK_STALE_S
    daemon_age = _age_s(st.get("daemon_at"))
    latest = _read_json(SYNC_DIR / "latest.json") or {}
    return {"running": running, "stage": st.get("stage") if running else None, "done": st.get("done") if running else None,
            "total": st.get("total") if running else None, "trigger": st.get("trigger") if running else None,
            "started_at": st.get("started_at") if running else None,
            "daemon_alive": daemon_age is not None and -60 < daemon_age < DAEMON_ALIVE_S, "schedule": st.get("schedule"), "next_run": st.get("next_run"),
            "request_pending": (SYNC_DIR / "run-request.json").exists(),
            "last_run": st.get("last_run") or ({k: latest.get(k) for k in ("at", "finished", "found", "queued_new", "stats")} if latest else None),
            "last_trigger": st.get("last_trigger"), "error": st.get("error")}


def spawn_sync() -> None:
    """Запустить сбор отдельным процессом, если планировщик не работает (локальный сервер без python -m sync --daemon)."""
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    out = open(SYNC_DIR / "manual-run.log", "a", encoding="utf-8")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-m", "sync"], cwd=REPO_ROOT, stdout=out, stderr=subprocess.STDOUT,
                     env={**os.environ, "PK_DATA_DIR": str(DATA_DIR), "PYTHONIOENCODING": "utf-8"}, **kw)


@app.get("/api/v1/admin/sync")
def sync_status(u=Depends(role("moderator"))):
    return sync_state()


@app.post("/api/v1/admin/sync/run", status_code=202)
def sync_run(u=Depends(role("admin"))):
    st = sync_state()
    if st["running"]:
        raise HTTPException(409, "Сбор уже идёт")
    if st["daemon_alive"]:
        SYNC_DIR.mkdir(parents=True, exist_ok=True)
        (SYNC_DIR / "run-request.json").write_text(json.dumps({"requested_by": u["id"], "at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
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
    toks = _norm_name(q).split()
    out = []
    for c in repo.companies.values():
        hay = _norm_name(" ".join(filter(None, [c["name"], c.get("short"), c.get("legal_name")])))
        if (toks and all(t in hay for t in toks)) or (c.get("inn") and c["inn"].startswith(q.strip())):
            out.append({k: c.get(k) for k in ("id", "name", "legal_name", "inn", "ogrn", "kpp", "okpo", "okved_main", "reg_date",
                                              "address", "site", "city", "verification_status")}
                       | {"phone": (c.get("phones") or [None])[0], "email": (c.get("emails") or [None])[0]})
    return out[:8]


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


@app.post("/api/v1/registration", status_code=201)
def register(body: RegistrationIn, u=Depends(role("user")), repo: DataRepo = Depends(get_repo)):
    co = body.company
    if len(co.inn) == 10 and not co.kpp:
        raise HTTPException(422, "Для организации укажите КПП")
    if (len(co.inn) == 12) != (len(co.ogrn) == 15):
        raise HTTPException(422, "ИНН и ОГРН относятся к разным типам лиц")
    if body.base_company_id and body.base_company_id not in repo.companies:
        raise HTTPException(404, "Карточка предприятия не найдена")
    REGISTRATIONS[u["id"]] = {**body.model_dump(), "user": u["id"], "status": "PENDING_MODERATION", "created_at": time.time()}
    NOTIFY.setdefault(u["id"], nt.default_settings())
    audit(u, "register", "organization", co.inn)
    return REGISTRATIONS[u["id"]]


@app.get("/api/v1/registration")
def my_registration(u=Depends(role("user"))):
    if u["id"] not in REGISTRATIONS:
        raise HTTPException(404, "Регистрация не найдена")
    return REGISTRATIONS[u["id"]]


class ModerationIn(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    comment: Medium | None = None


@app.patch("/api/v1/admin/registrations/{uid}")
def moderate_registration(uid: str, body: ModerationIn, u=Depends(role("moderator"))):
    reg = REGISTRATIONS.get(uid)
    if not reg:
        raise HTTPException(404, "Регистрация не найдена")
    reg["status"], reg["moderator_comment"] = body.status, body.comment
    audit(u, "moderate", "registration", uid, body.status)
    text = f"{reg['company']['name']}: " + ("данные подтверждены, права представителя подтверждены." if body.status == "APPROVED"
                                           else "регистрация отклонена." + (f" Комментарий: {body.comment}" if body.comment else ""))
    nt.notifier.dispatch("moderation", text, {uid: NOTIFY.get(uid, nt.default_settings())}, link="#cabinet.company")
    return reg


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
    return NOTIFY.get(u["id"], nt.default_settings())


@app.put("/api/v1/me/notifications")
def put_notifications(body: NotifySettingsIn, u=Depends(role("user"))):
    s = NOTIFY.get(u["id"], nt.default_settings())
    for ch, cfg in body.channels.items():
        try:
            contact = nt.normalize_contact(ch, cfg.contact)
        except ValueError as e:
            raise HTTPException(422, str(e))
        s["channels"][ch] = {"enabled": cfg.enabled, "contact": contact}
    for ev, per in body.events.items():
        s["events"][ev].update(per)
    NOTIFY[u["id"]] = s
    return s


@app.post("/api/v1/me/notifications/test")
def test_notification(u=Depends(role("user"))):
    res = nt.notifier.dispatch("test", "Уведомления платформы «Промышленная кооперация» подключены.", {u["id"]: NOTIFY.get(u["id"], nt.default_settings())})
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
    user, chat = msg.get("from") or {}, msg.get("chat") or {}
    if (msg.get("text") or "").startswith("/start") and user.get("username") and chat.get("id") is not None:
        nt.TELEGRAM_CHATS[user["username"].lower()] = chat["id"]
        return {"linked": "@" + user["username"]}
    return {"linked": None}


# ---------- уведомления на сайте (лента в личном кабинете) ----------
@app.get("/api/v1/me/inbox")
def my_inbox(unread_only: bool = False, u=Depends(role("user"))):
    items = nt.notifier.inbox.get(u["id"], [])
    return {"unread": sum(not x["read"] for x in items), "items": [x for x in items if not x["read"]] if unread_only else items}


class ReadIn(BaseModel):
    ids: list[str] | None = None   # None — отметить прочитанными все


@app.post("/api/v1/me/inbox/read")
def read_inbox(body: ReadIn, u=Depends(role("user"))):
    n = 0
    for x in nt.notifier.inbox.get(u["id"], []):
        if not x["read"] and (body.ids is None or x["id"] in body.ids):
            x["read"] = True
            n += 1
    return {"marked": n}


# ---------- сайт с того же адреса, что и API (локальный запуск: start-local.cmd → http://localhost:8000) ----------
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
