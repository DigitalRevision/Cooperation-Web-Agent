"""Поиск официального сайта предприятия: кандидаты доменов и проверка, что сайт принадлежит именно этому предприятию.

Кандидаты без поисковика: домен корпоративной почты из карточки; название из карточки и из ЕГРЮЛ латиницей в нескольких
вариантах транслитерации («Донкабель» → donkabel, «Станикс» → staniks и stanix), через дефис, аббревиатура длинного названия
(«Сальский завод прессовых узлов» → szpu), с кодом региона (vzsm34); зоны .ru, .рф, .com, .su, .net, .org.

Если задан ключ Яндекс Search API (PK_YANDEX_SEARCH_KEY и PK_YANDEX_FOLDER_ID, платно по тарифу Яндекс Облака), для
предприятий, у которых домены по названию не подтвердились, сайт ищется поисковиком: «название город официальный сайт»,
первые сайты выдачи, кроме справочников и площадок, проверяются теми же правилами.

Подтверждение — только тем, что написано на сайте:
  CONFIRMED — ИНН или ОГРН предприятия на главной, в контактах или реквизитах; либо название из ЕГРЮЛ вместе с улицей,
              домом и городом из адреса ЕГРЮЛ: одноимённых фирм много, а по одному адресу с тем же названием — нет;
  CANDIDATE — совпало только название: сайт, скорее всего, этого предприятия, но решает модератор;
  REJECTED  — ни ИНН, ни названия; каталог организаций (на странице ИНН многих фирм); перенаправление на площадку,
              агрегатор или страницу регистратора доменов.
"""
from __future__ import annotations
import base64
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "h", "ts",
               "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
# другие распространённые способы записать название латиницей
ALT = ({"й": "i", "х": "kh", "ц": "c", "ю": "iu", "я": "ia", "ы": "i", "щ": "shch"}, {"кс": "x", "х": "x", "ж": "j", "ц": "c"})
LEGAL_FORM = re.compile(r"^(ооо|оао|зао|ао|пао|нао|ип|фгуп|гуп|муп|фгбу|нпо|нпп|нпф|пкф|пк|тд|ано|нко|ук|ск|гк|мп)$")
REGION_SUFFIX = {"34": ["34", "vlg"], "61": ["61", "rnd"], "64": ["64"], "36": ["36", "vrn"], "30": ["30"], "08": ["08"], "57": ["57"]}
FREE_MAIL = {"mail.ru", "bk.ru", "list.ru", "inbox.ru", "internet.ru", "yandex.ru", "ya.ru", "yandex.com", "gmail.com", "rambler.ru",
             "lenta.ru", "ro.ru", "autorambler.ru", "myrambler.ru", "hotmail.com", "outlook.com", "icloud.com", "yahoo.com", "mail.com",
             "narod.ru", "e1.ru", "ngs.ru", "qip.ru", "pochta.ru", "live.ru", "vk.com"}
# куда перенаправляют чужие и пустые домены: регистраторы и парковки, площадки объявлений, справочники и агрегаторы организаций
DENY_HOST = re.compile(r"(^|\.)(reg\.ru|nic\.ru|r01\.ru|timeweb\.(ru|com)|beget\.(ru|com)|sprinthost\.ru|sweb\.ru|jino\.ru|hostland\.ru|"
                       r"sedo(parking)?\.com|dan\.com|afternic\.com|godaddy\.com|hugedomains\.com|domainmarket|parking|expired|"
                       r"avito\.ru|ozon\.ru|wildberries\.ru|tiu\.ru|satom\.ru|pulscen\.ru|blizko\.ru|all\.biz|flagma|yell\.ru|zoon\.ru|"
                       r"2gis\.(ru|com)|yandex\.(ru|com)|google\.(ru|com)|orgpage\.ru|spravker\.ru|rusprofile\.ru|list-org\.com|checko\.ru|"
                       r"zachestnyibiznes\.ru|sbis\.ru|kontur\.ru|audit-it\.ru|e-ecolog\.ru|companium\.ru|vbankcenter\.ru|rbc\.ru|"
                       r"hh\.ru|superjob\.ru|vk\.com|ok\.ru|t\.me|facebook\.com|instagram\.com|youtube\.com|nalog\.(gov\.)?ru|gosuslugi\.ru)$", re.I)
CONTACT_HREF = re.compile(r"kontakt|contact|rekviz|requisit|about|o-kompanii|o_kompanii|o-nas|company|firm|o-predpriyatii", re.I)
CONTACT_TEXT = re.compile(r"контакт|реквизит|о компании|о нас|о предприятии|о заводе", re.I)
CONTACT_PATHS = ("/contacts/", "/kontakty/", "/rekvizity/", "/about/", "/o-kompanii/")
MAX_PAGES = 5        # страниц на проверку одного домена: главная, контакты, реквизиты, «о компании»
MAX_DOMAINS = 40     # доменов-кандидатов на предприятие


def translit(s: str, alt: dict | None = None) -> str:
    s = s.lower().replace("ё", "е")
    for k, v in (alt or {}).items():
        if len(k) > 1:
            s = s.replace(k, v)
    return "".join((alt or {}).get(ch, TR.get(ch, ch)) for ch in s)


def _words(s: str | None) -> list[str]:
    return [w for w in re.split(r"[^0-9a-zа-яё]+", (s or "").lower()) if w and not LEGAL_FORM.match(w)]


def name_core(c: dict) -> str:
    """Название без организационно-правовой формы: последнее название в кавычках из ЕГРЮЛ («…ЗАВОД "ИРБИС"» → ирбис)."""
    q = re.findall(r'"([^"]+)', c.get("legal_name") or "")
    core = q[-1] if q else re.sub(r"[«»\"]", " ", c.get("short") or c.get("name") or "")
    return re.sub(r"\s+", " ", core.lower().replace("ё", "е")).strip(" -")


def brand_words(c: dict) -> list[list[str]]:
    out = []
    for raw in (c.get("short"), re.sub(r"[«»\"]", " ", c.get("name") or ""), name_core(c)):
        w = _words(raw)
        if w and w not in out:
            out.append(w)
    return out


def email_domains(c: dict) -> list[str]:
    out = []
    for e in c.get("emails") or []:
        v = (e.get("value") if isinstance(e, dict) else str(e)).strip().lower()
        d = v.rsplit("@", 1)[-1] if "@" in v else ""
        if d and d not in FREE_MAIL and "." in d and d not in out:
            out.append(d)
    return out


def candidate_domains(c: dict, limit: int = MAX_DOMAINS) -> list[tuple[str, str]]:
    """(домен, способ) в порядке проверки: корпоративная почта, затем название в зоне .ru, затем прочие варианты."""
    out = [(d, "email") for d in email_domains(c)]
    labels: list[str] = []
    for words in brand_words(c):
        for alt in (None, *ALT):
            t = [translit(x, alt) for x in words]
            for lab in ("".join(t), "-".join(t)) if len(t) > 1 else ("".join(t),):
                lab = re.sub(r"[^a-z0-9-]", "", lab).strip("-")
                if 3 <= len(lab) <= 40 and lab not in labels:
                    labels.append(lab)
        if len(words) >= 3:                                        # аббревиатура длинного названия
            ini = "".join(translit(x[0]) for x in words if x[0].isalpha())
            if len(ini) >= 3 and ini not in labels:
                labels.append(ini)
    guess = [f"{lab}.ru" for lab in labels]
    for lab in labels[:2]:
        guess += [f"{lab}{r}.ru" for r in REGION_SUFFIX.get(c.get("region") or "", [])] + [f"{lab}.{z}" for z in ("com", "su", "net", "org")]
    for words in brand_words(c)[:1]:
        try:
            guess.append(("-".join(words) + ".рф").encode("idna").decode("ascii"))
        except UnicodeError:
            pass
    seen = {d for d, _ in out}
    out += [(d, "guess") for d in dict.fromkeys(guess) if d not in seen]
    return out[:limit]


# ---------- поисковик ----------

YANDEX_SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
SEARCH_RESULTS = 5   # сайтов из выдачи на проверку


def search_enabled() -> bool:
    return bool(os.environ.get("PK_YANDEX_SEARCH_KEY") and os.environ.get("PK_YANDEX_FOLDER_ID"))


def search_query(c: dict) -> str:
    return " ".join(x for x in (name_core(c), c.get("city"), "официальный сайт") if x)[:400]


def search_request(c: dict) -> tuple[str, dict, bytes]:
    """(адрес, заголовки, тело) запроса к Яндекс Search API: выдача по России, по одному документу с сайта, XML."""
    body = {"query": {"searchType": "SEARCH_TYPE_RU", "queryText": search_query(c), "page": "0"},
            "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": "10", "docsInGroup": "1"},
            "maxPassages": "1", "region": "225", "l10n": "LOCALIZATION_RU", "folderId": os.environ.get("PK_YANDEX_FOLDER_ID", ""),
            "responseFormat": "FORMAT_XML"}
    headers = {"Authorization": f"Api-Key {os.environ.get('PK_YANDEX_SEARCH_KEY', '')}", "Content-Type": "application/json"}
    return YANDEX_SEARCH_URL, headers, json.dumps(body, ensure_ascii=False).encode()


def search_domains(payload: bytes | str, tried: set[str] = frozenset()) -> list[str]:
    """Сайты из ответа поисковика по порядку выдачи: без справочников, площадок и уже проверенных доменов."""
    raw = json.loads(payload)["rawData"]
    root = ET.fromstring(base64.b64decode(raw))
    out = []
    for doc in root.iter("doc"):
        url = (doc.findtext("url") or "").strip()
        h = host(url)
        if h and not denied(url) and h not in tried and h not in out:
            out.append(h)
    return out[:SEARCH_RESULTS]


def host(url: str | None) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def denied(url: str) -> bool:
    return bool(DENY_HOST.search(host(url)))


def contact_links(base_url: str, links: list[tuple[str, str]]) -> list[str]:
    """Страницы, где обычно пишут ИНН и адрес: ссылки «Контакты», «Реквизиты», «О компании» и типовые адреса этих разделов."""
    h = host(base_url)
    out = []
    for href, label in links:
        u = urljoin(base_url, href)
        if host(u) == h and (CONTACT_HREF.search(urlparse(u).path) or CONTACT_TEXT.search(label or "")) and u.split("#")[0] not in out:
            out.append(u.split("#")[0])
    # типовые адреса — только если ссылок на контакты и реквизиты почти нет (обычно они есть в меню)
    for p in CONTACT_PATHS if len(out) < 2 else ():
        u = urljoin(base_url, p)
        if u not in out and not any(x.rstrip("/") == u.rstrip("/") for x in out):
            out.append(u)
    return out[:MAX_PAGES - 1]


# ---------- подтверждение ----------

STREET = re.compile(r"(?:^|[\s,])(?:ул|улица|пр-кт|пр|проспект|пер|переулок|ш|шоссе|б-р|бульвар|пл|площадь|наб|набережная|проезд|пр-д|туп|"
                    r"тупик|мкр|микрорайон|тракт|линия|аллея)\.?\s+(?:им\.?\s+)?([А-Яа-яЁё0-9 .-]{3,40}?)\s*,\s*"
                    r"(?:д|дом|зд|здание|влд|вл|владение|стр|строение)\.?\s*(\d+)", re.I)


def _norm(s: str) -> str:
    """Слова текста строчными через один пробел: без кавычек, дефисов и знаков препинания («Ростов-на-Дону» → «ростов на дону»)."""
    return " ".join(re.findall(r"[а-яa-z0-9]+", (s or "").lower().replace("ё", "е")))


def _digits(s: str) -> str:
    """Числа без пробелов внутри: «ИНН 3435 000 717» → «ИНН 3435000717»."""
    return re.sub(r"(?<=\d)[\s-](?=\d)", "", s or "")   # \s включает неразрывный пробел


def address_parts(c: dict) -> tuple[str, str] | None:
    """(основа названия улицы, номер дома) из адреса ЕГРЮЛ."""
    m = STREET.search(c.get("address") or "")
    if not m:
        return None
    street = _norm(m.group(1)).split()
    return (street[-1][:6], m.group(2)) if street else None


def _has(text: str, phrase: str) -> bool:
    return bool(phrase) and re.search(r"(?<![а-яa-z0-9])" + re.escape(phrase) + r"(?![а-яa-z0-9])", text) is not None


def evidence(c: dict, pages: list[tuple[str, str]]) -> dict:
    """Решение по страницам одного сайта: status CONFIRMED / CANDIDATE / REJECTED и чем подтверждено."""
    inn, ogrn = c.get("inn") or "", c.get("ogrn") or ""
    all_inns = set()
    for url, text in pages:
        all_inns |= set(re.findall(r"ИНН\D{0,12}(\d{10}|\d{12})(?!\d)", _digits(text), re.I))
    if len(all_inns - {inn}) >= 3:
        return {"status": "REJECTED", "by": "directory", "inns": len(all_inns)}      # каталог организаций, а не сайт предприятия
    for url, text in pages:
        d = _digits(text)
        if inn and re.search(rf"(?<!\d){inn}(?!\d)", d):
            return {"status": "CONFIRMED", "by": "inn", "page": url}
        if ogrn and re.search(rf"(?<!\d){ogrn}(?!\d)", d):
            return {"status": "CONFIRMED", "by": "ogrn", "page": url}
    text = _norm(" ".join(t for _, t in pages))
    core = _norm(name_core(c))
    name = len(core.replace(" ", "")) >= 4 and _has(text, core)
    city = _has(text, _norm(c.get("city") or ""))
    addr = None
    parts = address_parts(c)
    if parts:
        street, house = parts
        addr = re.search(r"(?<![а-яa-z0-9])" + re.escape(street) + r"[а-яa-z]*[^0-9]{0,40}?(?<!\d)" + re.escape(house) + r"(?!\d)", text) is not None
    if name and addr and city:
        return {"status": "CONFIRMED", "by": "name+address", "name": True, "address": True, "city": True}
    if name and city:
        return {"status": "CANDIDATE", "by": "name", "name": True, "address": bool(addr), "city": True}
    return {"status": "REJECTED", "by": None, "name": bool(name), "address": bool(addr), "city": city}
