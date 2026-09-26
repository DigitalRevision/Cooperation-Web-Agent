"""Позиции продукции с официальных сайтов по результатам обхода краулером (sm01_ingest.crawl_page).

Два шага: кандидаты выносятся на проверку, в каталог попадают только одобренные.

  python tools/crawl_products.py review [--out review.json] [--companies ko,kzbi] [--since 7]
      кандидаты: пункты меню каталога и карточки продукции, заголовки страниц разделов, позиции на страницах услуг.
      Отсеиваются навигация, новости, кнопки («Подробнее», «Скачать»), ссылки-фильтры на ту же страницу.
      Каждому кандидату — решение accept/reject/review с причиной; уже известные позиции сопоставляются по названию.
  python tools/crawl_products.py apply review.json
      одобренные (accept) позиции записываются в sm01_catalog: источник — страница официального сайта, где позиция
      опубликована; код ОКПД2 — только класс по словарю, со статусом INFERRED («присвоено, требует подтверждения»).
      У известных позиций, найденных на сайте, обновляется дата проверки; у источников сайта — результат обхода.

Принцип платформы: ничего не дополняется «по памяти». Название позиции — дословно со страницы, у позиции — ссылка
на страницу-источник; характеристики — только из таблиц этой страницы.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from pkdb import connect  # noqa: E402
from sync import merge  # noqa: E402
from sync.store import Store, slug  # noqa: E402

CATALOG_PATH = re.compile(r"produk|product|katalog|catalog|izdeli|uslug|servic|oborud|equipment|goods|tovar|nomenklat|assortiment|production|proizvodstv", re.I)
SERVICE_PATH = re.compile(r"uslug|servic|servis", re.I)
NOISE_PATH = re.compile(r"/(news|novosti|press|article|stati|blog|event|sobyti|vakans|vacanc|career|kariera|about|o-kompanii|o_kompanii|company/?$|"
                        r"kontakt|contact|smi|media|foto|photo|video|gallery|galereya|partner|otzyv|review|dokument|document|licenz|sertifik|"
                        r"certific|history|istoriya|zakupk|tender|purchase|expert-form|feedback|order|zakaz|politika|privacy|sitemap)", re.I)
STOP = {"главная", "перейти", "подробнее", "читать", "читать далее", "далее", "назад", "еще", "ещё", "показать еще", "показать ещё", "смотреть",
        "смотреть все", "все", "вся продукция", "все услуги", "все товары", "каталог", "каталог продукции", "продукция", "наша продукция",
        "услуги", "наши услуги", "о компании", "о предприятии", "контакты", "новости", "вакансии", "отзывы", "партнеры", "партнёры",
        "документы", "сертификаты", "наличие на складе", "склад свободной реализации", "заказать", "оставить заявку", "отправить заявку",
        "купить", "в корзину", "цена", "цены", "прайс", "прайс-лист", "фото", "видео", "галерея", "карта сайта", "производство",
        "непрофильная продукция", "основная продукция", "запросить цену", "узнать цену", "получить консультацию", "обратная связь",
        "задать вопрос", "развернуть", "свернуть", "меню", "поиск", "english", "eng", "rus", "en", "ru", "каталоги", "техническая документация",
        "опросный лист", "опросные листы", "скачать опросный лист", "закупки", "тендеры", "продажа неликвидов", "социальные сети"}
START_JUNK = re.compile(r"^(c|с)качать|^читать|^подробн|^перейти|^смотреть|^узнать|^заказать|^оставить|^отправить|^получить|^задать|^показать|^вернуться|^©", re.I)
TEXT_JUNK = re.compile(r"@|https?:|www\.|\+7|\b8 ?\(\d{3,4}\)|\d{2}\.\d{2}\.\d{4}|©|\?$|взял[аи]? |отметил|поздравля|юбиле|состоял|прош[её]л|"
                       r"награ|выставк|конференц|форум|вакансия|политика|cookie|персональн", re.I)
SERVICE_WORDS = re.compile(r"^(услуг|ремонт|изготовлен|обработк|механообработ|механическ\w* обработ|резк|раскрой|сварк|термообработ|термическ|"
                           r"испытани|монтаж|проектир|покраск|окраск|гибк|токарн|фрезерн|шлифов|штамповк|литьё|литье|ковк|нанесени|цинкован|"
                           r"гальван|сборк|наладк|пусконалад|диагностик|модерниз|техническ\w* обслуж|инжинир|консалт|перевозк|доставк|аренд)", re.I)


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'().,:;/\\\-–—№+]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set[str]:
    """Основы значимых слов: первые 4 буквы (грубо, но хватает, чтобы «насосы» = «насосов», «кран» = «краны»)."""
    return {t[:4] for t in norm(s).split() if len(t) > 2 and t not in {"для", "производство", "продукция", "изготовление", "услуги", "работы"}}


def similar(a: str, b: str) -> bool:
    """То же название: совпадают основы слов (с точностью до окончаний и порядка)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return norm(a) == norm(b)
    return len(ta & tb) / len(ta | tb) >= 0.75


def broader(general: str, specific: str) -> bool:
    """general — более общее название той же позиции: все его слова есть в specific («Консольные краны» ⊂ «Кран консольный настенный»)."""
    tg, ts = tokens(general), tokens(specific)
    return len(tg) >= 1 and tg < ts


def canon(url: str) -> str:
    u = urlparse(url)
    path = re.sub(r"/index\.(php|html?)$", "/", u.path).rstrip("/") or "/"
    return f"{u.netloc.lower().removeprefix('www.')}{path}" + (f"?{u.query}" if u.query else "")


def tidy(name: str) -> str:
    """Оформление названия без изменения смысла: пробелы, регистр заголовков капсом, пометка «(Цена по запросу)»."""
    name = re.sub(r"\s*\((цена по запросу|под заказ|в наличии)\)\s*$", "", re.sub(r"\s+", " ", name or "").strip(" .,:;"), flags=re.I)
    letters = [ch for ch in name if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.8 and len(name.split()) >= 4:
        name = name[:1].upper() + name[1:].lower()
    return name


def short_title(h1: str, limit: int = 110) -> str:
    """Заголовок длиннее limit: часть до « - » («Станция управления HMS Control G - автоматика для …») или до последней запятой."""
    if len(h1) <= limit:
        return h1
    for sep in (" - ", " – ", " — "):
        head = h1.split(sep)[0].strip()
        if 10 <= len(head) <= limit and head != h1:
            return head
    cut = h1[:limit].rsplit(",", 1)[0].strip()
    return cut if len(cut) >= 20 else h1


def crumb_path(crumbs: list[str]) -> list[str]:
    """Хлебные крошки без выпадающих меню: в Битрикс-шаблонах группы разделены «-», настоящий пункт — первый в группе."""
    if "-" not in crumbs:
        return crumbs
    out, group = [], []
    for c in crumbs + ["-"]:
        if c == "-":
            if group:
                out.append(group[0])
            group = []
        else:
            group.append(c)
    return out


def junk(name: str) -> str | None:
    n = norm(name)
    if n in STOP:
        return "навигация сайта"
    if len(name) < 4 or len(name) > 120 or len(name.split()) > 16:
        return "не похоже на название позиции (длина)"
    if START_JUNK.search(name.strip()):
        return "кнопка или ссылка действия"
    if TEXT_JUNK.search(name):
        return "контакты, дата, новость или служебный текст"
    if sum(ch.isdigit() for ch in name) > len(name) * 0.5:
        return "в основном цифры"
    return None


# ---------- чтение результатов обхода ----------

def load_pages(since_days: int, only: set[str] | None) -> dict[str, dict[str, dict]]:
    """Предприятие → адрес → последняя прочитанная страница (с текстом: по нему подтверждаются известные позиции)."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    with connect("ingest") as g:
        rows = g.execute("SELECT company_id, url, fetched_at, fetch_status, item FROM crawl_page WHERE fetched_at >= %s ORDER BY fetched_at",
                         (since,)).fetchall()
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        if only and r["company_id"] not in only:
            continue
        item = r["item"] or {}
        out[r["company_id"]][canon(r["url"])] = {"url": r["url"], "status": r["fetch_status"], "fetched_at": r["fetched_at"],
                                                 "e": item.get("extracted") or {}, "text": item.get("text") or "",
                                                 "source_url": item.get("source_url")}
    return out


# ---------- кандидаты ----------

CATALOG_CLS = re.compile(r"catalog|product|prod|goods|tovar|izdel|store|shop|uslug|service", re.I)
CATALOG_H1 = re.compile(r"продукц|каталог|услуг|изделия|оборудован|номенклатур|ассортимент", re.I)
HOME = {"главная", "главная страница", "home"}


def candidates(cid: str, pages: dict[str, dict], existing: list[dict]) -> tuple[list[dict], list[dict]]:
    ok = {k: p for k, p in pages.items() if p["status"] == "OK"}
    h1_count = Counter(norm(p["e"].get("h1") or "") for p in ok.values())
    # карточки, которые повторяются на многих страницах (блок «популярные товары»), — оформление сайта, а не содержание раздела
    card_pages = Counter(t for p in ok.values() for t in {canon(c["url"]) for c in p["e"].get("cards") or []})
    sitewide = {t for t, n in card_pages.items() if n >= 5 and n >= 0.4 * len(ok)}

    def listing(key, p) -> bool:
        """Страница раздела: не меньше двух карточек на вложенные страницы или не меньше восьми собственных карточек.
        Блок «похожие модели» на странице модели (несколько карточек на соседние страницы) разделом её не делает."""
        own = {canon(c["url"]) for c in p["e"].get("cards") or []} - sitewide - {key}
        deeper = {t for t in own if t.startswith(key.rstrip("/") + "/")}
        return len(deeper) >= 2 or len(own) >= 8

    def page_is_catalog(p) -> bool:
        return bool(CATALOG_PATH.search(urlparse(p["url"]).path)) or bool(CATALOG_H1.search(p["e"].get("h1") or ""))

    # ссылки из блоков каталога, карточек и меню: адрес страницы → как её называют ссылки и откуда на неё ведут
    links: dict[str, dict] = defaultdict(lambda: {"names": Counter(), "cls_catalog": False, "from_catalog_page": False, "from_service_page": False,
                                                  "seen_on": [], "parents": []})
    for key, p in ok.items():
        e = p["e"]
        for c in (e.get("cards") or []) + (e.get("catalog_menu") or []):
            t = canon(c["url"])
            if t == key or host(c["url"]) != host(p["url"]) or NOISE_PATH.search(urlparse(c["url"]).path):
                continue
            L = links[t]
            L["names"][c["name"]] += 1
            L["cls_catalog"] |= bool(CATALOG_CLS.search(c.get("cls") or ""))
            if page_is_catalog(p):
                L["from_catalog_page"] = True
                h1 = e.get("h1") or ""
                if h1 and not junk(h1) and h1_count[norm(h1)] <= 2 and h1 not in L["parents"]:
                    L["parents"].append(h1)
            L["from_service_page"] |= bool(SERVICE_PATH.search(urlparse(p["url"]).path) or re.search(r"услуг", e.get("h1") or "", re.I))
            if p["url"] not in L["seen_on"]:
                L["seen_on"].append(p["url"])

    found: list[dict] = []
    sections_h1: list[tuple[str, str]] = []
    # страницы линеек: заголовок совпадает с известной позицией или это раздел каталога — вложенные в них страницы суть модели
    line_keys = {k for k, p in ok.items() if not NOISE_PATH.search(urlparse(p["url"]).path) and urlparse(p["url"]).path.strip("/")
                 and (page_is_catalog(p) or any(similar(x["name"], short_title(tidy(p["e"].get("h1") or ""))) for x in existing))}
    # 1) страница позиции: на неё ведёт пункт каталога или меню, либо она лежит в разделе каталога
    for key, p in ok.items():
        e, path = p["e"], urlparse(p["url"]).path
        if NOISE_PATH.search(path):
            continue
        if e.get("hop", 0) < 1:
            h1 = short_title(tidy(e.get("h1") or ""))
            if h1 and not junk(h1):
                sections_h1.append((h1, p["url"]))
            continue
        L = links.get(key)
        segs = [x for x in path.split("/") if x]
        in_cat_path = bool(CATALOG_PATH.search(path)) and len(segs) >= 2
        in_line = any(key.startswith(lk.rstrip("/") + "/") for lk in line_keys)
        h1 = short_title(tidy(e.get("h1") or ""))
        if h1 and not junk(h1):
            sections_h1.append((h1, p["url"]))            # заголовок любой страницы сайта подтверждает известную позицию
        if not L and not in_cat_path and not in_line:
            continue
        if listing(key, p):
            continue                                   # раздел каталога: позиции — на страницах, куда ведут его карточки
        h1_ok = bool(h1) and not junk(h1) and h1_count[norm(e.get("h1") or "")] <= 2 and len(h1) <= 110
        link_names = [tidy(n) for n, _ in L["names"].most_common()] if L else []
        link_names = [n for n in dict.fromkeys(link_names) if not junk(n)]
        # название — заголовок страницы позиции (обычно полнее), иначе текст ссылки на неё
        name = h1 if h1_ok else (link_names[0] if link_names else None)
        if not name:
            continue
        crumbs = [c for c in crumb_path(e.get("breadcrumbs") or []) if norm(c) not in HOME and norm(c) != norm(name) and not junk(c)
                  and not re.search(r"каталог|продукция", c, re.I)]
        category = (crumbs[-1] if crumbs else None) or ((L or {}).get("parents") or [None])[0]
        service = bool(SERVICE_PATH.search(path) or SERVICE_WORDS.search(name))   # вид — по адресу и названию самой позиции
        strong = in_cat_path or in_line or bool(L and (L["cls_catalog"] or L["from_catalog_page"]))
        found.append({"name": name, "alt": sorted(({h1} if h1_ok else set()) | set(link_names) - {name}), "url": p["url"],
                      "kind": "service" if service else "product", "category": category,
                      "seen_on": ((L or {}).get("seen_on") or [])[:3], "specs": len(e.get("specs") or []),
                      "signals": (["страница в разделе каталога"] if in_cat_path else []) + (["модель линейки"] if in_line else []) +
                                 (["пункт каталога на сайте"] if L and (L["cls_catalog"] or L["from_catalog_page"]) else []) +
                                 (["пункт меню сайта"] if L and not (L["cls_catalog"] or L["from_catalog_page"]) else []),
                      "strong": strong})
    # 2) позиции без отдельных страниц: заголовки на страницах услуг и продукции
    for key, p in ok.items():
        e, path = p["e"], urlparse(p["url"]).path
        if NOISE_PATH.search(path) or not page_is_catalog(p):
            continue
        service = bool(SERVICE_PATH.search(path) or re.search(r"услуг", e.get("h1") or "", re.I))
        for sec in e.get("sections") or []:
            sec = tidy(sec)
            found.append({"name": sec, "alt": [], "url": p["url"], "kind": "service" if service or SERVICE_WORDS.search(sec) else "product",
                          "category": (e.get("h1") or None) if h1_count[norm(e.get("h1") or "")] <= 2 else None, "seen_on": [p["url"]], "specs": 0,
                          "signals": ["заголовок на странице раздела"], "strong": False})

    # известные позиции: совпадение названия с кандидатом или все значимые слова названия есть в тексте страниц сайта
    texts = [norm(p["text"]) for p in ok.values()]
    confirmed, seen, out = {}, set(), []
    for c in sorted(found, key=lambda c: (not c["strong"], len(c["name"]))):
        key = norm(c["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        match = next((x for x in existing if any(similar(x["name"], n) for n in [c["name"], *c["alt"]])), None)
        if match:
            confirmed.setdefault(match["id"], {"id": match["id"], "name": match["name"], "site_name": c["name"], "url": c["url"], "how": "название на сайте"})
            continue
        general = next((x for x in existing if broader(x["name"], c["name"])), None)
        if general:
            confirmed.setdefault(general["id"], {"id": general["id"], "name": general["name"], "site_name": c["name"], "url": c["url"],
                                                 "how": "уточняющая позиция на сайте"})
        reason = junk(c["name"])
        rec = {k: c[k] for k in ("name", "alt", "kind", "category", "url", "seen_on", "signals", "specs")}
        if general:
            rec["refines"] = general["name"]
        if reason:
            rec.update(decision="reject", reason=reason)
        elif c["strong"]:
            rec.update(decision="accept", reason="отдельная страница позиции в каталоге официального сайта")
        else:
            rec.update(decision="review", reason="есть на сайте, но не в разделе каталога — проверить вручную")
        out.append(rec)
    for x in existing:
        hit = next(((h, u) for h, u in sections_h1 if similar(x["name"], h)), None)
        if hit and x["id"] not in confirmed:
            confirmed[x["id"]] = {"id": x["id"], "name": x["name"], "site_name": hit[0], "url": hit[1], "how": "заголовок страницы сайта"}
    for x in existing:
        if x["id"] in confirmed:
            continue
        words = [t for t in norm(x["name"]).split() if len(t) > 3]
        if len(words) >= 2 and any(all(w[:-1] in t for w in words) for t in texts):
            confirmed[x["id"]] = {"id": x["id"], "name": x["name"], "site_name": None, "url": None, "how": "название в тексте страницы"}
    order = {"accept": 0, "review": 1, "reject": 2}
    out.sort(key=lambda r: (order[r["decision"]], r["category"] or "", r["name"]))
    return out, list(confirmed.values())


def host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def cmd_review(args):
    only = set(args.companies.split(",")) if args.companies else None
    pages = load_pages(args.since, only)
    with connect("catalog") as c:
        from pkdb import catalog as cat
        comps, prods, _ = cat.load_companies(c, list(pages))
    report = []
    for cid in sorted(pages):
        cand, confirmed = candidates(cid, pages[cid], prods.get(cid, []))
        n = Counter(x["decision"] for x in cand)
        report.append({"company_id": cid, "name": comps[cid]["name"], "site": comps[cid].get("site"), "pages": len(pages[cid]),
                       "pages_ok": sum(p["status"] == "OK" for p in pages[cid].values()),
                       "existing_confirmed": confirmed, "existing_not_found": [p["name"] for p in prods.get(cid, []) if p["id"] not in {x["id"] for x in confirmed}],
                       "candidates": cand, "summary": dict(n)})
        print(f"{cid:12} страниц {len(pages[cid]):3}  известных позиций найдено {len(confirmed)}/{len(prods.get(cid, []))}  "
              f"новых: принять {n['accept']}, проверить {n['review']}, отсеяно {n['reject']}")
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nфайл на проверку: {args.out}  (decision: accept — записать, reject — нет, review — решить вручную)")


# ---------- запись в каталог ----------

SPEC_HEADER = re.compile(r"^(наименование|параметр|показатель|характеристик|технические характеристики|вид оборудования|таблица)", re.I)


def clean_specs(specs: list, sitewide: set) -> list[dict]:
    """Характеристики из таблицы страницы позиции: без строк, которые повторяются на многих страницах сайта (общий блок),
    без заголовков таблиц («Наименование — Значение») и строк с числом вместо названия параметра."""
    out = []
    for k, v in specs:
        k, v = re.sub(r"\s+", " ", k).strip(" :"), re.sub(r"\s+", " ", v).strip()
        if (k, v) in sitewide or SPEC_HEADER.search(k) or v.lower() in {"значение", "значения", "параметры оборудования"}:
            continue
        if not re.search(r"[A-Za-zА-Яа-яЁё]", k):
            continue
        out.append({"name": k, "value": v})
    return out[:10]


def infer_okpd2(name: str, okpd2: dict, kind: str = "product") -> dict | None:
    """Класс ОКПД2 по словарю предметной области — только по главному слову названия (первые три слова):
    «Станция управления … для погружных насосов» — не насос."""
    from app.matching import parse_query
    head = re.sub(r"^(услуги|работы)( по| на)?\s+", "", re.sub(r"[()«»\"]", " ", name).strip(), flags=re.I)   # «Услуги по резке …» → «резке …»
    q = parse_query(" ".join(head.split()[:3]))
    code = q.okpd2 if q.products or q.technologies else None
    tech = next((x["okpd2"] for x in q.technologies if x.get("okpd2")), None)
    if kind == "service" and tech:
        code = tech                                   # услуга «резка проката» — класс услуги обработки, а не проката
    return {"code": code, "name": okpd2[code], "status": "INFERRED"} if code and code in okpd2 else None


def cmd_apply(args):
    report = json.loads(Path(args.file).read_text(encoding="utf-8"))
    pages_all = load_pages(args.since, {r["company_id"] for r in report})
    st = Store()
    okpd2 = {}
    with connect("catalog") as c:
        okpd2 = {r["code"]: r["name"] for r in c.execute("SELECT code, name FROM okpd2")}
    today = date.today().isoformat()
    total_new = 0
    for r in report:
        cid = r["company_id"]
        if cid not in st.companies:
            continue
        pages = pages_all.get(cid, {})
        crawl_day = max((p["fetched_at"] for p in pages.values()), default=datetime.now(timezone.utc)).date().isoformat()
        prods, srcs = st.products[cid], st.sources[cid]
        changed = False
        spec_pages = Counter((k, v) for p in pages.values() for k, v in {tuple(x) for x in (p["e"].get("specs") or [])})
        spec_sitewide = {kv for kv, n in spec_pages.items() if n >= 5 and n >= 0.3 * len(pages)}
        # источники сайта: результат последнего обхода
        for s in srcs:
            if s["source_type"] == "OFFICIAL_SITE":
                p = pages.get(canon(s["source_url"]))
                if p and (s.get("fetch_status") != p["status"] or s.get("last_verified_at") != crawl_day):
                    s["fetch_status"], s["last_verified_at"] = p["status"], crawl_day
                    changed = True
        # кандидат, признанный при проверке известной позицией: decision "existing:<id позиции>"
        extra_confirmed = [{"id": c["decision"].split(":", 1)[1]} for c in r.get("candidates") or [] if str(c.get("decision", "")).startswith("existing:")]
        # известные позиции, найденные на сайте: дата проверки
        for x in (r.get("existing_confirmed") or []) + extra_confirmed:
            p = next((p for p in prods if p["id"] == x["id"]), None)
            if p and p.get("last_verified_at") != crawl_day:
                p["last_verified_at"] = crawl_day
                changed = True
        # новые позиции
        have = {norm(p["name"]) for p in prods}
        added = []
        for cand in r.get("candidates") or []:
            if cand.get("decision") != "accept" or norm(cand["name"]) in have or not cand.get("url"):
                continue
            page = pages.get(canon(cand["url"]))
            sid = f"{cid}-web-{hashlib.sha1(canon(cand['url']).encode()).hexdigest()[:8]}"
            if not any(s["id"] == sid for s in srcs):
                title = (page or {}).get("e", {}).get("h1") or (page or {}).get("e", {}).get("title") or cand["name"]
                srcs.append({"id": sid, "source_url": cand["url"], "source_type": "OFFICIAL_SITE", "source_title": f"Официальный сайт: {title}"[:300],
                             "priority": 1, "source_date": None, "last_verified_at": crawl_day, "confirms": ["продукция и услуги"],
                             "fetch_status": (page or {}).get("status") or "OK", "note": f"Обход сайта краулером {crawl_day}"})
            pid, n = f"{cid}-{slug(cand['name'])}", 2
            while any(p["id"] == pid for p in prods) or pid in st_ids(st):
                pid, n = f"{cid}-{slug(cand['name'])}-{n}", n + 1
            specs = (page or {}).get("e", {}).get("specs") or []
            own_page = "заголовок на странице раздела" not in (cand.get("signals") or [])   # у позиции своя страница, таблица — её характеристики
            params = clean_specs(specs, spec_sitewide) if page and own_page else []
            if cand.get("params") is not None:                                             # характеристики, уточнённые при проверке
                params = cand["params"]
            prods.append({"id": pid, "name": cand["name"], "kind": cand.get("kind") or "product", "category": cand.get("category") or
                          ("Услуги" if cand.get("kind") == "service" else "Продукция"), "okpd2": infer_okpd2(cand["name"], okpd2, cand.get("kind") or "product"),
                          "description": None, "params": params, "materials": [], "price": None, "volume": None, "min_batch": None,
                          "lead_time_production": None, "lead_time_delivery": None, "availability": None, "warehouse_id": None, "photo": None,
                          "source_id": sid, "last_verified_at": crawl_day, "company_id": cid})
            have.add(norm(cand["name"]))
            added.append(cand["name"])
        if added:
            merge._change([], st.companies[cid], "products", "Продукция (официальный сайт)", None, f"добавлено {len(added)} поз.", today)
            changed = True
        if changed:
            st.dirty.add(cid)
            st.products_dirty.add(cid)
            total_new += len(added)
            print(f"{cid:12} новых позиций {len(added)}" + (": " + "; ".join(added[:6]) + (" …" if len(added) > 6 else "") if added else ""))
    if args.dry_run:
        print(f"\nпроверка без записи: новых позиций {total_new}")
        return
    rev = st.save(f"продукция с официальных сайтов: +{total_new}")
    print(f"\nзаписано: новых позиций {total_new}, ревизия каталога {rev}")


_ids_cache: set[str] | None = None


def st_ids(st) -> set[str]:
    global _ids_cache
    if _ids_cache is None:
        _ids_cache = {p["id"] for lst in st.products.values() for p in lst}
    return _ids_cache


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python tools/crawl_products.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="кандидаты в позиции продукции на проверку")
    r.add_argument("--out", default="crawl_review.json")
    r.add_argument("--companies")
    r.add_argument("--since", type=int, default=7, help="страницы обхода за последние N дней")
    a = sub.add_parser("apply", help="записать одобренные позиции в каталог")
    a.add_argument("file")
    a.add_argument("--since", type=int, default=7)
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    (cmd_review if args.cmd == "review" else cmd_apply)(args)


if __name__ == "__main__":
    main()
