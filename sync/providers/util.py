"""Общие преобразования: даты, названия, адреса."""
from __future__ import annotations
import re


def iso_date(s: str | None) -> str | None:
    """«15.10.2024» или «2024-10-15T00:00:00» → «2024-10-15»."""
    if not s:
        return None
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m[1] if m else None


def ru_date(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else ""


def strip_tags(s: str | None) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


FORMS = {"ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ": "ООО", "АКЦИОНЕРНОЕ ОБЩЕСТВО": "АО",
         "ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ПАО", "НЕПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "НАО",
         "ОТКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ОАО", "ЗАКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ЗАО",
         "ПРОИЗВОДСТВЕННЫЙ КООПЕРАТИВ": "ПК", "ФЕДЕРАЛЬНОЕ ГОСУДАРСТВЕННОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "ФГУП",
         "МУНИЦИПАЛЬНОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "МУП", "ГОСУДАРСТВЕННОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "ГУП"}
SHORT_FORMS = sorted(set(FORMS.values()), key=len, reverse=True)


VOWELS = set("АЕЁИОУЫЭЮЯAEIOUY")


def _word(w: str) -> str:
    # аббревиатуры (НПО, ЖКХ, НЗНП, НВТЗ) оставляем заглавными: до 3 букв или без гласных; остальные слова — с заглавной буквы
    if len(w) <= 3 or not re.fullmatch(r"[А-ЯЁA-Z]+", w) or not VOWELS & set(w):
        return w
    return w[0] + w[1:].lower()


def nice_name(short: str | None, legal: str | None = None) -> tuple[str, str]:
    """Название для каталога из реестрового: 'ООО "НПО "ОРТЕХ-ЖКХ"' → ('ООО «НПО «Ортех-ЖКХ»»', 'НПО «Ортех-ЖКХ»')."""
    s = (short or legal or "").strip()
    form = ""
    for full, abbr in FORMS.items():
        if s.upper().startswith(full):
            s, form = s[len(full):].strip(), abbr
            break
    else:
        for abbr in SHORT_FORMS:
            if re.match(rf"{abbr}\b", s):
                s, form = s[len(abbr):].strip(), abbr
                break
    body = re.sub(r"[А-ЯЁA-Z]+", lambda m: _word(m[0]), s)
    # прямые кавычки → ёлочки: открывающая после пробела/начала/кавычки, остальные закрывающие
    out, depth = [], 0
    for i, ch in enumerate(body):
        if ch == '"':
            prev = body[i - 1] if i else " "
            if prev in " («\"" and (i + 1 < len(body) and body[i + 1] not in ' "»)'):
                out.append("«"); depth += 1
            else:
                out.append("»"); depth = max(0, depth - 1)
        else:
            out.append(ch)
    body = "".join(out) + "»" * depth
    body = re.sub(r"\s+", " ", body).strip()
    # внешние кавычки снимаем, только если они обрамляют всё название: «НПО «Ортех»» → НПО «Ортех»
    short_name = body
    if body.startswith("«") and body.endswith("»"):
        depth = 0
        for i, ch in enumerate(body):
            depth += (ch == "«") - (ch == "»")
            if depth == 0:
                break
        if i == len(body) - 1:
            short_name = body[1:-1]
    return (f"{form} {body}".strip() if form else body), short_name


ABBR = {"ОБЛ.": "обл.", "ОБЛАСТЬ": "область", "Г.": "г.", "УЛ.": "ул.", "Д.": "д.", "ПР-КТ": "пр-кт", "ПР-Д": "пр-д",
        "ПЕР.": "пер.", "Р-Н": "р-н", "ПОМ.": "пом.", "ОФИС": "офис", "КОРП.": "корп.", "СТР.": "стр.", "ЗД.": "зд.",
        "ТЕР.": "тер.", "ШОССЕ": "шоссе", "П.": "п.", "С.": "с.", "Р.П.": "р.п.", "Г.О.": "г.о.", "ПЛ.": "пл.",
        "ПРОМЗОНА": "промзона", "ВЛД.": "влд.", "КМ": "км", "ТУП.": "туп.", "Б-Р": "б-р", "НАБ.": "наб.",
        "ПОМЕЩ.": "помещ.", "КВ.": "кв.", "ЛИТЕР": "литер", "СООР.": "соор."}


def nice_address(a: str | None) -> str | None:
    """«404122, ВОЛГОГРАДСКАЯ ОБЛАСТЬ, Г. ВОЛЖСКИЙ, УЛ. ГОРЬКОГО, Д. 1» → «404122, Волгоградская область, г. Волжский, ул. Горького, д. 1»."""
    if not a:
        return None
    if a != a.upper():
        return a.strip()
    a = re.sub(r"\b(Г|УЛ|Д|П|С|ПОС|ОБЛ)\.(?=[А-ЯЁ]{2})", r"\1. ", a)   # «Г.МОСКВА» → «Г. МОСКВА»
    words = []
    for w in re.split(r"(\s+|,)", a):
        if w in ABBR:
            words.append(ABBR[w])
        elif re.search(r"[А-ЯЁ]", w):
            words.append("-".join(p[:1] + p[1:].lower() for p in w.split("-")))
        else:
            words.append(w)
    out = re.sub(r"\s*,\s*", ", ", "".join(words)).strip(", ")
    # муниципальное деление (г.о., м.р-н, с.п.) для почтового адреса лишнее
    return ", ".join(p for p in out.split(", ") if not re.match(r"(г\.о\.|м\.р-н|м\.о\.|с\.п\.|г\.п\.|вн\.тер\.г\.|муниципальный|городской округ|сельское поселение)", p, re.I))


def nice_city(c: str | None) -> str | None:
    """«РОСТОВ-НА-ДОНУ» → «Ростов-на-Дону», «БЫКОВ ОТРОГ» → «Быков Отрог»."""
    if not c:
        return None
    if not c.isupper():
        return c.strip()
    words = []
    for w in c.strip().split():
        parts = [p.lower() if i and p in ("НА", "ДЕ", "ЛЕ") else p[:1] + p[1:].lower() for i, p in enumerate(w.split("-"))]
        words.append("-".join(parts))
    return " ".join(words)


def address_numbers(a: str | None) -> tuple:
    """Числа адреса (индекс, дом, корпус) — для сравнения адресов, записанных в разном формате."""
    return tuple(re.findall(r"\d+", a or ""))


def same_address(old: str | None, new: str | None) -> bool:
    """Тот же адрес, если все числа прежней записи есть в новой: реестр часто добавляет офис или помещение."""
    if (old or "").strip().lower() == (new or "").strip().lower():
        return True
    o, n = address_numbers(old), address_numbers(new)
    return bool(o) and set(o) <= set(n) and o[0] == n[0]


def city_from_address(a: str | None) -> str | None:
    """Населённый пункт из адреса: «..., г. Волжский, ул. ...» → «Волжский»."""
    m = re.search(r"(?:^|,\s*)(?:г|с|п|рп|р\.п|пгт|ст-ца|х)\.?\s+([А-ЯЁ][а-яё-]+(?:\s[А-ЯЁ][а-яё-]+)?)", a or "")
    return m[1] if m else None
