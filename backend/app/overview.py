"""Расчёт публичной статистики по каталогу и состоянию сбора."""

from __future__ import annotations

import threading
from typing import Any

from pkdb import catalog as cat
from pkdb import ingest, tx

from .repo import DataRepo, _active

PRODUCT_SOURCES = {
    "MPT_REESTR": "Реестр промышленной продукции Минпромторга",
    "OFFICIAL_SITE": "Официальные сайты предприятий",
    "FNS_RMSP": "Реестр МСП ФНС",
}
OTHER_SOURCE = "Первичный сбор и другие источники"
TOP_N = 20
_METRIC_KEYS = (
    "companies",
    "active",
    "withProducts",
    "products",
    "withSite",
    "revenueK",
    "headcount",
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"revision": None, "data": None}


def _new_row() -> dict[str, int | float]:
    """Создаёт счётчики для общего итога, региона или отрасли."""
    return dict.fromkeys(_METRIC_KEYS, 0)


def _add_company_metrics(target: dict[str, int | float], summary: tuple[Any, ...]) -> None:
    """Добавляет показатели одной компании в агрегат, не меняя исходную строку индекса."""
    product_count = summary[cat.S_PRODUCTS]
    target["companies"] += 1
    target["active"] += _active(summary)
    target["withProducts"] += product_count > 0
    target["products"] += product_count
    target["withSite"] += summary[cat.S_SITE]
    target["revenueK"] += summary[cat.S_REVENUE] or 0
    target["headcount"] += summary[cat.S_HEADCOUNT] or 0


def _product_source_label(repo: DataRepo, product: dict[str, Any]) -> str:
    """Возвращает публичное название источника для позиции каталога."""
    source = repo.sources.get(product["source_id"]) or {}
    return PRODUCT_SOURCES.get(source.get("source_type"), OTHER_SOURCE)


def _product_source_stats(repo: DataRepo) -> list[dict[str, str | int]]:
    """Считает позиции и предприятия по типу источника, учитывая компанию один раз на тип."""
    merged: dict[str, dict[str, str | int]] = {}
    for company in repo.companies.values():
        products = company["products"]
        for label in {_product_source_label(repo, product) for product in products}:
            merged.setdefault(label, {"name": label, "products": 0, "companies": 0})[
                "companies"
            ] += 1
        for product in products:
            merged[_product_source_label(repo, product)]["products"] += 1
    return sorted(merged.values(), key=lambda source: -source["products"])


def _company_card(summary: tuple[Any, ...], regions: dict[str, str | None]) -> dict[str, Any]:
    """Формирует компактную карточку предприятия для рейтингов статистики."""
    region_code = summary[cat.S_REGION]
    return {
        "id": summary[cat.S_ID],
        "name": summary[cat.S_NAME],
        "region": regions.get(region_code, region_code),
        "industry": summary[cat.S_INDUSTRY],
        "revenueK": summary[cat.S_REVENUE],
        "products": summary[cat.S_PRODUCTS],
    }


def compute(repo: DataRepo) -> dict[str, Any]:
    """Строит статистику по индексу каталога и небольшим выборкам из PostgreSQL.

    Args:
        repo: Согласованный снимок каталога, используемый API.

    Returns:
        Данные регионов, отраслей, источников, проверок, обновлений и верхних рейтингов.
    """
    regions = {code: value.get("name") for code, value in (repo.regions or {}).items()}
    total = _new_row()
    by_region: dict[str, dict[str, int | float]] = {}
    by_industry: dict[str, dict[str, int | float]] = {}
    verification: dict[str, int] = {}
    origin: dict[str, int] = {}

    for summary in repo.summary:
        region = summary[cat.S_REGION] or "—"
        industry = summary[cat.S_INDUSTRY] or "Не указано"
        for aggregate in (
            total,
            by_region.setdefault(region, _new_row()),
            by_industry.setdefault(industry, _new_row()),
        ):
            _add_company_metrics(aggregate, summary)

        status = repo.overrides.get(summary[cat.S_ID]) or summary[cat.S_STATUS]
        verification[status] = verification.get(status, 0) + 1
        source = summary[cat.S_ORIGIN] or "seed"
        origin[source] = origin.get(source, 0) + 1

    with tx("catalog") as connection:
        added = connection.execute(
            "SELECT added_at AS d, count(*) AS n FROM company "
            "WHERE added_at IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 14"
        ).fetchall()

    top_products = sorted(
        (summary for summary in repo.summary if summary[cat.S_PRODUCTS]),
        key=lambda summary: -summary[cat.S_PRODUCTS],
    )[:TOP_N]
    return {
        "revision": repo.revision,
        "totals": dict(total, regions=sum(code != "—" for code in by_region)),
        "regions": sorted(
            (
                {"code": code, "name": regions.get(code, code), **values}
                for code, values in by_region.items()
            ),
            key=lambda row: -row["companies"],
        ),
        "industries": sorted(
            ({"name": name, **values} for name, values in by_industry.items()),
            key=lambda row: -row["companies"],
        ),
        "productSources": _product_source_stats(repo),
        "verification": verification,
        "origin": origin,
        "addedByDay": [[row["d"].isoformat(), row["n"]] for row in reversed(added)],
        # Индекс упорядочен по выручке; строки без подтверждённой выручки не входят в рейтинг.
        "topRevenue": [
            _company_card(summary, regions)
            for summary in repo.summary[:TOP_N]
            if summary[cat.S_REVENUE] is not None
        ],
        "topProducts": [_company_card(summary, regions) for summary in top_products],
    }


def catalog(repo: DataRepo) -> dict[str, Any]:
    """Возвращает статистику каталога из кэша, пересчитывая её при смене ревизии."""
    with _lock:
        if _cache["revision"] != repo.revision or _cache["data"] is None:
            _cache["data"] = compute(repo)
            _cache["revision"] = repo.revision
        return _cache["data"]


def collection() -> dict[str, Any]:
    """Возвращает актуальное состояние синхронизации и последних обходов сайтов."""
    with tx("ingest") as connection:
        state = ingest.read_status(connection)
        runs = connection.execute(
            "SELECT id, kind, started_at, finished_at, status, stats, applied "
            "FROM crawl_run ORDER BY id DESC LIMIT 5"
        ).fetchall()
        last_sync = ingest.read_run(connection, changes_limit=0, with_errors=False)
        running = ingest.lock_active(connection)

    kept_keys = (
        "state",
        "stage",
        "done",
        "total",
        "found",
        "existing",
        "new",
        "added",
        "trigger",
        "started_at",
        "last_run",
        "last_started_at",
    )
    crawl_runs = [
        {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items()
        }
        for row in runs
    ]
    return {
        "sync": {key: state.get(key) for key in kept_keys} | {"running": running},
        "last_sync": last_sync,
        "crawl": crawl_runs,
    }
