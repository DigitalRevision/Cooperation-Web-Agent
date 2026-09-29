"""AI Parser → Structured Query → сопоставление по базе. Те же правила, что и во фронтенде (site/src/02-match.js).

AI (LLM) используется только для разбора запроса в структуру. Результаты — только из базы; каждое основание ссылается на источник.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from .repo import DataRepo

W = r"(?<![а-яa-z])"

LEX = [
    ("насос", r"насос", ["насос"], "28.13", "28.13"),
    ("компрессор", r"компрессор", ["компрессор"], "28.13", "28.13"),
    ("трубопроводная арматура", r"арматур", ["арматур"], "28.14", None),
    ("кран", r"кран|козлов|мостов", ["кран"], "28.22", "28.22.42"),
    ("таль", W + r"тал[иья]|тельфер", ["тал", "тельфер"], "28.22", None),
    ("грейферная тележка", r"грейфер", ["грейфер"], "28.22", None),
    ("подшипник", r"подшипник", ["подшипник"], "28.15", "28.15.1"),
    ("кварцевый резонатор", r"резонатор|кварц", ["резонатор", "кварц"], "26.11", "26.11.2"),
    ("генератор", r"генератор", ["генератор"], "26.11", None),
    ("труба", r"труб(?!опровод|н)", ["труб"], "24.20", None),
    ("заготовка", r"трубн\w* заготов|заготовк|блюм", ["заготовк", "блюм"], "24.10", "24.10.6"),
    ("прокат", r"прокат|лист", ["прокат"], "24.10", "24.10.6"),
    ("буровой инструмент", r"штанг|коронк|перфоратор|буров", ["штанг", "коронк", "буров"], "28.92", "28.92"),
    ("оправки для трубных станов", r"оправк|прошивн|раскатн", ["оправк"], "28.91", None),
    ("абразивный инструмент", r"абразив|шлиф", ["абразив", "шлиф"], "23.91", None),
    ("карбид кремния", r"карбид", ["карбид"], "20.13", "20.13"),
    ("огнеупоры", r"огнеупор", ["огнеупор"], "23.20", None),
    ("резервуар", r"резервуар|емкост", ["резервуар"], "25.29", None),
    ("металлоконструкции", r"металлоконструкц|дымов", ["металлоконструкц", "дымов"], "25.11", "25.11"),
    ("котельное оборудование", r"котл|котель", ["котель"], None, None),
    ("сосуд под давлением", r"сосуд", ["сосуд"], None, None),
    ("судовые закрытия", r"судов|двер|люк", ["судов", "двер", "люк"], None, None),
    ("катализатор", r"катализатор", ["катализатор"], "20.59", None),
    ("запчасти", r"запчаст|запасн", ["запчаст"], None, None),
]
TECH = [
    ("термическая обработка", r"термообработ|термическ|закалк|отпуск", ["термическ", "термообработ"], "25.61"),
    ("механическая обработка", r"мехобработ|механообработ|механическ\w* обработ|токарн|фрезер", ["механическ", "фрезер", "токарн"], "25.62"),
    ("штамповка", r"штамповк|ковк|гкм", ["штамповк"], "25.50"),
    ("сварка", r"сварк|сварн|свароч", ["сварк", "сварн", "свароч"], None),
    ("резка", r"резк|раскрой", ["резк", "раскрой"], "25.62"),
    ("неразрушающий контроль", r"неразрушающ|дефектоскоп|испытан", ["неразрушающ", "испытан"], None),
    ("вальцовка", r"вальцовк|вальц", ["вальц"], None),
    ("прокатное производство", r"прокатн\w* производ", ["прокатн"], None),
]
MATERIALS = [("нержавеющая сталь", r"нержаве", ["нержаве"]), ("сталь", r"стал[ьи]|стальн", ["стал"]), ("чугун", r"чугун", ["чугун"]),
             ("алюминий", r"алюмини", ["алюмини"]), ("медь", r"медь|медн", ["мед"])]
# Порядок важен: берётся первая совпавшая отрасль, как во фронтенде
INDUSTRY = [("нефтегазовое оборудование", r"нефтегаз|нефт|газов", ["нефтегаз", "газопровод", "нефт"]),
            ("атомная промышленность", r"атомн", ["атомн"]),
            ("горнодобывающая промышленность", r"горн|шахт|рудн", ["горн", "добыч"]),
            ("металлургия", r"металлург|доменн", ["металлург", "доменн", "стан"]),
            ("судостроение", r"судостро|судов", ["судов"]),
            ("радиоэлектроника", r"электрон|радио", ["электрон", "пьезо"])]
UNITS = [(r"^(т|тн|тонн\w*)$", "т"), (r"^(кг|килограмм\w*)$", "кг"), (r"^(шт|штук\w*|ед|единиц\w*)$", "шт"), (r"^(м2|м²|кв\.?м)$", "м²"),
         (r"^(м3|м³|куб\.?м)$", "м³"), (r"^(м|метр\w*)$", "м"), (r"^(л|литр\w*)$", "л"), (r"^(компл\w*|комплект\w*)$", "комплект"), (r"^(парти\w*)$", "партия")]
# Все субъекты РФ, коды как в sync/config.py. Порядок важен: берётся первый совпавший («ямало-ненецк» раньше «ненецк»,
# «алтайск» раньше «алтай», «московск» раньше «москв», «нижегород» раньше «новгород»)
REGIONS = [(r"волгоград|волжск|камышин|урюпинск|михайловк|фролов", "34"), (r"орлов|ливн", "57"), (r"ростов", "61"),
           (r"астрахан", "30"), (r"саратов", "64"), (r"воронеж", "36"), (r"калмык|элист", "08"),
           (r"адыге|майкоп", "01"), (r"башкир|башкорт", "02"), (r"бурят|улан-удэ", "03"), (r"алтайск|барнаул", "22"), (r"алта[йе]", "04"),
           (r"дагестан|махачкал", "05"), (r"ингуш", "06"), (r"кабардин|нальчик", "07"), (r"карачаев|черкесск", "09"),
           (r"карели|петрозаводск", "10"), (r"коми" + r"(?![а-я])|сыктывкар", "11"), (r"марий|йошкар", "12"), (r"мордов|саранск", "13"),
           (r"якут", "14"), (r"осети|владикавказ", "15"), (r"татарст|казан", "16"), (r"тыв[аеы]|кызыл", "17"), (r"удмурт|ижевск", "18"),
           (r"хакас|абакан", "19"), (r"чечн|чеченск|грозн", "20"), (r"чуваш|чебоксар", "21"), (r"краснодар|кубан", "23"),
           (r"красноярск", "24"), (r"приморск|владивосток", "25"), (r"ставропол", "26"), (r"хабаровск", "27"), (r"амурск|благовещенск", "28"),
           (r"архангельск", "29"), (r"белгород", "31"), (r"брянск", "32"), (r"владимир", "33"), (r"вологод|череповец", "35"),
           (r"иванов", "37"), (r"иркутск", "38"), (r"калининград", "39"), (r"калуж|калуг", "40"), (r"камчат", "41"),
           (r"кемеров|кузбасс|новокузнецк", "42"), (r"киров", "43"), (r"костром", "44"), (r"курган", "45"), (r"курск", "46"),
           (r"ленинград", "47"), (r"липецк", "48"), (r"магадан", "49"), (r"московск|подмосков", "50"), (r"мурманск", "51"),
           (r"нижегород|нижн\w* новгород", "52"), (r"новгород", "53"), (r"новосибирск", "54"), (r"омск", "55"), (r"оренбург", "56"),
           (r"пенз", "58"), (r"перм", "59"), (r"псков", "60"), (r"рязан", "62"), (r"самар|тольятти", "63"), (r"сахалин", "65"),
           (r"свердловск|екатеринбург", "66"), (r"смоленск", "67"), (r"тамбов", "68"), (r"тверск|твер[ьи](?![а-я])", "69"), (r"томск", "70"), (r"тул[аеьы]|тульск", "71"),
           (r"тюмен", "72"), (r"ульянов", "73"), (r"челябинск", "74"), (r"забайкал|чита", "75"), (r"ярослав", "76"), (r"москв", "77"),
           (r"петербург|спб", "78"), (r"еврейск|биробиджан", "79"), (r"ямало|ямал", "89"), (r"ненецк", "83"), (r"ханты|югр|сургут", "86"),
           (r"чукот", "87"), (r"запорож", "90"), (r"крым|симферопол", "91"), (r"севастопол", "92"), (r"донецк|днр", "93"),
           (r"луганск|лнр", "94"), (r"херсон", "95")]
# Слова запроса, которых нет в словарях (реестр Минпромторга — тысячи наименований вне словаря), ищутся в названиях продукции.
# Не ищутся служебные слова заявки: «нужен», «поставка», «производство», единицы, регионы
FREE_STOP = re.compile(r"^(нуж|требует|требуют|купит|закуп|заказ|поставк|поставщ|поставит|доставк|производств|производител|изготовлен|"
                       r"изготовит|изготавлива|предприят|завод|компани|организац|фирм|срочн|недорог|оптов|оборудован|продукц|издели|товар|"
                       r"услуг|област|район|республик|росси|ищем|найти|можно|очень|также|котор|как(ой|ая|ие|ое|ую|их)|любо|любы|други|друго|"
                       r"штук|тонн|килограмм|метр|литр|комплект|месяц|недел|ежемесяч|ежегод|объем|количеств|размер|срок|качеств|интерес|"
                       r"предлож|подскаж|через|около|более|менее|всего|этого|этой|этих|сейчас|сегодня|желательно|примерно|чтобы|хотим|хочу|"
                       r"прошу|просим|гост|промышлен|работ)|^(цена|цены|цену|цене|опт|оптом|партия|партии|партию|край|крае|город|города|есть|плюс|года|лет|"
                       r"либо|если|тоже|надо|свой|свое|свои|наша|наши|ваша|ваши)$")
WORD = re.compile(r"[а-яa-z][а-яa-z0-9-]*")


@dataclass
class StructuredQuery:
    raw: str
    products: list[dict] = field(default_factory=list)
    technologies: list[dict] = field(default_factory=list)
    material: dict | None = None
    grades: list[str] = field(default_factory=list)
    industry: dict | None = None
    okpd2: str | None = None
    okved: str | None = None
    volume: float | None = None
    unit: str | None = None
    period: str | None = None
    region: str | None = None
    missing: list[str] = field(default_factory=list)
    engine: str = "rules"


def _stem(w: str) -> str:
    """Основа слова без окончания: «кабель» → «кабел», «симметричный» → «симметричн», «шина» → «шин»."""
    if len(w) >= 7:
        return w[:-2]
    if len(w) >= 5 or w[-1] in "аяоеуюыи":
        return w[:-1]
    return w


def free_words(t: str) -> tuple[list[str], list[str]]:
    """Слова запроса вне словарей и их основы."""
    known = [x[1] for x in LEX] + [x[1] for x in TECH] + [x[1] for x in MATERIALS] + [x[1] for x in INDUSTRY] + [x[0] for x in REGIONS]
    words = [w for w in dict.fromkeys(WORD.findall(t)) if len(w) >= 4 and not FREE_STOP.search(w) and not any(re.search(r, w) for r in known)]
    return words, list(dict.fromkeys(_stem(w) for w in words))


def free_required(n: int) -> int:
    """Сколько основ из n должно встретиться в названии позиции: два слова — оба, дальше — не меньше 60 %."""
    return n if n <= 2 else -(-n * 3 // 5)


def parse_query(text: str) -> StructuredQuery:
    t = " " + text.lower().replace("ё", "е") + " "
    q = StructuredQuery(raw=text)
    q.products = [dict(label=l, stems=s, okpd2=o, okved=v) for l, r, s, o, v in LEX if re.search(r, t)]
    q.technologies = [dict(label=l, stems=s, okpd2=o) for l, r, s, o in TECH if re.search(r, t)]
    q.material = next((dict(label=l, stems=s) for l, r, s in MATERIALS if re.search(r, t)), None)
    q.industry = next((dict(label=l, stems=s) for l, r, s in INDUSTRY if re.search(r, t)), None)
    q.grades = re.findall(r"\b\d{1,2}[ХГНМТЮСФКВРА]+[0-9ХГНМТЮСФКВРА]*\b", text)
    m = re.search(r"(\d[\d\s]*[.,]?\d*)\s*(тонн\w*|тн|т|кг|килограмм\w*|шт|штук\w*|единиц\w*|м2|м²|м3|м³|метр\w*|м|литр\w*|л|комплект\w*|компл|парти\w*)(?=[\s.,;/]|$)", t)
    if m:
        q.volume = float(m.group(1).replace(" ", "").replace(",", "."))
        q.unit = next((n for r, n in UNITS if re.match(r, m.group(2))), None)
    q.period = "мес" if re.search(r"в месяц|/мес|ежемесячн", t) else "год" if re.search(r"в год|/год|ежегодн", t) else None
    q.region = next((c for r, c in REGIONS if re.search(W + f"(?:{r})", t)), None)
    if not (q.products or q.technologies):
        words, stems = free_words(t)
        if stems:
            q.products = [dict(label=" ".join(words), stems=stems, okpd2=None, okved=None, free=True)]
    first = (q.products or q.technologies or [None])[0]
    q.okpd2 = first.get("okpd2") if first else None
    q.okved = next((p["okved"] for p in q.products if p.get("okved")), None)
    if not (q.products or q.technologies or q.industry):
        q.missing.append("product")
    if q.material and not q.okpd2:
        q.missing.append("okpd2")
    if q.volume is None:
        q.missing.append("volume")
    if not q.region:
        q.missing.append("region")
    return q


def _has(text: str, stems: list[str]) -> bool:
    x = (text or "").lower().replace("ё", "е")
    return any(re.search(W + re.escape(s), x) for s in stems)


def match_company(q: StructuredQuery, c: dict, repo: DataRepo, city: str | None = None) -> dict:
    crit = []
    prods = [p for p in c["products"] if not repo.sources.get(p["source_id"], {}).get("is_disabled")]
    stems = [s for p in q.products for s in p["stems"]]
    tstems = [s for p in q.technologies for s in p["stems"]]
    hits = []
    # источник реквизитов: официальный ЕГРЮЛ, затем «Прозрачный бизнес», затем агрегатор (как egrulSrc во фронтенде)
    egrul = next((s["id"] for t in ("FNS_EGRUL", "FNS_PB", "EGRUL_AGGREGATOR") for s in c["sources"] if s["source_type"] == t), None)
    free = next((p for p in q.products if p.get("free")), None)
    if free:
        # слова вне словаря: позиция подходит, если в названии или категории есть достаточно слов запроса; все слова — «совпадает»
        res = [re.compile(W + re.escape(s)) for s in free["stems"]]
        need = free_required(len(res))
        scored = sorted(((sum(1 for r in res if r.search(x)), i, p) for i, p in enumerate(prods)
                         for x in [f"{p['name']} {p.get('category') or ''}".lower().replace("ё", "е")]), key=lambda t: (-t[0], t[1]))
        hits = [p for n, _, p in scored if n >= need]
        full = bool(scored) and scored[0][0] == len(res)
        crit.append(dict(k="PRODUCT_MATCH", r="yes" if full else "compat" if hits else "no",
                         why="; ".join(p["name"] for p in hits[:3]) or "Нет совпадений в подтверждённой продукции", source_id=hits[0]["source_id"] if hits else None))
    elif stems:
        hits = [p for p in prods if _has(f"{p['name']} {p['category']} {p.get('description') or ''}", stems)]
        crit.append(dict(k="PRODUCT_MATCH", r="yes" if hits else "no", why="; ".join(p["name"] for p in hits[:3]) or "Нет совпадений в подтверждённой продукции", source_id=hits[0]["source_id"] if hits else None))
    elif q.industry:
        hits = [p for p in prods if _has(p["name"] + " " + (p.get("description") or "") + " " + (c.get("subindustry") or ""), q.industry["stems"])]
        ind = _has((c.get("subindustry") or "") + " " + (c.get("industry") or ""), q.industry["stems"])
        crit.append(dict(k="PRODUCT_MATCH", r="compat" if hits or ind else "no", why=c.get("subindustry"), source_id=hits[0]["source_id"] if hits else None))
    if q.okpd2:
        oh = [p for p in prods if p.get("okpd2") and (p["okpd2"]["code"].startswith(q.okpd2) or q.okpd2.startswith(p["okpd2"]["code"]))]
        src = any(p["okpd2"]["status"] != "INFERRED" for p in oh)
        crit.append(dict(k="OKPD2_MATCH", r="yes" if src else "part" if oh else "none", why="Код из источника" if src else "Код присвоен по классификатору — требует подтверждения" if oh else "Нет кода ОКПД2"))
        hits = hits or oh
    if q.okved:
        ov = c.get("okved_main")
        if not ov:
            crit.append(dict(k="OKVED", r="none", why="ОКВЭД не подтверждён"))
        elif ov == q.okved or ov.startswith(q.okved + "."):
            crit.append(dict(k="EXACT_OKVED_MATCH", r="yes", why=f"Основной ОКВЭД {ov}", source_id=egrul))
        elif ov.split(".")[0] == q.okved.split(".")[0]:
            crit.append(dict(k="COMPATIBLE_OKVED", r="compat", why=f"Основной ОКВЭД {ov}, тот же класс", source_id=egrul))
        else:
            crit.append(dict(k="OKVED", r="no", why=f"Основной ОКВЭД {ov}"))
    if q.material or q.grades:
        mats = c["materials"] + [m for p in prods for m in p.get("materials", [])]
        want = [g.lower() for g in q.grades] or q.material["stems"]
        hit = next((m for m in mats if _has(m["name"], want)), None)
        crit.append(dict(k="MATERIAL_MATCH", r="yes" if hit else "no" if mats else "none", why=hit["name"] if hit else "Материалы не указаны в источниках" if not mats else "Другие материалы", source_id=hit["source_id"] if hit else None))
    if tstems:
        hit = next((t for t in c["technologies"] if _has(t["name"], tstems)), None) or next((p for p in prods if p["kind"] == "service" and _has(p["name"], tstems)), None)
        # заявленная в ЕГРЮЛ возможность по ОКВЭД — только «совместимо», не подтверждение
        cap = None if hit else next((x for x in c.get("capabilities_declared") or [] if _has(x["name"], tstems)), None)
        crit.append(dict(k="TECHNOLOGY_MATCH", r="yes" if hit else "compat" if cap else "no" if c["technologies"] else "none",
                         why=hit["name"] if hit else f"По ОКВЭД {', '.join(cap['okved'])}: {cap['name']} (заявлено, не подтверждено)" if cap
                         else "Указаны другие технологии" if c["technologies"] else "Технологии не указаны в источниках",
                         source_id=hit.get("source_id") if hit else ((c.get("registry") or {}).get("source_ids") or {}).get("pb") if cap else None))
        if hit and not hits:
            hits = [p for p in prods if p["kind"] == "service" and _has(p["name"], tstems)]
    if q.region:
        crit.append(dict(k="GEOGRAPHICAL_MATCH", r="yes" if c["region"] == q.region else "no",
                         why=", ".join(filter(None, [(repo.regions.get(c["region"]) or {}).get("name", "Регион не указан"), c.get("city")]))))
    if q.volume is not None:
        cap = next((x for x in c["capacities"] if not x.get("historical") and x.get("unit") and q.unit and x["unit"].startswith(q.unit)), None)
        crit.append(dict(k="CAPACITY_MATCH", r="part" if cap else "none", why=f"Опубликовано: {cap['text']}; достаточность подтверждает предприятие" if cap else "Мощность и доступный объём не опубликованы", source_id=cap["source_id"] if cap else None))
    yes = sum(1 for x in crit if x["r"] == "yes")
    substantive = any((x["k"] in ("PRODUCT_MATCH", "OKPD2_MATCH", "TECHNOLOGY_MATCH") and x["r"] in ("yes", "part", "compat")) or x["k"] == "EXACT_OKVED_MATCH" for x in crit)
    verdict = ("Предприятие соответствует части критериев." if any(x["r"] == "no" for x in crit)
               else "Соответствует указанным критериям; часть параметров требует подтверждения у поставщика." if any(x["r"] in ("none", "part") for x in crit)
               else "Соответствует всем указанным критериям по данным источников.")
    return dict(company_id=c["id"], name=c["name"], verification_status=c["verification_status"], criteria=crit,
                confirmed=yes, applicable=len(crit), substantive=substantive, verdict=verdict,
                products=[p["id"] for p in hits], distance_km=repo.distance_km(city, c["city"]) if city else None)


def search(q: StructuredQuery, repo: DataRepo, include_unverified=False, city=None, exclude=()) -> list[dict]:
    ok = {"VERIFIED", "PARTIALLY_VERIFIED"} | ({"UNVERIFIED", "OUTDATED"} if include_unverified else set())
    res = [match_company(q, c, repo, city) for c in repo.companies.values() if c["verification_status"] in ok and c["id"] not in exclude]
    res = [r for r in res if r["substantive"]]
    return sorted(res, key=lambda r: (-r["confirmed"], r["distance_km"] if r["distance_km"] is not None else 1e9))


def query_dict(q: StructuredQuery) -> dict:
    return asdict(q)
