"""Статистика для раздела «Статистика» на сайте: предприятия и продукция по регионам и отраслям, источники, ход сбора.

Считается по индексу всего каталога в памяти API (repo.summary: одна строка на предприятие) и нескольким запросам к базе
sm01_catalog, один раз на ревизию каталога; состояние сбора и краулера читается из sm01_ingest при каждом запросе.
"""
from __future__ import annotations
import threading

from pkdb import ingest, tx
from pkdb import catalog as cat

from .repo import _active

# тип источника позиции продукции → подпись на сайте; остальные — «Первичный сбор и другие источники»
PRODUCT_SOURCES = {"MPT_REESTR": "Реестр промышленной продукции Минпромторга", "OFFICIAL_SITE": "Официальные сайты предприятий",
                   "FNS_RMSP": "Реестр МСП ФНС"}
OTHER_SOURCE = "Первичный сбор и другие источники"
TOP_N = 20

_lock = threading.Lock()
_cache: dict = {"revision": None, "data": None}

def _new_row() -> dict:
    return {"companies": 0, "active": 0, "withProducts": 0, "products": 0, "withSite": 0, "revenueK": 0, "headcount": 0}


def compute(repo) -> dict:
    regions = {k: v.get("name") for k, v in (repo.regions or {}).items()}
    total, by_region, by_industry = _new_row(), {}, {}
    verification, origin = {}, {}
    for s in repo.summary:
        n = s[cat.S_PRODUCTS]
        for r in (total, by_region.setdefault(s[cat.S_REGION] or "—", _new_row()), by_industry.setdefault(s[cat.S_INDUSTRY] or "Не указано", _new_row())):
            r["companies"] += 1
            r["active"] += _active(s)
            r["withProducts"] += n > 0
            r["products"] += n
            r["withSite"] += s[cat.S_SITE]
            r["revenueK"] += s[cat.S_REVENUE] or 0
            r["headcount"] += s[cat.S_HEADCOUNT] or 0
        st = repo.overrides.get(s[cat.S_ID]) or s[cat.S_STATUS]
        verification[st] = verification.get(st, 0) + 1
        origin[s[cat.S_ORIGIN] or "seed"] = origin.get(s[cat.S_ORIGIN] or "seed", 0) + 1
    with tx("catalog") as c:
        added = c.execute("SELECT added_at AS d, count(*) AS n FROM company WHERE added_at IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 14").fetchall()
    # продукция по источникам: у каждого предприятия с продукцией карточка в памяти (ядро каталога), считаем по ней
    merged: dict[str, dict] = {}
    for co in repo.companies.values():
        for label in {PRODUCT_SOURCES.get((repo.sources.get(p["source_id"]) or {}).get("source_type"), OTHER_SOURCE) for p in co["products"]}:
            merged.setdefault(label, {"name": label, "products": 0, "companies": 0})["companies"] += 1
        for p in co["products"]:
            merged[PRODUCT_SOURCES.get((repo.sources.get(p["source_id"]) or {}).get("source_type"), OTHER_SOURCE)]["products"] += 1
    card = lambda s: {"id": s[cat.S_ID], "name": s[cat.S_NAME], "region": regions.get(s[cat.S_REGION], s[cat.S_REGION]),
                      "industry": s[cat.S_INDUSTRY], "revenueK": s[cat.S_REVENUE], "products": s[cat.S_PRODUCTS]}
    return {
        "revision": repo.revision,
        "totals": dict(total, regions=len([k for k in by_region if k != "—"])),
        "regions": sorted(({"code": k, "name": regions.get(k, k), **v} for k, v in by_region.items()), key=lambda r: -r["companies"]),
        "industries": sorted(({"name": k, **v} for k, v in by_industry.items()), key=lambda r: -r["companies"]),
        "productSources": sorted(merged.values(), key=lambda s: -s["products"]),
        "verification": verification,
        "origin": origin,
        "addedByDay": [[r["d"].isoformat(), r["n"]] for r in reversed(added)],
        # индекс упорядочен по выручке
        "topRevenue": [card(s) for s in repo.summary[:TOP_N] if s[cat.S_REVENUE] is not None],
        "topProducts": [card(s) for s in sorted((s for s in repo.summary if s[cat.S_PRODUCTS]), key=lambda s: -s[cat.S_PRODUCTS])[:TOP_N]],
    }


def catalog(repo) -> dict:
    with _lock:
        if _cache["revision"] != repo.revision or _cache["data"] is None:
            _cache["data"], _cache["revision"] = compute(repo), repo.revision
        return _cache["data"]


def collection() -> dict:
    """Ход сбора из реестров и обхода сайтов: идёт ли сейчас, итоги последних запусков."""
    with tx("ingest") as g:
        st = ingest.read_status(g)
        runs = g.execute("SELECT id, kind, started_at, finished_at, status, stats, applied FROM crawl_run ORDER BY id DESC LIMIT 5").fetchall()
        running = ingest.lock_active(g)
    keep = ("state", "stage", "done", "total", "found", "existing", "new", "added", "trigger", "started_at", "last_run", "last_started_at")
    return {"sync": {k: st.get(k) for k in keep} | {"running": running},
            "crawl": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in runs]}
