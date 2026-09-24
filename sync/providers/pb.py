"""«Прозрачный бизнес» ФНС (pb.nalog.ru): юридические и налоговые признаки риска, все коды ОКВЭД, адрес.

Поиск: search-proc.json (mode=search-ul) → id запроса → get-response со строками и токеном компании.
Карточка: company-proc.json (get-request → get-response). В карточке:
  vyp.sulst_ex / sulst_name_ex — статус (10 — действующая, 30 — процесс банкротства и т. д.),
  vyp.НаимСтатусЮЛ / ДатаСтатусЮЛ — стадия (ликвидация, конкурсное производство) и её дата,
  vyp.invalid — недостоверность сведений в ЕГРЮЛ, vyp.pr_zd — задолженность по налогам свыше 1000 руб.,
  vyp.pr_otch — не сдаёт налоговую отчётность больше года, vyp.totalarrearsum — сумма недоимки и пеней,
  masaddress — другие юрлица по тому же адресу, vyp.masruk[].cnt — у скольких юрлиц тот же руководитель,
  sschr — среднесписочная численность, taxpay — уплаченные налоги, form1 — выручка и расходы,
  okved2exs — все коды ОКВЭД, vyp.bourl — карточка организации в ГИР БО.
"""
from __future__ import annotations
import re
import time

from ..http import Http, SourceError
from .util import iso_date

URL = "https://pb.nalog.ru/"
TITLE = "Прозрачный бизнес ФНС России (pb.nalog.ru)"
REF = {"Referer": URL}


def _poll(http: Http, path: str, data: dict, key: str) -> dict:
    for _ in range(8):
        r = http.json("POST", URL + path, data=data, headers=REF)
        if not isinstance(r, dict):   # пока запрос обрабатывается, сервис может вернуть null
            time.sleep(1)
            continue
        if key in r:
            return r
        if r.get("captchaRequired"):
            raise SourceError("pb.nalog.ru: требуется капча")
        time.sleep(1)
    raise SourceError("pb.nalog.ru: ответ не готов")


def fetch(http: Http, inn: str) -> dict | None:
    s = http.json("POST", URL + "search-proc.json", data={"mode": "search-ul", "queryUl": inn, "page": 1, "pageSize": 10}, headers=REF)
    if s.get("captchaRequired"):
        raise SourceError("pb.nalog.ru: требуется капча")
    res = _poll(http, "search-proc.json", {"id": s["id"], "method": "get-response"}, "ul")
    rows = [x for x in res["ul"].get("data", []) if x.get("inn") == inn]
    if not rows:
        return None
    q = http.json("POST", URL + "company-proc.json", data={"token": rows[0]["token"], "method": "get-request"}, headers=REF)
    if q.get("captchaRequired"):
        raise SourceError("pb.nalog.ru: требуется капча")
    card = _poll(http, "company-proc.json", {"token": q["token"], "id": q["id"], "method": "get-response"}, "vyp")
    return parse(card)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _latest(items: list[dict] | None, field: str):
    rows = [x for x in items or [] if not x.get("empty") and x.get(field) is not None]
    if not rows:
        return None, None
    y = max(int(x["yearcode"]) for x in rows)
    return y, sum(float(x[field]) for x in rows if int(x["yearcode"]) == y)


def parse(card: dict) -> dict:
    v = card.get("vyp") or {}
    okved = []
    for s in card.get("okved2exs") or []:
        m = re.match(r"\s*([\d.]+)\s*-\s*(.+)", s)
        if m:
            okved.append((m[1], m[2].strip()))
    # основной код в списке всех кодов встречается не всегда
    if v.get("КодОКВЭД") and v["КодОКВЭД"] not in {c for c, _ in okved}:
        okved.insert(0, (v["КодОКВЭД"], v.get("НаимОКВЭД") or ""))
    head = (v.get("masruk") or [{}])[0]
    heads_cnt = int(head.get("cnt") or 0)
    hc_year, headcount = _latest(card.get("sschr"), "sschr")
    tax_year, taxes = _latest(card.get("taxpay"), "taxsum")
    rev_year, revenue = _latest(card.get("form1"), "revenue")
    arrears = _num(v.get("totalarrearsum"))
    arrear_rows = [x for x in card.get("arrear") or [] if not x.get("empty")]
    msp = {1: "микропредприятие", 2: "малое предприятие", 3: "среднее предприятие"}.get(int(_num(v.get("rsmpcategory")) or 0))
    return {
        "inn": v.get("ИНН"), "ogrn": v.get("ОГРН"), "kpp": v.get("КПП"),
        "legal_name": v.get("НаимЮЛПолн"), "short_name": v.get("НаимЮЛСокр"),
        "reg_date": iso_date(v.get("ДатаРег") or v.get("ДатаОГРН")),
        "status_code_fns": int(_num(v.get("sulst_ex")) or 0), "status_text": v.get("sulst_name_ex"),
        "stage_text": v.get("НаимСтатусЮЛ"), "stage_date": iso_date(v.get("ДатаСтатусЮЛ")),
        "liquidated": bool(card.get("liquidated")),
        "invalid": bool(_num(v.get("invalid"))), "tax_debt_flag": bool(_num(v.get("pr_zd"))),
        "no_reports": bool(_num(v.get("pr_otch"))),
        "arrears": arrears if arrears else (sum(float(x.get("totalsum") or 0) for x in arrear_rows) or None),
        "arrears_period": f"{int(arrear_rows[0]['periodcode']):02d}.{int(arrear_rows[0]['yearcode'])}" if arrear_rows else None,
        "mass_address": len(card.get("masaddress") or []),
        "head": {"name": head.get("name"), "position": head.get("position"), "companies": heads_cnt} if head else None,
        "mass_head": bool(v.get("masrukinvalid")) or heads_cnt >= 10,
        "headcount": headcount, "headcount_year": hc_year,
        "taxes_paid": taxes, "taxes_year": tax_year,
        "revenue_rub": revenue, "revenue_year": rev_year,
        "capital": _num(v.get("СумКап")), "msp": msp,
        "tax_mode": ", ".join(n for k, n in (("usn", "УСН"), ("eshn", "ЕСХН"), ("envd", "ЕНВД"), ("spr", "СРП"), ("ausn", "АУСН")) if _num(v.get(k))) or "ОСНО",
        "okved_main": v.get("КодОКВЭД"), "okved_main_name": v.get("НаимОКВЭД"), "okved_all": okved,
        "address": v.get("АдресРФ"), "region_code": v.get("КодРегион"),
        "city": (v.get("НаимГород") or re.sub(r"^[А-ЯЁ.]+\s", "", v.get("НаселенПункт") or "") or None),
        "girbo_id": (re.search(r"organizations-card/(\d+)", v.get("bourl") or "") or [None, None])[1],
        "vestnik": len(card.get("vestnik") or []),   # сообщения в «Вестнике государственной регистрации»
        "extract_date": iso_date(v.get("ДатаВып")),
    }
