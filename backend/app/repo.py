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
import logging
import math
import os
import threading
import time

import psycopg

from pkdb import catalog as cat
from pkdb import connect
from sync.business_data import merge_financial_activities, summarize_financial_activities

REVISION_TTL = float(os.environ.get("PK_REVISION_TTL", "5"))
CHUNK = 2000
_ORDER = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 1, "UNVERIFIED": 2, "OUTDATED": 3}
SummaryRow = tuple
logger = logging.getLogger(__name__)


def _company_status(row: SummaryRow, overrides: dict[str, str]) -> str:
    """Вернуть актуальный статус предприятия с учетом решения модератора."""
    return overrides.get(row[cat.S_ID]) or row[cat.S_STATUS]


def _matches_company(
    row: SummaryRow,
    *,
    ids: set[str] | None,
    region: str | None,
    industry: str | None,
    okved: str | None,
    city: str | None,
    statuses: set[str] | None,
    overrides: dict[str, str],
) -> bool:
    """Проверить строку компактного индекса по фильтрам каталога."""
    code = row[cat.S_OKVED] or ""
    return (
        (ids is None or row[cat.S_ID] in ids)
        and (not region or row[cat.S_REGION] == region)
        and (not industry or row[cat.S_INDUSTRY] == industry)
        and (not city or row[cat.S_CITY] == city)
        and (not okved or code == okved or code.startswith(okved + "."))
        and (not statuses or _company_status(row, overrides) in statuses)
    )


def _company_sort_key(sort: str, overrides: dict[str, str]):
    """Сформировать ключ сортировки; None сохраняет исходный порядок по выручке."""

    def status(row: SummaryRow) -> str:
        return _company_status(row, overrides)

    return {
        "name": lambda row: (row[cat.S_NAME] or "").lower(),
        "region": lambda row: (
            row[cat.S_REGION] or "~",
            row[cat.S_CITY] or "~",
            (row[cat.S_NAME] or "").lower(),
        ),
        "products": lambda row: (-row[cat.S_PRODUCTS], -(row[cat.S_REVENUE] or 0)),
        "status": lambda row: (_ORDER.get(status(row), 9), -(row[cat.S_REVENUE] or 0)),
    }.get(sort)


def _active(s: tuple) -> bool:
    return s[cat.S_STATUS] != "OUTDATED" and (s[cat.S_STATE] or "ACTIVE") == "ACTIVE"


def _read_catalog() -> tuple[
    int, dict[str, dict], dict[str, dict], dict[str, dict], dict, list, dict
]:
    """Загрузить снимок каталога из БД, освобождая память порциями.

    Returns:
        tuple: ревизия, карточки предприятий, продукции, источников, справочники,
            индекс списка и агрегированные количества.
    """
    companies: dict[str, dict] = {}
    products: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    with connect("catalog") as connection:
        revision = cat.revision(connection)
        core_ids = cat.core_ids(connection)
        for start in range(0, len(core_ids), CHUNK):
            # Порционная загрузка не удерживает в памяти промежуточные строки всей базы.
            chunk_companies, chunk_products, chunk_sources = cat.load_companies(
                connection, core_ids[start : start + CHUNK], compact_registry=True
            )
            for company_id, company in chunk_companies.items():
                company.pop("history", None)
                company["products"] = chunk_products[company_id]
                company["sources"] = chunk_sources[company_id]
                companies[company_id] = company
                products.update({product["id"]: product for product in company["products"]})
                sources.update(
                    {
                        source["id"]: {**source, "company_id": company_id}
                        for source in company["sources"]
                    }
                )
        dictionaries = cat.load_dictionaries(connection)
        summary = cat.load_summary(connection)
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM product) AS products, "
            "(SELECT count(*) FROM source) AS sources"
        ).fetchone()
    return revision, companies, products, sources, dictionaries, summary, counts


class DataRepo:
    def __init__(self):
        self.revision: int | None = None
        self.financial_revision: int = 0
        self.financial_claims: dict[str, list[dict]] = {}
        self.companies: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        """Заменить кэш согласованным снимком и повторно применить решения модерации."""
        # прежний каталог отпускается до чтения нового: иначе на время перечитывания в памяти оба
        self.companies, self.products, self.sources = {}, {}, {}
        gc.collect()
        try:
            rev, companies, products, sources, dictionaries, summary, counts = _read_catalog()
        except Exception:
            self.revision = None  # каталог не прочитан: следующий запрос попробует снова
            raise
        self._replace_snapshot(rev, companies, products, sources, dictionaries, summary, counts)

    def _replace_snapshot(
        self, rev, companies, products, sources, dictionaries, summary, counts
    ) -> None:
        """Опубликовать загруженный снимок и подготовить индексы для чтения API."""
        self.companies, self.products, self.sources = companies, products, sources
        self.summary = summary
        self.all_ids = {s[cat.S_ID] for s in summary}
        self.totals = {
            "companies": len(summary),
            "active": sum(1 for s in summary if _active(s)),
            "regions": len({s[cat.S_REGION] for s in summary if s[cat.S_REGION]}),
            "with_site": sum(1 for s in summary if s[cat.S_SITE]),
            "with_products": sum(1 for s in summary if s[cat.S_PRODUCTS]),
            "products": counts["products"],
            "sources": counts["sources"],
        }
        self.collected_status = {
            cid: c["verification_status"] for cid, c in companies.items()
        }  # статус по данным сбора, без решений модератора
        self.okved, self.okpd2, self.regions = (
            dictionaries["okved"],
            dictionaries["okpd2"],
            dictionaries["regions"],
        )
        self.cities = {k: tuple(v) for k, v in dictionaries["cities"].items()}
        self.dictionaries = dictionaries
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
        self.financial_claims = {}
        try:
            with connect("moderation") as m:
                overrides = m.execute("SELECT company_id, status FROM status_override").fetchall()
                flags = m.execute("SELECT source_id, disabled FROM source_flag").fetchall()
                claim_revision = m.execute(
                    "SELECT COALESCE(max((extract(epoch FROM updated_at) * 1000000)::bigint), 0) AS revision FROM financial_submission"
                ).fetchone()["revision"]
                claims = m.execute(
                    "SELECT id, company_id, report_year, scope, document_url, activities, status, submitted_at, updated_at "
                    "FROM financial_submission WHERE status IN ('PENDING','APPROVED') ORDER BY submitted_at"
                ).fetchall()
        except psycopg.Error:
            logger.warning(
                "База модерации недоступна; каталог временно работает без решений модератора",
                exc_info=True,
            )
            return
        self.financial_revision = int(claim_revision or 0)
        for o in overrides:
            self.overrides[o["company_id"]] = o["status"]
            if o["company_id"] in self.companies:
                self.companies[o["company_id"]]["verification_status"] = o["status"]
        for f in flags:
            if f["disabled"]:
                self.disabled_sources.add(f["source_id"])
            if f["source_id"] in self.sources and f["disabled"]:
                self.sources[f["source_id"]]["is_disabled"] = True
        for claim in claims:
            rows = claim["activities"] or []
            total = sum(float(x.get("revenue") or 0) for x in rows)
            leader = max(rows, key=lambda x: float(x.get("revenue") or 0), default=None)
            unique_leader = (
                bool(leader)
                and sum(
                    float(x.get("revenue") or 0) == float(leader.get("revenue") or 0) for x in rows
                )
                == 1
            )
            status = "CONFIRMED" if claim["status"] == "APPROVED" else "DECLARED"
            for index, activity in enumerate(rows):
                share = activity.get("share")
                if share is None and total:
                    share = round(float(activity.get("revenue") or 0) / total * 100, 4)
                self.financial_claims.setdefault(claim["company_id"], []).append(
                    {
                        "id": f"company-claim:{claim['id']}:{index}",
                        "report_id": f"company-claim:{claim['id']}",
                        "okved_code": activity.get("okved_code"),
                        "activity_name": activity["activity_name"],
                        "revenue": float(activity["revenue"]),
                        "share": share,
                        "currency": "RUB",
                        "report_year": claim["report_year"],
                        "scope": claim["scope"],
                        "source_url": claim["document_url"],
                        "source_title": "Документ, предоставленный предприятием",
                        "source_id": f"company-claim:{claim['id']}",
                        "status": status,
                        "method": "COMPANY_DOCUMENT_REVIEW"
                        if status == "CONFIRMED"
                        else "COMPANY_DECLARATION",
                        "source_priority": 3 if status == "CONFIRMED" else 2,
                        "is_leading": bool(unique_leader and leader is activity),
                        "updated_at": claim["updated_at"].isoformat(),
                    }
                )
        for company_id, company in self.companies.items():
            self._overlay_financial_claims(company_id, company)

    def _overlay_financial_claims(self, company_id: str, company: dict) -> None:
        incoming = self.financial_claims.get(company_id) or []
        if not incoming:
            return
        registry = company.setdefault("registry", {})
        combined = merge_financial_activities(registry.get("financial_activities"), incoming)
        registry["financial_activities"] = combined
        registry["leading_financial_activity"] = summarize_financial_activities(combined)

    def list_companies(
        self,
        *,
        region=None,
        industry=None,
        okved=None,
        city=None,
        q=None,
        statuses=None,
        sort="revenue",
        offset=0,
        limit=20,
    ) -> tuple[int, list[dict]]:
        """Страница списка по всему каталогу: фильтры и сортировка — по индексу в памяти, поиск — полнотекстовым индексом
        базы, строки страницы — из базы. Решения модератора о статусе проверки учитываются."""
        S = cat
        ids = None
        with connect("catalog") as c:
            if q and q.strip():
                ids = cat.search_ids(c, q)
            rows = [
                row
                for row in self.summary
                if _matches_company(
                    row,
                    ids=ids,
                    region=region,
                    industry=industry,
                    okved=okved,
                    city=city,
                    statuses=statuses,
                    overrides=self.overrides,
                )
            ]
            key = _company_sort_key(sort, self.overrides)
            if key:  # по выручке индекс уже упорядочен
                rows.sort(key=key)
            items = cat.company_rows(c, [s[S.S_ID] for s in rows[offset : offset + limit]])
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
        self._overlay_financial_claims(cid, co)
        co["products"] = prods[cid]
        co["sources"] = [
            {**s, "is_disabled": True} if s["id"] in self.disabled_sources else s for s in srcs[cid]
        ]
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
        h = (
            math.sin(r(la2 - la1) / 2) ** 2
            + math.cos(r(la1)) * math.cos(r(la2)) * math.sin(r(lo2 - lo1) / 2) ** 2
        )
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
            try:
                with connect("moderation") as m:
                    fin_rev = m.execute(
                        "SELECT COALESCE(max((extract(epoch FROM updated_at) * 1000000)::bigint), 0) AS revision FROM financial_submission"
                    ).fetchone()["revision"]
            except psycopg.Error:
                logger.debug("Не удалось прочитать ревизию финансовых заявок", exc_info=True)
                fin_rev = _repo.financial_revision
            if rev != _repo.revision or int(fin_rev or 0) != _repo.financial_revision:
                _repo.reload()
            else:
                _repo.checked_at = time.monotonic()
        return _repo


def drop_cache() -> None:
    """Сбросить каталог в памяти (тесты, смена базы)."""
    global _repo
    with _lock:
        _repo = None
