"""ЕГРЮЛ ФНС (egrul.nalog.ru): статус юрлица, реквизиты, дата прекращения деятельности.

Поиск в два шага: POST / с ИНН возвращает токен, GET /search-result/{токен} возвращает строки.
Поля строки: n — полное наименование, c — краткое, i — ИНН, o — ОГРН, p — КПП, r — дата регистрации,
e — дата прекращения деятельности (ликвидация, реорганизация), g — руководитель, rn — регион.
Банкротство в поиске ЕГРЮЛ не отображается, его даёт Федресурс.
"""
from __future__ import annotations
import time

from ..http import Http, SourceError
from .util import iso_date

URL = "https://egrul.nalog.ru/"
TITLE = "ЕГРЮЛ ФНС России (egrul.nalog.ru)"


def fetch(http: Http, inn: str) -> dict | None:
    t = http.json("POST", URL, data={"query": inn, "nameEq": "on", "region": "", "PreventChromeAutocomplete": ""},
                  headers={"Referer": URL, "X-Requested-With": "XMLHttpRequest"})
    if t.get("captchaRequired"):
        raise SourceError("egrul.nalog.ru: требуется капча")
    for _ in range(5):
        res = http.json("GET", f"{URL}search-result/{t['t']}", headers={"Referer": URL, "X-Requested-With": "XMLHttpRequest"})
        if "rows" in res:
            return parse(res["rows"], inn)
        time.sleep(1)
    raise SourceError("egrul.nalog.ru: результат поиска не готов")


def parse(rows: list[dict], inn: str) -> dict | None:
    rows = [r for r in rows if r.get("i") == inn]
    if not rows:
        return None
    # у одного ИНН может быть несколько записей (например, после реорганизации): действующая важнее
    row = sorted(rows, key=lambda r: (bool(r.get("e")), r.get("r", "")))[0]
    return {
        "legal_name": row.get("n"), "short_name": row.get("c"), "inn": row.get("i"), "ogrn": row.get("o"),
        "kpp": row.get("p"), "reg_date": iso_date(row.get("r")), "end_date": iso_date(row.get("e")),
        "head": row.get("g"), "region_name": row.get("rn"),
    }
