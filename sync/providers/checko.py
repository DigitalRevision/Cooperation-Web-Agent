"""Checko API (api.checko.ru) — необязательный платный источник, включается ключом PK_CHECKO_KEY.

Даёт то, чего нет в открытых сервисах ФНС и Федресурса без капчи:
  /v2/company      — НедобПост (реестр недобросовестных поставщиков), ДисквЛица, Санкции, Налоги.СумНедоим;
  /v2/legal-cases  — арбитражные дела, где компания ответчик: ЗапВсего, ОбщСуммИск;
  /v2/enforcements — исполнительные производства ФССП: Записи[].ОстЗадолж.
Имена полей взяты из документации checko.ru/integration/api. Без ключа модуль не вызывается.
"""
from __future__ import annotations
from datetime import date, timedelta

from ..http import Http, SourceError
from .. import config

URL = "https://api.checko.ru/v2"
TITLE = "Checko: арбитражные дела, ФССП, РНП (api.checko.ru)"


def enabled() -> bool:
    return bool(config.CHECKO_KEY)


def _get(http: Http, method: str, **params) -> dict:
    res = http.json("GET", f"{URL}/{method}", params={"key": config.CHECKO_KEY, **params})
    if (res.get("meta") or {}).get("status") != "ok":
        raise SourceError(f"api.checko.ru: {(res.get('meta') or {}).get('message') or 'ошибка'}")
    return res.get("data") or {}


def fetch(http: Http, inn: str, today: date | None = None) -> dict:
    since = ((today or date.today()) - timedelta(days=3 * 365)).isoformat()
    comp = _get(http, "company", inn=inn)
    cases = _get(http, "legal-cases", inn=inn, role="defendant", date_from=since, limit=1)
    enf = _get(http, "enforcements", inn=inn, limit=100)
    return parse(comp, cases, enf)


def parse(comp: dict, cases: dict, enf: dict) -> dict:
    recs = enf.get("Записи") or []
    return {
        "unfair_supplier": bool(comp.get("НедобПост")), "disqualified": bool(comp.get("ДисквЛица")),
        "sanctions": bool(comp.get("Санкции")), "tax_arrears": (comp.get("Налоги") or {}).get("СумНедоим"),
        "cases_defendant": cases.get("ЗапВсего") or 0, "cases_claims_sum": cases.get("ОбщСуммИск") or 0,
        "enforcements": len(recs), "enforcements_debt": sum(float(r.get("ОстЗадолж") or 0) for r in recs),
    }
