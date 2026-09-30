"""Каталог предприятий для API: читается из базы sm01_catalog; в памяти сервера — «ядро» каталога.

Подбор поставщиков сравнивает запрос с каждой карточкой, поэтому карточки с продукцией и сайтами удобнее держать
в памяти процесса API. По всей стране в базе больше 150 тысяч компаний, заведённых быстрым добавлением (origin
registry_fast) без продукции и сайта: в памяти их нет (pkdb.catalog.CORE_SQL), список, поиск, статистику и полную карточку
любой компании API читает из базы. Позиции реестра Минпромторга в памяти компактные (RegistryProduct), полностью —
в карточке из базы. Когда сбор записал новые данные, ревизия каталога растёт — API замечает это не позже чем через
PK_REVISION_TTL секунд и перечитывает каталог. Поверх данных сбора накладываются решения модератора из sm01_moderation:
ручной статус проверки и отключённые источники.
"""
from __future__ import annotations
import gc
import math
import os
import threading
import time

from pkdb import connect
from pkdb import catalog as cat

REVISION_TTL = float(os.environ.get("PK_REVISION_TTL", "5"))
CHUNK = 2000
_ORDER = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 1, "UNVERIFIED": 2, "OUTDATED": 3}


def _active(s: tuple) -> bool:
    return s[cat.S_STATUS] != "OUTDATED" and (s[cat.S_STATE] or "ACTIVE") == "ACTIVE"


class DataRepo:
    def __init__(self):
        self.revision: int | None = None
        self.companies: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        self.reload()

    def reload(self):
        # прежний каталог отпускается до чтения нового: иначе на время перечитывания в памяти оба
        self.companies, self.products, self.sources = {}, {}, {}
        gc.collect()
        companies, products, sources = {}, {}, {}
        try:
            with connect("catalog") as c:
                rev = cat.revision(c)
                core = cat.core_ids(c)
                for i in range(0, len(core), CHUNK):   # порциями: строки запросов по всему ядру сразу заняли бы сотни мегабайт
                    comps, prods, srcs = cat.load_companies(c, core[i:i + CHUNK], compact_registry=True)
                    for cid, co in comps.items():
                        co.pop("history", None)   # история изменений — только в полной карточке из базы (full)
                        co["products"], co["sources"] = prods[cid], srcs[cid]
                        companies[cid] = co
                        for p in co["products"]:
                            products[p["id"]] = p
                        for s in co["sources"]:
                            sources[s["id"]] = {**s, "company_id": cid}
                    del comps, prods, srcs
                dic = cat.load_dictionaries(c)
                summary = cat.load_summary(c)
                counts = c.execute("SELECT (SELECT count(*) FROM product) AS products, (SELECT count(*) FROM source) AS sources").fetchone()
        except Exception:
            self.revision = None   # каталог не прочитан: следующий запрос попробует снова
            raise
        self.companies, self.products, self.sources = companies, products, sources
        self.summary = summary
        self.all_ids = {s[cat.S_ID] for s in summary}
        self.totals = {"companies": len(summary), "active": sum(1 for s in summary if _active(s)),
                       "regions": len({s[cat.S_REGION] for s in summary if s[cat.S_REGION]}),
                       "with_site": sum(1 for s in summary if s[cat.S_SITE]), "with_products": sum(1 for s in summary if s[cat.S_PRODUCTS]),
                       "products": counts["products"], "sources": counts["sources"]}
        self.collected_status = {cid: c["verification_status"] for cid, c in companies.items()}   # статус по данным сбора, без решений модератора
        self.okved, self.okpd2, self.regions = dic["okved"], dic["okpd2"], dic["regions"]
        self.cities = {k: tuple(v) for k, v in dic["cities"].items()}
        self.relations = dic["relations"]
        self.dictionaries = dic
        self.revision = rev
        self.apply_moderation()
        self.checked_at = time.monotonic()

    def apply_moderation(self):
        """Ручные статусы проверки и отключённые источники из базы модерации (поверх данных сбора)."""
        for cid, c in self.companies.items():
            c["verification_status"] = self.collected_status[cid]
        for s in self.sources.values():
            s.pop("is_disabled", None)
        self.overrides, self.disabled_sources = {}, set()
        try:
            with connect("moderation") as m:
                overrides = m.execute("SELECT company_id, status FROM status_override").fetchall()
                flags = m.execute("SELECT source_id, disabled FROM source_flag").fetchall()
        except Exception:
            return   # база модерации недоступна: каталог работает по данным сбора
        for o in overrides:
            self.overrides[o["company_id"]] = o["status"]
            if o["company_id"] in self.companies:
                self.companies[o["company_id"]]["verification_status"] = o["status"]
        for f in flags:
            if f["disabled"]:
                self.disabled_sources.add(f["source_id"])
            if f["source_id"] in self.sources and f["disabled"]:
                self.sources[f["source_id"]]["is_disabled"] = True

    def list_companies(self, *, region=None, industry=None, okved=None, city=None, q=None, statuses=None, sort="revenue",
                       offset=0, limit=20) -> tuple[int, list[dict]]:
        """Страница списка по всему каталогу: фильтры и сортировка — по индексу в памяти, поиск — полнотекстовым индексом
        базы, строки страницы — из базы. Решения модератора о статусе проверки учитываются."""
        S = cat
        ids = None
        with connect("catalog") as c:
            if q and q.strip():
                ids = cat.search_ids(c, q)
            status = lambda s: self.overrides.get(s[S.S_ID]) or s[S.S_STATUS]
            rows = [s for s in self.summary
                    if (ids is None or s[S.S_ID] in ids) and (not region or s[S.S_REGION] == region) and (not industry or s[S.S_INDUSTRY] == industry)
                    and (not city or s[S.S_CITY] == city) and (not okved or (s[S.S_OKVED] or "") == okved or (s[S.S_OKVED] or "").startswith(okved + "."))
                    and (not statuses or status(s) in statuses)]
            key = {"name": lambda s: (s[S.S_NAME] or "").lower(),
                   "region": lambda s: (s[S.S_REGION] or "~", s[S.S_CITY] or "~", (s[S.S_NAME] or "").lower()),
                   "products": lambda s: (-s[S.S_PRODUCTS], -(s[S.S_REVENUE] or 0)),
                   "status": lambda s: (_ORDER.get(status(s), 9), -(s[S.S_REVENUE] or 0))}.get(sort)
            if key:   # по выручке индекс уже упорядочен
                rows.sort(key=key)
            items = cat.company_rows(c, [s[S.S_ID] for s in rows[offset:offset + limit]])
        for it in items:
            it["verification_status"] = self.overrides.get(it["id"]) or it["verification_status"]
        return len(rows), items

    def exists(self, cid: str | None) -> bool:
        """Предприятие есть в каталоге (в памяти или только в базе)."""
        return bool(cid) and (cid in self.companies or cid in self.all_ids)

    def full(self, cid: str) -> dict | None:
        """Полная карточка из базы: все источники, история изменений, отчётность, продукция с описанием и характеристиками.
        verification_status — по данным сбора (решения модератора сайт накладывает сам)."""
        if not self.exists(cid):
            return None
        with connect("catalog") as c:
            comps, prods, srcs = cat.load_companies(c, [cid])
        if cid not in comps:
            return None
        co = comps[cid]
        co["products"] = prods[cid]
        co["sources"] = [{**s, "is_disabled": True} if s["id"] in self.disabled_sources else s for s in srcs[cid]]
        return co

    def source(self, sid: str) -> dict | None:
        if sid in self.sources:
            return self.sources[sid]
        with connect("catalog") as c:
            r = c.execute("SELECT company_id FROM source WHERE id = %s", (sid,)).fetchone()
        co = self.full(r["company_id"]) if r else None
        s = next((s for s in (co or {}).get("sources") or [] if s["id"] == sid), None)
        return {**s, "company_id": co["id"]} if s else None

    def product(self, pid: str) -> dict | None:
        """Позиция целиком: из карточки в памяти или (позиции реестра Минпромторга, компактные в памяти) из базы."""
        p = self.products.get(pid)
        if p is None or isinstance(p, dict):
            return p
        co = self.full(p["company_id"])
        return next((x for x in (co or {}).get("products") or [] if x["id"] == pid), None)

    def distance_km(self, a: str | None, b: str | None) -> int | None:
        if a not in self.cities or b not in self.cities:
            return None
        (la1, lo1), (la2, lo2) = self.cities[a], self.cities[b]
        r = math.radians
        h = math.sin(r(la2 - la1) / 2) ** 2 + math.cos(r(la1)) * math.cos(r(la2)) * math.sin(r(lo2 - lo1) / 2) ** 2
        return round(2 * 6371 * math.asin(math.sqrt(h)))


_repo: DataRepo | None = None
_lock = threading.Lock()


def get_repo() -> DataRepo:
    """Каталог; перечитывается, когда сбор записал новую ревизию (проверка не чаще раза в PK_REVISION_TTL секунд)."""
    global _repo
    with _lock:
        if _repo is None:
            _repo = DataRepo()
        elif time.monotonic() - _repo.checked_at > REVISION_TTL:
            with connect("catalog") as c:
                rev = cat.revision(c)
            if rev != _repo.revision:
                _repo.reload()
            else:
                _repo.checked_at = time.monotonic()
        return _repo


def drop_cache() -> None:
    """Сбросить каталог в памяти (тесты, смена базы)."""
    global _repo
    with _lock:
        _repo = None
