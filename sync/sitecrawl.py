"""Результаты обхода официальных сайтов краулером (sm01_ingest) — в каталог (sm01_catalog).

Краулер (crawler/) ищет сайты предприятий и обходит их, но карточки не меняет: у него доступ к каталогу только на чтение.
Этот модуль переносит в карточки то, что подтверждено:
  сайты — подтверждённые ИНН, ОГРН или названием с адресом из ЕГРЮЛ (site_discovery, status CONFIRMED): поле «Сайт»
  и источник «Официальный сайт» с тем, чем сайт подтверждён;
  позиции продукции — страницы позиций в каталоге сайта (решение accept): название дословно со страницы, источник —
  эта страница, характеристики — из таблицы этой страницы, код ОКПД2 — класс по словарю со статусом INFERRED;
  известные позиции, найденные на сайте, получают новую дату проверки.
Остальное (позиции review, сайты, у которых совпало только название) остаётся модератору.

Вызывается ежедневным сбором (python -m sync, этап «сайты и продукция с официальных сайтов») для страниц, появившихся
после прошлого запуска, и вручную — tools/crawl_products.py.
Принцип платформы: ничего не дополняется «по памяти».
"""
from __future__ import annotations
import hashlib
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from pkdb import connect

from . import merge
from .store import slug

CATALOG_PATH = re.compile(r"produk|product|katalog|catalog|izdeli|uslug|servic|oborud|equipment|goods|tovar|nomenklat|assortiment|production|proizvodstv", re.I)
SERVICE_PATH = re.compile(r"uslug|servic|servis", re.I)
NOISE_PATH = re.compile(r"/(news|novosti|press|article|stati|blog|event|sobyti|vakans|vacanc|career|kariera|about|o-kompanii|o_kompanii|company/?$|"
                        r"o-nas|o_nas|onas|o-zavode|o-predpriyatii|struktur|structure|rukovodstv|management|missi|klient|client|dileram|dealer|"
                        r"postavshchik|supplier|oplat|payment|dostavk|delivery|garanti|warranty|faq|vopros|help|support|soglashen|agreement|"
                        r"raskryti|disclosure|sout|antikorrup|anticorrup|rekvizit|requisit|karta-sajta|karta-sayta|"
                        r"kontakt|contact|smi|media|foto|photo|video|gallery|galereya|partner|otzyv|review|dokument|document|licenz|sertifik|"
                        r"certific|history|istoriya|zakupk|tender|purchase|expert-form|feedback|order|zakaz|politika|privacy|sitemap)", re.I)
STOP = {"главная", "перейти", "подробнее", "читать", "читать далее", "далее", "назад", "еще", "ещё", "показать еще", "показать ещё", "смотреть",
        "смотреть все", "все", "вся продукция", "все услуги", "все товары", "каталог", "каталог продукции", "продукция", "наша продукция",
        "услуги", "наши услуги", "о компании", "о предприятии", "контакты", "новости", "вакансии", "отзывы", "партнеры", "партнёры",
        "документы", "сертификаты", "наличие на складе", "склад свободной реализации", "заказать", "оставить заявку", "отправить заявку",
        "купить", "в корзину", "цена", "цены", "прайс", "прайс-лист", "фото", "видео", "галерея", "карта сайта", "производство",
        "непрофильная продукция", "основная продукция", "запросить цену", "узнать цену", "получить консультацию", "обратная связь",
        "задать вопрос", "развернуть", "свернуть", "меню", "поиск", "english", "eng", "rus", "en", "ru", "каталоги", "техническая документация",
        "опросный лист", "опросные листы", "скачать опросный лист", "закупки", "тендеры", "продажа неликвидов", "социальные сети",
        "о нас", "о заводе", "структура", "руководство", "история", "миссия", "реквизиты", "реквизиты компании", "лицензии", "карьера",
        "команда", "клиенты", "наши клиенты", "наши проекты", "наши партнеры", "наши партнёры", "акции", "доставка", "оплата",
        "доставка и оплата", "гарантия", "вопрос-ответ", "вопрос ответ", "faq", "статьи", "полезная информация", "информация",
        "раскрытие информации", "охрана труда", "специальная оценка условий труда", "противодействие коррупции",
        "политика конфиденциальности", "пользовательское соглашение", "сотрудничество", "дилерам", "поставщикам", "покупателям",
        "как купить", "как заказать", "где купить", "качество", "контроль качества", "сертификация", "награды", "фотогалерея",
        "видеогалерея", "обращение руководителя", "пресс-центр", "мероприятия", "процесс производства", "производственные мощности",
        "дилерская сеть", "дилеры", "каталоги продукции", "спецоценка условий труда", "технические характеристики", "характеристики",
        "документация", "описание", "преимущества"}
START_JUNK = re.compile(r"^(c|с)качать|^читать|^подробн|^перейти|^смотреть|^узнать|^заказать|^оставить|^отправить|^получить|^задать|^показать|^вернуться|^©", re.I)
DOC_START = re.compile(r"^(патент|сертификат|свидетельство|декларация|лицензия|диплом|благодарственное письмо|опросн\w* лист\w*)\b", re.I)
DOC_END = re.compile(r"\s(паспорт|рэ|руководство по эксплуатации|инструкция по эксплуатации)$", re.I)
NEWS_START = re.compile(r"^(выполнен|проведен|изготовлен|поставлен|завершен|сдан|отгружен|смонтирован|введен|запущен|реализован)[аоы]?\s", re.I)
ARTICLE_START = re.compile(r"^(как|почему|зачем|что такое|особенности|преимущества|советы|обзор|статья)\b", re.I)
SECTION_PREFIX = re.compile(r"^(рубрика|категория|раздел|метка|тег)\s*:", re.I)
TOC = re.compile(r"^1\.\s.*\s2\.\s")                     # «1. назначение 2. варианты исполнений 3. …» — оглавление страницы
# рекламная фраза, название фирмы, «… в Воронеже»: на сайте это позиция, но в каталог такое название без модератора не пишется
ADVERT = re.compile(r"^(производим|изготавливаем|изготовим|предлагаем|выполняем|осуществляем|поставляем|продаем|продаём|реализуем|выгодн\w*|лучш\w*)\s", re.I)
IN_CITY = re.compile(r"\sв\s(г\.\s?)?[А-ЯЁ][а-яё]+[еи](?=[\s:,.]|$)")
LEGAL_NAME = re.compile(r"\b(ООО|ОАО|ЗАО|ПАО|АО|НПП|НПО|ГКУ|компания|фирма|завод)\s*[«\"]", re.I)
ORG_FORM = re.compile(r"\b(ООО|ОАО|ЗАО|ПАО|АО|НПП|НПО|НПФ|ПКФ|ТПК|ФПК|ТД|ГК)\b")
PRICE_TAIL = re.compile(r"\s+(от\s+)?(\d{1,3}(?:[ \xa0]\d{3})+|\d{4,})(?:[.,]\d{1,2})?\s?(р\.?|руб\.?|₽)$|"
                        r"\s+(от\s+)?\d+(?:[.,]\d{1,2})?\s?(руб\.?|₽)$|\s+цена\s+по\s+запросу$", re.I)
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


def nominative(name: str) -> str:
    """После «Купить» название стоит в винительном падеже: «банную печь» → «банная печь», «турбину» → «турбина».
    Меняются прилагательные (-ую, -юю) и первое слово после них (-у, -ю); остальное — как на сайте."""
    words = name.split(" ")
    for i, w in enumerate(words[:4]):
        m = re.fullmatch(r"([А-ЯЁа-яё-]{2,})(ую|юю)", w)
        if m:
            words[i] = m.group(1) + ("ая" if m.group(2) == "ую" else "яя")
            continue
        m = re.fullmatch(r"([А-ЯЁа-яё-]{3,})([ую])", w)
        if m:
            words[i] = m.group(1) + ("а" if m.group(2) == "у" else "я")
        break
    return " ".join(words)


def undup(name: str) -> str:
    """Заголовок и подпись к нему подряд: «Коробка ЕхКК-А РЭ Коробка ЕхКК-А РЭ» → «Коробка ЕхКК-А РЭ»."""
    return re.sub(r"^(.{6,}?) \1$", r"\1", name)


def tidy(name: str) -> str:
    """Оформление названия без изменения смысла: пробелы, регистр заголовков капсом, пометка «(Цена по запросу)»."""
    name = re.sub(r"\s*\((цена по запросу|под заказ|в наличии)\)\s*$", "", re.sub(r"\s+", " ", name or "").strip(" .,:;"), flags=re.I)
    name = undup(name)
    name = re.split(r"\s[—–-]\s(?=[^—–]*(решени|идеальн|отличн|надежн|надёжн|лучш|выгодн|купить|цен[аы]|доставк|производител))", name, flags=re.I)[0]
    # оформление для поисковиков: «> Упаковка», «Купить печь-казан …», «… от производителя в Воронеже», «Лодка "Волга" 80 000 р»
    name = re.sub(r"^[>•·*»\-—–]+\s*", "", name)
    name = re.sub(r"^(продукция|каталог|товары|услуги)\s*[-—–:]\s+", "", name, flags=re.I)
    bought = re.match(r"купить\s+", name, re.I)
    if bought:
        name = nominative(name[bought.end():])
    name = PRICE_TAIL.sub("", name)
    name = re.sub(r"\s+(от производителя|оптом|недорого|в наличии|с доставкой|по выгодной цене|по низкой цене)(?=\s|$)", "", name, flags=re.I)
    name = re.sub(r"\s+в\s+[А-ЯЁ][а-яё]+(-[а-яё]+-[А-ЯЁ][а-яё]+)?$", "", name).strip(" ,.-")
    name = name[:1].upper() + name[1:]
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
    if DOC_START.search(name.strip()) or DOC_END.search(name.strip()):
        return "документ, а не позиция (патент, сертификат, опросный лист, паспорт)"
    if NEWS_START.search(name.strip()):
        return "новость или объект из портфолио («Выполнен ремонт…»)"
    if ARTICLE_START.search(name.strip()):
        return "статья («Как выбрать кран»), а не позиция"
    if SECTION_PREFIX.search(name.strip()):
        return "раздел сайта («Рубрика: …»), а не позиция"
    if TOC.search(name):
        return "оглавление страницы"
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
        rows = g.execute("SELECT company_id, url, fetched_at, fetch_status, item FROM crawl_page WHERE fetched_at >= %s "
                         "AND (%s::text[] IS NULL OR company_id = ANY(%s)) ORDER BY fetched_at",
                         (since, sorted(only) if only else None, sorted(only) if only else None)).fetchall()
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        item = r["item"] or {}
        out[r["company_id"]][canon(r["url"])] = {"url": r["url"], "status": r["fetch_status"], "fetched_at": r["fetched_at"],
                                                 "e": item.get("extracted") or {}, "text": item.get("text") or "",
                                                 "source_url": item.get("source_url")}
    return out


# ---------- кандидаты ----------

CATALOG_CLS = re.compile(r"catalog|product|prod|goods|tovar|izdel|store|shop|uslug|service", re.I)
CATALOG_H1 = re.compile(r"продукц|каталог|услуг|изделия|оборудован|номенклатур|ассортимент", re.I)
HOME = {"главная", "главная страница", "home"}


def site_prefix(names: list[str], company: str | None) -> str | None:
    """Имя сайта в начале заголовков («СаратовСталь Рубрика: Стойки», «Группа компаний FRAMECAD Навесные панели»): общее начало
    половины названий, совпадающее с названием предприятия или «Группа компаний …», «Корпорация …». Линейка продукции
    («Металлоформа 1ПБ30.20», «Труба профильная …») с названием предприятия не совпадает и остаётся."""
    names = list(dict.fromkeys(names))
    core = re.sub(r"[^a-zа-я0-9]", "", norm(ORG_FORM.sub(" ", company or "")))
    for k in (4, 3, 2, 1):
        heads = Counter(" ".join(n.split()[:k]) for n in names if len(n.split()) > k)
        if not heads:
            continue
        head, n = heads.most_common(1)[0]
        letters = re.sub(r"[^a-zа-я0-9]", "", norm(head))
        by_company = len(core) >= 4 and len(letters) >= 4 and (core in letters or letters in core)
        if n >= 3 and n >= 0.5 * len(names) and (by_company or re.match(r"(группа компаний|корпорация|холдинг)\s", head, re.I)):
            return head
    return None


def strip_prefix(name: str, prefix: str | None) -> str:
    """Название без имени сайта, если после него остаётся название на русском («БЕШТАУ M24FHD/BHM» — марка, не трогаем)."""
    if not prefix or not name.startswith(prefix + " "):
        return name
    rest = undup(name[len(prefix):].strip(" -—–:|/"))
    return rest[:1].upper() + rest[1:] if re.search(r"[А-ЯЁа-яё]{3,}", rest) else name


def candidates(cid: str, pages: dict[str, dict], existing: list[dict], company: str | None = None) -> tuple[list[dict], list[dict]]:
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
    # заголовок главной — обычно название предприятия или сайта, а не раздел каталога
    home_h1 = {norm(p["e"].get("h1") or "") for p in ok.values() if p["e"].get("hop", 0) < 1} - {""}
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
        if category and (norm(category) in home_h1 or norm(category) in STOP):
            category = None
        # вид — по названию позиции и адресу страницы; модель с маркой («Светильник LL-УП-20» в разделе /services/) — продукция
        service = bool(SERVICE_WORDS.search(name)) or (bool(SERVICE_PATH.search(path)) and not has_model(name))
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

    prefix = site_prefix([c["name"] for c in found], company)
    for c in found:
        c["name"], c["alt"] = strip_prefix(c["name"], prefix), [strip_prefix(a, prefix) for a in c["alt"]]

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


def build_report(pages: dict[str, dict[str, dict]], comps: dict, prods: dict, log=print) -> list[dict]:
    report = []
    for cid in sorted(pages):
        if cid not in comps:
            continue
        cand, confirmed = candidates(cid, pages[cid], prods.get(cid, []), comps[cid]["name"])
        n = Counter(x["decision"] for x in cand)
        report.append({"company_id": cid, "name": comps[cid]["name"], "site": comps[cid].get("site"), "pages": len(pages[cid]),
                       "pages_ok": sum(p["status"] == "OK" for p in pages[cid].values()),
                       "existing_confirmed": confirmed, "existing_not_found": [p["name"] for p in prods.get(cid, []) if p["id"] not in {x["id"] for x in confirmed}],
                       "candidates": cand, "summary": dict(n)})
        log(f"{cid:12} страниц {len(pages[cid]):3}  известных позиций найдено {len(confirmed)}/{len(prods.get(cid, []))}  "
            f"новых: принять {n['accept']}, проверить {n['review']}, отсеяно {n['reject']}")
    return report


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
    try:
        from app.matching import parse_query
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.matching import parse_query
    head = re.sub(r"^(услуги|работы)( по| на)?\s+", "", re.sub(r"[()«»\"]", " ", name).strip(), flags=re.I)   # «Услуги по резке …» → «резке …»
    q = parse_query(" ".join(head.split()[:3]))
    code = q.okpd2 if q.products or q.technologies else None
    tech = next((x["okpd2"] for x in q.technologies if x.get("okpd2")), None)
    if kind == "service" and tech:
        code = tech                                   # услуга «резка проката» — класс услуги обработки, а не проката
    return {"code": code, "name": okpd2[code], "status": "INFERRED"} if code and code in okpd2 else None


def okpd2_names() -> dict:
    with connect("catalog") as c:
        return {r["code"]: r["name"] for r in c.execute("SELECT code, name FROM okpd2")}


# ---------- что записывать без модератора ----------

GENERIC = {"услуга", "услуги", "перечень", "прочая продукция", "прочие услуги", "дополнительные услуги", "невостребованное имущество",
           "невостребованное имущество на реализацию", "номенклатура закупок", "продажа непрофильных активов", "пресс кит", "публикации",
           "навигация для водителей", "продукция", "товары", "решения", "направления деятельности", "виды деятельности"}
PRODUCTION_UNIT = re.compile(r"^производство\b|\bпроизводство$")


def has_model(name: str) -> bool:
    """В названии марка или модель: цифры (кроме года) или латинская аббревиатура — «АИП 6.0», «LL-УП-20», «SN-12400», «NMRV».
    Латинские слова без цифр («Shohadaye Dezful Sugar» — объект в портфолио) моделью не считаются."""
    for t in re.findall(r"[\w.,/-]+", name or ""):
        if (any(ch.isdigit() for ch in t) and not re.fullmatch(r"(19|20)\d\d", t)) or re.fullmatch(r"[A-Z]{2,}[A-Z0-9-]*", t):
            return True
    return False


def concatenated(name: str) -> bool:
    """Склеенные заголовки блоков («10 лет Договор поставки по счету Программа замещения…»): два и больше слов
    с заглавной буквы посреди названия (аббревиатуры и марки не считаются)."""
    return sum(1 for w in (name or "").split()[1:] if re.fullmatch(r"[А-ЯЁ][а-яё]{2,}[,.]?", w)) >= 2


def first_stem(name: str) -> str:
    """Первое слово без окончания: «Компенсаторы» и «Компенсатор» — одна линейка, «Металлургия» и «Металлоконструкции» — нет."""
    w = norm(name).split()
    return re.sub(r"[аеёиоуыэюяйь]+$", "", w[0]) if w else ""


def auto_accept(c: dict, family: Counter) -> bool:
    """Позиция записывается без модератора, только если кроме места на сайте (раздел каталога, карточка) есть признак
    именно товара или услуги: характеристики на её странице, марка или модель в названии или соседние позиции той же
    линейки («Компенсаторы осевые…», «Компенсаторы сдвиговые…»). Иначе это часто пункты меню («Пресс-кит»),
    подразделения («Прокатное производство»), лозунги («Производим краны по цене на 15% ниже рынка») — их решает модератор."""
    name = c["name"]
    if c.get("decision") != "accept" or norm(name) in GENERIC or norm(name) in STOP or PRODUCTION_UNIT.search(norm(name)) or concatenated(name):
        return False
    if ADVERT.search(name) or IN_CITY.search(name) or LEGAL_NAME.search(name):
        return False
    return c.get("specs", 0) > 0 or has_model(name) or family[first_stem(name)] >= 2


def apply_report(st, report: list[dict], pages_all: dict, okpd2: dict, today: str, log=print, changes: list | None = None,
                 auto: bool = False) -> int:
    """Одобренные (accept) позиции и подтверждения известных — в хранилище каталога (запись — st.save). Возвращает число новых.
    auto — без модератора: из одобренных только те, что проходят auto_accept."""
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
        family = Counter(first_stem(c["name"]) for c in r.get("candidates") or [] if c.get("decision") == "accept")
        for cand in r.get("candidates") or []:
            if cand.get("decision") != "accept" or norm(cand["name"]) in have or not cand.get("url") or (auto and not auto_accept(cand, family)):
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
            merge._change(changes if changes is not None else [], st.companies[cid], "products", "Продукция (официальный сайт)", None,
                          f"добавлено {len(added)} поз.", today)
            changed = True
        if changed:
            st.dirty.add(cid)
            st.products_dirty.add(cid)
            total_new += len(added)
            log(f"{cid:12} новых позиций {len(added)}" + (": " + "; ".join(added[:6]) + (" …" if len(added) > 6 else "") if added else ""))
    return total_new


# ---------- найденные краулером сайты ----------

SITE_HOW = {"inn": "ИНН предприятия на странице {page}", "ogrn": "ОГРН предприятия на странице {page}",
            "name+address": "название, улица, дом и город из ЕГРЮЛ на сайте", "moderator": "подтверждён модератором"}


def load_sites(only: set[str] | None) -> list[dict]:
    """Последнее решение по каждому предприятию: подтверждённый сайт, если есть, иначе сайт на решение модератора."""
    with connect("ingest") as g:
        return g.execute("""SELECT DISTINCT ON (company_id) company_id, domain, url, method, status, evidence, checked_at FROM site_discovery
                            WHERE status IN ('CONFIRMED', 'CANDIDATE') AND (%s::text[] IS NULL OR company_id = ANY(%s))
                            ORDER BY company_id, (status = 'CONFIRMED') DESC, checked_at DESC""",
                         (sorted(only) if only else None, sorted(only) if only else None)).fetchall()


def apply_sites(st, rows: list[dict], today: str, changes: list | None = None) -> list[str]:
    """Подтверждённые сайты — в карточки без сайта: поле «Сайт» и источник «Официальный сайт» с тем, чем сайт подтверждён."""
    added = []
    for r in rows:
        cid, c = r["company_id"], st.companies.get(r["company_id"])
        if r["status"] != "CONFIRMED" or not c or c.get("site"):
            continue
        ev, day = r["evidence"] or {}, r["checked_at"].date().isoformat()
        how = SITE_HOW.get(ev.get("by"), "проверка краулером").format(page=ev.get("page") or r["url"])
        c["site"] = r["url"]
        sid = f"{cid}-site"
        if any(s["id"] == sid for s in st.sources[cid]):
            sid = f"{cid}-site-{hashlib.sha1(r['url'].encode()).hexdigest()[:6]}"
        st.sources[cid].append({"id": sid, "source_url": r["url"], "source_type": "OFFICIAL_SITE", "source_title": f"Официальный сайт {c['name']}",
                                "priority": 1, "source_date": None, "last_verified_at": day, "confirms": ["официальный сайт предприятия"],
                                "fetch_status": "OK", "note": f"Найден краулером {day}: {how}"})
        merge._change(changes if changes is not None else [], c, "updated", "Официальный сайт", None, r["url"], today)
        st.dirty.add(cid)
        added.append(cid)
    return added


_ids_cache: set[str] | None = None


def st_ids(st) -> set[str]:
    global _ids_cache
    if _ids_cache is None:
        _ids_cache = {p["id"] for lst in st.products.values() for p in lst}
    return _ids_cache


def apply_new(st, today: str, since: datetime | None = None, window_days: int = 8, only: set[str] | None = None, log=print,
              changes: list | None = None) -> dict:
    """Найденное краулером — в хранилище каталога (запись — st.save): подтверждённые сайты и позиции с решением accept.

    since — разбирать предприятия, у которых есть страницы обхода новее этого момента (ежедневный сбор помнит, докуда
    обработал), иначе — за последние window_days дней; страницы для разбора — за window_days дней. Возвращает число
    записанных сайтов и позиций, материалы для модератора и отметку upto — время последней разобранной страницы."""
    sites = load_sites(only)
    new_sites = apply_sites(st, sites, today, changes)
    start = since or (datetime.now(timezone.utc) - timedelta(days=window_days))
    with connect("ingest") as g:
        rows = g.execute("SELECT company_id, max(fetched_at) AS last FROM crawl_page WHERE fetched_at > %s AND company_id IS NOT NULL "
                         "GROUP BY company_id", (start,)).fetchall()
    ids = sorted(r["company_id"] for r in rows if (not only or r["company_id"] in only) and r["company_id"] in st.companies)
    okpd2, total, review = okpd2_names(), 0, []
    # страницы — пачками по предприятиям: у сотен сайтов десятки тысяч страниц с текстом
    for i in range(0, len(ids), 40):
        batch = set(ids[i:i + 40])
        pages = load_pages(window_days, batch)
        report = build_report(pages, st.companies, st.products, log=lambda *a: None)
        total += apply_report(st, report, pages, okpd2, today, log=log, changes=changes, auto=True)
        for r in report:   # модератору — review и одобренные правилами обхода, но без признака товара
            fam = Counter(first_stem(c["name"]) for c in r["candidates"] if c["decision"] == "accept")
            rest = [c for c in r["candidates"] if c["decision"] == "review" or (c["decision"] == "accept" and not auto_accept(c, fam))]
            if rest:
                review.append({**{k: r[k] for k in ("company_id", "name", "site")}, "candidates": rest})
    cand_sites = [{k: (str(v) if k == "checked_at" else v) for k, v in r.items()} for r in sites
                  if r["status"] == "CANDIDATE" and not st.companies.get(r["company_id"], {}).get("site")]
    return {"sites": new_sites, "confirmed": sum(r["status"] == "CONFIRMED" for r in sites), "products": total, "review": review,
            "candidate_sites": cand_sites, "upto": max((r["last"] for r in rows), default=since)}
