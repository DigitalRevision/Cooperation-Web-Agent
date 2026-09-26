"""Каталог для браузера: облегчённые карточки всех предприятий одним сжатым ответом.

Раньше сайт при каждом открытии скачивал data.json на 18 МБ: полные карточки со всеми источниками, историей изменений
и отчётностью. Спискам, фильтрам и подбору поставщиков это не нужно. Облегчённая карточка содержит то, что нужно
спискам и подбору; полная карточка (все источники, история, отчётность, налоги) загружается при открытии
предприятия — GET /api/v1/companies/{id}.

Ответ сжат gzip заранее и отдаётся с ETag по ревизии каталога и последнему запуску сбора: пока база не менялась,
повторный заход получает 304 без тела.
"""
from __future__ import annotations
import gzip
import json
import threading
from datetime import date

from pkdb import tx
from pkdb import ingest

# Формат облегчённой карточки (разворачивает сайт, site/src/01-core.js, expandLight):
#   rs  — источники реестров строкой «egrul,girbo,fedresurs!FAILED» (id записи — <id предприятия>-<ключ>, статус OK по умолчанию);
#         только если у предприятия нет других источников, иначе — список sources из id, типа и результата обхода;
#   rk  — сигналы риска парами [код, уровень] (название — из общего словаря risk_titles, если совпадает);
#   sc  — дата последней сверки с реестрами;
#   subindustry опускается, если совпадает с названием основного ОКВЭД; отчётность, история, налоги — только в полной карточке.
LIGHT_DROP = ("history", "registry", "sync", "sources", "risk_signals", "_light")
REG_SRC = {"egrul": "FNS_EGRUL", "pb": "FNS_PB", "girbo": "FNS_GIRBO", "fedresurs": "EFRSB", "opendata": "FNS_OPENDATA", "checko": "CHECKO"}


def _registry_sources(c: dict) -> str | None:
    parts = []
    for s in c.get("sources") or []:
        key = s["id"][len(c["id"]) + 1:] if s["id"].startswith(c["id"] + "-") else None
        if REG_SRC.get(key) != s["source_type"]:
            return None
        st = s.get("fetch_status") or "OK"
        parts.append(key if st == "OK" else f"{key}!{st}")
    return ",".join(parts)


def light_company(c: dict, collected_status: str, okved: dict, risk_titles: dict) -> dict:
    out = {k: v for k, v in c.items() if k not in LIGHT_DROP and v not in (None, [], {}, "")}
    out["verification_status"] = collected_status   # решения модератора сайт накладывает сам (коллекция overrides)
    if not c.get("subindustry"):
        out["subindustry"] = None                   # явно: иначе сайт подставит название ОКВЭД
    elif okved.get(c.get("okved_main")) == c["subindustry"]:
        del out["subindustry"]
    rs = _registry_sources(c)
    if rs is not None:
        out["rs"] = rs
    else:
        # адрес — только у официальных сайтов: текст риска «сайт не прочитан»
        out["sources"] = [{"id": s["id"], "source_type": s["source_type"], "fetch_status": s.get("fetch_status"),
                           **({"source_url": s["source_url"]} if s["source_type"] == "OFFICIAL_SITE" else {})} for s in c.get("sources") or []]
    rk = [[x["code"], x["level"]] + ([x["title"]] if risk_titles.get(x["code"]) != x["title"] else []) for x in c.get("risk_signals") or []]
    if rk:
        out["rk"] = rk
    sc = (c.get("sync") or {}).get("checked_at")
    if sc:
        out["sc"] = sc
    out["products"] = [{k: v for k, v in p.items() if v not in (None, [], {}) and k != "company_id"} for p in c.get("products") or []]
    if not out["products"]:
        del out["products"]
    out["_light"] = 1
    return out


def _risk_titles(companies) -> dict:
    """Самое частое название сигнала для каждого кода."""
    from collections import Counter
    cnt = Counter((x["code"], x["title"]) for c in companies for x in c.get("risk_signals") or [])
    out = {}
    for (code, title), _ in cnt.most_common():
        out.setdefault(code, title)
    return out


def _order_key(c: dict):
    # сначала предприятия первичного сбора, затем добавленные сбором из реестров — в порядке добавления
    return (c.get("origin") == "registry_sync", c.get("added_at") or "", c["id"])


def build(repo) -> dict:
    with tx("ingest") as g:
        last = ingest.read_run(g, changes_limit=200, with_errors=False)
        crawl = ingest.read_crawl_log(g)
    companies = sorted(repo.companies.values(), key=_order_key)
    titles = _risk_titles(companies)
    b = {"generated_at": date.today().isoformat(), "revision": repo.revision, "format": 2, "risk_titles": titles,
         "companies": [light_company(c, repo.collected_status[c["id"]], repo.okved, titles) for c in companies],
         "okved": repo.okved, "okpd2": repo.okpd2, "regions": repo.regions,
         "cities": {k: list(v) for k, v in repo.cities.items()}, "relations": repo.relations, "crawl_log": crawl}
    if last:
        b["sync"] = last
    return b


_cache: dict = {}
_lock = threading.Lock()


def etag_of(repo) -> str:
    with tx("ingest") as g:
        r = g.execute("SELECT max(id) AS run, (SELECT count(*) FROM crawl_log) AS crawl FROM sync_run").fetchone()
    return 'W/"cat-%s-%s-%s"' % (repo.revision, r["run"] or 0, r["crawl"] or 0)


def get(repo) -> tuple[str, bytes, int]:
    """(ETag, тело gzip, размер без сжатия). Собирается один раз на ревизию каталога."""
    tag = etag_of(repo)
    with _lock:
        if _cache.get("etag") != tag:
            raw = json.dumps(build(repo), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _cache.update(etag=tag, gz=gzip.compress(raw, compresslevel=6), raw_size=len(raw), raw=raw)
        return _cache["etag"], _cache["gz"], _cache["raw_size"]


def raw_body() -> bytes:
    return _cache.get("raw", b"")


def reset() -> None:
    with _lock:
        _cache.clear()
