"""Открытые данные ФНС (nalog.gov.ru/opendata): массовые наборы без капчи, обновляются раз в месяц.

  debtam   — недоимка, пени и штрафы по налогам и взносам (в наборе только должники: нет записи — нет долга);
  sshr2019 — среднесписочная численность работников за год;
  paytax   — уплаченные налоги и взносы за год;
  snr      — специальные налоговые режимы (УСН, ЕСХН, АУСН, СРП): нет записи — общая система.

Архив скачивается в Trash/opendata, только если на странице набора появился новый файл.
Из архива выбираются записи по ИНН компаний базы и кандидатов, остальное не хранится.
"""
from __future__ import annotations
import re
import time
import zipfile
from pathlib import Path

import httpx

from ..http import Http, SourceError
from .util import iso_date

PAGE = "https://www.nalog.gov.ru/opendata/7707329152-{}/"
DATASETS = {"debtam": "задолженность по налогам", "sshr2019": "среднесписочная численность",
            "paytax": "уплаченные налоги", "snr": "специальные налоговые режимы"}
TITLE = "Открытые данные ФНС России (nalog.gov.ru/opendata)"
CACHE = Path(__file__).resolve().parents[2] / "Trash" / "opendata"   # Trash — кеш и служебные файлы, можно очищать целиком
ATTR = re.compile(r'(\w+)="([^"]*)"')
CHUNK = 32_000_000   # перекачка повреждённых участков кусками: сбой в одном куске не портит соседние


def latest_url(http: Http, ds: str) -> str:
    html = http.request("GET", PAGE.format(ds)).text
    # на странице набора бывают и архивы со схемой (XSD): нужен архив данных data-<дата>-structure-<дата>.zip
    m = re.search(r'https://file\.nalog\.ru/opendata/[^"]+?/data-[^"/]+?\.zip', html) or re.search(r'https://file\.nalog\.ru/opendata/[^"]+?\.zip', html)
    if not m:
        raise SourceError(f"nalog.gov.ru: не найден архив набора {ds}")
    return m[0]


def ensure(http: Http, ds: str, cache: Path = CACHE) -> Path:
    """Архив набора в кеше; скачивается, только если опубликован новый файл. Обрыв соединения — докачка с места обрыва."""
    url = latest_url(http, ds)
    d = cache / ds
    path = d / url.rsplit("/", 1)[1]
    if path.exists():
        return path
    d.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    for attempt in range(6):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with http.client.stream("GET", url, headers=headers, timeout=600) as r:
                if r.status_code == 416:                       # уже скачано целиком
                    break
                if r.status_code not in (200, 206):
                    raise SourceError(f"file.nalog.ru: HTTP {r.status_code} для {ds}")
                total = int(r.headers.get("content-range", "/0").rsplit("/", 1)[1] or 0) if r.status_code == 206 else int(r.headers.get("content-length") or 0)
                with open(tmp, "ab" if r.status_code == 206 else "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            if not total or tmp.stat().st_size >= total:
                break
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            if attempt == 5:
                raise SourceError(f"file.nalog.ru: загрузка {ds} прервана: {e}")
            time.sleep(5 * (attempt + 1))
    # поток с file.nalog.ru бывает испорчен без обрыва соединения: проверяем архив и перекачиваем испорченное кусками по 32 МБ
    for _ in range(4):
        bad = verify_zip(tmp)
        if not bad:
            break
        patch_ranges(http, url, tmp, [(x, min(x + CHUNK - 1, b)) for a, b in bad for x in range(a, b + 1, CHUNK)])
    else:
        if verify_zip(tmp):
            raise SourceError(f"file.nalog.ru: архив {ds} повреждён при загрузке и не восстановился докачкой")
    tmp.replace(path)
    for old in d.glob("*.zip"):
        if old != path:
            old.unlink()
    return path


def verify_zip(path: Path) -> list[tuple[int, int]]:
    """Диапазоны байтов, где заголовки файлов архива не на своих местах (повреждение при загрузке). Пусто — архив цел."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return [(0, path.stat().st_size - 1)]
    infos = sorted(z.infolist(), key=lambda i: i.header_offset)
    cd_start = z.start_dir
    bad, out = [], []
    with open(path, "rb") as f:
        for i in infos:
            f.seek(i.header_offset)
            bad.append(f.read(4) != b"PK\x03\x04")
    k = 0
    while k < len(infos):
        if not bad[k]:
            k += 1
            continue
        a = infos[k - 1].header_offset if k else 0          # повреждение могло начаться в данных предыдущего файла
        while k < len(infos) and bad[k]:
            k += 1
        b = infos[k].header_offset - 1 if k < len(infos) else cd_start - 1
        out.append((a, b))
    return out


def member_range(z: zipfile.ZipFile, name: str) -> tuple[int, int]:
    """Байты файла архива вместе с его заголовком — для перекачки файла с неверной контрольной суммой."""
    infos = sorted(z.infolist(), key=lambda i: i.header_offset)
    i = next(k for k, x in enumerate(infos) if x.filename == name)
    end = infos[i + 1].header_offset - 1 if i + 1 < len(infos) else z.start_dir - 1
    return infos[i].header_offset, end


def patch_ranges(http: Http, url: str, path: Path, ranges: list[tuple[int, int]]) -> None:
    """Перекачать диапазоны байтов (HTTP Range) и записать поверх; обрыв — продолжение с места обрыва."""
    with open(path, "r+b") as f:
        for a, b in ranges:
            pos, tries = a, 0
            while pos <= b:
                try:
                    with http.client.stream("GET", url, headers={"Range": f"bytes={pos}-{b}"}, timeout=600) as r:
                        if r.status_code != 206:
                            raise SourceError(f"file.nalog.ru: докачка диапазона не поддерживается (HTTP {r.status_code})")
                        f.seek(pos)
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                            pos += len(chunk)
                except (httpx.TransportError, httpx.RemoteProtocolError):
                    tries += 1
                    if tries > 8:
                        raise SourceError("file.nalog.ru: не удалось перекачать повреждённый участок архива")
                    time.sleep(5 * tries)


def scan(zip_path: Path, inns: set[str]) -> tuple[str | None, dict[str, dict]]:
    """Записи набора по нужным ИНН: ИНН → {date, rows: [атрибуты элементов, кроме СведНП]}."""
    out: dict[str, dict] = {}
    as_of = None
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            text = z.read(name).decode("utf-8", "replace")
            for doc in text.split("<Документ ")[1:]:
                i = doc.find('ИННЮЛ="')
                if i < 0:
                    continue
                inn = doc[i + 7:doc.find('"', i + 7)]
                if inn not in inns:
                    continue
                head = dict(ATTR.findall(doc[:doc.find(">")]))
                as_of = as_of or head.get("ДатаСост")
                rows = [dict(ATTR.findall(attrs)) for _, attrs in re.findall(r"<(?!СведНП)(\w+) ([^>]*)/>", doc)]
                rec = out.setdefault(inn, {"date": iso_date(head.get("ДатаСост")), "rows": []})
                rec["rows"] += rows
            if as_of is None:
                m = re.search(r'ДатаСост="([\d.]+)"', text)
                as_of = m[1] if m else None
    return iso_date(as_of), out


def load(http: Http, inns: set[str], log=print, cache: Path = CACHE) -> tuple[dict, dict]:
    """Скачивает (при необходимости) и разбирает все наборы. Возвращает (данные по наборам, ошибки)."""
    data, errors = {}, {}
    for ds in DATASETS:
        t = time.monotonic()
        try:
            path = ensure(http, ds, cache)
            as_of, recs = scan(path, inns)
            data[ds] = {"file": path.name, "as_of": as_of, "records": recs}
            log(f"открытые данные ФНС: {DATASETS[ds]} на {as_of}, найдено {len(recs)} из {len(inns)} ИНН, {time.monotonic() - t:.0f} с")
        except (SourceError, OSError, zipfile.BadZipFile) as e:
            errors[ds] = str(e)
    return data, errors


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def lookup(od: dict, inn: str) -> dict | None:
    """Показатели компании из загруженных наборов. None — ни один набор не загружен."""
    if not od:
        return None
    out = {}
    if "debtam" in od:
        rec = od["debtam"]["records"].get(inn)
        out["arrears"] = sum(_f(r.get("ОбщСумНедоим")) for r in rec["rows"]) if rec else 0.0
        out["arrears_date"] = (rec or {}).get("date") or od["debtam"]["as_of"]
        out["arrears_items"] = [{"tax": r.get("НаимНалог"), "sum": _f(r.get("ОбщСумНедоим"))}
                                for r in (rec or {}).get("rows", []) if _f(r.get("ОбщСумНедоим"))]
    if "sshr2019" in od and inn in od["sshr2019"]["records"]:
        rec = od["sshr2019"]["records"][inn]
        out["headcount"] = int(_f(next((r.get("КолРаб") for r in rec["rows"] if "КолРаб" in r), 0)))
        out["headcount_year"] = int(rec["date"][:4]) if rec.get("date") else None
    if "paytax" in od and inn in od["paytax"]["records"]:
        rec = od["paytax"]["records"][inn]
        out["taxes_paid"] = sum(_f(r.get("СумУплНал")) for r in rec["rows"])
        out["taxes_year"] = int(rec["date"][:4]) if rec.get("date") else None
    if "snr" in od:
        rec = od["snr"]["records"].get(inn)
        flags = {k[5:]: v for r in (rec or {}).get("rows", []) for k, v in r.items() if k.startswith("Призн")}
        out["tax_mode"] = ", ".join(k for k, v in flags.items() if v == "1") or "ОСНО"
    return out
