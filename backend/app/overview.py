"""Статистика для раздела «Статистика» на сайте: предприятия и продукция по регионам и отраслям, источники, ход сбора.

Считается по каталогу в памяти API один раз на ревизию каталога (по всей стране — сотни тысяч карточек); состояние
сбора и краулера читается из sm01_ingest при каждом запросе.
"""
from __future__ import annotations
import threading
from collections import Counter

from pkdb import ingest, tx

# тип источника позиции продукции → подпись на сайте; остальные — «Первичный сбор и другие источники»
PRODUCT_SOURCES = {"MPT_REESTR": "Реестр промышленной продукции Минпромторга", "OFFICIAL_SITE": "Официальные сайты предприятий",
                   "FNS_RMSP": "Реестр МСП ФНС"}
OTHER_SOURCE = "Первичный сбор и другие источники"
TOP_N = 20

_lock = threading.Lock()
_cache: dict = {"revision": None, "data": None}


def _revenue(c: dict) -> float | None:
    fin = ((c.get("registry") or {}).get("finance") or [None])[0] or {}
    return fin.get("revenue")


def _active(c: dict) -> bool:
    return c.get("verification_status") != "OUTDATED" and (c.get("status_code") or "ACTIVE") == "ACTIVE"


def _row() -> dict:
    return {"companies": 0, "active": 0, "withProducts": 0, "products": 0, "withSite": 0, "revenueK": 0, "headcount": 0}


def compute(repo) -> dict:
    regions = {k: v.get("name") for k, v in (repo.regions or {}).items()}
    by_region: dict[str, dict] = {}
    by_industry: dict[str, dict] = {}
    src_products: Counter = Counter()
    src_companies: dict[str, set] = {}
    status, origin, added = Counter(), Counter(), Counter()
    total = _row()
    tops = []
    for cid, c in repo.companies.items():
        prods = c.get("products") or []
        rev, hc = _revenue(c), (c.get("registry") or {}).get("headcount")
        rows = (total, by_region.setdefault(c.get("region") or "—", _row()), by_industry.setdefault(c.get("industry") or "Не указано", _row()))
        for r in rows:
            r["companies"] += 1
            r["active"] += _active(c)
            r["withProducts"] += bool(prods)
            r["products"] += len(prods)
            r["withSite"] += bool(c.get("site"))
            r["revenueK"] += rev or 0
            r["headcount"] += hc or 0
        status[c.get("verification_status") or "—"] += 1
        origin[c.get("origin") or "seed"] += 1
        if c.get("added_at"):
            added[c["added_at"][:10]] += 1
        for p in prods:
            label = PRODUCT_SOURCES.get((repo.sources.get(p.get("source_id")) or {}).get("source_type"), OTHER_SOURCE)
            src_products[label] += 1
            src_companies.setdefault(label, set()).add(cid)
        tops.append((rev or 0, len(prods), cid))
    card = lambda cid: {"id": cid, "name": repo.companies[cid].get("short") or repo.companies[cid]["name"],
                        "region": regions.get(repo.companies[cid].get("region"), repo.companies[cid].get("region")),
                        "industry": repo.companies[cid].get("industry"), "revenueK": _revenue(repo.companies[cid]),
                        "products": len(repo.companies[cid].get("products") or [])}
    return {
        "revision": repo.revision,
        "totals": dict(total, regions=len([k for k in by_region if k != "—"])),
        "regions": sorted(({"code": k, "name": regions.get(k, k), **v} for k, v in by_region.items()), key=lambda r: -r["companies"]),
        "industries": sorted(({"name": k, **v} for k, v in by_industry.items()), key=lambda r: -r["companies"]),
        "productSources": [{"name": k, "products": n, "companies": len(src_companies[k])} for k, n in src_products.most_common()],
        "verification": dict(status),
        "origin": dict(origin),
        "addedByDay": sorted(added.items())[-14:],
        "topRevenue": [card(cid) for _, _, cid in sorted(tops, key=lambda t: -t[0])[:TOP_N]],
        "topProducts": [card(cid) for _, _, cid in sorted(tops, key=lambda t: -t[1])[:TOP_N] if repo.companies[cid].get("products")],
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
