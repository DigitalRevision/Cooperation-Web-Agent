"""Реестр российской промышленной продукции Минпромторга (ПП РФ № 719), открытые данные minpromtorg.gov.ru.

Продукция, производство которой на территории России подтверждено (акт экспертизы ТПП, заключение Минпромторга):
производитель (ИНН, ОГРН), наименование продукции, коды ОКПД2 и ТН ВЭД, технические условия или ГОСТ, реестровый номер,
срок действия записи. Это тот же реестр, что на gisp.gov.ru (там закрыт защитой от ботов), но опубликованный открытыми
данными — CSV около 420 МБ, обновляется ежедневно.

Файл скачивается в sync/.cache/opendata/minpromtorg не чаще раза в PK_SYNC_MPT_DAYS дней (по умолчанию 7); обрыв —
докачка с места обрыва, размер сверяется с заголовком сервера. Из файла берутся записи по ИНН предприятий базы,
только действующие: не исключённые из реестра (Enddate) и со сроком действия не раньше сегодняшнего дня.
"""
from __future__ import annotations
import csv
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from ..http import Http, SourceError
from . import opendata

DS = "1000000012-ReestrProducts"
META = f"https://minpromtorg.gov.ru/opendata/{DS}/meta.csv"
TITLE = "Реестр российской промышленной продукции Минпромторга России (ПП РФ № 719)"
URL = "https://gisp.gov.ru/pp719v2/pub/prod/"          # публичный поиск по реестру: реестровый номер записи есть у каждой позиции
CACHE = opendata.CACHE / "minpromtorg"
MAX_AGE_DAYS = int(os.environ.get("PK_SYNC_MPT_DAYS", "7"))
FIELDS = ("INN", "Registernumber", "Productname", "OKPD2", "TNVED", "Nameofregulations", "Docdate", "Docvalidtill", "Enddate",
          "Docname", "Docdatebasis", "Score", "Percentage", "Mptdep")


def latest(http: Http) -> tuple[str, str]:
    """(дата ГГГГММДД, адрес) самого свежего файла данных из паспорта набора."""
    text = http.request("GET", META).text
    found = re.findall(rf"data-(\d{{8}})-structure-\d+,(https://minpromtorg\.gov\.ru/opendata/{DS}/data-\d{{8}}-structure-\d+\.csv)", text)
    if not found:
        raise SourceError("minpromtorg.gov.ru: в паспорте набора не найден файл данных")
    return max(found)


def _day(path: Path) -> date | None:
    m = re.search(r"(\d{8})", path.name)
    return date(int(m[1][:4]), int(m[1][4:6]), int(m[1][6:])) if m else None


def ensure(http: Http, today: date, cache: Path = CACHE, max_age_days: int = MAX_AGE_DAYS) -> Path:
    """Файл реестра: свежий из кеша (не старше max_age_days) или скачанный заново."""
    cache.mkdir(parents=True, exist_ok=True)
    have = sorted(cache.glob("reestr-products-*.csv"))
    if have and (_day(have[-1]) or date.min) >= today - timedelta(days=max_age_days):
        return have[-1]
    day, url = latest(http)
    path = cache / f"reestr-products-{day}.csv"
    if path.exists():
        return path
    tmp = path.with_suffix(".part")
    total = 0
    for attempt in range(6):
        size = tmp.stat().st_size if tmp.exists() else 0
        try:
            with http.client.stream("GET", url, headers={"Range": f"bytes={size}-"} if size else {}, timeout=900) as r:
                if r.status_code == 416:
                    break
                if r.status_code not in (200, 206):
                    raise SourceError(f"minpromtorg.gov.ru: HTTP {r.status_code}")
                total = int(r.headers.get("content-range", "/0").rsplit("/", 1)[1] or 0) if r.status_code == 206 else int(r.headers.get("content-length") or 0)
                with open(tmp, "ab" if r.status_code == 206 else "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            if not total or tmp.stat().st_size >= total:
                break
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            if attempt == 5:
                raise SourceError(f"minpromtorg.gov.ru: загрузка прервана: {e}")
            time.sleep(5 * (attempt + 1))
    if total and tmp.stat().st_size != total:
        raise SourceError(f"minpromtorg.gov.ru: файл скачан не полностью ({tmp.stat().st_size} из {total} байт)")
    tmp.replace(path)
    for old in cache.glob("reestr-products-*.csv"):
        if old != path:
            old.unlink()
    return path


def _clean(v: str | None) -> str | None:
    v = re.sub(r"\s+", " ", (v or "")).strip()
    return None if v in ("", "-") else v


def scan(path: Path, inns: set[str], today: date) -> tuple[str | None, dict[str, list[dict]]]:
    """ИНН → действующие записи реестра (не исключены, срок действия не истёк)."""
    csv.field_size_limit(10 ** 7)
    out: dict[str, list[dict]] = {}
    day = today.isoformat()
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            inn = (row.get("INN") or "").strip()
            if inn not in inns:
                continue
            rec = {k: _clean(row.get(k)) for k in FIELDS}
            if rec["Enddate"] or (rec["Docvalidtill"] and rec["Docvalidtill"] < day) or not rec["Productname"] or not rec["Registernumber"]:
                continue
            out.setdefault(inn, []).append(rec)
    d = _day(path)
    return (d.isoformat() if d else None), out


def load(http: Http, inns: set[str], today: date, log=print) -> dict:
    t = time.monotonic()
    path = ensure(http, today)
    as_of, recs = scan(path, inns, today)
    log(f"реестр промышленной продукции на {as_of}: {sum(map(len, recs.values()))} действующих записей у {len(recs)} из {len(inns)} предприятий, "
        f"{time.monotonic() - t:.0f} с")
    return {"file": path.name, "as_of": as_of, "records": recs}
