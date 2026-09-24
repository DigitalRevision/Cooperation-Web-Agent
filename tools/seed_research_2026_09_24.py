"""
Первичный сбор данных, выполненный 24.09.2026 вручную (веб-запросы к открытым источникам).
Каждое значение хранится вместе с id источника. Ничего не дополнялось «по памяти»:
если значения нет в источнике — поле = None, а интерфейс показывает «Нет открытых данных» / «Не указано».

ОКПД2 у продукции источниками НЕ публикуется. Код класса присвоен по классификатору
(okpd2.status = "INFERRED") и требует подтверждения предприятием или ГИСП.

Запуск: python tools/seed_research_2026_09_24.py  -> пишет data/**
"""
import glob, json, os, shutil, sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
D = "2026-09-24"

# ---------- справочник ОКВЭД (только коды, встреченные в источниках) ----------
OKVED = {
    "28.99.9": "Производство оборудования специального назначения, не включенного в другие группировки",
    "25.11": "Производство строительных металлических конструкций, изделий и их частей",
    "28.22.42": "Производство прочих подъемных кранов",
    "28.92": "Производство машин и оборудования для добычи полезных ископаемых и строительства",
    "28.15.1": "Производство шариковых и роликовых подшипников",
    "26.11.2": "Производство диодов, транзисторов и прочих полупроводниковых приборов, включая светоизлучающие диоды, пьезоэлектрические приборы и их части",
    "24.10.6": "Производство сортового горячекатаного проката и катанки",
    "20.13": "Производство прочих основных неорганических химических веществ",
    "46.72.2": "Торговля оптовая металлами в первичных формах",
    "28.13": "Производство прочих насосов и компрессоров",
}

# ---------- справочник классов ОКПД2 (используются только как INFERRED) ----------
OKPD2 = {
    "28.13": "Насосы и компрессоры прочие",
    "28.14": "Краны, клапаны и аналогичная арматура",
    "28.22": "Оборудование подъемно-транспортное",
    "28.15": "Подшипники, зубчатые передачи, элементы механических передач и приводов",
    "28.91": "Оборудование для металлургии и его части",
    "28.92": "Машины и оборудование для добычи полезных ископаемых и строительства",
    "26.11": "Компоненты электронные",
    "24.10": "Продукты основные черной металлургии: железо, чугун, сталь и ферросплавы",
    "24.20": "Трубы, профили пустотелые и их фитинги стальные",
    "23.91": "Изделия абразивные",
    "23.20": "Изделия огнеупорные",
    "20.13": "Вещества химические неорганические основные прочие",
    "20.59": "Продукты химические прочие, не включенные в другие группировки",
    "25.11": "Конструкции металлические и их части",
    "25.29": "Резервуары, цистерны и аналогичные емкости из металлов прочие",
    "25.50": "Услуги по ковке, прессованию, объемной и листовой штамповке и профилированию листового металла; изготовлению изделий методом порошковой металлургии",
    "25.61": "Услуги по обработке металлов и нанесению покрытий на металлы",
    "25.62": "Услуги по механической обработке металлических изделий",
}

REGIONS = {
    "34": {"code": "34", "name": "Волгоградская область", "pilot": True},
    "57": {"code": "57", "name": "Орловская область", "pilot": False},
}

# Координаты центров городов — только для расчёта расстояния «по прямой между городами».
CITIES = {
    "Волгоград": [48.7080, 44.5133],
    "Волжский": [48.7858, 44.7797],
    "Камышин": [50.0833, 45.4000],
    "Урюпинск": [50.7964, 42.0056],
    "Ливны": [52.4281, 37.6044],
}

def src(id, url, type_, title, priority, params, note=None, status="OK"):
    return {"id": id, "source_url": url, "source_type": type_, "source_title": title,
            "priority": priority, "source_date": None, "last_verified_at": D,
            "confirms": params, "fetch_status": status, "note": note}

def okpd(code, status="INFERRED"):
    return {"code": code, "name": OKPD2[code], "status": status} if code else None

def prod(pid, name, kind, category, okpd2, src_id, params=None, desc=None):
    return {"id": pid, "name": name, "kind": kind, "category": category, "okpd2": okpd(okpd2),
            "description": desc, "params": params or [], "materials": [],
            "price": None, "volume": None, "min_batch": None, "lead_time_production": None,
            "lead_time_delivery": None, "availability": None, "warehouse_id": None,
            "photo": None, "source_id": src_id, "last_verified_at": D}

COMPANIES = []

# 1. ОАО «Волгограднефтемаш»
COMPANIES.append({
 "id": "vnm", "name": "ОАО «Волгограднефтемаш»", "short": "Волгограднефтемаш",
 "legal_name": "ОТКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО \"ВОЛГОГРАДНЕФТЕМАШ\"",
 "inn": "3446003396", "ogrn": "1023404238384", "kpp": "344601001", "reg_date": "1993-08-02",
 "legal_status": "Действующая", "region": "34", "city": "Волгоград",
 "address": "400011, г. Волгоград, ул. Электролесовская, 45",
 "site": "https://www.vnm.ru/", "phones": [], "emails": ["office@vnm.ru"],
 "okved_main": "28.99.9", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Нефтегазовое и энергетическое оборудование",
 "description": None,
 "technologies": [{"name": "Испытания и неразрушающий контроль", "source_id": "vnm-site"}],
 "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "VERIFIED",
 "sources": [
   src("vnm-site", "https://www.vnm.ru/", "OFFICIAL_SITE", "Официальный сайт ОАО «Волгограднефтемаш»", 1,
       ["название", "адрес", "e-mail", "категории продукции", "услуги"]),
   src("vnm-egrul", "https://www.1cont.ru/contragent/1023404238384", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [],
 "products": [
   prod("vnm-vessels", "Сосуды под давлением", "product", "Оборудование нефтегазовое", None, "vnm-site"),
   prod("vnm-nuclear", "Оборудование для атомной промышленности", "product", "Оборудование энергетическое", None, "vnm-site"),
   prod("vnm-pumps", "Центробежные насосы", "product", "Насосы", "28.13", "vnm-site"),
   prod("vnm-pig", "Блоки камер приема и запуска средств очистки и диагностики", "product", "Оборудование трубопроводное", None, "vnm-site"),
   prod("vnm-valves", "Трубопроводная арматура", "product", "Арматура", "28.14", "vnm-site"),
   prod("vnm-eng", "Инженерно-конструкторские услуги", "service", "Инжиниринг", None, "vnm-site"),
   prod("vnm-tech", "Инженерно-технологические услуги", "service", "Инжиниринг", None, "vnm-site"),
   prod("vnm-ndt", "Испытания и неразрушающий контроль", "service", "Контроль качества", None, "vnm-site"),
   prod("vnm-service", "Сервисные услуги", "service", "Сервис", None, "vnm-site"),
 ],
})

# 2. ООО «ВЗСМ»
COMPANIES.append({
 "id": "vzsm", "name": "ООО «Волгоградский завод судового машиностроения»", "short": "ВЗСМ",
 "legal_name": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ \"ВОЛГОГРАДСКИЙ ЗАВОД СУДОВОГО МАШИНОСТРОЕНИЯ\"",
 "inn": "3461065380", "ogrn": "1193443012553", "kpp": "346101001", "reg_date": "2019-10-07",
 "legal_status": "Действующая", "region": "34", "city": "Волгоград",
 "address": "400112, г. Волгоград, ул. им. Арсеньева, д. 2",
 "site": "http://vzsm34.ru/", "phones": ["+7 (8442) 98-85-91"], "emails": ["marketing@vzsm34.ru"],
 "okved_main": "25.11", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Судовое машиностроение",
 "description": "Производитель штампованных судовых закрытий (двери и люки) с приёмкой Минобороны РФ — по данным отраслевой ассоциации.",
 "technologies": [{"name": "Листовая штамповка", "source_id": "vzsm-assoc"}],
 "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "PARTIALLY_VERIFIED",
 "sources": [
   src("vzsm-site", "http://vzsm34.ru/", "OFFICIAL_SITE", "Официальный сайт ВЗСМ", 1, [],
       note="Краулер не смог прочитать сайт: циклическое перенаправление https→http. Перечень продукции требует проверки по сайту вручную.", status="REDIRECT_LOOP"),
   src("vzsm-assoc", "https://anosudprom.ru/volgogradskij-zavod-sudovogo-mashinostroeniya/", "INDUSTRY_CATALOG", "Отраслевой каталог АНО «Судпром»", 11,
       ["адрес (офис 17)", "телефон", "e-mail", "сайт", "описание продукции"]),
   src("vzsm-egrul", "https://www.1cont.ru/contragent/1193443012553", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [
   {"field": "Продукция", "values": [{"value": "Штампованные судовые закрытия (двери и люки)", "source_id": "vzsm-assoc"}],
    "note": "Официальный сайт недоступен для автоматической проверки — продукция подтверждена только вторичным источником."}
 ],
 "products": [
   prod("vzsm-doors", "Судовые двери штампованные", "product", "Судовое оборудование", None, "vzsm-assoc"),
   prod("vzsm-hatches", "Судовые люки штампованные", "product", "Судовое оборудование", None, "vzsm-assoc"),
 ],
})

# 3. АО «Урюпинский крановый завод»
COMPANIES.append({
 "id": "ukz", "name": "АО «Урюпинский крановый завод»", "short": "УКЗ",
 "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"УРЮПИНСКИЙ КРАНОВЫЙ ЗАВОД\"",
 "inn": "3438000352", "ogrn": "1023405761510", "kpp": "343801001", "reg_date": "1992-06-17",
 "legal_status": "Действующая", "region": "34", "city": "Урюпинск",
 "address": "403113, г. Урюпинск, ул. Штеменко, д. 20",
 "site": "https://urupinsk-kran.ru/",
 "phones": ["+7 844 261 38 66 (приёмная)", "+7 844 261 38 68 (тали)", "+7 844 261 34 49 (запчасти)", "+7 844 261 34 99 (ОМТС)"],
 "emails": ["info@ukran.ru"],
 "okved_main": "28.22.42", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Подъёмно-транспортное оборудование",
 "description": None,
 "technologies": [], "materials": [],
 "capacities": [{"text": "Более 300 единиц в год", "value": 300, "qualifier": "более", "unit": "шт/год", "source_id": "ukz-site"}],
 "sites": [], "certificates": [{"name": "Подтверждение производства на территории РФ (ПП РФ № 719) — электрические канатные тали; сведения в реестре российской продукции", "source_id": "ukz-site"}],
 "verification_status": "VERIFIED",
 "sources": [
   src("ukz-site", "https://urupinsk-kran.ru/", "OFFICIAL_SITE", "Официальный сайт АО «УКЗ»", 1,
       ["название", "адрес", "телефоны", "e-mail", "продукция", "грузоподъёмность", "производственная мощность", "подтверждение ПП 719"]),
   src("ukz-egrul", "https://www.1cont.ru/contragent/1023405761510", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [],
 "products": [
   prod("ukz-bridge", "Мостовые краны", "product", "Краны", "28.22", "ukz-site", [{"name": "Грузоподъёмность", "value": None}]),
   prod("ukz-gantry", "Козловые краны", "product", "Краны", "28.22", "ukz-site", [{"name": "Грузоподъёмность", "value": "до 32 т"}]),
   prod("ukz-semigantry", "Полукозловые краны", "product", "Краны", "28.22", "ukz-site", [{"name": "Грузоподъёмность", "value": "3,2–20 т"}]),
   prod("ukz-jib", "Консольные краны", "product", "Краны", "28.22", "ukz-site", [{"name": "Исполнение", "value": "настенные поворотные"}, {"name": "Грузоподъёмность", "value": "до 5 т"}]),
   prod("ukz-hoists", "Тельферы и тали", "product", "Тали", "28.22", "ukz-site", [{"name": "Грузоподъёмность", "value": "0,5–63 т"}]),
   prod("ukz-grab", "Грейферные тележки", "product", "Тележки", "28.22", "ukz-site", [{"name": "Грузоподъёмность", "value": "до 5 т"}]),
   prod("ukz-parts", "Запчасти и детали", "product", "Запчасти", None, "ukz-site"),
   prod("ukz-service", "Сервис", "service", "Сервис", None, "ukz-site"),
 ],
})

# 4. ООО «КЗБИ»
COMPANIES.append({
 "id": "kzbi", "name": "ООО «Камышинский завод бурового инструмента»", "short": "КЗБИ",
 "legal_name": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ \"КАМЫШИНСКИЙ ЗАВОД БУРОВОГО ИНСТРУМЕНТА\"",
 "inn": "3436009350", "ogrn": "1023404963504", "kpp": "343601001", "reg_date": "1998-12-24",
 "legal_status": "Действующая", "region": "34", "city": "Камышин",
 "address": "403882, г. Камышин, территория Промзона, дом 10",
 "site": "https://kzbi.ru/", "phones": ["+7 (84457) 544 10"], "emails": ["kzbi@kzbi.ru"],
 "okved_main": "28.92", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Горное и металлургическое оборудование, инструмент",
 "description": None,
 "technologies": [
   {"name": "Штамповка на горизонтально-ковочных машинах ГКМ-250 и ГКМ-800", "source_id": "kzbi-site"},
   {"name": "Термическая и химико-термическая обработка", "source_id": "kzbi-site"},
   {"name": "Термообработка длинномерных изделий до 6 метров в вертикальных печах", "source_id": "kzbi-site"},
   {"name": "Газопламенная резка толстого листа по программе", "source_id": "kzbi-site"},
   {"name": "Механическая обработка металлов резанием", "source_id": "kzbi-site"},
   {"name": "Правка сортового металлопроката", "source_id": "kzbi-site"},
 ],
 "materials": [],
 "capacities": [{"text": "50+ тонн продукции в месяц", "value": 50, "qualifier": "более", "unit": "т/мес", "source_id": "kzbi-site"}],
 "sites": [], "certificates": [],
 "verification_status": "PARTIALLY_VERIFIED",
 "sources": [
   src("kzbi-site", "https://kzbi.ru/", "OFFICIAL_SITE", "Официальный сайт ООО «КЗБИ»", 1,
       ["название", "адрес", "телефон", "e-mail", "продукция", "услуги", "объём производства"]),
   src("kzbi-egrul", "https://www.1cont.ru/contragent/1023404963504", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [
   {"field": "Адрес", "values": [
      {"value": "403882, г. Камышин, территория Промзона, дом 10", "source_id": "kzbi-site"},
      {"value": "403874, г. Камышин, Промзона тер., влд. 10", "source_id": "kzbi-egrul"}],
    "note": "Почтовый индекс на сайте и в ЕГРЮЛ различается. Автоматический вывод не делается — требуется подтверждение у предприятия."}
 ],
 "products": [
   prod("kzbi-taphole", "Инструмент для вскрытия лёток доменной печи", "product", "Металлургический инструмент", None, "kzbi-site"),
   prod("kzbi-rods", "Штанги буровые, муфты соединительные, коронки для переносных пневматических перфораторов", "product", "Буровой инструмент", "28.92", "kzbi-site"),
   prod("kzbi-mandrels", "Оправки прошивные, раскатные, оправочные стержни и линейки для станов винтовой прокатки", "product", "Инструмент для трубного производства", "28.91", "kzbi-site"),
   prod("kzbi-catalyst", "Катализаторы", "product", "Химическая продукция", "20.59", "kzbi-site", desc="Раздел «Производство катализаторов» на сайте предприятия."),
   prod("kzbi-forging", "Штамповка на ГКМ-250 и ГКМ-800", "service", "Кузнечно-штамповочные услуги", "25.50", "kzbi-site"),
   prod("kzbi-heat", "Термическая и химико-термическая обработка", "service", "Термообработка", "25.61", "kzbi-site"),
   prod("kzbi-heatlong", "Термообработка длинномерных изделий до 6 м", "service", "Термообработка", "25.61", "kzbi-site", [{"name": "Длина изделия", "value": "до 6 м"}]),
   prod("kzbi-cut", "Раскрой толстого листа газопламенной резкой по программе", "service", "Металлообработка", "25.62", "kzbi-site"),
   prod("kzbi-machining", "Механическая обработка металлов резанием", "service", "Механообработка", "25.62", "kzbi-site"),
   prod("kzbi-straight", "Правка сортового металлопроката", "service", "Металлообработка", "25.62", "kzbi-site"),
 ],
})

# 5. ОАО «ЕПК Волжский»
COMPANIES.append({
 "id": "epkv", "name": "ОАО «ЕПК Волжский»", "short": "ЕПК Волжский",
 "legal_name": "ОТКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО \"ЕПК ВОЛЖСКИЙ\"",
 "inn": "3435052024", "ogrn": "1023402005582", "kpp": "343501001", "reg_date": "2001-09-13",
 "legal_status": "Действующая", "region": "34", "city": "Волжский",
 "address": "404112, г. Волжский, ул. Пушкина, д. 45",
 "site": "https://epkgroup.ru/", "phones": [], "emails": [],
 "okved_main": "28.15.1", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Подшипники",
 "description": None,
 "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "PARTIALLY_VERIFIED",
 "sources": [
   src("epkv-site", "https://epkgroup.ru/business/SOUT/SOUT_EPK_Volgsky/", "OFFICIAL_SITE", "Сайт группы ЕПК — страница ОАО «ЕПК Волжский»", 1, [],
       note="Сайт группы не ответил краулеру (robots.txt недоступен). Продукция требует проверки по официальному сайту.", status="ROBOTS_UNAVAILABLE"),
   src("epkv-egrul", "https://www.1cont.ru/contragent/1023402005582", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
   src("epkv-evpk", "https://evpk.ru/manufacturers/epk-vl", "OTHER", "Страница производителя на сайте подшипникового центра «ЕВПК»", 12,
       ["классы точности подшипников"]),
 ],
 "discrepancies": [],
 "products": [
   prod("epkv-bearings", "Подшипники шариковые и роликовые", "product", "Подшипники", "28.15", "epkv-egrul",
        [{"name": "Классы точности", "value": "2, 4 и 5-й (по данным ЕВПК)"}],
        desc="Вид продукции определён по основному ОКВЭД (28.15.1) и вторичному источнику; номенклатура на официальном сайте не проверена."),
 ],
})

# 6. АО «Завод «Метеор»
COMPANIES.append({
 "id": "meteor", "name": "АО «Завод «Метеор»", "short": "Метеор",
 "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"ЗАВОД \"МЕТЕОР\"",
 "inn": "3435000717", "ogrn": "1023402012050", "kpp": "343501001", "reg_date": "1992-06-08",
 "legal_status": "Действующая", "region": "34", "city": "Волжский",
 "address": "404122, г. Волжский, ул. Горького, д. 1",
 "site": "https://www.meteor.su/", "phones": ["+7 (8443) 34-26-94", "+7 (8443) 34-21-50 (отдел сбыта)"], "emails": ["info@meteor.su"],
 "okved_main": "26.11.2", "okved_extra": None,
 "industry": "Радиоэлектроника", "subindustry": "Пьезоэлектрические приборы",
 "description": "Основан в 1959 году; с 2009 года — в составе госкорпорации «Ростехнологии» (по данным сайта предприятия).",
 "technologies": [], "materials": [],
 "capacities": [{"text": "Исторический максимум (1990 г.): резонаторов 6,8 млн шт. и фильтров 300 тыс. шт. в год", "value": None, "unit": None, "historical": True, "source_id": "meteor-site"}],
 "sites": [], "certificates": [],
 "verification_status": "PARTIALLY_VERIFIED",
 "sources": [
   src("meteor-site", "https://www.meteor.su/about", "OFFICIAL_SITE", "Официальный сайт завода «Метеор» — «О предприятии»", 1,
       ["адрес", "телефоны", "e-mail", "виды продукции", "история"]),
   src("meteor-catalog", "https://www.meteor.su/", "OFFICIAL_CATALOG", "Официальный сайт завода «Метеор» — каталог", 2, ["разделы каталога"]),
   src("meteor-egrul", "https://www.1cont.ru/contragent/1023402012050", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [
   {"field": "Организационно-правовая форма", "values": [
      {"value": "Открытое акционерное общество «Завод «Метеор»", "source_id": "meteor-site"},
      {"value": "Акционерное общество \"Завод \"Метеор\"", "source_id": "meteor-egrul"}],
    "note": "На сайте указана прежняя форма (ОАО). В карточке используется наименование из ЕГРЮЛ."},
   {"field": "Кварцевые фильтры", "values": [
      {"value": "Указаны среди видов продукции", "source_id": "meteor-site"},
      {"value": "Отсутствуют в разделах каталога", "source_id": "meteor-catalog"}],
    "note": "Наличие фильтров в текущей номенклатуре требует подтверждения."},
 ],
 "products": [
   prod("meteor-res", "Кварцевые резонаторы", "product", "Пьезоэлектрические компоненты", "26.11", "meteor-catalog", [{"name": "Корпуса", "value": "SMD и DIP"}]),
   prod("meteor-xo", "Тактовые кварцевые генераторы", "product", "Кварцевые генераторы", "26.11", "meteor-catalog"),
   prod("meteor-vcxo", "Управляемые напряжением кварцевые генераторы", "product", "Кварцевые генераторы", "26.11", "meteor-catalog"),
   prod("meteor-tcxo", "Термокомпенсированные кварцевые генераторы", "product", "Кварцевые генераторы", "26.11", "meteor-catalog"),
   prod("meteor-mw", "СВЧ-генераторы", "product", "Кварцевые генераторы", "26.11", "meteor-catalog"),
   prod("meteor-filters", "Кварцевые фильтры", "product", "Пьезоэлектрические компоненты", "26.11", "meteor-site", desc="Требует подтверждения: нет в разделах каталога."),
 ],
})

# 7. АО «Корпорация Красный Октябрь»
COMPANIES.append({
 "id": "ko", "name": "АО «Корпорация Красный Октябрь»", "short": "Красный Октябрь",
 "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"КОРПОРАЦИЯ КРАСНЫЙ ОКТЯБРЬ\"",
 "inn": "3459080648", "ogrn": "1203400006072", "kpp": "345901001", "reg_date": "2020-06-08",
 "legal_status": "Действующая", "region": "34", "city": "Волгоград",
 "address": "400007, г. Волгоград, пр-кт им. В.И. Ленина, д. 110",
 "site": "https://www.vmzko.ru/", "phones": ["+7 800 301 33 35 (отдел продаж)", "+7 844 274 87 77 (справочная)"],
 "emails": ["sales@vmzko.ru", "info@vmzko.ru"],
 "okved_main": "24.10.6", "okved_extra": None,
 "industry": "Металлургия", "subindustry": "Качественные и специальные стали, прокат",
 "description": "По данным сайта: более 500 профилей проката и около 1000 марок стали.",
 "technologies": [
   {"name": "Производство стали", "source_id": "ko-site"},
   {"name": "Прокатное производство", "source_id": "ko-site"},
   {"name": "Отделочное производство", "source_id": "ko-site"},
 ],
 "materials": [{"name": n, "source_id": "ko-site"} for n in ["40ХН2МА", "40Х", "08Х22Н6Т (ЭП53)", "ТМК-С", "45Г17Ю3"]],
 "capacities": [], "sites": [],
 "certificates": [{"name": "ISO 9001:2015", "source_id": "ko-site"}, {"name": "ISO 14001:2015", "source_id": "ko-site"}],
 "verification_status": "VERIFIED",
 "sources": [
   src("ko-site", "https://www.vmzko.ru/", "OFFICIAL_SITE", "Официальный сайт АО «Корпорация Красный Октябрь»", 1,
       ["адрес", "телефоны", "e-mail", "продукция", "марки стали", "сертификаты", "виды производства"]),
   src("ko-egrul", "https://www.1cont.ru/contragent/1203400006072", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "КПП", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [
   {"field": "Одноимённые юрлица", "values": [
      {"value": "В реестре также есть ООО «Корпорация Красный Октябрь» (ИНН 3443141359)", "source_id": "ko-egrul"}],
    "note": "При заключении договора сверяйте ИНН. В карточке — АО, ИНН 3459080648, реквизиты которого совпадают с адресом сайта."}
 ],
 "products": [
   prod("ko-coldsheet", "Прокат холоднокатаный тонколистовой", "product", "Листовой прокат", "24.10", "ko-site"),
   prod("ko-round", "Прокат горячекатаный круглого сечения", "product", "Сортовой прокат", "24.10", "ko-site"),
   prod("ko-plate", "Прокат горячекатаный толстолистовой", "product", "Листовой прокат", "24.10", "ko-site"),
   prod("ko-billet", "Трубная заготовка", "product", "Заготовка", "24.10", "ko-site"),
   prod("ko-square", "Прокат горячекатаный квадратного сечения (блюм + квадратная заготовка)", "product", "Заготовка", "24.10", "ko-site"),
   prod("ko-thinsheet", "Прокат горячекатаный тонколистовой", "product", "Листовой прокат", "24.10", "ko-site"),
 ],
})
for p in COMPANIES[-1]["products"]:
    p["materials"] = [{"name": "Сталь (качественные, нержавеющие, жаропрочные марки — по данным сайта)", "source_id": "ko-site"}]

# 8. ООО «ВЗМК»
COMPANIES.append({
 "id": "vzmk", "name": "ООО «Волгоградский завод металлоконструкций и котельного оборудования»", "short": "ВЗМК",
 "legal_name": None, "inn": None, "ogrn": None, "kpp": None, "reg_date": None,
 "legal_status": None, "region": "34", "city": "Волгоград",
 "address": "400031, г. Волгоград, ул. Бахтурова, 4Г",
 "site": None, "phones": ["+7 (8442) 63-42-10", "+7 (8442) 63-42-35"], "emails": ["vzmk@bk.ru"],
 "okved_main": None, "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Металлоконструкции, резервуары, котельное оборудование",
 "description": "Создан в 1991 году (по данным индустриального парка).",
 "technologies": [
   {"name": "Вальцовка (листогибочные вальцы)", "source_id": "vzmk-park"},
   {"name": "Автоматическая сварка под флюсом", "source_id": "vzmk-park"},
   {"name": "Полуавтоматическая и автоматическая сварка", "source_id": "vzmk-park"},
   {"name": "Фрезерная и токарная обработка", "source_id": "vzmk-park"},
   {"name": "Трубогибка", "source_id": "vzmk-park"},
 ],
 "materials": [], "capacities": [],
 "sites": [{"name": "Производственная площадка", "type": "PLANT", "address": "400031, г. Волгоград, ул. Бахтурова, 4Г", "area": "4,6 га", "source_id": "vzmk-park"}],
 "certificates": [],
 "verification_status": "UNVERIFIED",
 "sources": [
   src("vzmk-park", "https://russiaindustrialpark.ru/residents/917", "REGIONAL_CATALOG", "Каталог резидентов индустриальных парков", 8,
       ["название", "адрес", "телефоны", "e-mail", "продукция", "оборудование", "площадь"]),
 ],
 "discrepancies": [
   {"field": "Реквизиты", "values": [], "note": "ИНН и официальный сайт не найдены в открытых источниках. Предприятие не может быть сопоставлено с ЕГРЮЛ до подтверждения реквизитов."}
 ],
 "products": [
   prod("vzmk-tanks", "Резервуары вертикальные и горизонтальные", "product", "Резервуары", "25.29", "vzmk-park"),
   prod("vzmk-chimneys", "Стальные дымовые трубы", "product", "Металлоконструкции", "25.11", "vzmk-park"),
   prod("vzmk-steel", "Строительные и производственные металлоконструкции", "product", "Металлоконструкции", "25.11", "vzmk-park"),
   prod("vzmk-boiler", "Металлургическое и котельное оборудование", "product", "Котельное оборудование", None, "vzmk-park"),
 ],
})

# 9. ОАО «Волжский абразивный завод»
COMPANIES.append({
 "id": "vabz", "name": "ОАО «Волжский абразивный завод»", "short": "Волжский абразивный завод",
 "legal_name": "ОТКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО \"ВОЛЖСКИЙ АБРАЗИВНЫЙ ЗАВОД\"",
 "inn": "3435000467", "ogrn": "1023402019596", "kpp": None, "reg_date": "1991-02-14",
 "legal_status": "Действующая", "region": "34", "city": "Волжский",
 "address": "404119, г. Волжский, ул. им. Ф.Г. Логинова, д. 169",
 "site": "https://vabz.ru/", "phones": [], "emails": [],
 "okved_main": "20.13", "okved_extra": None,
 "industry": "Химическая промышленность", "subindustry": "Абразивы, карбид кремния, огнеупоры",
 "description": "Основан в 1961 году. По заявлению предприятия — единственный производитель карбида кремния в России. Член FEPA и SiCMa.",
 "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "VERIFIED",
 "sources": [
   src("vabz-site", "https://vabz.ru/", "OFFICIAL_SITE", "Официальный сайт Волжского абразивного завода", 1,
       ["название", "продукция", "год основания", "членство в ассоциациях"]),
   src("vabz-egrul", "https://www.1cont.ru/contragent/1023402019596", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [],
 "products": [
   prod("vabz-sic-black", "Карбид кремния чёрный", "product", "Шлифматериалы", "20.13", "vabz-site"),
   prod("vabz-sic-green", "Карбид кремния зелёный", "product", "Шлифматериалы", "20.13", "vabz-site"),
   prod("vabz-tools", "Абразивный инструмент на керамической и бакелитовой связках", "product", "Абразивный инструмент", "23.91", "vabz-site"),
   prod("vabz-refr", "Огнеупоры", "product", "Огнеупоры", "23.20", "vabz-site"),
 ],
})

# 10. Волжский трубный завод
COMPANIES.append({
 "id": "vtz", "name": "Волжский трубный завод (филиал ПАО «ТМК»)", "short": "ВТЗ",
 "legal_name": "ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО \"ТРУБНАЯ МЕТАЛЛУРГИЧЕСКАЯ КОМПАНИЯ\"",
 "inn": "7710373095", "ogrn": "1027739217758", "kpp": None, "reg_date": None,
 "legal_status": "Действующая (головная организация)", "region": "34", "city": "Волжский",
 "address": "404119, г. Волжский, пр-т Металлургов, д. 6",
 "site": "https://vtz.tmk-group.ru/",
 "phones": ["+7 (8443) 55-10-55", "+7 (8443) 55-16-34 (продажи)", "+7 (8443) 55-17-70 (качество)"], "emails": ["vtz@vtz.ru"],
 "okved_main": "46.72.2", "okved_extra": None,
 "industry": "Металлургия", "subindustry": "Трубное производство",
 "description": None,
 "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "PARTIALLY_VERIFIED",
 "sources": [
   src("vtz-site", "https://vtz.tmk-group.ru/vtz_factory_contacts", "OFFICIAL_SITE", "Официальный сайт ВТЗ — контакты", 1, ["наименование (филиал ПАО «ТМК»)", "адрес", "телефоны", "e-mail"]),
   src("vtz-prod", "https://vtz.tmk-group.ru/index.php", "OFFICIAL_SITE", "Официальный сайт ВТЗ — продукция", 1, ["виды труб", "отрасли применения"]),
   src("vtz-egrul", "https://www.1cont.ru/contragent/1027739217758", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ о ПАО «ТМК» (агрегатор 1cont.ru)", 5, ["юр. название", "ИНН", "ОГРН", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [
   {"field": "Юридическое лицо", "values": [
      {"value": "Филиал ПАО «ТМК» Волжский трубный завод", "source_id": "vtz-site"},
      {"value": "В реестре также есть АО «ВТЗ» (ИНН 3435900186), г. Волжский", "source_id": "vtz-egrul"}],
    "note": "Сторону договора для конкретной поставки нужно уточнить у предприятия. ОКВЭД в карточке — головной организации, не производственной площадки."}
 ],
 "products": [
   prod("vtz-seamless", "Трубы бесшовные", "product", "Трубы", "24.20", "vtz-prod", desc="Для нефтегазовой, химической, нефтехимической, автомобильной отраслей."),
   prod("vtz-welded", "Трубы электросварные спиральношовные и прямошовные большого диаметра", "product", "Трубы", "24.20", "vtz-prod", desc="Для строительства газопроводов."),
 ],
})

# 11. ООО «ВЗБТ» — ликвидировано
COMPANIES.append({
 "id": "vzbt", "name": "ООО «Волгоградский завод буровой техники»", "short": "ВЗБТ",
 "legal_name": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ \"ВОЛГОГРАДСКИЙ ЗАВОД БУРОВОЙ ТЕХНИКИ\"",
 "inn": "3443144920", "ogrn": "1203400005005", "kpp": None, "reg_date": "2020-04-28",
 "legal_status": "Ликвидировано 15.10.2024", "region": "34", "city": "Волгоград",
 "address": "400048, г. Волгоград, ш. Авиаторов, д. 16",
 "site": None, "phones": [], "emails": [],
 "okved_main": "28.92", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Буровое оборудование",
 "description": None, "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "OUTDATED",
 "sources": [
   src("vzbt-egrul", "https://www.1cont.ru/contragent/1203400005005", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "дата регистрации", "юр. адрес", "статус: ликвидировано", "основной ОКВЭД"]),
 ],
 "discrepancies": [{"field": "Статус", "values": [], "note": "Юрлицо ликвидировано 15.10.2024. Не показывается в основном поиске; карточка сохранена для истории изменений."}],
 "products": [],
})

# 12. АО «ГМС Ливгидромаш» — вне пилотного региона (для сравнения альтернатив)
COMPANIES.append({
 "id": "livgm", "name": "АО «ГМС Ливгидромаш»", "short": "ГМС Ливгидромаш",
 "legal_name": "АКЦИОНЕРНОЕ ОБЩЕСТВО \"ГМС ЛИВГИДРОМАШ\"",
 "inn": "5702000265", "ogrn": "1025700514476", "kpp": None, "reg_date": "1992-09-30",
 "legal_status": "Действующая", "region": "57", "city": "Ливны",
 "address": "303851, Орловская обл., г. Ливны, ул. Мира, д. 231",
 "site": "https://www.hms-livgidromash.ru/", "phones": [], "emails": [],
 "okved_main": "28.13", "okved_extra": None,
 "industry": "Машиностроение", "subindustry": "Насосное оборудование",
 "description": "По заявлению предприятия — производит насосы более 70 лет.",
 "technologies": [], "materials": [], "capacities": [], "sites": [], "certificates": [],
 "verification_status": "VERIFIED",
 "sources": [
   src("livgm-site", "https://www.hms-livgidromash.ru/", "OFFICIAL_SITE", "Официальный сайт АО «ГМС Ливгидромаш»", 1, ["название", "город", "продукция"]),
   src("livgm-egrul", "https://www.1cont.ru/contragent/1025700514476", "EGRUL_AGGREGATOR", "Сведения ЕГРЮЛ (агрегатор 1cont.ru)", 5,
       ["юр. название", "ИНН", "ОГРН", "дата регистрации", "юр. адрес", "статус", "основной ОКВЭД"]),
 ],
 "discrepancies": [],
 "products": [
   prod("livgm-centrifugal", "Насосы центробежные (консольные, двустороннего входа, погружные, многоступенчатые, вихревые)", "product", "Насосы", "28.13", "livgm-site"),
   prod("livgm-gear", "Насосы шестерённые", "product", "Насосы", "28.13", "livgm-site"),
   prod("livgm-screw", "Насосы винтовые", "product", "Насосы", "28.13", "livgm-site"),
   prod("livgm-vacuum", "Насосы вакуумные", "product", "Насосы", "28.13", "livgm-site"),
   prod("livgm-auto", "Насосное оборудование и системы автоматизации", "product", "Насосы", "28.13", "livgm-site"),
 ],
})

# ---------- потенциальные связи между предприятиями (ни одна не подтверждена) ----------
RELATIONS = [
 {"id": "r1", "from": "ko", "from_product": "ko-billet", "to": "vtz", "to_product": "vtz-seamless", "type": "POTENTIAL_RELATION",
  "basis": "Трубная заготовка (ko-site) — входной материал для бесшовных труб (vtz-prod). Факт поставок не подтверждён."},
 {"id": "r2", "from": "ko", "from_product": "ko-round", "to": "kzbi", "to_product": "kzbi-rods", "type": "INFERRED_RELATION",
  "basis": "Сортовой круглый прокат может использоваться для буровых штанг. Вывод системы по видам продукции."},
 {"id": "r3", "from": "ko", "from_product": "ko-plate", "to": "vnm", "to_product": "vnm-vessels", "type": "INFERRED_RELATION",
  "basis": "Толстолистовой прокат может использоваться для сосудов под давлением. Вывод системы по видам продукции."},
 {"id": "r4", "from": "ko", "from_product": "ko-plate", "to": "vzmk", "to_product": "vzmk-tanks", "type": "INFERRED_RELATION",
  "basis": "Толстолистовой прокат может использоваться для резервуаров. Вывод системы."},
 {"id": "r5", "from": "epkv", "from_product": "epkv-bearings", "to": "ukz", "to_product": "ukz-bridge", "type": "INFERRED_RELATION",
  "basis": "Подшипники — комплектующие для механизмов кранов. Вывод системы."},
 {"id": "r6", "from": "vabz", "from_product": "vabz-tools", "to": "kzbi", "to_product": "kzbi-machining", "type": "INFERRED_RELATION",
  "basis": "Абразивный инструмент применяется в механической обработке. Вывод системы."},
 {"id": "r7", "from": "kzbi", "from_product": "kzbi-mandrels", "to": "vtz", "to_product": "vtz-seamless", "type": "POTENTIAL_RELATION",
  "basis": "Оправки для станов винтовой прокатки (kzbi-site) применяются в производстве бесшовных труб (vtz-prod). Факт поставок не подтверждён."},
]

# ---------- журнал обхода источников за 24.09.2026 (фактические результаты запросов) ----------
CRAWL_LOG = [
 ("https://soyuzmash.ru/", "OK", "Структура меню, контакты — референс дизайна"),
 ("https://soyuzmash.ru/local/templates/main/template_styles.css", "HTTP_404", "Стили сайта недоступны"),
 ("https://www.vnm.ru/", "OK", "Продукция, адрес, e-mail"),
 ("https://www.1cont.ru/contragent/1023404238384", "OK", "ЕГРЮЛ: Волгограднефтемаш"),
 ("http://vzsm34.ru/", "REDIRECT_LOOP", "Сайт ВЗСМ: цикл https→http"),
 ("https://anosudprom.ru/volgogradskij-zavod-sudovogo-mashinostroeniya/", "OK", "ВЗСМ: отраслевой каталог"),
 ("https://www.1cont.ru/contragent/1193443012553", "OK", "ЕГРЮЛ: ВЗСМ"),
 ("https://www.rusprofile.ru/id/11904377", "HTTP_403", "Агрегатор закрыт для краулера — источник отключён"),
 ("https://urupinsk-kran.ru/", "OK", "Продукция, грузоподъёмность, мощность"),
 ("https://www.1cont.ru/contragent/1023405761510", "OK", "ЕГРЮЛ: УКЗ"),
 ("https://kzbi.ru/", "OK", "Продукция, услуги, объём производства"),
 ("https://www.1cont.ru/contragent/1023404963504", "OK", "ЕГРЮЛ: КЗБИ"),
 ("https://epkgroup.ru/business/SOUT/SOUT_EPK_Volgsky/", "ROBOTS_UNAVAILABLE", "robots.txt недоступен — обход не выполнялся"),
 ("https://www.1cont.ru/contragent/1023402005582", "OK", "ЕГРЮЛ: ЕПК Волжский"),
 ("https://evpk.ru/manufacturers/epk-vl", "OK", "ЕПК: вторичный источник"),
 ("https://www.meteor.su/about", "OK", "Метеор: о предприятии"),
 ("https://www.meteor.su/", "OK", "Метеор: каталог"),
 ("https://www.1cont.ru/contragent/1023402012050", "OK", "ЕГРЮЛ: Метеор"),
 ("https://www.vmzko.ru/", "OK", "Красный Октябрь: продукция, марки, сертификаты"),
 ("https://www.1cont.ru/contragent/1203400006072", "OK", "ЕГРЮЛ: Корпорация Красный Октябрь"),
 ("https://russiaindustrialpark.ru/residents/917", "OK", "ВЗМК: каталог индустриальных парков"),
 ("https://vabz.ru/", "OK", "Волжский абразивный завод"),
 ("https://www.1cont.ru/contragent/1023402019596", "OK", "ЕГРЮЛ: ВАЗ"),
 ("https://vtz.tmk-group.ru/vtz_factory_contacts", "OK", "ВТЗ: контакты"),
 ("https://vtz.tmk-group.ru/index.php", "OK", "ВТЗ: продукция"),
 ("https://www.1cont.ru/contragent/1027739217758", "OK", "ЕГРЮЛ: ПАО ТМК"),
 ("https://www.1cont.ru/contragent/1203400005005", "OK", "ЕГРЮЛ: ВЗБТ (ликвидировано)"),
 ("https://market.neftegaz.ru/catalog/company/349214-volgogradskiy-zavod-burovoy-tekhniki/", "HTTP_468", "Отраслевой каталог закрыт для краулера"),
 ("http://economics.volgograd.ru/foreign/info/vabz.php", "ROBOTS_UNAVAILABLE", "Региональный портал: таймаут robots.txt"),
 ("https://www.hms-livgidromash.ru/", "OK", "Ливгидромаш: продукция"),
 ("https://www.1cont.ru/contragent/1025700514476", "OK", "ЕГРЮЛ: Ливгидромаш"),
]

def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def synced_data() -> list[str]:
    """Что в data/ появилось после первичного сбора и пропадёт при пересборке: компании и журналы синхронизации."""
    found = []
    for p in glob.glob(os.path.join(ROOT, "companies", "*", "company.json")):
        with open(p, encoding="utf-8") as f:
            if json.load(f).get("origin") == "registry_sync":
                found.append(os.path.basename(os.path.dirname(p)))
    if os.path.isdir(os.path.join(ROOT, "sync")):
        found.append("sync/")
    return found


def main():
    # Скрипт пересобирает data/ с нуля. Компании, добавленные python -m sync, и журналы синхронизации
    # он не воспроизводит, поэтому без --force отказывается их удалять
    lost = synced_data()
    if lost and "--force" not in sys.argv:
        sys.exit(f"data/ содержит результаты синхронизации с реестрами ({len(lost)}: {', '.join(lost[:5])}{' …' if len(lost) > 5 else ''}).\n"
                 "Пересборка удалит их. Запустите с --force, если это нужно, и затем python -m sync, чтобы вернуть компании.")
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    for c in COMPANIES:
        cid = c["id"]
        comp = {k: v for k, v in c.items() if k not in ("products", "sources")}
        w(f"{ROOT}/companies/{cid}/company.json", comp)
        prods = [dict(p, company_id=cid) for p in c["products"]]
        w(f"{ROOT}/companies/{cid}/products.json", prods)
        w(f"{ROOT}/companies/{cid}/sources.json", c["sources"])
        for p in prods:
            w(f"{ROOT}/products/{p['id']}.json", p)
    w(f"{ROOT}/okved/okved.json", [{"code": k, "name": v} for k, v in OKVED.items()])
    w(f"{ROOT}/okpd2/okpd2.json", [{"code": k, "name": v} for k, v in OKPD2.items()])
    w(f"{ROOT}/regions/regions.json", list(REGIONS.values()))
    w(f"{ROOT}/regions/cities.json", [{"city": k, "lat": v[0], "lon": v[1], "note": "центр города"} for k, v in CITIES.items()])
    w(f"{ROOT}/relations/relations.json", RELATIONS)
    mats = sorted({m["name"] for c in COMPANIES for m in c["materials"]})
    w(f"{ROOT}/materials/materials.json", mats)
    techs = sorted({t["name"] for c in COMPANIES for t in c["technologies"]})
    w(f"{ROOT}/technologies/technologies.json", techs)
    w(f"{ROOT}/warehouses/README.json", {"note": "Складские остатки ни одним предприятием не опубликованы. Записи появятся после подтверждения предприятием."})
    allsrc = [dict(s, company_id=c["id"]) for c in COMPANIES for s in c["sources"]]
    w(f"{ROOT}/sources/sources.json", allsrc)
    w(f"{ROOT}/sources/crawl_log_2026-09-24.json", [{"url": u, "status": s, "note": n, "fetched_at": D} for u, s, n in CRAWL_LOG])
    # единый бандл для фронтенда
    bundle = {"generated_at": D, "companies": COMPANIES, "okved": OKVED, "okpd2": OKPD2, "regions": REGIONS,
              "cities": CITIES, "relations": RELATIONS,
              "crawl_log": [{"url": u, "status": s, "note": n, "fetched_at": D} for u, s, n in CRAWL_LOG]}
    w(os.path.join(ROOT, "..", "site", "data.json"), bundle)
    print(len(COMPANIES), "companies,", sum(len(c["products"]) for c in COMPANIES), "products,", len(allsrc), "sources")

if __name__ == "__main__":
    main()
