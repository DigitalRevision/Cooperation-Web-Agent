"""ГИР БО ФНС (bo.nalog.gov.ru): поиск промышленных компаний и бухгалтерская отчётность.

Поиск: /advanced-search/organizations?okved=25&address=Волгоградская&page=0&size=100. Фильтр адреса текстовый,
поэтому в выдачу попадают и компании других регионов с этим словом в адресе: отбираем по полю region.
Карточка: /nbo/organizations/{id} — основной ОКВЭД с названием.
Отчётность: /nbo/organizations/{id}/bfo/ — по годам, суммы в тысячах рублей.
Строки: 2110 выручка, 2400 чистая прибыль, 1600 активы, 1300 капитал и резервы, 1400 и 1500 обязательства.
Часть оборонных и подсанкционных предприятий вправе не раскрывать отчётность: тогда данных нет, это не риск.
"""
from __future__ import annotations
from typing import Iterator

from ..http import Http
from .util import strip_tags

URL = "https://bo.nalog.gov.ru"
TITLE = "ГИР БО ФНС России (bo.nalog.gov.ru)"
# statusCode в ГИР БО → статус в базе
STATUS = {"ACTIVE": "ACTIVE", "INACTIVE": "LIQUIDATED", "LIQUIDATION_STAGE": "LIQUIDATING",
          "REORGANIZATION_STAGE": "REORGANIZING", "BANKRUPTCY_STAGE": "BANKRUPTCY"}


def discover(http: Http, okved: str, region: dict, page_size: int = 100, max_pages: int = 100) -> Iterator[dict]:
    """Все организации класса ОКВЭД в регионе (по основному ОКВЭД), по страницам."""
    for page in range(max_pages):
        res = http.json("GET", f"{URL}/advanced-search/organizations",
                        params={"okved": okved, "address": region["query"], "page": page, "size": page_size})
        for row in res.get("content", []):
            if strip_tags(row.get("region")) == region["girbo"]:
                yield parse_row(row)
        if res.get("last", True):
            break


def parse_row(row: dict) -> dict:
    bfo = row.get("bfo") or {}
    return {"girbo_id": str(row["id"]), "inn": row.get("inn"), "ogrn": row.get("ogrn"),
            "short_name": strip_tags(row.get("shortName")), "okved_main": strip_tags(row.get("okved2")),
            "status": STATUS.get(row.get("statusCode"), row.get("statusCode")), "status_date": row.get("statusDate"),
            "city": strip_tags(row.get("city")) or strip_tags(row.get("settlement")) or None,
            "revenue_k": bfo.get("gainSum"), "period": bfo.get("period")}


def find_id(http: Http, inn: str) -> str | None:
    res = http.json("GET", f"{URL}/advanced-search/organizations", params={"inn": inn, "page": 0, "size": 5})
    for row in res.get("content", []):
        if row.get("inn") == inn:
            return str(row["id"])
    return None


def fetch(http: Http, inn: str, girbo_id: str | None = None) -> dict | None:
    gid = girbo_id or find_id(http, inn)
    if not gid:
        return None
    card = http.json("GET", f"{URL}/nbo/organizations/{gid}")
    reports = http.json("GET", f"{URL}/nbo/organizations/{gid}/bfo/")
    okved = card.get("okved2") or {}
    return {"girbo_id": gid, "url": f"{URL}/organizations-card/{gid}", "years": parse_bfo(reports), "okpo": parse_okpo(reports),
            "okved_main": okved.get("id"), "okved_main_name": okved.get("name")}


def parse_okpo(reports: list[dict]) -> str | None:
    for r in sorted(reports or [], key=lambda r: r.get("period") or "", reverse=True):
        okpo = (r.get("organizationInfo") or {}).get("okpo")
        if okpo:
            return okpo
    return None


def parse_bfo(reports: list[dict]) -> list[dict]:
    years = []
    for r in reports or []:
        if not r.get("period"):
            continue
        tc = next((t for t in r.get("typeCorrections") or [] if t.get("type") == 12), None) or (r.get("typeCorrections") or [None])[0]
        corr = (tc or {}).get("correction") or {}
        bal, fin = corr.get("balance") or {}, corr.get("financialResult") or {}
        val = lambda d, code: d.get(f"current{code}")
        years.append({"year": int(r["period"]), "revenue": val(fin, 2110), "net_profit": val(fin, 2400),
                      "assets": val(bal, 1600), "equity": val(bal, 1300),
                      "liabilities": sum(x for x in (val(bal, 1400), val(bal, 1500)) if x) if bal else None})
    return sorted(years, key=lambda y: y["year"], reverse=True)
