"""Единый реестр субъектов МСП ФНС (открытые данные, набор rsmp): сведения о производимой продукции.

Малые и средние предприятия сами указывают в реестре продукцию, которую производят: код ОКПД2 и наименование
(элемент СвПрод; признак ПрОтнПрод — продукция инновационная или высокотехнологичная). Это официальный источник по ИНН,
он покрывает предприятия без сайта. Крупные предприятия в реестр МСП не входят.

Архив (около 2 ГБ, раз в месяц) скачивается в Trash/opendata/rsmp, только если опубликован новый файл.
Документы ищутся по байтам без разбора всего XML; результат по ИНН базы кешируется рядом с архивом (rsmp.<файл>.json):
повторный запуск на том же архиве просматривает его заново, только если в базе появились новые ИНН.

Тем же проходом собираются названия кодов ОКПД2 из всех документов реестра: предприятие выбирает код из классификатора,
реестр хранит его официальное название. Ими пополняется справочник ОКПД2 платформы (у кодов реестра Минпромторга названий нет).
"""
from __future__ import annotations
import html
import json
import re
import time
import zipfile
import zlib
from collections import Counter
from pathlib import Path

from ..http import Http, SourceError
from . import opendata
from .util import iso_date

DS = "rsmp"
TITLE = "Единый реестр субъектов МСП ФНС России: сведения о производимой продукции"
URL = "https://rmsp.nalog.ru/"
ATTR = re.compile(r'([\w.]+)="([^"]*)"')
CATEGORY = {"1": "микропредприятие", "2": "малое предприятие", "3": "среднее предприятие"}


def clean_name(name: str | None) -> str:
    """Наименование продукции без пояснения классификатора: реестр обрезает текст до ~100 знаков вместе с началом
    «Эта группировка включает …»."""
    name = re.split(r"\s+Эта (?:группировка|подгруппа)", name or "")[0]
    return re.sub(r"\s+", " ", name).strip()


def _encoding(head: bytes) -> str:
    m = re.search(rb'encoding="([^"]+)"', head[:200])
    return m[1].decode("ascii").lower() if m else "utf-8"


def scan(zip_path: Path, inns: set[str], log=print, names: list[str] | None = None,
         okpd2: dict[str, Counter] | None = None) -> tuple[str | None, dict[str, dict], list[str]]:
    """ИНН → {date, category, products: [{code, name, innovative}]} для предприятий, указавших продукцию.
    Третье значение — файлы архива, которые не прочитались (повреждены при загрузке): их перекачивает load().
    okpd2 — если передан, в него собираются названия кодов ОКПД2 из всех документов: код → Counter(название)."""
    out: dict[str, dict] = {}
    bad: list[str] = []
    as_of = None
    t = time.monotonic()
    with zipfile.ZipFile(zip_path) as z:
        names = names or z.namelist()
        for n, name in enumerate(names, 1):
            try:
                data = z.read(name)
            except (zlib.error, zipfile.BadZipFile, EOFError):
                bad.append(name)
                continue
            enc = _encoding(data)
            if okpd2 is not None:
                tag = "<СвПрод ".encode(enc)
                i = data.find(tag)
                while i >= 0:
                    j = data.find(b">", i)
                    a = dict(ATTR.findall(data[i:j].decode(enc, "replace")))
                    code, pname = (a.get("КодПрод") or "").strip(), clean_name(html.unescape(a.get("НаимПрод") or ""))
                    if code and pname:
                        okpd2.setdefault(code, Counter())[pname] += 1
                    i = data.find(tag, j)
            key, open_tag, close_tag = 'ИННЮЛ="'.encode(enc), "<Документ ".encode(enc), "</Документ>".encode(enc)
            pos = 0
            while True:
                i = data.find(key, pos)
                if i < 0:
                    break
                j = data.find(b'"', i + len(key))
                inn = data[i + len(key):j].decode("ascii", "replace")
                pos = j
                if inn not in inns:
                    continue
                start, end = data.rfind(open_tag, 0, i), data.find(close_tag, i)
                if start < 0 or end < 0:
                    continue
                doc = data[start:end].decode(enc, "replace")
                pos = end
                head = dict(ATTR.findall(doc[:doc.find(">")]))
                as_of = as_of or head.get("ДатаСост")
                prods = []
                for attrs in re.findall(r"<СвПрод ([^>]*?)/?>", doc):
                    a = dict(ATTR.findall(attrs))
                    if a.get("КодПрод") or a.get("НаимПрод"):
                        prods.append({"code": a.get("КодПрод"), "name": html.unescape(a.get("НаимПрод") or "").strip(),   # как в реестре; чистит merge
                                      "innovative": a.get("ПрОтнПрод") == "1"})
                if prods:
                    out[inn] = {"date": iso_date(head.get("ДатаСост")), "category": CATEGORY.get(head.get("КатСубМСП")), "products": prods}
            if n % 200 == 0:
                log(f"  реестр МСП: просмотрено {n} из {len(names)} файлов, найдено {len(out)}, {time.monotonic() - t:.0f} с")
    return iso_date(as_of), out, bad


def load(http: Http, inns: set[str], log=print, cache: Path = opendata.CACHE) -> dict:
    """Продукция предприятий из реестра МСП по ИНН. {file, as_of, records: {ИНН: …}, okpd2: {код: название}};
    SourceError — набор недоступен."""
    path = opendata.ensure(http, DS, cache)
    cpath = path.with_name(f"rsmp.{path.stem}.json")
    cached = None
    if cpath.exists():
        try:
            cached = json.loads(cpath.read_text(encoding="utf-8"))
        except ValueError:
            cached = None
    if cached and set(cached.get("scanned") or []) >= inns and "okpd2" in cached:
        return {"file": path.name, "as_of": cached["as_of"], "records": {k: v for k, v in cached["records"].items() if k in inns},
                "okpd2": cached["okpd2"]}
    t = time.monotonic()
    names: dict[str, Counter] = {}
    try:
        as_of, recs, bad = scan(path, inns, log, okpd2=names)
        if bad:   # файлы архива с неверной контрольной суммой: перекачать их байты и прочитать заново
            log(f"реестр МСП: {len(bad)} файлов архива повреждены при загрузке, перекачиваю")
            with zipfile.ZipFile(path) as z:
                ranges = [opendata.member_range(z, n) for n in bad]
            opendata.patch_ranges(http, opendata.latest_url(http, DS), path, ranges)
            as_of2, recs2, bad = scan(path, inns, log, names=bad, okpd2=names)
            recs.update(recs2)
            as_of = as_of or as_of2
            if bad:
                raise SourceError(f"реестр МСП: {len(bad)} файлов архива не читаются даже после перекачки")
    except zipfile.BadZipFile as e:
        raise SourceError(f"реестр МСП: повреждён архив {path.name}: {e}")
    okpd2 = {k: v.most_common(1)[0][0] for k, v in sorted(names.items())}
    tmp = cpath.with_suffix(".tmp")
    tmp.write_text(json.dumps({"as_of": as_of, "scanned": sorted(inns), "records": recs, "okpd2": okpd2}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cpath)
    for old in path.parent.glob("rsmp.*.json"):
        if old != cpath:
            old.unlink()
    log(f"реестр МСП на {as_of}: продукцию указали {len(recs)} из {len(inns)} предприятий, названий кодов ОКПД2: {len(okpd2)}, "
        f"{time.monotonic() - t:.0f} с")
    return {"file": path.name, "as_of": as_of, "records": recs, "okpd2": okpd2}
