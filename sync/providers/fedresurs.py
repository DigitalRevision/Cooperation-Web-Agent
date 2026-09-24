"""Федресурс и ЕФРСБ (fedresurs.ru): банкротство.

/backend/companies?searchString=ИНН → guid, текстовый статус, признак активности, адрес по ЕГРЮЛ.
/backend/companies/{guid}/bankruptcy → дела о банкротстве (номер, стадия) и намерения кредиторов обратиться в суд.
"""
from __future__ import annotations
from datetime import date, timedelta

from ..http import Http
from .util import iso_date

URL = "https://fedresurs.ru"
TITLE = "Федресурс и ЕФРСБ (fedresurs.ru)"
# Стадии дела, при которых компания находится в процедуре банкротства
ACTIVE_STAGES = {"Observation": "наблюдение", "Tender": "конкурсное производство", "ExternalManagement": "внешнее управление",
                 "FinancialRecovery": "финансовое оздоровление", "Restructuring": "реструктуризация долгов"}


def fetch(http: Http, inn: str) -> dict | None:
    h = {"Referer": f"{URL}/search/entity?code={inn}"}
    res = http.json("GET", f"{URL}/backend/companies", params={"searchString": inn, "limit": 5, "offset": 0}, headers=h)
    rows = [x for x in res.get("pageData", []) if x.get("inn") == inn]
    if not rows:
        return None
    row = rows[0]
    bk = http.json("GET", f"{URL}/backend/companies/{row['guid']}/bankruptcy", headers={"Referer": f"{URL}/companies/{row['guid']}"})
    return parse(row, bk)


def parse(row: dict, bk: dict | None, today: date | None = None) -> dict:
    today = today or date.today()
    cases = []
    for c in (bk or {}).get("legalCases") or []:
        st = c.get("status") or {}
        pubs = c.get("lastPublications") or []
        cases.append({"number": c.get("number"), "stage_code": st.get("code"), "stage": st.get("name"),
                      "last_publication": iso_date(pubs[0].get("datePublish")) if pubs else None,
                      "last_publication_type": pubs[0].get("typeName") if pubs else None})
    year_ago = (today - timedelta(days=365)).isoformat()
    intents = [{"date": iso_date(x.get("datePublish")), "type": x.get("typeName")} for x in (bk or {}).get("intentionMessages") or []]
    active = [c for c in cases if c["stage_code"] in ACTIVE_STAGES]
    return {
        "guid": row.get("guid"), "url": f"{URL}/companies/{row.get('guid')}",
        "status_text": row.get("status"), "is_active": row.get("isActive"), "address": row.get("egrulAddress"),
        "bankrupt": bool(active) or "банкрот" in (row.get("status") or "").lower(),
        "cases": cases, "active_case": active[0] if active else None,
        "intents_recent": [x for x in intents if (x["date"] or "") >= year_ago],
    }
